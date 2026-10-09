# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_answers_store.py, Version: 0.25.1 (2026-10-08)

"""The one file of pencil answers (0.25.1).

What powers a device and what a device is live in device_sentinel.answers,
with a last-good copy taken before each save. The first start of 0.25.1
moves the power answers out of device_sentinel.power, reads the new file
back, and only then deletes the old file and its copy (James, 8 October
2026). Answers for devices Device Sentinel does not watch are kept and
listed in the diagnostics in one place.

The harness keeps storage in memory, so the files on disk (last-good
copies, and the old power file's copy) are written by hand here, as
test_backup_integrity.py does.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import storage as ha_storage
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.answers_store import ANSWERS_STORE_KEY, LEGACY_POWER_KEY
from custom_components.device_sentinel.const import CONF_EXCLUDED_INTEGRATIONS
from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics

from .helpers import register_device, setup_coordinator, setup_entry

# Home Assistant's own storage functions, taken before the harness puts
# its in-memory stand-ins in their place, for the tests on real files.
REAL_LOAD = Store._async_load
REAL_WRITE = Store._async_write_data
REAL_REMOVE = Store.async_remove

SET = "2026-10-05T12:00:00+00:00"
MAKER, MODEL, MODEL_ID = "Unlisted Maker", "Unlisted Sensor", "UL-SENSOR-1"
KEY = json.dumps([MAKER, MODEL, MODEL_ID])


def _disk(hass, key, suffix=""):
    directory = hass.config.path(".storage")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, key + (f".{suffix}" if suffix else ""))


@pytest.fixture
def _no_files(hass):
    def sweep():
        for key in (ANSWERS_STORE_KEY, LEGACY_POWER_KEY):
            for suffix in ("", "last-good"):
                if os.path.exists(_disk(hass, key, suffix)):
                    os.remove(_disk(hass, key, suffix))
    sweep()
    yield
    sweep()


def _write(path, document):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _doc(key, data):
    return {"version": 1, "minor_version": 1, "key": key, "data": data}


def _power(battery="AA", quantity=4, setter="gone"):
    return {"kind": "battery", "type": battery, "quantity": quantity, "set": SET, "device_id": setter}


def _type(words="Plug", setter="gone"):
    return {"type": words, "set": SET, "device_id": setter}


def _model_device(hass, uid="a1", name="Button Doorbell"):
    device, _ = register_device(hass, uid, name)
    dr.async_get(hass).async_update_device(device.id, manufacturer=MAKER, model=MODEL, model_id=MODEL_ID)
    return device


def _legacy_0_25_0(device_id):
    """A power file as 0.25.0 wrote it: the model entry, and its copy for 0.24.7."""
    return _doc(LEGACY_POWER_KEY, {
        "models": {KEY: _power("AAA", 2, device_id)},
        "devices": {device_id: {"kind": "battery", "type": "AAA", "quantity": 2, "set": SET, "model": KEY}},
    })


# ------------------------------------------------------------------ the move


async def test_the_first_start_moves_the_power_file_and_deletes_it(hass: HomeAssistant, hass_storage, caplog, _no_files):
    device = _model_device(hass)
    hass_storage[LEGACY_POWER_KEY] = _legacy_0_25_0(device.id)
    _write(_disk(hass, LEGACY_POWER_KEY, "last-good"), _legacy_0_25_0(device.id))
    coord = await setup_coordinator(hass)
    assert coord.power_view(device.id)["words"] == "2× AAA"
    data = hass_storage[ANSWERS_STORE_KEY]["data"]
    assert data == {"power": {"models": {KEY: _power("AAA", 2, device.id)}, "devices": {}},
                    "types": {"models": {}, "devices": {}}}, "the copy for 0.24.7 came along"
    assert LEGACY_POWER_KEY not in hass_storage, "the power file outlived the move"
    assert not os.path.exists(_disk(hass, LEGACY_POWER_KEY, "last-good")), "its last-good copy outlived the move"
    assert "moved 1 power answer from device_sentinel.power into device_sentinel.answers" in caplog.text


async def test_the_move_reads_the_old_copy_when_the_old_file_is_unreadable(hass: HomeAssistant, hass_storage, _no_files):
    device = _model_device(hass)
    _write(_disk(hass, LEGACY_POWER_KEY, "last-good"), _legacy_0_25_0(device.id))
    coord = await setup_coordinator(hass)
    assert coord.power_view(device.id)["words"] == "2× AAA"
    assert KEY in hass_storage[ANSWERS_STORE_KEY]["data"]["power"]["models"]
    assert not os.path.exists(_disk(hass, LEGACY_POWER_KEY, "last-good"))


async def test_a_failed_save_keeps_the_power_file_and_the_next_start_moves_it(
    hass: HomeAssistant, hass_storage, monkeypatch, caplog, _no_files
):
    """Home Assistant logs a save it could not make and raises nothing, so
    the move reads the file back before it deletes anything."""
    device = _model_device(hass)
    hass_storage[LEGACY_POWER_KEY] = _legacy_0_25_0(device.id)
    original = Store.async_save

    async def refused(store, data):
        if store.key != ANSWERS_STORE_KEY:
            await original(store, data)

    monkeypatch.setattr(Store, "async_save", refused)
    entry = await setup_entry(hass)
    assert entry.runtime_data.power_view(device.id)["words"] == "2× AAA", "the answers are shown all the same"
    assert ANSWERS_STORE_KEY not in hass_storage
    assert LEGACY_POWER_KEY in hass_storage, "the power file was deleted with nothing written in its place"
    assert "could not confirm device_sentinel.answers was written" in caplog.text
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    monkeypatch.setattr(Store, "async_save", original)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.power_view(device.id)["words"] == "2× AAA"
    assert KEY in hass_storage[ANSWERS_STORE_KEY]["data"]["power"]["models"]
    assert LEGACY_POWER_KEY not in hass_storage


async def test_the_move_happens_once_and_a_leftover_old_file_is_ignored_and_deleted(
    hass: HomeAssistant, hass_storage, _no_files
):
    """A stop between the save and the delete leaves both files. The answers
    file is the one that counts: the old one is never read again, only
    deleted."""
    device = _model_device(hass)
    hass_storage[ANSWERS_STORE_KEY] = _doc(ANSWERS_STORE_KEY, {
        "power": {"models": {KEY: _power("CR2032", 1, device.id)}, "devices": {}},
        "types": {"models": {}, "devices": {}}})
    hass_storage[LEGACY_POWER_KEY] = _legacy_0_25_0(device.id)
    _write(_disk(hass, LEGACY_POWER_KEY, "last-good"), _legacy_0_25_0(device.id))
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    assert coord.power_view(device.id)["words"] == "CR2032", "the leftover old file was read"
    assert LEGACY_POWER_KEY not in hass_storage
    assert not os.path.exists(_disk(hass, LEGACY_POWER_KEY, "last-good"))
    calls = []
    original = type(coord)._remove_legacy_power

    async def counting(self):
        calls.append(1)
        await original(self)

    type(coord)._remove_legacy_power = counting
    try:
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    finally:
        type(coord)._remove_legacy_power = original
    assert calls == [], "a start with nothing left to move deleted again"
    assert entry.runtime_data.power_view(device.id)["words"] == "CR2032"


async def test_a_fresh_install_writes_nothing_until_a_pencil_is_used(hass: HomeAssistant, hass_storage, _no_files):
    device = _model_device(hass)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    assert coord.power_view(device.id)["words"] == "Not known"
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert ANSWERS_STORE_KEY not in hass_storage and LEGACY_POWER_KEY not in hass_storage
    assert not os.path.exists(_disk(hass, ANSWERS_STORE_KEY, "last-good"))


async def test_power_and_type_answers_share_the_file_and_survive_a_restart(hass: HomeAssistant, hass_storage, _no_files):
    device = _model_device(hass)
    entry = await setup_entry(hass)
    entry.runtime_data.page_set_power(device.id, "AAA", 2)
    entry.runtime_data.page_set_type(device.id, "Button")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    data = hass_storage[ANSWERS_STORE_KEY]["data"]
    assert data["power"]["models"][KEY]["type"] == "AAA"
    assert data["types"]["models"][KEY]["type"] == "Button"
    assert entry.runtime_data.power_view(device.id)["words"] == "2× AAA"
    assert entry.runtime_data.type_words(device.id) == "Button"


# -------------------------------------------------------------- last-good


async def test_a_save_keeps_the_previous_file_as_last_good(hass: HomeAssistant, hass_storage, _no_files):
    """Before each save the file about to be replaced becomes last-good
    (ruling #370's rule)."""
    device = _model_device(hass)
    coord = await setup_coordinator(hass)
    _write(_disk(hass, ANSWERS_STORE_KEY), _doc(ANSWERS_STORE_KEY, {
        "power": {"models": {KEY: _power("CR2032", 1, device.id)}, "devices": {}},
        "types": {"models": {KEY: _type("Button", device.id)}, "devices": {}}}))
    coord._answers_rotation_armed = True
    coord.page_set_power(device.id, "AAA", 2)
    await coord.async_flush_answers()
    kept = _read(_disk(hass, ANSWERS_STORE_KEY, "last-good"))["data"]
    assert kept["power"]["models"][KEY]["type"] == "CR2032"
    assert kept["types"]["models"][KEY]["type"] == "Button"


async def test_an_unreadable_file_is_restored_from_last_good(hass: HomeAssistant, hass_storage, caplog, _no_files):
    device = _model_device(hass)
    _write(_disk(hass, ANSWERS_STORE_KEY, "last-good"), _doc(ANSWERS_STORE_KEY, {
        "power": {"models": {KEY: _power("CR2450", 1, device.id)}, "devices": {}},
        "types": {"models": {KEY: _type("Button", device.id)}, "devices": {}}}))
    coord = await setup_coordinator(hass)
    assert coord.power_view(device.id)["words"] == "CR2450"
    assert coord.type_words(device.id) == "Button"
    assert "restored the answers you set on device pages" in caplog.text
    assert coord._answers_rotation_armed is False


async def test_a_restored_load_never_rotates_over_the_copy(hass: HomeAssistant, hass_storage, _no_files):
    """The first save after a restore writes without rotating, so the
    damaged file on disk can never become last-good; the save after it
    rotates as usual."""
    device = _model_device(hass)
    good = _doc(ANSWERS_STORE_KEY, {"power": {"models": {KEY: _power("CR2450", 1, device.id)}, "devices": {}},
                                    "types": {"models": {}, "devices": {}}})
    _write(_disk(hass, ANSWERS_STORE_KEY, "last-good"), good)
    coord = await setup_coordinator(hass)
    with open(_disk(hass, ANSWERS_STORE_KEY), "w", encoding="utf-8") as handle:
        handle.write("{ damaged")
    coord.page_set_power(device.id, "AAA", 2)
    await coord.async_flush_answers()
    assert _read(_disk(hass, ANSWERS_STORE_KEY, "last-good"))["data"]["power"]["models"][KEY]["type"] == "CR2450"
    _write(_disk(hass, ANSWERS_STORE_KEY), hass_storage[ANSWERS_STORE_KEY])
    coord.page_set_power(device.id, "AA", 4)
    await coord.async_flush_answers()
    assert _read(_disk(hass, ANSWERS_STORE_KEY, "last-good"))["data"]["power"]["models"][KEY]["type"] == "AAA"


async def test_a_damaged_answer_is_left_out_and_the_rest_kept(hass: HomeAssistant, hass_storage, caplog, _no_files):
    device = _model_device(hass)
    lonely, _ = register_device(hass, "n1", "No Maker")
    hass_storage[ANSWERS_STORE_KEY] = _doc(ANSWERS_STORE_KEY, {
        "power": {"models": {KEY: _power("AA", 4, device.id), "bad": {"kind": "battery", "type": 3}},
                  "devices": {}},
        "types": {"models": {"not json": {"type": 3}},
                  "devices": {lonely.id: {"type": "Zigbee router", "set": None}}}})
    coord = await setup_coordinator(hass)
    assert coord.power_view(device.id)["words"] == "4× AA"
    assert coord.type_words(lonely.id) == "Zigbee router"
    assert "left out 2 answers set on device pages" in caplog.text
    assert coord._answers_rotation_armed is False


# ---------------------------------------------- answers held for unwatched devices


_MAINS = {"kind": "mains", "type": "Mains Powered", "quantity": None, "set": SET}


def _elsewhere(hass, uid, name, maker=None, model=None, model_id=None):
    """A device from an integration that can be excluded on its own."""
    source = MockConfigEntry(domain="hue", title="Elsewhere")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("hue", uid)}, name=name,
        manufacturer=maker, model=model, model_id=model_id,
    )
    er.async_get(hass).async_get_or_create("sensor", "hue", uid, device_id=device.id, config_entry=source)
    return device


