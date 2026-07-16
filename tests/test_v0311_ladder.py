# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.3.11 (2026-07-16)

"""0.3.11 tests: the exclusion priority ladder and the area retirement.

The ladder is integration, label, device, entity, broadest first.
Each picker lists only what the kinds above it have not caught, and a
pick a broader kind covers is pruned from stored options on save. The
prune is silent and permanent by ruling, so these tests pin the drop
rather than treating it as incidental.

Pruning is proven against the flow's own pure helpers as well as
through a real options flow, because the helpers are where the ruling
lives and a schema change should not be able to quietly retire it.
"""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.config_flow import (
    DeviceSentinelOptionsFlow,
    _devices_covered_by,
    _entities_covered_by,
)
from custom_components.device_sentinel.const import (
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_BATTERY_EXCLUDED_INTEGRATIONS,
    CONF_BATTERY_EXCLUDED_LABELS,
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_ENTITIES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_EXCLUDED_LABELS,
    DEAD_OPTION_KEYS,
)

DOMAIN = "device_sentinel"


async def _setup(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _device(hass, source, index, name=None):
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


def test_entity_covered_by_integration_label_or_device():
    rows = [
        {
            "entity_id": "sensor.one",
            "device_id": "a",
            "integration": "spook",
            "labels": frozenset(),
        },
        {
            "entity_id": "sensor.two",
            "device_id": "b",
            "integration": "zha",
            "labels": frozenset({"ice"}),
        },
        {
            "entity_id": "sensor.three",
            "device_id": "c",
            "integration": "zha",
            "labels": frozenset(),
        },
        {
            "entity_id": "sensor.four",
            "device_id": "d",
            "integration": "zha",
            "labels": frozenset(),
        },
    ]
    covered = _entities_covered_by(rows, ["spook"], ["ice"], ["c"])
    assert covered == {"sensor.one", "sensor.two", "sensor.three"}


def test_prune_drops_superseded_device_pick():
    rows = [
        {"device_id": "a", "integration": "spook", "labels": frozenset()},
    ]
    pruned = DeviceSentinelOptionsFlow._pruned_exclusion_input(
        {
            CONF_EXCLUDED_INTEGRATIONS: ["spook"],
            CONF_EXCLUDED_LABELS: [],
            CONF_EXCLUDED_DEVICES: ["a"],
            CONF_EXCLUDED_ENTITIES: [],
        },
        rows,
        [],
    )
    assert pruned[CONF_EXCLUDED_DEVICES] == []


def test_prune_settles_the_whole_ladder_in_one_save():
    """Devices prune first, then entities judge against the pruned
    list, so an integration tick clears both levels below it at once."""
    device_rows = [
        {"device_id": "a", "integration": "spook", "labels": frozenset()},
    ]
    entity_rows = [
        {
            "entity_id": "sensor.one",
            "device_id": "a",
            "integration": "spook",
            "labels": frozenset(),
        },
    ]
    pruned = DeviceSentinelOptionsFlow._pruned_exclusion_input(
        {
            CONF_EXCLUDED_INTEGRATIONS: ["spook"],
            CONF_EXCLUDED_LABELS: [],
            CONF_EXCLUDED_DEVICES: ["a"],
            CONF_EXCLUDED_ENTITIES: ["sensor.one"],
        },
        device_rows,
        entity_rows,
    )
    assert pruned[CONF_EXCLUDED_DEVICES] == []
    assert pruned[CONF_EXCLUDED_ENTITIES] == []


def test_prune_keeps_picks_no_broader_kind_covers():
    """The entity here hangs off a device nobody excluded, so nothing
    above it reaches it and its pick stands. An entity on an excluded
    device would prune, because device is the broader kind."""
    device_rows = [
        {"device_id": "a", "integration": "zha", "labels": frozenset()},
        {"device_id": "b", "integration": "zha", "labels": frozenset()},
    ]
    entity_rows = [
        {
            "entity_id": "sensor.one",
            "device_id": "b",
            "integration": "zha",
            "labels": frozenset(),
        },
    ]
    pruned = DeviceSentinelOptionsFlow._pruned_exclusion_input(
        {
            CONF_EXCLUDED_INTEGRATIONS: ["spook"],
            CONF_EXCLUDED_LABELS: [],
            CONF_EXCLUDED_DEVICES: ["a"],
            CONF_EXCLUDED_ENTITIES: ["sensor.one"],
        },
        device_rows,
        entity_rows,
    )
    assert pruned[CONF_EXCLUDED_DEVICES] == ["a"]
    assert pruned[CONF_EXCLUDED_ENTITIES] == ["sensor.one"]


def test_device_pick_prunes_its_own_entity_picks():
    """Device is broader than entity, so excluding a device drops any
    entity pick beneath it."""
    device_rows = [
        {"device_id": "a", "integration": "zha", "labels": frozenset()},
    ]
    entity_rows = [
        {
            "entity_id": "sensor.one",
            "device_id": "a",
            "integration": "zha",
            "labels": frozenset(),
        },
    ]
    pruned = DeviceSentinelOptionsFlow._pruned_exclusion_input(
        {
            CONF_EXCLUDED_INTEGRATIONS: [],
            CONF_EXCLUDED_LABELS: [],
            CONF_EXCLUDED_DEVICES: ["a"],
            CONF_EXCLUDED_ENTITIES: ["sensor.one"],
        },
        device_rows,
        entity_rows,
    )
    assert pruned[CONF_EXCLUDED_DEVICES] == ["a"]
    assert pruned[CONF_EXCLUDED_ENTITIES] == []


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
    )
    assert pruned[CONF_BATTERY_EXCLUDED_DEVICES] == []


