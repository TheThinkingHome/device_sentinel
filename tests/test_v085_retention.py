# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v085_retention.py, Version: 0.8.5 (2026-07-23)

"""0.8.5 tests: the three records that are supposed to forget.

Briefs, episodes and incidents are each bounded at fourteen, and
none of those bounds had a test. That is the failure worth guarding
against, because a trim that stops working raises nothing and
answers nothing wrongly: it just grows, quietly, for weeks, which is
the exact failure this integration exists to catch elsewhere.

Also here: the kind vocabulary. Every wording table now keys off the
kind constants rather than bare strings, so a rename breaks at
import instead of printing a raw kind into somebody's brief.
"""

import glob
import os

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIEF_KEEP_DAYS,
    DATA_EPISODES,
    DATA_INCIDENTS,
    EPISODE_KEEP_DAYS,
    EPISODE_ENDED_RESUMED,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_NOT_REPORTED,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_UNKNOWN,
    INCIDENT_KEEP_DAYS,
    INCIDENT_OPENED,
    INC_WHEN,
    REPORT_BRIEF_PREFIX,
    TODO_KIND_BATTERY,
    TODO_KIND_FROZEN,
    TODO_KIND_NOT_REPORTED,
    TODO_KIND_SIGNAL,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_UNKNOWN,
)

DOMAIN = "device_sentinel"


async def _coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _episode(coord, days_ago, ended=EPISODE_ENDED_RESUMED, lag=None):
    when = dt_util.utcnow().timestamp() - days_ago * 86400.0
    coord.data[DATA_EPISODES].append(
        {
            "device_id": f"d{days_ago}",
            "name": f"Device {days_ago}",
            "since": when,
            "basis": 3600.0,
            "window": 7200.0,
            "ended": ended,
            "at": when + 60 if ended else None,
            "lag": lag,
            "learned": "yes" if ended else None,
        }
    )


# ------------------------------------------------------- the briefs

async def test_only_the_newest_briefs_are_kept(hass: HomeAssistant):
    coord = await _coordinator(hass)
    directory = hass.config.path("device_sentinel")
    os.makedirs(directory, exist_ok=True)
    # Setup writes today's brief, so start from a known count.
    for path in glob.glob(os.path.join(directory, "daily_brief_*.md")):
        os.remove(path)
    for day in range(1, BRIEF_KEEP_DAYS + 7):
        name = f"{REPORT_BRIEF_PREFIX}2026-06-{day:02d}.md"
        with open(os.path.join(directory, name), "w") as handle:
            handle.write("stale\n")
    assert len(glob.glob(os.path.join(directory, "daily_brief_*.md"))) == (
        BRIEF_KEEP_DAYS + 6
    )

    coord._trim_briefs(directory)
    left = sorted(
        os.path.basename(p)
        for p in glob.glob(os.path.join(directory, "daily_brief_*.md"))
    )
    assert len(left) == BRIEF_KEEP_DAYS
    # The newest survive: the oldest six dates are gone.
    assert left[0] == f"{REPORT_BRIEF_PREFIX}2026-06-07.md"


async def test_trimming_briefs_is_safe_when_there_are_few(
    hass: HomeAssistant,
):
    coord = await _coordinator(hass)
    directory = hass.config.path("device_sentinel")
    before = glob.glob(os.path.join(directory, "daily_brief_*.md"))
    coord._trim_briefs(directory)
    assert len(glob.glob(os.path.join(directory, "daily_brief_*.md"))) == (
        len(before)
    )


# ----------------------------------------------------- the episodes

async def test_old_episodes_are_dropped(hass: HomeAssistant):
    coord = await _coordinator(hass)
    coord.data[DATA_EPISODES].clear()
    _episode(coord, days_ago=EPISODE_KEEP_DAYS + 6)
    _episode(coord, days_ago=EPISODE_KEEP_DAYS + 1)
    _episode(coord, days_ago=2)
    coord._trim_episodes(dt_util.utcnow().timestamp())
    assert len(coord.data[DATA_EPISODES]) == 1
    assert coord.data[DATA_EPISODES][0]["name"] == "Device 2"


async def test_an_unfinished_episode_survives_the_boundary(
    hass: HomeAssistant,
):
    """An episode still waiting on its lag is an unfinished story, not
    old news, so age alone does not remove it."""
    coord = await _coordinator(hass)
    coord.data[DATA_EPISODES].clear()
    _episode(coord, days_ago=EPISODE_KEEP_DAYS + 9, ended=None)
    _episode(
        coord,
        days_ago=EPISODE_KEEP_DAYS + 9,
        ended="intervention (restart)",
        lag=None,
    )
    _episode(coord, days_ago=EPISODE_KEEP_DAYS + 9)
    coord._trim_episodes(dt_util.utcnow().timestamp())
    survivors = [row["ended"] for row in coord.data[DATA_EPISODES]]
    assert len(survivors) == 2
    assert EPISODE_ENDED_RESUMED not in survivors


# ---------------------------------------------------- the incidents

async def test_old_incidents_are_dropped_as_new_ones_arrive(
    hass: HomeAssistant,
):
    coord = await _coordinator(hass)
    coord.data[DATA_INCIDENTS].clear()
    stale = dt_util.utcnow().timestamp() - (INCIDENT_KEEP_DAYS + 3) * 86400
    coord.data[DATA_INCIDENTS].append(
        {
            "device_id": "old",
            "name": "Ancient History",
            "kind": TODO_KIND_FROZEN,
            "event": INCIDENT_OPENED,
            INC_WHEN: stale,
            "cause": None,
            "duration": None,
        }
    )
    coord._record_incident("new", "Fresh", TODO_KIND_FROZEN, INCIDENT_OPENED)
    names = [row["name"] for row in coord.data[DATA_INCIDENTS]]
    assert names == ["Fresh"]


# ------------------------------------------------ the kind vocabulary

async def test_freeze_kinds_alias_their_verdicts(hass: HomeAssistant):
    """The sync passes a freeze verdict straight through as a kind, so
    the two names must be the same string, defined once."""
    assert TODO_KIND_FROZEN == FREEZE_CATEGORY_FROZEN
    assert TODO_KIND_UNAVAILABLE == FREEZE_CATEGORY_UNAVAILABLE
    assert TODO_KIND_UNKNOWN == FREEZE_CATEGORY_UNKNOWN
    assert TODO_KIND_NOT_REPORTED == FREEZE_CATEGORY_NOT_REPORTED


async def test_every_kind_has_words_for_both_shapes(
    hass: HomeAssistant,
):
    """The guard the literals could not give: if a kind is ever renamed
    and a table is missed, this fails rather than a raw kind name
    reaching a person's brief."""
    coord = await _coordinator(hass)
    kinds = (
        TODO_KIND_FROZEN,
        TODO_KIND_UNAVAILABLE,
        TODO_KIND_UNKNOWN,
        TODO_KIND_NOT_REPORTED,
        TODO_KIND_BATTERY,
        TODO_KIND_SIGNAL,
    )
    for kind in kinds:
        assert kind in coord._KIND_SEVERITY, kind
    for kind in (
        TODO_KIND_FROZEN,
        TODO_KIND_UNAVAILABLE,
        TODO_KIND_UNKNOWN,
        TODO_KIND_SIGNAL,
    ):
        assert kind in coord._EVENT_WORDING, kind
        assert kind in coord._STATE_TEMPLATE, kind