async def test_answers_for_unwatched_devices_are_kept_and_listed_in_one_place(hass: HomeAssistant, hass_storage, _no_files):
    watched = _model_device(hass, "w1", "Button Doorbell")
    twin = _elsewhere(hass, "t1", "Button Hue Twin", MAKER, MODEL, MODEL_ID)
    lamp = _elsewhere(hass, "h1", "Lamp Office", "Signify", "Hue go", "7602031P7")
    bare = _elsewhere(hass, "h2", "Bridge Bare")
    lamp_key = json.dumps(["Signify", "Hue go", "7602031P7"])
    gone_key = json.dumps(["Gone Maker", "Gone Model", ""])
    hass_storage[ANSWERS_STORE_KEY] = _doc(ANSWERS_STORE_KEY, {
        "power": {"models": {KEY: _power("AA", 2, twin.id), lamp_key: {**_MAINS, "device_id": lamp.id},
                             gone_key: _power("CR2032", 1, "gone")},
                  "devices": {bare.id: _MAINS}},
        "types": {"models": {lamp_key: _type("Lamp", lamp.id)},
                  "devices": {bare.id: {"type": "Hub", "set": SET}}}})
    coord = await setup_coordinator(hass, {CONF_EXCLUDED_INTEGRATIONS: ["hue"]})
    answers = (await async_get_config_entry_diagnostics(hass, coord.entry))["answers"]
    assert (answers["file"], answers["power_models"], answers["power_devices"],
            answers["type_models"], answers["type_devices"]) == ("device_sentinel.answers", 3, 1, 1, 1)
    held = answers["held"]
    by_model = {json.dumps(item["model"]) if item["model"] else None: item for item in held}
    assert KEY not in by_model, "a model with a watched device was listed as held"
    assert coord.power_view(watched.id)["words"] == "2× AA", "the excluded setter's answer stopped covering its model"
    lamp_item = by_model[lamp_key]
    assert (lamp_item["power"], lamp_item["type"], lamp_item["set"]) == ("Mains Powered", "Lamp", SET)
    assert lamp_item["devices"] == [{"device_id": lamp.id, "name": "Lamp Office", "why": "excluded"}]
    assert by_model[gone_key]["devices"] == [{"device_id": "gone", "name": None, "why": "not in Home Assistant"}]
    assert (by_model[None]["power"], by_model[None]["type"]) == ("Mains Powered", "Hub")
    assert by_model[None]["devices"] == [{"device_id": bare.id, "name": "Bridge Bare", "why": "excluded"}]
    assert len(held) == 3


