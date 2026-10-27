# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_anonymise_fleet.py, Version: 0.27.10 (2026-10-27)

"""The anonymizer, the power file and the answers file (rule CODE-17).

Model keys are written by the device's own integration, and an ESPHome
device's maker is often a name its owner chose. So a model key is
replaced like a name: by a stand-in of the same shape, the same in
every place it stands and from one refresh to the next, with an empty
part left empty so the suite can still give a device the maker and
model its entry names.

A house keeps every pencil answer in the answers file, what powers a
device and what it is. Its two parts carry model keys of the same
kind, and both are replaced the same way (rule STOR-20).

Every day older than the main file's thirty lives in the history file
beside it, keyed by the same device ids and carrying rows that can
name devices. So the history file is anonymized like the storage file,
and a name that stands only in it is still caught (rule STOR-03).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

TOOL = Path(__file__).parent.parent / "tools" / "anonymise_fleet.py"
DEVICE = "0123456789abcdef0123456789abcdef"
REAL_KEY = json.dumps(["esphome-carol-workshop", "bluetooth-proxy", ""])
SECOND_KEY = json.dumps(["Aqara", "Door and window sensor", "MCCGQ11LM"])


def _tool():
    spec = importlib.util.spec_from_file_location("anonymise_fleet", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _house(raw: Path) -> None:
    folder = raw / "reference"
    folder.mkdir(parents=True)
    store = {"version": 1, "minor_version": 1, "key": "k", "data": {}}
    (folder / "device_sentinel.storage").write_text(json.dumps({
        **store, "data": {"devices": {DEVICE: {"name": "Carol Workshop Proxy"}}}}))
    (folder / "device_sentinel.clocks").write_text(json.dumps({
        **store, "data": {"clocks": {DEVICE: {"event_count": 3}}}}))
    (folder / "device_sentinel.power").write_text(json.dumps({**store, "data": {
        "models": {
            REAL_KEY: {"kind": "usb", "type": "USB Powered", "quantity": None,
                       "set": "2026-10-06T00:00:00+00:00", "device_id": DEVICE},
            SECOND_KEY: {"kind": "battery", "type": "CR2032", "quantity": 1,
                         "set": "2026-10-06T00:00:00+00:00", "device_id": DEVICE},
        },
        "devices": {DEVICE: {"kind": "usb", "type": "USB Powered", "quantity": None,
                             "set": "2026-10-06T00:00:00+00:00", "model": REAL_KEY}},
    }}))
    (folder / "config_entry-device_sentinel-01KX781WVRSH9TNTNCD8R6DF09.json").write_text(
        json.dumps({"data": {"devices": {DEVICE: {"name": "Carol Workshop Proxy"}},
                             "entry_options": {}}}))


def test_power_model_keys_become_stand_ins_of_the_same_shape(tmp_path: Path):
    tool = _tool()
    _house(tmp_path / "raw")
    key = tmp_path / "key.json"
    assert tool.main([str(tmp_path / "raw"), str(tmp_path / "out"), "--key", str(key)]) == 0
    written = tmp_path / "out" / "reference" / "device_sentinel.power"
    text = written.read_text(encoding="utf-8")
    assert "carol" not in text.lower()
    assert "Aqara" not in text and "MCCGQ11LM" not in text
    power = json.loads(text)["data"]
    keys = sorted(power["models"])
    shapes = sorted(tuple(bool(part) for part in json.loads(k)) for k in keys)
    assert shapes == [(True, True, False), (True, True, True)]
    copy = next(iter(power["devices"].values()))
    assert copy["model"] in power["models"], "the device's copy names a different stand-in"
    assert power["models"][copy["model"]]["type"] == "USB Powered"
    assert DEVICE not in text


def test_a_second_run_with_the_same_key_writes_the_same_power_file(tmp_path: Path):
    tool = _tool()
    _house(tmp_path / "raw")
    key = tmp_path / "key.json"
    tool.main([str(tmp_path / "raw"), str(tmp_path / "one"), "--key", str(key)])
    tool.main([str(tmp_path / "raw"), str(tmp_path / "two"), "--key", str(key)])
    name = Path("reference") / "device_sentinel.power"
    assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()


def test_a_house_without_a_power_file_still_anonymizes(tmp_path: Path):
    tool = _tool()
    _house(tmp_path / "raw")
    (tmp_path / "raw" / "reference" / "device_sentinel.power").unlink()
    assert tool.main([str(tmp_path / "raw"), str(tmp_path / "out"), "--key", str(tmp_path / "k.json")]) == 0
    assert not (tmp_path / "out" / "reference" / "device_sentinel.power").exists()


def test_a_model_key_left_in_place_is_caught(tmp_path: Path, monkeypatch):
    """The leak check reads the power file too: a model key the run
    gave a stand-in but failed to replace stops the run."""
    tool = _tool()
    _house(tmp_path / "raw")

    def forgetful(power, house):
        for key in power["data"]["models"]:
            house.model(key)
        return power

    monkeypatch.setattr(tool, "_power_models", forgetful)
    with pytest.raises(SystemExit, match="real values survived"):
        tool.main([str(tmp_path / "raw"), str(tmp_path / "out"), "--key", str(tmp_path / "k.json")])


def _answers_house(raw: Path) -> None:
    """The same house a release later: its power file moved into the
    answers file, with a type answer on the same models."""
    _house(raw)
    folder = raw / "reference"
    power = json.loads((folder / "device_sentinel.power").read_text())["data"]
    (folder / "device_sentinel.power").unlink()
    store = {"version": 1, "minor_version": 1, "key": "device_sentinel.answers"}
    (folder / "device_sentinel.answers").write_text(json.dumps({**store, "data": {
        "power": {"models": power["models"], "devices": {}},
        "types": {
            "models": {
                REAL_KEY: {"type": "Bluetooth Proxy", "set": "2026-10-09T00:00:00+00:00", "device_id": DEVICE},
                SECOND_KEY: {"type": "Door Sensor", "set": "2026-10-09T00:00:00+00:00", "device_id": DEVICE},
            },
            "devices": {DEVICE: {"type": "Bluetooth Proxy", "set": "2026-10-09T00:00:00+00:00"}},
        },
    }}))


def test_answer_model_keys_become_the_same_stand_ins_in_both_parts(tmp_path: Path):
    tool = _tool()
    _answers_house(tmp_path / "raw")
    key = tmp_path / "key.json"
    assert tool.main([str(tmp_path / "raw"), str(tmp_path / "out"), "--key", str(key)]) == 0
    written = tmp_path / "out" / "reference" / "device_sentinel.answers"
    text = written.read_text(encoding="utf-8")
    assert "carol" not in text.lower()
    assert "Aqara" not in text and "MCCGQ11LM" not in text
    assert DEVICE not in text
    data = json.loads(text)["data"]
    assert set(data["power"]["models"]) == set(data["types"]["models"]), "one model, two stand-ins"
    shapes = sorted(tuple(bool(part) for part in json.loads(k)) for k in data["types"]["models"])
    assert shapes == [(True, True, False), (True, True, True)]
    assert sorted(e["type"] for e in data["types"]["models"].values()) == ["Bluetooth Proxy", "Door Sensor"]
    assert not (tmp_path / "out" / "reference" / "device_sentinel.power").exists()


def test_a_house_on_0_24_and_one_on_0_25_share_a_key(tmp_path: Path):
    """A refresh that moves a house from its power file to its answers
    file gives each model the stand-in it had before."""
    tool = _tool()
    key = tmp_path / "key.json"
    _house(tmp_path / "old")
    tool.main([str(tmp_path / "old"), str(tmp_path / "one"), "--key", str(key)])
    _answers_house(tmp_path / "new")
    tool.main([str(tmp_path / "new"), str(tmp_path / "two"), "--key", str(key)])
    before = json.loads((tmp_path / "one" / "reference" / "device_sentinel.power").read_text())["data"]
    after = json.loads((tmp_path / "two" / "reference" / "device_sentinel.answers").read_text())["data"]
    assert set(before["models"]) == set(after["power"]["models"])


def test_a_type_key_left_in_place_is_caught(tmp_path: Path, monkeypatch):
    """The leak check reads the answers file: a type answer's model key
    given a stand-in but left in place stops the run."""
    tool = _tool()
    _answers_house(tmp_path / "raw")

    def forgetful(answers, house):
        data = answers["data"]
        data["power"]["models"] = {house.model(k): e for k, e in data["power"]["models"].items()}
        for key in data["types"]["models"]:
            house.model(key)
        return answers

    monkeypatch.setattr(tool, "_answers_models", forgetful)
    with pytest.raises(SystemExit, match="real values survived"):
        tool.main([str(tmp_path / "raw"), str(tmp_path / "out"), "--key", str(tmp_path / "k.json")])


def _history_house(raw: Path, history: dict) -> None:
    """The reference house of `_house`, with a history file beside it."""
    _house(raw)
    store = {"version": 1, "minor_version": 1, "key": "k"}
    (raw / "reference" / "device_sentinel.history").write_text(
        json.dumps({**store, "data": history}))


def test_the_history_file_is_anonymized_beside_the_storage_file(tmp_path: Path):
    tool = _tool()
    _history_house(tmp_path / "raw", {
        "generation": 4, "line": 1760000000.0,
        "devices": {DEVICE: {"daily_max": [60.0, 61.0]}},
        "system_events": [{"device_id": DEVICE, "name": "Carol Workshop Proxy",
                           "summary": "Carol Workshop Proxy went quiet"}],
    })
    key = tmp_path / "key.json"
    assert tool.main([str(tmp_path / "raw"), str(tmp_path / "out"), "--key", str(key)]) == 0
    written = tmp_path / "out" / "reference" / "device_sentinel.history"
    text = written.read_text(encoding="utf-8")
    assert DEVICE not in text and "carol" not in text.lower()
    history = json.loads(text)["data"]
    storage = json.loads(
        (tmp_path / "out" / "reference" / "device_sentinel.storage").read_text(encoding="utf-8")
    )["data"]
    assert list(history["devices"]) == list(storage["devices"])
    assert history["devices"][next(iter(history["devices"]))]["daily_max"] == [60.0, 61.0]
    assert history["generation"] == 4 and history["line"] == 1760000000.0


def test_a_name_only_the_history_file_holds_is_replaced(tmp_path: Path):
    """A device removed since keeps its name in the older rows only."""
    tool = _tool()
    gone = "fedcba9876543210fedcba9876543210"
    _history_house(tmp_path / "raw", {
        "generation": 1, "line": 1760000000.0, "devices": {},
        "system_events": [
            {"device_id": gone, "name": "Garage Freezer Dave"},
            {"device_id": gone, "summary": "Garage Freezer Dave went quiet"},
        ],
    })
    key = tmp_path / "key.json"
    assert tool.main([str(tmp_path / "raw"), str(tmp_path / "out"), "--key", str(key)]) == 0
    text = (tmp_path / "out" / "reference" / "device_sentinel.history").read_text(encoding="utf-8")
    assert "Dave" not in text and gone not in text


def test_a_removed_device_keeps_no_real_name(tmp_path: Path):
    """A record held thirty days after its device was removed carries
    the name it had, which is a person's name for a device too."""
    tool = _tool()
    raw = tmp_path / "raw"
    _house(raw)
    storage = raw / "reference" / "device_sentinel.storage"
    data = json.loads(storage.read_text(encoding="utf-8"))
    data["data"]["devices"]["fedcba9876543210fedcba9876543210"] = {
        "removed_name": "Garage Freezer Dave"}
    storage.write_text(json.dumps(data))
    key = tmp_path / "key.json"
    assert tool.main([str(raw), str(tmp_path / "out"), "--key", str(key)]) == 0
    text = (tmp_path / "out" / "reference" / "device_sentinel.storage").read_text(encoding="utf-8")
    assert "Dave" not in text

