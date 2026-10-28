# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_exclusions.py, Version: 0.27.11 (2026-10-28)

"""Excluding and muting, and the ladder that settles them
(rules MUTE-01, MUTE-03, MUTE-04, MUTE-07, WATCH-08).

A muted device keeps its clock and history and is still watched; a mute
stops only judging and reporting, and the STATUS column names why. Mute
everything sits above each family's mute, a mute applies live through
options with no restart, and an integration-level pick catches a
multi-homed device only through its owning domain. Excluding a device
or an integration stops the watching. The pickers tag each option with
its integration so two devices sharing a name can be told apart. Each
save settles the ladder, integration over label over device, broadest
first, removing a pick a broader one covers, and setup clears option
keys no code reads.
"""

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.device_sentinel.config_flow import DeviceSentinelOptionsFlow, _devices_covered_by
from custom_components.device_sentinel.const import (
    ACTION_MUTED,
    CONF_BADDAY_BASELINE_DAYS,
    CONF_BADDAY_DROP_LQI,
    CONF_BADDAY_DROP_RSSI,
    CONF_BADDAY_SENSITIVITY,
    CONF_BATTERY_MUTED_DEVICES,
    CONF_BATTERY_MUTED_INTEGRATIONS,
    CONF_BATTERY_MUTED_LABELS,
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_FREEZE_DELTA_HIGH,
    CONF_FREEZE_DELTA_LOW,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_FREEZE_MUTED_INTEGRATIONS,
    CONF_FREEZE_MUTED_LABELS,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_MUTED_DEVICES,
    CONF_MUTED_INTEGRATIONS,
    CONF_MUTED_LABELS,
    CONF_SIGNAL_MUTED_DEVICES,
    CONF_SIGNAL_MUTED_INTEGRATIONS,
    CONF_SIGNAL_MUTED_LABELS,
    DATA_DEVICES,
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    DEAD_OPTION_KEYS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    INCIDENT_ACTION,
    LEARNING_MIN_DAYS,
    SET_ASIDE_EXCLUDED,
    STARTUP_GRACE_SECONDS,
    SYS_DETAIL,
    SYS_DEVICE_PAGE,
    SYS_KIND,
    SYS_OPTIONS_CHANGED,
    TODO_KINDS,
)
from custom_components.device_sentinel.coordinator import _new_device_record

from .test_bridge_hold import _house, _minutes
from tests.helpers import (
    MULTI_OWNER_GONE,
    MULTI_OWNER_POSSIBLE,
    flat_schema,
    register_device,
    setup_coordinator,
    setup_entry,
)

DOMAIN = "device_sentinel"


def _battery_device(hass, source, index, uid_prefix="ex", name_prefix="Excl Device"):
    """A device carrying a percentage battery entity under the given
    source, named by index so its exclusion can be asserted by name.
    The uid uses the source domain so integration-level excludes bind."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(source.domain, f"{uid_prefix}{index}")},
        name=f"{name_prefix} {index}",
    )
    reg = er.async_get(hass).async_get_or_create(
        "sensor", source.domain, f"{uid_prefix}{index}_pct",
        device_id=device.id, config_entry=source,
        original_device_class="battery",
    )
    return device, reg.entity_id


def _register(hass, uid, name):
    """A bare device (no entities) under a test source, for status and
    sweep tests that drive the coordinator's record directly."""
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )


def _named_device(hass, domain, uid, name, device_class=None):
    """A watched device on a named integration domain, for the picker
    disambiguation tests where the integration is the thing asserted."""
    source = MockConfigEntry(domain=domain)
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(domain, uid)},
        name=name,
    )
    er.async_get(hass).async_get_or_create(
        "sensor",
        domain,
        f"{uid}_0",
        device_id=device.id,
        config_entry=source,
        original_device_class=device_class,
    )
    return device


def _ghost_record():
    record = _new_device_record("2026-07-08T00:00:00+00:00", None)
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    return record


# ------------------------------------------ the Mute everything surface

async def test_excluded_device_keeps_learning_never_reported(
    hass: HomeAssistant, freezer
):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, battery_eid = _battery_device(hass, source, 1)
    coord = await setup_coordinator(
        hass, {CONF_MUTED_DEVICES: [device.id]}
    )
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    hass.states.async_set(battery_eid, "10")  # far below threshold
    await hass.async_block_till_done()

    # Observation continues: events counted, verdict stored.
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_EVENT_COUNT] > 0
    # Judgment suppressed: never reported.
    assert coord.battery_low_count == 0
    assert coord.battery_low_list == []
    assert coord._muted_devices[device.id] == "device"


@pytest.mark.skipif(not MULTI_OWNER_POSSIBLE, reason=MULTI_OWNER_GONE)
async def test_integration_exclude_respects_primary_owner(
    hass: HomeAssistant,
):
    """A multi-homed device is caught only by its owning domain."""
    owner = MockConfigEntry(domain="camera_brand")
    owner.add_to_hass(hass)
    tracker = MockConfigEntry(domain="router_tracker")
    tracker.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("camera_brand", "cam9")},
        name="Multi-homed Cam",
    )
    dev_reg.async_update_device(
        device.id, add_config_entry_id=tracker.entry_id
    )
    er.async_get(hass).async_get_or_create(
        "camera", "camera_brand", "cam9_uid",
        device_id=device.id, config_entry=owner,
    )

    # Muting the tracker does not catch the camera.
    entry = await setup_entry(
        hass, {CONF_MUTED_INTEGRATIONS: ["router_tracker"]}
    )
    coord = entry.runtime_data
    assert device.id not in coord._muted_devices

    # Muting the owner does, applied live through options.
    hass.config_entries.async_update_entry(
        entry,
        options={CONF_MUTED_INTEGRATIONS: ["camera_brand"]},
    )
    await hass.async_block_till_done()
    assert coord._muted_devices[device.id] == "integration"


async def test_classification_shows_excluded(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _battery_device(hass, source, 4)
    coord = await setup_coordinator(
        hass, {CONF_MUTED_DEVICES: [device.id]}
    )
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/classification.md")
    ).read()
    # One combined table: the muted device carries a Watched check
    # and names why in the EXCLUDED column.
    assert "WATCHED" in text
    assert "Global (device)" in text
    assert "Excl Device 4" in text


async def test_todo_identity_attributes(hass: HomeAssistant):
    await setup_entry(hass)
    state = hass.states.get("todo.device_sentinel_problem_list")
    assert state is not None
    assert state.attributes["sentinel_type"] == "problem_list"
    # Assert identity is present, not a pinned number: a version bump
    # must not fail a test about attributes existing.
    assert state.attributes["sentinel_version"]


# ------------------------------------------ battery-only exclusions

async def test_device_level_battery_exclude(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    kept, kept_eid = _battery_device(hass, source, 1, "bx", "BatX Device")
    dropped, dropped_eid = _battery_device(hass, source, 2, "bx", "BatX Device")
    coord = await setup_coordinator(
        hass, {CONF_BATTERY_MUTED_DEVICES: [dropped.id]}
    )
    # Battery mechanics, not restart behavior: the startup window
    # the harness opens is shut so flags apply at once (rule BAT-03).
    coord._grace_until = 0.0

    hass.states.async_set(kept_eid, "5")
    hass.states.async_set(dropped_eid, "5")
    await hass.async_block_till_done()

    # Both judged (observation), only the kept one reported.
    assert coord.battery_low_count == 1
    assert coord.battery_low_list[0]["name"] == "BatX Device 1"


async def test_integration_level_battery_exclude(hass: HomeAssistant):
    phone_src = MockConfigEntry(domain="mobile_app")
    phone_src.add_to_hass(hass)
    zig_src = MockConfigEntry(domain="mqtt")
    zig_src.add_to_hass(hass)
    phone, phone_eid = _battery_device(hass, phone_src, 3, "bx", "BatX Device")
    sensor, sensor_eid = _battery_device(hass, zig_src, 4, "bx", "BatX Device")
    coord = await setup_coordinator(
        hass, {CONF_BATTERY_MUTED_INTEGRATIONS: ["mobile_app"]}
    )
    # Battery mechanics, not restart behavior: the startup window
    # the harness opens is shut so flags apply at once (rule BAT-03).
    coord._grace_until = 0.0

    hass.states.async_set(phone_eid, "5")
    hass.states.async_set(sensor_eid, "5")
    await hass.async_block_till_done()

    assert coord.battery_low_count == 1
    assert coord.battery_low_list[0]["name"] == "BatX Device 4"


async def test_battery_exclude_applies_live(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eid = _battery_device(hass, source, 5, "bx", "BatX Device")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    # Battery mechanics, not restart behavior: the startup window
    # the harness opens is shut so flags apply at once (rule BAT-03).
    coord._grace_until = 0.0

    hass.states.async_set(eid, "5")
    await hass.async_block_till_done()
    assert coord.battery_low_count == 1

    hass.config_entries.async_update_entry(
        entry, options={CONF_BATTERY_MUTED_DEVICES: [device.id]}
    )
    await hass.async_block_till_done()
    assert coord.battery_low_count == 0  # excluded, no restart

    hass.config_entries.async_update_entry(entry, options={})
    await hass.async_block_till_done()
    assert coord.battery_low_count == 1  # undo instant, nothing lost


async def test_detected_batteries_picker_source(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    _battery_device(hass, source, 7, "bx", "BatX Device")
    _battery_device(hass, source, 6, "bx", "BatX Device")
    entry = await setup_entry(hass)
    rows = entry.runtime_data.detected_batteries
    assert [r["name"] for r in rows] == ["BatX Device 6", "BatX Device 7"]
    assert all(
        r["device_id"] and r["entity_id"] and r["integration"] == "test"
        for r in rows
    )


# ----------------------------------- muting and STATUS

async def test_globally_muted_device_is_not_judged(hass: HomeAssistant):
    """A device muted for everything gets no verdict: the sweep skips it,
    rather than working out a verdict the report then hides (rule MUTE-01)."""
    device = _register(hass, "gx", "Excluded Ghost")
    coord = await setup_coordinator(hass)
    # Mute it for everything.
    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_MUTED_DEVICES: [device.id]}
    )
    coord._muted_devices[device.id] = "device"
    record = _ghost_record()
    coord.data["devices"][device.id] = record
    now = 1_784_600_000.0
    assert coord._device_down_category(device.id, record, now) is None


async def test_status_reads_the_exclusion_state(hass: HomeAssistant):
    """STATUS reads Reported when nothing mutes the device, GLB alone when
    it is muted for everything, and the family tags otherwise (rule MUTE-10)."""
    device = _register(hass, "st", "Status Device")
    coord = await setup_coordinator(hass)
    # Nothing mutes it: Reported.
    assert coord._device_status(device.id) == "Reported"

    # Family mutes: tags, no GLB.
    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            CONF_BATTERY_MUTED_DEVICES: [device.id],
            CONF_FREEZE_MUTED_DEVICES: [device.id],
        },
    )
    status = coord._device_status(device.id)
    assert status == "Muted (BAT, FRZ)"
    assert "GLB" not in status

    # Mute everything wins and shows alone.
    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            CONF_MUTED_DEVICES: [device.id],
            CONF_BATTERY_MUTED_DEVICES: [device.id],
        },
    )
    coord._muted_devices[device.id] = "device"
    assert coord._device_status(device.id) == "Muted (GLB)"


