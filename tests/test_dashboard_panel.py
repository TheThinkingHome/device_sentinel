# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dashboard_panel.py, Version: 0.25.4 (2026-10-09)

"""The dashboard's sidebar entry and the one module behind it.

Registered when Device Sentinel loads, removed when it unloads, admins
only. The module's address carries a hash of its contents, because the
frontend's service worker serves a stale copy of a file whose address
has not changed, whatever query string is added.

The hash is also told to the dashboard (0.25.4): a tab left open across
an update runs the old file while Home Assistant hands it the new one,
and the tab compares the two to offer a reload.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import SYS_RESTART
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


async def _ws(client, **message):
    await client.send_json_auto_id(message)
    return await client.receive_json()


async def test_the_status_names_the_file_served(hass: HomeAssistant, hass_ws_client):
    """An open tab compares this with the file it runs (0.25.4)."""
    await setup_entry(hass)
    digest = hashlib.sha256(MODULE.read_bytes()).hexdigest()[:12]
    assert _panel(hass).config["_panel_custom"]["module_url"].endswith(f".{digest}.js")
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/status")
    assert reply["success"], reply
    assert reply["result"]["panel"] == digest


async def test_every_change_marker_names_the_file_served(hass: HomeAssistant, hass_ws_client):
    """The frontend subscribes again when it reconnects after a restart,
    so the first marker after an update reaches an open tab (0.25.4)."""
    entry = await setup_entry(hass)
    digest = hashlib.sha256(MODULE.read_bytes()).hexdigest()[:12]
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/subscribe_changes")
    assert reply["success"], reply
    first = await client.receive_json()
    assert first["event"]["panel"] == digest
    entry.runtime_data._record_system_event(SYS_RESTART)
    pushed = await client.receive_json()
    assert pushed["event"]["panel"] == digest
    assert pushed["event"]["marker"] > first["event"]["marker"]


async def test_a_reload_names_the_same_file(hass: HomeAssistant, hass_ws_client):
    """Nothing changed, so an open tab is not told it is out of date."""
    entry = await setup_entry(hass)
    client = await hass_ws_client(hass)
    before = (await _ws(client, type="device_sentinel/status"))["result"]["panel"]
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    after = (await _ws(client, type="device_sentinel/status"))["result"]["panel"]
    assert before == after and before


async def test_a_changed_file_is_a_new_name(hass: HomeAssistant, tmp_path, hass_ws_client):
    """An update that changes the dashboard gives it a new address and a
    new name, which is what tells an open tab (0.25.4). The file is
    changed before setup, as an update does with its restart: Home
    Assistant 2026.5 refuses a new address once it has started."""
    from unittest.mock import patch

    import custom_components.device_sentinel as integration

    released = hashlib.sha256(MODULE.read_bytes()).hexdigest()[:12]
    changed = MODULE.read_bytes() + b"\n// a later release\n"
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "panel.js").write_bytes(changed)
    (tmp_path / "__init__.py").write_text("")
    with patch.object(integration, "__file__", str(tmp_path / "__init__.py")):
        await setup_entry(hass)
    client = await hass_ws_client(hass)
    served = (await _ws(client, type="device_sentinel/status"))["result"]["panel"]
    assert served == hashlib.sha256(changed).hexdigest()[:12]
    assert served != released
    assert _panel(hass).config["_panel_custom"]["module_url"].endswith(f".{served}.js")


async def test_a_dashboard_never_served_names_no_file(hass: HomeAssistant, hass_ws_client):
    """With no dashboard there is nothing to compare, so nothing is said."""
    from unittest.mock import patch

    from homeassistant.setup import async_setup_component

    await async_setup_component(hass, "http", {})

    async def _boom(configs):
        raise RuntimeError("no static paths today")

    with patch.object(hass.http, "async_register_static_paths", _boom):
        await setup_entry(hass)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/status")
    assert reply["success"], reply
    assert reply["result"]["panel"] is None


def test_the_element_is_registered_once_per_tab():
    """A second copy in a tab registers nothing and tells the page
    (0.25.4); the behaviour is checked in check_stale_tab.js."""
    source = MODULE.read_text(encoding="utf-8")
    assert "if (!customElements.get(PANEL_ELEMENT))" in source
    assert source.count("customElements.define(") == 1
