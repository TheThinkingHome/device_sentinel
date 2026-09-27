# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_probe_guard.py, Version: 0.23.10 (2026-09-26)

"""Extended Diagnostics records and never judges (0.23.10).

Found by the adversarial campaign of 26 September on 0.23.9. The probe
ran unguarded in the minute tick, ahead of the freeze judgment, and at
the start of the midnight fold. A studied library that threw stopped
the tick every minute it misbehaved, so nothing was judged, listed or
saved, and aborted the fold for every device in the house. The three
throws below are each a library object behaving oddly: a Lutron
session torn down mid-read, a Matter attribute table with a key that is
not text, and a Z-Wave status from a newer library. With Extended
Diagnostics off the same objects are harmless, which is the control.

Also from the campaign: the lines a tick holds for the next one were
lost at every stop, and a probe file that could not be written raised
an anonymous traceback every minute.
"""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace

import pytest
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import diagnostics
from custom_components.device_sentinel.const import (
    CONF_STUDY_HARDWARE,
    DATA_CLEAN_STOP,
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_TODAY_MAX,
    REPORT_DIR,
    REPORT_STACK_PROBE,
    STORAGE_KEY,
    STUDIABLE,
)

from .helpers import register_device, setup_coordinator, setup_entry
from .test_stack_probes_hubs import _Connectivity, _device, _hue

LAMP = "3a1b2c3d-0000-4000-8000-000000000001"


class _TornSession:
    """A Lutron bridge whose session goes while it is read."""

    @property
    def _leap(self):
        raise RuntimeError("session torn down mid-read")

    def is_connected(self):
        return True


class _NewerStatus:
    """A Z-Wave status enum whose name a newer library computes."""

    @property
    def name(self):
        raise RuntimeError("status from a newer library")


def _entry(hass, domain, runtime):
    entry = MockConfigEntry(domain=domain, title=domain)
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = runtime
    return entry


def _lutron(hass):
    _entry(hass, "lutron_caseta", SimpleNamespace(bridge=_TornSession()))
    return "lutron_caseta"


def _matter(hass):
    node = SimpleNamespace(
        node_id=5, available=True,
        node_data=SimpleNamespace(attributes={7: 1, "0/53/1": 2}),
    )
    client = SimpleNamespace(get_nodes=lambda: [node], connection=SimpleNamespace(connected=True))
    _entry(hass, "matter", SimpleNamespace(adapter=SimpleNamespace(matter_client=client)))
    return "matter"


def _zwave(hass):
    node = SimpleNamespace(node_id=4, status=_NewerStatus(), is_controller_node=False)
    controller = SimpleNamespace(home_id=1, nodes={4: node}, status=0)
    client = SimpleNamespace(driver=SimpleNamespace(controller=controller), connected=True)
    _entry(hass, "zwave_js", SimpleNamespace(client=client))
    return "zwave_js"


THROWERS = pytest.mark.parametrize("make", [_lutron, _matter, _zwave], ids=["lutron", "matter", "zwave"])


@THROWERS
async def test_a_throwing_reader_leaves_the_tick_judging(hass: HomeAssistant, make):
    domain = make(hass)
    register_device(hass, "plain")
    coord = await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[domain]]})
    judged = []
    original = coord._judge_all_devices

    def _counted(*args, **kwargs):
        judged.append(1)
        return original(*args, **kwargs)

    coord._judge_all_devices = _counted
    await coord._on_render_tick(None)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert judged, "the freeze judgment did not run"


@THROWERS
async def test_a_throwing_reader_leaves_the_fold_whole(hass: HomeAssistant, make):
    domain = make(hass)
    device, _ = register_device(hass, "plain")
    coord = await setup_coordinator(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[domain]]})
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_TODAY_MAX] = 123.0
    before = list(record[DEV_DAILY_MAX])
    await coord._on_midnight(None)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert record[DEV_DAILY_MAX] == [*before, 123.0]


@THROWERS
async def test_control_nothing_studied(hass: HomeAssistant, make):
    """Guard: the same objects with Extended Diagnostics off."""
    make(hass)
    device, _ = register_device(hass, "plain")
    coord = await setup_coordinator(hass)
    await coord._on_render_tick(None)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_TODAY_MAX] = 123.0
    await coord._on_midnight(None)
    assert record[DEV_DAILY_MAX][-1] == 123.0