async def test_report_has_status_column(hass: HomeAssistant):
    """The telemetry table carries a STATUS column and its legend."""
    device = _register(hass, "rep", "Report Device")
    coord = await setup_coordinator(hass)
    coord.data["devices"][device.id] = _new_device_record(
        "2026-07-08T00:00:00+00:00", None
    )
    await hass.async_add_executor_job(coord._write_reports, "test")
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    header = next(
        line for line in text.splitlines() if "DEVICE (INTEGRATION) | STATUS" in line
    )
    assert "STATUS" in header
    # The legend explains the tags.
    assert "BAT battery" in text
    assert "SIG signal" in text
    assert "FRZ freeze" in text


# ---------------------------- picker labels disambiguate collisions

async def test_watched_rows_carry_integration_for_collided_names(
    hass: HomeAssistant,
):
    """The two same-named panels are both present as watched rows,
    each with its own integration, which is the raw material the
    picker labels need to tell them apart."""
    _named_device(hass, "mqtt", "panel_mqtt", "NSPanel Pro Randy")
    _named_device(hass, "mobile_app", "panel_app", "NSPanel Pro Randy")
    # mobile_app is on the default ignore list, and this test is
    # about the name collision rather than the ignoring, so the
    # list is emptied to keep both panels watched.
    coord = await setup_coordinator(
        hass, {CONF_EXCLUDED_INTEGRATIONS: []}
    )

    rows = [
        r
        for r in coord.watched_device_rows
        if r["name"] == "NSPanel Pro Randy"
    ]
    assert len(rows) == 2
    integrations = {r["integration"] for r in rows}
    assert integrations == {"mqtt", "mobile_app"}


async def test_the_two_panels_are_distinct_device_ids(hass: HomeAssistant):
    """The collision is only in the name: the device ids differ, so
    an exclude that addresses the right id reaches exactly one panel.
    This is why the fix is a label change, not an id change."""
    d1 = _named_device(hass, "mqtt", "panel_mqtt", "NSPanel Pro Randy")
    d2 = _named_device(hass, "mobile_app", "panel_app", "NSPanel Pro Randy")
    assert d1.id != d2.id
    # mobile_app is on the default ignore list, and this test is
    # about the name collision rather than the ignoring, so the
    # list is emptied to keep both panels watched.
    coord = await setup_coordinator(
        hass, {CONF_EXCLUDED_INTEGRATIONS: []}
    )
    ids = {
        r["device_id"]
        for r in coord.watched_device_rows
        if r["name"] == "NSPanel Pro Randy"
    }
    assert ids == {d1.id, d2.id}


async def test_exclude_option_labels_disambiguate_by_integration(
    hass: HomeAssistant,
):
    """The end-to-end proof: the global exclude step offers the two
    panels as distinct, integration-tagged options, so a person can
    pick the mqtt one. Drives the real options flow and reads the
    labels off the rendered schema."""
    _named_device(hass, "mqtt", "panel_mqtt", "NSPanel Pro Randy")
    _named_device(hass, "mobile_app", "panel_app", "NSPanel Pro Randy")
    # mobile_app is on the default ignore list, and this test is
    # about the name collision rather than the ignoring, so the
    # list is emptied to keep both panels watched.
    entry = await setup_entry(hass, {CONF_EXCLUDED_INTEGRATIONS: []})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    assert result["step_id"] == "exclusions"
    schema = flat_schema(result["data_schema"].schema)
    labels = []
    for key in schema:
        selector_obj = schema[key]
        config = getattr(selector_obj, "config", {})
        for opt in config.get("options", []):
            if isinstance(opt, dict):
                labels.append(opt["label"])

    panel_labels = [x for x in labels if "NSPanel Pro Randy" in x]
    assert "NSPanel Pro Randy (mqtt)" in panel_labels
    assert "NSPanel Pro Randy (mobile_app)" in panel_labels
    # The bare, ambiguous name is no longer offered on its own.
    assert "NSPanel Pro Randy" not in panel_labels


# ==================================================================
# The exclusion priority ladder and the option-key retirement.
# ==================================================================

