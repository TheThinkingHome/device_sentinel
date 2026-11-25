# File: tools/translation/phrase_sheet.py, Version: 0.30.7 (2026-11-24)
"""Translation workbooks for the phrase files, one block at a time (rule GEN-12).

A key's first word names its block: brief, push and common go in the
Brief and Pushes workbook, dashboard in the Dashboard workbook, the rest
in the third. A phrase that changes with a number gets one row for each
plural form the language needs, beside the English form it follows.

Build a workbook (any translation already in CODE.json is filled in):
    python3 -I phrase_sheet.py build phrases/en.json out.xlsx BLOCK CODE NAME VERSION DATE [CODE.json]
    BLOCK is brief, dashboard or rest; for example: brief pl Polish VERSION DATE
Read a returned workbook into the language's phrase file:
    python3 -I phrase_sheet.py return returned.xlsx phrases/en.json CODE.json report.txt
Rows that fail a check are left out and listed; the rest are written.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys

PLACEHOLDER = re.compile(r"\{[a-z_]+\}")
BLOCKS = {"brief": "Brief and Pushes", "dashboard": "Dashboard", "rest": "The Rest"}
LANGUAGE_FORMS = {
    "pl": ("one", "few", "many", "other"),
    "ru": ("one", "few", "many", "other"),
}
HEAD = ["Key (do not edit)", "Form", "English", "Translation", "Tips for translator", "Questions for James", "Fingerprint"]


def block_of(key: str) -> str:
    first = key.split(".", 1)[0]
    if first in ("brief", "push", "common"):
        return "brief"
    if first == "dashboard":
        return "dashboard"
    return "rest"


def forms_for(code: str) -> tuple[str, ...]:
    return LANGUAGE_FORMS.get(code.split("-")[0], ("one", "other"))


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def rows(english: dict, block: str, code: str, existing: dict | None = None) -> list[list]:
    """The workbook's rows: key, form, English, translation, tips, question, fingerprint."""
    existing = existing or {}
    out = []
    for key, value in english.items():
        if key.startswith("_") or block_of(key) != block:
            continue
        have = existing.get(key)
        if isinstance(value, dict):
            for form in forms_for(code):
                source = value["one"] if form == "one" else value["other"]
                done = have.get(form, "") if isinstance(have, dict) else ""
                tip = f"Used when the number is in the \"{form}\" group of your language."
                out.append([key, form, source, done, tips(source, tip), "", fingerprint(source)])
        else:
            out.append([key, "", value, have if isinstance(have, str) else "", tips(value), "", fingerprint(value)])
    return out


def tips(text: str, more: str = "") -> str:
    found = PLACEHOLDER.findall(text)
    keep = f"Keep {', '.join(found)} as written; the code fills it in." if found else ""
    return " ".join(part for part in (keep, more) if part)


def take_back(english: dict, returned: list[list], existing: dict) -> tuple[dict, list[str]]:
    """Merge returned rows into the language's phrases; list what was left out and why."""
    merged = {k: (dict(v) if isinstance(v, dict) else v) for k, v in existing.items()}
    problems = []
    for key, form, source, text, _tip, question, mark in returned:
        if question:
            problems.append(f"{key} {form}: question: {question}")
        if not text:
            continue
        value = english.get(key)
        if value is None:
            problems.append(f"{key}: no such key, left out")
            continue
        current = (value["one"] if form == "one" else value["other"]) if isinstance(value, dict) else value
        if fingerprint(current) != mark:
            problems.append(f"{key} {form}: the English changed since the sheet was sent, left out")
            continue
        wanted = set(PLACEHOLDER.findall(current)) - ({"{count}"} if form else set())
        if not wanted <= set(PLACEHOLDER.findall(text)) or not set(PLACEHOLDER.findall(text)) <= set(PLACEHOLDER.findall(current)):
            problems.append(f"{key} {form}: placeholders differ from the English, left out")
            continue
        if form:
            slot = merged.get(key)
            merged[key] = slot if isinstance(slot, dict) else {}
            merged[key][form] = text
        else:
            merged[key] = text
    return merged, problems


def build(src: str, out: str, block: str, code: str, name: str, version: str, date: str, have: str | None) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    english = json.load(open(src, encoding="utf-8"))
    existing = json.load(open(have, encoding="utf-8")) if have else {}
    book = Workbook()
    sheet = book.active
    sheet.title = "Translations"
    sheet.append([*HEAD[:3], name, *HEAD[4:]])
    for row in rows(english, block, code, existing):
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for column, width in zip("ABCDEFG", (34, 8, 50, 50, 40, 30, 12)):
        sheet.column_dimensions[column].width = width
    for line in sheet.iter_rows(min_row=2):
        for cell in line:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.column_dimensions["G"].hidden = True
    sheet.freeze_panes = "A2"
    info = book.create_sheet("File info")
    for pair in (("Block", BLOCKS[block]), ("Language", f"{name} ({code})"), ("Device Sentinel", version),
                 ("Prepared", date), ("Source file", "custom_components/device_sentinel/phrases/en.json"),
                 ("Translated by (your GitHub name)", "")):
        info.append(list(pair))
    book.save(out)


def take(xlsx: str, src: str, target: str, report: str) -> int:
    from openpyxl import load_workbook

    english = json.load(open(src, encoding="utf-8"))
    try:
        existing = json.load(open(target, encoding="utf-8"))
    except FileNotFoundError:
        existing = {}
    sheet = load_workbook(xlsx)["Translations"]
    returned = [[cell if cell is not None else "" for cell in row] for row in sheet.iter_rows(min_row=2, values_only=True)]
    merged, problems = take_back(english, returned, existing)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    with open(report, "w", encoding="utf-8") as handle:
        handle.write("\n".join(problems or ["Every row passed."]) + "\n")
    return 1 if any("left out" in p for p in problems) else 0


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(*sys.argv[2:9], sys.argv[9] if len(sys.argv) > 9 else None)
    elif sys.argv[1] == "return":
        sys.exit(take(*sys.argv[2:6]))
    else:
        sys.exit(__doc__)
