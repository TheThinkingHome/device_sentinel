# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_last_seen_switched_off_clock.py, Version: 0.27.10 (2026-10-27)

"""A switched-off Last Seen sensor is never the device's clock (rule WATCH-01).

A switched-off entity has no state, so taking it as the clock would
leave every report reading "the clock has not moved": the device would
never be heard, and one that had already learned would be called
frozen while it reported. A device whose Last Seen is switched off is judged by when
its reports arrive, as a device with no Last Seen is.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
)
from tests.helpers import setup_coordinator


def _device(hass, uid, *, last_seen_disabled):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=uid,
    )
    reg = er.async_get(hass)
    plain = reg.async_get_or_create(
        "sensor", "test", f"{uid}_temp",
        suggested_object_id=f"{uid}_temperature",
        device_id=device.id, config_entry=source,
    )
    seen = reg.async_get_or_create(
        "sensor", "test", f"{uid}_last_seen",
        suggested_object_id=f"{uid}_last_seen",
        device_id=device.id, config_entry=source,
        disabled_by=last_seen_disabled,
    ).entity_id
    return device, plain.entity_id, seen


async def test_switched_off_last_seen_is_not_the_clock(hass: HomeAssistant, freezer):
    off, off_eid, off_seen = _device(
        hass, "ls_off", last_seen_disabled=er.RegistryEntryDisabler.INTEGRATION
    )
    on, _on_eid, on_seen = _device(hass, "ls_on", last_seen_disabled=None)
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()

    # The switched-on one is still the clock; the switched-off one is not.
    assert coord._last_seen_entity.get(on.id) == on_seen
    assert off.id not in coord._last_seen_entity
    # The Last Seen Sensor Switched Off card still finds it.
    assert coord.switched_off(off.id, "last_seen") == "other"

    for minute in range(10):
        freezer.tick(timedelta(minutes=5))
        hass.states.async_set(off_eid, str(20 + minute))
        await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][off.id]
    # Heard by when its reports arrive.
    assert record[DEV_LAST_ACTIVITY] is not None
    assert abs(record[DEV_LAST_ACTIVITY] - dt_util.utcnow().timestamp()) < 1


async def test_learned_device_reporting_is_not_called_frozen(
    hass: HomeAssistant, freezer
):
    """A device that learned a one-hour rhythm, whose Last Seen is
    switched off, reports every five minutes and stays clear."""
    from tests.outage_helpers import arm

    off, off_eid, _ = _device(
        hass, "ls_off2", last_seen_disabled=er.RegistryEntryDisabler.USER
    )
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    hass.states.async_set(off_eid, "20")
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][off.id]
    arm(coord, off.id, rhythm=3600.0)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()
    for step in range(60):  # five hours of reports every five minutes
        freezer.tick(timedelta(minutes=5))
        hass.states.async_set(off_eid, str(20 + step % 7))
        await hass.async_block_till_done()
    coord._judge_all_devices()
    assert record.get(DEV_FROZEN_CATEGORY) is None
