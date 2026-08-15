# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_exclusions.py, Version: 0.13.2 (2026-08-13)

"""Exclusion: watched and recorded, but not judged or reported.

An excluded device keeps its clock and statistics and never stops being
observed; exclusion only suppresses judgment and reporting, and the
STATUS column names why. Exclusion comes in a global kind and three
per-family kinds (battery, signal, freeze), applies live through
options with no restart, and respects the primary owner for an
integration-level exclude so a multi-homed device is caught only by
its owning domain. The exclude pickers tag each option with its
integration so two devices sharing a friendly name can be told apart.
This file holds the exclusion surface, the STATUS column, the live
application, the disambiguated pickers, and the priority ladder:
integration over label over device over entity, broadest first, with a
pick that a broader kind covers pruned on save, plus the retirement of
dead option keys that no code reads.
"""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.config_flow import (
    DeviceSentinelOptionsFlow,
    _devices_covered_by,
)
from custom_components.device_sentinel.const import (
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_BATTERY_EXCLUDED_INTEGRATIONS,
    CONF_BATTERY_EXCLUDED_LABELS,
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_IGNORED_INTEGRATIONS,
    CONF_EXCLUDED_LABELS,
    CONF_FREEZE_EXCLUDED_DEVICES,
    DATA_DEVICES,
    DEAD_OPTION_KEYS,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
    STARTUP_GRACE_SECONDS,
)
from custom_components.device_sentinel.coordinator import _new_device_record

from tests.helpers import setup_coordinator, setup_entry

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


# ------------------------------------------ the global exclude surface

async def test_excluded_device_keeps_learning_never_reported(
    hass: HomeAssistant, freezer
):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, battery_eid = _battery_device(hass, source, 1)
    coord = await setup_coordinator(
        hass, {CONF_EXCLUDED_DEVICES: [device.id]}
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
    assert coord._excluded_devices[device.id] == "device"


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

    # Excluding the tracker does not catch the camera.
    entry = await setup_entry(
        hass, {CONF_EXCLUDED_INTEGRATIONS: ["router_tracker"]}
    )
    coord = entry.runtime_data
    assert device.id not in coord._excluded_devices

    # Excluding the owner does, applied live through options.
    hass.config_entries.async_update_entry(
        entry,
        options={CONF_EXCLUDED_INTEGRATIONS: ["camera_brand"]},
    )
    await hass.async_block_till_done()
    assert coord._excluded_devices[device.id] == "integration"


async def test_classification_shows_excluded(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _battery_device(hass, source, 4)
    coord = await setup_coordinator(
        hass, {CONF_EXCLUDED_DEVICES: [device.id]}
    )
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/classification.md")
    ).read()
    # One combined table: the excluded device carries a Watched
    # check and names why in the EXCLUDED column.
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
        hass, {CONF_BATTERY_EXCLUDED_DEVICES: [dropped.id]}
    )

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
        hass, {CONF_BATTERY_EXCLUDED_INTEGRATIONS: ["mobile_app"]}
    )

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

    hass.states.async_set(eid, "5")
    await hass.async_block_till_done()
    assert coord.battery_low_count == 1

    hass.config_entries.async_update_entry(
        entry, options={CONF_BATTERY_EXCLUDED_DEVICES: [device.id]}
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


# ----------------------------------- exclusion relationship + STATUS

async def test_globally_excluded_device_is_not_judged(hass: HomeAssistant):
    """A globally excluded device gets no verdict: the sweep skips it,
    rather than computing a verdict that the report then hides."""
    device = _register(hass, "gx", "Excluded Ghost")
    coord = await setup_coordinator(hass)
    # Exclude it globally.
    hass.config_entries.async_update_entry(
        coord.entry, options={CONF_EXCLUDED_DEVICES: [device.id]}
    )
    coord._excluded_devices[device.id] = "device"
    record = _ghost_record()
    coord.data["devices"][device.id] = record
    now = 1_784_600_000.0
    assert coord._device_down_category(device.id, record, now) is None


async def test_status_reads_the_exclusion_state(hass: HomeAssistant):
    """STATUS is reported when nothing excludes, global when globally
    excluded (alone), and the section tags otherwise."""
    device = _register(hass, "st", "Status Device")
    coord = await setup_coordinator(hass)
    # Nothing excludes: Reported.
    assert coord._device_status(device.id) == "Reported"

    # Section excludes: tags, no global.
    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            CONF_BATTERY_EXCLUDED_DEVICES: [device.id],
            CONF_FREEZE_EXCLUDED_DEVICES: [device.id],
        },
    )
    status = coord._device_status(device.id)
    assert status == "Excluded (BAT, FRZ)"
    assert "GLB" not in status

    # Global exclude wins and shows alone.
    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            CONF_EXCLUDED_DEVICES: [device.id],
            CONF_BATTERY_EXCLUDED_DEVICES: [device.id],
        },
    )
    coord._excluded_devices[device.id] = "device"
    assert coord._device_status(device.id) == "Excluded (GLB)"


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
        hass, {CONF_IGNORED_INTEGRATIONS: []}
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
        hass, {CONF_IGNORED_INTEGRATIONS: []}
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
    entry = await setup_entry(hass, {CONF_IGNORED_INTEGRATIONS: []})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    assert result["step_id"] == "exclusions"
    schema = result["data_schema"].schema
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


