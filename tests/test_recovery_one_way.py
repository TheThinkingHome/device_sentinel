# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_recovery_one_way.py, Version: 0.23.12 (2026-09-27)

"""A recovery goes one way, and what else 0.23.12 settles (#529 to #533).

#529: a recovery is announced only when a device that was not
reporting starts reporting again. Frozen to unavailable is the device
getting worse; unavailable to frozen happens only in a boot or a
coordinator restart and is false data. On the reference rig the bus
heard Switch Hall Living recover twice in one night without it ever
speaking. #530: a bridge restoring a device's values is not the device
speaking. #531, withdrawn before release, and #535: a restart or an outage is
credited with nothing, on any stack. #532: integrations are named as Home Assistant shows them.
#533: Device Sentinel's own text does not say "we". And the probe
file keeps its lines when stored lines move in on an upgrade.
"""

from __future__ import annotations

import os
from datetime import timedelta
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
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


# ------------------------------------------------------------------ #529


async def test_getting_worse_is_not_a_recovery(hass: HomeAssistant, freezer):
    """Frozen to unavailable: the record says worse, the bus says nothing."""
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    await _minutes(hass, coord, freezer, 3)
    assert coord.data[DATA_DEVICES][device.id][DEV_FROZEN_CATEGORY] == "frozen"
    hass.states.async_set(value, "unavailable")
    hass.states.async_set(seen, "unavailable")
    await _minutes(hass, coord, freezer, 2)
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
    await _minutes(hass, coord, freezer, 2)
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


# ------------------------------------------------------------------ #530


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


# ------------------------------------------------- #531 withdrawn, #535


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
    """#535: a restart or an outage earns no credit, 13.5 hours after it
    (the second fleet's P03, woken by hand) or 17 minutes (the reference
    rig's 17 September). #531's window was withdrawn before release."""
    assert await _cause_after(hass, 13.5 * 3600) == RECOVERY_CAUSE_UNOBSERVED
    assert await _cause_after(hass, 17 * 60) == RECOVERY_CAUSE_UNOBSERVED


async def test_a_bridge_reconnect_revives_nothing(hass: HomeAssistant):
    assert await _cause_after(hass, 60, "intervention (bridge reconnect)") == RECOVERY_CAUSE_UNOBSERVED


# ------------------------------------------------------------- #532, #533


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
    """The first start after an upgrade from 0.23.8: a catch-up fold wrote
    its lines before the stored ones moved in, and the move replaced
    the file."""
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


# ------------------------------------------------ #535 beyond the bridge


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
    startup grace are republished, not the device speaking (#535,
    reversing #125's reboot stamp)."""
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


# ------------------------------------------- #535 amended: fetched readings


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
    clock (#535, amended)."""
    record, before = await _restarted(hass, "homekit_controller")
    assert record[DEV_LAST_ACTIVITY] > before


async def test_a_value_restored_from_a_cache_is_not(hass: HomeAssistant):
    """ZHA restores the last state from Home Assistant's store."""
    record, before = await _restarted(hass, "zha")
    assert record[DEV_LAST_ACTIVITY] == before


# ------------------------------- #529: a standing item survives a restart


async def test_a_broker_outage_is_upstream_only_to_mqtt_devices(hass: HomeAssistant):
    """The chaos weeks of 27 September: with the broker down, every device
    in the house answered to it, Lutron Picos included, so their standing
    items were hidden behind it and retired as recovered, and #535's hold
    would have stopped judging every device in the house."""
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
    for a moment, its item stays and no recovery is announced (#529)."""
    from .test_fourth_fleet_fixes import _never_reported, _resolved

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
