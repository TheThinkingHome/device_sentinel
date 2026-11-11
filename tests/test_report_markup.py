# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_report_markup.py, Version: 0.28.11 (2026-11-10)

"""Attacks that must fail: markup and Markdown injection through device names
and areas into the Daily Brief page and email, and the Markdown reports.

Every test asserts the SAFE behaviour: a passing test means the attack
failed.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.const import CONF_REPORT_LINKS, REPORT_LINKS_INTERNAL
from custom_components.device_sentinel.report_brief import _markdown_unescaped
from custom_components.device_sentinel.reports import ReportWritingMixin

from tests.helpers import register_device, setup_coordinator

HOSTILE = [
    "<script>alert(1)</script>",
    '<img src=x onerror="alert(2)">',
    '"><svg onload=alert(3)>',
    "</td></tr></table><a href='javascript:alert(4)'>x</a>",
    "\\<script>alert(5)\\</script>",
    "\\\\<b>bold</b>",
    "A|B\nC\r# Heading\n| x | y |",
    "![p](https://evil.example/p.png)",
    "[Sign in](javascript:alert(6))",
    "&lt;script&gt;",
    " <i>sep</i>\u0085",
]

ALLOWED_TAGS = {"html", "head", "meta", "title", "style", "body", "h1", "h2", "p", "table", "tr", "th", "td", "a"}


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, list[tuple[str, str | None]]]] = []

    def handle_starttag(self, tag, attrs):
        self.found.append((tag, attrs))


def _audit(page: str, base: str | None) -> list[str]:
    parser = _Tags()
    parser.feed(page)
    problems = []
    styles = 0
    for tag, attrs in parser.found:
        if tag == "style":
            styles += 1
        if tag not in ALLOWED_TAGS:
            problems.append(f"tag {tag}")
        for name, value in attrs:
            if name.startswith("on"):
                problems.append(f"{tag} {name}")
            if tag == "a" and name == "href" and not (base and (value or "").startswith(base)):
                problems.append(f"href {value}")
            if tag == "a" and name != "href":
                problems.append(f"a {name}")
    if styles != 1:
        problems.append(f"{styles} style tags")
    return problems


async def test_the_brief_page_draws_no_markup_from_names_or_areas(hass: HomeAssistant):
    """Each hostile string as a device's name and as its area, through
    the one renderer the file and the email share. Linked, so the anchor
    path is exercised. Safe: no tag, handler or link of the attacker's."""
    devices = []
    for index, text in enumerate(HOSTILE):
        device, _ = register_device(hass, f"hostile{index}", name=f"Dev {index} {text}")
        area = ar.async_get(hass).async_get_or_create(f"Area {index} {text}"[:200])
        dr.async_get(hass).async_update_device(device.id, area_id=area.id)
        devices.append((device, f"Dev {index} {text}"))
    coord = await setup_coordinator(hass)
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_REPORT_LINKS: REPORT_LINKS_INTERNAL}
    )
    await hass.async_block_till_done()
    base = coord._configured_url(REPORT_LINKS_INTERNAL)
    coord._brief_devices = {}
    rows = [f"| {coord._note_brief_device(device.id, name)} | 1 |" for device, name in devices]
    sentences = [f"At 3 pm, {coord._report_cell(name)} stopped reporting." for _, name in devices]
    sentences += [f"Raw: {name}" for _, name in devices]
    headings = [f"## {coord._report_cell(name)}" for _, name in devices]
    markdown = "\n".join(
        ["# Daily Brief", "", "| Device | Count |", "|---|---|", *rows, "", *sentences, *headings]
    )
    page = coord._render_brief_html(markdown)
    assert _audit(page, base) == []


def test_a_report_cell_leaves_nothing_live_for_markdown():
    """_report_cell (expected to hold): no live bracket, angle, pipe or
    line break, whatever backslashes the name brings."""
    live = re.compile(r"(?<!\\)(?:\\\\)*[\[\]<>|]")
    for text in HOSTILE + ["\\" * n + "[x](u)" for n in range(1, 6)] + ["\\" * n + "<b>" for n in range(1, 6)]:
        cell = ReportWritingMixin._report_cell(text)
        assert "\n" not in cell and "\r" not in cell, text
        assert not live.search(cell), (text, cell)


def test_unescaping_a_cell_gives_back_the_name():
    """The page takes the cell's escapes off before escaping for HTML
    (expected to hold): what was a name comes back as the name."""
    for text in HOSTILE:
        flat = text.replace("\n", " ").replace("\r", " ")
        assert _markdown_unescaped(ReportWritingMixin._report_cell(text)) == flat, text
