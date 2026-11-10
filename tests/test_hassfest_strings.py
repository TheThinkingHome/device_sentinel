# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_hassfest_strings.py, Version: 0.28.9 (2026-11-10)

"""The translation files pass Home Assistant's hassfest check.

The repository's hassfest workflow refuses an integration whose strings
hold a URL: a link's address must reach the text as a description
placeholder. The pattern below is hassfest's own (RE_URL in
script/hassfest/translations.py), so a string it would refuse fails
here first. Only a preview feature's description may hold a URL, and
Device Sentinel has none.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent / "custom_components" / "device_sentinel"
FILES = [ROOT / "strings.json", *sorted((ROOT / "translations").glob("*.json"))]

RE_URL = re.compile(
    r"(((ftp|ftps|scp|http|https|mqtt|mqtts|socket|socks5):\/\/|www\.)"
    r"[a-z0-9]+([\-\.]{1}[a-z0-9]+)*\.[a-z]{2,5}(:[0-9]{1,5})?(\/.*)?)",
    re.IGNORECASE,
)


def _strings(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}" if path else key)
    elif isinstance(node, str):
        yield path, node


@pytest.mark.parametrize("file", FILES, ids=lambda f: f.name)
def test_no_string_holds_a_url(file: Path):
    text = json.loads(file.read_text(encoding="utf-8"))
    assert "preview_features" not in text
    found = [key for key, value in _strings(text) if RE_URL.search(value)]
    assert found == []


def test_the_pattern_catches_what_hassfest_refused():
    """The string hassfest refused, and its fixed form."""
    refused = "[Sending the Daily Brief by Email](https://github.com/TheThinkingHome/device_sentinel/wiki/Sending-the-Daily-Brief-by-Email)"
    assert RE_URL.search(refused)
    assert not RE_URL.search("[Sending the Daily Brief by Email]({email_link})")
