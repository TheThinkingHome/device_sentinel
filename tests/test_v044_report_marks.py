# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.4.4 (2026-07-19)

"""0.4.4 tests: the marked report columns and the three buttons.

Covers the three marks in one SIGNAL LOWS cell (bold floor, struck
trim, italic rail), the new BAT LEVEL column with at-or-below-threshold
bolding, the k values shown in the headers, and the split of the enable
assist into three buttons.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_SIGNAL_SENSITIVITY,
    DEV_BATTERY_DAILY,
    DEV_SIGNAL_DAILY_MIN,
)

DOMAIN = "device_sentinel"


async def _coordinator(hass, options=None):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "marks")},
        name="Marks Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "marks",
        suggested_object_id="marks_linkquality",
        device_id=device.id, config_entry=source,
    )
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data, device.id


def _row(hass, name="Marks Device"):
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    return next(
        line for line in text.splitlines() if name in line
    )


async def test_signal_lows_shows_all_three_marks(hass: HomeAssistant):
    """One cell, all three states: the floor bold, the trimmed low
    struck, the rail value italic. Eight readings, one a rail (255)
    and one an anomaly (40); at a week the ladder trims the single
    lowest non-rail value, so 40 is struck and 87 is the floor."""
    coord, device_id = await _coordinator(hass)
    coord.data["devices"][device_id][DEV_SIGNAL_DAILY_MIN] = [
        88.0, 90.0, 255.0, 40.0, 92.0, 89.0, 91.0, 87.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)
    row = _row(hass)
    assert "**87** 91 89 92 ~~40~~ *255* 90 88" in row


async def test_battery_column_bolds_at_or_below_threshold(
    hass: HomeAssistant,
):
    """The battery series, newest first, with any level at or below
    the low threshold bold. Default threshold is 20, so 18 and 15 are
    bold and 22 is not."""
    coord, device_id = await _coordinator(hass)
    coord.data["devices"][device_id][DEV_BATTERY_DAILY] = [
        95.0, 60.0, 22.0, 18.0, 15.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)
    row = _row(hass)
    assert "**15** **18** 22 60 95" in row


async def test_headers_show_k_and_threshold(hass: HomeAssistant):
    """The column headers carry the tunables: GAPS its fixed trim k,
    SIGNAL LOWS the slider value, BAT LEVEL the live threshold."""
    coord, _ = await _coordinator(hass, {CONF_SIGNAL_SENSITIVITY: 1})
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    header = next(line for line in text.splitlines() if "DEVICE | DAYS" in line)
    assert "SIGNAL LOWS (K=1)" in header
    assert "GAPS (K=" in header
    assert "BAT LEVEL (floor 20%)" in header
    # The retired columns are gone.
    assert "LINE" not in header
    assert "FAMILY" not in header
    assert "SIG MIN" not in header

    # Every data row must have exactly as many cells as the header,
    # nine, so a dropped column can never leave the rows misaligned.
    def _cells(line: str) -> int:
        return len([c for c in line.strip().strip("|").split("|")])

    header_cells = _cells(header)
    assert header_cells == 9, header_cells
    data_rows = [
        line
        for line in text.splitlines()
        if line.startswith("| ")
        and "DEVICE | DAYS" not in line
        and not line.startswith("|---")
    ]
    for line in data_rows:
        assert _cells(line) == header_cells, line


async def test_three_enable_buttons_exist_and_press(hass: HomeAssistant):
    """The enable assist is three buttons now, one per diagnostic
    kind, each pressable without error."""
    await _coordinator(hass)
    for entity_id in (
        "button.device_sentinel_enable_signals",
        "button.device_sentinel_enable_last_seen",
        "button.device_sentinel_enable_battery",
    ):
        assert hass.states.get(entity_id) is not None, entity_id
        await hass.services.async_call(
            "button", "press",
            {"entity_id": entity_id},
            blocking=True,
        )
