# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_history_file_hostile.py, Version: 0.26.2 (2026-10-13)

"""Hostile history files (ruling #661, the adversarial round).

A history file damaged in any shape must never stop a start, never be
joined into a record the main file holds clean, and never reach a
reader: a damaged live copy is answered by last-good, and two damaged
copies by the main file's thirty days. The same for the two keys the
main file carries for it.
"""

from __future__ import annotations

import copy
import random

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_HISTORY_GENERATION,
    DATA_HISTORY_LINE,
    STORAGE_HISTORY_KEY,
    STORAGE_KEY,
)
from custom_components.device_sentinel.history_file import LAST_GOOD
from custom_components.device_sentinel.normalise import check_records, damaged_rows

from .test_history_file import furnish, furnished, restart_with, series

HOSTILE_VALUES = [
    None, True, False, 0, -1, 1.5, 1e308, -1e308, "", "x", "1", [], {}, [None],
    ["x"], [True], [[1.0]], [{"a": 1}], {"a": [1.0]}, [1e308], [-5.0], [float("inf")],
]


def _paths(node, prefix=()):
    """Every place in a document a value can be replaced."""
    yield prefix
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _paths(value, (*prefix, key))
    elif isinstance(node, list):
        for index, value in enumerate(node[:3]):
            yield from _paths(value, (*prefix, index))


def _replace(document, path, value):
    if not path:
        return value
    target = document
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return document


def _clean(coord) -> None:
    """What a reader would meet passes both checks."""
    assert check_records(coord.data[DATA_DEVICES]) == []
    assert damaged_rows(coord.data) == {}


@pytest.mark.parametrize(
    "shape",
    [
        "not a map", "generation a string", "generation true", "generation missing",
        "devices a list", "device a list", "series a string", "series of text",
        "series of booleans", "series nested", "gap out of range", "battery out of range",
        "unknown series", "alt a list", "alt unknown series", "rows a map",
        "row a string", "row with a text time",
    ],
)
async def test_a_hostile_live_copy_is_answered_by_last_good(
    hass: HomeAssistant, hass_storage, shape
):
    entry, coord, ids = await furnished(hass, n=40, alt=True)
    await coord._save_now()
    good = copy.deepcopy(hass_storage[STORAGE_HISTORY_KEY]["data"])
    first = ids[0]
    damage = {
        "not a map": lambda d: "nonsense",
        "generation a string": lambda d: {**d, "generation": str(d["generation"])},
        "generation true": lambda d: {**d, "generation": True},
        "generation missing": lambda d: {k: v for k, v in d.items() if k != "generation"},
        "devices a list": lambda d: {**d, "devices": []},
        "device a list": lambda d: _replace(d, ("devices", first), []),
        "series a string": lambda d: _replace(d, ("devices", first, "daily_max"), "x"),
        "series of text": lambda d: _replace(d, ("devices", first, "daily_max"), ["x"] * 10),
        "series of booleans": lambda d: _replace(d, ("devices", first, "battery_daily_value"), [True] * 10),
        "series nested": lambda d: _replace(d, ("devices", first, "signal_daily_mean"), [[1.0]] * 10),
        "gap out of range": lambda d: _replace(d, ("devices", first, "daily_max"), [-5.0] * 10),
        "battery out of range": lambda d: _replace(d, ("devices", first, "battery_daily_value"), [900.0] * 10),
        "unknown series": lambda d: _replace(d, ("devices", first, "flap_drops"), [1.0]),
        "alt a list": lambda d: _replace(d, ("devices", first, "signal_alt"), []),
        "alt unknown series": lambda d: _replace(d, ("devices", first, "signal_alt", "signal_value"), [1.0]),
        "rows a map": lambda d: {**d, "system_events": {"a": 1}},
        "row a string": lambda d: {**d, "system_events": ["row"]},
        "row with a text time": lambda d: {**d, "system_events": [{"when": "noon", "kind": "restart", "scope": "system", "detail": None, "duration": None}]},
    }[shape]

    def hostile():
        hass_storage[STORAGE_HISTORY_KEY]["data"] = damage(copy.deepcopy(good))

    coord2 = await restart_with(hass, entry, hostile)
    assert entry.state is ConfigEntryState.LOADED
    assert coord2._history_state["joined"] == "last-good"
    assert coord2.data[DATA_DEVICES][first]["daily_max"] == series("daily_max", 40)
    _clean(coord2)


