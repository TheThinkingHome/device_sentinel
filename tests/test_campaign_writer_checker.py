"""Pre-stable campaign: the writer and the checker agree, always.

Tim's false repair card came from a row the journal writes by design
and the storage check called damage. 0.19.7 writes a new incident
cause and touches the retire path, the verdict lifecycle and the
grace rules. So after every operation this campaign performs on a
fleet, it runs the storage check over the live document and requires
zero faults. Any disagreement between what the code writes and what
the code accepts fails here, before a fold on a real system finds it.

Operations are randomized from the things a day actually holds:
devices going silent past their basis, resuming, restarts opening
and closing grace, devices leaving and rejoining the watched set,
items acknowledged, deleted by hand and re-added, batteries falling,
bridges dropping, and the midnight fold itself.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CLOCK_FIELDS,
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
)
from custom_components.device_sentinel.normalise import (
    check_records,
    check_storage,
)

from tests.conftest import FLEET_ABSENT, fleet_path
from tests.helpers import register_device, setup_coordinator

JAMES = fleet_path("james", "2026-08-29", "device_sentinel.storage")
TIM = fleet_path("tim", "2026-08-29", "device_sentinel_storage.json")
OBSERVED = "2026-07-08T00:00:00+00:00"
STEPS = 60


CLOCKS_FOR = {
    "device_sentinel.storage": "device_sentinel.clocks",
    "device_sentinel_storage.json": "device_sentinel_clocks.json",
}


def _fleet(path: Path) -> list[dict]:
    """The fleet's records as the load path presents them: the main
    file with the companion clocks merged in."""
    with open(path, encoding="utf-8") as handle:
        devices = json.load(handle)["data"]["devices"]
    with open(path.parent / CLOCKS_FOR[path.name], encoding="utf-8") as h:
        clocks = json.load(h)["data"].get("clocks") or {}
    out = []
    for device_id, record in devices.items():
        if not isinstance(record, dict):
            continue
        merged = dict(record)
        fields = clocks.get(device_id) or {}
        for field in CLOCK_FIELDS:
            if field in fields:
                merged[field] = fields[field]
        out.append(merged)
    return out


def _faults(coord) -> list:
    """Every fault the check would raise on the live document."""
    return check_records(coord.data.get(DATA_DEVICES)) + check_storage(
        coord.data
    )


async def _campaign(hass: HomeAssistant, path: Path, seed: int) -> dict:
    rng = random.Random(seed)
    records = _fleet(path)
    owner = MockConfigEntry(domain="campaign_stack", title="Campaign")
    owner.add_to_hass(hass)
    registry = dr.async_get(hass)

    # A dozen watched devices with entities and learned rhythms, two
    # with no entities at all, all carrying real fleet records.
    watched = []
    for index in range(12):
        device, _ = register_device(hass, f"c{seed}_{index}")
        watched.append(device)
    bare = [
        registry.async_get_or_create(
            config_entry_id=owner.entry_id,
            identifiers={("campaign_stack", f"bare-{seed}-{i}")},
            name=f"Bare {seed} {i}",
        )
        for i in range(2)
    ]
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    now = dt_util.utcnow().timestamp()
    for index, device in enumerate(watched):
        base = dict(rng.choice(records))
        base[DEV_DAILY_MAX] = [float(rng.randint(600, 7200))] * 14
        base[DEV_EVENT_COUNT] = rng.randint(1, 500)
        base[DEV_LAST_ACTIVITY] = now - rng.uniform(0, 300)
        base[DEV_FROZEN_CATEGORY] = None
        base[DEV_FROZEN_SINCE] = None
        coord.data[DATA_DEVICES][device.id] = base
    for device in bare:
        rec = coord.data[DATA_DEVICES].setdefault(device.id, {})
        rec[DEV_EVENT_COUNT] = 0
        rec[DEV_LAST_ACTIVITY] = None
        rec[DEV_FIRST_OBSERVED] = OBSERVED
    for index, record in enumerate(records[:80]):
        coord.data[DATA_DEVICES].setdefault(f"bg{seed}_{index}", dict(record))
    coord._rebuild_registry_view()

    operations = 0
    worst = 0
    for step in range(STEPS):
        op = rng.choice(
            [
                "silent", "resume", "restart_open", "restart_close",
                "leave", "rejoin", "ack", "delete", "fold", "judge",
                "battery", "sweep",
            ]
        )
        device = rng.choice(watched)
        rec = coord.data[DATA_DEVICES][device.id]
        if op == "silent":
            rec[DEV_LAST_ACTIVITY] = (
                dt_util.utcnow().timestamp()
                - rng.uniform(1.5, 6.0) * rec[DEV_DAILY_MAX][0]
            )
        elif op == "resume":
            coord._record_activity(device.id, coord.entry.entry_id)
        elif op == "restart_open":
            coord._grace_until = dt_util.utcnow().timestamp() + 300.0
            coord._rebuild_registry_view()
        elif op == "restart_close":
            coord._grace_until = 0.0
            coord._rebuild_registry_view()
        elif op == "leave":
            coord._watched.pop(device.id, None)
            coord._clear_verdicts_for_set_aside(
                {device.id: ("n", "campaign", "x")}
            )
        elif op == "rejoin":
            coord._watched[device.id] = "campaign_stack"
        elif op == "ack":
            for item in coord.data.get("todo_items", []):
                if item["device_id"] == device.id:
                    item["status"] = "completed"
        elif op == "delete":
            coord.data["todo_items"] = [
                i for i in coord.data.get("todo_items", [])
                if i["device_id"] != device.id
            ]
            coord._hand_deleted.add(device.id)
        elif op == "fold":
            coord._note_silences(dt_util.utcnow().timestamp())
            coord._trim_episodes(dt_util.utcnow().timestamp())
        elif op == "battery":
            rec["battery_value"] = rng.choice([100.0, 45.0, 8.0, None])
        elif op == "sweep":
            coord._note_silences(dt_util.utcnow().timestamp())
        coord._judge_all_devices()
        coord._sync_problem_list()
        await hass.async_block_till_done()
        operations += 1
        faults = _faults(coord)
        worst = max(worst, len(faults))
        assert faults == [], (
            f"seed {seed} step {step} op {op}: the check disagrees with "
            f"the writer: {faults[:3]}"
        )
    return {"seed": seed, "operations": operations, "worst": worst}


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
@pytest.mark.parametrize("seed", range(25))
async def test_writer_and_checker_agree_james(hass: HomeAssistant, seed):
    await _campaign(hass, JAMES, 30_000 + seed)


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
@pytest.mark.parametrize("seed", range(25))
async def test_writer_and_checker_agree_tim(hass: HomeAssistant, seed):
    await _campaign(hass, TIM, 40_000 + seed)
