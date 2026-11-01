# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_bridges.py, Version: 0.27.17 (2026-11-01)

"""What the diagnostics download says about each bridge's pairing
window: whether every join of it was heard, and when the bridge last
said it opened or closed, so a re-pair restart that did or did not
happen can be explained from the file (rule FRZ-05)."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import STACK_Z2M
from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.device_sentinel.stack_z2m import Z2MBridgeReader

from .helpers import setup_entry


def _msg(payload, retain=False):
    return SimpleNamespace(payload=payload, retain=retain)


async def test_the_download_names_each_bridge_s_join_state(hass: HomeAssistant):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    reader = Z2MBridgeReader(hass)
    reader._joins_live = True
    reader._on_state(_msg("online"))
    reader._on_info(_msg('{"permit_join": false}'))
    reader._on_info(_msg('{"permit_join": true, "permit_join_end": 1}'))
    coord._bridge_readers[STACK_Z2M] = reader
    payload = await async_get_config_entry_diagnostics(hass, entry)
    joins = payload["classification"]["bridge_joins"][STACK_Z2M]
    assert joins["joins_heard"] is True
    assert joins["pairing_changed"] and joins["pairing_changed"].endswith("+00:00")
    # A window found already open when the reader subscribed is one
    # whose joins were not all heard.
    late = Z2MBridgeReader(hass)
    late._joins_live = True
    late._on_info(_msg('{"permit_join": true, "permit_join_end": 1}', retain=True))
    coord._bridge_readers[STACK_Z2M] = late
    payload = await async_get_config_entry_diagnostics(hass, entry)
    assert payload["classification"]["bridge_joins"][STACK_Z2M]["joins_heard"] is False
    del coord._bridge_readers[STACK_Z2M]


async def test_a_reader_that_names_no_joins_reads_none(hass: HomeAssistant):
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._bridge_readers["other"] = SimpleNamespace(state="running", pairing_open=False, async_stop=lambda: None)
    payload = await async_get_config_entry_diagnostics(hass, entry)
    assert payload["classification"]["bridge_joins"]["other"] is None
    del coord._bridge_readers["other"]
