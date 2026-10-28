# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tools/compare_code.py, Version: 0.27.10 (2026-10-27)

"""Prove that two trees differ only in comments and docstrings.

Each Python file is parsed, its docstrings dropped and its syntax tree
compared. Each JavaScript file has its comments taken out and its
whitespace folded, then is compared as text. Any other difference is
a change to the code and is listed.

With --text, a file whose only other change is to the words in its
strings or the names of its functions is listed as text only, with
each string that changed, so the words can be read; logic is still
proved unchanged.

    python3 tools/compare_code.py [--text] OLD_TREE NEW_TREE [FILE ...]

Exit code 0 when only comments and docstrings differ, or with --text,
when nothing but text differs.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from check_comments import js_comments  # noqa: E402


def _python_shape(source: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree, include_attributes=False)


def _python_words(source: str) -> tuple[str, list[str]]:
    """The shape with every string and function name blanked, and the
    strings and names in order."""
    tree = ast.parse(_python_unshaped(source))
    words: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            words.append(node.value)
            node.value = ""
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            words.append(node.name)
            node.name = ""
    return ast.dump(tree, include_attributes=False), words


def _python_unshaped(source: str) -> str:
    """The source with its docstrings taken out."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


JS_STRING = re.compile(r"\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`")


def _js_words(source: str) -> tuple[str, list[str]]:
    """The code with every string blanked, and the strings in order."""
    code = _js_shape(source)
    words = JS_STRING.findall(code)
    return JS_STRING.sub('""', code), words


def _js_shape(source: str) -> str:
    lines = source.split("\n")
    for number, text in sorted(js_comments(source), reverse=True):
        row = lines[number - 1]
        at = row.find(text)
        if at >= 0:
            lines[number - 1] = row[:at] + row[at + len(text):]
    return re.sub(r"\s+", " ", "\n".join(lines)).strip()


def main(old: pathlib.Path, new: pathlib.Path, only: list[str], text: bool = False) -> int:
    names = only or sorted(
        str(p.relative_to(new))
        for pattern in ("custom_components/**/*.py", "tests/*.py", "tools/**/*.py", "custom_components/**/*.js", "tools/panel_checks/*.js")
        for p in new.glob(pattern)
        if "__pycache__" not in p.parts
    )
    changed = []
    for name in names:
        a, b = old / name, new / name
        if not a.exists():
            changed.append(f"{name}: new file")
            continue
        sa, sb = a.read_text(encoding="utf-8"), b.read_text(encoding="utf-8")
        if sa == sb:
            continue
        try:
            same = (
                _js_shape(sa) == _js_shape(sb) if name.endswith(".js") else _python_shape(sa) == _python_shape(sb)
            )
        except SyntaxError as err:
            changed.append(f"{name}: does not parse ({err})")
            continue
        if not same and text:
            try:
                words = _js_words if name.endswith(".js") else _python_words
                (shape_a, words_a), (shape_b, words_b) = words(sa), words(sb)
            except SyntaxError:
                shape_a, shape_b, words_a, words_b = "a", "b", [], []
            if shape_a == shape_b and len(words_a) == len(words_b):
                print(f"{name}: text only")
                for before, after in zip(words_a, words_b):
                    if before != after:
                        print(f"    - {before[:200]!r}")
                        print(f"    + {after[:200]!r}")
                continue
        if not same:
            changed.append(f"{name}: code changed")
    for line in changed:
        print(line)
    print(f"{len(changed)} file(s) with a code change, of {len(names)} compared")
    return 1 if changed else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    text = "--text" in args
    args = [a for a in args if a != "--text"]
    sys.exit(main(pathlib.Path(args[0]), pathlib.Path(args[1]), args[2:], text))