def _ladder_device(hass, source, index, name=None):
    """A device with a battery entity, for the ladder tests: the
    picker rows the ladder prunes carry a battery entity so the
    battery kind can cover them too."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", f"ladder{index}")},
        name=name or f"Ladder Device {index}",
    )
    reg = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"ladder{index}_pct",
        device_id=device.id, config_entry=source,
        original_device_class="battery",
    )
    return device, reg.entity_id


# The pure coverage helpers, where the ladder lives (rule MUTE-04).


def test_integration_covers_its_devices():
    rows = [
        {"device_id": "a", "integration": "spook", "labels": frozenset()},
        {"device_id": "b", "integration": "zha", "labels": frozenset()},
    ]
    assert _devices_covered_by(rows, ["spook"], []) == {"a"}


def test_label_covers_its_bearers():
    rows = [
        {"device_id": "a", "integration": "zha", "labels": frozenset({"ice"})},
        {"device_id": "b", "integration": "zha", "labels": frozenset()},
    ]
    assert _devices_covered_by(rows, [], ["ice"]) == {"a"}


def test_coverage_is_positive_only():
    """An id nobody can account for is never named, so a pick is only
    pruned on proof of coverage, never on absence. A device deleted or
    owned by an integration that has not loaded yet keeps its pick."""
    rows = [
        {"device_id": "a", "integration": "zha", "labels": frozenset()},
    ]
    assert _devices_covered_by(rows, ["spook"], ["ice"]) == set()


class _FakeRegistry:
    """A registry that holds exactly the ids it is given.

    The pruner asks it whether a picked device still exists, which is
    the proof required before dropping a pick (rule MUTE-04).
    """

    def __init__(self, ids: set[str]):
        self._ids = ids

    def async_get(self, device_id: str):
        return object() if device_id in self._ids else None


def test_prune_drops_superseded_device_pick():
    rows = [
        {"device_id": "a", "integration": "spook", "labels": frozenset()},
    ]
    pruned = DeviceSentinelOptionsFlow._pruned_muting_input(
        {
            CONF_MUTED_INTEGRATIONS: ["spook"],
            CONF_MUTED_LABELS: [],
            CONF_MUTED_DEVICES: ["a"],
        },
        rows,
        _FakeRegistry({row['device_id'] for row in rows}),
    )
    assert pruned[CONF_MUTED_DEVICES] == []


def test_prune_settles_the_whole_ladder_in_one_save():
    """An integration tick clears the device pick below it in the same
    save, so no device pick survives under a parent that hides it."""
    device_rows = [
        {"device_id": "a", "integration": "spook", "labels": frozenset()},
    ]
    pruned = DeviceSentinelOptionsFlow._pruned_muting_input(
        {
            CONF_MUTED_INTEGRATIONS: ["spook"],
            CONF_MUTED_LABELS: [],
            CONF_MUTED_DEVICES: ["a"],
        },
        device_rows,
        _FakeRegistry({row['device_id'] for row in device_rows}),
    )
    assert pruned[CONF_MUTED_DEVICES] == []


def test_prune_keeps_picks_no_broader_kind_covers():
    """Device 'a' is excluded but no broader kind covers it, so its
    pick stands. A device an integration exclude reached would prune,
    because integration is the broader kind."""
    device_rows = [
        {"device_id": "a", "integration": "zha", "labels": frozenset()},
        {"device_id": "b", "integration": "zha", "labels": frozenset()},
    ]
    pruned = DeviceSentinelOptionsFlow._pruned_muting_input(
        {
            CONF_MUTED_INTEGRATIONS: ["spook"],
            CONF_MUTED_LABELS: [],
            CONF_MUTED_DEVICES: ["a"],
        },
        device_rows,
        _FakeRegistry({row['device_id'] for row in device_rows}),
    )
    assert pruned[CONF_MUTED_DEVICES] == ["a"]


def test_battery_prune_drops_superseded_device_pick():
    rows = [
        {
            "device_id": "a",
            "integration": "mobile_app",
            "labels": frozenset(),
            "entity_id": "sensor.phone_battery",
            "name": "Phone",
        },
    ]
    pruned = DeviceSentinelOptionsFlow._pruned_battery_input(
        {
            CONF_BATTERY_MUTED_INTEGRATIONS: ["mobile_app"],
            CONF_BATTERY_MUTED_LABELS: [],
            CONF_BATTERY_MUTED_DEVICES: ["a"],
        },
        rows,
        _FakeRegistry({row['device_id'] for row in rows}),
    )
    assert pruned[CONF_BATTERY_MUTED_DEVICES] == []


# The freeze and signal pruners are siblings of the battery one. Each
# has two jobs the battery test cannot prove for it: round its own
# sliders to the option's type (the deltas, the two drops and the
# baseline days are integers, the sensitivity a float), and settle its
# own ladder on save the way battery does.

_FREEZE_ROWS = [
    {
        "device_id": "a",
        "integration": "mobile_app",
        "labels": frozenset(),
        "name": "Phone",
    },
    {
        "device_id": "b",
        "integration": "mqtt",
        "labels": frozenset({"noisy"}),
        "name": "Motion Hall",
    },
    {
        "device_id": "c",
        "integration": "mqtt",
        "labels": frozenset(),
        "name": "Door Front",
    },
]


def test_freeze_prune_rounds_the_deltas_to_integers():
    """The two deltas arrive from a slider as floats and are stored
    as the integers they are. A stray 2.0 must not survive a save."""
    pruned = DeviceSentinelOptionsFlow._pruned_freeze_input(
        {
            CONF_FREEZE_DELTA_LOW: 3.0,
            CONF_FREEZE_DELTA_HIGH: 8.0,
            CONF_FREEZE_MUTED_INTEGRATIONS: [],
            CONF_FREEZE_MUTED_LABELS: [],
            CONF_FREEZE_MUTED_DEVICES: [],
        },
        _FREEZE_ROWS,
        _FakeRegistry({"a", "b", "c"}),
    )
    assert pruned[CONF_FREEZE_DELTA_LOW] == 3
    assert isinstance(pruned[CONF_FREEZE_DELTA_LOW], int)
    assert pruned[CONF_FREEZE_DELTA_HIGH] == 8
    assert isinstance(pruned[CONF_FREEZE_DELTA_HIGH], int)


def test_freeze_prune_drops_superseded_device_pick():
    """A device pick the same save's integration exclude covers is
    dropped, the same determinism rule as battery."""
    pruned = DeviceSentinelOptionsFlow._pruned_freeze_input(
        {
            CONF_FREEZE_DELTA_LOW: 3,
            CONF_FREEZE_DELTA_HIGH: 8,
            CONF_FREEZE_MUTED_INTEGRATIONS: ["mobile_app"],
            CONF_FREEZE_MUTED_LABELS: [],
            CONF_FREEZE_MUTED_DEVICES: ["a"],
        },
        _FREEZE_ROWS,
        _FakeRegistry({"a", "b", "c"}),
    )
    assert pruned[CONF_FREEZE_MUTED_DEVICES] == []


def test_freeze_prune_settles_label_and_keeps_the_uncovered_pick():
    """A label exclude prunes the device it reaches; a pick that no
    broader kind covers stands. Both halves in one save so the ladder
    is proven to settle rather than merely to drop."""
    pruned = DeviceSentinelOptionsFlow._pruned_freeze_input(
        {
            CONF_FREEZE_DELTA_LOW: 3,
            CONF_FREEZE_DELTA_HIGH: 8,
            CONF_FREEZE_MUTED_INTEGRATIONS: [],
            CONF_FREEZE_MUTED_LABELS: ["noisy"],
            CONF_FREEZE_MUTED_DEVICES: ["b", "c"],
        },
        _FREEZE_ROWS,
        _FakeRegistry({"a", "b", "c"}),
    )
    # b is reached by the label and goes; c is covered by nothing and stays.
    assert pruned[CONF_FREEZE_MUTED_DEVICES] == ["c"]


def test_freeze_prune_drops_a_deleted_device_pick():
    """A pick for a device the registry no longer holds is dropped on
    proof of absence, so a stale id cannot wedge the save (rule MUTE-04)."""
    pruned = DeviceSentinelOptionsFlow._pruned_freeze_input(
        {
            CONF_FREEZE_DELTA_LOW: 3,
            CONF_FREEZE_DELTA_HIGH: 8,
            CONF_FREEZE_MUTED_INTEGRATIONS: [],
            CONF_FREEZE_MUTED_LABELS: [],
            CONF_FREEZE_MUTED_DEVICES: ["c", "gone"],
        },
        _FREEZE_ROWS,
        _FakeRegistry({"a", "b", "c"}),  # "gone" was deleted
    )
    assert pruned[CONF_FREEZE_MUTED_DEVICES] == ["c"]


_SIGNAL_ROWS = [
    {
        "device_id": "a",
        "integration": "mobile_app",
        "labels": frozenset(),
        "entity_id": "sensor.phone_rssi",
        "name": "Phone",
    },
    {
        "device_id": "b",
        "integration": "mqtt",
        "labels": frozenset({"far"}),
        "entity_id": "sensor.blinds_rssi",
        "name": "Master Park Blinds",
    },
    {
        "device_id": "c",
        "integration": "mqtt",
        "labels": frozenset(),
        "entity_id": "sensor.door_lqi",
        "name": "Door Entryway",
    },
]


def test_signal_prune_rounds_the_sliders_to_their_types():
    """The two drops and the baseline days are integers; the bad-day
    sensitivity is a float. Each arrives from its slider as a float and
    is stored as the type the option declares (rule SIG-08)."""
    pruned = DeviceSentinelOptionsFlow._pruned_signal_input(
        {
            CONF_BADDAY_DROP_LQI: 25.0,
            CONF_BADDAY_DROP_RSSI: 6.0,
            CONF_BADDAY_BASELINE_DAYS: 7.0,
            CONF_BADDAY_SENSITIVITY: 4,
            CONF_SIGNAL_MUTED_INTEGRATIONS: [],
            CONF_SIGNAL_MUTED_LABELS: [],
            CONF_SIGNAL_MUTED_DEVICES: [],
        },
        _SIGNAL_ROWS,
        _FakeRegistry({"a", "b", "c"}),
    )
    for key, want in (
        (CONF_BADDAY_DROP_LQI, 25),
        (CONF_BADDAY_DROP_RSSI, 6),
        (CONF_BADDAY_BASELINE_DAYS, 7),
    ):
        assert pruned[key] == want
        assert isinstance(pruned[key], int), key
    assert pruned[CONF_BADDAY_SENSITIVITY] == 4.0
    assert isinstance(pruned[CONF_BADDAY_SENSITIVITY], float)


def test_signal_prune_leaves_absent_sliders_absent():
    """A save that carries only the exclusion fields must not invent
    the slider keys: each cast is guarded by an `in` test so a partial
    input passes through with the keys it came with."""
    pruned = DeviceSentinelOptionsFlow._pruned_signal_input(
        {
            CONF_SIGNAL_MUTED_INTEGRATIONS: [],
            CONF_SIGNAL_MUTED_LABELS: [],
            CONF_SIGNAL_MUTED_DEVICES: ["c"],
        },
        _SIGNAL_ROWS,
        _FakeRegistry({"a", "b", "c"}),
    )
    for key in (
        CONF_BADDAY_BASELINE_DAYS,
        CONF_BADDAY_DROP_LQI,
        CONF_BADDAY_DROP_RSSI,
        CONF_BADDAY_SENSITIVITY,
    ):
        assert key not in pruned, key
    assert pruned[CONF_SIGNAL_MUTED_DEVICES] == ["c"]


def test_signal_prune_drops_superseded_device_pick():
    """A device pick the same save's integration exclude covers is
    dropped, the same determinism rule as battery."""
    pruned = DeviceSentinelOptionsFlow._pruned_signal_input(
        {
            CONF_SIGNAL_MUTED_INTEGRATIONS: ["mobile_app"],
            CONF_SIGNAL_MUTED_LABELS: [],
            CONF_SIGNAL_MUTED_DEVICES: ["a"],
        },
        _SIGNAL_ROWS,
        _FakeRegistry({"a", "b", "c"}),
    )
    assert pruned[CONF_SIGNAL_MUTED_DEVICES] == []


def test_signal_prune_settles_label_and_keeps_the_uncovered_pick():
    """A label exclude prunes the device it reaches; a pick nothing
    broader covers stands. The ladder settles in one save."""
    pruned = DeviceSentinelOptionsFlow._pruned_signal_input(
        {
            CONF_SIGNAL_MUTED_INTEGRATIONS: [],
            CONF_SIGNAL_MUTED_LABELS: ["far"],
            CONF_SIGNAL_MUTED_DEVICES: ["b", "c"],
        },
        _SIGNAL_ROWS,
        _FakeRegistry({"a", "b", "c"}),
    )
    assert pruned[CONF_SIGNAL_MUTED_DEVICES] == ["c"]


def test_signal_prune_drops_a_deleted_device_pick():
    """A pick for a device the registry no longer holds is dropped on
    proof of absence, never on a guess (rule MUTE-04)."""
    pruned = DeviceSentinelOptionsFlow._pruned_signal_input(
        {
            CONF_SIGNAL_MUTED_INTEGRATIONS: [],
            CONF_SIGNAL_MUTED_LABELS: [],
            CONF_SIGNAL_MUTED_DEVICES: ["c", "gone"],
        },
        _SIGNAL_ROWS,
        _FakeRegistry({"a", "b", "c"}),
    )
    assert pruned[CONF_SIGNAL_MUTED_DEVICES] == ["c"]


# The live coordinator, where the ladder has to hold.


async def test_battery_label_excludes_the_device(hass: HomeAssistant):
    """A label set from the device's own page reaches battery judgment
    without this dialog being opened."""
    label = lr.async_get(hass).async_create("No Battery")
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _ladder_device(hass, source, 1)
    dr.async_get(hass).async_update_device(
        device.id, labels={label.label_id}
    )
    entry = await setup_entry(
        hass, {CONF_BATTERY_MUTED_LABELS: [label.label_id]}
    )
    coord = entry.runtime_data
    assert coord._battery_muted(device.id)
    # Battery only: the device keeps every other kind of watching.
    assert device.id not in coord._muted_devices


async def test_watched_device_rows_carry_cascade_facts(
    hass: HomeAssistant,
):
    label = lr.async_get(hass).async_create("Ice")
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _ladder_device(hass, source, 2, name="Rowed Device")
    dr.async_get(hass).async_update_device(
        device.id, labels={label.label_id}
    )
    entry = await setup_entry(hass)
    rows = entry.runtime_data.watched_device_rows
    row = next(r for r in rows if r["device_id"] == device.id)
    assert row["name"] == "Rowed Device"
    assert row["integration"] == "test"
    assert row["labels"] == frozenset({label.label_id})


async def test_integration_reason_wins_over_device_reason(
    hass: HomeAssistant,
):
    """The reason recorded is the one that survives a prune, so a
    device picked under an excluded integration reads as integration
    rather than as a pick that is about to be dropped."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _ladder_device(hass, source, 4)
    entry = await setup_entry(
        hass,
        {
            CONF_MUTED_INTEGRATIONS: ["test"],
            CONF_MUTED_DEVICES: [device.id],
        },
    )
    assert entry.runtime_data._muted_devices[device.id] == "integration"


