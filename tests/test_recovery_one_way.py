# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_recovery_one_way.py, Version: 0.27.10 (2026-10-27)

"""A recovery goes one way, and the other rules it travels with
(rules LIST-08, UP-06, FRZ-11, GEN-07, GEN-08, UNAV-07).

A recovery is announced only when a device that was not reporting
starts reporting again. Frozen to unavailable is the device getting
worse; unavailable to frozen happens only in a boot or a coordinator
restart and is false data, so without this rule a switch can be heard
recovering twice in one night without ever speaking. A bridge
restoring a device's values is not the device speaking. A restart or
an outage is credited with nothing, on any stack. Integrations are
named as Home Assistant shows them, and Device Sentinel's own text
does not say "we". The probe file keeps its lines when stored lines
move in on an upgrade.
"""

from __future__ import annotations

import os
from datetime import timedelta
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BROKER_LABEL,
    DATA_DEVICES,
    DATA_INCIDENTS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    EP_AT,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LAG,
    LEARNING_MIN_DAYS,
    RECOVERY_CAUSE_UNOBSERVED,
    REPORT_DIR,
    REPORT_STACK_PROBE,
    STACK_Z2M,
    TODO_KINDS,
)
from custom_components.device_sentinel.report_brief import REPEAT_PARAGRAPH

from .helpers import register_device, setup_coordinator, setup_entry
from .test_bridge_hold import _house, _minutes
from .test_bridge_pairing import _Stub


def _item_kinds(coord, device_id):
    for record in coord.todo_items:
        if record.get("device_id") == device_id:
            return set(record.get(TODO_KINDS) or {})
    return set()


# ------------------------------------------------ one way (rule LIST-08)


async def test_getting_worse_is_not_a_recovery(hass: HomeAssistant, freezer):
    """Frozen to unavailable: the record says worse, the bus says nothing."""
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    await _minutes(hass, coord, freezer, 3)
    assert coord.data[DATA_DEVICES][device.id][DEV_FROZEN_CATEGORY] == "frozen"
    hass.states.async_set(value, "unavailable")
    hass.states.async_set(seen, "unavailable")
    # Past the debounce a frozen device waits before it turns
    # unavailable (rule UNAV-03).
    await _minutes(hass, coord, freezer, 4)
    rows = [(r["kind"], r["event"], bool(r.get("superseded"))) for r in coord.data[DATA_INCIDENTS]]
    assert rows == [("frozen", "opened", False), ("unavailable", "opened", False), ("frozen", "resolved", True)], rows
    assert bus == [("fault", ["frozen"])], bus
    assert not any("no longer" in call.data.get("message", "") for call in phone)


async def test_the_step_back_is_not_reported(hass: HomeAssistant, freezer):
    """Unavailable to frozen with no word from the device: nothing moves."""
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    await _minutes(hass, coord, freezer, 3)
    hass.states.async_set(value, "unavailable")
    hass.states.async_set(seen, "unavailable")
    # Past the debounce a frozen device waits before it turns
    # unavailable (rule UNAV-03).
    await _minutes(hass, coord, freezer, 4)
    before = list(coord.data[DATA_INCIDENTS])
    hass.states.async_set(value, "56")
    hass.states.async_set(seen, heard)
    await _minutes(hass, coord, freezer, 10)
    assert coord.data[DATA_DEVICES][device.id][DEV_FROZEN_CATEGORY] == "frozen"
    assert _item_kinds(coord, device.id) == {"unavailable"}, "the list stepped down"
    assert coord.data[DATA_INCIDENTS] == before, "the step back reached the record"
    assert bus == [("fault", ["frozen"])], bus


async def test_the_one_real_recovery_is_heard_once(hass: HomeAssistant, freezer):
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    await _minutes(hass, coord, freezer, 3)
    hass.states.async_set(value, "unavailable")
    hass.states.async_set(seen, "unavailable")
    await _minutes(hass, coord, freezer, 2)
    hass.states.async_set(value, "56")
    hass.states.async_set(seen, heard)
    await _minutes(hass, coord, freezer, 5)
    hass.states.async_set(seen, dt_util.utcnow().isoformat())  # the switch speaks
    await _minutes(hass, coord, freezer, 2)
    assert coord.data[DATA_DEVICES][device.id][DEV_FROZEN_CATEGORY] is None
    assert [event for event, _kind in bus] == ["fault", "recovered"], bus
    assert not _item_kinds(coord, device.id)


