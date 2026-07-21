# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v063_hardening.py, Version: 0.6.3 (2026-07-21)

"""0.6.3 tests: the four audit hardening fixes.

S1 report cells escape pipes and newlines in device names. C1 the
hot-path handlers survive an entity missing from the map. C2 a since
ahead of the clock prints a zero age, never a negative one. C3 a
signal line whose name lookup misses falls back to the device id.
"""

from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
)

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


async def test_pipe_in_name_stays_in_one_cell(hass: HomeAssistant):
    """S1: a pipe in a device name is escaped everywhere it appears,
    so the tables keep their column count."""
    device, eid = _register(hass, "p1", "Weird | Name")
    coord = await _coordinator(hass)
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_add_executor_job(coord._write_reports, "test")

    telemetry = open(
        hass.config.path("device_sentinel", "device_telemetry.md"),
        encoding="utf-8",
    ).read()
    classification = open(
        hass.config.path("device_sentinel", "classification.md"),
        encoding="utf-8",
    ).read()
    assert "Weird \\| Name" in telemetry
    assert "Weird \\| Name" in classification
    assert "Weird | Name" not in telemetry
    # The table rows containing it still parse to the right width.
    for line in classification.splitlines():
        if "Weird" in line and line.startswith("|"):
            assert line.count("|") - line.count("\\|") == 7


async def test_newline_in_name_is_flattened(hass: HomeAssistant):
    """S1: a newline in a name cannot break a report row."""
    assert (
        __import__(
            "custom_components.device_sentinel.coordinator",
            fromlist=["DeviceSentinelCoordinator"],
        ).DeviceSentinelCoordinator._report_cell("Two\nLines")
        == "Two Lines"
    )


async def test_hot_path_survives_unmapped_entity(hass: HomeAssistant):
    """C1: a state event for an entity not in the map returns quietly
    instead of raising."""
    coord = await _coordinator(hass)
    fake = SimpleNamespace(
        data={
            "entity_id": "sensor.never_mapped",
            "new_state": SimpleNamespace(state="42"),
        }
    )
    coord._on_state_changed(fake)
    coord._on_state_reported(fake)


async def test_future_since_prints_zero_age(hass: HomeAssistant):
    """C2: a since ahead of the clock clamps to zero, no negatives."""
    device, eid = _register(hass, "f1", "Future Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(eid, "21.5")
    from homeassistant.util import dt as dt_util
    _freeze(coord, device.id, since=dt_util.utcnow().timestamp() + 3600)
    coord._sync_problem_list()
    text = "\n".join(coord._reporting_lines())
    assert "for 0m" in text
    assert "-" not in text.split("for ")[1].split(" ")[0]


async def test_signal_line_falls_back_to_device_id(hass: HomeAssistant):
    """C3: a missing name prints the device id, never None."""
    device, eid = _register(hass, "n1", "Named Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    # Blank the name map to force the miss.
    coord._device_names = {}
    rows = [
        {"name": None, "device_id": device.id, "kind": "rail"},
    ]
    # Exercise the formatting path through the section by patching
    # the property's source list.
    original = type(coord).signal_problem_list
    try:
        type(coord).signal_problem_list = property(lambda self: rows)
        text = "\n".join(coord._reporting_lines())
    finally:
        type(coord).signal_problem_list = original
    assert device.id in text
    assert "**None**" not in text