# The area retirement.


async def test_area_is_no_longer_an_exclusion_kind(hass: HomeAssistant):
    """Area membership is set for dashboards, voice, and automations,
    so it must not switch off monitoring. A stored area exclusion is
    inert, and the device it once caught is watched again."""
    from homeassistant.helpers import area_registry as ar

    area = ar.async_get(hass).async_create("Garage")
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _ladder_device(hass, source, 5)
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)

    entry = await setup_entry(hass, {"excluded_areas": [area.id]})
    await hass.async_block_till_done()
    assert device.id not in entry.runtime_data._muted_devices


async def test_dead_option_keys_are_cleared_at_setup(hass: HomeAssistant):
    """A key no code reads must not survive in the options, where it
    would read as a live setting quietly doing nothing."""
    entry = await setup_entry(
        hass,
        {
            "excluded_areas": ["area_1"],
            "excluded_entities": ["image.some_screenshot"],
            CONF_MUTED_LABELS: ["ice"],
        },
    )
    await hass.async_block_till_done()
    for key in DEAD_OPTION_KEYS:
        assert key not in entry.options
    # Only the retired keys go; live settings are untouched.
    assert entry.options[CONF_MUTED_LABELS] == ["ice"]


async def test_retired_notification_keys_are_cleared(hass: HomeAssistant):
    """Retired notification shapes are cleared, because a setting no
    code reads would otherwise show as live in every diagnostics
    download (rule STOR-19).
    """
    entry = await setup_entry(
        hass,
        {
            "notify_targets": ["notify.old"],
            "quiet_start": "22:00:00",
            "quiet_end": "07:00:00",
            "reminder_time": "08:00:00",
            "high_priority_pierces_quiet": True,
            "quiet_hours_start": "23:00:00",
            CONF_MUTED_LABELS: ["ice"],
        },
    )
    await hass.async_block_till_done()
    for key in (
        "notify_targets",
        "quiet_start",
        "quiet_end",
        "reminder_time",
        "high_priority_pierces_quiet",
    ):
        assert key not in entry.options, key
    # The shapes that replaced them are live settings and stay.
    assert entry.options["quiet_hours_start"] == "23:00:00"
    assert entry.options[CONF_MUTED_LABELS] == ["ice"]


async def test_setup_survives_when_nothing_is_dead(hass: HomeAssistant):
    entry = await setup_entry(hass, {CONF_MUTED_LABELS: ["ice"]})
    assert entry.options[CONF_MUTED_LABELS] == ["ice"]


# The real options flow, end to end.


async def test_options_flow_prunes_on_save(hass: HomeAssistant):
    """Drive the actual dialog: a device is picked, then the
    integration that owns it is excluded in the next save, and the
    device pick is gone from stored options.

    The entity list is empty here because the standing device pick
    already covers this device's entities, so the form does not offer
    them. That is the render-time half of the ladder.
    """
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _ladder_device(hass, source, 6)
    entry = await setup_entry(hass, {CONF_MUTED_DEVICES: [device.id]})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    assert result["step_id"] == "exclusions"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "exclude": {CONF_EXCLUDED_INTEGRATIONS: []},
            "muting": {
                CONF_MUTED_INTEGRATIONS: ["test"],
                CONF_MUTED_LABELS: [],
                CONF_MUTED_DEVICES: [device.id],
            },
        },
    )
    await hass.async_block_till_done()
    assert result["type"] == "menu"
    assert entry.options[CONF_MUTED_DEVICES] == []
    assert entry.options[CONF_MUTED_INTEGRATIONS] == ["test"]