# ------------------------------------------ restored values (rule FRZ-11)


async def _clockless(hass, freezer):
    """A device with no last-seen clock, behind the Zigbee2MQTT bridge."""
    device, entities = register_device(hass, "lamp", name="Lamp")
    entity_id = entities[0] if isinstance(entities, list) else entities
    hass.states.async_set(entity_id, "on")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._grace_until = 0.0
    coord._watched[device.id] = "mqtt"
    coord._stack_for_device = lambda device_id: STACK_Z2M if device_id == device.id else None
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_EVENT_COUNT] = 5000
    record[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 5)
    record[DEV_LAST_ACTIVITY] = (dt_util.utcnow() - timedelta(hours=5)).timestamp()
    return coord, device, entity_id, record


async def test_a_restored_value_is_not_the_device_speaking(hass: HomeAssistant, freezer):
    coord, device, entity_id, record = await _clockless(hass, freezer)
    await _minutes(hass, coord, freezer, 2)
    assert record[DEV_FROZEN_CATEGORY] == "frozen"
    heard = record[DEV_LAST_ACTIVITY]
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    hass.states.async_set(entity_id, "unavailable")
    await _minutes(hass, coord, freezer, 3)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    await _minutes(hass, coord, freezer, 1)
    hass.states.async_set(entity_id, "on")  # the bridge hands the value back
    await hass.async_block_till_done()
    assert record[DEV_LAST_ACTIVITY] == heard, "the restore moved the clock"
    await _minutes(hass, coord, freezer, 10)
    assert record[DEV_FROZEN_CATEGORY] == "frozen"


async def test_a_real_word_after_the_hold_still_counts(hass: HomeAssistant, freezer):
    coord, device, entity_id, record = await _clockless(hass, freezer)
    await _minutes(hass, coord, freezer, 2)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    hass.states.async_set(entity_id, "unavailable")
    await _minutes(hass, coord, freezer, 3)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    hass.states.async_set(entity_id, "on")
    await _minutes(hass, coord, freezer, 5)
    hass.states.async_set(entity_id, "off")  # the lamp itself, well after the hand-back
    await hass.async_block_till_done()
    assert record[DEV_LAST_ACTIVITY] > dt_util.utcnow().timestamp() - 5
    await _minutes(hass, coord, freezer, 1)
    assert record[DEV_FROZEN_CATEGORY] is None


# -------------------------------- no credit for a restart (rule UP-06)


async def _cause_after(hass, lag, ended="intervention (reboot)"):
    device, _ = register_device(hass, "p03", name="P03 Z-Wave Smart plug")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    now = dt_util.utcnow().timestamp()
    coord.data.setdefault("silence_episodes", []).append({
        EP_DEVICE_ID: device.id, "name": "P03 Z-Wave Smart plug", "since": now - 200000,
        "basis": 3600.0, "window": 7200.0, EP_ENDED: ended,
        EP_AT: now - lag - 10, EP_LAG: lag, "learned": None, "signal": None, "taint_seconds": None,
    })
    return coord._recovery_cause(device.id, now - 150000)


async def test_a_reboot_revives_nothing_however_soon(hass: HomeAssistant):
    """A restart or an outage earns no credit, whether 13.5 hours after
    it (a device woken by hand) or 17 minutes (rule UP-06)."""
    assert await _cause_after(hass, 13.5 * 3600) == RECOVERY_CAUSE_UNOBSERVED
    assert await _cause_after(hass, 17 * 60) == RECOVERY_CAUSE_UNOBSERVED


async def test_a_bridge_reconnect_revives_nothing(hass: HomeAssistant):
    assert await _cause_after(hass, 60, "intervention (bridge reconnect)") == RECOVERY_CAUSE_UNOBSERVED


# ---------------------------------- names and "we" (rules GEN-07, GEN-08)


async def test_an_integration_is_named_as_home_assistant_shows_it(hass: HomeAssistant):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    row = {"kind": "integration_down", "when": dt_util.utcnow().timestamp(), "scope": "zwave_js",
           "detail": None, "duration": None}
    sentence = coord._system_event_sentence(row) if hasattr(coord, "_system_event_sentence") else None
    phrase = coord._system_event_phrase(row)
    assert "zwave_js" not in phrase and "Z-Wave integration went down" in phrase, phrase
    if sentence is not None:
        assert "The Z-Wave integration went down" in sentence


