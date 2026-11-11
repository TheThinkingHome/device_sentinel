# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_corruption_cards_recovered.py, Version: 0.28.12 (2026-11-11)

"""Home Assistant's own corruption card after
Device Sentinel has already put the file back.

When a Store cannot parse its file, Home Assistant renames it to
`.corrupt.<time>` and raises a CRITICAL repair issue telling the person
to fix the file by hand or restore the whole system from a backup. For
the main file Device Sentinel removes that card once it has restored
from last-good (rule REP-08). The history file and the answers file are
read through a Store too, and are answered by their own last-good
copies, but nothing removes Home Assistant's card for them, so a person
is told to restore the whole system for a file that is already whole.

Each test asserts the correct behaviour: after a recovery from
last-good, no storage_corruption card for that file is left standing.
"""

from __future__ import annotations

import json
import os

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from tests.helpers import setup_entry, start_storage_as_home_assistant_does
from tests.test_history_file import learned, restart_with
from tests.test_history_file_disk import HIST, devices_only, house

ANSWERS = "device_sentinel.answers"


def _corruption_cards(hass: HomeAssistant, key: str) -> list[str]:
    registry = ir.async_get(hass)
    prefix = f"storage_corruption_{key}_"
    return [issue_id for (_domain, issue_id) in registry.issues if issue_id.startswith(prefix)]


async def test_history_file_answered_by_last_good_leaves_no_critical_card(
    hass: HomeAssistant, real_disk
):
    """A damaged live history file is joined from last-good and mended;
    Home Assistant's card advising a system restore must not stay."""
    entry, _coord, _ids = await house(hass)
    before = devices_only(learned(entry.runtime_data))

    def damage():
        with open(os.path.join(real_disk, HIST), "w", encoding="utf-8") as handle:
            handle.write("{not json")

    coord2 = await restart_with(hass, entry, damage)
    # The recovery itself works.
    assert coord2._history_state["joined"] == "last-good"
    assert devices_only(learned(coord2)) == before
    # The card telling the person to restore the whole system is gone.
    assert _corruption_cards(hass, HIST) == []


async def test_answers_file_restored_from_last_good_leaves_no_critical_card(
    hass: HomeAssistant, real_disk
):
    """A damaged answers file is restored from its last-good copy; Home
    Assistant's card advising a system restore must not stay."""
    with open(os.path.join(real_disk, ANSWERS), "w", encoding="utf-8") as handle:
        handle.write("{ not json")
    with open(os.path.join(real_disk, f"{ANSWERS}.last-good"), "w", encoding="utf-8") as handle:
        json.dump(
            {
                "version": 1,
                "minor_version": 1,
                "key": ANSWERS,
                "data": {
                    "power": {"models": {}, "devices": {}},
                    "types": {"models": {}, "devices": {}},
                },
            },
            handle,
        )
    await start_storage_as_home_assistant_does(hass)
    await setup_entry(hass)
    await hass.async_block_till_done()
    # Home Assistant did set the file aside, so the read went through it.
    assert any(".answers.corrupt." in name for name in os.listdir(real_disk))
    assert _corruption_cards(hass, ANSWERS) == []