async def test_options_flow_freeze_save_prunes_on_save(hass: HomeAssistant):
    """Drive the actual Freeze dialog, the sibling of the exclusions
    save above: a device pick is submitted alongside an integration
    exclude that covers it, and the pick is gone from stored options
    while the deltas land as the integers they are. This is the
    save-button path the pruner unit tests cannot reach."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _ladder_device(hass, source, 7)
    entry = await setup_entry(hass, {})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "freeze"}
    )
    assert result["step_id"] == "freeze"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_FREEZE_DELTA_LOW: 3.0,
            CONF_FREEZE_DELTA_HIGH: 8.0,
            "freeze_muting": {
                CONF_FREEZE_MUTED_INTEGRATIONS: ["test"],
                CONF_FREEZE_MUTED_LABELS: [],
                CONF_FREEZE_MUTED_DEVICES: [device.id],
            },
        },
    )
    await hass.async_block_till_done()
    assert result["type"] == "menu"
    assert entry.options[CONF_FREEZE_MUTED_DEVICES] == []
    assert entry.options[CONF_FREEZE_MUTED_INTEGRATIONS] == ["test"]
    assert entry.options[CONF_FREEZE_DELTA_LOW] == 3
    assert isinstance(entry.options[CONF_FREEZE_DELTA_LOW], int)
    assert entry.options[CONF_FREEZE_DELTA_HIGH] == 8
    assert isinstance(entry.options[CONF_FREEZE_DELTA_HIGH], int)


async def test_options_flow_signal_save_prunes_on_save(hass: HomeAssistant):
    """Drive the actual Signal dialog: the same superseded-pick prune
    on save, plus the four knobs landing as their declared types.
    The device carries no signal entity here, so it is not on the
    signal rows and cannot be covered by the ladder; a device pick
    for it survives, which is the correct outcome for a pick nothing
    broader reaches. What this proves is the save path itself:
    the form submits, the entry is created, the knobs are cast."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    _ladder_device(hass, source, 8)
    entry = await setup_entry(hass, {})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "signal"}
    )
    assert result["step_id"] == "signal"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_BADDAY_DROP_LQI: 25.0,
            CONF_BADDAY_DROP_RSSI: 6.0,
            CONF_BADDAY_SENSITIVITY: 4,
            CONF_BADDAY_BASELINE_DAYS: 7.0,
            "signal_muting": {
                CONF_SIGNAL_MUTED_INTEGRATIONS: ["test"],
                CONF_SIGNAL_MUTED_LABELS: [],
                CONF_SIGNAL_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()
    assert result["type"] == "menu"
    assert entry.options[CONF_SIGNAL_MUTED_INTEGRATIONS] == ["test"]
    for key, want in (
        (CONF_BADDAY_DROP_LQI, 25),
        (CONF_BADDAY_DROP_RSSI, 6),
        (CONF_BADDAY_BASELINE_DAYS, 7),
    ):
        assert entry.options[key] == want
        assert isinstance(entry.options[key], int), key
    assert entry.options[CONF_BADDAY_SENSITIVITY] == 4.0
    assert isinstance(entry.options[CONF_BADDAY_SENSITIVITY], float)
    # The three line shapers are retired, so the form cannot carry
    # them and the entry must not gain them (rule SIG-13).
    for gone in ("signal_margin", "signal_lift", "signal_sensitivity"):
        assert gone not in entry.options, gone


async def test_options_flow_hides_covered_devices(hass: HomeAssistant):
    """A device an integration exclude already reaches is gone from
    the picker, so the list only ever offers a decision still worth
    making."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _ladder_device(hass, source, 7)
    entry = await setup_entry(
        hass, {CONF_MUTED_INTEGRATIONS: ["test"]}
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    schema = flat_schema(result["data_schema"].schema)
    device_key = next(
        key for key in schema if str(key) == CONF_MUTED_DEVICES
    )
    offered = {
        option["value"]
        for option in schema[device_key].config["options"]
    }
    assert device.id not in offered


async def test_options_flow_menu_is_work_ordered(hass: HomeAssistant):
    """Notifications leads: it is the one section a new installation
    must visit for alerts to reach a phone (rule CFG-01)."""
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["menu_options"] == [
        "notifications",
        "exclusions",
        "battery",
        "signal",
        "freeze",
        "wifi",
        "advanced",
        "extended",
    ]


# The rungs settled against each other (rule MUTE-04). Every save
# passes through one method, so a decision made on one screen reaches
# the picks stored by another.


async def test_excluding_clears_the_global_mute(hass: HomeAssistant):
    """Excluding clears a mute it covers, driven through the real dialog.

    An integration is muted, then excluded on the same save, and the
    mute is gone from stored options rather than sitting underneath
    the exclusion where the screen would show it back.
    """
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _ladder_device(hass, source, 20)
    entry = await setup_entry(
        hass,
        {
            CONF_MUTED_INTEGRATIONS: ["test"],
            CONF_MUTED_DEVICES: [device.id],
        },
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    # The device pick is not resubmitted: the standing integration
    # mute already covers it, so the picker does not offer it. It is
    # in stored options, which is exactly what settling must clear.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "exclude": {CONF_EXCLUDED_INTEGRATIONS: ["test"]},
            "muting": {
                CONF_MUTED_INTEGRATIONS: ["test"],
                CONF_MUTED_LABELS: [],
                CONF_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()

    assert entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["test"]
    assert entry.options[CONF_MUTED_INTEGRATIONS] == []
    assert entry.options[CONF_MUTED_DEVICES] == []


async def test_excluding_clears_every_section_mute(hass: HomeAssistant):
    """Exclusion reaches the three section screens, not only the one
    that was submitted."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _ladder_device(hass, source, 21)
    entry = await setup_entry(
        hass,
        {
            CONF_BATTERY_MUTED_INTEGRATIONS: ["test"],
            CONF_BATTERY_MUTED_DEVICES: [device.id],
            CONF_SIGNAL_MUTED_INTEGRATIONS: ["test"],
            CONF_FREEZE_MUTED_DEVICES: [device.id],
        },
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "exclude": {CONF_EXCLUDED_INTEGRATIONS: ["test"]},
            "muting": {
                CONF_MUTED_INTEGRATIONS: [],
                CONF_MUTED_LABELS: [],
                CONF_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()

    assert entry.options[CONF_BATTERY_MUTED_INTEGRATIONS] == []
    assert entry.options[CONF_BATTERY_MUTED_DEVICES] == []
    assert entry.options[CONF_SIGNAL_MUTED_INTEGRATIONS] == []
    assert entry.options[CONF_FREEZE_MUTED_DEVICES] == []


async def test_global_mute_clears_the_section_mutes(hass: HomeAssistant):
    """A globally muted integration is judged by nothing, so a
    section mute of the same integration decides nothing."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _ladder_device(hass, source, 22)
    entry = await setup_entry(
        hass,
        {
            CONF_SIGNAL_MUTED_INTEGRATIONS: ["test"],
            CONF_BATTERY_MUTED_DEVICES: [device.id],
        },
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "exclude": {CONF_EXCLUDED_INTEGRATIONS: []},
            "muting": {
                CONF_MUTED_INTEGRATIONS: ["test"],
                CONF_MUTED_LABELS: [],
                CONF_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()

    assert entry.options[CONF_MUTED_INTEGRATIONS] == ["test"]
    assert entry.options[CONF_SIGNAL_MUTED_INTEGRATIONS] == []
    assert entry.options[CONF_BATTERY_MUTED_DEVICES] == []


async def test_a_pick_a_higher_rung_does_not_reach_survives(
    hass: HomeAssistant,
):
    """Settling removes what is covered and nothing else.

    A second integration's device, muted in a section, is untouched
    by excluding the first. Coverage is proved rather than assumed
    (rule MUTE-04), so a pick nothing covers stays.
    """
    first = MockConfigEntry(domain="test")
    first.add_to_hass(hass)
    covered, _ = _ladder_device(hass, first, 23)
    # A device's integration is its config entry's domain, not its
    # identifiers, so a separate integration needs its own entry.
    second = MockConfigEntry(domain="keeper")
    second.add_to_hass(hass)
    other = dr.async_get(hass).async_get_or_create(
        config_entry_id=second.entry_id,
        identifiers={("keeper", "keeper1")},
        name="Keeper",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "keeper", "keeper_pct",
        device_id=other.id, config_entry=second,
        original_device_class="battery",
    )
    entry = await setup_entry(
        hass,
        {
            CONF_BATTERY_MUTED_DEVICES: [covered.id, other.id],
        },
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "exclude": {CONF_EXCLUDED_INTEGRATIONS: ["test"]},
            "muting": {
                CONF_MUTED_INTEGRATIONS: [],
                CONF_MUTED_LABELS: [],
                CONF_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()

    assert covered.id not in entry.options[CONF_BATTERY_MUTED_DEVICES]
    assert other.id in entry.options[CONF_BATTERY_MUTED_DEVICES]


async def test_settling_is_idempotent(hass: HomeAssistant):
    """Saving twice changes nothing the first save did not."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _ladder_device(hass, source, 24)
    entry = await setup_entry(
        hass,
        {
            CONF_MUTED_INTEGRATIONS: ["test"],
            CONF_BATTERY_MUTED_DEVICES: [device.id],
        },
    )
    submission = {
        "exclude": {CONF_EXCLUDED_INTEGRATIONS: ["test"]},
        "muting": {
            CONF_MUTED_INTEGRATIONS: ["test"],
            CONF_MUTED_LABELS: [],
            CONF_MUTED_DEVICES: [],
        },
    }
    for _ in range(2):
        result = await hass.config_entries.options.async_init(
            entry.entry_id
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "exclusions"}
        )
        await hass.config_entries.options.async_configure(
            result["flow_id"], submission
        )
        await hass.async_block_till_done()
        assert entry.options[CONF_MUTED_INTEGRATIONS] == []
        assert entry.options[CONF_BATTERY_MUTED_DEVICES] == []


async def test_an_excluded_integration_clears_no_label(
    hass: HomeAssistant,
):
    """A label spans integrations, so excluding one says nothing
    about the others wearing it."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    _ladder_device(hass, source, 25)
    label = lr.async_get(hass).async_create("Ladder Label")
    entry = await setup_entry(
        hass, {CONF_SIGNAL_MUTED_LABELS: [label.label_id]}
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "exclude": {CONF_EXCLUDED_INTEGRATIONS: ["test"]},
            "muting": {
                CONF_MUTED_INTEGRATIONS: [],
                CONF_MUTED_LABELS: [],
                CONF_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()

    assert entry.options[CONF_SIGNAL_MUTED_LABELS] == [label.label_id]


# ------------------------------------------------- coming back again


async def test_a_device_returns_when_its_exclusion_is_lifted(
    hass: HomeAssistant, freezer
):
    """Un-excluding puts a device back under judgment.

    A person excludes a noisy integration, sees later that it was the
    wrong one, and takes it off the list. The device must return to the
    watched set with its record still there, because an exclusion taken
    back before midnight loses nothing (rule MUTE-01).
    """
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, battery_eid = _battery_device(hass, source, 1)
    coord = await setup_coordinator(
        hass, {CONF_EXCLUDED_INTEGRATIONS: ["test"]}
    )
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    hass.states.async_set(battery_eid, "55")
    await hass.async_block_till_done()
    assert device.id not in coord._watched
    before = coord.data[DATA_DEVICES].get(device.id)

    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_EXCLUDED_INTEGRATIONS: []}
    )
    await hass.async_block_till_done()
    coord._rebuild_registry_view()

    assert device.id in coord._watched
    record = coord.data[DATA_DEVICES][device.id]
    assert record is not None
    if before is not None:
        # The history survived the round trip.
        assert record[DEV_EVENT_COUNT] >= before[DEV_EVENT_COUNT]


async def test_a_device_returns_when_its_muting_is_lifted(
    hass: HomeAssistant, freezer
):
    """Un-muting restores reporting, and the learning never stopped.

    Muting and excluding differ in exactly this: a muted device is
    still watched and still recorded, so when the muting lifts it has
    a full history rather than starting again. That difference is the
    reason both settings exist (rule MUTE-01).
    """
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, battery_eid = _battery_device(hass, source, 2)
    coord = await setup_coordinator(
        hass, {CONF_MUTED_DEVICES: [device.id]}
    )
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    hass.states.async_set(battery_eid, "10")
    await hass.async_block_till_done()
    assert coord.battery_low_count == 0
    counted = coord.data[DATA_DEVICES][device.id][DEV_EVENT_COUNT]
    assert counted > 0

    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_MUTED_DEVICES: []}
    )
    await hass.async_block_till_done()
    coord._rebuild_registry_view()

    assert device.id not in coord._muted_devices
    hass.states.async_set(battery_eid, "9")
    await hass.async_block_till_done()
    assert coord.battery_low_count == 1
    # Nothing was relearned: the count carried straight through.
    assert coord.data[DATA_DEVICES][device.id][DEV_EVENT_COUNT] > counted


async def test_muting_and_unmuting_around_an_open_fault(
    hass: HomeAssistant, freezer
):
    """A fault open when the muting arrives, and still open when it
    lifts, is reported again rather than forgotten."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, battery_eid = _battery_device(hass, source, 3)
    coord = await setup_coordinator(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    hass.states.async_set(battery_eid, "8")
    await hass.async_block_till_done()
    assert coord.battery_low_count == 1

    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_MUTED_DEVICES: [device.id]}
    )
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    assert coord.battery_low_count == 0

    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_MUTED_DEVICES: []}
    )
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    assert coord.battery_low_count == 1


