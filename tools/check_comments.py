# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tools/check_comments.py, Version: 0.27.10 (2026-10-27)

"""Check that comments and docstrings cite rules, not their history.

The code says why with a rule ID (FRZ-05), never with the number of
the decision behind it, a review, the release that added it, a person
or a date: those live in the rulebook. This reads every comment and
docstring in the integration, the tests, the panel and the tools, and
lists each line that still carries one.

    python3 tools/check_comments.py [ROOT]

Exit code 0 when clean, 1 with a list of lines otherwise.
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import sys
import tokenize

MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)

# Each pattern, and what it finds.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ruling number", re.compile(r"(?<![\w&/])#\d{1,3}(?![\w])")),
    ("ruling", re.compile(r"\b[Rr]ul(ing|ings|ed)\b")),
    ("record", re.compile(r"Decision History|Authority Document|Known Gap|Ruled Change")),
    ("review round", re.compile(
        r"\b(adversarial|review|hostile|red[- ]team)\b.{0,20}\bround\b|\bround (one|two|three|four|five|six|"
        r"seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
        r"nineteen|twenty|\d+)\b|\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|"
        r"tenth|\w+teenth|twentieth)\s+(adversarial\s+)?round\b|\bfound by (review|the)\b", re.I)),
    ("person", re.compile(r"\b(James|Tim|Plas|Christopher|Roger|Ranger)\b")),
    ("date", re.compile(rf"\b\d{{1,2}} ({MONTHS})\b|\b({MONTHS}) \d{{1,2}}(,? 20\d\d)?\b|\b({MONTHS}) 20\d\d\b")),
    ("release", re.compile(r"\b\d\.\d{1,2}\.\d{1,2}\b")),
]

HEADER = re.compile(r"^(#|//| \*)?\s*File: .*Version: ")


def _versions_in_code(source: str, javascript: bool = False) -> set[str]:
    """Versions the code itself compares with: a version string, or a
    name such as _pin_before_ followed by its digits. A comment naming one explains the code.
    Comments and docstrings are left out, so a docstring cannot vouch
    for a version."""
    if javascript:
        lines = source.split("\n")
        for number, text in sorted(js_comments(source), reverse=True):
            row = lines[number - 1]
            at = row.find(text)
            if at >= 0:
                lines[number - 1] = row[:at] + row[at + len(text):]
        code = "\n".join(lines)
    else:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return set()
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    docstrings.add(id(body[0].value))
        parts = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                parts.append(repr(node.value))
            elif isinstance(node, ast.Name):
                parts.append(node.id)
            elif isinstance(node, ast.Attribute):
                parts.append(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                parts.append(node.name)
        code = "\n".join(parts)
    found = set(re.findall(r"[\"'](\d\.\d{1,2}\.\d{1,2})[\"']", code))
    for digits in re.findall(r"_(\d)(\d{2})(\d)\b", code):
        found.add(f"{digits[0]}.{int(digits[1])}.{digits[2]}")
    return found


def _python_texts(source: str) -> list[tuple[int, str]]:
    """Each comment and each docstring line, with its line number."""
    texts: list[tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                texts.append((tok.start[0], tok.string))
    except (tokenize.TokenError, SyntaxError):
        pass
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return texts
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                start = body[0].lineno
                for offset, line in enumerate(body[0].value.value.splitlines()):
                    texts.append((start + offset, line))
    return texts


def js_comments(source: str) -> list[tuple[int, str]]:
    """Each comment in a JavaScript file, with its line number. Strings,
    template literals and regular expressions are stepped over."""
    out: list[tuple[int, str]] = []
    i, n, line = 0, len(source), 1
    prev = ""  # last significant character, to tell a regex from a division
    stack: list[str] = []  # open template literals and their braces
    while i < n:
        c = source[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if stack and stack[-1] == "`":
            if c == "\\":
                i += 2
                continue
            if c == "`":
                stack.pop()
                prev = "`"
                i += 1
                continue
            if c == "$" and i + 1 < n and source[i + 1] == "{":
                stack.append("{")
                i += 2
                prev = "{"
                continue
            i += 1
            continue
        if c == "/" and i + 1 < n and source[i + 1] == "/":
            end = source.find("\n", i)
            end = n if end == -1 else end
            out.append((line, source[i:end]))
            i = end
            continue
        if c == "/" and i + 1 < n and source[i + 1] == "*":
            end = source.find("*/", i + 2)
            end = n if end == -1 else end + 2
            block = source[i:end]
            for offset, text in enumerate(block.split("\n")):
                out.append((line + offset, text))
            line += block.count("\n")
            i = end
            continue
        if c in "'\"":
            j = i + 1
            while j < n and source[j] != c:
                if source[j] == "\\":
                    j += 1
                elif source[j] == "\n":
                    break
                j += 1
            i = j + 1
            prev = c
            continue
        if c == "`":
            stack.append("`")
            i += 1
            continue
        if c == "{" and stack:
            stack.append("{")
        elif c == "}" and stack and stack[-1] == "{":
            stack.pop()
            if stack and stack[-1] == "`":
                i += 1
                continue
        if c == "/" and (prev == "" or prev in "(,=:[!&|?{};+-*%<>~^" or source[max(0, i - 7):i].rstrip().endswith(("return", "typeof"))):
            j = i + 1
            in_class = False
            while j < n and source[j] != "\n":
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == "[":
                    in_class = True
                elif source[j] == "]":
                    in_class = False
                elif source[j] == "/" and not in_class:
                    break
                j += 1
            i = j + 1
            while i < n and source[i].isalpha():
                i += 1
            prev = "/"
            continue
        if not c.isspace():
            prev = c
        i += 1
    return out


def check_text(path: str, texts: list[tuple[int, str]], allowed: set[str]) -> list[str]:
    found = []
    for number, text in texts:
        if HEADER.search(text) or "Copyright (C)" in text:
            continue
        for label, pattern in PATTERNS:
            for match in pattern.finditer(text):
                if label == "release" and match.group(0) in allowed:
                    continue
                found.append(f"{path}:{number}: {label}: {text.strip()[:160]}")
                break
            else:
                continue
            break
    return found


def main(root: pathlib.Path) -> int:
    found: list[str] = []
    files = (
        sorted((root / "custom_components").rglob("*.py"))
        + sorted((root / "tests").glob("*.py"))
        + sorted((root / "tools").rglob("*.py"))
        + sorted((root / "custom_components").rglob("*.js"))
        + sorted((root / "tools" / "panel_checks").glob("*.js"))
    )
    for path in files:
        if "node_modules" in path.parts or "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(root))
        allowed = _versions_in_code(source, path.suffix == ".js")
        texts = js_comments(source) if path.suffix == ".js" else _python_texts(source)
        found.extend(check_text(rel, texts, allowed))
    for line in found:
        print(line)
    print(f"{len(found)} line(s) found in {len(files)} file(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()))
