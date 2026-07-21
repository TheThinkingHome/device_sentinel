# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v062_reporting_section.py, Version: 0.6.2 (2026-07-21)

"""0.6.2 tests: the Reporting Devices section and the STATUS revert.

Every fault in one section, all three families, grouped freeze then
battery then signal, alphabetical within each. Acknowledged items are
shown, tagged acknowledged: this is diagnostics, not notification. A
device in two families appears in both, each line with that family's
own age; the header count is distinct devices. The STATUS cell is
back to the plain 0.6.0 grammar, the icon having moved here.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
)

DOMAIN = "device_sentinel"

OPEN_TAG = "[\u25cb open]"
ACKED_TAG = "[\u2713 acknowledged]"
REMOVED_TAG = "[\u2717 removed from list]"


def _register(hass, uid, name, battery=False):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    ent_reg = er.async_get(hass)
    plain = ent_reg.async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    if battery:
        ent_reg.async_get_or_create(
            "sensor", "test", f"{uid}_pct",
            device_id=device.id, config_entry=source,
            original_device_class="battery",
        )
    return device, plain.entity_id


async def _coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _freeze(coord, device_id, since=1_000_000.0):
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = since - 10.0
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = since


def _battery_low(coord, device_id, level=14.0,
                 since="2026-07-20T15:02:00+00:00"):
    record = coord.data["devices"][device_id]
    record[DEV_BATTERY_LOW] = True
    record[DEV_BATTERY_VALUE] = level
    record[DEV_BATTERY_SINCE] = since


async def test_all_three_families_grouped_and_sorted(
    hass: HomeAssistant,
):
    """Freeze then battery, alphabetical inside each group, the
    header counting distinct devices."""
    d1, e1 = _register(hass, "r1", "Zebra Frozen")
    d2, e2 = _register(hass, "r2", "Apple Frozen")
    d3, e3 = _register(hass, "r3", "Mango Battery", battery=True)
    coord = await _coordinator(hass)
    for eid in (e1, e2, e3):
        hass.states.async_set(eid, "on")
    _freeze(coord, d1.id)
    _freeze(coord, d2.id)
    _battery_low(coord, d3.id)
    coord._sync_problem_list()

    text = "\n".join(coord._reporting_lines())
    assert "## Reporting Devices (3)" in text
    assert text.index("### Freeze") < text.index("### Battery")
    assert text.index("Apple Frozen") < text.index("Zebra Frozen")
    assert "(14%)" in text
    assert text.count(OPEN_TAG) == 3


async def test_acknowledged_item_still_shows_tagged(
    hass: HomeAssistant,
):
    """The whole reason for the section: the checkbox silences the
    phone, never the diagnostics."""
    device, eid = _register(hass, "a1", "Acked Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")

    text = "\n".join(coord._reporting_lines())
    assert "Acked Sensor" in text
    assert ACKED_TAG in text


async def test_hand_deleted_item_shows_removed_tag(
    hass: HomeAssistant,
):
    """Still reporting, removed from the list by a human: the fault
    stays visible here with the removed tag until the sync re-adds."""
    device, eid = _register(hass, "x1", "Orphan Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_delete([uid])

    text = "\n".join(coord._reporting_lines())
    assert "Orphan Sensor" in text
    assert REMOVED_TAG in text


async def test_two_family_device_appears_in_both(hass: HomeAssistant):
    """One device, two lines, each family carrying its own age, both
    wearing the device's single todo tag."""
    device, eid = _register(hass, "b1", "Doubled Sensor", battery=True)
    coord = await _coordinator(hass)
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    _battery_low(coord, device.id)
    coord._sync_problem_list()

    text = "\n".join(coord._reporting_lines())
    assert "## Reporting Devices (1)" in text  # distinct devices
    assert text.count("Doubled Sensor") == 2
    assert "### Freeze" in text and "### Battery" in text
    assert text.count(OPEN_TAG) == 2


async def test_empty_section_is_all_clear(hass: HomeAssistant):
    coord = await _coordinator(hass)
    coord._sync_problem_list()
    text = "\n".join(coord._reporting_lines())
    assert "## Reporting Devices (0)" in text
    assert "low on battery" in text


async def test_status_cell_reverted_to_plain_grammar(
    hass: HomeAssistant,
):
    """The 0.6.1 icon is gone from STATUS: a faulted device reads
    plain Reported there, and the icon lives in Reporting Devices."""
    device, eid = _register(hass, "s1", "Plain Status")
    coord = await _coordinator(hass)
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    assert coord._device_status(device.id) == "Reported"


async def test_section_reaches_the_written_report(hass: HomeAssistant):
    device, eid = _register(hass, "w1", "Written Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_add_executor_job(coord._write_reports, "test")
    path = hass.config.path("device_sentinel", "device_telemetry.md")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert "## Reporting Devices (1)" in text
    assert OPEN_TAG in text
    assert "Down devices" not in text