# A mute is a person's act, not a recovery (rule MUTE-07).


MUTES = {
    "muted_devices": "dev", "muted_integrations": "dom", "muted_labels": "lab",
    "freeze_muted_devices": "dev", "freeze_muted_integrations": "dom", "freeze_muted_labels": "lab",
    "battery_muted_devices": "dev", "battery_muted_integrations": "dom", "battery_muted_labels": "lab",
}

def _kinds(coord, device_id):
    for item in coord.todo_items:
        if item.get("device_id") == device_id:
            return sorted(item.get(TODO_KINDS) or {})
    return []

@pytest.mark.parametrize("option", list(MUTES))
async def test_a_mute_is_not_a_recovery(hass: HomeAssistant, freezer, option):
    """A device muted while frozen is never announced recovered: every
    mute setting, every surface silent (rule MUTE-07)."""
    source = MockConfigEntry(domain="zwave_js", title="zwave_js")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    label = lr.async_get(hass).async_create("Quiet")
    reg = dr.async_get(hass)
    device = reg.async_get_or_create(config_entry_id=source.entry_id, identifiers={("zwave_js", "p")}, name="Probe")
    reg.async_update_device(device.id, labels={label.label_id})
    sibling = reg.async_get_or_create(config_entry_id=source.entry_id, identifiers={("zwave_js", "s")}, name="Sibling")
    ents = er.async_get(hass)
    ents.async_get_or_create("sensor", "zwave_js", "s", device_id=sibling.id, config_entry=source)
    value = ents.async_get_or_create("sensor", "zwave_js", "v", device_id=device.id, config_entry=source).entity_id
    battery = ents.async_get_or_create(
        "sensor", "zwave_js", "b", device_id=device.id, config_entry=source, original_device_class="battery"
    ).entity_id
    battery_only = option.startswith("battery")
    hass.states.async_set(value, "40")
    hass.states.async_set(battery, "5", {"unit_of_measurement": "%", "device_class": "battery"})
    bus: list[tuple[str, object]] = []
    for name in ("device_sentinel_fault", "device_sentinel_recovered", "device_sentinel_withdrawn"):
        hass.bus.async_listen(
            name, lambda e, n=name: bus.append((n.rsplit("_", 1)[-1], e.data.get("kinds") or e.data.get("kind"), e.data.get("reason")))
        )
    phone = async_mock_service(hass, "notify", "phone")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]})
    heard = dt_util.utcnow() - timedelta(hours=10)

    def arm():
        c = entry.runtime_data
        c._grace_until = 0.0
        record = c.data[DATA_DEVICES][device.id]
        record[DEV_EVENT_COUNT] = 5000
        if len(record.get(DEV_DAILY_MAX) or []) < LEARNING_MIN_DAYS + 5:
            record[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 5)
        if not battery_only:
            record[DEV_LAST_ACTIVITY] = min(record.get(DEV_LAST_ACTIVITY) or 9e18, heard.timestamp())
        return c

    async def minutes(count):
        for _ in range(count):
            freezer.tick(60)
            c = arm()
            c._evaluate_all_batteries()
            await c._on_render_tick(None)
            await hass.async_block_till_done()

    await minutes(6)
    coord = entry.runtime_data
    listed = _kinds(coord, device.id)
    assert "low_battery" in listed, listed
    if not battery_only:
        assert "frozen" in listed, listed
    rows_before = len(coord.data[DATA_INCIDENTS])
    bus.clear()
    phone.clear()
    chosen = {"dev": [device.id], "dom": ["zwave_js"], "lab": [label.label_id]}[MUTES[option]]
    hass.config_entries.async_update_entry(entry, options={**entry.options, option: chosen})
    await hass.async_block_till_done()
    await minutes(3)
    coord = entry.runtime_data
    rows = [
        (r["kind"], r["event"], r.get("cause"))
        for r in coord.data[DATA_INCIDENTS][rows_before:]
        if r.get("device_id") == device.id
    ]
    assert not [b for b in bus if b[0] == "recovered"], bus
    # Only what the mute sends: a storage notice an earlier test in the
    # same run leaves behind reaches the same phone and is not this test's.
    about_it = [
        c.data.get("message")
        for c in phone
        if "Probe" in str(c.data.get("message")) or "recover" in str(c.data.get("message")).lower()
    ]
    assert not about_it, about_it
    assert rows and all(event == INCIDENT_ACTION and cause == ACTION_MUTED for _k, event, cause in rows), rows
    assert [b for b in bus if b[0] == "withdrawn"] and all(b[2] == "muted" for b in bus if b[0] == "withdrawn"), bus
    if option.startswith("freeze"):
        assert _kinds(coord, device.id) == ["low_battery"]
    else:
        assert _kinds(coord, device.id) == []

async def test_a_genuine_recovery_still_announces(hass: HomeAssistant, freezer):
    """The control: the same device, unmuted, reporting again."""
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    await _minutes(hass, coord, freezer, 3)
    assert coord.data[DATA_DEVICES][device.id][DEV_FROZEN_CATEGORY] == "frozen"
    bus.clear()
    hass.states.async_set(seen, dt_util.utcnow().isoformat())
    await _minutes(hass, coord, freezer, 2)
    assert ("recovered", "frozen") in bus, bus


# ---------------------------------------------------------------------
# Excluding one device (rule MUTE-03).
#
# The integration exclusion's rules for a single device: set aside with
# the same reason, its record, episodes and incidents discarded at the
# next midnight's fold, and taking it back before then loses nothing.
# Picked in Settings beside the integrations, or from the device page,
# and both paths write the same option.


_ids = iter(range(1, 10_000))


async def _ws(client, **payload):
    await client.send_json({"id": next(_ids), **payload})
    return await client.receive_json()


def _rows(coord, kind):
    return [row for row in coord.data.get(DATA_SYSTEM_EVENTS) or [] if row[SYS_KIND] == kind]


async def _two(hass, options=None):
    keep, _ = register_device(hass, "keep", "Door Master")
    drop, _ = register_device(hass, "drop", "Old Plug")
    entry = await setup_entry(hass, {CONF_EXCLUDED_INTEGRATIONS: [], **(options or {})})
    return entry, entry.runtime_data, keep, drop


async def _set(hass, entry, **options):
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.async_block_till_done()


async def test_an_excluded_device_is_set_aside_alone(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass)
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    assert keep.id in coord._watched
    assert drop.id not in coord._watched
    assert coord._set_aside[drop.id][2] == SET_ASIDE_EXCLUDED
    row = next(r for r in coord.classification_rows() if r["device_id"] == drop.id)
    assert row["set_aside"] == "excluded (device)"
    # Its integration is not excluded, and no other device is.
    assert coord._set_aside.get(keep.id) is None


async def test_its_record_goes_at_the_fold_and_not_before(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass)
    coord.data[DATA_DEVICES].setdefault(drop.id, {})
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    assert drop.id in coord.data[DATA_DEVICES], "the record went before midnight"
    # Taken back before midnight: nothing lost.
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: []})
    coord._discard_excluded_records()
    assert drop.id in coord.data[DATA_DEVICES] and drop.id in coord._watched
    # Excluded through midnight: gone, and the other device kept.
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    coord._discard_excluded_records()
    assert drop.id not in coord.data[DATA_DEVICES]
    assert keep.id in coord.data[DATA_DEVICES]


async def test_the_page_excludes_and_takes_back_with_one_row_each(hass: HomeAssistant, hass_ws_client):
    entry, coord, keep, drop = await _two(hass)
    client = await hass_ws_client(hass)
    assert coord.page_actions(drop.id)["excluded"] == {"here": False, "integration": False}
    reply = await _ws(client, type="device_sentinel/device_exclude", device_id=drop.id, on=True)
    assert reply["success"], reply
    await hass.async_block_till_done()
    assert entry.options[CONF_EXCLUDED_DEVICES] == [drop.id]
    assert drop.id not in coord._watched
    assert coord.page_actions(drop.id)["excluded"] == {"here": True, "integration": False}
    page = _rows(coord, SYS_DEVICE_PAGE)
    assert [r[SYS_DETAIL] for r in page] == ["excluded, from its device page"]
    assert _rows(coord, SYS_OPTIONS_CHANGED) == [], "the page act also wrote a Settings changed row"
    # The same act twice changes nothing and writes nothing.
    reply = await _ws(client, type="device_sentinel/device_exclude", device_id=drop.id, on=True)
    assert reply["success"] and len(_rows(coord, SYS_DEVICE_PAGE)) == 1
    reply = await _ws(client, type="device_sentinel/device_exclude", device_id=drop.id, on=False)
    await hass.async_block_till_done()
    assert reply["success"] and entry.options[CONF_EXCLUDED_DEVICES] == []
    assert drop.id in coord._watched
    assert _rows(coord, SYS_DEVICE_PAGE)[-1][SYS_DETAIL] == "no longer excluded, from its device page"


async def test_the_page_says_when_the_integration_is_excluded(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass, {CONF_EXCLUDED_INTEGRATIONS: ["test"]})
    assert coord.page_actions(drop.id)["excluded"] == {"here": False, "integration": True}
    row = next(r for r in coord.classification_rows() if r["device_id"] == drop.id)
    assert row["set_aside"] == "excluded (integration: test)"


