# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_settings_screen_text.py, Version: 0.27.10 (2026-10-27)

"""What the Settings screens say, read from the files Home Assistant
draws them from.

The priority targets (rules NOTE-02, NOTE-07, BRIEF-11): high-priority
targets get every alert at any hour, normal-priority targets every
alert outside Quiet Hours, and neither gets the Daily Brief, which goes
only to Send the Full Brief To. Labels are in Title Case (rule GEN-06).
strings.json and translations/en.json carry the same words.
"""

from __future__ import annotations

import json
import pathlib

PKG = pathlib.Path(__file__).parent.parent / "custom_components" / "device_sentinel"


def _load(name: str) -> dict:
    return json.loads((PKG / name).read_text(encoding="utf-8"))


def _both() -> list[dict]:
    return [_load("strings.json"), _load("translations/en.json")]


def _instant(doc: dict) -> dict:
    return doc["options"]["step"]["notifications"]["sections"]["instant"]["data_description"]


def test_high_priority_targets_get_every_alert_quiet_hours_included():
    for doc in _both():
        words = _instant(doc)["high_priority_targets"]
        assert "all alerts" in words
        assert "Quiet Hours included" in words
        assert "daily brief with its history" not in words.lower()
        assert "Send the Full Brief To" in words


def test_normal_priority_targets_get_every_alert_outside_quiet_hours():
    for doc in _both():
        words = _instant(doc)["normal_priority_targets"]
        assert "all alerts" in words
        assert "except during Quiet Hours" in words
        assert "daily brief only" not in words.lower()
        assert "Send the Full Brief To" in words


def test_quiet_hours_say_high_priority_targets_still_hear():
    """Quiet Hours do not silence high-priority targets, so the screen
    does not say "Nothing is sent" (rule NOTE-07)."""
    for doc in _both():
        words = doc["options"]["step"]["notifications"]["sections"]["quiet"][
            "data_description"]["quiet_hours_enabled"]
        assert "Nothing is sent" not in words
        assert "High-Priority Targets" in words
        assert "Normal-Priority Targets" in words


def test_hardware_to_study_is_in_title_case():
    for doc in _both():
        label = doc["options"]["step"]["extended"]["data"]["study_hardware"]
        assert label == "Hardware to Study"


def test_strings_and_english_carry_the_same_words():
    strings, english = _both()
    assert strings == english
