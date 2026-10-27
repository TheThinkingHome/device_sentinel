# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_screen_text.py, Version: 0.27.9 (2026-10-27)

"""The settings screens say what is true (rule CFG-03): the trim backups
are deleted after 30 days except the newest, each wiki link names its
screen and reads "on the wiki", and no link ends with a stray full stop."""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "device_sentinel"


def _descriptions(path):
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "description" and isinstance(value, str):
                    found.append(value)
                walk(value)

    walk(json.loads(path.read_text(encoding="utf-8")))
    return found


def test_the_screens_say_what_is_true():
    for path in (ROOT / "strings.json", ROOT / "translations" / "en.json"):
        text = "\n".join(_descriptions(path))
        assert "kept until you delete them yourself" not in text
        assert "deleted after 30 days, except the newest" in text
        assert "[Freeze and Unavailable Detection on the wiki]" in text
        assert "on the Wiki]" not in text
        assert not re.search(r"\]\(\{wiki_link\}\)\.", text)
