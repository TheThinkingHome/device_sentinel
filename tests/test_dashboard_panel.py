# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dashboard_panel.py, Version: 0.22.1 (2026-09-19)

"""The dashboard's sidebar entry and the one module behind it.

Registered when Device Sentinel loads, removed when it unloads, admins
only. The module's address carries a hash of its contents, because the
frontend's service worker serves a stale copy of a file whose address
has not changed, whatever query string is added.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant

from tests.helpers import setup_entry

MODULE = (
    Path(__file__).parent.parent
    / "custom_components" / "device_sentinel" / "frontend" / "panel.js"
)


def _panel(hass: HomeAssistant):
    return hass.data.get("frontend_panels", {}).get("device-sentinel")


async def test_the_panel_is_registered_for_admins(hass: HomeAssistant):
    await setup_entry(hass)
    panel = _panel(hass)
    assert panel is not None
    assert panel.require_admin is True
    assert panel.component_name == "custom"
    assert panel.sidebar_title == "Device Sentinel"
    custom = panel.config["_panel_custom"]
    assert custom["name"] == "device-sentinel-panel"
    assert custom["embed_iframe"] is False
    digest = hashlib.sha256(MODULE.read_bytes()).hexdigest()[:12]
    assert custom["module_url"] == f"/device_sentinel_panel/panel.{digest}.js"


async def test_the_panel_leaves_with_the_integration(hass: HomeAssistant):
    entry = await setup_entry(hass)
    assert _panel(hass) is not None
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert _panel(hass) is None


async def test_a_reload_registers_it_again(hass: HomeAssistant):
    entry = await setup_entry(hass)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _panel(hass) is not None


async def test_the_module_is_served_at_its_address(hass: HomeAssistant, hass_client):
    await setup_entry(hass)
    url = _panel(hass).config["_panel_custom"]["module_url"]
    client = await hass_client()
    response = await client.get(url)
    assert response.status == 200
    assert await response.read() == MODULE.read_bytes()


def test_the_module_builds_no_markup_from_data():
    """Every name comes from a person's own registry, so the module
    sets text, never markup: no innerHTML, no eval."""
    source = MODULE.read_text(encoding="utf-8")
    assert "innerHTML" not in source
    assert "outerHTML" not in source
    assert "eval(" not in source
    assert re.search(r"new\s+Function\s*\(", source) is None


def test_the_module_parses():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(  # noqa: S603 - a fixed local file
        [node, "--check", str(MODULE)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


async def test_a_dashboard_that_cannot_be_served_stops_nothing(hass: HomeAssistant):
    """A missing page, never a broken integration."""
    from unittest.mock import patch

    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.setup import async_setup_component

    await async_setup_component(hass, "http", {})

    async def _boom(configs):
        raise RuntimeError("no static paths today")

    with patch.object(hass.http, "async_register_static_paths", _boom):
        entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert _panel(hass) is None