# The pure coverage helpers, where the ruling lives.


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
    the proof ruling #45 requires before dropping a pick.
    """

    def __init__(self, ids: set[str]):
        self._ids = ids

    def async_get(self, device_id: str):
        return object() if device_id in self._ids else None


def test_prune_drops_superseded_device_pick():
    rows = [
        {"device_id": "a", "integration": "spook", "labels": frozenset()},
    ]
    pruned = DeviceSentinelOptionsFlow._pruned_exclusion_input(
        {
            CONF_EXCLUDED_INTEGRATIONS: ["spook"],
            CONF_EXCLUDED_LABELS: [],
            CONF_EXCLUDED_DEVICES: ["a"],
        },
        rows,
        _FakeRegistry({row['device_id'] for row in rows}),
    )
    assert pruned[CONF_EXCLUDED_DEVICES] == []


def test_prune_settles_the_whole_ladder_in_one_save():
    """An integration tick clears the device pick below it in the same
    save, so no device pick survives under a parent that hides it."""
    device_rows = [
        {"device_id": "a", "integration": "spook", "labels": frozenset()},
    ]
    pruned = DeviceSentinelOptionsFlow._pruned_exclusion_input(
        {
            CONF_EXCLUDED_INTEGRATIONS: ["spook"],
            CONF_EXCLUDED_LABELS: [],
            CONF_EXCLUDED_DEVICES: ["a"],
        },
        device_rows,
        _FakeRegistry({row['device_id'] for row in device_rows}),
    )
    assert pruned[CONF_EXCLUDED_DEVICES] == []


def test_prune_keeps_picks_no_broader_kind_covers():
    """Device 'a' is excluded but no broader kind covers it, so its
    pick stands. A device an integration exclude reached would prune,
    because integration is the broader kind."""
    device_rows = [
        {"device_id": "a", "integration": "zha", "labels": frozenset()},
        {"device_id": "b", "integration": "zha", "labels": frozenset()},
    ]
    pruned = DeviceSentinelOptionsFlow._pruned_exclusion_input(
        {
            CONF_EXCLUDED_INTEGRATIONS: ["spook"],
            CONF_EXCLUDED_LABELS: [],
            CONF_EXCLUDED_DEVICES: ["a"],
        },
        device_rows,
        _FakeRegistry({row['device_id'] for row in device_rows}),
    )
    assert pruned[CONF_EXCLUDED_DEVICES] == ["a"]


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
            CONF_BATTERY_EXCLUDED_INTEGRATIONS: ["mobile_app"],
            CONF_BATTERY_EXCLUDED_LABELS: [],
            CONF_BATTERY_EXCLUDED_DEVICES: ["a"],
        },
        rows,
        _FakeRegistry({row['device_id'] for row in rows}),
    )
    assert pruned[CONF_BATTERY_EXCLUDED_DEVICES] == []


# The live coordinator, where the ruling has to hold.


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
        hass, {CONF_BATTERY_EXCLUDED_LABELS: [label.label_id]}
    )
    coord = entry.runtime_data
    assert coord._battery_excluded(device.id)
    # Battery only: the device keeps every other kind of watching.
    assert device.id not in coord._excluded_devices


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
            CONF_EXCLUDED_INTEGRATIONS: ["test"],
            CONF_EXCLUDED_DEVICES: [device.id],
        },
    )
    assert entry.runtime_data._excluded_devices[device.id] == "integration"


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
    assert device.id not in entry.runtime_data._excluded_devices


async def test_dead_option_keys_are_cleared_at_setup(hass: HomeAssistant):
    """A key no code reads must not survive in the options, where it
    would read as a live setting quietly doing nothing."""
    entry = await setup_entry(
        hass,
        {
            "excluded_areas": ["area_1"],
            "excluded_entities": ["image.some_screenshot"],
            CONF_EXCLUDED_LABELS: ["ice"],
        },
    )
    await hass.async_block_till_done()
    for key in DEAD_OPTION_KEYS:
        assert key not in entry.options
    # Only the retired keys go; live settings are untouched.
    assert entry.options[CONF_EXCLUDED_LABELS] == ["ice"]


async def test_retired_notification_keys_are_cleared(hass: HomeAssistant):
    """The 0.3.3 notification shapes that 0.3.4 replaced. They read as
    live settings in every diagnostics download for nine releases,
    which is the rot ruling 49 exists to stop. Cleared at 0.3.13.
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
            CONF_EXCLUDED_LABELS: ["ice"],
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
    assert entry.options[CONF_EXCLUDED_LABELS] == ["ice"]


async def test_setup_survives_when_nothing_is_dead(hass: HomeAssistant):
    entry = await setup_entry(hass, {CONF_EXCLUDED_LABELS: ["ice"]})
    assert entry.options[CONF_EXCLUDED_LABELS] == ["ice"]


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
    entry = await setup_entry(hass, {CONF_EXCLUDED_DEVICES: [device.id]})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    assert result["step_id"] == "exclusions"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_EXCLUDED_INTEGRATIONS: ["test"],
            CONF_EXCLUDED_LABELS: [],
            CONF_EXCLUDED_DEVICES: [device.id],
        },
    )
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options[CONF_EXCLUDED_DEVICES] == []
    assert entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["test"]


async def test_options_flow_hides_covered_devices(hass: HomeAssistant):
    """A device an integration exclude already reaches is gone from
    the picker, so the list only ever offers a decision still worth
    making."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _ladder_device(hass, source, 7)
    entry = await setup_entry(
        hass, {CONF_EXCLUDED_INTEGRATIONS: ["test"]}
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    schema = result["data_schema"].schema
    device_key = next(
        key for key in schema if str(key) == CONF_EXCLUDED_DEVICES
    )
    offered = {
        option["value"]
        for option in schema[device_key].config["options"]
    }
    assert device.id not in offered


async def test_options_flow_menu_is_work_ordered(hass: HomeAssistant):
    """Notifications leads from 0.3.12: it is the one section a new
    installation must visit for alerts to reach a phone."""
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["menu_options"] == [
        "notifications",
        "exclusions",
        "battery",
        "signal",
        "freeze",
        "advanced",
    ]