def test_the_legend_does_not_say_we():
    assert "Device Sentinel ruled out the usual causes" in REPEAT_PARAGRAPH
    assert " We " not in f" {REPEAT_PARAGRAPH} "


# ---------------------------------------------------- the upgrade's lines


async def test_moving_stored_lines_in_keeps_the_lines_already_written(hass: HomeAssistant):
    """The first start after an upgrade: a catch-up fold writes its lines
    before the stored ones move in, so the move must not replace the
    file (rule STACK-12)."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._probe_write_lines(["| Sep 27 00:00 | zwave_js | day | | | the catch-up fold's line | | | |"])
    coord._probe_write_lines(["| Sep 25 19:54 | matter | server | | | connected | | | entry loaded |"], True)
    path = os.path.join(hass.config.path(REPORT_DIR), REPORT_STACK_PROBE)
    rows = [line for line in open(path, encoding="utf-8").read().splitlines() if line.startswith("| Sep")]
    assert rows == [
        "| Sep 25 19:54 | matter | server | | | connected | | | entry loaded |",
        "| Sep 27 00:00 | zwave_js | day | | | the catch-up fold's line | | | |",
    ], rows


# ------------------------------------------- beyond the bridge (rule UP-06)


async def _behind(hass, freezer, domain="zwave_js"):
    """A clock-less device whose upstream is an integration, not a bridge."""
    device, entities = register_device(hass, "plug", name="P25 Washing machine power")
    entity_id = entities[0] if isinstance(entities, list) else entities
    hass.states.async_set(entity_id, "120")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_EVENT_COUNT] = 5000
    record[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 5)
    down = {"now": None}
    real = coord.upstream_down_since
    coord.upstream_down_since = lambda device_id: (
        (domain, down["now"]) if device_id == device.id and down["now"] else real(device_id)
    )
    return coord, device, entity_id, record, down


async def test_an_integration_outage_leaves_a_frozen_device_frozen(hass: HomeAssistant, freezer):
    coord, device, entity_id, record, down = await _behind(hass, freezer)
    record[DEV_LAST_ACTIVITY] = (dt_util.utcnow() - timedelta(hours=5)).timestamp()
    await _minutes(hass, coord, freezer, 2)
    assert record[DEV_FROZEN_CATEGORY] == "frozen"
    heard = record[DEV_LAST_ACTIVITY]
    down["now"] = dt_util.utcnow().timestamp()
    hass.states.async_set(entity_id, "unavailable")
    await _minutes(hass, coord, freezer, 6)
    assert record[DEV_FROZEN_CATEGORY] == "frozen", "the integration's outage rewrote the device"
    hass.states.async_set(entity_id, "120")  # the integration republishes
    await hass.async_block_till_done()
    assert record[DEV_LAST_ACTIVITY] == heard
    down["now"] = None
    await _minutes(hass, coord, freezer, 5)
    assert record[DEV_FROZEN_CATEGORY] == "frozen"


async def test_an_unavailable_device_recovers_when_its_stack_says_available(hass: HomeAssistant, freezer):
    coord, device, entity_id, record, down = await _behind(hass, freezer)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()
    hass.states.async_set(entity_id, "unavailable")
    await _minutes(hass, coord, freezer, 6)
    assert record[DEV_FROZEN_CATEGORY] == "unavailable"
    down["now"] = dt_util.utcnow().timestamp()
    await _minutes(hass, coord, freezer, 2)
    hass.states.async_set(entity_id, "118")  # the stack says it is back
    await hass.async_block_till_done()
    down["now"] = None
    await _minutes(hass, coord, freezer, 2)
    assert record[DEV_FROZEN_CATEGORY] is None, "the genuine recovery #535 names"


async def test_a_restart_does_not_move_a_working_device_clock(hass: HomeAssistant, freezer):
    """Home Assistant's own restart: values coming back inside the
    startup grace are republished, not the device speaking
    (rule UNAV-05)."""
    device, entities = register_device(hass, "lamp", name="Lamp")
    entity_id = entities[0] if isinstance(entities, list) else entities
    hass.states.async_set(entity_id, "unavailable")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    before = dt_util.utcnow().timestamp() - 3000
    record[DEV_LAST_ACTIVITY] = before
    assert coord._in_startup_grace()
    hass.states.async_set(entity_id, "on")
    await hass.async_block_till_done()
    assert record[DEV_LAST_ACTIVITY] == before


async def test_a_person_pairing_is_still_credited(hass: HomeAssistant):
    from custom_components.device_sentinel import attribution
    from custom_components.device_sentinel.const import SYS_PAIRING_OPEN, SYS_RESTART

    assert attribution.credits(SimpleNamespace(kind=SYS_PAIRING_OPEN))
    assert not attribution.credits(SimpleNamespace(kind=SYS_RESTART))


# ------------------------------------------------------ fetched readings


async def _restarted(hass, domain):
    """A clock-less device on the given integration, inside the grace."""
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    source = MockConfigEntry(domain=domain, title=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, "guest")}, name="Presence Guest",
    )
    entity_id = er.async_get(hass).async_get_or_create(
        "binary_sensor", domain, "guest-occupancy", device_id=device.id, config_entry=source,
    ).entity_id
    hass.states.async_set(entity_id, "unavailable")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    record = coord.data[DATA_DEVICES][device.id]
    before = dt_util.utcnow().timestamp() - 3000
    record[DEV_LAST_ACTIVITY] = before
    assert coord._in_startup_grace()
    hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()
    return record, before


async def test_a_reading_fetched_from_the_device_is_the_device_answering(hass: HomeAssistant):
    """HomeKit Device polls the accessory when it connects: Presence
    Guest's 3:40 AM reading is the sensor answering, and it moves the
    clock (rule FRZ-11)."""
    record, before = await _restarted(hass, "homekit_controller")
    assert record[DEV_LAST_ACTIVITY] > before


async def test_a_value_restored_from_a_cache_is_not(hass: HomeAssistant):
    """ZHA restores the last state from Home Assistant's store."""
    record, before = await _restarted(hass, "zha")
    assert record[DEV_LAST_ACTIVITY] == before


