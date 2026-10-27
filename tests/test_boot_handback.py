# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_boot_handback.py, Version: 0.27.10 (2026-10-27)

"""A value handed back at a start is not the device speaking
(rule WATCH-12).

On a real boot Device Sentinel can set up before the integrations it
watches, and their entities then arrive carrying the value they kept:
with no previous state, after Home Assistant's unavailable placeholder,
after unknown, or from the integration's own restore. A device with a
standing verdict keeps its own entities' last good values from the
verdict's start, and after a restart, a reload or an entity added again
those entities are on watch: the held value coming back is the cache,
the same value written again does not count, and only a different value
is the device speaking.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_FROZEN_CATEGORY,
    DEV_HELD_VALUES,
    DEV_LAST_ACTIVITY,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_UNAVAILABLE,
)

from tests.helpers import record_events, register_device, setup_coordinator
from tests.outage_helpers import (
    PIN,
    Runtime,
    arm,
    esp_device,
    esp_source,
    past_grace,
    rec,
    reload,
    restart,
    walk,
)
from tests.test_freeze_unavailable_split import _mine, _ready


async def _frozen(hass, freezer, uid="door", values=("on",)):
    """A device with no Last Seen clock, frozen: silent four hours on a
    ten-minute rhythm."""
    freezer.move_to(PIN)
    device, eids = register_device(hass, uid, uid.title(), entity_count=len(values))
    for eid, value in zip(eids, values):
        hass.states.async_set(eid, value)
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=600.0)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 4 * 3600
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == "frozen"
    return coord, device, eids


async def _still_frozen(hass, freezer, coord, device, clock, recovered):
    await walk(hass, freezer, 7 * 60)
    await hass.async_block_till_done()
    record = rec(coord, device.id)
    assert record[DEV_FROZEN_CATEGORY] == "frozen"
    assert record[DEV_LAST_ACTIVITY] == clock
    assert _mine(recovered, device.id) == []


# ------------------------------------------------ the paths of a start


async def test_a_frozen_device_stays_frozen_when_its_value_is_handed_back(
    hass: HomeAssistant, freezer
):
    """Path A: its integration comes up after Device Sentinel and hands
    back the value it kept, with no previous state. The door has said
    nothing, so it stays frozen, its clock does not move and no
    recovery is sent."""
    coord, device, (eid,) = await _frozen(hass, freezer)
    clock = rec(coord, device.id)[DEV_LAST_ACTIVITY]
    recovered = record_events(hass, EVENT_RECOVERED)
    coord = await restart(hass, freezer)
    assert hass.states.get(eid).state == "on"
    await _still_frozen(hass, freezer, coord, device, clock, recovered)


async def test_the_value_after_home_assistants_placeholder_is_the_cache(
    hass: HomeAssistant, freezer
):
    """Path B: an integration finishing after Home Assistant's start
    event replaces the restored unavailable placeholder with its kept
    value."""
    coord, device, _ = await _frozen(hass, freezer)
    clock = rec(coord, device.id)[DEV_LAST_ACTIVITY]
    recovered = record_events(hass, EVENT_RECOVERED)
    coord = await restart(hass, freezer, placeholders=True)
    await _still_frozen(hass, freezer, coord, device, clock, recovered)


async def test_the_value_after_unknown_is_the_cache(hass: HomeAssistant, freezer):
    """Path C: unknown first, then the kept value, as MQTT does."""
    coord, device, (eid,) = await _frozen(hass, freezer)
    clock = rec(coord, device.id)[DEV_LAST_ACTIVITY]
    recovered = record_events(hass, EVENT_RECOVERED)
    coord = await restart(
        hass, freezer, before_setup=lambda: hass.states.async_set(eid, "unknown")
    )
    hass.states.async_set(eid, "on")
    await hass.async_block_till_done()
    await _still_frozen(hass, freezer, coord, device, clock, recovered)


async def test_a_reload_puts_the_entities_on_watch(hass: HomeAssistant, freezer):
    """Reloading Device Sentinel arms the watch too: the same value
    written again after it does not count."""
    coord, device, (eid,) = await _frozen(hass, freezer)
    clock = rec(coord, device.id)[DEV_LAST_ACTIVITY]
    recovered = record_events(hass, EVENT_RECOVERED)
    coord = await reload(hass)
    assert coord._on_watch.get(device.id)
    hass.states.async_set(eid, "on")
    await hass.async_block_till_done()
    await _still_frozen(hass, freezer, coord, device, clock, recovered)


async def test_its_integration_reloading_hands_back_the_cache(hass: HomeAssistant, freezer):
    """The device's own integration reloading: Home Assistant writes its
    placeholder, then the integration its kept value."""
    coord, device, (eid,) = await _frozen(hass, freezer)
    clock = rec(coord, device.id)[DEV_LAST_ACTIVITY]
    recovered = record_events(hass, EVENT_RECOVERED)
    assert not coord._on_watch
    er.async_get(hass).async_get(eid).write_unavailable_state(hass)
    await hass.async_block_till_done()
    hass.states.async_set(eid, "on")
    await hass.async_block_till_done()
    await _still_frozen(hass, freezer, coord, device, clock, recovered)


async def test_an_entity_removed_and_added_again_hands_back_the_cache(hass: HomeAssistant, freezer):
    coord, device, (eid,) = await _frozen(hass, freezer)
    clock = rec(coord, device.id)[DEV_LAST_ACTIVITY]
    recovered = record_events(hass, EVENT_RECOVERED)
    hass.states.async_remove(eid)
    await hass.async_block_till_done()
    hass.states.async_set(eid, "on")
    await hass.async_block_till_done()
    await _still_frozen(hass, freezer, coord, device, clock, recovered)


async def test_a_poll_rewriting_the_value_after_boot_never_counts(hass: HomeAssistant, freezer):
    """A same-value write while on watch, inside the grace and after it."""
    coord, device, (eid,) = await _frozen(hass, freezer)
    clock = rec(coord, device.id)[DEV_LAST_ACTIVITY]
    recovered = record_events(hass, EVENT_RECOVERED)
    coord = await restart(hass, freezer)
    for _ in range(3):
        hass.states.async_set(eid, "on")
        await hass.async_block_till_done()
        await walk(hass, freezer, 4 * 60)
    hass.states.async_set(eid, "on", {"linkquality": 90})
    await hass.async_block_till_done()
    await _still_frozen(hass, freezer, coord, device, clock, recovered)
    assert coord._on_watch.get(device.id)


async def test_a_different_value_is_the_device_speaking(hass: HomeAssistant, freezer):
    """Only a value different from the held one ends the watch: the
    device recovers, and its held values go."""
    coord, device, (eid,) = await _frozen(hass, freezer)
    recovered = record_events(hass, EVENT_RECOVERED)
    coord = await restart(hass, freezer)
    await walk(hass, freezer, 60)
    hass.states.async_set(eid, "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 7 * 60)
    record = rec(coord, device.id)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_HELD_VALUES] is None
    assert device.id not in coord._on_watch
    assert len(_mine(recovered, device.id)) == 1


async def test_numbers_compare_as_numbers(hass: HomeAssistant, freezer):
    """21.5 handed back as 21.50 is the same value; 21.6 is not."""
    coord, device, (eid,) = await _frozen(hass, freezer, "thermo", values=("21.5",))
    clock = rec(coord, device.id)[DEV_LAST_ACTIVITY]
    recovered = record_events(hass, EVENT_RECOVERED)
    coord = await restart(
        hass, freezer, before_setup=lambda: hass.states.async_set(eid, "21.50")
    )
    await _still_frozen(hass, freezer, coord, device, clock, recovered)
    hass.states.async_set(eid, "21.6")
    await hass.async_block_till_done()
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None


async def test_text_compares_without_case(hass: HomeAssistant, freezer):
    coord, device, (eid,) = await _frozen(hass, freezer, "mode", values=("Heat",))
    clock = rec(coord, device.id)[DEV_LAST_ACTIVITY]
    recovered = record_events(hass, EVENT_RECOVERED)
    coord = await restart(
        hass, freezer, before_setup=lambda: hass.states.async_set(eid, "heat")
    )
    await _still_frozen(hass, freezer, coord, device, clock, recovered)


# ----------------------------------------------- a device unavailable


async def test_an_unavailable_device_handed_its_value_stays_unavailable(hass: HomeAssistant, freezer):
    """Its stack calling it available, with the held value, is not the
    device speaking: the value reads as not known yet."""
    coord, device, ids, record = await _ready(hass, freezer, "hb1")
    back = record_events(hass, EVENT_RECOVERED)
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert set(record[DEV_HELD_VALUES].values()) == {"on", "87"}

    def _handed_back():
        hass.states.async_set(ids["main"], "on")
        hass.states.async_set(ids["x0"], "87")

    coord = await restart(hass, freezer, before_setup=_handed_back)
    await walk(hass, freezer, 20 * 60)
    record = rec(coord, device.id)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert not _mine(back, device.id)
    hass.states.async_set(ids["main"], "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 2 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    assert len(_mine(back, device.id)) == 1


async def test_1c_main_unknown_and_its_diagnostic_handed_back(hass: HomeAssistant, freezer):
    """test_1c's case on a real start: the main entity comes back
    unknown, the diagnostic with the value it held. Still dead."""
    coord, device, ids, record = await _ready(hass, freezer, "hb2")
    back = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(ids["main"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    def _states():
        hass.states.async_set(ids["main"], "unknown")
        hass.states.async_set(ids["x0"], "87")

    coord = await restart(hass, freezer, before_setup=_states)
    await walk(hass, freezer, 20 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert not _mine(back, device.id)


async def test_a_lutron_light_judged_by_its_hub_stays_unavailable(hass: HomeAssistant, freezer):
    """A light whose hub is connected, unavailable before a restart and
    handed back its value after it."""
    from tests.test_lutron_hub import _house, _past_grace, _tick

    h = await _house(hass, freezer)
    back = record_events(hass, EVENT_RECOVERED)
    await _past_grace(hass, freezer)
    hass.states.async_set(h.kitchen_eid, "unavailable")
    await hass.async_block_till_done()
    await _tick(hass, freezer, n=5)
    assert rec(h.coord, h.kitchen.id)[DEV_FROZEN_CATEGORY] == "unavailable"
    coord = await restart(
        hass, freezer, before_setup=lambda: hass.states.async_set(h.kitchen_eid, "on")
    )
    await walk(hass, freezer, 20 * 60)
    assert rec(coord, h.kitchen.id)[DEV_FROZEN_CATEGORY] == "unavailable"
    assert not _mine(back, h.kitchen.id)


# ---------------------------------------------- what takes no part


async def test_a_healthy_device_is_untouched(hass: HomeAssistant, freezer):
    """No verdict, nothing held, nothing on watch: a start reads it as it
    always has."""
    freezer.move_to(PIN)
    device, (eid,) = register_device(hass, "lamp", "Lamp")
    hass.states.async_set(eid, "on")
    coord = await setup_coordinator(hass)
    arm(coord, device.id, rhythm=6 * 3600.0)
    await past_grace(hass, freezer)
    hass.states.async_set(eid, "off")
    await hass.async_block_till_done()
    coord = await restart(hass, freezer)
    await walk(hass, freezer, 7 * 60)
    record = rec(coord, device.id)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_HELD_VALUES] is None
    assert coord._on_watch == {}


async def test_a_normal_run_is_unchanged(hass: HomeAssistant, freezer):
    """Outside a watch a same-value write counts as it always has."""
    coord, device, (eid,) = await _frozen(hass, freezer)
    hass.states.async_set(eid, "on")
    await hass.async_block_till_done()
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None


async def test_exempt_devices_hold_nothing(hass: HomeAssistant, freezer, monkeypatch):
    """A device with a Last Seen clock, a ZHA device whose radio keeps its
    own clock (rule STACK-04) and an ESPHome device never store held
    values."""
    from custom_components.device_sentinel import stack_zha

    monkeypatch.setattr(stack_zha, "last_heard", lambda _hass, _device: 1791700000.5)
    seen, (seen_eid,) = register_device(hass, "door_last_seen", "Door")
    zha = MockConfigEntry(domain="zha")
    zha.add_to_hass(hass)
    zha.mock_state(hass, ConfigEntryState.LOADED)
    zigbee = dr.async_get(hass).async_get_or_create(
        config_entry_id=zha.entry_id, identifiers={("zha", "z1")}, name="Zigbee Door")
    zigbee_eid = er.async_get(hass).async_get_or_create(
        "binary_sensor", "zha", "z1_door", device_id=zigbee.id, config_entry=zha).entity_id
    esp, (esp_eid, _) = esp_device(hass, esp_source(hass, Runtime(False)), "e1")
    plain, (plain_eid,) = register_device(hass, "plain", "Plain")
    for eid in (seen_eid, zigbee_eid, esp_eid, plain_eid):
        hass.states.async_set(eid, "on")
    coord = await setup_coordinator(hass)
    for device in (seen, zigbee, esp, plain):
        record = rec(coord, device.id)
        coord._hold_values(device.id, record)
    assert rec(coord, plain.id)[DEV_HELD_VALUES] == {
        er.async_get(hass).async_get(plain_eid).id: "on"
    }
    for device in (seen, zigbee, esp):
        assert rec(coord, device.id)[DEV_HELD_VALUES] is None, device.name


async def test_timestamp_and_duration_sensors_never_vote(hass: HomeAssistant, freezer):
    """Their value is worked out again at each start: never held, and a
    new one is not the device speaking while it is on watch."""
    freezer.move_to(PIN)
    device, (main, stamp, uptime) = register_device(hass, "plug", "Plug", entity_count=3)
    registry = er.async_get(hass)
    registry.async_update_entity(stamp, device_class="timestamp")
    registry.async_update_entity(uptime, original_device_class="duration")
    hass.states.async_set(main, "on")
    hass.states.async_set(stamp, "2026-10-11T10:00:00+00:00")
    hass.states.async_set(uptime, "300")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=600.0)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 4 * 3600
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    record = rec(coord, device.id)
    assert record[DEV_FROZEN_CATEGORY] == "frozen"
    assert list(record[DEV_HELD_VALUES].values()) == ["on"]
    clock = record[DEV_LAST_ACTIVITY]
    recovered = record_events(hass, EVENT_RECOVERED)

    def _boot():
        hass.states.async_set(stamp, "2026-10-11T15:30:00+00:00")
        hass.states.async_set(uptime, "12")

    coord = await restart(hass, freezer, before_setup=_boot)
    hass.states.async_set(uptime, "70")
    await hass.async_block_till_done()
    await _still_frozen(hass, freezer, coord, device, clock, recovered)


# ------------------------------- an entity resting at empty text


async def _frozen_remote(hass, freezer):
    """A remote whose action sensor shows a press, then rests at "",
    which is never held: the held value is the press."""
    freezer.move_to(PIN)
    device, (action, battery) = register_device(hass, "remote", "Remote", entity_count=2)
    hass.states.async_set(action, "single")
    hass.states.async_set(battery, "87")
    coord = await setup_coordinator(hass)
    hass.states.async_set(action, "")
    await hass.async_block_till_done()
    record = arm(coord, device.id, rhythm=600.0)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 4 * 3600
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    record = rec(coord, device.id)
    assert record[DEV_FROZEN_CATEGORY] == "frozen"
    assert sorted(record[DEV_HELD_VALUES].values()) == ["87", "single"]
    return coord, device


async def test_a_reload_keeps_the_held_values_of_a_remote_resting_at_empty(
    hass: HomeAssistant, freezer
):
    """Empty text is not a value: showing it is not the device having
    spoken, so a reload keeps the watch."""
    coord, device = await _frozen_remote(hass, freezer)
    coord = await reload(hass)
    assert rec(coord, device.id)[DEV_HELD_VALUES] is not None
    assert coord._on_watch.get(device.id)


async def test_empty_text_handed_back_does_not_recover_a_frozen_remote(
    hass: HomeAssistant, freezer
):
    """Handed back after Home Assistant's placeholder, empty text reads as a
    republish inside the grace."""
    coord, device = await _frozen_remote(hass, freezer)
    clock = rec(coord, device.id)[DEV_LAST_ACTIVITY]
    recovered = record_events(hass, EVENT_RECOVERED)
    coord = await restart(hass, freezer, placeholders=True)
    await _still_frozen(hass, freezer, coord, device, clock, recovered)


# ------------------------------- a value already new when the watch begins


async def test_a_report_of_a_new_value_shown_at_setup_counts(hass: HomeAssistant, freezer):
    """Its integration loaded before Device Sentinel with a new value
    ("off", held "on"). The device's next report repeats it: a value
    different from the held one is a normal report, by any event."""
    coord, device, (eid,) = await _frozen(hass, freezer)
    recovered = record_events(hass, EVENT_RECOVERED)
    coord = await restart(
        hass, freezer, keep_states=True,
        before_setup=lambda: hass.states.async_set(eid, "off"),
    )
    await walk(hass, freezer, 6 * 60)
    hass.states.async_set(eid, "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    assert len(_mine(recovered, device.id)) == 1


async def test_an_unavailable_device_showing_new_values_at_setup_is_judged_on_them(
    hass: HomeAssistant, freezer
):
    """Back while Home Assistant was down, its integration loading before
    Device Sentinel: values other than the held ones mean it spoke while
    nobody listened, so nothing is held and it is judged as it reads."""
    coord, device, ids, record = await _ready(hass, freezer, "q4")
    for eid in ids.values():
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    def _back():
        hass.states.async_set(ids["main"], "off")
        hass.states.async_set(ids["x0"], "64")

    coord = await restart(hass, freezer, keep_states=True, before_setup=_back)
    assert device.id not in coord._on_watch
    assert rec(coord, device.id)[DEV_HELD_VALUES] is None
    await walk(hass, freezer, 20 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
