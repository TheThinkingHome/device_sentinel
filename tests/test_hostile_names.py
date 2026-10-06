# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_hostile_names.py, Version: 0.24.9 (2026-10-06)

"""Names and typed text that could break a page (0.24.9, before Latest).

A device name can come from the device itself, and a person can type a
name or a battery. None of it may split a table, become a link or a
picture, or carry characters that cannot be shown.
"""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import CONF_LOW_THRESHOLD
from custom_components.device_sentinel.notifier import _card_text
from custom_components.device_sentinel.report_brief import _markdown_unescaped
from custom_components.device_sentinel.reports import ReportWritingMixin

from .helpers import card_message, register_device, setup_coordinator
from .test_falling_surfaces import _battery_device, _seed

HOSTILE = ["Pipe | Split", "Line\nBreak", "<script>alert(1)</script>", "[Pay](https://evil.example)",
           "![pic](https://evil.example/p.png)", "Back\\slash"]


class _Rows(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.widths: list[int] = []
        self.tags: set[str] = set()
        self._cells: int | None = None

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        if tag == "tr":
            self._cells = 0
        elif tag in ("td", "th") and self._cells is not None:
            self._cells += 1

    def handle_endtag(self, tag):
        if tag == "tr" and self._cells is not None:
            self.widths.append(self._cells)
            self._cells = None


def test_the_report_escape_covers_links_and_pictures_and_comes_back_off():
    for name in HOSTILE:
        cell = ReportWritingMixin._report_cell(name)
        assert "\n" not in cell and not re.search(r"(?<!\\)[|<>\[\]]", cell), cell
        assert _markdown_unescaped(cell) == name.replace("\n", " ")
    assert ReportWritingMixin._report_cell("Soil Irrigation (Monstera)") == "Soil Irrigation (Monstera)"


async def test_the_last_24_hours_keeps_three_cells_whatever_is_typed(hass: HomeAssistant, hass_ws_client, tmp_path):
    devices = []
    for i, name in enumerate(HOSTILE):
        device, _ = register_device(hass, f"hn{i}", f"plain {i}")
        dr.async_get(hass).async_update_device(device.id, name_by_user=name)
        devices.append(device)
    coord = await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    for i, device in enumerate(devices):
        await client.send_json({"id": i + 1, "type": "device_sentinel/device_power", "device_id": device.id,
                                "choice": "Other", "other": f"CR{i}|x"})
        assert (await client.receive_json())["success"]
    now = dt_util.utcnow().timestamp()
    coord._write_brief(str(tmp_path), "manual", now - 86400, now, False)
    page = open(os.path.join(tmp_path, "daily_brief.html"), encoding="utf-8").read()
    rows = _Rows()
    rows.feed(page)
    assert set(rows.widths) == {3}, rows.widths
    assert "script" not in rows.tags and "a" not in rows.tags and "img" not in rows.tags
    text = re.sub(r"<[^>]+>", "", page).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    assert "Pipe | Split" in text and "Line Break" in text and "CR0|x" in text


async def test_the_card_shows_names_as_text(hass: HomeAssistant):
    device, _ = _battery_device(hass, "![pic](https://evil.example/p.png)", 24.0)
    coord = await setup_coordinator(hass, {CONF_LOW_THRESHOLD: 18.0, "persistent_enabled": True})
    _seed(coord, device.id, 24.0)
    coord._sync_problem_list()
    await coord.async_update_card()
    message = card_message(hass)
    assert "\\!\\[pic\\]\\(https://evil.example/p.png\\)" in message, message
    assert message.endswith("[Open the Problem List](/device-sentinel/problem-list)"), "the card's own link stays a link"
    assert _card_text("Soil Irrigation (Monstera)\nTwo") == "Soil Irrigation \\(Monstera\\) Two"


async def test_a_name_with_hidden_characters_is_refused(hass: HomeAssistant, hass_ws_client):
    device, _ = register_device(hass, "hc", "Plain Name")
    await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    for i, name in enumerate(("Bad\u0000Name", "Bad\u202eName", "Bad\u200bName")):
        await client.send_json({"id": i + 1, "type": "device_sentinel/device_rename", "device_id": device.id, "name": name})
        reply = await client.receive_json()
        assert reply["error"]["code"] == "refused" and "cannot be shown" in reply["error"]["message"], reply
    assert dr.async_get(hass).async_get(device.id).name_by_user is None
    await client.send_json({"id": 9, "type": "device_sentinel/device_rename", "device_id": device.id, "name": "Café 🔋 Ñandú"})
    assert (await client.receive_json())["success"], "ordinary letters and emoji are welcome"
    assert dr.async_get(hass).async_get(device.id).name_by_user == "Café 🔋 Ñandú"
