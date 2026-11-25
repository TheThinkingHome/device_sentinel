"""The words come from the phrase files (rule GEN-12).

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_phrases.py, Version: 0.30.7 (2026-11-24)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

Every key the code uses is in the English file and no English key sits
unused. Every language's phrases carry English's placeholders and the
plural forms the language needs. A phrase or form a language leaves out
reads English, by English's own plural rules. The test language, the
English wrapped in markers and filed as Russian, runs every phrase
through the reader.
"""

import ast
import importlib.util
import json
import re
import shutil
from datetime import date, datetime
from pathlib import Path

import pytest

from custom_components.device_sentinel import clock, phrases

ROOT = Path(__file__).resolve().parent.parent
CODE = ROOT / "custom_components" / "device_sentinel"
FOLDER = CODE / "phrases"
KEY = re.compile(r"^(?:brief|push|dashboard|common|[a-z_]+)\.[a-z0-9_.]+$")
NEEDED = {"en": {"one", "other"}, "fr": {"one", "other"}, "es": {"one", "other"},
          "pl": {"one", "few", "many", "other"}, "ru": {"one", "few", "many", "other"}}


def _english():
    return json.loads((FOLDER / "en.json").read_text(encoding="utf-8"))


def _maker():
    spec = importlib.util.spec_from_file_location("make_test_language", ROOT / "tools" / "translation" / "make_test_language.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _literals():
    """Every string in the code that could name a phrase, and every key handed to say()."""
    found, asked = set(), set()
    for path in CODE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and KEY.match(node.value):
                found.add(node.value)
            if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == "say" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant):
                    asked.add(first.value)
    panel = (CODE / "frontend" / "panel.js").read_text(encoding="utf-8")
    found |= {m for m in re.findall(r"[\"'`]([a-z_]+\.[a-z0-9_.]+)[\"'`]", panel) if KEY.match(m)}
    return found, asked


@pytest.fixture(autouse=True)
def _real_files_after():
    yield
    phrases.load()
    clock.bind(None, "en")


@pytest.fixture
def test_language(tmp_path):
    """The shipped files plus the test language, filed as Russian."""
    for path in FOLDER.glob("*.json"):
        shutil.copy(path, tmp_path / path.name)
    (tmp_path / "ru.json").write_text(json.dumps(_maker().make(_english(), "ru"), ensure_ascii=False), encoding="utf-8")
    phrases.load(tmp_path)
    return tmp_path


def test_only_english_ships():
    assert sorted(p.name for p in FOLDER.glob("*.json")) == ["en.json"]


def test_english_file_is_well_formed():
    english = _english()
    for key, value in english.items():
        assert KEY.match(key), key
        if isinstance(value, dict):
            assert set(value) == NEEDED["en"], key
            assert all(isinstance(text, str) and text for text in value.values()), key
        else:
            assert isinstance(value, str) and value, key


def test_every_key_the_code_uses_is_in_english():
    english = _english()
    _found, asked = _literals()
    assert asked, "the scan found no say() calls"
    assert sorted(asked - set(english)) == []


def test_no_english_key_sits_unused():
    found, _asked = _literals()
    assert sorted(set(_english()) - found) == []


def test_every_language_carries_englishs_placeholders_and_forms():
    english = _english()
    for path in FOLDER.glob("*.json"):
        code = path.stem
        language = json.loads(path.read_text(encoding="utf-8"))
        for key, value in language.items():
            assert key in english, f"{code}: {key} is not in English"
            source = english[key]
            if isinstance(source, dict):
                assert isinstance(value, dict), f"{code}: {key} needs its plural forms"
                assert NEEDED.get(code.split("-")[0], {"one", "other"}) <= set(value), f"{code}: {key}"
                wanted = set(phrases.PLACEHOLDER.findall(source["other"])) - {"count"}
                texts = value.values()
            else:
                wanted = set(phrases.PLACEHOLDER.findall(source))
                texts = [value]
            for text in texts:
                assert set(phrases.PLACEHOLDER.findall(text)) - {"count"} == wanted, f"{code}: {key}"


@pytest.mark.parametrize(("language", "numbers", "forms"), [
    ("en", [0, 1, 2, 1.5], ["other", "one", "other", "other"]),
    ("fr", [0, 1, 1.5, 2], ["one", "one", "one", "other"]),
    ("es", [0, 1, 2], ["other", "one", "other"]),
    ("pl", [0, 1, 2, 4, 5, 12, 21, 22, 25, 112, 1.5], ["many", "one", "few", "few", "many", "many", "many", "few", "many", "many", "other"]),
    ("ru", [0, 1, 2, 5, 11, 12, 21, 22, 111, 1.5], ["many", "one", "few", "many", "many", "many", "one", "few", "many", "other"]),
    ("pt-BR", [1, 2], ["one", "other"]),
])
def test_plural_rules(language, numbers, forms):
    assert [phrases.plural(language, n) for n in numbers] == forms