async def test_an_excluded_device_keeps_its_answers_for_when_it_is_watched_again(hass: HomeAssistant, hass_storage, _no_files):
    lamp = _elsewhere(hass, "h1", "Lamp Office", "Signify", "Hue go", "7602031P7")
    entry = await setup_entry(hass)
    entry.runtime_data.page_set_type(lamp.id, "Other", "Lamp")
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_EXCLUDED_INTEGRATIONS: ["hue"]})
    await hass.async_block_till_done()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert lamp.id not in entry.runtime_data._watched
    held = entry.runtime_data.answers_held()
    assert [item["type"] for item in held] == ["Lamp"]
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_EXCLUDED_INTEGRATIONS: []})
    await hass.async_block_till_done()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert lamp.id in entry.runtime_data._watched
    assert entry.runtime_data.type_words(lamp.id) == "Lamp"
    assert entry.runtime_data.answers_held() == []


async def test_deleting_a_device_deletes_its_answers(hass: HomeAssistant, hass_storage, _no_files):
    """Deletes need no saving (James, 8 October 2026)."""
    lonely, _ = register_device(hass, "n1", "No Maker")
    coord = await setup_coordinator(hass)
    coord.page_set_type(lonely.id, "Other", "Hub")
    coord.page_set_power(lonely.id, "Mains Powered")
    dr.async_get(hass).async_remove_device(lonely.id)
    await hass.async_block_till_done()
    assert coord.answers_held() == []
    assert lonely.id not in coord._type_entries and lonely.id not in coord._power_entries


