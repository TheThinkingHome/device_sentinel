# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: conftest.py, Version: 0.19.11 (2026-08-31)

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
import importlib.util
import os
import shutil
from pathlib import Path

import pytest
from homeassistant.helpers import storage as ha_storage
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


# ----------------------------------------------- the reference fleets

# The reference fleets are two real people's storage files and are
# deliberately not in this repository. Point DEVICE_SENTINEL_FLEET_DIR
# at a directory holding them to run the fleet cases; without it
# every fleet case skips, which is what happens in continuous
# integration and on anyone else's checkout. One place since 0.19.11,
# so no test can hardcode a path the others do not share.
FLEET_DIR = Path(
    os.environ.get("DEVICE_SENTINEL_FLEET_DIR", "/home/claude/fleets")
)
FLEET_ABSENT = "reference fleet file absent; set DEVICE_SENTINEL_FLEET_DIR"


def fleet_path(*parts: str) -> Path:
    """A path under the fleet directory."""
    return FLEET_DIR.joinpath(*parts)


def fleet_param(*parts: str, id: str, clocks: tuple[str, ...] | None = None):
    """A pytest param for one fleet file, skipping when it is absent.

    With `clocks`, the param carries both paths and skips unless both
    exist.
    """
    path = fleet_path(*parts)
    if clocks is None:
        return pytest.param(
            path,
            id=id,
            marks=pytest.mark.skipif(not path.exists(), reason=FLEET_ABSENT),
        )
    clocks_path = fleet_path(*clocks)
    return pytest.param(
        path,
        clocks_path,
        id=id,
        marks=pytest.mark.skipif(
            not (path.exists() and clocks_path.exists()), reason=FLEET_ABSENT
        ),
    )


# ------------------------------------------------------ the real disk


@pytest.fixture
def real_disk(hass):
    """Put the real Store load and write back for one test.

    The harness mocks storage in memory, so nothing a test does
    ordinarily reaches a file. A few claims are about the files
    themselves, the rotation and the crash window among them, and
    those need the disk. This borrows the two methods from a fresh,
    unpatched copy of Home Assistant's storage module for the
    duration of one test, so every read and write goes to the real
    `.storage` under the test config directory.

    Restored by hand rather than through monkeypatch, because
    monkeypatch tears down after the harness's own storage patch has
    already exited and would leave the mock on the class for the
    next test to trip over. The module is loaded as a member of its
    own package so its relative imports resolve.
    """
    spec = importlib.util.spec_from_file_location(
        "homeassistant.helpers.storage_fresh", ha_storage.__file__
    )
    fresh = importlib.util.module_from_spec(spec)
    fresh.__package__ = "homeassistant.helpers"
    spec.loader.exec_module(fresh)
    mocked_load = ha_storage.Store._async_load
    mocked_write = ha_storage.Store._async_write_data
    ha_storage.Store._async_load = fresh.Store._async_load
    ha_storage.Store._async_write_data = fresh.Store._async_write_data
    directory = hass.config.path(".storage")
    os.makedirs(directory, exist_ok=True)

    def _sweep() -> None:
        for name in os.listdir(directory):
            if name.startswith("device_sentinel"):
                os.remove(os.path.join(directory, name))

    _sweep()
    try:
        yield directory
    finally:
        ha_storage.Store._async_load = mocked_load
        ha_storage.Store._async_write_data = mocked_write
        _sweep()