# ---------------------- a standing item survives a restart (rule LIST-08)


async def test_a_broker_outage_is_upstream_only_to_mqtt_devices(hass: HomeAssistant):
    """With the broker down, every device in the house answers to it,
    Lutron Picos included, so their standing items are hidden behind it.
    They must not be retired as recovered, and the hold must not stop
    judging every device in the house (rule LIST-08)."""
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    coord = await setup_coordinator(hass)
    made = {}
    for domain in ("lutron_caseta", "mqtt"):
        source = MockConfigEntry(domain=domain, title=domain)
        source.add_to_hass(hass)
        source.mock_state(hass, ConfigEntryState.LOADED)
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id, identifiers={(domain, "x")}, name=domain,
        )
        coord._watched[device.id] = domain
        made[domain] = device.id
    coord._broker_down_at = dt_util.utcnow().timestamp() - 60
    assert coord.upstream_down_since(made["lutron_caseta"]) is None
    assert coord.upstream_down_since(made["mqtt"]) is not None


async def test_a_silent_device_missing_from_the_source_is_not_retired(
    hass: HomeAssistant, monkeypatch
):
    """Whatever keeps a still-silent device's problem out of the source
    for a moment, its item stays and no recovery is announced (rule LIST-08)."""
    from .test_upstream_loading import _never_reported, _resolved

    coord, device = await _never_reported(hass)
    fired = []
    coord.fire_recovered = lambda *args, **kwargs: fired.append(args[2])
    real = coord._current_problems
    monkeypatch.setattr(
        coord, "_current_problems",
        lambda: {k: v for k, v in real().items() if k != device.id},
    )
    coord._sync_problem_list()
    assert _item_kinds(coord, device.id) == {"never_reported"}, "retired while still silent"
    assert not fired and _resolved(coord, device.id) == []


# A problem hidden behind an outage dated from the start of the run is
# held, not closed and announced again, on every upstream (rule LIST-08).


