# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v080_contact_clock.py, Version: 0.8.0 (2026-07-23)

"""0.8.0 tests: the clock records contact, not arrival.

The integration found each device's last-contact entity, used it once
to seed a clock, and then ignored it for the life of the device,
stamping the moment a payload arrived instead. A republish therefore
advanced the clock and erased the silence behind it, which is why
three quiet devices were flagged night after night while their
learned baselines described the interval between the nightly reboot
and the household waking. Where the protocol keeps that record we now
read it every time; where it does not, the moment we heard something
is the only evidence there is and it counts.
"""

from datetime import timedelta

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_INCIDENTS,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DEV_TODAY_MAX,
    FREEZE_CATEGORY_FROZEN,
    INC_CAUSE,
    LEGACY_CAUSE_UNOBSERVED,
    RECOVERY_CAUSE_UNOBSERVED,
)

DOMAIN = "device_sentinel"


def _register(hass, uid, name, with_contact=True):
    """Register a device, optionally with a last_seen entity."""
    source = MockConfigEntry(domain="test", title=f"Source {uid}")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    reg = er.async_get(hass)
    plain = reg.async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    contact = None
    if with_contact:
        contact = reg.async_get_or_create(
            "sensor", "test", f"{uid}_last_seen",
            device_id=device.id, config_entry=source,
            original_name="Last seen",
            suggested_object_id=f"{uid}_last_seen",
        ).entity_id
    return device, plain.entity_id, contact, source


async def _coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _iso(offset_seconds: float = 0.0) -> str:
    return (
        dt_util.utcnow() + timedelta(seconds=offset_seconds)
    ).isoformat()


def _record(coord, device_id):
    return coord.data[DATA_DEVICES][device_id]


# --------------------------------------------- the contact clock

async def test_contact_entity_is_found_and_used(hass: HomeAssistant):
    device, _entity, contact, _src = _register(hass, "c1", "Zigbee Thing")
    coord = await _coordinator(hass)
    assert device.id in coord._last_seen_entity
    assert coord._last_seen_entity[device.id] == contact


async def test_a_republish_does_not_advance_the_clock(
    hass: HomeAssistant, freezer
):
    """The heart of it. A replayed payload carries the coordinator's
    old reading, so the silence behind it keeps running."""
    device, entity_id, contact, _src = _register(hass, "c2", "Republished")
    coord = await _coordinator(hass)
    coord._grace_until = 0.0

    heard = _iso()
    hass.states.async_set(contact, heard)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    first = _record(coord, device.id)[DEV_LAST_ACTIVITY]
    assert first is not None

    # An hour later the payload is replayed: same last_seen value.
    freezer.tick(timedelta(hours=1))
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()
    assert _record(coord, device.id)[DEV_LAST_ACTIVITY] == first
    assert _record(coord, device.id)[DEV_TODAY_MAX] is None


async def test_a_genuine_report_advances_and_learns(
    hass: HomeAssistant, freezer
):
    device, entity_id, contact, _src = _register(hass, "c3", "Genuine")
    coord = await _coordinator(hass)
    coord._grace_until = 0.0

    hass.states.async_set(contact, _iso())
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    first = _record(coord, device.id)[DEV_LAST_ACTIVITY]

    freezer.tick(timedelta(hours=2))
    hass.states.async_set(contact, _iso())
    await hass.async_block_till_done()
    record = _record(coord, device.id)
    assert record[DEV_LAST_ACTIVITY] > first
    assert record[DEV_TODAY_MAX] == pytest.approx(7200, abs=5)


async def test_an_unavailable_contact_entity_stops_the_clock(
    hass: HomeAssistant, freezer
):
    """Door Master's read unavailable for the ten hours it was
    wedged. That is information, not a missing value."""
    device, entity_id, contact, _src = _register(hass, "c4", "Wedged")
    coord = await _coordinator(hass)
    coord._grace_until = 0.0

    hass.states.async_set(contact, _iso())
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    first = _record(coord, device.id)[DEV_LAST_ACTIVITY]

    freezer.tick(timedelta(hours=4))
    hass.states.async_set(contact, "unavailable")
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()
    assert _record(coord, device.id)[DEV_LAST_ACTIVITY] == first


