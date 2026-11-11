# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_orphan_episodes_reload.py, Version: 0.28.12 (2026-11-11)

"""A reload does not call every silence episode still open an orphan (store._count_orphan_episodes, called from
coordinator.async_setup; rule STOR-18).

The count rests on one claim: "after a clean stop every open episode has
been stamped, and after an unclean one the unclean-stop reset has just
stamped them too, so an episode carrying no ending is an orphan, a row
whose closing never reached disk". That holds for a Home Assistant stop
(_on_hass_stop stamps them as a reboot) and for a power cut
(_handle_unclean_restart stamps them as unclean). It does not hold for a
reload: async_shutdown stamps nothing, as it should, since a reload
revives no radio and the silence goes on. So every reload on a house
with any device part way into its patience logs, at WARNING, "Episode
integrity: N silence episode(s) ... carry no ending ... A closing did not
reach disk", and the diagnostics carry a non-zero orphan count, for rows
that are healthy and still running.

A reload is an ordinary act on a real house (the Reload menu item,
disabling and enabling the entry); no test reloads with an episode open.

The test asserts the correct behaviour: an episode that is legitimately
still open across a reload is not reported at WARNING as a closing that
never reached disk. (Counting open rows for the diagnostics is the rule.)
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_EPISODES,
    EP_AT,
    EP_BASIS,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LAG,
    EP_LEARNED,
    EP_NAME,
    EP_SIGNAL,
    EP_SINCE,
    EP_TAINT_SECONDS,
    EP_WINDOW,
)
from tests.helpers import setup_entry


async def test_an_episode_open_across_a_reload_is_not_an_orphan(
    hass: HomeAssistant, caplog
):
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    now = dt_util.utcnow().timestamp()
    # A device well into its patience: the episode is open, waiting for
    # the device to speak, exactly as _note_silences writes it.
    assert coordinator._append_row(
        DATA_EPISODES,
        {
            EP_DEVICE_ID: "device-in-a-silence",
            EP_NAME: "Hall Sensor",
            EP_SINCE: now - 3 * 3600.0,
            EP_BASIS: 3600.0,
            EP_WINDOW: 4 * 3600.0,
            EP_ENDED: None,
            EP_AT: None,
            EP_LAG: None,
            EP_LEARNED: None,
            EP_TAINT_SECONDS: None,
            EP_SIGNAL: None,
        },
    )
    coordinator._mark_cold_dirty()
    await coordinator._save_now()

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="custom_components.device_sentinel"):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    reloaded = entry.runtime_data
    assert reloaded is not coordinator
    # The row came through the reload still open, which is right: a
    # reload is not an intervention on the device.
    still_open = [
        row
        for row in reloaded.data[DATA_EPISODES]
        if row[EP_DEVICE_ID] == "device-in-a-silence" and row[EP_ENDED] is None
    ]
    assert len(still_open) == 1
    # Counting open rows for the diagnostics is the rule (STOR-18,
    # STOR-21); telling the log at WARNING that a closing was lost is
    # not, because none was.
    warned = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
        and "did not reach disk" in record.getMessage()
    ]
    assert warned == []
