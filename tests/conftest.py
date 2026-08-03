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
WWW_DIRECTORY = os.path.join(get_test_config_dir(), "www", "device_sentinel")


@pytest.fixture(autouse=True)
def clean_report_directory():
    """Give each test empty report directories, before and after.

    Both folders since 0.10.18: what a person reads lives under www
    (#178), and a dated brief left by one test is a wrong answer in
    the next test's file count.
    """
    shutil.rmtree(REPORT_DIRECTORY, ignore_errors=True)
    shutil.rmtree(WWW_DIRECTORY, ignore_errors=True)
    yield
    shutil.rmtree(REPORT_DIRECTORY, ignore_errors=True)
    shutil.rmtree(WWW_DIRECTORY, ignore_errors=True)


@pytest.fixture
def read_brief():
    """Return a reader for whichever brief was written.

    The file is named for the day its window opened, which is not
    today's date when the window began before the brief hour, so
    tests locate it rather than reconstructing the name.
    """

    def _read(hass):
        # The file on disk is the rendered page (0.10.18); the one-
        # file naming discipline is still asserted on it, and the
        # composed text is returned, because it is the message field
        # and the source the page renders from, so its prose is the
        # prose these tests examine.
        pattern = os.path.join(
            hass.config.path("www", "device_sentinel"),
            "daily_brief_2*.html",
        )
        written = sorted(glob.glob(pattern))
        assert written, "no daily brief was written"
        assert len(written) == 1, f"expected one brief, found {written}"
        from custom_components.device_sentinel.const import DOMAIN

        entry = hass.config_entries.async_entries(DOMAIN)[0]
        return entry.runtime_data._last_brief_text

    return _read
