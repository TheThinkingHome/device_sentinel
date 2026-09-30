# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_rhythm_shadow.py, Version: 0.23.19 (2026-09-30)

"""The clipped rhythm, computed beside the trimmed maximum (ruling #542).

What the rule must do, from the reference rig's own days: set bad days
aside however many there are, aim at the same day the trimmed maximum
aims at, and never read a device as perfectly regular. What the shadow
must do: record where the two rules disagree, change no verdict, and
say so once when a disagreement carries over a restart.
"""

from __future__ import annotations

import math
import os
import random

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    CLIP_MAX_DAYS,
    CLIP_START_DAYS,
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    REPORT_DIR,
    REPORT_RHYTHM_SHADOW,
)
from custom_components.device_sentinel.rhythm_shadow import clipped_rhythm

from .test_bridge_hold import _house, _minutes

MINUTE = 60.0

# Leak Kitchen Sink on the reference rig: its last 42 daily longest gaps
# in seconds, oldest first, as stored on 29 September 2026. The last is
# the four-hour Zigbee2MQTT outage of 28 September and the fifth from
# last the 16.5-minute stop of 24 September. Today's trimmed maximum
# read it as 17.7 minutes; its rhythm before those days was 4.0.
LEAK = [
    238, 231, 192, 241, 240, 233, 201, 214, 229, 358, 223, 241, 240, 236,
    1034, 176, 235, 236, 213, 191, 793, 186, 173, 193, 223, 480, 206, 168,
    238, 205, 172, 212, 225, 240, 213, 241, 145, 1062, 219, 241, 233, 14255,
]


def _steady(days: int, seed: int = 7) -> list[float]:
    """A device whose longest gap is about ten minutes, give or take."""
    rng = random.Random(seed)
    return [600.0 * math.exp(rng.gauss(0.0, 0.25)) for _ in range(days)]


# ------------------------------------------------------------ the rule


def test_no_clipped_rhythm_before_day_28():
    assert clipped_rhythm(_steady(CLIP_START_DAYS - 1)) is None
    assert clipped_rhythm(_steady(CLIP_START_DAYS)) is not None


def test_it_reads_at_most_42_days():
    found = clipped_rhythm(_steady(80))
    assert found["read"] == CLIP_MAX_DAYS


def test_the_rigs_bad_days_are_set_aside():
    found = clipped_rhythm(LEAK)
    assert found["clipped"] >= 3, found
    assert 3.5 * MINUTE < found["basis"] < 5.0 * MINUTE, found["basis"] / MINUTE


@pytest.mark.parametrize("planted", [3, 5])
def test_far_out_days_do_not_move_it(planted):
    clean = _steady(42)
    base = clipped_rhythm(clean)["basis"]
    bad = list(clean)
    for back in range(2, 2 + 5 * planted, 5):
        bad[-back] = 14400.0
    found = clipped_rhythm(bad)
    assert found["clipped"] >= planted
    assert abs(found["basis"] / base - 1.0) < 0.05, (found["basis"], base)


def test_it_aims_at_the_ninetieth_percentile_day():
    """On a lognormal device the rule should land near its true 90th
    percentile, which is where the trimmed maximum aims."""
    days = _steady(42, seed=11)
    true_p90 = 600.0 * math.exp(1.2816 * 0.25)
    assert abs(clipped_rhythm(days)["basis"] / true_p90 - 1.0) < 0.25


def test_a_regular_device_still_has_a_spread():
    """SwitchBot s11 on the second house reads ten minutes nearly every
    day; without a floor its window sat a few percent above that."""
    found = clipped_rhythm([600.0] * 42)
    assert found["spread"] == pytest.approx(0.15)
    assert found["basis"] > 600.0 * 1.2


def test_days_that_are_not_gaps_are_not_read():
    days = _steady(30) + [None, "x", -5, 0, float("nan"), float("inf"), True]
    assert clipped_rhythm(days)["read"] == 30


# ------------------------------------------------------------ the shadow


