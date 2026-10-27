# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_silence_episode_rhythm.py, Version: 0.27.9 (2026-10-27)

"""A silence episode opens halfway between the rhythm in use and the
freeze line (rules FRZ-08, BRIEF-16), so it always opens before the
device is called frozen, whichever rule sets the wait."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_EPISODES,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
)

from tests.helpers import register_device, setup_coordinator

H = 3600.0


async def _house(hass, monkeypatch, rhythm):
    device, _ = register_device(hass, "ln", "Log Normal Plug")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [12 * H] * 14
    real = type(coord)._freeze_rhythm

    def pinned(self, rec):
        found = real(self, rec)
        if rec is record and found is not None and rhythm is not None:
            found = {**found, "rhythm": rhythm, "window": None, "rule": "lognormal"}
        return found

    monkeypatch.setattr(type(coord), "_freeze_rhythm", pinned)
    return device, coord, record


def _episodes(coord, device_id):
    return [r for r in coord.data.get(DATA_EPISODES) or [] if r.get("device_id") == device_id]


async def test_the_log_normal_rhythm_opens_the_episode_before_the_freeze(
    hass: HomeAssistant, monkeypatch
):
    device, coord, record = await _house(hass, monkeypatch, 6 * H)
    window = coord._freeze_window(record)
    line = 6 * H + coord.episode_share * (window - 6 * H)
    assert line < window
    now = dt_util.utcnow().timestamp()
    record[DEV_LAST_ACTIVITY] = now - (line - 60)
    coord._note_silences(now)
    assert _episodes(coord, device.id) == []
    record[DEV_LAST_ACTIVITY] = now - (line + 60)
    coord._note_silences(now)
    rows = _episodes(coord, device.id)
    assert len(rows) == 1
    assert rows[0]["basis"] == 6 * H


async def test_the_trimmed_maximum_still_sets_it_alone(hass: HomeAssistant, monkeypatch):
    device, coord, record = await _house(hass, monkeypatch, None)
    window = coord._freeze_window(record)
    basis = coord._freeze_rhythm(record)["rhythm"]
    line = basis + coord.episode_share * (window - basis)
    now = dt_util.utcnow().timestamp()
    record[DEV_LAST_ACTIVITY] = now - (line + 60)
    coord._note_silences(now)
    assert len(_episodes(coord, device.id)) == 1
    assert line < window
