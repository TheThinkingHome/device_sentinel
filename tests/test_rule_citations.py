# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_rule_citations.py, Version: 0.27.10 (2026-10-27)

"""Comments and docstrings cite rule IDs that exist, and nothing else
(rule CODE-01)."""

from __future__ import annotations

import importlib.util
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES = ROOT / "developer"
CITED = re.compile(r"\brules?\s+((?:[A-Z]{2,5}-\d{2}(?:\s*(?:,|and)\s*)?)+)")
RULE_ID = re.compile(r"[A-Z]{2,5}-\d{2}")


def _checker():
    spec = importlib.util.spec_from_file_location("check_comments", ROOT / "tools" / "check_comments.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rules() -> set[str]:
    found = set()
    for path in RULES.glob("Rulebook__*.md"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("### "):
                found.add(line[4:].split(" ", 1)[0])
    return found


def test_the_rulebook_is_in_the_repository():
    assert len(_rules()) > 250


def test_no_comment_carries_history(capsys):
    """No decision number, review, release, person or date."""
    assert _checker().main(ROOT) == 0, capsys.readouterr().out[-3000:]


def test_every_cited_rule_exists():
    checker = _checker()
    rules = _rules()
    missing = []
    for path in sorted((ROOT / "custom_components").rglob("*.py")) + sorted((ROOT / "tests").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for number, text in checker._python_texts(source):
            for run in CITED.findall(text):
                for rule in RULE_ID.findall(run):
                    if rule not in rules:
                        missing.append(f"{path.relative_to(ROOT)}:{number}: {rule}")
    for path in sorted((ROOT / "custom_components").rglob("*.js")):
        for number, text in checker.js_comments(path.read_text(encoding="utf-8")):
            for run in CITED.findall(text):
                for rule in RULE_ID.findall(run):
                    if rule not in rules:
                        missing.append(f"{path.relative_to(ROOT)}:{number}: {rule}")
    assert not missing, missing[:40]
