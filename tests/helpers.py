# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: helpers.py, Version: 0.9.9 (2026-07-26)

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

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "device_sentinel"


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
