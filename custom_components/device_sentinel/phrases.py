# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: phrases.py, Version: 0.30.8 (2026-11-24)

"""The words Device Sentinel writes, read from its phrase files (rule GEN-12).

Each language has one file in `phrases/`, named by its code (`en.json`,
`fr.json`), mapping a key to its text. A key names the block it belongs
to by its first word: `brief.` and `push.` for the Daily Brief and the
pushes, `dashboard.` for the dashboard page, `common.` for words several
use (month names, AM and PM), anything else for the rest. A text holds
`{name}` placeholders the code fills in. A text that changes with a
number is a set of forms, one per plural category of its language
(`one`, `few`, `many`, `other`), and `{count}` is the number.

A phrase a language leaves out, or a form it leaves out, is read from
English, with English's own plural rules, so a partial translation is
safe to ship. The files are read once, off the event loop, when Device
Sentinel starts; reading a phrase never touches the disk.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

FOLDER = Path(__file__).parent / "phrases"
ENGLISH = "en"
FORMS = ("zero", "one", "two", "few", "many", "other")
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")

_FILES: dict[str, dict[str, Any]] = {}
_LOADED: list[bool] = [False]


def load(folder: Path | None = None) -> None:
    """Read every phrase file in the folder; a file that cannot be read
    is left out, and its language reads English."""
    found: dict[str, dict[str, Any]] = {}
    for path in sorted((folder or FOLDER).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            found[path.stem] = {k: v for k, v in data.items() if not k.startswith("_")}
    _FILES.clear()
    _FILES.update(found)
    _LOADED[0] = True


def languages() -> list[str]:
    """The languages with a phrase file."""
    if not _LOADED[0]:
        load()
    return sorted(_FILES)


def _file_for(language: str) -> tuple[str, dict[str, Any]]:
    """The file for a language: its own (pt-BR), its family's (pt), or
    English."""
    for code in (language, language.split("-")[0]):
        if code in _FILES:
            return code, _FILES[code]
    return ENGLISH, _FILES.get(ENGLISH, {})


def page_words(language: str) -> dict[str, Any]:
    """The words the dashboard draws itself, for a viewer's language: its
    own file's and English beside them, `dashboard.` and `common.`."""
    if not _LOADED[0]:
        load()
    code, own = _file_for(language)

    def page(found: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in found.items() if k.startswith(("dashboard.", "common."))}

    english = page(_FILES.get(ENGLISH, {}))
    return {"language": code, "phrases": page(own) if code != ENGLISH else {}, "english": english}


def plural(language: str, count: float) -> str:
    """The plural category of a number in a language, as Unicode's CLDR
    rules name it, for the languages Device Sentinel has or plans."""
    base = language.split("-")[0]
    whole = float(count).is_integer()
    i = int(abs(count)) if whole else None
    if base == "fr":
        return "one" if 0 <= abs(count) < 2 else "other"
    if base in ("pl", "ru"):
        if i is None:
            return "other"
        tens, hundreds = i % 10, i % 100
        if base == "pl" and i == 1:
            return "one"
        if base == "ru" and tens == 1 and hundreds != 11:
            return "one"
        if 2 <= tens <= 4 and not 12 <= hundreds <= 14:
            return "few"
        return "many"
    return "one" if i == 1 else "other"


def _fill(text: str, values: dict[str, Any]) -> str:
    return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def say(key: str, language: str | None = None, count: float | None = None, **values: Any) -> str:
    """The text of a phrase in a language (the house's when none is
    given), its placeholders filled in. A key no file knows reads as
    the key itself, which the tests never let ship."""
    if not _LOADED[0]:
        load()
    if language is None:
        from . import clock

        language = clock.language()
    wanted = language
    code, phrases = _file_for(wanted)
    entry = phrases.get(key)
    if entry is None and code != ENGLISH:
        code, entry = ENGLISH, _FILES.get(ENGLISH, {}).get(key)
    if entry is None:
        return key
    if count is not None:
        values = {"count": count, **values}
    if isinstance(entry, dict):
        form = plural(code, count if count is not None else 0)
        text = entry.get(form) or entry.get("other")
        if text is None and code != ENGLISH:
            english = _FILES.get(ENGLISH, {}).get(key)
            if isinstance(english, dict):
                text = english.get(plural(ENGLISH, count if count is not None else 0)) or english.get("other")
        entry = text if text is not None else key
    return _fill(str(entry), values)


# Home Assistant imports an integration off the event loop, so the files
# are read here, before anything can ask for a phrase.
load()
