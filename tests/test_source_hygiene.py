# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_source_hygiene.py, Version: 0.16.8 (2026-08-20)

"""Two guards against a class of edit accident nothing else can see.

On 20 August a deep pass found three sites where an edit had spliced
a line into a call at the wrong indentation. All three were valid
Python, so the suite, ruff at its pinned rules, and bandit passed
over every one. Two were logging calls whose placeholder and
argument counts no longer matched: Python's logging swallows that
mismatch inside its own handler, so the message never reaches the
log and the caller never learns. One of the two was the trim's only
error path, telling a person their storage copy failed; it had never
once produced its message. The third was a field tuple pasted twice,
inert by luck because the reader only takes a minimum and a maximum.

Ruff carries the rule for the logging half and cannot apply it here,
because it resolves a logger only where `logging.getLogger` sits in
the same file, and this project binds LOGGER once in `const.py`. So
the check lives in the suite instead, beside the citation guard,
which is the same idea (ruling #233): a convention the code relies
on, watched by the code.

What these prove is narrow and stated plainly. The first proves
every LOGGER call formats: the count of `%` conversions in a
constant format string equals the count of arguments. It cannot
judge an f-string or a computed format, and skips them. The second
proves no line inside an open bracket sits at or below the indent of
the line that opened it, which is the fingerprint all three
accidents shared. Neither can tell a wrong argument from a right
one; that still needs a person reading.
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize

PACKAGE = pathlib.Path(
    __import__("custom_components.device_sentinel.const", fromlist=["const"])
    .__file__
).parent
TESTS = pathlib.Path(__file__).parent

# The printf conversions Python's %-formatting accepts, with %% left
# out because it is an escaped percent rather than a placeholder.
PLACEHOLDER = re.compile(
    r"%(?!%)[-+ #0]*[0-9*]*(?:\.[0-9*]+)?[hlL]?[diouxXeEfFgGcrsa]"
)

LOG_METHODS = frozenset(
    ("debug", "info", "warning", "error", "exception", "critical")
)


def _sources() -> list[pathlib.Path]:
    """Every Python file the guards read: the package and the tests."""
    return sorted(PACKAGE.glob("*.py")) + sorted(TESTS.glob("*.py"))


def _logger_mismatches(path: pathlib.Path) -> list[str]:
    """Return every LOGGER call whose arguments cannot format.

    Only calls with a constant format string are judged, because a
    computed format cannot be counted from the outside. Mapping-style
    formats and starred arguments are skipped for the same reason.
    Implicit string concatenation is one constant by the time the
    parser is done, so a format built from adjacent literals counts
    as the whole it is.
    """
    found: list[str] = []
    tree = ast.parse(path.read_text(), str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in LOG_METHODS:
            continue
        target = getattr(func.value, "id", getattr(func.value, "attr", ""))
        if "LOGGER" not in str(target):
            continue
        if not node.args:
            continue
        if any(isinstance(arg, ast.Starred) for arg in node.args):
            continue
        try:
            fmt = ast.literal_eval(node.args[0])
        except (ValueError, TypeError, SyntaxError):
            continue
        if not isinstance(fmt, str) or "%(" in fmt:
            continue
        wanted = len(PLACEHOLDER.findall(fmt))
        supplied = len(node.args) - 1
        if wanted != supplied:
            found.append(
                f"{path.name}:{node.lineno} wants {wanted} "
                f"argument(s) and got {supplied}"
            )
    return found


def _sunken_continuations(path: pathlib.Path) -> list[str]:
    """Return every continuation line at or below its bracket's line.

    The opener's indent is the indent of the line the bracket sits
    on, and everything inside the bracket belongs further right. A
    line starting with a closing bracket is the conventional
    exception and is allowed. Lines inside a string are part of one
    token and never start a line of their own, so they cannot trip
    this.
    """
    source = path.read_text()
    lines = source.splitlines()
    found: list[str] = []
    openers: list[int] = []
    flagged: set[int] = set()
    skip = (
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.COMMENT,
        tokenize.INDENT,
        tokenize.DEDENT,
    )
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.OP and tok.string in "([{":
            row = tok.start[0]
            line = lines[row - 1]
            openers.append(len(line) - len(line.lstrip()))
        elif tok.type == tokenize.OP and tok.string in ")]}":
            if openers:
                openers.pop()
        elif openers and tok.type not in skip:
            row = tok.start[0]
            line = lines[row - 1]
            indent = len(line) - len(line.lstrip())
            first_on_line = tok.start[1] == indent
            closes = line.lstrip().startswith((")", "]", "}"))
            if (
                first_on_line
                and not closes
                and indent <= openers[-1]
                and row not in flagged
            ):
                flagged.add(row)
                found.append(f"{path.name}:{row} sits at indent {indent}")
    return found


def test_every_logger_call_can_format_its_message():
    """A message that cannot format is a message nobody gets.

    The trim's abandoned-copy error and the broker watch's startup
    failure both carried this fault, one for a day and one for
    twelve, and neither ever said its sentence.
    """
    found = [
        line for path in _sources() for line in _logger_mismatches(path)
    ]
    assert not found, "\n".join(found)


def test_no_line_inside_a_bracket_sinks_to_its_opener():
    """The shared fingerprint of all three 20 August edit accidents."""
    found = [
        line for path in _sources() for line in _sunken_continuations(path)
    ]
    assert not found, "\n".join(found)
