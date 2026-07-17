# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.3.12 (2026-07-17)

"""0.3.12 tests: the device page a person actually reads.

Home Assistant gives entities no helper text on the device page, so a
name and its state are the whole explanation. These tests pin the
three things that follow from that: Status answers its own name
rather than publishing a build artifact, every count carries a unit,
and the renames land on one set of entity ids for every install
rather than splitting old installs from new.

The migration is the load-bearing one. A rename changes the entity id
a fresh install derives but never one already in the registry, so
without it a 0.3.11 install would keep sensor.device_sentinel_coverage
forever while a new install got devices_watched, and no documentation
could name an id true for both.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEAD_ENTITY_SENTINEL_TYPES,
    STATUS_LEARNING,
    STATUS_WATCHING,
    UNIT_BATTERIES,
    UNIT_DEVICES,
)

DOMAIN = "device_sentinel"


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# Status says something a person can read.


async def test_status_reads_learning_before_any_device_is_established(
    hass: HomeAssistant,
):
    await _setup(hass)
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
    entry = await _setup(hass)
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
    await _setup(hass)
    state = hass.states.get("sensor.device_sentinel_status")
    assert state.attributes["setup_count"] == 1
    assert state.attributes["storage_healthy"] is True


# Counts carry units.


async def test_every_count_sensor_carries_a_unit(hass: HomeAssistant):
    await _setup(hass)
    expected = {
        "sensor.device_sentinel_devices_watched": UNIT_DEVICES,
        "sensor.device_sentinel_devices_learned": UNIT_DEVICES,
        "sensor.device_sentinel_service_devices_ignored": UNIT_DEVICES,
        "sensor.device_sentinel_battery_low_count": UNIT_BATTERIES,
        "sensor.device_sentinel_battery_low_list": UNIT_BATTERIES,
    }
    for entity_id, unit in expected.items():
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.attributes["unit_of_measurement"] == unit, entity_id


async def test_status_carries_no_unit(hass: HomeAssistant):
    """Status is a word now, so a unit would be nonsense."""
    await _setup(hass)
    state = hass.states.get("sensor.device_sentinel_status")
    assert "unit_of_measurement" not in state.attributes


# The renames land where the spec says.


async def test_renamed_entities_exist_at_their_new_ids(
    hass: HomeAssistant,
):
    await _setup(hass)
    for entity_id in (
        "sensor.device_sentinel_devices_watched",
        "sensor.device_sentinel_devices_learned",
        "sensor.device_sentinel_service_devices_ignored",
        "todo.device_sentinel_problem_list",
        "button.device_sentinel_scan_and_enable_signal_and"
        "_last_seen_entities",
    ):
        assert hass.states.get(entity_id) is not None, entity_id


async def test_old_entity_ids_are_gone(hass: HomeAssistant):
    await _setup(hass)
    for entity_id in (
        "sensor.device_sentinel_coverage",
        "sensor.device_sentinel_learning_progress",
        "sensor.device_sentinel_classification",
        "todo.device_sentinel",
        "button.device_sentinel_enable_signal_entities",
    ):
        assert hass.states.get(entity_id) is None, entity_id


# The migration: one set of ids for every install.


async def test_a_pre_0312_install_is_migrated_onto_the_new_ids(
    hass: HomeAssistant,
):
    """Seed the registry as 0.3.11 left it, then set up and watch the
    old ids move rather than sit alongside the new ones."""
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_coverage",
        suggested_object_id="device_sentinel_coverage",
        config_entry=entry,
    )
    assert old.entity_id == "sensor.device_sentinel_coverage"

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert ent_reg.async_get("sensor.device_sentinel_coverage") is None
    moved = ent_reg.async_get("sensor.device_sentinel_devices_watched")
    assert moved is not None
    assert moved.unique_id == f"{entry.entry_id}_coverage"


async def test_migration_leaves_another_entry_alone(hass: HomeAssistant):
    """Only this config entry's entities move. An id that looks like
    ours but belongs elsewhere is not ours to rename."""
    other = MockConfigEntry(domain="test", title="Other")
    other.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "sensor",
        "test",
        "someone_elses_coverage",
        suggested_object_id="device_sentinel_coverage",
        config_entry=other,
    )
    await _setup(hass)
    survivor = ent_reg.async_get("sensor.device_sentinel_coverage")
    assert survivor is not None
    assert survivor.platform == "test"


# The retirement leaves no dead row.


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
