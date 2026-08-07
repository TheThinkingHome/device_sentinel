# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_device_page.py, Version: 0.12.12 (2026-08-07)

"""The device page a person actually reads, and its diagnostics journal.

Home Assistant gives entities no helper text on the device page, so a
name and its state are the whole explanation. Status answers its own
name (Learning or Watching) rather than publishing a build artifact,
every count sensor carries a unit, and the entity renames land on one
set of ids for every install rather than splitting old from new, with
the migration that makes a rename change only a fresh install's derived
id. A retired sensor is removed from the registry rather than left
showing unavailable, which would read as breakage. Alongside the page,
the additions journal is surfaced in the diagnostics download, and an
excluded device shows its exclude reason without a verdict. This file
holds the status word, the units, the renames, the retirement sweep,
and the diagnostics journal.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEAD_ENTITY_SENTINEL_TYPES,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    STATUS_LEARNING,
    STATUS_WATCHING,
    UNIT_BATTERIES,
    UNIT_DEVICES,
    UNIT_SIGNALS,
)
from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)

from tests.helpers import setup_entry

DOMAIN = "device_sentinel"


def _register(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    ent = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    return device, ent.entity_id


def _freeze(coord, device_id, since=1_000_000.0):
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = since - 10.0
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = since


# ==================================================================
# Status says something a person can read.
# ==================================================================

async def test_status_reads_learning_before_any_device_is_established(
    hass: HomeAssistant,
):
    await setup_entry(hass)
    state = hass.states.get("sensor.device_sentinel_status")
    assert state.state == STATUS_LEARNING


async def test_status_reads_watching_once_a_device_is_established(
    hass: HomeAssistant,
):
    """Learning ends at the first established device, not at the last.

    Partial learning is permanent rather than a phase: every new
    device starts unlearned, so keying the word to "any device
    unlearned" would read Learning forever and tell nobody anything.
    """
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord.learning_buckets  # touch the property before faking it
    original = type(coord).learning_buckets

    try:
        type(coord).learning_buckets = property(
            lambda self: {"observing": 3, "building": 2, "established": 1}
        )
        coord._notify()
        await hass.async_block_till_done()
        state = hass.states.get("sensor.device_sentinel_status")
        assert state.state == STATUS_WATCHING
    finally:
        type(coord).learning_buckets = original


async def test_status_keeps_the_setup_count_as_an_attribute(
    hass: HomeAssistant,
):
    """The count still proves the storage round-trip; it just stopped
    being the thing a user reads."""
    await setup_entry(hass)
    state = hass.states.get("sensor.device_sentinel_status")
    assert state.attributes["setup_count"] == 1
    assert state.attributes["storage_healthy"] is True


# ==================================================================
# Counts carry units.
# ==================================================================

async def test_every_count_sensor_carries_a_unit(hass: HomeAssistant):
    entry = await setup_entry(hass)
    # The count sensors are disabled by default (ruling #239); enable
    # them so their state exists to check.
    reg = er.async_get(hass)
    for suffix in (
        "signal_rails",
        "signal_weak",
        "low_batteries",
        "falling_batteries",
        "frozen_devices",
        "tracked_signals",
        "tracked_batteries",
        "tracked_devices",
    ):
        eid = reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{suffix}")
        if eid and reg.async_get(eid).disabled:
            reg.async_update_entity(eid, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    expected = {
        "sensor.device_sentinel_devices_watched": UNIT_DEVICES,
        "sensor.device_sentinel_devices_learned": UNIT_DEVICES,
        "sensor.device_sentinel_signal_tracked": UNIT_SIGNALS,
        "sensor.device_sentinel_battery_tracked": UNIT_BATTERIES,
        "sensor.device_sentinel_device_tracked": UNIT_DEVICES,
        "sensor.device_sentinel_signal_rails": UNIT_SIGNALS,
        "sensor.device_sentinel_signal_weak": UNIT_SIGNALS,
        "sensor.device_sentinel_battery_falling": UNIT_BATTERIES,
        "sensor.device_sentinel_battery_low": UNIT_BATTERIES,
        "sensor.device_sentinel_device_frozen": UNIT_DEVICES,
    }
    for entity_id, unit in expected.items():
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.attributes["unit_of_measurement"] == unit, entity_id


async def test_status_carries_no_unit(hass: HomeAssistant):
    """Status is a word now, so a unit would be nonsense."""
    await setup_entry(hass)
    state = hass.states.get("sensor.device_sentinel_status")
    assert "unit_of_measurement" not in state.attributes


# ==================================================================
# The renames land where the spec says.
# ==================================================================

async def test_renamed_entities_exist_at_their_new_ids(
    hass: HomeAssistant,
):
    await setup_entry(hass)
    for entity_id in (
        "sensor.device_sentinel_devices_watched",
        "sensor.device_sentinel_devices_learned",
        "todo.device_sentinel_problem_list",
        "button.device_sentinel_enable_signals",
        "button.device_sentinel_enable_last_seen",
        "button.device_sentinel_enable_battery",
    ):
        assert hass.states.get(entity_id) is not None, entity_id


async def test_old_entity_ids_are_gone(hass: HomeAssistant):
    await setup_entry(hass)
    for entity_id in (
        "sensor.device_sentinel_coverage",
        "sensor.device_sentinel_learning_progress",
        "sensor.device_sentinel_classification",
        "todo.device_sentinel",
        "button.device_sentinel_scan_and_enable_signal_and"
        "_last_seen_entities",
    ):
        assert hass.states.get(entity_id) is None, entity_id


# ==================================================================
# The retirement leaves no dead row.
# ==================================================================

async def test_retired_clock_source_is_removed_from_the_registry(
    hass: HomeAssistant,
):
    """Deleting the code does not delete the registry entry, so a
    retired sensor would sit on the page showing unavailable, which
    reads as breakage rather than as removal."""
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    for sentinel_type in DEAD_ENTITY_SENTINEL_TYPES:
        ent_reg.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{entry.entry_id}_{sentinel_type}",
            suggested_object_id=f"device_sentinel_{sentinel_type}",
            config_entry=entry,
        )
    assert ent_reg.async_get("sensor.device_sentinel_clock_source")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert ent_reg.async_get("sensor.device_sentinel_clock_source") is None
    assert hass.states.get("sensor.device_sentinel_clock_source") is None


# ==================================================================
# The diagnostics journal and the excluded device's grammar.
# ==================================================================

async def test_excluded_device_keeps_its_grammar(hass: HomeAssistant):
    """An excluded device shows its exclude reason, verdictless."""
    device, entity_id = _register(hass, "e1", "Excluded Sensor")
    entry = await setup_entry(hass, {"excluded_devices": [device.id]})
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    assert coord._device_status(device.id) == "Excluded (GLB)"


async def test_journal_is_in_diagnostics(hass: HomeAssistant):
    device, entity_id = _register(hass, "j1", "Journal Sensor")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert "todo_journal" in diag
    assert any(
        e["device_id"] == device.id for e in diag["todo_journal"]
    )
    assert any(
        r["device_id"] == device.id for r in diag["todo_items"]
    )
