# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_0_23_15.py, Version: 0.23.15 (2026-09-28)

"""What the reference rig's night of 28 September and the attack rounds
after it found, each held here.

1. A down problem hidden behind an upstream outage dated from the start
   of the run was closed, reopened and announced again, and for an
   integration announced as recovered (#529). Every upstream.
2. A stored outage with a corrupt duration forgave a silence that began
   long before it, clearing a frozen device without it speaking.
3. A person's pairing window was credited in the brief but not stored
   with the recovery, so the bus said unknown (#535).
4. In Short named an outage by its return alone.
5. A newer version's device field was removed at load (#189, amended).
6. The classification report kept the setup snapshot.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta

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
    CLASSIFICATION_SETTLED_TRIGGER,
    DATA_DEVICES,
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
    LEARNING_MIN_DAYS,
    RECOVERY_BY_INTERVENTION,
    RECOVERY_CAUSE_PAIRING,
    REPORT_CLASSIFICATION,
    REPORT_DIR,
    STACK_Z2M,
    TODO_KINDS,
)
from custom_components.device_sentinel.events import resolved_by
from custom_components.device_sentinel.records import _new_device_record

from .helpers import register_device, setup_coordinator, setup_entry
from .test_bridge_pairing import _Stub

HOUR = 3600.0


# ------------------------------------------- 1. the start-of-run claim


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
    """Soil Irrigation (Monstera), 3:47 AM on 28 September, on every upstream."""
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


# ------------------------------------------------- 2. the outage bound


def _event(kind, scope, when, duration=None):
    return {"kind": kind, "scope": scope, "when": when, "duration": duration, "detail": None}


async def _one(hass):
    device, _ = register_device(hass, "d", name="Probe")
    coord = await setup_coordinator(hass)
    coord._watched[device.id] = "mqtt"
    coord._stack_for_device = lambda d: STACK_Z2M
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [3000.0] * (LEARNING_MIN_DAYS + 5)
    return coord, device, record


async def test_a_corrupt_duration_does_not_clear_a_frozen_device(hass: HomeAssistant):
    """The real harm: a device frozen for days, credited back under its
    window by one bad duration, would read as recovered unheard."""
    coord, device, record = await _one(hass)
    now = dt_util.utcnow().timestamp()
    record[DEV_LAST_ACTIVITY] = now - 3 * 24 * HOUR
    window = coord._freeze_window(record)
    coord.data[DATA_SYSTEM_EVENTS] = [
        _event("bridge_down", STACK_Z2M, now - 2 * HOUR),
        _event("bridge_up", STACK_Z2M, now - 60, 10 ** 9),
    ]
    silence = coord._observed_silence(record, now, device.id, window)
    assert silence > window


@pytest.mark.parametrize(
    "rows",
    [
        [_event("bridge_up", STACK_Z2M, 0, float("inf"))],
        [_event("bridge_up", STACK_Z2M, 0, float("nan"))],
        ["not a row", 42, None],
        [_event("bridge_up", STACK_Z2M, float("inf"), 60)],
    ],
    ids=["infinite duration", "nan duration", "not rows", "infinite time"],
)
async def test_malformed_stored_outages_are_skipped(hass: HomeAssistant, rows):
    coord, device, record = await _one(hass)
    now = dt_util.utcnow().timestamp()
    record[DEV_LAST_ACTIVITY] = now - 2 * HOUR
    for row in rows:
        if isinstance(row, dict) and row["when"] == 0:
            row["when"] = now - 60
    coord.data[DATA_SYSTEM_EVENTS] = rows
    window = coord._freeze_window(record)
    assert coord._observed_silence(record, now, device.id, window) >= 2 * HOUR - 3600


async def test_a_return_with_no_recorded_fall_is_credited_an_hour_at_most(hass: HomeAssistant):
    """Its four hours claimed, one credited: the device, heard 90 minutes
    ago and within its window when the hour began, is silent 30 minutes."""
    coord, device, record = await _one(hass)
    now = dt_util.utcnow().timestamp()
    record[DEV_LAST_ACTIVITY] = now - 90 * 60
    coord.data[DATA_SYSTEM_EVENTS] = [_event("bridge_up", STACK_Z2M, now - 60, 4 * HOUR)]
    silence = coord._observed_silence(record, now, device.id, coord._freeze_window(record))
    assert abs(silence - 30 * 60) < 2, silence


async def test_the_rigs_own_outage_is_credited_whole(hass: HomeAssistant):
    """Dated from the start of the run, 3:42, its fall recorded at 3:47."""
    coord, device, record = await _one(hass)
    back = dt_util.utcnow().timestamp() - 300
    began = back - 14146
    record[DEV_LAST_ACTIVITY] = began - 600
    coord.data[DATA_SYSTEM_EVENTS] = [
        _event("bridge_down", STACK_Z2M, began + 305),
        _event("bridge_up", STACK_Z2M, back, 14146),
    ]
    silence = coord._observed_silence(record, back + 300, device.id, coord._freeze_window(record))
    assert abs(silence - 900) < 2


# ------------------------------------------------ 3. the pairing credit


def test_a_pairing_window_is_an_intervention_on_the_bus():
    assert resolved_by(RECOVERY_CAUSE_PAIRING) == RECOVERY_BY_INTERVENTION


async def test_a_recovery_inside_a_pairing_window_stores_the_credit(hass: HomeAssistant):
    """Switch Hall Living, 11:51 on 28 September."""
    coord, device, record = await _one(hass)
    now = dt_util.utcnow().timestamp()
    coord.data[DATA_SYSTEM_EVENTS] = [_event("pairing_open", STACK_Z2M, now - 15)]
    assert coord._recovery_cause(device.id, now - 4 * HOUR) == RECOVERY_CAUSE_PAIRING


async def test_the_brief_reads_the_stored_credit_as_revived(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    assert coord._recovery_tail({"cause": RECOVERY_CAUSE_PAIRING}) == ", revived by a pairing window"


# ------------------------------------------------ 4. the outage sentence


async def test_an_outage_is_told_from_its_start_until_its_return(hass: HomeAssistant):
    await hass.config.async_set_time_zone("America/Guayaquil")
    coord = await setup_coordinator(hass)
    back = dt_util.as_utc(dt_util.parse_datetime("2026-09-28T07:37:49-05:00")).timestamp()
    sentence = coord._outage_span_sentence("The Zigbee2MQTT bridge", {"when": back, "duration": 14146.0})
    assert sentence.startswith("The Zigbee2MQTT bridge was down for 3.9h, from ")
    assert "3:42" in sentence and "until 7:37" in sentence, sentence
    assert coord._outage_span_sentence("The MQTT broker", {"when": back, "duration": None}).startswith(
        "The MQTT broker came back at "
    )


# ------------------------------------------ 5. a newer version's fields


def test_a_newer_versions_field_survives_the_reconciler():
    from custom_components.device_sentinel.store import StorageMixin

    record = _new_device_record("2026-09-28T00:00:00+00:00", None)
    record["firmware_history_v2"] = [{"version": "1.2"}]
    record["signal_sum"] = 5.0
    removed, _filled = StorageMixin._reconcile_records({"d": record}, "2026-09-28T00:00:00+00:00")
    assert record["firmware_history_v2"] == [{"version": "1.2"}]
    assert "signal_sum" not in record and removed == 1


async def test_a_newer_versions_field_survives_a_load_and_a_save(hass: HomeAssistant, hass_storage):
    coord = await setup_coordinator(hass)
    device, _ = register_device(hass, "keep", name="Keep")
    coord._rebuild_registry_view()
    coord.data[DATA_DEVICES][device.id]["a_newer_versions_field"] = {"kept": [1, 2, 3]}
    coord._dirty = True
    await coord._save_main()
    from custom_components.device_sentinel.const import DOMAIN

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    again = entry.runtime_data
    assert again.data[DATA_DEVICES][device.id].get("a_newer_versions_field") == {"kept": [1, 2, 3]}
    assert json.dumps(hass_storage).count("a_newer_versions_field") >= 1


# ------------------------------- 6. the classification after the grace


async def test_the_classification_is_written_again_when_the_grace_closes(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord._on_grace_closed(None)
    await hass.async_block_till_done()
    path = os.path.join(hass.config.path(REPORT_DIR), REPORT_CLASSIFICATION)
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert f"({CLASSIFICATION_SETTLED_TRIGGER})" in text
