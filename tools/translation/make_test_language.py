# File: tools/translation/make_test_language.py, Version: 0.30.10 (2026-11-25)
"""Make the test language from the English phrase file (rule GEN-12).

Every phrase is the English wrapped in markers no keyboard types:
⟦ ⟧ around the phrase and ⟨ ⟩ around each value the code fills in, so
on a page or in a report, text without markers is text not yet in the
phrase file. A phrase that changes with a number gets one form per
plural category of the language it is filed as, each naming its form:
⟦few: ⟨3⟩ devices⟧. Filed as Russian it has Polish's four forms.

It ships as phrases/test.json, made with ru, and a house reads in it only
while an empty file named test_language sits in its device_sentinel folder.
Usage:
    python3 -I make_test_language.py phrases/en.json phrases/test.json [ru]
"""

import json
import re
import sys

PLACEHOLDER = re.compile(r"\{[a-z_]+\}")
FORMS = {"ru": ("one", "few", "many", "other"), "pl": ("one", "few", "many", "other")}


def marked(text: str) -> str:
    return PLACEHOLDER.sub(lambda m: f"⟨{m.group(0)}⟩", text)


def make(english: dict, code: str = "ru") -> dict:
    out = {}
    for key, value in english.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            out[key] = {
                form: f"⟦{form}: {marked(value['one'] if form == 'one' else value['other'])}⟧"
                for form in FORMS.get(code, ("one", "other"))
            }
        else:
            out[key] = f"⟦{marked(value)}⟧"
    return out


if __name__ == "__main__":
    source, target = sys.argv[1:3]
    code = sys.argv[3] if len(sys.argv) > 3 else "ru"
    english = json.load(open(source, encoding="utf-8"))
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(make(english, code), handle, indent=2, ensure_ascii=False)
        handle.write("\n")