def _probe(hass, domain):
    """A device with a battery and a value, and a sibling on its entry."""
    source = MockConfigEntry(domain=domain, title=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    reg = dr.async_get(hass)
    device = reg.async_get_or_create(config_entry_id=source.entry_id, identifiers={(domain, "soil")}, name="Soil Probe")
    sibling = reg.async_get_or_create(config_entry_id=source.entry_id, identifiers={(domain, "sib")}, name="Sibling")
    ents = er.async_get(hass)
    ents.async_get_or_create("sensor", domain, "sib", device_id=sibling.id, config_entry=source)
    value = ents.async_get_or_create("sensor", domain, "soil_value", device_id=device.id, config_entry=source).entity_id
    battery = ents.async_get_or_create(
        "sensor", domain, "soil_battery", device_id=device.id, config_entry=source, original_device_class="battery"
    ).entity_id
    return source, device, value, battery

def _kinds(coord, device_id):
    for item in coord.todo_items:
        if item.get("device_id") == device_id:
            return sorted(item.get(TODO_KINDS) or {})
    return []

@pytest.mark.parametrize("upstream", ["bridge", "integration", "broker", "wifi"])
async def test_a_problem_hidden_by_a_start_of_run_outage_is_held(hass: HomeAssistant, freezer, upstream):
    """Soil Irrigation (Monstera), 3:47 AM, on every upstream."""
    domain = {"bridge": "mqtt", "integration": "zwave_js", "broker": "mqtt", "wifi": "shelly"}[upstream]
    source, device, value, battery = _probe(hass, domain)
    hass.states.async_set(value, "40")
    hass.states.async_set(battery, "5", {"unit_of_measurement": "%", "device_class": "battery"})
    heard = dt_util.utcnow() - timedelta(hours=10)
    bus = []
    for name in ("device_sentinel_fault", "device_sentinel_recovered"):
        hass.bus.async_listen(name, lambda e, n=name: bus.append(n.rsplit("_", 1)[-1]))
    entry = await setup_entry(hass)
    state = {"down": False, "graced": True}

    def arm():
        c = entry.runtime_data
        if state["graced"]:
            c._grace_until = 0.0
        c._watched[device.id] = domain
        if upstream == "bridge":
            c._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN if state["down"] else BRIDGE_RUNNING)
            c._stack_for_device = lambda d: STACK_Z2M if d == device.id else None
        if upstream == "wifi":
            c._wifi_ties = {device.id: "device_tracker.probe"}
            if state["down"]:
                c._wifi_down_at = c._run_start()
                c._wifi_fallen = {"device_tracker.probe": c._run_start()}
                c._upstream_from_start.add("wifi")
            else:
                c._wifi_down_at = None
                c._upstream_from_start.discard("wifi")
        if upstream == "broker":
            c._broker_down_at = c._run_start() if state["down"] else None
            if state["down"]:
                c._upstream_from_start.add(BROKER_LABEL)
            else:
                c._upstream_from_start.discard(BROKER_LABEL)
        record = c.data[DATA_DEVICES][device.id]
        record[DEV_EVENT_COUNT] = max(record.get(DEV_EVENT_COUNT) or 0, 5000)
        if len(record.get(DEV_DAILY_MAX) or []) < LEARNING_MIN_DAYS + 5:
            record[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 5)
        if record.get(DEV_LAST_ACTIVITY) is None:
            record[DEV_LAST_ACTIVITY] = heard.timestamp()
        return c

    async def minutes(count):
        for _ in range(count):
            freezer.tick(60)
            c = arm()
            if upstream == "broker":
                c._sample_broker = lambda now, c=c: "down" if state["down"] else "running"
            await c._on_render_tick(None)
            await hass.async_block_till_done()

    arm()
    await minutes(8)
    for eid in (value, battery):
        hass.states.async_set(eid, "unavailable")
    await minutes(6)
    assert _kinds(entry.runtime_data, device.id) == ["low_battery", "unavailable"]
    rows_before = len(entry.runtime_data.data[DATA_INCIDENTS])
    bus.clear()
    # The upstream goes as Home Assistant restarts, so this run finds
    # it down from its start.
    state["graced"] = False
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    state["down"] = True
    if upstream == "integration":
        source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    freezer.tick(120)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    c = entry.runtime_data
    if upstream == "bridge":
        c._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
        c._stack_for_device = lambda d: STACK_Z2M if d == device.id else None
        c._upstream_from_start.add(STACK_Z2M)
        c._bridge_down_at[STACK_Z2M] = c._run_start()
    await minutes(10)
    during = _kinds(entry.runtime_data, device.id)
    state["down"] = False
    if upstream == "integration":
        source.mock_state(hass, ConfigEntryState.LOADED)
    await minutes(15)
    rows = [(r["kind"], r["event"]) for r in entry.runtime_data.data[DATA_INCIDENTS][rows_before:]]
    assert during == ["low_battery", "unavailable"], during
    assert "recovered" not in bus, bus
    assert "fault" not in bus, bus
    assert not rows, rows

