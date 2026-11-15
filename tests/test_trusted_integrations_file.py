# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_trusted_integrations_file.py, Version: 0.29.1 (2026-11-14)

"""docs/TRUSTED_INTEGRATIONS.md and the list in the code agree (rule
WATCH-12).

The file gives, for every integration checked, whether Device Sentinel
takes it as reporting cached values after a restart, and why. The code
holds the list itself. One cannot change without the other.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from custom_components.device_sentinel.restart_values import (
    CACHED_VALUE_INTEGRATIONS,
    LAST_SEEN_BY_RULE,
)

FILE = Path(__file__).resolve().parents[1] / "docs" / "TRUSTED_INTEGRATIONS.md"
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