async def test_one_stack_throwing_leaves_the_others_recording(hass: HomeAssistant, caplog):
    """Lutron throws; Hue's lines are written as usual, and the
    warning names Lutron once however many ticks it repeats."""
    caplog.set_level(logging.DEBUG)
    _lutron(hass)
    hue = _hue(hass, {LAMP: _Connectivity.CONNECTED})
    _device(hass, hue, "hue", LAMP, "Hall lamp")
    coord = await setup_coordinator(
        hass, {CONF_STUDY_HARDWARE: [STUDIABLE["lutron_caseta"], STUDIABLE["hue"]]}
    )
    for minute in range(3):
        coord.probe_tick(1000.0 + 60 * minute)
    # The file is written off the event loop, as a background task; a
    # write left running would land in the next test's folder.
    await hass.async_block_till_done(wait_background_tasks=True)
    assert any("Hall lamp" in line for line in coord._probe_recent)
    assert any("| hue | bridge |" in line for line in coord._probe_recent)
    warned = [
        rec for rec in caplog.records
        if rec.levelno == logging.WARNING and "Extended Diagnostics could not read" in rec.getMessage()
    ]
    assert len(warned) == 1, [rec.getMessage() for rec in warned]
    assert "Lutron" in warned[0].getMessage()


def _probe_path(hass):
    return os.path.join(hass.config.path(REPORT_DIR), REPORT_STACK_PROBE)


async def test_the_lines_held_at_a_stop_are_written(hass: HomeAssistant):
    hue = _hue(hass, {LAMP: _Connectivity.CONNECTED})
    _device(hass, hue, "hue", LAMP, "Hall lamp")
    entry = await setup_entry(hass, {CONF_STUDY_HARDWARE: [STUDIABLE["hue"]]})
    coord = entry.runtime_data
    coord.probe_tick(1000.0)
    assert any("Hall lamp" in line for line in coord._probe_pending)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    with open(_probe_path(hass), encoding="utf-8") as handle:
        assert "Hall lamp" in handle.read()


async def test_a_file_that_cannot_be_written_is_said_once(hass: HomeAssistant, caplog, monkeypatch):
    """A folder where the file should be: the tick carries on, and one
    Device Sentinel warning names the file, where before Home
    Assistant logged an anonymous traceback every minute. The file has
    a name of its own here, so no other test's write can meet the
    folder."""
    from custom_components.device_sentinel import report_maintainer

    monkeypatch.setattr(report_maintainer, "REPORT_STACK_PROBE", "unwritable_probe.md")
    caplog.set_level(logging.DEBUG)
    hue = _hue(hass, {LAMP: _Connectivity.CONNECTED})
    _device(hass, hue, "hue", LAMP, "Hall lamp")
    entry = await setup_entry(hass, {CONF_STUDY_HARDWARE: [STUDIABLE["hue"]]})
    coord = entry.runtime_data
    path = os.path.join(hass.config.path(REPORT_DIR), "unwritable_probe.md")
    os.makedirs(path, exist_ok=True)
    try:
        for minute in range(4):
            coord.probe_tick(1000.0 + 60 * minute)
            coord._probe_queue({key: "x" for key in (
                "when", "stack", "node", "device_id", "was", "now", "sentinel", "agrees", "detail",
            )} | {"when": 1000.0 + 60 * minute})
            await hass.async_block_till_done(wait_background_tasks=True)
        await coord.async_probe_stop()
        await hass.async_block_till_done(wait_background_tasks=True)
        warned = [
            rec for rec in caplog.records
            if rec.levelno == logging.WARNING and "could not write" in rec.getMessage()
        ]
        assert len(warned) == 1, [rec.getMessage() for rec in warned]
        assert "unwritable_probe.md" in warned[0].getMessage()
        assert not [
            rec for rec in caplog.records
            if rec.levelno >= logging.ERROR and "never retrieved" in rec.getMessage()
        ]
    finally:
        os.rmdir(path)


# ------------------------------------------- found testing 0.23.10 itself

# Three more, from simulating 0.23.10 on 26 September before it shipped:
# Home Assistant does not unload integrations when it stops, so the
# write at the unload never ran at a restart; that write sat ahead of
# the unload's save and a throw from it skipped the save and the
# clean-stop marker; and the diagnostics download failed outright when
# a studied library threw.


