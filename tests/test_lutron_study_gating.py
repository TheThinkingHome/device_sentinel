# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_lutron_study_gating.py, Version: 0.27.8 (2026-10-27)

"""The Lutron study is gathered only behind its own Extended Diagnostics
switch, opens no connection to the hub, and leaves out an entry the
person ignored or disabled (rules STACK-11, STACK-13)."""

from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import CONF_STUDY_HARDWARE, STUDIABLE
from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics
from custom_components.device_sentinel.study_lutron import lutron_study

from .test_lutron_hub import _house


def _no_connections(monkeypatch):
    opened = []

    async def refuse(*args, **kwargs):
        opened.append(args)
        raise AssertionError("a connection was opened")

    monkeypatch.setattr(asyncio, "open_connection", refuse)
    return opened


async def test_not_gathered_under_another_switch(hass: HomeAssistant, freezer, monkeypatch):
    opened = _no_connections(monkeypatch)
    h = await _house(hass, freezer, options=lambda b, g: {CONF_STUDY_HARDWARE: [STUDIABLE["hue"]]})
    diag = (await async_get_config_entry_diagnostics(hass, h.coord.entry))["classification"]
    assert diag["lutron"] == {}
    assert opened == []


async def test_gathered_under_its_own_switch_without_a_connection(
    hass: HomeAssistant, freezer, monkeypatch
):
    opened = _no_connections(monkeypatch)
    h = await _house(
        hass, freezer, options=lambda b, g: {CONF_STUDY_HARDWARE: [STUDIABLE["lutron_caseta"]]}
    )
    diag = (await async_get_config_entry_diagnostics(hass, h.coord.entry))["classification"]
    hubs = diag["lutron"]["hubs"]
    assert len(hubs) == 2
    assert all("tcp" not in hub for hub in hubs)
    assert opened == []


async def test_an_ignored_or_disabled_entry_is_left_out(hass: HomeAssistant, freezer):
    h = await _house(hass, freezer)
    await hass.config_entries.async_set_disabled_by(h.garage.entry_id, ConfigEntryDisabler.USER)
    await hass.async_block_till_done()
    hubs = (await lutron_study(hass))["hubs"]
    assert [hub["title"] for hub in hubs] == ["Basement"]