async def test_the_page_refuses_an_unknown_device_and_a_non_admin(
    hass: HomeAssistant, hass_ws_client, hass_read_only_access_token
):
    entry, coord, keep, drop = await _two(hass)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/device_exclude", device_id="no-such-device", on=True)
    assert reply["error"]["code"] == "not_found"
    reader = await hass_ws_client(hass, hass_read_only_access_token)
    reply = await _ws(reader, type="device_sentinel/device_exclude", device_id=drop.id, on=True)
    assert reply["error"]["code"] == "unauthorized"
    assert CONF_EXCLUDED_DEVICES not in entry.options


async def test_a_hand_edited_list_names_only_devices(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass)
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id, 7, None, ["x"]]})
    assert coord.excluded_devices == frozenset({drop.id})
    assert drop.id not in coord._watched and keep.id in coord._watched
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: "not a list"})
    assert coord.excluded_devices == frozenset()
    assert drop.id in coord._watched


async def test_settings_offers_watched_and_excluded_devices(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass, {CONF_EXCLUDED_DEVICES: []})
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "exclusions"})
    schema = flat_schema(result["data_schema"].schema)
    field = next(k for k in schema if str(k) == CONF_EXCLUDED_DEVICES)
    labels = {opt["value"]: opt["label"] for opt in schema[field].config["options"]}
    assert labels[keep.id] == "Door Master (test)"
    assert labels[drop.id] == "Old Plug (test, excluded)"
    assert field.default() == [drop.id]


async def test_saving_settings_excludes_and_keeps_its_mutes(hass: HomeAssistant):
    """Taking an exclusion back before midnight gives back everything,
    mutes included, whatever screen was saved meanwhile (rule MUTE-03)."""
    entry, coord, keep, drop = await _two(
        hass, {CONF_MUTED_DEVICES: [], CONF_FREEZE_MUTED_DEVICES: []}
    )
    await _set(hass, entry, **{CONF_FREEZE_MUTED_DEVICES: [drop.id, keep.id]})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "exclusions"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"exclude": {CONF_EXCLUDED_INTEGRATIONS: [], CONF_EXCLUDED_DEVICES: [drop.id]},
         "muting": {CONF_MUTED_DEVICES: [keep.id]}},
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_EXCLUDED_DEVICES] == [drop.id]
    assert drop.id not in coord._watched
    assert entry.options[CONF_FREEZE_MUTED_DEVICES] == [drop.id], "the excluded device's mute was dropped"
    # The global mute added in the same save took keep's section mute;
    # the exclusion took nothing.
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: []})
    assert drop.id in coord._watched
    assert drop.id in entry.options[CONF_FREEZE_MUTED_DEVICES]


@pytest.mark.parametrize("how", ["device", "integration"])
async def test_an_excluded_device_removed_is_not_held(hass: HomeAssistant, hass_ws_client, how):
    """Removed from Home Assistant after it was excluded, its record and
    answers are not held for 30 days: the person asked for them to go,
    so they go with the removal (rule WATCH-07)."""
    entry, coord, keep, drop = await _two(hass)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/device_power", device_id=drop.id, choice="AAA", quantity=2)
    assert reply["success"], reply
    reply = await _ws(client, type="device_sentinel/device_type", device_id=drop.id, choice="Plug")
    assert reply["success"], reply
    coord.data[DATA_DEVICES].setdefault(drop.id, {})
    if how == "device":
        await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    else:
        other, _ = register_device(hass, "other", "Other Source Device")
        await _set(hass, entry, **{CONF_EXCLUDED_INTEGRATIONS: ["test"]})
    assert drop.id in coord.data[DATA_DEVICES]
    dr.async_get(hass).async_remove_device(drop.id)
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    assert drop.id not in coord.data[DATA_DEVICES], "the record was held"
    assert drop.id not in {row["device_id"] for row in coord.held_records()}
    assert drop.id not in coord._power_entries and drop.id not in coord._type_entries
    assert keep.id in coord.data[DATA_DEVICES]


async def test_a_watched_device_removed_is_still_held(hass: HomeAssistant):
    """The control: the 30-day hold is unchanged for a device that was
    never excluded (rule WATCH-07)."""
    entry, coord, keep, drop = await _two(hass)
    coord.data[DATA_DEVICES].setdefault(drop.id, {})
    dr.async_get(hass).async_remove_device(drop.id)
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    assert drop.id in {row["device_id"] for row in coord.held_records()}


async def test_an_integration_whose_devices_are_all_excluded_reads_excluded(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass)
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id, keep.id]})
    assert coord._integration_standing("test", 0) == "excluded"
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    assert coord._integration_standing("test", 1) == "watched"


async def test_a_device_removed_from_home_assistant_leaves_the_list(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass)
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    dr.async_get(hass).async_remove_device(drop.id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "exclusions"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"exclude": {CONF_EXCLUDED_INTEGRATIONS: []}, "muting": {}},
    )
    await hass.async_block_till_done()
    assert entry.options.get(CONF_EXCLUDED_DEVICES) == []


# An exclusion is a person's act, not a recovery, as a mute is (rule LIST-09).


@pytest.mark.parametrize("option", [CONF_EXCLUDED_DEVICES, CONF_EXCLUDED_INTEGRATIONS])
async def test_excluding_a_device_in_trouble_is_not_a_recovery(hass: HomeAssistant, freezer, option):
    source = MockConfigEntry(domain="zwave_js", title="zwave_js")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    reg = dr.async_get(hass)
    device = reg.async_get_or_create(config_entry_id=source.entry_id, identifiers={("zwave_js", "p")}, name="Probe")
    ents = er.async_get(hass)
    value = ents.async_get_or_create("sensor", "zwave_js", "v", device_id=device.id, config_entry=source).entity_id
    battery = ents.async_get_or_create(
        "sensor", "zwave_js", "b", device_id=device.id, config_entry=source, original_device_class="battery"
    ).entity_id
    hass.states.async_set(value, "40")
    hass.states.async_set(battery, "5", {"unit_of_measurement": "%", "device_class": "battery"})
    bus: list[tuple[str, object]] = []
    for name in ("device_sentinel_fault", "device_sentinel_recovered", "device_sentinel_withdrawn"):
        hass.bus.async_listen(name, lambda e, n=name: bus.append((n.rsplit("_", 1)[-1], e.data.get("reason"))))
    phone = async_mock_service(hass, "notify", "phone")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"], CONF_EXCLUDED_INTEGRATIONS: []})
    heard = dt_util.utcnow() - timedelta(hours=10)

    async def minutes(count):
        for _ in range(count):
            freezer.tick(60)
            c = entry.runtime_data
            c._grace_until = 0.0
            record = c.data[DATA_DEVICES].get(device.id)
            if record is not None:
                record[DEV_EVENT_COUNT] = 5000
                if len(record.get(DEV_DAILY_MAX) or []) < LEARNING_MIN_DAYS + 5:
                    record[DEV_DAILY_MAX] = [600.0] * (LEARNING_MIN_DAYS + 5)
                record[DEV_LAST_ACTIVITY] = min(record.get(DEV_LAST_ACTIVITY) or 9e18, heard.timestamp())
            c._evaluate_all_batteries()
            await c._on_render_tick(None)
            await hass.async_block_till_done()

    await minutes(6)
    coord = entry.runtime_data
    listed = next((sorted(i.get(TODO_KINDS) or {}) for i in coord.todo_items if i.get("device_id") == device.id), [])
    assert "frozen" in listed and "low_battery" in listed, listed
    bus.clear()
    phone.clear()
    chosen = [device.id] if option == CONF_EXCLUDED_DEVICES else ["zwave_js"]
    hass.config_entries.async_update_entry(entry, options={**entry.options, option: chosen})
    await hass.async_block_till_done()
    await minutes(3)
    coord = entry.runtime_data
    assert not [i for i in coord.todo_items if i.get("device_id") == device.id]
    assert not [b for b in bus if b[0] == "recovered"], bus
    assert [b for b in bus if b[0] == "withdrawn"], bus
    about_it = [c.data.get("message") for c in phone if "Probe" in str(c.data.get("message"))]
    assert not about_it, about_it


def _defaults_of(schema, section_name: str, key: str):
    """The value a section's field opens with, as the form shows it."""
    for marker, field in schema.schema.items():
        if str(marker) == section_name:
            for inner, _ in field.schema.schema.items():
                if str(inner) == key:
                    return inner.default()
    raise AssertionError(f"{section_name}.{key} not on the form")