async def test_a_home_assistant_restart_writes_the_held_lines(hass: HomeAssistant):
    hue = _hue(hass, {LAMP: _Connectivity.CONNECTED})
    _device(hass, hue, "hue", LAMP, "Hall lamp")
    entry = await setup_entry(hass, {CONF_STUDY_HARDWARE: [STUDIABLE["hue"]]})
    coord = entry.runtime_data
    coord.probe_tick(1000.0)
    assert any("Hall lamp" in line for line in coord._probe_pending)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done(wait_background_tasks=True)
    with open(_probe_path(hass), encoding="utf-8") as handle:
        assert "Hall lamp" in handle.read()
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


_UNENCODABLE = UnicodeEncodeError("utf-8", "\udc80", 0, 1, "surrogates not allowed")


async def test_a_throwing_write_at_the_unload_leaves_the_save(hass: HomeAssistant, hass_storage):
    hue = _hue(hass, {LAMP: _Connectivity.CONNECTED})
    _device(hass, hue, "hue", LAMP, "Hall lamp")
    entry = await setup_entry(hass, {CONF_STUDY_HARDWARE: [STUDIABLE["hue"]]})
    coord = entry.runtime_data
    coord.probe_tick(1000.0)
    hass_storage.pop(STORAGE_KEY, None)
    with patch.object(type(coord), "_probe_append", side_effect=_UNENCODABLE):
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert hass_storage[STORAGE_KEY]["data"].get(DATA_CLEAN_STOP) is True


async def test_a_throwing_executor_at_the_stop_event_leaves_the_save(hass: HomeAssistant, hass_storage):
    """The executor itself refusing the job, as it can while Home
    Assistant goes down."""
    hue = _hue(hass, {LAMP: _Connectivity.CONNECTED})
    _device(hass, hue, "hue", LAMP, "Hall lamp")
    entry = await setup_entry(hass, {CONF_STUDY_HARDWARE: [STUDIABLE["hue"]]})
    coord = entry.runtime_data
    coord.probe_tick(1000.0)
    hass_storage.pop(STORAGE_KEY, None)
    real = hass.async_add_executor_job

    def _refuse(target, *args):
        if getattr(target, "__name__", "") == "_probe_write_lines":
            raise RuntimeError("cannot schedule new futures after shutdown")
        return real(target, *args)

    with patch.object(hass, "async_add_executor_job", side_effect=_refuse):
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert hass_storage[STORAGE_KEY]["data"].get(DATA_CLEAN_STOP) is True
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_text_that_cannot_be_encoded_is_said_once(hass: HomeAssistant, caplog):
    """A line that cannot be encoded raises UnicodeEncodeError, which
    is not an OSError and escaped the file's catch into an anonymous
    traceback each minute. Raised at the write here: Home Assistant's
    registry refuses such text in a name, but a library's own strings
    reach the line as they are."""
    caplog.set_level(logging.DEBUG)
    hue = _hue(hass, {LAMP: _Connectivity.CONNECTED})
    _device(hass, hue, "hue", LAMP, "Hall lamp")
    entry = await setup_entry(hass, {CONF_STUDY_HARDWARE: [STUDIABLE["hue"]]})
    coord = entry.runtime_data
    with patch.object(type(coord), "_probe_append", side_effect=_UNENCODABLE):
        for minute in range(3):
            coord.probe_tick(1000.0 + 60 * minute)
            coord._probe_queue({key: "x" for key in (
                "when", "stack", "node", "device_id", "was", "now", "sentinel", "agrees", "detail",
            )} | {"when": 1000.0 + 60 * minute})
            await hass.async_block_till_done(wait_background_tasks=True)
    warned = [rec for rec in caplog.records if rec.levelno == logging.WARNING and "could not write" in rec.getMessage()]
    assert len(warned) == 1, [rec.getMessage() for rec in warned]
    assert not [rec for rec in caplog.records if rec.levelno >= logging.ERROR]


@THROWERS
async def test_the_download_arrives_beside_a_throwing_library(hass: HomeAssistant, make):
    domain = make(hass)
    register_device(hass, "plain")
    entry = await setup_entry(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[domain]]})
    out = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    data = out.get("data", out)
    assert data["devices"] is not None
    studied = {"lutron_caseta": "lutron", "matter": "matter", "zwave_js": "zwave"}[domain]
    section = data["classification"][studied]
    assert isinstance(section, dict)
    if domain != "lutron_caseta":
        assert "unreadable" in section, section