async def test_a_republish_does_not_clear_a_freeze_verdict(
    hass: HomeAssistant, freezer
):
    """A four-second bridge blip erased a nine-hour silence once."""
    device, entity_id, contact, _src = _register(hass, "c5", "Still Frozen")
    coord = await _coordinator(hass)
    coord._grace_until = 0.0
    hass.states.async_set(contact, _iso(-36000))
    await hass.async_block_till_done()

    record = _record(coord, device.id)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 3600

    hass.states.async_set(entity_id, "republished")
    await hass.async_block_till_done()
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN

    # A real report clears it.
    hass.states.async_set(contact, _iso())
    await hass.async_block_till_done()
    assert record[DEV_FROZEN_CATEGORY] is None


async def test_a_clock_never_runs_backwards_or_ahead(
    hass: HomeAssistant, freezer
):
    device, entity_id, contact, _src = _register(hass, "c6", "Time Traveller")
    coord = await _coordinator(hass)
    coord._grace_until = 0.0

    hass.states.async_set(contact, _iso())
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    first = _record(coord, device.id)[DEV_LAST_ACTIVITY]

    # A device clock running fast must not push ours into the future.
    hass.states.async_set(contact, _iso(3600))
    await hass.async_block_till_done()
    assert _record(coord, device.id)[DEV_LAST_ACTIVITY] <= (
        dt_util.utcnow().timestamp()
    )

    # And an older reading must not drag it back.
    hass.states.async_set(contact, _iso(-3600))
    await hass.async_block_till_done()
    assert _record(coord, device.id)[DEV_LAST_ACTIVITY] >= first


async def test_events_are_still_counted_when_nothing_advances(
    hass: HomeAssistant,
):
    device, entity_id, contact, _src = _register(hass, "c7", "Counted")
    coord = await _coordinator(hass)
    hass.states.async_set(contact, "unavailable")
    hass.states.async_set(entity_id, "1")
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()
    assert _record(coord, device.id)[DEV_EVENT_COUNT] >= 2


# ------------------------------- devices with no protocol clock

async def test_without_a_contact_entity_arrival_time_counts(
    hass: HomeAssistant, freezer
):
    """#125: the reboot stamp is a report, because it is the only
    evidence there is."""
    device, entity_id, _none, _src = _register(
        hass, "n1", "HomeKit Like", with_contact=False
    )
    coord = await _coordinator(hass)
    coord._grace_until = 0.0

    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=5))
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()

    record = _record(coord, device.id)
    assert record[DEV_TODAY_MAX] == pytest.approx(18000, abs=5)


async def test_a_gap_completed_inside_grace_is_learned(
    hass: HomeAssistant, freezer
):
    """The reversal that matters. The nightly restart is part of the
    home, and discarding what it completes left quiet devices with
    baselines describing half a night."""
    device, entity_id, _none, _src = _register(
        hass, "n2", "Quiet Overnight", with_contact=False
    )
    coord = await _coordinator(hass)
    coord._grace_until = dt_util.utcnow().timestamp() + 300

    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=6))
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()

    assert _record(coord, device.id)[DEV_TODAY_MAX] == pytest.approx(
        21600, abs=5
    )


# ------------------------------------------------ the migration

async def test_the_legacy_cause_wording_is_migrated(
    hass: HomeAssistant,
):
    """0.7.6 renamed a stored value without rewriting what was
    already stored, and the composer then wrote "revived by a on its
    own" into a live brief."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data

    coord.data[DATA_INCIDENTS].append(
        {
            "device_id": "d",
            "name": "Door Master",
            "kind": "unavailable",
            "event": "resolved",
            "when": dt_util.utcnow().timestamp(),
            INC_CAUSE: LEGACY_CAUSE_UNOBSERVED,
            "duration": 15480.0,
        }
    )
    await coord._save_now()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    reloaded = entry.runtime_data.data[DATA_INCIDENTS]
    assert reloaded[-1][INC_CAUSE] == RECOVERY_CAUSE_UNOBSERVED
    assert all(
        row[INC_CAUSE] != LEGACY_CAUSE_UNOBSERVED for row in reloaded
    )