def test_every_phrase_reads_in_the_test_language(test_language):
    english = _english()
    for key, value in english.items():
        names = phrases.PLACEHOLDER.findall(value["other"] if isinstance(value, dict) else value)
        values = {name: f"v{name}" for name in names if name != "count"}
        text = phrases.say(key, "ru", count=3 if isinstance(value, dict) else None, **values)
        assert text.startswith("⟦") and text.endswith("⟧"), (key, text)
        for name in values:
            assert f"⟨v{name}⟩" in text, (key, text)


def test_the_test_language_names_its_plural_forms(test_language, tmp_path):
    english = _english()
    english["common.test_count"] = {"one": "{count} device", "other": "{count} devices"}
    (tmp_path / "ru.json").write_text(json.dumps(_maker().make(english, "ru"), ensure_ascii=False), encoding="utf-8")
    (tmp_path / "en.json").write_text(json.dumps(english), encoding="utf-8")
    phrases.load(tmp_path)
    said = {n: phrases.say("common.test_count", "ru", count=n) for n in (1, 3, 5, 21, 1.5)}
    assert said == {1: "⟦one: ⟨1⟩ device⟧", 3: "⟦few: ⟨3⟩ devices⟧", 5: "⟦many: ⟨5⟩ devices⟧",
                    21: "⟦one: ⟨21⟩ device⟧", 1.5: "⟦other: ⟨1.5⟩ devices⟧"}


def test_a_missing_phrase_or_form_reads_english_by_englishs_rules(tmp_path):
    (tmp_path / "en.json").write_text(json.dumps({
        "common.a": "A {name}", "common.n": {"one": "{count} device", "other": "{count} devices"},
    }), encoding="utf-8")
    (tmp_path / "ru.json").write_text(json.dumps({"common.n": {"one": "RU one {count}"}}), encoding="utf-8")
    phrases.load(tmp_path)
    assert phrases.say("common.a", "ru", name="x") == "A x"
    # 21 is "one" in Russian, but English's "devices" is what reads.
    assert phrases.say("common.n", "ru", count=21) == "RU one 21"
    assert phrases.say("common.n", "ru", count=3) == "3 devices"
    (tmp_path / "ru.json").write_text("{}", encoding="utf-8")
    phrases.load(tmp_path)
    assert phrases.say("common.n", "ru", count=21) == "21 devices"
    assert phrases.say("common.n", "pt-BR", count=1) == "1 device"


def test_a_file_that_cannot_be_read_leaves_its_language_english(tmp_path):
    shutil.copy(FOLDER / "en.json", tmp_path / "en.json")
    (tmp_path / "ru.json").write_text("{not json", encoding="utf-8")
    phrases.load(tmp_path)
    assert phrases.languages() == ["en"]
    assert phrases.say("common.month.11", "ru") == "November"


def test_an_unknown_key_reads_as_itself():
    assert phrases.say("common.no_such_phrase") == "common.no_such_phrase"


def test_the_clock_writes_in_the_owners_language(test_language):
    class _Store:
        data = {"language": {"language": "ru", "time_format": "12", "date_format": "MDY"}}

    clock.bind(_Store(), "en")
    assert clock.day_text(date(2026, 11, 23)) == "⟦Nov⟧ 23"
    assert clock.time_text(datetime(2026, 11, 23, 17, 34)) == "5:34 ⟦PM⟧"
    assert clock.report_text(datetime(2026, 11, 23, 5, 34)) == "⟦⟨⟦November⟧ 23, 2026⟩ at ⟨5:34 ⟦AM⟧⟩⟧"


def test_the_clock_reads_as_it_did_in_english():
    clock.bind(None, "en")
    assert clock.day_text(date(2026, 9, 3)) == "Sep 3"
    assert clock.day_text(date(2026, 9, 3), year=True, long=True) == "September 3, 2026"
    assert clock.report_text(datetime(2026, 11, 23, 17, 34)) == "November 23, 2026 at 5:34 PM"
    for month in range(1, 13):
        moment = date(2026, month, 1)
        assert clock.day_text(moment).split()[0] == moment.strftime("%b")
        assert clock.day_text(moment, long=True).split()[0] == moment.strftime("%B")
