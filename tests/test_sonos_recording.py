# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_sonos_recording.py, Version: 0.29.1 (2026-11-14)

"""Sonos in Extended Diagnostics (rule STACK-11).

What Home Assistant's Sonos integration holds for each speaker is
recorded at each change, and each Sonos entity as it turns unavailable
or comes back, from Home Assistant's own data. Nothing is asked of a
speaker, and nothing is detected.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.config_flow import _studiable
from custom_components.device_sentinel.const import (
    CONF_STUDY_HARDWARE,
    PROBE_DETAIL,
    PROBE_NOW,
    PROBE_WAS,
    SONOS_KEY,
    STUDIABLE,
)

from .helpers import probe_lines, setup_coordinator

NOW = 1_800_000_000.0
UID = "RINCON_000E58AAAAAA01400"


def _sonos(hass: HomeAssistant):
    entry = MockConfigEntry(domain="sonos", title="Sonos")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("sonos", UID)}, name="Stue",
        manufacturer="Sonos", model="Connect",
    )
    player = er.async_get(hass).async_get_or_create(
        "media_player", "sonos", UID, device_id=device.id, config_entry=entry,
    ).entity_id
    hass.states.async_set(player, "idle")
    speaker = SimpleNamespace(
        available=True, model_name="Connect", version="11.14", subscriptions_failed=False,
        _subscriptions=[object(), object()], _poll_timer=None,
        _last_activity=time.monotonic() - 40, battery_info={},
    )
    entry.runtime_data = SimpleNamespace(discovered={UID: speaker})
    return entry, device, player, speaker


async def test_sonos_is_offered_where_sonos_is_installed(hass: HomeAssistant):
    assert STUDIABLE[SONOS_KEY] not in _studiable(hass)
    _sonos(hass)
    assert STUDIABLE[SONOS_KEY] in _studiable(hass)


async def test_a_line_at_each_change_of_a_speaker_and_of_an_entity(hass: HomeAssistant):
    _entry, device, player, speaker = _sonos(hass)
    coord = await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[SONOS_KEY]]})
    coord._sonos_tick(NOW)
    first = probe_lines(coord, node=UID)
    assert len(first) == 1
    assert first[0][PROBE_NOW] == (
        "available True, subscriptions 2, a subscription failed False, polling False"
    )
    assert first[0][PROBE_DETAIL].startswith("Connect, software 11.14, last heard ")
    # Nothing changed: no new line, and an entity's first sighting is none.
    coord._sonos_tick(NOW + 60)
    assert len(probe_lines(coord, node=UID)) == 1
    assert probe_lines(coord, node="entity") == []
    # The integration gives the speaker up, and its entity follows.
    speaker.available = False
    speaker._subscriptions = []
    hass.states.async_set(player, "unavailable")
    coord._sonos_tick(NOW + 120)
    lines = probe_lines(coord, node=UID)
    assert len(lines) == 2 and lines[1][PROBE_NOW].startswith("available False, subscriptions 0")
    assert lines[1][PROBE_WAS].startswith("available True")
    gone = probe_lines(coord, node="entity")
    assert len(gone) == 1 and gone[0][PROBE_NOW] == "unavailable" and gone[0][PROBE_DETAIL] == player
    coord._sonos_fold(NOW + 200)
    day = probe_lines(coord, node="day")
    assert day and day[0][PROBE_NOW].startswith("last heard ")
    download = coord.sonos_diagnostics()
    told = download["entries"][0]["speakers"][UID]
    assert told["available"] is False and told["model"] == "Connect" and told["device_id"] == device.id
    assert told["entities"] == {player: "unavailable"}
    # Never the entry's title, which can be a family's name (rule STOR-21).
    assert download["entries"][0]["entry"].startswith("sonos entry ")


async def test_an_entry_kept_some_other_way_is_recorded_and_breaks_nothing(hass: HomeAssistant):
    entry, _device, _player, _speaker = _sonos(hass)
    entry.runtime_data = object()
    coord = await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[SONOS_KEY]]})
    coord._sonos_tick(NOW)
    coord._sonos_fold(NOW)
    assert probe_lines(coord, node=UID) == []
    assert coord.sonos_diagnostics()["entries"][0]["speakers_readable"] is False