async def test_a_real_return_still_ends_the_problem(hass: HomeAssistant, freezer):
    """The hold is for a device still judged down; one that reports
    clears as before."""
    coord = await setup_coordinator(hass)
    held = coord._hold_the_worst({"unavailable": 1.0, "low_battery": 2.0}, {"low_battery": 2.0}, None)
    assert held == {"low_battery": 2.0}


# --------------------- how long a recovered device was down (rule UNAV-07)


async def _armed_device(hass, freezer, uid):
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    from custom_components.device_sentinel.const import (
        DEV_DAILY_MAX,
        DEV_TODAY_MAX,
        FREEZE_ARMING_DAYS,
        STARTUP_GRACE_SECONDS,
    )

    freezer.move_to("2026-10-12 12:00:00+00:00")
    device, (eid,) = register_device(hass, uid, f"Device {uid}")
    coord = await setup_coordinator(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_TODAY_MAX] = None
    hass.states.async_set(eid, "21.5")
    await hass.async_block_till_done()
    return coord, device, eid


async def _minutes_on(hass, freezer, n):
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    for _ in range(n):
        freezer.tick(timedelta(seconds=60))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def test_down_for_counts_from_when_the_device_went_silent(hass: HomeAssistant, freezer):
    """Frozen, then unavailable, then back: the recovery says how long
    since the device last spoke, not since it turned unavailable
    (rule UNAV-07)."""
    from tests.helpers import record_events

    from custom_components.device_sentinel.const import EVENT_RECOVERED

    coord, device, eid = await _armed_device(hass, freezer, "silent1")
    recoveries = record_events(hass, EVENT_RECOVERED)
    await _minutes_on(hass, freezer, 160)
    assert coord.data["devices"][device.id]["frozen_category"] == "frozen"
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await _minutes_on(hass, freezer, 10)
    hass.states.async_set(eid, "22.0")
    await hass.async_block_till_done()
    await _minutes_on(hass, freezer, 2)
    mine = [r for r in recoveries if r.get("device_id") == device.id]
    assert len(mine) == 1 and mine[0]["kind"] == "unavailable"
    assert abs(mine[0]["down_for"] - 170 * 60) <= 60, mine[0]


async def test_a_battery_recovery_keeps_its_own_opening(hass: HomeAssistant, freezer):
    """Only the down family counts from the silence: a low battery that
    recovers is timed from when it was found low."""
    from custom_components.device_sentinel.const import TODO_KIND_LOW_BATTERY

    coord, device, eid = await _armed_device(hass, freezer, "silent2")
    coord._silence_began[device.id] = 100.0
    coord._report_ends_down[device.id] = ("frozen", 400.0)
    assert coord._down_for(device.id, TODO_KIND_LOW_BATTERY, 1000.0, 1600.0) == 600.0
    assert coord._down_for(device.id, "frozen", 1000.0, 1600.0) == 1500.0, "a freeze: from the last report"
    coord._report_ends_down[device.id] = ("frozen", 400.0)
    assert coord._down_for(device.id, "frozen", None, 1600.0) == 1500.0
    coord._report_ends_down[device.id] = ("unavailable", 900.0)
    assert coord._down_for(device.id, "unavailable", 1000.0, 1600.0) == 700.0, "straight to unavailable: from when it went"
    coord._silence_began.pop(device.id)
    coord._report_ends_down[device.id] = ("frozen", 400.0)
    assert coord._down_for(device.id, "frozen", 1000.0, 1600.0) == 600.0, "no silence seen: the opening"
    coord.data["devices"][device.id]["last_activity"] = float("-inf")
    assert coord._down_for(device.id, "frozen", 1000.0, 1600.0) == 600.0, "a damaged stamp: the opening"


