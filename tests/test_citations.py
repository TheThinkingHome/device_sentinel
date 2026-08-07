# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_citations.py, Version: 0.12.10 (2026-08-07)

"""Every ruling cited in the source is a ruling that exists.

The comments and docstrings in this project cite the decision that
produced them, so a reader following a citation reaches the reasoning
rather than a rediscovered argument. That only works while the
numbers are real, and two were not: one was a typo for a ruling that
does exist, and one pointed at reasoning that was never written down.
Both sat in the tree for weeks, because nothing looked (ruling #233).

The decision history is not in this repository, so the ceiling lives
in `const.py` as HIGHEST_RULING. That is a hand-maintained number,
which #215 warned about, and the warning was about a list that drifts
silently while its guard keeps passing. This one cannot: it is a
single number, and a stale one fails the suite the moment a new
citation is written rather than going quiet.

What this proves is that a cited ruling exists. It cannot prove the
citation is the right one, and a number pointing at real reasoning
about something else would pass. That needs a person reading, and
this guard does not pretend otherwise.
"""

from __future__ import annotations

import pathlib
import re

from custom_components.device_sentinel.const import HIGHEST_RULING

PACKAGE = pathlib.Path(
    __import__("custom_components.device_sentinel.const", fromlist=["const"])
    .__file__
).parent
TESTS = pathlib.Path(__file__).parent

# "ruling #218", "rulings #139 and #143", "#141 and #142". Anchored on
# the word, because a bare hash and digits is also a CSS colour: the
# first version of this guard reported `#444` from three stylesheets
# as a citation past the end of the history. A number is a citation
# only where "ruling" or "rulings" introduces the run it belongs to.
CITATION = re.compile(r"rulings?\s+((?:#\d+(?:\s*(?:,|and)\s*)?)+)")
NUMBER = re.compile(r"#(\d+)")


def _cited(root: pathlib.Path) -> dict[pathlib.Path, set[int]]:
    """Return every ruling number cited, by file."""
    found: dict[pathlib.Path, set[int]] = {}
    for path in sorted(root.glob("*.py")):
        text = path.read_text()
        numbers = {
            int(number)
            for run in CITATION.findall(text)
            for number in NUMBER.findall(run)
        }
        if numbers:
            found[path] = numbers
    return found


def test_the_ceiling_is_a_plausible_ruling_number():
    """A number that has slipped to zero would pass everything."""
    assert isinstance(HIGHEST_RULING, int)
    assert HIGHEST_RULING >= 232


def test_every_citation_in_the_package_exists():
    """No citation past the highest recorded ruling.

    This is the check that would have caught both faults: a
    four-hundred-odd citation in a project with 232 rulings, and one
    pointing at reasoning that had never been written down.
    """
    bad: list[str] = []
    for path, numbers in _cited(PACKAGE).items():
        for number in sorted(numbers):
            if number < 1 or number > HIGHEST_RULING:
                bad.append(f"{path.name} cites #{number}")
    assert not bad, (
        "citations past the highest recorded ruling "
        f"(#{HIGHEST_RULING}): " + ", ".join(bad)
    )


def test_every_citation_in_the_tests_exists():
    """The tests cite rulings too, and drift the same way.

    This file is included, so it cannot name a bad number as an
    example without failing itself. That is the guard working on
    itself rather than an inconvenience.
    """
    bad: list[str] = []
    for path, numbers in _cited(TESTS).items():
        for number in sorted(numbers):
            if number < 1 or number > HIGHEST_RULING:
                bad.append(f"{path.name} cites #{number}")
    assert not bad, (
        "citations past the highest recorded ruling "
        f"(#{HIGHEST_RULING}): " + ", ".join(bad)
    )


def test_the_citations_are_actually_being_found():
    """A guard that matches nothing passes forever.

    #215's lesson in its own shape: a check that silently stops
    checking is worse than no check, so this asserts the reader is
    still reading. The package carries citations in most files and
    always will, since the project's rule is that a decided point is
    referred to by its number rather than re-argued.
    """
    cited = _cited(PACKAGE)
    assert len(cited) >= 10, "the citation reader found almost nothing"
    everything = {n for numbers in cited.values() for n in numbers}
    assert len(everything) >= 40
    assert max(everything) <= HIGHEST_RULING
