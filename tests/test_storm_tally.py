# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_storm_tally.py, Version: 0.17.1 (2026-08-23)

"""The storm tally and the flood sentence (rulings #320, #321).

Raw storm rows keep one hour, the size of their only reader, after
two days of them reached 64 percent of the reference fleet's storage
file. The daily record is the tally: one row per domain per day,
written at the fold with the count and three medians. The brief's
flood sentence reads the newest tally day, skips excluded domains,
and teaches that muting does not reduce what is recorded.
"""


from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_INTEGRATIONS,
    DATA_STORM_DAYS,
    DATA_STORMS,
    STORM_DAY_COUNT,
    STORM_DAY_DATE,
    STORM_DAY_DOMAIN,
    STORM_DAY_DURATION,
    STORM_DAY_INTERVAL,
    STORM_KEEP_SECONDS,
)
from custom_components.device_sentinel.interventions import _median

from tests.helpers import setup_coordinator


def _close_storms(coord, domain, times, devices=18, duration=5.0):
    """Feed the in-memory day list the way _end_storm does."""
    for at in times:
        coord._storm_day.setdefault(domain, []).append(
            (at, devices, duration)
        )


async def test_the_raw_keep_is_one_hour(hass: HomeAssistant):
    """Ruling #320, amending #232: the only reader of the raw rows
    looks back one hour, so that is the keep. Two days held 47
    unread hours and 64 percent of the reference fleet's file."""
    assert STORM_KEEP_SECONDS == 3600.0


async def test_the_prune_drops_rows_past_the_hour(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    now = 100_000.0
    coord.data[DATA_STORMS] = [
        {"at": now - 5000.0, "entry_id": "e1", "domain": "poller",
         "devices": 18, "duration": 5.0},
        {"at": now - 300.0, "entry_id": "e1", "domain": "poller",
         "devices": 18, "duration": 5.0},
    ]
    coord._trim_storms(now)
    kept = coord.data[DATA_STORMS]
    assert len(kept) == 1
    assert kept[0]["at"] == now - 300.0


async def test_the_fold_writes_one_tally_row_per_domain(
    hass: HomeAssistant,
):
    """Count, median interval, median devices, median duration, one
    row per domain that stormed, and the day list clears so the
    next day starts empty."""
    coord = await setup_coordinator(hass)
    _close_storms(
        coord, "poller", [1000.0, 1040.0, 1080.0, 1120.0], devices=18
    )
    _close_storms(coord, "reloader", [2000.0, 2600.0], devices=22)

    coord._fold_storm_days("2026-08-23")

    rows = coord.data[DATA_STORM_DAYS]
    assert len(rows) == 2
    poller = next(r for r in rows if r[STORM_DAY_DOMAIN] == "poller")
    assert poller[STORM_DAY_DATE] == "2026-08-23"
    assert poller[STORM_DAY_COUNT] == 4
    assert poller[STORM_DAY_INTERVAL] == 40.0
    assert poller[STORM_DAY_DURATION] == 5.0
    reloader = next(
        r for r in rows if r[STORM_DAY_DOMAIN] == "reloader"
    )
    assert reloader[STORM_DAY_COUNT] == 2
    assert reloader[STORM_DAY_INTERVAL] == 600.0
    assert coord._storm_day == {}


async def test_a_quiet_day_writes_no_tally(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord._fold_storm_days("2026-08-23")
    assert coord.data[DATA_STORM_DAYS] == []


async def test_a_single_storm_has_no_interval(hass: HomeAssistant):
    """One storm has no gap to take a median of; the interval is
    None rather than an invented zero."""
    coord = await setup_coordinator(hass)
    _close_storms(coord, "poller", [1000.0])
    coord._fold_storm_days("2026-08-23")
    row = coord.data[DATA_STORM_DAYS][0]
    assert row[STORM_DAY_COUNT] == 1
    assert row[STORM_DAY_INTERVAL] is None


def test_the_median_is_the_middle_value():
    assert _median([3.0]) == 3.0
    assert _median([1.0, 9.0]) == 5.0
    assert _median([1.0, 2.0, 100.0]) == 2.0


async def test_the_flood_sentence_reads_the_newest_day(
    hass: HomeAssistant,
):
    """One sentence per flooding domain (ruling #321), carrying the
    count, the cadence, and the teaching that muting does not
    reduce what is recorded."""
    coord = await setup_coordinator(hass)
    coord.data[DATA_STORM_DAYS] = [
        {STORM_DAY_DATE: "2026-08-22", STORM_DAY_DOMAIN: "poller",
         STORM_DAY_COUNT: 2397, STORM_DAY_INTERVAL: 36.0,
         "median_devices": 18.0, STORM_DAY_DURATION: 5.0},
        {STORM_DAY_DATE: "2026-08-21", STORM_DAY_DOMAIN: "poller",
         STORM_DAY_COUNT: 2023, STORM_DAY_INTERVAL: 36.0,
         "median_devices": 18.0, STORM_DAY_DURATION: 5.0},
    ]
    said = coord._flood_sentences()
    assert len(said) == 1
    sentence = said[0]
    assert "poller" in sentence
    assert "2397" in sentence
    assert "muting does not reduce what is recorded" in sentence
    assert "Exclusions and Muting" in sentence
    # Only the newest day speaks; yesterday's 2023 does not repeat.
    assert "2023" not in sentence


async def test_an_excluded_domain_is_not_named(hass: HomeAssistant):
    """The sentence is gone the day the person acts on it: an
    excluded integration writes no new storms and its standing
    tally rows stop being read."""
    coord = await setup_coordinator(
        hass, {CONF_EXCLUDED_INTEGRATIONS: ["poller"]}
    )
    coord.data[DATA_STORM_DAYS] = [
        {STORM_DAY_DATE: "2026-08-22", STORM_DAY_DOMAIN: "poller",
         STORM_DAY_COUNT: 2397, STORM_DAY_INTERVAL: 36.0,
         "median_devices": 18.0, STORM_DAY_DURATION: 5.0},
    ]
    assert coord._flood_sentences() == []


async def test_a_single_storm_day_is_not_a_flood(hass: HomeAssistant):
    """One storm in a day is a reload, already told as a system
    event; the flood sentence starts at two."""
    coord = await setup_coordinator(hass)
    coord.data[DATA_STORM_DAYS] = [
        {STORM_DAY_DATE: "2026-08-22", STORM_DAY_DOMAIN: "reloader",
         STORM_DAY_COUNT: 1, STORM_DAY_INTERVAL: None,
         "median_devices": 20.0, STORM_DAY_DURATION: 4.0},
    ]
    assert coord._flood_sentences() == []


async def test_the_tally_survives_a_round_trip(
    hass: HomeAssistant,
):
    """The tally is storage, not memory: written by the fold,
    carried through a save, present at the next load."""
    coord = await setup_coordinator(hass)
    _close_storms(coord, "poller", [1000.0, 1040.0])
    coord._fold_storm_days("2026-08-23")
    saved = coord.data[DATA_STORM_DAYS]
    assert saved and saved[0][STORM_DAY_DOMAIN] == "poller"


async def test_the_midnight_roll_folds_the_tally(
    hass: HomeAssistant, freezer,
):
    """The fold writer runs inside the midnight roll, so the tally
    row exists in the same save as the day's series."""
    coord = await setup_coordinator(hass)
    _close_storms(coord, "poller", [1000.0, 1040.0, 1090.0])
    await coord._on_midnight(None)
    rows = coord.data[DATA_STORM_DAYS]
    assert len(rows) == 1
    assert rows[0][STORM_DAY_COUNT] == 3
