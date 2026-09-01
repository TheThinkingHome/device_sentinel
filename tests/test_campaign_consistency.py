"""Pre-stable campaign: the changed paths stay consistent, and every
report still renders.

0.19.7 changed the retire path, the verdict lifecycle, the grace
rules and the incident log. This campaign drives randomized days
against both fleets and, after every step, checks invariants that
tie those pieces together:

  1  a recovery event fires only for a device in the watched set
  2  every to-do item belongs to a device that currently has a
     problem, or was held only by an acknowledgment
  3  in the incident log, an opening is followed by at most one
     closing (resolved or set aside) before the next opening
  4  every recovery duration is non-negative and no longer than the
     time since the incident opened
  5  a device outside the watched set carries no freeze verdict
  6  a device with no entities is never on the list

And at the end of every round it regenerates every report, so a
row the renderers have not learned cannot reach a real system as a
crash or as a sentence that is untrue.
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
    ACTION_SET_ASIDE,
    CLOCK_FIELDS,
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    EVENT_RECOVERED,
    INCIDENT_ACTION,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
)

from tests.conftest import FLEET_ABSENT, fleet_path
from tests.helpers import register_device, setup_coordinator

JAMES = fleet_path("james", "2026-08-29", "device_sentinel.storage")
TIM = fleet_path("tim", "2026-08-29", "device_sentinel_storage.json")
CLOCKS_FOR = {
    "device_sentinel.storage": "device_sentinel.clocks",
    "device_sentinel_storage.json": "device_sentinel_clocks.json",
}
OBSERVED = "2026-07-08T00:00:00+00:00"
STEPS = 50


def _fleet(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        devices = json.load(handle)["data"]["devices"]
    with open(path.parent / CLOCKS_FOR[path.name], encoding="utf-8") as h:
        clocks = json.load(h)["data"].get("clocks") or {}
    out = []
    for device_id, record in devices.items():
        if not isinstance(record, dict):
            continue
        merged = dict(record)
        for field in CLOCK_FIELDS:
            if field in (clocks.get(device_id) or {}):
                merged[field] = clocks[device_id][field]
        out.append(merged)
    return out


def _check_invariants(coord, recoveries, bare_ids, step: str) -> None:
    watched = set(coord._watched)
    problems = coord._problem_device_ids()

    # 1: recoveries only for watched devices. The event is fired at
    # the moment of retirement, so we check against the watched set
    # recorded on the event by the spy below.
    for r in recoveries:
        assert r["_watched_at_fire"], (
            f"[{step}] recovery fired for an unwatched device"
        )

    # 2: every item belongs to a device with a problem, or is an
    # acknowledged item awaiting its next check.
    for item in coord.data.get("todo_items", []):
        did = item["device_id"]
        assert did in problems or item.get("status") == "completed", (
            f"[{step}] item for {did} with no problem behind it"
        )

    # 3 and 4: the incident log balances, per device and kind.
    opened: dict[tuple, float] = {}
    for row in coord.data.get("incidents", []):
        key = (row["device_id"], row["kind"])
        event = row["event"]
        if event == INCIDENT_OPENED:
            assert key not in opened, (
                f"[{step}] {key} opened twice without closing"
            )
            opened[key] = row["when"]
        elif event == INCIDENT_RESOLVED:
            assert key in opened, f"[{step}] {key} resolved unopened"
            duration = row.get("duration")
            if duration is not None:
                assert 0 <= duration <= row["when"] - opened[key] + 1.0, (
                    f"[{step}] {key} duration {duration} impossible"
                )
            opened.pop(key)
        elif event == INCIDENT_ACTION and row.get("cause") == ACTION_SET_ASIDE:
            assert key in opened, f"[{step}] {key} set aside unopened"
            opened.pop(key)

    # 5: an unwatched device holds no verdict.
    for did, record in coord.data.get(DATA_DEVICES, {}).items():
        if did in watched or not isinstance(record, dict):
            continue
        if did.startswith("bg"):
            continue  # background records were never in the registry
        assert record.get(DEV_FROZEN_CATEGORY) is None, (
            f"[{step}] unwatched {did} holds a verdict"
        )

    # 6: a device with no entities is never listed.
    for item in coord.data.get("todo_items", []):
        assert item["device_id"] not in bare_ids, (
            f"[{step}] entity-less device on the list"
        )


async def _round(hass: HomeAssistant, path: Path, seed: int) -> dict:
    rng = random.Random(seed)
    records = _fleet(path)
    owner = MockConfigEntry(domain="consistency_stack", title="C")
    owner.add_to_hass(hass)
    registry = dr.async_get(hass)
    watched = [register_device(hass, f"k{seed}_{i}")[0] for i in range(10)]
    bare = [
        registry.async_get_or_create(
            config_entry_id=owner.entry_id,
            identifiers={("consistency_stack", f"b-{seed}-{i}")},
            name=f"Bare {seed} {i}",
        )
        for i in range(2)
    ]
    bare_ids = {d.id for d in bare}
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0

    recoveries: list[dict] = []

    def _catch(event):
        data = dict(event.data)
        data["_watched_at_fire"] = data.get("device_id") in coord._watched
        recoveries.append(data)

    hass.bus.async_listen(EVENT_RECOVERED, _catch)

    now = dt_util.utcnow().timestamp()
    for device in watched:
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
    for index, record in enumerate(records[:60]):
        coord.data[DATA_DEVICES].setdefault(f"bg{seed}_{index}", dict(record))
    coord._rebuild_registry_view()

    for step in range(STEPS):
        op = rng.choice(
            ["silent", "resume", "grace_open", "grace_close",
             "leave", "rejoin", "ack", "judge", "sweep"]
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
        elif op == "grace_open":
            coord._grace_until = dt_util.utcnow().timestamp() + 300.0
            coord._rebuild_registry_view()
        elif op == "grace_close":
            coord._grace_until = 0.0
            coord._rebuild_registry_view()
        elif op == "leave":
            coord._watched.pop(device.id, None)
            coord._clear_verdicts_for_set_aside(
                {device.id: ("n", "consistency_stack", "x")}
            )
        elif op == "rejoin":
            coord._watched[device.id] = "consistency_stack"
        elif op == "ack":
            for item in coord.data.get("todo_items", []):
                if item["device_id"] == device.id:
                    item["status"] = "completed"
        elif op == "sweep":
            coord._note_silences(dt_util.utcnow().timestamp())
        coord._judge_all_devices()
        coord._sync_problem_list()
        await hass.async_block_till_done()
        _check_invariants(coord, recoveries, bare_ids, f"seed {seed} step {step} {op}")

    # Every report must still render on this document.
    written = await coord.async_regenerate_reports()
    assert written, "no report was written"
    return {"seed": seed, "recoveries": len(recoveries), "reports": written}


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
@pytest.mark.parametrize("seed", range(20))
async def test_consistency_james(hass: HomeAssistant, seed):
    await _round(hass, JAMES, 50_000 + seed)


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
@pytest.mark.parametrize("seed", range(20))
async def test_consistency_tim(hass: HomeAssistant, seed):
    await _round(hass, TIM, 60_000 + seed)
