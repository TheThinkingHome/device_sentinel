# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_recovery_wording.py, Version: 0.27.10 (2026-10-27)

"""A closed signal problem says it was the signal (rule NOTE-10).

A plug that never stopped reporting closes its signal problem at the
midnight judgment. "Recovered after 2 and a half weeks" leaves a reader
guessing whether the device was silent or its signal was weak, so the
sentence names the signal.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    INCIDENT_RESOLVED,
    TODO_KIND_RAILED_SIGNAL,
    TODO_KIND_UNAVAILABLE,
)

from tests.helpers import setup_coordinator


def _resolved(kind: str) -> dict:
    return {
        INC_DEVICE_ID: "plug",
        INC_NAME: "Plug Living Room Router",
        INC_KIND: kind,
        INC_EVENT: INCIDENT_RESOLVED,
        INC_WHEN: dt_util.utcnow().timestamp(),
        INC_DURATION: 19 * 86400.0,
    }


async def test_the_sentence_names_the_signal(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    sentence = coord._compose_event(_resolved(TODO_KIND_RAILED_SIGNAL))
    assert "Plug Living Room Router signal recovered at" in sentence


async def test_the_table_cell_names_the_signal(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    cell = coord._brief_phrase(_resolved(TODO_KIND_RAILED_SIGNAL))
    assert cell.startswith("signal recovered after 2 and a half weeks")


async def test_a_device_recovery_reads_as_before(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    sentence = coord._compose_event(_resolved(TODO_KIND_UNAVAILABLE))
    assert "Plug Living Room Router recovered at" in sentence
    assert "signal" not in sentence
