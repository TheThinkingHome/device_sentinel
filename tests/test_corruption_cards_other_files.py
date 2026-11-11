# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_corruption_cards_other_files.py, Version: 0.28.12 (2026-11-11)

"""Home Assistant's critical
storage-corruption card for Device Sentinel files that the first fix
does not reach.

The first fix clears the card for the live history file and the answers file
once each is put back. Two more files are read through a Store, so an
unparseable one is renamed `.corrupt.<time>` by Home Assistant with a
CRITICAL card telling the person to fix it by hand or restore the whole
system from a backup:

- the clocks file, written at every routine save, which Device
  Sentinel sets aside and rebuilds within a day (rule STOR-10), so the
  card's advice to restore the whole system is wrong;
- the history file's last-good copy, which Device Sentinel rewrites
  from the live history file at load ("mended").

Each test asserts the correct behaviour (rule REP-08 as widened
it): once Device Sentinel has answered the file, no storage_corruption
card for it is left standing.
"""

from __future__ import annotations

import os

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.device_sentinel.const import STORAGE_CLOCKS_KEY

from tests.test_history_file import learned, restart_with
from tests.test_history_file_disk import HIST_COPY, devices_only, house


def _corruption_cards(hass: HomeAssistant, key: str) -> list[str]:
    registry = ir.async_get(hass)
    prefix = f"storage_corruption_{key}_"
    return [issue_id for (_domain, issue_id) in registry.issues if issue_id.startswith(prefix)]


async def test_an_unreadable_clocks_file_leaves_no_critical_card(
    hass: HomeAssistant, real_disk
):
    entry, _coord, _ids = await house(hass)

    def damage():
        with open(os.path.join(real_disk, STORAGE_CLOCKS_KEY), "w", encoding="utf-8") as handle:
            handle.write("{not json")

    await restart_with(hass, entry, damage)
    # Home Assistant set the file aside, so the read went through it.
    assert any(".clocks.corrupt." in name for name in os.listdir(real_disk))
    assert _corruption_cards(hass, STORAGE_CLOCKS_KEY) == []


async def test_a_damaged_history_last_good_mended_leaves_no_critical_card(
    hass: HomeAssistant, real_disk
):
    entry, coord, _ids = await house(hass)
    before = devices_only(learned(coord))

    def damage():
        with open(os.path.join(real_disk, HIST_COPY), "w", encoding="utf-8") as handle:
            handle.write("{not json")

    coord2 = await restart_with(hass, entry, damage)
    assert coord2._history_state["joined"] == "live"
    assert coord2._history_state.get("mended") == "last-good"
    assert devices_only(learned(coord2)) == before
    assert _corruption_cards(hass, HIST_COPY) == []
