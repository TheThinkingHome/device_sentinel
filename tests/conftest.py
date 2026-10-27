# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: conftest.py, Version: 0.27.10 (2026-10-27)

"""Shared test fixtures: clean report folders, the fleets, and a failure
on any deprecation Home Assistant reports (rules REL-03, CODE-16).

The harness keeps one config directory inside the installed package, so
a file one test writes is still there for the next test and the next
run. Each test starts from empty report folders, so an old brief cannot
pass or fail a later test.
"""

import importlib.util
import json
import logging
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
    """Give each test empty report folders, before and after.

    The www folder too, though nothing writes there now, so a test that
    plants an old installation's files there leaves nothing behind.
    """
    shutil.rmtree(REPORT_DIRECTORY, ignore_errors=True)
    shutil.rmtree(WWW_DIRECTORY, ignore_errors=True)
    yield
    shutil.rmtree(REPORT_DIRECTORY, ignore_errors=True)
    shutil.rmtree(WWW_DIRECTORY, ignore_errors=True)


# ------------------------------------- the frontend counted as loaded

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_frontend: set up Home Assistant's real frontend and panel_custom"
    )


@pytest.fixture(autouse=True)
def frontend_loaded(request):
    """Count the frontend and panel_custom as set up, as every Home
    Assistant has them, unless a test asks for the real ones.

    Device Sentinel names both as dependencies (rule DASH-01). Setting up
    the real frontend for each of the suite's thousands of setups makes
    the suite 75 percent slower, and the dashboard's registration needs
    only the panel table, which this leaves as Home Assistant keeps it.
    A test marked `real_frontend` sets both up for real.
    """
    if request.node.get_closest_marker("real_frontend") is not None:
        yield
        return
    hass = request.getfixturevalue("hass") if "hass" in request.fixturenames else None
    if hass is not None:
        hass.config.components.update({"frontend", "panel_custom"})
    yield


# ------------------------------------------ entries only mocked loaded

@pytest.fixture(autouse=True)
def unmark_mocked_entries(request):
    """Leave no entry marked loaded for an integration never set up.

    A fleet case marks a real domain's entry, mqtt among them, as loaded
    so the house looks up before anything falls. The harness unloads
    every loaded entry after the test, and Home Assistant 2026.5 and
    later log an error for each one whose integration was never set up.
    Marking those entries not loaded first leaves the harness nothing to
    unload. An integration that really loaded, this one included, is
    untouched, so its own unload is still exercised.
    """
    if "hass" not in request.fixturenames:
        yield
        return
    hass = request.getfixturevalue("hass")
    yield
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
    )

    for entry in hass.config_entries.async_entries():
        if (
            isinstance(entry, MockConfigEntry)
            and entry.state is ConfigEntryState.LOADED
            and entry.domain not in hass.config.components
        ):
            entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


# --------------------------------------------- the deprecation guard

# Home Assistant logs this when a custom integration uses something it
# has deprecated. Any such line fails the test that caused it, because
# a deprecation nobody sees reaches users first (rule REL-03).
DEPRECATION_PREFIX = "Detected that custom integration 'device_sentinel'"

# Deprecations already known and scheduled, each matched by every
# fragment it lists so a second use of the same API elsewhere is still
# caught. Remove an entry in the release that fixes it.
KNOWN_DEPRECATIONS: tuple[tuple[str, ...], ...] = ()


def deprecation_findings(
    messages: list[str],
    known: tuple[tuple[str, ...], ...] = KNOWN_DEPRECATIONS,
) -> list[str]:
    """Return the deprecation warnings about this integration not yet known."""
    return [
        message for message in messages
        if message.startswith(DEPRECATION_PREFIX)
        and not any(
            all(fragment in message for fragment in fragments)
            for fragments in known
        )
    ]


