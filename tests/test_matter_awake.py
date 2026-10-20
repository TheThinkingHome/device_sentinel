# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_matter_awake.py, Version: 0.26.8 (2026-10-20)

"""A Matter device with no battery is judged by being available (ruling #710).

Tim Plas's test of 19 October 2026: his Matter lamp L20 and plug P22,
unplugged, were marked away by the Matter server and unavailable by
Home Assistant in the same second, about five minutes after they were
last heard. So a quiet Matter device with no battery that stays
available is plugged in and well, and is never newly judged frozen, as
an awake ESPHome device is (#636). Unavailable is judged as before. A
Matter device with a battery entity may sleep, and keeps the freeze
rule; a frozen verdict already standing stays until the device
reports (#529); and the Slow Reporting Devices card leaves the device
off, since a freeze mute would change nothing for it.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
)
from custom_components.device_sentinel.coordinator import _new_device_record

from .helpers import setup_coordinator


def _device(hass, domain, uid, battery=False):
    """A lamp on a loaded entry of this domain, with a battery when asked."""
    source = MockConfigEntry(domain=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, uid)}, name=f"Device {uid}"
    )
    registry = er.async_get(hass)
    light = registry.async_get_or_create(
        "light", domain, f"{uid}_light", device_id=device.id, config_entry=source
    ).entity_id
    if battery:
        registry.async_get_or_create(
            "sensor", domain, f"{uid}_battery", device_id=device.id, config_entry=source,
            original_device_class="battery",
        )
    return device, light


def _silent_past_window(coord, device_id, frozen=False):
    """An armed hourly rhythm, last heard well past its window."""
    now = 1_000_000.0
    window = coord._freeze_grace(3600.0) + 3600.0
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = now - window - 10
    if frozen:
        record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    coord.data["devices"][device_id] = record
    return record, now


async def test_an_available_matter_lamp_is_never_frozen(hass: HomeAssistant):
    """L20 and L21, quiet for a day while plugged in (Tim, 11 October)."""
    lamp, light = _device(hass, "matter", "l20")
    other, other_light = _device(hass, "test", "plain")
    coord = await setup_coordinator(hass)
    hass.states.async_set(light, "off")
    hass.states.async_set(other_light, "off")
    record, now = _silent_past_window(coord, lamp.id)
    plain, _ = _silent_past_window(coord, other.id)

    assert coord._awake_matter(lamp.id) is True
    assert coord._device_down_category(lamp.id, record, now) is None
    # The same silence on any other integration is a freeze.
    assert coord._awake_matter(other.id) is False
    assert coord._device_down_category(other.id, plain, now) == FREEZE_CATEGORY_FROZEN


async def test_an_unplugged_matter_lamp_is_unavailable(hass: HomeAssistant):
    """Tim's test: unplugged, every entity reads unavailable."""
    lamp, light = _device(hass, "matter", "unplugged")
    coord = await setup_coordinator(hass)
    hass.states.async_set(light, STATE_UNAVAILABLE)
    record, now = _silent_past_window(coord, lamp.id)

    assert coord._device_down_category(lamp.id, record, now) == FREEZE_CATEGORY_UNAVAILABLE


async def test_a_matter_device_with_a_battery_keeps_the_freeze_rule(hass: HomeAssistant):
    """A battery device on Thread may sleep and check in: not tested yet,
    so it is judged by its rhythm (the 0.27 test with Tim's buttons)."""
    button, light = _device(hass, "matter", "b13", battery=True)
    coord = await setup_coordinator(hass)
    hass.states.async_set(light, "off")
    record, now = _silent_past_window(coord, button.id)

    assert coord._awake_matter(button.id) is False
    assert coord._device_down_category(button.id, record, now) == FREEZE_CATEGORY_FROZEN


async def test_a_standing_frozen_verdict_stays_until_it_reports(hass: HomeAssistant):
    """A lamp frozen when 0.26.8 starts is not told as recovered by a
    rule changing (#529)."""
    lamp, light = _device(hass, "matter", "standing")
    coord = await setup_coordinator(hass)
    hass.states.async_set(light, "off")
    record, now = _silent_past_window(coord, lamp.id, frozen=True)

    assert coord._device_down_category(lamp.id, record, now) == FREEZE_CATEGORY_FROZEN


async def test_nothing_but_unknown_keeps_the_freeze_rule(hass: HomeAssistant):
    """A lamp whose entities say nothing but unknown is judged by its clock."""
    lamp, light = _device(hass, "matter", "unknown")
    coord = await setup_coordinator(hass)
    hass.states.async_set(light, STATE_UNKNOWN)
    record, now = _silent_past_window(coord, lamp.id)

    assert coord._device_down_category(lamp.id, record, now) == FREEZE_CATEGORY_FROZEN


async def test_the_slow_card_leaves_an_available_matter_lamp_off(hass: HomeAssistant):
    """A freeze mute would change nothing for it."""
    lamp, light = _device(hass, "matter", "slow")
    other, other_light = _device(hass, "test", "slowplain")
    coord = await setup_coordinator(hass)
    hass.states.async_set(light, "off")
    hass.states.async_set(other_light, "off")
    for device in (lamp, other):
        record, _ = _silent_past_window(coord, device.id)
        record[DEV_DAILY_MAX] = [3 * 86400.0] * (FREEZE_ARMING_DAYS + 2)

    assert coord._slow_reporter(lamp.id) is False
    assert coord._slow_reporter(other.id) is True


async def test_a_device_behind_a_matter_bridge_keeps_the_freeze_rule(hass: HomeAssistant):
    """A bridge may keep a dead sensor reachable, and nothing tested that
    (adversarial round of 0.26.8)."""
    bridge, _ = _device(hass, "matter", "bridge")
    sensor, light = _device(hass, "matter", "bridged")
    dr.async_get(hass).async_update_device(sensor.id, via_device_id=bridge.id)
    coord = await setup_coordinator(hass)
    hass.states.async_set(light, "on")
    record, now = _silent_past_window(coord, sensor.id)

    assert coord._awake_matter(sensor.id) is False
    assert coord._device_down_category(sensor.id, record, now) == FREEZE_CATEGORY_FROZEN


async def test_the_page_says_how_it_is_judged(hass: HomeAssistant):
    """No window on the Devices tab, and the device page's flag, while no
    frozen verdict stands (adversarial round of 0.26.8)."""
    lamp, light = _device(hass, "matter", "page")
    coord = await setup_coordinator(hass)
    hass.states.async_set(light, "off")
    record, _ = _silent_past_window(coord, lamp.id)
    coord._rebuild_registry_view()

    assert coord.dashboard_device(lamp.id)["status"]["available_rule"] is True
    row = next(r for r in coord.dashboard_devices() if r["device_id"] == lamp.id)
    assert row["window"] is None
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    assert coord.dashboard_device(lamp.id)["status"]["available_rule"] is False


async def test_nothing_but_unknown_is_not_said_spared(hass: HomeAssistant):
    """The page and the card follow the rule: a lamp reading only unknown
    can still be called frozen, so neither says it is spared (second
    adversarial round of 0.26.8)."""
    lamp, light = _device(hass, "matter", "quiet")
    coord = await setup_coordinator(hass)
    hass.states.async_set(light, STATE_UNKNOWN)
    record, _ = _silent_past_window(coord, lamp.id)
    record[DEV_DAILY_MAX] = [3 * 86400.0] * (FREEZE_ARMING_DAYS + 2)
    coord._rebuild_registry_view()

    assert coord.dashboard_device(lamp.id)["status"]["available_rule"] is False
    assert coord._slow_reporter(lamp.id) is True
