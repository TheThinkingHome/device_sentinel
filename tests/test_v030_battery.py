# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.3.10 (2026-07-16)

"""0.3.0 tests: battery detection."""


from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_LOW_THRESHOLD,
    DATA_DEVICES,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
)

DOMAIN = "device_sentinel"


def _battery_device(hass, source, index, *, percentage=True, binary=False):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", f"bat{index}")},
        name=f"Battery Device {index}",
    )
    ent_reg = er.async_get(hass)
    entity_ids = {}
    if percentage:
        reg = ent_reg.async_get_or_create(
            "sensor", "test", f"bat{index}_pct",
            device_id=device.id, config_entry=source,
            original_device_class="battery",
        )
        entity_ids["pct"] = reg.entity_id
    if binary:
        reg = ent_reg.async_get_or_create(
            "binary_sensor", "test", f"bat{index}_low",
            device_id=device.id, config_entry=source,
            original_device_class="battery",
        )
        entity_ids["bin"] = reg.entity_id
    return device, entity_ids


async def _setup(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_election_prefers_percentage(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 1, percentage=True, binary=True)
    entry = await _setup(hass)
    coord = entry.runtime_data
    elected_entity, is_binary = coord._battery_entity[device.id]
    assert elected_entity == eids["pct"]
    assert is_binary is False


async def test_binary_fallback_and_on_is_low(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 2, percentage=False, binary=True)
    entry = await _setup(hass)
    coord = entry.runtime_data

    hass.states.async_set(eids["bin"], "on")
    await hass.async_block_till_done()
    assert coord.data[DATA_DEVICES][device.id][DEV_BATTERY_LOW] is True
    assert coord.battery_low_count == 1

    hass.states.async_set(eids["bin"], "off")
    await hass.async_block_till_done()
    assert coord.battery_low_count == 0


async def test_threshold_and_hysteresis(hass: HomeAssistant):
    """Flag at or below 20; clear only above 22 (threshold + 2)."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 3)
    entry = await _setup(hass)
    coord = entry.runtime_data
    rec = coord.data[DATA_DEVICES][device.id]

    hass.states.async_set(eids["pct"], "50")
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is False

    hass.states.async_set(eids["pct"], "20")  # at threshold: flag
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is True
    assert rec[DEV_BATTERY_SINCE] is not None
    since_first = rec[DEV_BATTERY_SINCE]

    hass.states.async_set(eids["pct"], "21")  # inside margin: stays low
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is True
    assert rec[DEV_BATTERY_SINCE] == since_first  # since carried

    hass.states.async_set(eids["pct"], "22")  # past margin: recovers
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is False
    assert rec[DEV_BATTERY_SINCE] is None

    hass.states.async_set(eids["pct"], "19")  # re-crossing restamps
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is True
    assert rec[DEV_BATTERY_SINCE] != since_first


async def test_unavailable_battery_holds_verdict(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 4)
    entry = await _setup(hass)
    coord = entry.runtime_data
    rec = coord.data[DATA_DEVICES][device.id]

    hass.states.async_set(eids["pct"], "15")
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is True

    hass.states.async_set(eids["pct"], "unavailable")
    await hass.async_block_till_done()
    assert rec[DEV_BATTERY_LOW] is True  # verdict held; liveness is Step 4


async def test_options_change_applies_live(hass: HomeAssistant):
    """Sliding the threshold above a real cell flags it immediately."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 5)
    entry = await _setup(hass)
    coord = entry.runtime_data

    hass.states.async_set(eids["pct"], "32")
    await hass.async_block_till_done()
    assert coord.battery_low_count == 0

    hass.config_entries.async_update_entry(
        entry, options={CONF_LOW_THRESHOLD: 35}
    )
    await hass.async_block_till_done()
    assert coord.battery_low_count == 1

    hass.config_entries.async_update_entry(
        entry, options={CONF_LOW_THRESHOLD: 20}
    )
    await hass.async_block_till_done()
    assert coord.battery_low_count == 0


async def test_list_shape_and_order(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    d1, e1 = _battery_device(hass, source, 6)
    d2, e2 = _battery_device(hass, source, 7)
    entry = await _setup(hass)
    coord = entry.runtime_data

    hass.states.async_set(e1["pct"], "10")
    hass.states.async_set(e2["pct"], "5")
    await hass.async_block_till_done()

    state = hass.states.get("sensor.device_sentinel_battery_low")
    assert state is not None
    coord._notify()
    await hass.async_block_till_done()
    # Low Batteries merges the old count and list: state is the count,
    # rows and thresholds ride in attributes.
    state = hass.states.get("sensor.device_sentinel_battery_low")
    assert state.state == "2"
    rows = state.attributes["devices"]
    assert [r["name"] for r in rows] == [
        "Battery Device 6", "Battery Device 7",
    ]
    row = rows[0]
    assert row["kind"] == "device"
    assert row["level"] == 10.0
    assert row["since"] is not None
    assert row["area"] == "Unassigned"
    assert state.attributes["low_threshold"] == 20.0
    assert state.attributes["clear_margin"] == 2


async def test_since_survives_reload(hass: HomeAssistant, hass_storage):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 8)
    entry = await _setup(hass)
    coord = entry.runtime_data

    hass.states.async_set(eids["pct"], "12")
    await hass.async_block_till_done()
    since = coord.data[DATA_DEVICES][device.id][DEV_BATTERY_SINCE]
    assert since is not None
    await coord._store.async_save(coord.data)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord2 = entry.runtime_data
    assert coord2.data[DATA_DEVICES][device.id][DEV_BATTERY_SINCE] == since
    assert coord2.battery_low_count == 1


async def test_number_entity_sets_threshold_live(hass: HomeAssistant):
    """The dashboard slider writes the same setting as the dialog."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, 9)
    entry = await _setup(hass)
    coord = entry.runtime_data

    hass.states.async_set(eids["pct"], "32")
    await hass.async_block_till_done()
    assert coord.battery_low_count == 0

    slider = hass.states.get(
        "number.device_sentinel_battery_threshold"
    )
    assert slider is not None
    assert float(slider.state) == 20.0

    await hass.services.async_call(
        "number", "set_value",
        {
            "entity_id": "number.device_sentinel_battery_threshold",
            "value": 35,
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert coord.low_threshold == 35.0
    assert coord.battery_low_count == 1
