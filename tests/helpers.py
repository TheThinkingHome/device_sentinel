# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: helpers.py, Version: 0.21.11 (2026-09-16)

"""Shared test helpers, one canonical version of each.

The suite grew a separate copy of these in almost every file, and the
copies drifted: ten spellings of setting up the integration, nine of
registering a device. That made a test's behaviour depend on which
copy its file happened to hold, which is the opposite of what a test
should be. These are the reconciled versions, each a superset of the
copies it replaces: the extra parameters default to the simplest case,
so a caller that wants the plain behaviour writes nothing extra, and a
caller that wants a variant asks for it by name.

Every helper here is a plain function, imported, not a fixture, so a
call site reads the same as it always did (`await setup_entry(hass)`),
only the import changes. Fixtures that every test shares stay in
conftest.py; these are the building blocks a test calls directly.
"""

from __future__ import annotations

from awesomeversion import AwesomeVersion

from custom_components.device_sentinel.const import OPTIONS_MINOR_VERSION
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "device_sentinel"

# From Home Assistant 2026.8 a device belongs to exactly one config
# entry, and asking for a second one is refused. The suite runs on two
# harnesses until the minimum version reaches 2026.8, and a test that
# needs a device with two owners can only be built on the older one.
MULTI_OWNER_POSSIBLE = AwesomeVersion(HA_VERSION) < AwesomeVersion("2026.8.0")
MULTI_OWNER_GONE = (
    "a device can belong to only one config entry from Home Assistant "
    "2026.8; this case is proven on the 2026.5 harness"
)