# ------------------------------------------------------------- uninstall


async def test_uninstall_removes_the_answers_file_and_the_old_power_file(hass: HomeAssistant, hass_storage, _no_files):
    """0.24.7 to 0.25.0 left the power file behind on uninstall."""
    entry = await setup_entry(hass)
    for key in (ANSWERS_STORE_KEY, LEGACY_POWER_KEY):
        for suffix in ("", "last-good"):
            _write(_disk(hass, key, suffix), _doc(key, {}))
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    for key in (ANSWERS_STORE_KEY, LEGACY_POWER_KEY):
        for suffix in ("", "last-good"):
            assert not os.path.exists(_disk(hass, key, suffix)), (key, suffix)


# ------------------------------------------------- on real files (0.25.1 testing)
#
# The harness keeps storage in memory and never runs Home Assistant's
# own reading code, which is where a wrong-shaped file fails. These run
# it, on files in the test configuration's .storage folder.


@pytest.fixture
def real_disk(hass, hass_storage, _no_files):
    """Home Assistant's own storage on disk, undone before the harness's."""

    async def list_storage():
        await ha_storage.get_internal_store_manager(hass).async_initialize()

    with (patch.object(Store, "_async_load", REAL_LOAD), patch.object(Store, "_async_write_data", REAL_WRITE),
          patch.object(Store, "async_remove", REAL_REMOVE)):
        yield list_storage
    for path in glob.glob(_disk(hass, "device_sentinel") + "*"):
        os.remove(path)