def _shadow_lines(hass) -> list[str]:
    """The file's rows. The shadow writes in a background job, which
    async_block_till_done() does not wait for unless asked, so every
    test waits with wait_background_tasks=True before reading."""
    path = hass.config.path(os.path.join(REPORT_DIR, REPORT_RHYTHM_SHADOW))
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [line for line in handle.read().splitlines() if line.startswith("| ") and "WHO LISTS" not in line]


async def _armed_house(hass, freezer, days):
    coord, device, value, seen, heard, phone, bus = await _house(hass, freezer)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = list(days)
    hass.states.async_set(seen, dt_util.utcnow().isoformat())
    await hass.async_block_till_done(wait_background_tasks=True)
    return coord, device, record, seen


async def test_a_disagreement_opens_and_closes(hass: HomeAssistant, freezer):
    """The rig's leak sensor: today's window is about 59 minutes (a
    17.7-minute rhythm plus grace), the clipped one about 23, so a
    silence between them is listed by the clipped rhythm alone. When
    the device speaks, the two agree again."""
    coord, device, record, seen = await _armed_house(hass, freezer, LEAK)
    clipped = coord.clipped_window(record)
    today = coord._freeze_window(record)
    assert clipped < today
    await _minutes(hass, coord, freezer, int(clipped // 60) + 2)
    await hass.async_block_till_done(wait_background_tasks=True)
    lines = _shadow_lines(hass)
    opened = [line for line in lines if "| opened |" in line]
    assert len(opened) == 1 and "| clipped |" in opened[0], lines
    assert record[DEV_FROZEN_CATEGORY] is None, "the shadow changed a verdict"
    hass.states.async_set(seen, dt_util.utcnow().isoformat())
    await _minutes(hass, coord, freezer, 1)
    await hass.async_block_till_done(wait_background_tasks=True)
    closed = [line for line in _shadow_lines(hass) if "| closed |" in line]
    assert len(closed) == 1 and "it spoke" in closed[0], closed


async def test_the_daily_line_counts_what_happened(hass: HomeAssistant, freezer):
    coord, device, record, seen = await _armed_house(hass, freezer, LEAK)
    await _minutes(hass, coord, freezer, int(coord.clipped_window(record) // 60) + 3)
    coord.shadow_fold(dt_util.utcnow().timestamp())
    await hass.async_block_till_done(wait_background_tasks=True)
    day = [line for line in _shadow_lines(hass) if "| day |" in line]
    assert len(day) == 1
    assert "Counted from " in day[0], "the daily line must say from when it counted"
    assert "clipped narrower on 1" in day[0]
    assert "Disagreements opened 1" in day[0]
    assert "only the clipped rhythm " in day[0] and "only the clipped rhythm 0." not in day[0]


async def test_a_disagreement_standing_at_a_restart_is_marked(hass: HomeAssistant, freezer):
    coord, device, record, seen = await _armed_house(hass, freezer, LEAK)
    # Past the clipped window and short of today's: the clipped rhythm
    # alone would list it at the first check after the restart.
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - coord.clipped_window(record) - MINUTE
    coord._init_rhythm_shadow()  # as a fresh start leaves it
    await _minutes(hass, coord, freezer, 1)
    await hass.async_block_till_done(wait_background_tasks=True)
    opened = [line for line in _shadow_lines(hass) if "| opened |" in line]
    assert len(opened) == 1 and "carried over a restart" in opened[0], opened
    assert coord._shadow_opened == 0, "a carried disagreement counted as new"
    coord.shadow_fold(dt_util.utcnow().timestamp())
    await hass.async_block_till_done(wait_background_tasks=True)
    day = [line for line in _shadow_lines(hass) if "| day |" in line]
    assert day and "Counted from " in day[-1], "after a restart the count's start is named"


async def test_a_young_device_is_not_compared(hass: HomeAssistant, freezer):
    coord, device, record, seen = await _armed_house(hass, freezer, _steady(20))
    assert coord.clipped_window(record) is None
    await _minutes(hass, coord, freezer, 30)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not [line for line in _shadow_lines(hass) if "| opened |" in line]


async def test_a_freeze_muted_device_is_not_compared(hass: HomeAssistant, freezer):
    coord, device, record, seen = await _armed_house(hass, freezer, LEAK)
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, "freeze_muted_devices": [device.id]}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    coord = coord.entry.runtime_data
    coord._grace_until = 0.0
    await _minutes(hass, coord, freezer, 10)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not [line for line in _shadow_lines(hass) if "| opened |" in line]


async def test_the_shadow_changes_no_verdict(hass: HomeAssistant, freezer):
    """The same device and the same silence judged with the shadow on
    and with it stubbed out give the same verdicts, minute by minute."""
    verdicts = []
    for shadow in (True, False):
        coord, device, record, seen = await _armed_house(hass, freezer, LEAK)
        if not shadow:
            coord.shadow_check = lambda now: None  # type: ignore[method-assign]
        run = []
        for _ in range(25):
            await _minutes(hass, coord, freezer, 1)
            run.append(record[DEV_FROZEN_CATEGORY])
        verdicts.append(run)
        await hass.config_entries.async_unload(coord.entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert verdicts[0] == verdicts[1]


# 0.23.18: what the adversarial round of 29 September found in the shadow.


def test_the_rule_returns_nothing_rather_than_overflowing():
    """Days near 10^308 overflowed the final step and stopped the
    report writer. The range check keeps such days out of storage
    (#544); the rule stands behind it."""
    assert clipped_rhythm([1e308] * 21 + [1e290] * 21) is None


async def test_the_rhythm_is_worked_out_once_until_the_days_change(hass, freezer, monkeypatch):
    coord, device, record, seen = await _armed_house(hass, freezer, LEAK)
    from custom_components.device_sentinel import rhythm_shadow

    calls = []
    real = rhythm_shadow.clipped_rhythm
    monkeypatch.setattr(rhythm_shadow, "clipped_rhythm", lambda days: calls.append(1) or real(days))
    for _ in range(5):
        coord.clipped_window(record, device.id)
    assert len(calls) == 1
    record[DEV_DAILY_MAX] = [*record[DEV_DAILY_MAX], 240.0]
    coord.clipped_window(record, device.id)
    assert len(calls) == 2, "a new day did not recompute it"


async def test_a_clock_reset_is_not_the_device_speaking(hass, freezer):
    coord, device, record, seen = await _armed_house(hass, freezer, LEAK)
    await _minutes(hass, coord, freezer, int(coord.clipped_window(record) // 60) + 2)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert device.id in coord._shadow_open
    mono = {"now": 1000.0}
    coord._monotonic = lambda: mono["now"]  # type: ignore[method-assign]
    await coord._on_render_tick(None)
    freezer.tick(60 + 7200)
    mono["now"] += 60
    await coord._on_render_tick(None)
    await hass.async_block_till_done(wait_background_tasks=True)
    closed = [line for line in _shadow_lines(hass) if "| closed |" in line]
    assert closed and "the clocks restarted" in closed[-1], closed


async def test_a_removed_device_keeps_its_name_in_the_closing_line(hass, freezer):
    from homeassistant.helpers import device_registry as dr

    coord, device, record, seen = await _armed_house(hass, freezer, LEAK)
    await _minutes(hass, coord, freezer, int(coord.clipped_window(record) // 60) + 2)
    await hass.async_block_till_done(wait_background_tasks=True)
    name = coord._shadow_open[device.id][3]
    dr.async_get(hass).async_remove_device(device.id)
    await hass.async_block_till_done()
    await _minutes(hass, coord, freezer, 2)
    await hass.async_block_till_done(wait_background_tasks=True)
    closed = [line for line in _shadow_lines(hass) if "| closed |" in line]
    assert closed and f"| {name} |" in closed[-1] and "Unknown" not in closed[-1], closed


async def test_the_file_exists_from_the_start(hass):
    """Until 0.23.19 the file appeared only with its first line, so a
    person could not tell "nothing to report" from "not running"."""
    from .helpers import setup_entry

    await setup_entry(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    path = hass.config.path(os.path.join(REPORT_DIR, REPORT_RHYTHM_SHADOW))
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert "Rhythm Shadow" in text and "| WHEN | EVENT |" in text
    assert _shadow_lines(hass) == []
