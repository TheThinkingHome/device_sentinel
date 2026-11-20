# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_translation_files.py, Version: 0.29.8 (2026-11-20)

"""Each language file fits en.json, and Home Assistant shows it.

A language file holds only rows of en.json, with the same placeholders,
the same link form and the same bold marks, so no settings screen opens
with a missing or broken field. Home Assistant then serves the language
for a person who picks it, and English for any row it does not hold.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

ROOT = Path(__file__).parent.parent / "custom_components" / "device_sentinel" / "translations"
LANGUAGES = sorted(p for p in ROOT.glob("*.json") if p.name != "en.json")
PLACEHOLDER = re.compile(r"\{[a-z_]*\}")
LINK = re.compile(r"\]\((\{[a-z_]+\})\)")


def _flat(node, path=""):
    for key, value in node.items():
        here = f"{path}.{key}" if path else key
        if isinstance(value, dict):
            yield from _flat(value, here)
        else:
            yield here, value


ENGLISH = dict(_flat(json.loads((ROOT / "en.json").read_text(encoding="utf-8"))))


def test_spanish_french_and_polish_ship():
    assert {p.name for p in LANGUAGES} >= {"es.json", "fr.json", "pl.json"}


@pytest.mark.parametrize("file", LANGUAGES, ids=lambda f: f.name)
def test_a_language_file_fits_the_english(file: Path):
    rows = dict(_flat(json.loads(file.read_text(encoding="utf-8"))))
    assert set(rows) <= set(ENGLISH), sorted(set(rows) - set(ENGLISH))
    for key, text in rows.items():
        english = ENGLISH[key]
        assert text.strip(), key
        assert sorted(PLACEHOLDER.findall(text)) == sorted(PLACEHOLDER.findall(english)), key
        assert sorted(LINK.findall(text)) == sorted(LINK.findall(english)), key
        assert text.count("**") == english.count("**"), key
        assert "—" not in text, key


@pytest.mark.parametrize("name", ["es.json", "pl.json"])
def test_a_complete_language_has_every_row(name: str):
    rows = dict(_flat(json.loads((ROOT / name).read_text(encoding="utf-8"))))
    assert set(rows) == set(ENGLISH)


async def test_home_assistant_serves_spanish(hass: HomeAssistant, enable_custom_integrations):
    spanish = await async_get_translations(hass, "es", "options", ["device_sentinel"])
    english = await async_get_translations(hass, "en", "options", ["device_sentinel"])
    key = "component.device_sentinel.options.step.advanced.data.cached_integrations"
    assert english[key] == "Integrations That Report Cached Values"
    assert spanish[key] == "Integraciones que devuelven valores en caché"
    title = "component.device_sentinel.options.step.init.description"
    assert "aplicación" not in english[title] and "Notificaciones" in spanish[title]


async def test_home_assistant_serves_polish(hass: HomeAssistant, enable_custom_integrations):
    polish = await async_get_translations(hass, "pl", "options", ["device_sentinel"])
    english = await async_get_translations(hass, "en", "options", ["device_sentinel"])
    key = "component.device_sentinel.options.step.advanced.data.cached_integrations"
    assert english[key] == "Integrations That Report Cached Values"
    assert polish[key] == "Integracje raportujące wartości z pamięci podręcznej"
    title = "component.device_sentinel.options.step.init.title"
    assert polish[title] == "Konfiguracja Device Sentinel"