class FrameLog(logging.Handler):
    """Collect what Home Assistant's frame helper logs during one test.

    A handler of its own rather than `caplog`, which tests clear and
    re-level for their own purposes and which would then hide a
    finding.
    """

    LOGGER = "homeassistant.helpers.frame"

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def __enter__(self) -> "FrameLog":
        logging.getLogger(self.LOGGER).addHandler(self)
        return self

    def __exit__(self, *exc) -> None:
        logging.getLogger(self.LOGGER).removeHandler(self)


@pytest.fixture(autouse=True)
def no_new_deprecations():
    """Fail any test during which this integration used a deprecated API."""
    with FrameLog() as frame_log:
        yield frame_log
    found = deprecation_findings(frame_log.messages)
    if found:
        pytest.fail(
            "Home Assistant reported a deprecated use:\n" + "\n".join(found),
            pytrace=False,
        )


@pytest.fixture
def read_brief():
    """Return a reader for the brief that was written, the one file
    daily_brief.html in the reports folder."""

    def _read(hass):
        # The file on disk is the rendered page; the one-file naming is
        # still asserted on it, and the composed text is returned,
        # because it is the message field the page renders from, so its
        # prose is the prose these tests examine.
        written = os.path.join(
            hass.config.path("device_sentinel"), "daily_brief.html"
        )
        assert os.path.isfile(written), "no daily brief was written"
        from custom_components.device_sentinel.const import DOMAIN

        entry = hass.config_entries.async_entries(DOMAIN)[0]
        return entry.runtime_data._last_brief_text

    return _read


# ----------------------------------------------- the reference fleets

# The fleets are real houses' storage, anonymized and committed under
# tests/fleets/ by tools/anonymise_fleet.py: reference/, second/ and
# fourth/, a folder for each tester after them, and under upgrade/ the
# first two houses as they stood before the history file. They are the
# set the Test Baseline counts, and the set continuous integration runs.
# Point DEVICE_SENTINEL_FLEET_DIR at another directory laid out the same
# way, such as the private archive's real files, to run the fleet cases
# on it instead, or at an empty one to run without fleets. One place, so
# no test can hardcode a path the others do not share (rule CODE-16).
FLEET_DIR = Path(
    os.environ.get(
        "DEVICE_SENTINEL_FLEET_DIR", str(Path(__file__).parent / "fleets")
    )
)
FLEET_ABSENT = "fleet file absent; see tests/fleets or DEVICE_SENTINEL_FLEET_DIR"


def fleet_path(*parts: str) -> Path:
    """A path under the fleet directory."""
    return FLEET_DIR.joinpath(*parts)


# A house with a history file keeps every day older than its main file's
# thirty there, beside it, under the storage file's spelling (rule STOR-03).
HISTORY_FOR = {
    "device_sentinel.storage": "device_sentinel.history",
    "device_sentinel_storage.json": "device_sentinel_history.json",
}


def fleet_document(path: Path) -> dict:
    """A fleet's storage document, with its history joined back in.

    The committed houses keep thirty days in the main file and the rest
    in the history file. A test that reads a house reads all of it: the
    older part goes back in front of each series and table, as the load
    does, and the two keys that tie the main file to a history file are
    dropped, so what a test seats is one whole file, as a house without
    a history file wrote it and as the upgrade fixtures under `upgrade/`
    still are. A house with no history file is returned as it stands.
    """
    from custom_components.device_sentinel import history_file
    from custom_components.device_sentinel.const import (
        DATA_HISTORY_GENERATION,
        DATA_HISTORY_LINE,
    )

    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    history = path.parent / HISTORY_FOR.get(path.name, "")
    if path.name in HISTORY_FOR and history.exists():
        with open(history, encoding="utf-8") as handle:
            payload = json.load(handle)["data"]
        data = loaded.get("data", loaded)
        history_file.join(data, payload)
        data.pop(DATA_HISTORY_GENERATION, None)
        data.pop(DATA_HISTORY_LINE, None)
    return loaded


def fleet_data(path: Path) -> dict:
    """The data part of `fleet_document`."""
    loaded = fleet_document(path)
    return loaded.get("data", loaded)


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
