# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_signal_badday_hostile.py, Version: 0.16.11 (2026-08-21)

"""What the bad-day detector does with data it should never see.

Every case here was found by an adversarial pass on 21 August, and
four of them were live faults before that pass: a corrupt reading in
a baseline raised inside statistics.median, an infinity flagged the
day and rendered as "inf", a string raised on comparison, and a
device whose scale field was absent had the LQI gate applied to a
dBm series, which is a 25 dB demand and therefore deafness.

The scale case was not hypothetical. A 16 August snapshot of the
reference fleet carries a P5 series on 79 devices and a scale on
none of them, seven of those devices negative.

None of this is guarded on the reasoning that the recorder could
never write it. Storage is a JSON file on a person's disk, the Data
Trim tool exists because records do go wrong, and the outages of 20
August came from deciding a case was unreachable instead of checking
it.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_SCALE,
    SIGNAL_SCALE_RSSI,
)

from .helpers import register_device, setup_coordinator

STEADY = [160.0, 162.0, 158.0, 161.0, 160.0, 159.0]


async def _record(hass, key: str, series: list, scale=None) -> dict:
    device, _ = register_device(hass, key, f"Device {key}")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_DAILY_P5] = series
    if scale is not None:
        record[DEV_SIGNAL_SCALE] = scale
    return coord, record


async def test_an_rssi_series_with_no_scale_field_uses_the_decibel_gate(
    hass: HomeAssistant,
):
    """The live case. The sign decides where the field is silent.

    Without this the gate is 25 against a dBm series, so an 8 dB
    collapse reads as nothing at all.
    """
    coord, record = await _record(
        hass, "h1", [-60.0, -61.0, -59.0, -60.0, -61.0, -60.0, -68.0]
    )

    reading = coord.signal_badday(record)
    assert reading is not None
    assert reading["drop_gate"] == 6.0
    assert reading["bad"] is True


async def test_the_record_scale_still_wins_where_it_is_present(
    hass: HomeAssistant,
):
    """The fallback reads the data only where the field is absent."""
    coord, record = await _record(
        hass,
        "h2",
        [-60.0, -61.0, -59.0, -60.0, -61.0, -60.0, -68.0],
        scale=SIGNAL_SCALE_RSSI,
    )

    assert coord.signal_badday(record)["drop_gate"] == 6.0


async def test_a_corrupt_reading_in_the_baseline_does_not_raise(
    hass: HomeAssistant,
):
    """Each of these took down the whole fold before the guard.

    A NaN and an infinity raise inside statistics.median; a string
    raises on comparison. One bad row on one device must cost that
    device's day, not the report.
    """
    for key, poison in (
        ("h3", float("nan")),
        ("h4", float("inf")),
        ("h5", "162"),
        ("h6", True),
        ("h7", None),
    ):
        coord, record = await _record(
            hass, key, [160.0, poison, 158.0, 161.0, 160.0, 159.0, 100.0]
        )
        reading = coord.signal_badday(record)
        assert reading is not None, poison
        assert reading["bad"] is True, poison
        assert reading["fall"] == reading["fall"], poison


async def test_a_corrupt_reading_today_leaves_the_day_unjudged(
    hass: HomeAssistant,
):
    """Unjudged, not innocent. An infinity today would otherwise
    clear every gate and print "inf" on the page."""
    for key, poison in (
        ("h8", float("nan")),
        ("h9", float("-inf")),
        ("h10", "100"),
    ):
        coord, record = await _record(hass, key, STEADY + [poison])
        assert coord.signal_badday(record) is None, poison


async def test_a_reading_from_the_other_scale_is_not_judged(
    hass: HomeAssistant,
):
    """The moment a promotion lands.

    A device whose LQI entity reported first hands the primary block
    over when its RSSI arrives (rulings #285, #286), so today's
    reading can sit on the other side of zero from the days behind
    it. The two are not comparable and the day is left unjudged
    rather than judged from the difference between two measuring
    systems.

    A stored series holding both signs is storage's to deal with,
    once at load (ruling #282), and is not tested here.
    """
    coord, record = await _record(
        hass, "h11", [160.0, 162.0, 158.0, 161.0, 160.0, 159.0, -60.0]
    )
    assert coord.signal_badday(record) is None

    coord, record = await _record(
        hass, "h12", [-60.0, -61.0, -59.0, -60.0, -61.0, -60.0, 160.0]
    )
    assert coord.signal_badday(record) is None


async def test_a_device_whose_signal_improves_is_never_bad(
    hass: HomeAssistant,
):
    """On both scales. A rise is a rise however it is measured."""
    coord, record = await _record(hass, "h13", [100.0] * 6 + [160.0])
    assert coord.signal_badday(record)["bad"] is False

    coord, record = await _record(
        hass, "h14", [-70.0, -71.0, -69.0, -70.0, -71.0, -70.0, -55.0]
    )
    assert coord.signal_badday(record)["bad"] is False


async def test_a_year_of_history_is_judged_without_complaint(
    hass: HomeAssistant,
):
    """The retention ceiling is a year, and the window slices from
    the end, so series length must not reach the arithmetic."""
    coord, record = await _record(
        hass, "h15", [160.0 + (index % 3) for index in range(365)] + [60.0]
    )
    reading = coord.signal_badday(record)
    assert reading is not None
    assert reading["bad"] is True


async def test_an_index_past_the_end_is_unjudged(hass: HomeAssistant):
    """The report walks positions and must not reach off the end."""
    coord, record = await _record(hass, "h16", STEADY + [100.0])
    assert coord.signal_badday(record, 99) is None
    assert coord.signal_badday(record, -99) is None
    assert coord.signal_badday(record, 0) is None


async def test_a_hostile_fleet_still_writes_the_page(
    hass: HomeAssistant,
):
    """End to end. Every poison at once, and the report is written.

    A page that raises leaves the person with yesterday's file and no
    sign that anything is wrong, which is worse than a page missing
    one device.
    """
    coord = await setup_coordinator(hass)
    poisons = {
        "p1": [float("nan")] * 8,
        "p2": ["a", "b", "c", "d", "e"],
        "p3": [160.0, 162.0, 158.0, 161.0, -60.0, -61.0],
        "p4": [],
        "p5": [None] * 9,
        "p6": [float("inf")] * 5 + [0.0],
        "p7": [160.0, 162.0, 158.0, 161.0, 160.0, 159.0, 100.0],
    }
    for key, series in poisons.items():
        device, _ = register_device(hass, key, f"Poison {key}")
        coord.data[DATA_DEVICES][device.id][DEV_SIGNAL_DAILY_P5] = series

    await hass.async_add_executor_job(coord._write_reports, "manual")

    import os

    from custom_components.device_sentinel.const import (
        REPORT_SIGNAL,
        REPORT_WWW_DIR,
    )

    path = os.path.join(hass.config.path(REPORT_WWW_DIR), REPORT_SIGNAL)
    with open(path, encoding="utf-8") as handle:
        page = handle.read()

    assert "Device Sentinel Signal Report" in page
    assert "nan" not in page.lower().replace("naname", "")
    assert "inf" not in page.replace("information", "")
    assert "Poison p7" in page