# The live coordinator, where the ruling has to hold.


async def test_battery_label_excludes_the_device(hass: HomeAssistant):
    """A label set from the device's own page reaches battery judgment
    without this dialog being opened."""
    label = lr.async_get(hass).async_create("No Battery")
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _device(hass, source, 1)
    dr.async_get(hass).async_update_device(
        device.id, labels={label.label_id}
    )
    entry = await _setup(
        hass, options={CONF_BATTERY_EXCLUDED_LABELS: [label.label_id]}
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
    device, _ = _device(hass, source, 2, name="Rowed Device")
    dr.async_get(hass).async_update_device(
        device.id, labels={label.label_id}
    )
    entry = await _setup(hass)
    rows = entry.runtime_data.watched_device_rows
    row = next(r for r in rows if r["device_id"] == device.id)
    assert row["name"] == "Rowed Device"
    assert row["integration"] == "test"
    assert row["labels"] == frozenset({label.label_id})


async def test_watched_entity_rows_carry_cascade_facts(
    hass: HomeAssistant,
):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, entity_id = _device(hass, source, 3)
    entry = await _setup(hass)
    rows = entry.runtime_data.watched_entity_rows
    row = next(r for r in rows if r["entity_id"] == entity_id)
    assert row["device_id"] == device.id
    assert row["integration"] == "test"


async def test_integration_reason_wins_over_device_reason(
    hass: HomeAssistant,
):
    """The reason recorded is the one that survives a prune, so a
    device picked under an excluded integration reads as integration
    rather than as a pick that is about to be dropped."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _device(hass, source, 4)
    entry = await _setup(
        hass,
        options={
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
    device, _ = _device(hass, source, 5)
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)

    entry = await _setup(hass, options={"excluded_areas": [area.id]})
    await hass.async_block_till_done()
    assert device.id not in entry.runtime_data._excluded_devices


async def test_dead_option_keys_are_cleared_at_setup(hass: HomeAssistant):
    """A key no code reads must not survive in the options, where it
    would read as a live setting quietly doing nothing."""
    entry = await _setup(
        hass,
        options={"excluded_areas": ["area_1"], CONF_EXCLUDED_LABELS: ["ice"]},
    )
    await hass.async_block_till_done()
    for key in DEAD_OPTION_KEYS:
        assert key not in entry.options
    # Only the retired keys go; live settings are untouched.
    assert entry.options[CONF_EXCLUDED_LABELS] == ["ice"]


async def test_setup_survives_when_nothing_is_dead(hass: HomeAssistant):
    entry = await _setup(hass, options={CONF_EXCLUDED_LABELS: ["ice"]})
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
    device, _ = _device(hass, source, 6)
    entry = await _setup(hass, options={CONF_EXCLUDED_DEVICES: [device.id]})

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
            CONF_EXCLUDED_ENTITIES: [],
        },
    )
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options[CONF_EXCLUDED_DEVICES] == []
    assert entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["test"]


async def test_options_flow_prunes_picks_made_in_the_same_save(
    hass: HomeAssistant,
):
    """The half render-time filtering cannot reach: the form offered
    the entity because nothing covered it when it was drawn, and the
    same submission then excludes its integration. Only the prune on
    save catches this, which is why the prune exists rather than
    trusting the frontend to withhold the field.
    """
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, entity_id = _device(hass, source, 8)
    entry = await _setup(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_EXCLUDED_INTEGRATIONS: ["test"],
            CONF_EXCLUDED_LABELS: [],
            CONF_EXCLUDED_DEVICES: [device.id],
            CONF_EXCLUDED_ENTITIES: [entity_id],
        },
    )
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options[CONF_EXCLUDED_DEVICES] == []
    assert entry.options[CONF_EXCLUDED_ENTITIES] == []


async def test_entity_picker_refuses_a_covered_entity(
    hass: HomeAssistant,
):
    """exclude_entities is a validator, not merely a UI filter: the
    picker rejects an entity a standing exclusion already covers, so
    the ladder holds even against a hand-built submission."""
    import voluptuous as vol

    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, entity_id = _device(hass, source, 9)
    entry = await _setup(
        hass, options={CONF_EXCLUDED_INTEGRATIONS: ["test"]}
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    with pytest.raises(vol.Invalid):
        result["data_schema"](
            {
                CONF_EXCLUDED_INTEGRATIONS: ["test"],
                CONF_EXCLUDED_LABELS: [],
                CONF_EXCLUDED_DEVICES: [],
                CONF_EXCLUDED_ENTITIES: [entity_id],
            }
        )


async def test_options_flow_hides_covered_devices(hass: HomeAssistant):
    """A device an integration exclude already reaches is gone from
    the picker, so the list only ever offers a decision still worth
    making."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, _ = _device(hass, source, 7)
    entry = await _setup(
        hass, options={CONF_EXCLUDED_INTEGRATIONS: ["test"]}
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


async def test_options_flow_menu_is_ladder_ordered(hass: HomeAssistant):
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["menu_options"] == [
        "exclusions",
        "battery",
        "notifications",
    ]
