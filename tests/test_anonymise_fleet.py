# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_anonymise_fleet.py, Version: 0.25.0 (2026-10-08)

"""The anonymizer and the power file (fleet refresh, 8 October 2026).

The committed houses now carry each house's power file. Its model keys
are written by the device's own integration, and an ESPHome device's
maker is often a name its owner chose, as one of the second fleet's
was. So a model key is replaced like a name: by a stand-in of the same
shape, the same in every place it stands and from one refresh to the
next, with an empty part left empty so the suite can still give a
device the maker and model its entry names.
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