async def test_two_hostile_copies_start_with_thirty_days(hass: HomeAssistant, hass_storage):
    entry, coord, ids = await furnished(hass, n=40)
    await coord._save_now()

    def both():
        for key in (STORAGE_HISTORY_KEY, LAST_GOOD):
            hass_storage[key]["data"]["devices"][ids[0]]["daily_max"] = ["x"]

    coord2 = await restart_with(hass, entry, both)
    assert entry.state is ConfigEntryState.LOADED
    assert coord2.data[DATA_DEVICES][ids[0]]["daily_max"] == series("daily_max", 40)[-30:]
    _clean(coord2)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (DATA_HISTORY_GENERATION, "1"),
        (DATA_HISTORY_GENERATION, True),
        (DATA_HISTORY_GENERATION, [1]),
        (DATA_HISTORY_GENERATION, -3),
        (DATA_HISTORY_LINE, "yesterday"),
        (DATA_HISTORY_LINE, {"when": 1}),
        (DATA_HISTORY_LINE, 1e30),
    ],
)
async def test_hostile_keys_on_the_main_file_never_stop_a_start(
    hass: HomeAssistant, hass_storage, key, value
):
    entry, coord, ids = await furnished(hass, n=40)
    await coord._save_now()

    def hostile():
        hass_storage[STORAGE_KEY]["data"][key] = value

    coord2 = await restart_with(hass, entry, hostile)
    assert entry.state is ConfigEntryState.LOADED
    whole = coord2.data[DATA_DEVICES][ids[0]]["daily_max"]
    # Joined whole, or the main file's thirty days: never doubled.
    assert whole in (series("daily_max", 40), series("daily_max", 40)[-30:])
    _clean(coord2)


async def test_random_damage_anywhere_in_the_history_file(hass: HomeAssistant, hass_storage):
    """Three hundred random replacements at random places in both
    copies: every start runs, nothing damaged reaches a reader, and a
    series is the whole history or the main file's thirty days."""
    rng = random.Random(661)
    entry, coord, ids = await furnished(hass, n=40, alt=True)
    await coord._save_now()
    good = copy.deepcopy(hass_storage[STORAGE_HISTORY_KEY]["data"])
    places = list(_paths(good))
    for _round in range(300):
        live = copy.deepcopy(good)
        last = copy.deepcopy(good)
        live = _replace(live, rng.choice(places), rng.choice(HOSTILE_VALUES))
        if rng.random() < 0.5:
            last = _replace(last, rng.choice(places), rng.choice(HOSTILE_VALUES))

        def lay(live=live, last=last):
            hass_storage[STORAGE_HISTORY_KEY] = {"version": 1, "minor_version": 1, "key": STORAGE_HISTORY_KEY, "data": live}
            hass_storage[LAST_GOOD] = {"version": 1, "minor_version": 1, "key": LAST_GOOD, "data": last}

        coord2 = await restart_with(hass, entry, lay)
        assert entry.state is ConfigEntryState.LOADED
        _clean(coord2)
        thirty = series("daily_max", 40)[-30:]
        for device_id in ids:
            got = coord2.data[DATA_DEVICES][device_id]["daily_max"]
            # The main file's thirty days, or one copy's older part in
            # front of them: a value the checks accept is a value, but
            # nothing is ever a mixture of the two copies or doubled.
            allowed = [thirty]
            for doc in (live, last):
                try:
                    allowed.append(list(doc["devices"][device_id]["daily_max"]) + thirty)
                except (KeyError, TypeError, IndexError):
                    continue
            assert got in allowed
        # A start that joined nothing has only thirty days left, so the
        # next round starts from the furnished house again.
        for device_id in ids:
            furnish(coord2.data[DATA_DEVICES][device_id], 40, alt=True)
        coord2._critical = True
        await coord2._save_now()
        good = copy.deepcopy(hass_storage[STORAGE_HISTORY_KEY]["data"])
        places = list(_paths(good))
