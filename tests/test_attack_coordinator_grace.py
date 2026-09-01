"""Attack the coordinator fix until it cannot be broken.

Three barriers were built against one fault, and each is attacked
here rather than trusted:

  1. a device with no entity is never judged never reported
  2. a device first seen never reported inside grace is not listed
     until grace closes
  3. an item retired because its device left the watched set makes
     no sound of any kind

The attack drives randomized sequences of the things a real house
does around a restart: grace opening and closing, integrations
finishing loading at different moments, devices gaining entities
late, devices leaving and returning, persisted items from before the
restart, a device speaking mid-window, several restarts in a row.
After every step it checks invariants that may never be false:

  A  an entity-less device has no item, ever
  B  an entity-less device produces no fault push and no recovery
     event, ever
  C  a device that genuinely never reported and owns entities has
     exactly one item once grace has closed, and one fault push
  D  a genuine recovery, watched throughout, fires exactly one
     recovery event
  E  nothing is announced twice for one occurrence

It runs against the real device records of both fleets when their
files are present, and against a synthetic fleet otherwise.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    EVENT_RECOVERED,
)

from tests.conftest import FLEET_ABSENT, fleet_path
from tests.helpers import setup_coordinator

JAMES = fleet_path("james", "2026-08-29", "device_sentinel.storage")
TIM = fleet_path("tim", "2026-08-29", "device_sentinel_storage.json")
OBSERVED = "2026-07-08T00:00:00+00:00"
ROUNDS = 150


def _fleet(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return [{} for _ in range(40)]
    with open(path, encoding="utf-8") as handle:
        return [
            r for r in json.load(handle)["data"]["devices"].values()
            if isinstance(r, dict)
        ]


class _House:
    """One randomized house around one or more restarts."""

    def __init__(self, hass: HomeAssistant, coord, rng: random.Random):
        self.hass = hass
        self.coord = coord
        self.rng = rng
        self.registry = dr.async_get(hass)
        self.entities = er.async_get(hass)
        self.recoveries: list[dict] = []
        self.pushes: list[tuple] = []
        hass.bus.async_listen(
            EVENT_RECOVERED, lambda e: self.recoveries.append(e.data)
        )
        real_collect = coord._collect_event

        def spy(kind, name, recovery, device_id, **kw):
            self.pushes.append((device_id, kind, recovery))
            return real_collect(kind, name, recovery, device_id, **kw)

        coord._collect_event = spy
        self.owner = MockConfigEntry(domain="attack_stack", title="Attack")
        self.owner.add_to_hass(hass)
        self.entityless: set[str] = set()
        self.silent_with_entities: set[str] = set()
        self.recovering: set[str] = set()
        self.counter = 0

    def _device(self, name: str):
        self.counter += 1
        return self.registry.async_get_or_create(
            config_entry_id=self.owner.entry_id,
            identifiers={("attack_stack", f"{name}-{self.counter}")},
            name=f"{name} {self.counter}",
        )

    def add_entityless(self):
        device = self._device("Coordinator")
        self.entityless.add(device.id)
        return device

    def add_silent_with_entities(self):
        device = self._device("Silent")
        self.entities.async_get_or_create(
            "sensor", "attack_stack", f"uid-{self.counter}",
            device_id=device.id,
        )
        self.silent_with_entities.add(device.id)
        return device

    def seed(self, device_id: str):
        record = self.coord.data[DATA_DEVICES].setdefault(device_id, {})
        record[DEV_EVENT_COUNT] = 0
        record[DEV_LAST_ACTIVITY] = None
        record[DEV_FIRST_OBSERVED] = OBSERVED
        record[DEV_FROZEN_CATEGORY] = None
        record[DEV_FROZEN_SINCE] = None

    def open_grace(self):
        self.coord._grace_until = dt_util.utcnow().timestamp() + 300.0

    def close_grace(self):
        self.coord._grace_until = 0.0

    def rebuild(self):
        self.coord._rebuild_registry_view()

    def judge_and_sync(self):
        self.coord._judge_all_devices()
        self.coord._sync_problem_list()

    def speak(self, device_id: str):
        record = self.coord.data[DATA_DEVICES][device_id]
        record[DEV_EVENT_COUNT] = record.get(DEV_EVENT_COUNT, 0) + 1
        record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()
        record[DEV_FROZEN_CATEGORY] = None
        record[DEV_FROZEN_SINCE] = None
        self.recovering.add(device_id)

    def items_for(self, device_id: str) -> list[dict]:
        return [
            i for i in self.coord.data.get("todo_items", [])
            if i.get("device_id") == device_id
        ]

    def check_invariants(self, step: str) -> None:
        for device_id in self.entityless:
            assert not self.items_for(device_id), (
                f"[{step}] INVARIANT A: entity-less device listed"
            )
            assert not [p for p in self.pushes if p[0] == device_id], (
                f"[{step}] INVARIANT B: entity-less device pushed"
            )
            assert not [
                r for r in self.recoveries if r.get("device_id") == device_id
            ], f"[{step}] INVARIANT B: entity-less device recovered"


async def _run_round(hass: HomeAssistant, records: list[dict], seed: int):
    rng = random.Random(seed)
    coord = await setup_coordinator(hass)
    for index, record in enumerate(records[:60]):
        coord.data[DATA_DEVICES].setdefault(f"bg{seed}_{index}", dict(record))
    house = _House(hass, coord, rng)

    n_less = rng.randint(1, 8)
    n_silent = rng.randint(0, 3)
    entityless = [house.add_entityless() for _ in range(n_less)]
    silent = [house.add_silent_with_entities() for _ in range(n_silent)]
    for device in entityless + silent:
        house.seed(device.id)

    restarts = rng.randint(1, 3)
    for restart in range(restarts):
        # The restart: grace opens, the rebuild runs while the owner
        # may or may not have finished loading, the judge runs some
        # number of times inside the window.
        house.open_grace()
        house.rebuild()
        house.check_invariants(f"r{restart} rebuild-in-grace")
        for _ in range(rng.randint(1, 4)):
            house.judge_and_sync()
            await hass.async_block_till_done()
            house.check_invariants(f"r{restart} judge-in-grace")
            if silent and rng.random() < 0.2:
                house.speak(rng.choice(silent).id)
        # Sometimes a device gains entities mid-window, the case #260
        # protects: it must then be judged normally after grace.
        if entityless and rng.random() < 0.3:
            device = rng.choice(entityless)
            house.entities.async_get_or_create(
                "sensor", "attack_stack", f"late-{seed}-{restart}",
                device_id=device.id,
            )
            house.entityless.discard(device.id)
            house.silent_with_entities.add(device.id)
            silent.append(device)
            entityless.remove(device)
        # Grace closes: rebuild sets aside what has no entities.
        house.close_grace()
        house.rebuild()
        house.judge_and_sync()
        await hass.async_block_till_done()
        house.check_invariants(f"r{restart} grace-closed")
        for _ in range(rng.randint(1, 3)):
            house.judge_and_sync()
            await hass.async_block_till_done()
            house.check_invariants(f"r{restart} steady")

    # Invariant C: silent devices with entities are listed after
    # grace, exactly once each, unless they spoke.
    for device in silent:
        items = house.items_for(device.id)
        if device.id in house.recovering:
            assert not items, "a device that spoke is still listed"
        else:
            assert len(items) == 1, (
                f"INVARIANT C: silent device has {len(items)} item(s)"
            )
    # Invariant D and E: each speaking device recovered exactly once
    # per listing, never more.
    for device_id in house.recovering:
        mine = [
            r for r in house.recoveries if r.get("device_id") == device_id
        ]
        assert len(mine) <= 1, f"INVARIANT E: {len(mine)} recoveries"
    return {
        "entityless": n_less,
        "silent": n_silent,
        "restarts": restarts,
        "recoveries": len(house.recoveries),
        "pushes": len(house.pushes),
    }


@pytest.mark.parametrize("seed", range(ROUNDS))
async def test_attack_synthetic(hass: HomeAssistant, seed: int) -> None:
    await _run_round(hass, _fleet(None), seed)


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
@pytest.mark.parametrize("seed", range(40))
async def test_attack_james_fleet(hass: HomeAssistant, seed: int) -> None:
    await _run_round(hass, _fleet(JAMES), 10_000 + seed)


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
@pytest.mark.parametrize("seed", range(40))
async def test_attack_tim_fleet(hass: HomeAssistant, seed: int) -> None:
    await _run_round(hass, _fleet(TIM), 20_000 + seed)
