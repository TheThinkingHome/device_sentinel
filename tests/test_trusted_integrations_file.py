# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_trusted_integrations_file.py, Version: 0.29.2 (2026-11-15)

"""docs/TRUSTED_INTEGRATIONS.md, docs/UNTRUSTED_DEVICES.md and the lists
in the code agree (rule WATCH-12).

The first file gives, for every integration checked, whether Device
Sentinel takes it as reporting cached values after a restart, and why;
the second does the same for makes and models. The code holds the lists
themselves. One cannot change without the other.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from custom_components.device_sentinel.restart_values import (
    CACHED_VALUE_INTEGRATIONS,
    CACHED_VALUE_MODEL_NAMES,
    LAST_SEEN_BY_RULE,
)

FILE = Path(__file__).resolve().parents[1] / "docs" / "TRUSTED_INTEGRATIONS.md"
MODELS_FILE = Path(__file__).resolve().parents[1] / "docs" / "UNTRUSTED_DEVICES.md"
MODEL_ROW = re.compile(
    r"^\| ([^|]+) \| ([^|]+) \| ([^|]+) \| [^|]*\(`([a-z0-9_]+)`\) \| ([^|]+) \| (Strong|Fair) \| "
    r"(Code|Code and library) \| (No|Yes[^|]*) \| (\d{1,2} [A-Z][a-z]{2} \d{4}) \|$"
)
VERDICTS = {
    "Reports live", "Reports cached values", "Some models only", "Judged by last seen", "Not settled",
}
ROW = re.compile(r"^\| [^|]*\(`([a-z0-9_]+)`\) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$")


def _rows() -> dict[str, tuple[str, str, str, str]]:
    found: dict[str, tuple[str, str, str, str]] = {}
    for line in FILE.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match:
            domain = match.group(1)
            assert domain not in found, f"{domain} is listed twice"
            found[domain] = tuple(part.strip() for part in match.groups()[1:])
    return found


pytestmark = pytest.mark.shipped_cached_list


def test_the_file_and_the_code_hold_the_same_list():
    rows = _rows()
    in_file = {domain for domain, row in rows.items() if row[0] == "Reports cached values"}
    assert in_file == set(CACHED_VALUE_INTEGRATIONS)


def test_every_row_has_a_verdict_a_reason_its_evidence_and_a_date():
    rows = _rows()
    assert len(rows) >= 113
    for domain, (verdict, why, evidence, checked) in rows.items():
        assert verdict in VERDICTS, domain
        assert why.endswith(".") and len(why) > 20, domain
        assert evidence.startswith(("Code", "Seen running")), domain
        assert re.fullmatch(r"\d{1,2} [A-Z][a-z]{2} \d{4}", checked), domain


def test_what_is_judged_by_last_seen_is_never_on_the_list():
    rows = _rows()
    for domain in LAST_SEEN_BY_RULE:
        assert rows[domain][0] == "Judged by last seen"
        assert domain not in CACHED_VALUE_INTEGRATIONS
    assert rows["mqtt"][0] == "Not settled" and "mqtt" not in CACHED_VALUE_INTEGRATIONS


def test_the_file_never_names_a_house():
    text = FILE.read_text(encoding="utf-8")
    for name in ("Brian", "Tim ", "Chris", "James", "bimmer"):
        assert name not in text


def _model_rows() -> list[tuple[str, ...]]:
    found = []
    for line in MODELS_FILE.read_text(encoding="utf-8").splitlines():
        match = MODEL_ROW.match(line)
        if match:
            found.append(tuple(part.strip() for part in match.groups()))
    return found


def test_the_models_file_and_the_code_hold_the_same_models():
    in_file = [
        (maker, model, "" if model_id == "none" else model_id)
        for maker, model, model_id, *_rest in _model_rows()
    ]
    assert len(in_file) == len(set(in_file)), "a model is listed twice"
    assert set(in_file) == set(CACHED_VALUE_MODEL_NAMES)


def test_each_listed_model_is_in_an_integration_marked_some_models_only():
    rows = _rows()
    for _maker, _model, _model_id, domain, why, *_rest in _model_rows():
        assert rows[domain][0] == "Some models only", domain
        assert why.endswith(".") and len(why) > 20, domain


def test_the_models_file_never_names_a_house():
    text = MODELS_FILE.read_text(encoding="utf-8")
    for name in ("Brian", "Tim ", "Chris", "James", "bimmer"):
        assert name not in text
