# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: conftest.py, Version: 0.7.5 (2026-07-23)

"""Shared test fixtures.

The harness gives every test the same config directory, a fixed path
inside the installed package rather than a temporary one, so any file
a test writes survives into the next test and into later runs. A
daily brief written by an older version was still being read days
afterwards, which failed a correct change and could as easily have
passed an incorrect one. Every test now starts from an empty report
directory.
"""

import glob
import os
import shutil

import pytest
from pytest_homeassistant_custom_component.common import (
    get_test_config_dir,
)

REPORT_DIRECTORY = os.path.join(get_test_config_dir(), "device_sentinel")


@pytest.fixture(autouse=True)
def clean_report_directory():
    """Give each test an empty report directory, before and after."""
    shutil.rmtree(REPORT_DIRECTORY, ignore_errors=True)
    yield
    shutil.rmtree(REPORT_DIRECTORY, ignore_errors=True)


@pytest.fixture
def read_brief():
    """Return a reader for whichever brief was written.

    The file is named for the day its window opened, which is not
    today's date when the window began before the brief hour, so
    tests locate it rather than reconstructing the name.
    """

    def _read(hass):
        pattern = os.path.join(
            hass.config.path("device_sentinel"), "daily_brief_*.md"
        )
        written = sorted(glob.glob(pattern))
        assert written, "no daily brief was written"
        assert len(written) == 1, f"expected one brief, found {written}"
        with open(written[0], encoding="utf-8") as handle:
            return handle.read()

    return _read
