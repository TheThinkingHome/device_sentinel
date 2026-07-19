# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.4.6 (2026-07-19)

"""0.4.6 test: the Signals Frozen entity refreshes on a verdict flip.

The frozen verdict was judged live, but the entity only reflected it
when an unrelated event fired a refresh, so it could show a stale
count. The feed now refreshes on a flip, so the entity tracks the
verdict without waiting. It refreshes only on a flip, not on every
reading, so a healthy fleet never notifies.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_FROZEN_VERDICT,
    SIGNAL_FROZEN_REPEAT_COUNT,
)

DOMAIN = "device_sentinel"


async def _setup(hass):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "frz46")},
        name="Frz46 Device",
    )
    signal = er.async_get(hass).async_get_or_create(
        "sensor", "test", "frz46",
        suggested_object_id="frz46_linkquality",
        device_id=device.id, config_entry=source,
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data, device.id, signal.entity_id


def _make_lively(coord, device_id):
    """Give the device a rhythm and recent activity so Check 1 passes."""
    import homeassistant.util.dt as dt_util
    rec = coord.data["devices"][device_id]
    rec[DEV_DAILY_MAX] = [3600.0, 3500.0, 3400.0, 3600.0, 3550.0,
                          3400.0, 3600.0]
    rec[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 60
    return rec


async def test_entity_tracks_the_freeze_and_the_clear(
    hass: HomeAssistant,
):
    """Feed five identical readings: the entity flips to frozen. Feed
    a different reading: it clears at once. No unrelated refresh is
    needed for either transition."""
    coord, device_id, signal_id = await _setup(hass)
    _make_lively(coord, device_id)

    # Five identical rail readings drive the freeze (rail-only rule).
    for _ in range(SIGNAL_FROZEN_REPEAT_COUNT):
        hass.states.async_set(signal_id, "255")
        await hass.async_block_till_done()
    state = hass.states.get("sensor.device_sentinel_signals_frozen")
    assert int(state.state) == 1
    devices = state.attributes["devices"]
    assert devices and devices[0]["name"] == "Frz46 Device"

    # A real reading resets the counter: the entity clears at once.
    hass.states.async_set(signal_id, "84")
    await hass.async_block_till_done()
    state = hass.states.get("sensor.device_sentinel_signals_frozen")
    assert int(state.state) == 0
    assert state.attributes["devices"] == []


async def test_stored_verdict_tracks_the_flip(hass: HomeAssistant):
    """The stored verdict field follows the judgment, so the guard
    knows when a flip has happened and does not notify on every read."""
    coord, device_id, signal_id = await _setup(hass)
    rec = _make_lively(coord, device_id)

    for _ in range(SIGNAL_FROZEN_REPEAT_COUNT):
        hass.states.async_set(signal_id, "255")
        await hass.async_block_till_done()
    assert rec[DEV_SIGNAL_FROZEN_VERDICT] is True

    hass.states.async_set(signal_id, "84")
    await hass.async_block_till_done()
    assert rec[DEV_SIGNAL_FROZEN_VERDICT] is False


async def test_healthy_reads_do_not_flip_the_verdict(hass: HomeAssistant):
    """A device whose readings vary never reaches the count, so its
    verdict stays False and no flip-refresh fires."""
    coord, device_id, signal_id = await _setup(hass)
    rec = _make_lively(coord, device_id)
    for value in ("80", "82", "81", "83", "80", "84"):
        hass.states.async_set(signal_id, value)
        await hass.async_block_till_done()
    assert rec[DEV_SIGNAL_FROZEN_VERDICT] is False
    state = hass.states.get("sensor.device_sentinel_signals_frozen")
    assert int(state.state) == 0
