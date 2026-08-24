# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_review_0_17_3.py, Version: 0.17.3 (2026-08-24)

"""The code review release: what an outside standard found (0.17.3).

Four fixes from the review against `Research__Code_Review_Guide.md`.
Three are small and one reaches a person: a storage file Home
Assistant cannot parse used to leave a traceback and a config entry
whose error named no cause. It now states the fault, says nothing was
changed, and stops permanently rather than retrying, because a corrupt
file does not repair itself between attempts (ruling #327).
"""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import trim
from custom_components.device_sentinel.const import (
    DOMAIN,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)

from tests.helpers import register_device, setup_entry


# ------------------------------------------- the unreadable file (#327)


async def _entry_with_failing_load(hass: HomeAssistant, error: Exception):
    """Set up the integration with our own store raising on load.

    Only this integration's key fails: patching every Store would
    break Home Assistant's own registries and prove nothing about
    this guard.
    """
    from homeassistant.helpers.storage import Store

    real_load = Store.async_load

    async def _selective(self, *args, **kwargs):
        if self.key == STORAGE_KEY:
            raise error
        return await real_load(self, *args, **kwargs)

    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={}, options={}
    )
    entry.add_to_hass(hass)
    with patch.object(Store, "async_load", _selective):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_an_unreadable_storage_file_states_the_fault(
    hass: HomeAssistant, caplog
) -> None:
    """A file that will not parse stops setup with a sentence.

    Before this, the exception escaped `async_setup_entry` and Home
    Assistant showed a traceback with no cause a person could act on.
    """
    entry = await _entry_with_failing_load(
        hass, HomeAssistantError("expecting value: line 1 column 1")
    )
    assert entry.state is ConfigEntryState.SETUP_ERROR
    # The log names the file and says nothing was changed.
    assert STORAGE_KEY in caplog.text
    assert "will not start" in caplog.text
    assert "Nothing has been changed" in caplog.text


async def test_an_unreadable_storage_file_does_not_retry(
    hass: HomeAssistant
) -> None:
    """ConfigEntryError rather than ConfigEntryNotReady.

    A corrupt file does not become readable on the next attempt, so a
    retry loop would only repeat the same failure every few minutes
    and bury the one line that explains it.
    """
    entry = await _entry_with_failing_load(
        hass, ValueError("Expecting ',' delimiter")
    )
    assert entry.state is ConfigEntryState.SETUP_ERROR
    # SETUP_RETRY is what ConfigEntryNotReady would have produced.
    assert entry.state is not ConfigEntryState.SETUP_RETRY


async def test_an_unreadable_clocks_file_is_survivable(
    hass: HomeAssistant, hass_storage, caplog
) -> None:
    """The small companion is not the record.

    Losing it costs one interval of live counters, so the start
    continues on the clocks held in the main file and says so, rather
    than refusing to run (ruling #327).
    """
    real_load = None

    async def _selective(self, *args, **kwargs):
        if self.key == STORAGE_CLOCKS_KEY:
            raise HomeAssistantError("clocks file is not JSON")
        return await real_load(self, *args, **kwargs)

    from homeassistant.helpers.storage import Store

    real_load = Store.async_load
    with patch.object(Store, "async_load", _selective):
        entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert STORAGE_CLOCKS_KEY in caplog.text
    assert "Nothing learned is lost" in caplog.text


async def test_a_missing_storage_file_is_still_a_fresh_install(
    hass: HomeAssistant
) -> None:
    """The guard catches faults, not absence. A first run has no file
    at all, and that path is unchanged."""
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.data["devices"] == {}


# ------------------------------------------ the trim log line (#329)


def test_the_trim_log_says_what_was_erased(caplog) -> None:
    """The counts were accepted and dropped on the floor.

    A person reading this line after a trim that matched a device
    with no record needs to see the zero rather than infer it.
    """
    import logging

    caplog.set_level(logging.INFO)
    trim.log_result(
        "2026-08-24-1200", {"devices": 2, "episodes": 7}, ["A", "B"]
    )
    assert "Erased: devices 2, episodes 7" in caplog.text


def test_the_trim_log_says_so_when_nothing_was_recorded(caplog) -> None:
    """An excluded device's record went at the fold, so the trim
    finds nothing to erase and the line has to say that."""
    import logging

    caplog.set_level(logging.INFO)
    trim.log_result("2026-08-24-1200", {"devices": 0}, ["Ghost"])
    assert "Erased: nothing recorded" in caplog.text


# ------------------------------------- the www folder, one trip (#326)


async def test_the_www_check_never_touches_the_loop(
    hass: HomeAssistant, monkeypatch
) -> None:
    """The look and the make are one executor job.

    The stat was the only filesystem call the integration made on the
    event loop, which is the one rule the review guide puts above
    every other.
    """
    import importlib

    module = importlib.import_module("custom_components.device_sentinel")

    seen: list[str] = []
    real_isdir = module.os.path.isdir

    def _watched(path):
        seen.append("isdir")
        return real_isdir(path)

    monkeypatch.setattr(module.os.path, "isdir", _watched)

    jobs: list[str] = []
    real_executor = hass.async_add_executor_job

    def _counted(target, *args):
        jobs.append(getattr(target, "__name__", str(target)))
        return real_executor(target, *args)

    monkeypatch.setattr(hass, "async_add_executor_job", _counted)
    await module._async_serve_www_folder(hass)

    # One trip, and the stat happened inside it rather than beside it.
    assert jobs.count("_look_then_make") == 1
    assert seen == ["isdir"]


# --------------------------------------------- explicit pairing (#328)


async def test_the_rail_verdict_survives_uneven_series(
    hass: HomeAssistant
) -> None:
    """Non-strict on purpose: a stored file whose count and rail
    series differ by a day reads as no rail rather than raising
    inside a verdict."""
    from custom_components.device_sentinel.const import (
        DEV_SIGNAL_DAILY_COUNT,
        DEV_SIGNAL_DAILY_RAIL,
    )

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    device, _ = register_device(hass, "z328", "Uneven Series")
    coord._rebuild_registry_view()
    record = coord.data["devices"][device.id]
    record[DEV_SIGNAL_DAILY_COUNT] = [0, 0, 0, 0, 0]
    record[DEV_SIGNAL_DAILY_RAIL] = [9, 7]

    # Two rail days against five silent ones is not three railed days.
    assert coord.signal_railed(record) is False


def test_the_brief_pairing_is_strict() -> None:
    """The brief's flood pairing is built in this method, one entry
    per device, so a length mismatch is a bug here rather than a
    shape a stored file can produce. Strict says so."""
    import inspect

    from custom_components.device_sentinel import report_brief

    source = inspect.getsource(report_brief)
    assert "zip(told, owners, strict=True)" in source


@pytest.mark.parametrize(
    "module_name",
    ["detect_signal", "interventions", "diagnostics", "report_brief"],
)
def test_every_pairing_states_its_intent(module_name: str) -> None:
    """No bare zip anywhere in the component (ruling #328).

    Ruff's B905 enforces this on the build; the test states why it
    matters, which a lint rule cannot.
    """
    import importlib
    import inspect

    module = importlib.import_module(
        f"custom_components.device_sentinel.{module_name}"
    )
    source = inspect.getsource(module)
    for index, line in enumerate(source.splitlines()):
        if "zip(" not in line:
            continue
        window = "\n".join(source.splitlines()[index : index + 6])
        assert "strict=" in window, f"{module_name}:{index + 1}"