async def test_a_verdict_that_clears_without_a_report_counts_from_the_last_report(hass: HomeAssistant, freezer):
    """A frozen verdict can clear on a minute tick when the wait grows (a
    day folds in, a setting changes). The silence is still running, so
    "down for" counts from the last report, not from the start of the
    gap before it (rule UNAV-07)."""
    from tests.helpers import record_events

    from custom_components.device_sentinel.const import (
        DEV_DAILY_MAX,
        EVENT_RECOVERED,
        FREEZE_ARMING_DAYS,
    )

    coord, device, eid = await _armed_device(hass, freezer, "silent3")
    recoveries = record_events(hass, EVENT_RECOVERED)
    await _minutes_on(hass, freezer, 50)
    hass.states.async_set(eid, "23.0")
    await hass.async_block_till_done()
    record = coord.data["devices"][device.id]
    last_report = record["last_activity"]
    await _minutes_on(hass, freezer, 240)
    assert record["frozen_category"] == "frozen"
    record[DEV_DAILY_MAX] = [12 * 3600.0] * (FREEZE_ARMING_DAYS + 2)
    await _minutes_on(hass, freezer, 1)
    assert record["frozen_category"] is None
    # Told after the minute's wait (rule LIST-06), timed to the clear.
    now = dt_util.utcnow().timestamp()
    await _minutes_on(hass, freezer, 2)
    mine = [r for r in recoveries if r.get("device_id") == device.id]
    assert len(mine) == 1
    assert abs(mine[0]["down_for"] - (now - last_report)) <= 61, (mine[0], now - last_report)


async def test_a_report_stamped_before_the_opening_by_its_last_seen_clock(hass: HomeAssistant, freezer):
    """With a Last Seen clock the recovering report carries the stack's
    own time of contact, which can be older than the moment the
    incident opened. It is still a report, so "down for" counts from the
    start of the silence it ended, 30 hours (rules FRZ-11, UNAV-07)."""
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    from tests.helpers import record_events

    from custom_components.device_sentinel.const import (
        DEV_DAILY_MAX,
        DEV_FROZEN_CATEGORY,
        DEV_LAST_ACTIVITY,
        DEV_TODAY_MAX,
        EVENT_RECOVERED,
        FREEZE_ARMING_DAYS,
        FREEZE_CATEGORY_FROZEN,
        STARTUP_GRACE_SECONDS,
    )

    async def _tick(step=61, n=1):
        for _ in range(n):
            freezer.tick(timedelta(seconds=step))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()

    freezer.move_to("2026-10-12 12:00:00+00:00")
    device, (eid,) = register_device(hass, "lastseen1", "Device lastseen1")
    source_id = er.async_get(hass).async_get(eid).config_entry_id
    seen = er.async_get(hass).async_get_or_create(
        "sensor", "test", "lastseen1_last_seen", device_id=device.id,
        config_entry=hass.config_entries.async_get_entry(source_id))
    old = dt_util.utcnow() - timedelta(hours=30)
    hass.states.async_set(seen.entity_id, old.isoformat())
    hass.states.async_set(eid, "1")
    coord = await setup_coordinator(hass)
    await _tick(step=STARTUP_GRACE_SECONDS + 5)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_TODAY_MAX] = None
    assert coord._last_seen_entity.get(device.id) == seen.entity_id
    record[DEV_LAST_ACTIVITY] = old.timestamp()
    recoveries = record_events(hass, EVENT_RECOVERED)
    await _tick(n=3)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    await _tick(step=600)
    heard = dt_util.utcnow() - timedelta(minutes=14)
    hass.states.async_set(seen.entity_id, heard.isoformat())
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()
    await _tick(n=2)
    mine = [r for r in recoveries if r.get("device_id") == device.id]
    assert len(mine) == 1, mine
    expected = dt_util.utcnow().timestamp() - old.timestamp()
    assert abs(mine[0]["down_for"] - expected) <= 900, (mine[0]["down_for"], expected)


async def test_a_short_drop_on_a_quiet_device_reads_as_short(hass: HomeAssistant, freezer):
    """A device that reports once an hour, quiet for 40 minutes, then
    unavailable for five: the trouble began as unavailable, so "down for"
    counts from when it went, five minutes, not the 45 since it last
    spoke (rule UNAV-07)."""
    from tests.helpers import record_events

    from custom_components.device_sentinel.const import EVENT_RECOVERED

    coord, device, eid = await _armed_device(hass, freezer, "quiet1")
    recoveries = record_events(hass, EVENT_RECOVERED)
    await _minutes_on(hass, freezer, 40)
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await _minutes_on(hass, freezer, 5)
    assert coord.data["devices"][device.id]["frozen_category"] == "unavailable"
    hass.states.async_set(eid, "22.5")
    await hass.async_block_till_done()
    await _minutes_on(hass, freezer, 1)
    mine = [r for r in recoveries if r.get("device_id") == device.id]
    assert len(mine) == 1
    assert 4 * 60 <= mine[0]["down_for"] <= 6 * 60, mine[0]