async def test_the_badges_open_in_alphabetical_order(hass: HomeAssistant):
    """Saved picks are shown sorted by the words on their badges, not in
    the order they were picked (rule CFG-05)."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    names = ["Zulu Plug", "alpha Sensor", "Mike Switch"]
    devices = [
        dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id, identifiers={("test", f"badge{i}")}, name=name
        )
        for i, name in enumerate(names)
    ]
    for i, device in enumerate(devices):
        er.async_get(hass).async_get_or_create("sensor", "test", f"badge{i}", device_id=device.id, config_entry=source)
    labels = [lr.async_get(hass).async_create(name).label_id for name in ("Winter", "attic", "Garage")]
    entry = await setup_entry(
        hass,
        {CONF_MUTED_DEVICES: [d.id for d in devices], CONF_MUTED_LABELS: labels,
         CONF_EXCLUDED_INTEGRATIONS: ["zwave_js", "mqtt", "esphome"]},
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    schema = result["data_schema"]
    by_name = {d.id: d.name for d in devices}
    assert [by_name[d] for d in _defaults_of(schema, "muting", CONF_MUTED_DEVICES)] == ["alpha Sensor", "Mike Switch", "Zulu Plug"]
    label_names = {lid: lr.async_get(hass).async_get_label(lid).name for lid in labels}
    assert [label_names[x] for x in _defaults_of(schema, "muting", CONF_MUTED_LABELS)] == ["attic", "Garage", "Winter"]
    assert _defaults_of(schema, "exclude", CONF_EXCLUDED_INTEGRATIONS) == ["esphome", "mqtt", "zwave_js"]


def test_accented_names_sort_with_their_letter():
    """Names such as "Ático" and "Ärger" file with the A's, not after Z
    (rule CFG-05)."""
    from custom_components.device_sentinel.config_flow import _alphabetical

    names = ["Zulu", "Ático", "Mike", "alpha", "Ärger"]
    assert sorted(names, key=_alphabetical) == ["alpha", "Ärger", "Ático", "Mike", "Zulu"]
    # Letters drawn with a stroke or joined, and an invisible mark in
    # front of a name, file with the plain letter too.
    others = ["Zulu", "Øvre", "Łódź", "Ærø", "Oak", "\u200bBeta", "Lima", "Echo"]
    assert sorted(others, key=_alphabetical) == ["Ærø", "\u200bBeta", "Echo", "Lima", "Łódź", "Oak", "Øvre", "Zulu"]


async def test_a_cancelled_exclusion_raises_no_frozen_alert(hass: HomeAssistant, freezer):
    """A device reporting every ten minutes, excluded for an hour and taken
    back: the hour nobody watched it is not its silence, so the next
    minute check raises nothing before it reports (rule WATCH-08)."""
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    from custom_components.device_sentinel.const import (
        DEV_DAILY_MAX,
        DEV_FROZEN_CATEGORY,
        FREEZE_ARMING_DAYS,
        STARTUP_GRACE_SECONDS,
    )

    async def minutes(n):
        for _ in range(n):
            freezer.tick(timedelta(seconds=60))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()

    freezer.move_to("2026-10-12 12:00:00+00:00")
    entry, coord, keep, drop = await _two(hass)
    eid = next(
        e.entity_id for e in er.async_entries_for_device(er.async_get(hass), drop.id)
    )
    await minutes(STARTUP_GRACE_SECONDS // 60 + 1)
    record = coord.data[DATA_DEVICES][drop.id]
    record[DEV_DAILY_MAX] = [600.0] * (FREEZE_ARMING_DAYS + 2)
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    await minutes(5)
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    await minutes(60)
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: []})
    seen = []
    for _ in range(5):
        await minutes(1)
        seen.append(coord.data[DATA_DEVICES][drop.id][DEV_FROZEN_CATEGORY])
    assert seen == [None] * 5, seen


# ---------------------------------------------------------------------
# Taking an exclusion back from the dashboard (rules MUTE-03, DASH-12).
# The Devices tab lists the excluded devices, read live, and an
# integration's page excludes it or takes it back, as Settings does.


async def test_the_devices_tab_lists_the_excluded_devices_live(hass: HomeAssistant, hass_ws_client):
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import label_registry as lr

    entry, coord, keep, drop = await _two(hass)
    area = ar.async_get(hass).async_create("Garage")
    label = lr.async_get(hass).async_create("Spare")
    dr.async_get(hass).async_update_device(drop.id, area_id=area.id, labels={label.label_id})
    coord.data[DATA_DEVICES].setdefault(drop.id, {})
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/devices")
    assert reply["success"], reply
    excluded = reply["result"]["excluded"]
    assert [row["name"] for row in excluded] == ["Old Plug"]
    row = excluded[0]
    assert (row["how"], row["page"], row["area"], row["labels"]) == ("device", True, "Garage", ["Spare"])
    assert all(r["device_id"] != drop.id for r in reply["result"]["rows"]), "an excluded device is listed as watched"
    watched = next(r for r in reply["result"]["rows"] if r["device_id"] == keep.id)
    assert (watched["area"], watched["labels"]) == (None, [])
    # Past midnight its history is gone, and so is its page here.
    coord._discard_excluded_records()
    assert coord.dashboard_excluded_devices()[0]["page"] is False


async def test_a_device_excluded_with_its_integration_is_listed_as_such(hass: HomeAssistant):
    entry, coord, keep, drop = await _two(hass, {CONF_EXCLUDED_INTEGRATIONS: ["test"]})
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    rows = {row["name"]: row["how"] for row in coord.dashboard_excluded_devices()}
    # The broader exclusion covers both, the one picked by hand too.
    assert rows == {"Door Master": "integration", "Old Plug": "integration"}


async def test_the_devices_tab_takes_an_exclusion_back_and_says_where(hass: HomeAssistant, hass_ws_client):
    entry, coord, keep, drop = await _two(hass)
    await _set(hass, entry, **{CONF_EXCLUDED_DEVICES: [drop.id]})
    settings_rows = len(_rows(coord, SYS_OPTIONS_CHANGED))
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/device_exclude", device_id=drop.id, on=False, source="devices_tab")
    assert reply["success"], reply
    await hass.async_block_till_done()
    assert entry.options[CONF_EXCLUDED_DEVICES] == [] and drop.id in coord._watched
    assert [r[SYS_DETAIL] for r in _rows(coord, SYS_DEVICE_PAGE)] == ["no longer excluded, from the Devices tab"]
    assert len(_rows(coord, SYS_OPTIONS_CHANGED)) == settings_rows, "the act also wrote a Settings changed row"
    reply = await _ws(client, type="device_sentinel/device_exclude", device_id=drop.id, on=True, source="elsewhere")
    assert not reply["success"], "an unknown source was accepted"


async def test_an_integration_page_excludes_and_takes_back_with_one_row_each(hass: HomeAssistant, hass_ws_client):
    from custom_components.device_sentinel.const import (
        CONF_FREEZE_MUTED_INTEGRATIONS,
        CONF_MUTED_INTEGRATIONS,
        SYS_INTEGRATION_PAGE,
        SYS_SCOPE,
    )

    entry, coord, keep, drop = await _two(hass, {
        CONF_MUTED_INTEGRATIONS: ["test"], CONF_FREEZE_MUTED_INTEGRATIONS: ["test"],
    })
    client = await hass_ws_client(hass)
    assert coord.dashboard_integration("test")["excluded"] is False
    reply = await _ws(client, type="device_sentinel/integration_exclude", domain="test", on=True)
    assert reply["success"], reply
    await hass.async_block_till_done()
    assert entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["test"]
    assert keep.id not in coord._watched and drop.id not in coord._watched
    # Its mutes are kept, so taking it back loses nothing (rule MUTE-03).
    assert entry.options[CONF_MUTED_INTEGRATIONS] == ["test"]
    assert entry.options[CONF_FREEZE_MUTED_INTEGRATIONS] == ["test"]
    rows = _rows(coord, SYS_INTEGRATION_PAGE)
    assert [(r[SYS_SCOPE], r[SYS_DETAIL]) for r in rows] == [("test", "excluded")]
    assert _rows(coord, SYS_OPTIONS_CHANGED) == [], "the page act also wrote a Settings changed row"
    assert coord.dashboard_integration("test")["excluded"] is True
    # The brief tells it once, saying where it was pressed.
    sentence = coord._system_event_sentence(rows[0])
    title = coord._integration_title("test")
    assert sentence.startswith(f"{title}: excluded, from its integration page, at "), sentence
    reply = await _ws(client, type="device_sentinel/integration_exclude", domain="test", on=False)
    await hass.async_block_till_done()
    assert reply["success"] and entry.options[CONF_EXCLUDED_INTEGRATIONS] == []
    assert keep.id in coord._watched and drop.id in coord._watched
    assert _rows(coord, SYS_INTEGRATION_PAGE)[-1][SYS_DETAIL] == "no longer excluded"
    # The same act twice changes nothing and writes nothing.
    reply = await _ws(client, type="device_sentinel/integration_exclude", domain="test", on=False)
    assert reply["success"] and len(_rows(coord, SYS_INTEGRATION_PAGE)) == 2


async def test_an_integration_page_starts_from_the_default_list(hass: HomeAssistant, hass_ws_client):
    from custom_components.device_sentinel.const import DEFAULT_EXCLUDED_INTEGRATIONS

    keep, _ = register_device(hass, "keep", "Door Master")
    entry = await setup_entry(hass, {})
    assert CONF_EXCLUDED_INTEGRATIONS not in entry.options
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/integration_exclude", domain="test", on=True)
    assert reply["success"], reply
    await hass.async_block_till_done()
    # The default list stood until now, so it is kept beside the new one.
    assert entry.options[CONF_EXCLUDED_INTEGRATIONS] == [*DEFAULT_EXCLUDED_INTEGRATIONS, "test"]


async def test_an_integration_page_refuses_an_unknown_integration_and_a_non_admin(
    hass: HomeAssistant, hass_ws_client, hass_read_only_access_token
):
    entry, coord, keep, drop = await _two(hass)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/integration_exclude", domain="nothing_here", on=True)
    assert reply["error"]["code"] == "not_found"
    reader = await hass_ws_client(hass, hass_read_only_access_token)
    reply = await _ws(reader, type="device_sentinel/integration_exclude", domain="test", on=True)
    assert reply["error"]["code"] == "unauthorized"
    assert entry.options[CONF_EXCLUDED_INTEGRATIONS] == []