async def setup_entry(
    hass: HomeAssistant, options: dict | None = None
) -> MockConfigEntry:
    """Set up the integration and return its config entry.

    options defaults to none, so a test that does not care about
    settings calls setup_entry(hass) and gets the plain integration;
    a test that needs a threshold or a target passes options.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Device Sentinel",
        data={},
        options=options or {},
        # A fresh install is created at the current version and runs
        # no migration, which is what a test writing today's option
        # names is describing. Left at the default, every entry here
        # would arrive looking like a 0.16.3 upgrade and the chain
        # would rename the names the test just wrote.
        version=1,
        minor_version=OPTIONS_MINOR_VERSION,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def setup_coordinator(
    hass: HomeAssistant, options: dict | None = None
):
    """Set up the integration and return its coordinator.

    The coordinator is entry.runtime_data; most tests want it rather
    than the entry, so this is the common entry point. A test that
    needs the entry itself (to reload or read its id) calls
    setup_entry instead.
    """
    entry = await setup_entry(hass, options)
    return entry.runtime_data


def register_device(
    hass: HomeAssistant,
    uid: str,
    name: str | None = None,
    entity_count: int = 1,
    entity_domain: str = "sensor",
):
    """Create a real registry device with N entities under a source.

    Returns (device, [entity_id, ...]). A device must exist in the
    registry or setup prunes its storage record as an orphan, so tests
    that drive a device through the coordinator register it here first.

    name defaults to the uid, entity_count to one, the entity domain
    to sensor. The return is always the device and the list of entity
    ids; a caller wanting the single common case reads
    device, (eid,) = ... or indexes [0].
    """
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name or uid,
    )
    entity_ids = []
    for index in range(entity_count):
        suffix = uid if entity_count == 1 else f"{uid}_{index}"
        entry = er.async_get(hass).async_get_or_create(
            entity_domain,
            "test",
            suffix,
            device_id=device.id,
            config_entry=source,
        )
        entity_ids.append(entry.entity_id)
    return device, entity_ids


def register_fleet(
    hass: HomeAssistant,
    source: MockConfigEntry,
    count: int,
    prefix: str = "dev",
):
    """Create count devices under one shared source entry.

    Used by the storm tests, which need a whole fleet under a single
    config entry so the entry can be judged a synchronized poller. The
    source is passed in rather than made here, because those tests set
    its domain deliberately (poller, zigbee_like) and then assert on
    it. Returns a list of (device, entity_id).
    """
    fleet = []
    for index in range(count):
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("test", f"{prefix}{index}")},
            name=f"{prefix} {index}",
        )
        entry = er.async_get(hass).async_get_or_create(
            "sensor",
            "test",
            f"{prefix}_uid{index}",
            device_id=device.id,
            config_entry=source,
        )
        fleet.append((device, entry.entity_id))
    return fleet


async def setup_coordinator_flat_line(
    hass: HomeAssistant, options: dict | None = None
):
    """Return a coordinator whose danger line sits on the floor.

    Many signal tests want the line to equal the floor so the floor's
    own arithmetic can be asserted without the margin's share of the
    band in the way. Until ruling #311 they got that by saving a
    margin of zero; the margin is a constant now, so they patch the
    accessor instead. The patch is the smallest thing that keeps
    those tests asking what they were written to ask.
    """
    coordinator = await setup_coordinator(hass, options)
    coordinator._signal_margin = lambda: 0.0
    return coordinator


def flat_schema(schema) -> dict:
    """Return a form's fields with section nesting removed.

    Ruling #314 moved every exclude picker into a section, so a test
    reading `result["data_schema"].schema` now meets a `section`
    object where it used to meet a selector. The nesting is a way of
    drawing the screen and not a change to what is stored, so a test
    asking what a picker offers should not have to know which section
    holds it.
    """
    from homeassistant.data_entry_flow import section as _section

    flat = {}
    for key, value in schema.items():
        if isinstance(value, _section):
            flat.update(flat_schema(value.schema.schema))
        else:
            flat[key] = value
    return flat


def nest_for(step: str, payload: dict) -> dict:
    """Return a submit payload with the excludes under their section.

    The four sectioned steps take their exclude picks nested (ruling
    #314) and store them flat. A test that knows the flat keys can
    hand them here rather than restating the section layout.
    """
    sections = {
        "battery": ("battery_muting", "battery_excluded_"),
        "signal": ("signal_muting", "signal_excluded_"),
        "freeze": ("freeze_muting", "freeze_excluded_"),
        "exclusions": ("exclusions", "excluded_"),
    }
    if step not in sections:
        return dict(payload)
    name, prefix = sections[step]
    loose, nested = {}, {}
    for key, value in payload.items():
        if key.startswith(prefix):
            nested[key] = value
        else:
            loose[key] = value
    loose[name] = nested
    return loose


def add_mac(hass: HomeAssistant, device, mac: str):
    """Give a registry device one more MAC connection.

    Home Assistant 2026.9 deprecated `merge_connections`, and from code
    it cannot tie to an integration a deprecated call raises. Passing
    the whole set as `new_connections` is the replacement it names, and
    it behaves the same on every harness the suite runs on.
    """
    registry = dr.async_get(hass)
    current = registry.async_get(device.id)
    connections = set(current.connections) if current else set()
    connections.add((dr.CONNECTION_NETWORK_MAC, mac))
    return registry.async_update_device(
        device.id, new_connections=connections
    )


def devices_of_entry(hass: HomeAssistant, entry_id: str) -> list:
    """Return the registry devices a config entry owns.

    Reading `registry.devices` as a mapping is deprecated from 2026.9,
    and iterating it yields entries only from 2026.9. The lookup by
    config entry reads the same on every harness.
    """
    return dr.async_entries_for_config_entry(dr.async_get(hass), entry_id)


def record_events(hass: HomeAssistant, event_type: str) -> list:
    """Record the data of every event of one type, in firing order.

    A plain function or lambda passed to `hass.bus.async_listen` is not
    a callback, so Home Assistant runs it as a job off the event loop,
    and a burst of events can be recorded out of order. Measured on 16
    September: fifty down and up pairs arrived interleaved in up to
    eleven runs of twenty. A callback runs in the loop, in firing
    order, which is the order a test about events needs.
    """
    seen: list = []

    @callback
    def _record(event: Event) -> None:
        seen.append(dict(event.data))

    hass.bus.async_listen(event_type, _record)
    return seen


def record_labelled(hass: HomeAssistant, labels: dict[str, str]) -> list:
    """Record several event types into one list, in firing order.

    `labels` maps each event type to the word stored beside its data,
    so a test about pairing reads `("down", {...})` then
    `("restored", {...})`. Ordered for the reason `record_events` gives.
    """
    seen: list = []
    for event_type, label in labels.items():

        @callback
        def _record(event: Event, _label: str = label) -> None:
            seen.append((_label, dict(event.data)))

        hass.bus.async_listen(event_type, _record)
    return seen
