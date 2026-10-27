# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_matter_awake.py, Version: 0.27.10 (2026-10-27)

"""A Matter device of a type that reports only on use is judged by being
available (rule STACK-06).

A Matter lamp and plug, unplugged, are marked away by the Matter server
and unavailable by Home Assistant in the same second, about five minutes
after they were last heard. So a quiet Matter device of such a type that
stays available is plugged in and well, and is never newly judged
frozen, as an awake ESPHome device is (rule STACK-07). Unavailable is
judged as before. A frozen verdict already standing stays until the
device reports (rule LIST-08), and the Slow Reporting Devices card
leaves the device off, since a freeze mute would change nothing for it.

The type decides, not what powers the device. A Matter button that
loses its battery is marked away about fourteen minutes after it was
last heard, so a button, light, plug or switch is spared whatever
powers it, and so is a cover, fan, valve, lock, siren, appliance, vacuum
or Matter Bridge. A sensor can go silent while Matter still calls it
available, so a sensor, and any type that reports on a schedule, keeps
the freeze rule whatever powers it, as does a device that measures
something whatever its entities call it.

A Matter button whose buttons have never been pressed has event
entities as its main entities, which read unknown until the first
press, and its only values are diagnostic ones such as its battery. An
entity of its own holding a value shows it available; one whose
entities read nothing at all keeps the freeze rule, and an entity
another integration added never counts (rule WATCH-02).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
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


def _device(hass, domain, uid, battery=False, sensor=False, main="light"):
    """A lamp on a loaded entry of this domain, with a battery when asked;
    a temperature sensor in place of the lamp when asked; another main
    entity's domain (a cover, a switch) in place of the light when
    asked."""
    source = MockConfigEntry(domain=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, uid)}, name=f"Device {uid}"
    )
    registry = er.async_get(hass)
    if sensor:
        light = registry.async_get_or_create(
            "sensor", domain, f"{uid}_temperature", device_id=device.id,
            config_entry=source, original_device_class="temperature",
        ).entity_id
    else:
        light = registry.async_get_or_create(
            main, domain, f"{uid}_{main}", device_id=device.id, config_entry=source
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
    """L20 and L21, quiet for a day while plugged in."""
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
    """Unplugged, every entity reads unavailable."""
    lamp, light = _device(hass, "matter", "unplugged")
    coord = await setup_coordinator(hass)
    hass.states.async_set(light, STATE_UNAVAILABLE)
    record, now = _silent_past_window(coord, lamp.id)

    assert coord._device_down_category(lamp.id, record, now) == FREEZE_CATEGORY_UNAVAILABLE


async def test_a_matter_lamp_with_a_battery_is_spared_too(hass: HomeAssistant):
    """What powers it does not decide (rule STACK-06): a light, plug,
    switch or button is judged by being available on a battery as on mains."""
    lamp, light = _device(hass, "matter", "b13", battery=True)
    coord = await setup_coordinator(hass)
    hass.states.async_set(light, "off")
    record, now = _silent_past_window(coord, lamp.id)

    assert coord.type_words(lamp.id) == "Light"
    assert coord._awake_matter(lamp.id) is True
    assert coord._device_down_category(lamp.id, record, now) is None


async def test_a_matter_sensor_keeps_the_freeze_rule(hass: HomeAssistant):
    """S87: a sensor silent while Matter called it available, caught only
    by its frozen verdict. On a battery and on mains alike."""
    sensors = {
        uid: _device(hass, "matter", uid, battery=battery, sensor=True)
        for uid, battery in (("s87", True), ("mains", False))
    }
    coord = await setup_coordinator(hass)
    for uid, (sensor, entity) in sensors.items():
        hass.states.async_set(entity, "21.5")
        record, now = _silent_past_window(coord, sensor.id)

        assert coord._watched.get(sensor.id) == "matter", uid
        assert coord.type_words(sensor.id) == "Temperature Sensor"
        assert coord._awake_matter(sensor.id) is False, uid
        assert coord._device_down_category(sensor.id, record, now) == FREEZE_CATEGORY_FROZEN, uid


async def test_the_owner_type_decides_in_any_spelling(hass: HomeAssistant):
    """A type set with the pencil counts in the list's name or the
    owner's own spelling of it (rule DEV-11); a type that reports on a
    schedule keeps the rule, such as a thermostat."""
    lamp, light = _device(hass, "matter", "owner")
    coord = await setup_coordinator(hass)
    hass.states.async_set(light, "off")
    record, now = _silent_past_window(coord, lamp.id)

    coord._type_entries[lamp.id] = {"type": "plug", "device_id": lamp.id}
    assert coord._awake_matter(lamp.id) is True
    coord._type_entries[lamp.id] = {"type": "Thermostat", "device_id": lamp.id}
    assert coord._awake_matter(lamp.id) is False
    assert coord._device_down_category(lamp.id, record, now) == FREEZE_CATEGORY_FROZEN


async def test_a_cover_on_mains_is_spared_as_in_0_26_8(hass: HomeAssistant):
    """A cover, fan, valve, lock, siren, appliance, vacuum or Matter
    Bridge reports when used, so a device of these types spared before
    on mains is not called frozen on the upgrade (rule STACK-06)."""
    blind, entity = _device(hass, "matter", "blind", main="cover")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity, "open")
    record, now = _silent_past_window(coord, blind.id)

    assert coord.type_words(blind.id) == "Cover"
    assert coord._awake_matter(blind.id) is True
    assert coord._device_down_category(blind.id, record, now) is None
    for words in ("Fan", "Valve", "Lock", "Siren", "Appliance", "Vacuum", "Matter Bridge"):
        coord._type_entries[blind.id] = {"type": words, "device_id": blind.id}
        assert coord._awake_matter(blind.id) is True, words


async def test_a_sensor_with_a_switch_keeps_the_freeze_rule(hass: HomeAssistant):
    """Its entities read Switch, but it measures a temperature, and a
    silent sensor is what S87 was. The owner's own type is trusted
    (rule STACK-06)."""
    sensor, entity = _device(hass, "matter", "s87switch", sensor=True)
    switch = er.async_get(hass).async_get_or_create(
        "switch", "matter", "s87switch_switch", device_id=sensor.id,
        config_entry=hass.config_entries.async_get_entry(
            er.async_get(hass).async_get(entity).config_entry_id
        ),
    ).entity_id
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity, "21.5")
    hass.states.async_set(switch, "off")
    record, now = _silent_past_window(coord, sensor.id)

    assert coord.type_words(sensor.id) == "Switch"
    assert coord._awake_matter(sensor.id) is False
    assert coord._device_down_category(sensor.id, record, now) == FREEZE_CATEGORY_FROZEN
    coord._type_entries[sensor.id] = {"type": "Switch", "device_id": sensor.id}
    assert coord._awake_matter(sensor.id) is True


async def test_a_standing_frozen_verdict_stays_until_it_reports(hass: HomeAssistant):
    """A lamp frozen at the start is not told as recovered because a
    rule changed (rule LIST-08)."""
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
    """A bridge may keep a dead sensor reachable, so a device behind a
    bridge keeps the freeze rule (rule STACK-06)."""
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
    frozen verdict stands."""
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
    can still be called frozen, so neither says it is spared."""
    lamp, light = _device(hass, "matter", "quiet")
    coord = await setup_coordinator(hass)
    hass.states.async_set(light, STATE_UNKNOWN)
    record, _ = _silent_past_window(coord, lamp.id)
    record[DEV_DAILY_MAX] = [3 * 86400.0] * (FREEZE_ARMING_DAYS + 2)
    coord._rebuild_registry_view()

    assert coord.dashboard_device(lamp.id)["status"]["available_rule"] is False
    assert coord._slow_reporter(lamp.id) is True


def _button(hass, uid, battery="100", foreign_battery=None):
    """A Matter dual button as Home Assistant registers one: two event
    entities for its buttons, its battery, battery type and voltage, and
    an identify button, all diagnostic but the events; and, when asked,
    a battery another integration added. The events read unknown, as
    they do until a button is first pressed."""
    source = MockConfigEntry(domain="matter")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("matter", uid)}, name=f"Button {uid}"
    )
    registry = er.async_get(hass)
    diagnostic = EntityCategory.DIAGNOSTIC

    def add(domain, key, value, device_class=None, category=diagnostic, entry=source, platform="matter"):
        entity = registry.async_get_or_create(
            domain, platform, f"{uid}_{key}", device_id=device.id, config_entry=entry,
            original_device_class=device_class, entity_category=category,
        )
        hass.states.async_set(entity.entity_id, value)

    add("event", "button_1", STATE_UNKNOWN, "button", category=None)
    add("event", "button_2", STATE_UNKNOWN, "button", category=None)
    add("button", "identify", STATE_UNKNOWN, "identify")
    add("sensor", "battery", battery, "battery")
    held = battery not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
    add("sensor", "battery_type", "CR2032" if held else battery)
    add("sensor", "battery_voltage", "3.0" if held else battery, "voltage")
    if foreign_battery is not None:
        notes = MockConfigEntry(domain="battery_notes")
        notes.add_to_hass(hass)
        notes.mock_state(hass, ConfigEntryState.LOADED)
        add("sensor", "battery_plus", foreign_battery, "battery", entry=notes, platform="battery_notes")
    return device


async def test_a_button_never_pressed_is_not_frozen(hass: HomeAssistant):
    """B13 to B15: buttons that read unknown and a battery at 100%,
    silent past their window, on Matter over Thread."""
    button = _button(hass, "b13")
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    record, now = _silent_past_window(coord, button.id)

    assert coord.type_words(button.id) == "Button"
    assert coord._matter_available_now(button.id) is True
    assert coord._device_down_category(button.id, record, now) is None


async def test_a_button_never_pressed_is_said_spared(hass: HomeAssistant):
    """The page and the Slow Reporting Devices card agree with the rule."""
    button = _button(hass, "b14")
    coord = await setup_coordinator(hass)
    record, _ = _silent_past_window(coord, button.id)
    record[DEV_DAILY_MAX] = [3 * 86400.0] * (FREEZE_ARMING_DAYS + 2)
    coord._rebuild_registry_view()

    assert coord.dashboard_device(button.id)["status"]["available_rule"] is True
    assert coord._slow_reporter(button.id) is False


async def test_a_button_frozen_before_stays_frozen_until_it_reports(hass: HomeAssistant):
    """A verdict standing at the upgrade is not told as a recovery (rule LIST-08)."""
    button = _button(hass, "b15")
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    record, now = _silent_past_window(coord, button.id, frozen=True)

    assert coord._device_down_category(button.id, record, now) == FREEZE_CATEGORY_FROZEN


async def test_a_button_showing_nothing_keeps_the_freeze_rule(hass: HomeAssistant):
    """Nothing of its own holds a value, so nothing shows it available."""
    button = _button(hass, "blank", battery=STATE_UNKNOWN)
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    record, now = _silent_past_window(coord, button.id)

    assert coord._matter_available_now(button.id) is False
    assert coord._device_down_category(button.id, record, now) == FREEZE_CATEGORY_FROZEN


async def test_another_integrations_battery_does_not_count(hass: HomeAssistant):
    """Battery Notes adds a battery to the buttons; its value is not the
    device showing itself available (rule WATCH-02)."""
    button = _button(hass, "notes", battery=STATE_UNKNOWN, foreign_battery="100")
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    record, now = _silent_past_window(coord, button.id)

    assert coord._device_down_category(button.id, record, now) == FREEZE_CATEGORY_FROZEN


async def test_a_button_whose_battery_went_unavailable_is_not_spared(hass: HomeAssistant):
    """Its only value gone: unavailable or frozen, never spared."""
    button = _button(hass, "gone", battery=STATE_UNAVAILABLE)
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    record, now = _silent_past_window(coord, button.id)

    assert coord._matter_available_now(button.id) is False
    assert coord._device_down_category(button.id, record, now) is not None
