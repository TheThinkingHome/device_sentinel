# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_device_page.py, Version: 0.26.7 (2026-10-19)

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

from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONNECTS_WORDS,
    DATA_DEVICES,
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
from custom_components.device_sentinel.device_addresses import addresses, shown
from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics

from tests.helpers import registry_settled, setup_coordinator, setup_entry

# A real moment for the fixtures' stamps: the storage check refuses
# a time before 2020 as impossible (ruling #544).
TIME_BASE = 1_780_000_000.0

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


def _freeze(coord, device_id, since=TIME_BASE):
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
    ):
        eid = reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{suffix}")
        if eid and reg.async_get(eid).disabled:
            reg.async_update_entity(eid, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    expected = {
        "sensor.device_sentinel_devices_watched": UNIT_DEVICES,
        "sensor.device_sentinel_devices_learned": UNIT_DEVICES,
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

# ==================================================================
# The diagnostics journal and the excluded device's grammar.
# ==================================================================

async def test_excluded_device_keeps_its_grammar(hass: HomeAssistant):
    """An excluded device shows its exclude reason, verdictless."""
    device, entity_id = _register(hass, "e1", "Excluded Sensor")
    entry = await setup_entry(hass, {"muted_devices": [device.id]})
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "21.5")
    assert coord._device_status(device.id) == "Muted (GLB)"


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


# ---------------------------------------------------------------------
# The device page's rows: no data, no row (0.25.5).
#
# A row with nothing to show is left out (James, 10 October 2026). The
# server sends None for a registry field that is empty or only zeros,
# Connects only for a device that does not report on the local network
# as changes happen, and each address under the name of its kind.


# ------------------------------------------------------------ shown


@pytest.mark.parametrize("value", [None, "", "  ", "0", "0.0", "0.0.0", "00", " 0 "])
def test_nothing_or_only_zeros_is_nothing(value):
    assert shown(value) is None


@pytest.mark.parametrize("value,expected", [
    ("2", "2"), ("1.0", "1.0"), ("0x0", "0x0"), ("v0", "v0"), (" Aqara ", "Aqara"), (3, "3"), (0, None),
])
def test_anything_else_is_shown(value, expected):
    assert shown(value) == expected


# ------------------------------------------------------------ addresses


def _device(connections=(), identifiers=()):
    return SimpleNamespace(connections=set(connections), identifiers=set(identifiers))


def test_each_connection_kind_has_its_own_row():
    rows = addresses(_device(connections={
        ("mac", "aa:bb:cc:dd:ee:ff"), ("zigbee", "00:15:8d:00:01"),
        ("bluetooth", "11:22:33:44:55:66"), ("upnp", "uuid:abc"),
    }))
    assert rows == [
        {"label": "MAC Address", "value": "aa:bb:cc:dd:ee:ff"},
        {"label": "Zigbee Address", "value": "00:15:8d:00:01"},
        {"label": "Bluetooth Address", "value": "11:22:33:44:55:66"},
        {"label": "UPnP ID", "value": "uuid:abc"},
    ]


def test_zigbee2mqtt_gives_its_address_in_its_identifier():
    rows = addresses(_device(identifiers={("mqtt", "zigbee2mqtt_0x00158d0001a2b3c4")}))
    assert rows == [{"label": "Zigbee Address", "value": "0x00158d0001a2b3c4"}]


def test_a_zwave_device_shows_its_node():
    rows = addresses(_device(identifiers={("zwave_js", "3967510042-14"), ("zwave_js", "3967510042-14-271:4099:12801")}))
    assert rows == [{"label": "Z-Wave Node", "value": "14"}]


def test_a_matter_device_shows_its_serial_number():
    rows = addresses(_device(identifiers={("matter", "serial_SN12345"), ("matter", "deviceid_ABC-0000000000000004-MatterNodeDevice")}))
    assert rows == [{"label": "Serial Number", "value": "SN12345"}]


def test_one_row_per_kind_and_no_repeats():
    rows = addresses(_device(connections={("mac", "aa:bb"), ("mac", "AA:BB"), ("mac", "cc:dd")}))
    assert rows == [{"label": "MAC Address", "value": "AA:BB, cc:dd"}]


def test_nothing_known_is_no_rows():
    assert addresses(_device()) == []
    assert addresses(None) == []
    assert addresses(_device(connections={("ieee", "x"), ("mac", ""), ("mac", 5)})) == []


def test_odd_registry_values_do_not_raise():
    assert addresses(SimpleNamespace(connections=5, identifiers=7)) == []
    assert addresses(SimpleNamespace(connections={("mac",)}, identifiers={("matter",), ("zwave_js", 4)})) == []


# ------------------------------------------------------------ the page


def _registered(hass, domain, uid, **fields):
    source = MockConfigEntry(domain=domain, title=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, uid)}, name=f"{domain} {uid}", **fields
    )
    er.async_get(hass).async_get_or_create("sensor", domain, uid, device_id=device.id, config_entry=source)
    return device


async def test_zeros_and_blanks_reach_the_page_as_nothing(hass: HomeAssistant):
    device = _registered(hass, "test", "z1", manufacturer="  ", model="0", model_id="", hw_version="0.0")
    coord = await setup_coordinator(hass)
    identity = coord.dashboard_device(device.id)["identity"]
    assert (identity["manufacturer"], identity["model"], identity["model_id"], identity["hw_version"]) == (None,) * 4
    assert identity["addresses"] == []


async def test_connects_only_where_it_says_something(hass: HomeAssistant):
    for domain in ("tuya", "zha", "mqtt"):
        await async_get_integration(hass, domain)
    pushed = _registered(hass, "mqtt", "c1")
    polled = _registered(hass, "zha", "c2")
    cloud = _registered(hass, "tuya", "c3")
    coord = await setup_coordinator(hass)
    await registry_settled(hass)
    assert coord.dashboard_device(pushed.id)["identity"]["connects"] is None
    assert coord.dashboard_device(polled.id)["identity"]["connects"] == CONNECTS_WORDS["local_polling"]
    assert coord.dashboard_device(cloud.id)["identity"]["connects"] == CONNECTS_WORDS["cloud_push"]


def test_the_assumed_state_sentence():
    assert CONNECTS_WORDS["assumed_state"] == "It can't report back, so Home Assistant shows what it last told it."


async def test_a_zigbee2mqtt_device_shows_its_address_on_the_page(hass: HomeAssistant):
    source = MockConfigEntry(domain="mqtt", title="MQTT")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("mqtt", "zigbee2mqtt_0x00158d0001a2b3c4")}, name="Door"
    )
    er.async_get(hass).async_get_or_create("sensor", "mqtt", "door", device_id=device.id, config_entry=source)
    coord = await setup_coordinator(hass)
    identity = coord.dashboard_device(device.id)["identity"]
    assert identity["addresses"] == [{"label": "Zigbee Address", "value": "0x00158d0001a2b3c4"}]


async def test_a_held_device_has_no_page(hass: HomeAssistant):
    """Removed from Home Assistant, its record held (ruling #622): a
    page would offer actions on a device that is not there."""
    device = _registered(hass, "test", "h1")
    coord = await setup_coordinator(hass)
    dr.async_get(hass).async_remove_device(device.id)
    await registry_settled(hass)
    assert device.id in coord.data[DATA_DEVICES]
    assert coord.dashboard_device(device.id) is None
