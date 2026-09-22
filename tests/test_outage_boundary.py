# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_outage_boundary.py, Version: 0.22.20 (2026-09-21)

"""0.21.12's stored data at the storage boundary (rulings #279, #370).

0.21.12 writes one new field, an ended outage's worst figure, and two
new event kinds. The wide fuzz in `test_campaign_boundary_hostile.py`
damages the fields a fleet file already holds, and no fleet file holds
these yet, so on its own it would never touch them: the gap #279 was
ruled against, where a check was read off one file's values rather
than off every value the code can write. Here the new shape is
written onto each fleet first, then the new fields are damaged, the
file goes through the real load, and every reader, the new Wi-Fi
rules among them, runs over what the gate let through. The write
seam and the save are held to the same shape.
"""

from __future__ import annotations

import copy
import math
import random

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    SYS_BRIDGE_UP,
    SYS_DEVICES,
    SYS_KIND,
    SYS_WIFI_RECOVERING,
    SYS_WORST,
)
from custom_components.device_sentinel.normalise import damaged_rows
from tests.conftest import fleet_param
from tests.helpers import register_device, setup_coordinator
from tests.test_campaign_boundary_hostile import (
    FLEETS,
    POISONS,
    _boot,
    _clean,
    _clocks,
    _fleet,
    _plant,
)
from tests.test_forward_outage_shape import _synthesize

_EVENT_FIELDS = (SYS_WORST, SYS_DEVICES, SYS_KIND)

# The hostile file's own pair, and both fleets as they stand now.
SHAPE_FLEETS = FLEETS + [
    fleet_param(
        "reference", "device_sentinel.storage", id="james_now",
        clocks=("reference", "device_sentinel.clocks"),
    ),
]


def _vouched(coord) -> None:
    """What the boundary promises about the fields 0.21.12 reads."""
    for row in coord.data[DATA_SYSTEM_EVENTS]:
        assert isinstance(row.get(SYS_KIND), str), row
        for field in (SYS_WORST, SYS_DEVICES):
            if field in row:
                value = row[field]
                assert isinstance(value, int) and not isinstance(
                    value, bool
                ), row
    for record in coord.data[DATA_DEVICES].values():
        began = record.get(DEV_FROZEN_SINCE)
        assert began is None or (
            isinstance(began, (int, float))
            and not isinstance(began, bool)
            and math.isfinite(began)
        ), record


def _damage(data: dict, rng: random.Random) -> int:
    """Poison the fields 0.21.12 writes, and the failure times its
    rules read. Returns how many values were damaged."""
    damaged = 0
    events = data[DATA_SYSTEM_EVENTS]
    carriers = [row for row in events if SYS_WORST in row]
    for _ in range(rng.randint(3, 12)):
        row = rng.choice(carriers or events)
        field = rng.choice(_EVENT_FIELDS)
        if rng.random() < 0.8:
            row[field] = rng.choice(POISONS)
        else:
            row.pop(field, None)
        damaged += 1
    devices = [
        record for record in (data.get(DATA_DEVICES) or {}).values()
        if isinstance(record, dict)
    ]
    for record in rng.sample(devices, min(len(devices), rng.randint(3, 12))):
        record[DEV_FROZEN_CATEGORY] = "unavailable"
        record[DEV_FROZEN_SINCE] = rng.choice(
            POISONS + [float("nan"), float("inf")]
        )
        damaged += 1
    return damaged


def test_the_synthesized_shape_carries_the_new_fields():
    """The fuzz below is only worth running if the data it damages
    carries what 0.21.12 writes."""
    for path, _clocks_path in (param.values for param in SHAPE_FLEETS):
        if not path.exists():
            continue
        data = _synthesize(copy.deepcopy(_fleet(path)))
        kinds = {row[SYS_KIND] for row in data[DATA_SYSTEM_EVENTS]}
        assert SYS_WIFI_RECOVERING in kinds
        assert any(SYS_WORST in row for row in data[DATA_SYSTEM_EVENTS])
        assert damaged_rows(data) == {}


@pytest.mark.parametrize("path,clocks_path", SHAPE_FLEETS)
@pytest.mark.parametrize("seed", range(12))
async def test_the_new_fields_damaged_through_the_real_load(
    hass: HomeAssistant, hass_storage, path, clocks_path, seed
):
    rng = random.Random(44_000 + seed)
    data = _synthesize(copy.deepcopy(_fleet(path)))
    assert _damage(data, rng) > 0

    register_device(hass, f"shape{seed}")
    _plant(hass_storage, data, _clocks(clocks_path))
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    _plant(hass_storage, data, _clocks(clocks_path))
    coord = await _boot(hass, entry)
    assert coord is not None, f"seed {seed}: setup died"
    coord._grace_until = 0.0

    ok, why = _clean(coord)
    assert ok, f"seed {seed}: {why}"
    _vouched(coord)

    coord._judge_all_devices()
    coord._wifi_backdate()
    coord._note_upstream_peaks()
    coord.wifi_burst_held()
    coord.reportable_down_rows
    coord.suppressed_down_counts
    coord._sync_problem_list()
    await hass.async_block_till_done()
    assert await coord.async_regenerate_reports(), (
        f"seed {seed}: the reports died on a repaired document"
    )
    await coord._save_main()
    ok, why = _clean(coord)
    assert ok, f"seed {seed}, after the save: {why}"
    _vouched(coord)


async def test_the_write_seam_refuses_a_bad_worst_figure(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    before = len(coord.data[DATA_SYSTEM_EVENTS])
    for bad in ("56", 5.5, True, [56]):
        coord._record_system_event(
            SYS_BRIDGE_UP, scope="zha", devices=55, worst=bad
        )
    assert len(coord.data[DATA_SYSTEM_EVENTS]) == before
    coord._record_system_event(SYS_BRIDGE_UP, scope="zha", devices=55, worst=14)
    assert coord.data[DATA_SYSTEM_EVENTS][-1][SYS_WORST] == 14


async def test_a_clean_save_still_rotates_the_last_good_copy(
    hass: HomeAssistant,
):
    """#281: a save that holds a new-shaped row must still check clean,
    or the last-good copy stops being refreshed and nobody notices."""
    coord = await setup_coordinator(hass)
    coord._record_system_event(
        SYS_BRIDGE_UP, scope="zha", devices=55, worst=14, duration=700.0
    )
    coord._record_system_event(SYS_WIFI_RECOVERING, scope="wifi")
    await coord._save_main()
    assert coord._rotation_armed is True
    taken = coord._last_good_taken
    await coord._save_main()
    assert coord._last_good_taken is not None
    assert coord._last_good_taken != taken or taken is None
    assert coord._rotation_armed is True
    assert dt_util.utcnow().timestamp() >= coord._last_good_taken