def _text(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


async def test_disk_the_move_works_with_home_assistants_file_cache(hass: HomeAssistant, real_disk):
    """Home Assistant lists .storage at start and answers "no such file"
    from that list; only the save's own invalidation lets the read-back
    see the new file."""
    device = _model_device(hass)
    _write(_disk(hass, LEGACY_POWER_KEY), _legacy_0_25_0(device.id))
    await real_disk()
    coord = await setup_coordinator(hass)
    assert coord.power_view(device.id)["words"] == "2× AAA"
    assert _read(_disk(hass, ANSWERS_STORE_KEY))["data"]["power"]["models"][KEY]["type"] == "AAA"
    assert not os.path.exists(_disk(hass, LEGACY_POWER_KEY))
    coord.page_set_power(device.id, "CR2032", 1)
    await coord.async_flush_answers()
    assert _read(_disk(hass, ANSWERS_STORE_KEY, "last-good"))["data"]["power"]["models"][KEY]["type"] == "AAA"


async def test_disk_a_corrupt_file_is_set_aside_and_restored(hass: HomeAssistant, real_disk):
    device = _model_device(hass)
    _text(_disk(hass, ANSWERS_STORE_KEY), "{ not json")
    _write(_disk(hass, ANSWERS_STORE_KEY, "last-good"), _doc(ANSWERS_STORE_KEY, {
        "power": {"models": {KEY: _power("CR2450", 1, device.id)}, "devices": {}},
        "types": {"models": {}, "devices": {}}}))
    await real_disk()
    entry = await setup_entry(hass)
    assert entry.runtime_data.power_view(device.id)["words"] == "CR2450"
    assert glob.glob(_disk(hass, ANSWERS_STORE_KEY) + ".corrupt.*")
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert glob.glob(_disk(hass, "device_sentinel") + "*") == [], "uninstall left a file"


WRONG_SHAPES = [
    json.dumps({"key": "x", "data": {}}),
    json.dumps({"version": 1, "key": "x"}),
    json.dumps([1, 2, 3]),
    json.dumps({"version": "1", "minor_version": 1, "data": {}}),
    json.dumps({"version": 2, "minor_version": 1, "data": {}}),
    json.dumps({"version": 0, "minor_version": 1, "data": {}}),
    json.dumps({"version": False, "minor_version": 1, "data": {}}),
    json.dumps({"version": 1, "minor_version": 2, "data": {"power": [], "types": "x"}}),
    json.dumps({"version": 1, "minor_version": 1, "data": [1]}),
    "",
    "null",
    "7",
]


@pytest.mark.parametrize("text", WRONG_SHAPES)
async def test_disk_an_answers_file_of_the_wrong_shape_never_stops_a_start(hass: HomeAssistant, real_disk, text):
    """Valid text in the wrong shape made Home Assistant raise a KeyError or
    TypeError, and Device Sentinel did not start (found by testing)."""
    device = _model_device(hass)
    _text(_disk(hass, ANSWERS_STORE_KEY), text)
    _write(_disk(hass, ANSWERS_STORE_KEY, "last-good"), _doc(ANSWERS_STORE_KEY, {
        "power": {"models": {KEY: _power("CR2450", 1, device.id)}, "devices": {}},
        "types": {"models": {}, "devices": {}}}))
    await real_disk()
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    words = entry.runtime_data.power_view(device.id)["words"]
    assert words in ("CR2450", "Not known"), words


@pytest.mark.parametrize("text", WRONG_SHAPES + [
    json.dumps(_doc(LEGACY_POWER_KEY, {"models": [1], "devices": "x"})),
    json.dumps(_doc(LEGACY_POWER_KEY, {"models": {"k": None, "[1]": {"kind": "battery"}}, "devices": {"7": 7}})),
])
async def test_disk_an_old_power_file_of_the_wrong_shape_never_stops_a_start(hass: HomeAssistant, real_disk, text):
    _model_device(hass)
    _text(_disk(hass, LEGACY_POWER_KEY), text)
    await real_disk()
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED


async def test_disk_a_restart_inside_the_save_second_keeps_the_answers(hass: HomeAssistant, real_disk):
    """Only the unload wrote an answer still inside its one-second wait,
    and Home Assistant does not unload integrations when it stops
    (found by testing; power had it since 0.24.9)."""
    device = _model_device(hass)
    await real_disk()
    coord = await setup_coordinator(hass)
    coord.page_set_power(device.id, "AAA", 3)
    coord.page_set_type(device.id, "Button")
    await hass.async_stop(force=True)
    data = _read(_disk(hass, ANSWERS_STORE_KEY))["data"]
    assert data["power"]["models"][KEY]["quantity"] == 3
    assert data["types"]["models"][KEY]["type"] == "Button"


def _age(path, seconds):
    stamp = os.path.getmtime(path) - seconds
    os.utime(path, (stamp, stamp))


LATER = "2026-10-09T12:00:00+00:00"


async def test_disk_coming_back_after_a_rollback_keeps_what_was_set_there(hass: HomeAssistant, real_disk, caplog):
    """0.25.1 moved the answers; the owner went back to 0.25.0, which started
    with no power answers, set a battery there, which wrote
    device_sentinel.power again, and came back. That answer is taken, and
    every other answer here stays (found by testing and review)."""
    device = _model_device(hass)
    other_key = json.dumps(["Other Maker", "Other Model", ""])
    _write(_disk(hass, ANSWERS_STORE_KEY), _doc(ANSWERS_STORE_KEY, {
        "power": {"models": {KEY: _power("AAA", 2, device.id), other_key: _power("CR2", 1, "elsewhere")},
                  "devices": {}},
        "types": {"models": {KEY: _type("Button", device.id)}, "devices": {}}}))
    _write(_disk(hass, LEGACY_POWER_KEY), _doc(LEGACY_POWER_KEY, {
        "models": {KEY: {**_power("CR2477", 1, device.id), "set": LATER}}, "devices": {}}))
    await real_disk()
    coord = await setup_coordinator(hass)
    assert coord.power_text(device.id) == "CR2477"
    assert coord.type_words(device.id) == "Button"
    assert not os.path.exists(_disk(hass, LEGACY_POWER_KEY))
    data = _read(_disk(hass, ANSWERS_STORE_KEY))["data"]
    assert data["power"]["models"][KEY]["type"] == "CR2477", "the answer set on the older release was lost"
    assert data["power"]["models"][other_key]["type"] == "CR2", "an answer the older release never had was lost"
    assert data["types"]["models"][KEY]["type"] == "Button"
    kept = _read(_disk(hass, ANSWERS_STORE_KEY, "last-good"))["data"]
    assert kept["power"]["models"][KEY]["type"] == "AAA", "the answers file it replaced was not kept"
    assert "took power answers set later" in caplog.text


async def test_disk_a_backup_copied_back_by_hand_never_overrides_newer_answers(hass: HomeAssistant, real_disk):
    """A copied file gets a new file time; the answers' own set times decide
    (found by review)."""
    device = _model_device(hass)
    new_key = json.dumps(["Other Maker", "Other Model", ""])
    _write(_disk(hass, ANSWERS_STORE_KEY), _doc(ANSWERS_STORE_KEY, {
        "power": {"models": {KEY: {**_power("CR2032", 1, device.id), "set": LATER}}, "devices": {}},
        "types": {"models": {}, "devices": {}}}))
    _age(_disk(hass, ANSWERS_STORE_KEY), 3600)
    stale = _legacy_0_25_0(device.id)
    stale["data"]["models"][new_key] = _power("AA", 3, "elsewhere")
    _write(_disk(hass, LEGACY_POWER_KEY), stale)
    await real_disk()
    coord = await setup_coordinator(hass)
    assert coord.power_text(device.id) == "CR2032", "a stale backup overrode a newer answer"
    data = _read(_disk(hass, ANSWERS_STORE_KEY))["data"]
    assert data["power"]["models"][new_key]["type"] == "AA", "an answer only the backup had was not taken"
    assert not os.path.exists(_disk(hass, LEGACY_POWER_KEY))


async def test_disk_an_older_leftover_changes_nothing_and_is_deleted(hass: HomeAssistant, real_disk):
    """The move wrote the answers file and a stop came before the delete."""
    device = _model_device(hass)
    _write(_disk(hass, LEGACY_POWER_KEY), _legacy_0_25_0(device.id))
    answers = _doc(ANSWERS_STORE_KEY, {
        "power": {"models": {KEY: _power("AAA", 2, device.id)}, "devices": {}},
        "types": {"models": {}, "devices": {}}})
    _write(_disk(hass, ANSWERS_STORE_KEY), answers)
    await real_disk()
    coord = await setup_coordinator(hass)
    assert coord.power_text(device.id) == "2× AAA"
    assert not os.path.exists(_disk(hass, LEGACY_POWER_KEY))
    assert _read(_disk(hass, ANSWERS_STORE_KEY)) == answers, "an unchanged file was rewritten"


# ------------------------------------------------------- found by testing


async def test_a_flush_waits_for_a_write_already_running(hass: HomeAssistant, hass_storage, _no_files):
    """A reload's flush returned while the timer's write sat between its
    rotation and its save, so the new session could start from last-good
    and then overwrite the newest answer."""
    device = _model_device(hass)
    coord = await setup_coordinator(hass)
    original = coord._answers_store.async_save
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(data):
        entered.set()
        await release.wait()
        await original(data)

    coord._answers_store.async_save = slow
    coord.page_set_power(device.id, "AAA", 2)
    write = hass.async_create_task(coord._answers_write())
    await entered.wait()
    flush = hass.async_create_task(coord.async_flush_answers())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not flush.done(), "the flush returned before the write it raced"
    release.set()
    await write
    await flush
    assert hass_storage[ANSWERS_STORE_KEY]["data"]["power"]["models"][KEY]["type"] == "AAA"


async def test_a_deleted_setter_hands_its_answers_to_an_unwatched_device_of_the_model(
    hass: HomeAssistant, hass_storage, _no_files
):
    """Only watched devices could take a model answer over, so deleting the
    device that set it dropped it while an excluded one still used it."""
    setter = _model_device(hass, "w1", "Button Watched")
    twin = _elsewhere(hass, "t1", "Button Excluded Twin", MAKER, MODEL, MODEL_ID)
    coord = await setup_coordinator(hass, {CONF_EXCLUDED_INTEGRATIONS: ["hue"]})
    coord.page_set_type(setter.id, "Button")
    coord.page_set_power(setter.id, "AAA", 2)
    dr.async_get(hass).async_remove_device(setter.id)
    await hass.async_block_till_done()
    assert coord.type_words(twin.id) == "Button"
    assert coord.power_text(twin.id) == "2× AAA"
    held = coord.answers_held()
    assert [(h["type"], h["power"], h["devices"][0]["device_id"], h["devices"][0]["why"]) for h in held] == [
        ("Button", "2× AAA", twin.id, "excluded")]


async def test_an_answer_whose_device_changed_model_says_so(hass: HomeAssistant, hass_storage, _no_files):
    device = _model_device(hass)
    coord = await setup_coordinator(hass)
    coord.page_set_type(device.id, "Button")
    dr.async_get(hass).async_update_device(device.id, model_id="NEW-ID")
    held = coord.answers_held()
    assert held[0]["devices"] == [{"device_id": device.id, "name": "Button Doorbell",
                                   "why": "now reports another model"}]


async def test_a_damaged_model_key_is_left_out_and_the_download_works(hass: HomeAssistant, hass_storage, caplog, _no_files):
    device = _model_device(hass)
    hass_storage[ANSWERS_STORE_KEY] = _doc(ANSWERS_STORE_KEY, {
        "power": {"models": {"not json": _power("AA", 1, "gone"), json.dumps(["", "x", ""]): _power("AA", 1, "g"),
                             json.dumps([1, 2, 3]): _power("AA", 1, "g"), KEY: _power("CR2", 1, device.id)},
                  "devices": {}},
        "types": {"models": {"[]": _type("Plug")}, "devices": {}}})
    coord = await setup_coordinator(hass)
    assert "left out 4 answers set on device pages" in caplog.text
    assert coord.power_text(device.id) == "CR2"
    diagnostics = await async_get_config_entry_diagnostics(hass, coord.entry)
    assert diagnostics["answers"]["power_models"] == 1


async def test_disk_a_damaged_newer_old_file_leaves_the_answers_in_charge(hass: HomeAssistant, real_disk):
    """Its last-good copy may be from before the move, so it is not read."""
    device = _model_device(hass)
    _write(_disk(hass, ANSWERS_STORE_KEY), _doc(ANSWERS_STORE_KEY, {
        "power": {"models": {KEY: _power("AAA", 2, device.id)}, "devices": {}},
        "types": {"models": {}, "devices": {}}}))
    _age(_disk(hass, ANSWERS_STORE_KEY), 3600)
    _text(_disk(hass, LEGACY_POWER_KEY), "{ damaged")
    _write(_disk(hass, LEGACY_POWER_KEY, "last-good"), _legacy_0_25_0(device.id))
    with open(_disk(hass, LEGACY_POWER_KEY, "last-good"), encoding="utf-8") as handle:
        stale = json.load(handle)
    stale["data"]["models"][KEY].update(type="CR2", quantity=1)
    _write(_disk(hass, LEGACY_POWER_KEY, "last-good"), stale)
    await real_disk()
    coord = await setup_coordinator(hass)
    assert coord.power_text(device.id) == "2× AAA"
    assert not os.path.exists(_disk(hass, LEGACY_POWER_KEY, "last-good"))


async def test_a_devices_own_answer_stays_its_own_across_a_restart(hass: HomeAssistant, hass_storage, _no_files):
    """Set before the device reported a model, a power answer is the
    device's own. A restart after the model arrived turned it into the
    whole model's answer, or dropped it when the model had one (found by
    testing)."""
    first, _ = register_device(hass, "o1", "First")
    second = _model_device(hass, "o2", "Second")
    third, _ = register_device(hass, "o3", "Third")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord.page_set_power(first.id, "AAA", 1)
    coord.page_set_power(third.id, "CR2", 1)
    coord.page_set_type(third.id, "Other", "Lamp")
    for device in (first, third):
        dr.async_get(hass).async_update_device(device.id, manufacturer=MAKER, model=MODEL, model_id=MODEL_ID)
    coord.page_set_power(second.id, "CR2032", 1)
    before = {d.id: (coord.power_text(d.id), coord.type_words(d.id)) for d in (first, second, third)}
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    after = {d.id: (coord.power_text(d.id), coord.type_words(d.id)) for d in (first, second, third)}
    assert after == before
    assert before[first.id][0] == "AAA" and before[second.id][0] == "CR2032"


async def test_the_move_keeps_an_old_per_device_entry_whose_model_is_answered(hass: HomeAssistant, hass_storage, _no_files):
    """A 0.24.7-style entry on a device whose model already has an answer
    was dropped without a word, and the move then deleted the file (found
    by review). It stays the device's own."""
    first = _model_device(hass, "k1", "First")
    second = _model_device(hass, "k2", "Second")
    hass_storage[LEGACY_POWER_KEY] = _doc(LEGACY_POWER_KEY, {
        "models": {KEY: _power("AAA", 2, second.id)},
        "devices": {first.id: {"kind": "battery", "type": "CR2", "quantity": 1, "set": SET}}})
    coord = await setup_coordinator(hass)
    assert coord.power_text(first.id) == "CR2" and coord.power_text(second.id) == "2× AAA"
    assert hass_storage[ANSWERS_STORE_KEY]["data"]["power"]["devices"][first.id]["type"] == "CR2"


async def test_the_page_names_the_models_answer_and_counts_only_devices_it_covers(
    hass: HomeAssistant, hass_storage, _no_files
):
    """A device with its own answer is not covered by the model's, and its
    clear button names the model's answer, which is what clearing puts in
    place (found by review)."""
    first = _model_device(hass, "v1", "First")
    second = _model_device(hass, "v2", "Second")
    third = _model_device(hass, "v3", "Third")
    coord = await setup_coordinator(hass)
    coord._power_entries[first.id] = {"kind": "battery", "type": "CR2", "quantity": 1, "set": SET}
    coord._type_entries[first.id] = {"type": "Lamp", "set": SET}
    coord.page_set_power(second.id, "AAA", 2)
    coord.page_set_type(second.id, "Button")
    power, kind = coord.power_view(first.id), coord.type_view(first.id)
    assert (power["words"], power["model_answer"]) == ("CR2", "2× AAA")
    assert (kind["words"], kind["model_answer"]) == ("Lamp", "Button")
    assert coord.power_view(second.id)["covers"] == 2 and coord.type_view(second.id)["covers"] == 2
    assert coord.power_view(second.id)["model_answer"] is None
    from custom_components.device_sentinel.const import DATA_SYSTEM_EVENTS, SYS_DEVICE_PAGE, SYS_KIND
    rows = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_DEVICE_PAGE]
    assert coord._system_event_phrase(rows[-1]) == "type set to Button, for all 2 devices of this model, from its device page"
    coord.page_set_type(first.id, "Plug")
    rows = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_DEVICE_PAGE]
    assert coord._system_event_phrase(rows[-1]) == "type set to Plug, for all 3 devices of this model, from its device page"
    assert third.id
