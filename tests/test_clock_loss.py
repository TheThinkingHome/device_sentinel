# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_clock_loss.py, Version: 0.24.2 (2026-10-03)

"""A lost clocks file, and a startup grace that holds everything.

The owner deleted the reference rig's clocks file on 23 September to
see what a person would meet. Every clock came back empty, and an
empty clock with no events is what "never reported" means: 31 healthy
devices went on the list when the grace closed, each with a fault
event, and the watering sensor's verdict moved from unavailable to
never reported one minute into the start, closed its unavailable
incident as a recovery and pushed to the phone inside the grace.

These tests replay that start. The ones that are not guards fail on
0.22.27.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    DATA_DEVICES,
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_ITEMS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DOMAIN,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_NEVER_REPORTED,
    FREEZE_CATEGORY_UNAVAILABLE,
    INC_EVENT,
    INC_KIND,
    INCIDENT_RESOLVED,
    REPAIR_CLOCK_RESET,
    REPAIR_CLOCKS_RESET,
    STARTUP_GRACE_SECONDS,
    STORAGE_CLOCKS_KEY,
    SYS_CLOCK_RESET,
    SYS_DURATION,
    SYS_KIND,
    TODO_KINDS,
    TODO_SORT_NAME,
)
from tests.conftest import FLEET_ABSENT, fleet_path
from tests.helpers import registry_settled, setup_coordinator

from .helpers import record_events, register_device, setup_entry
from .test_bridge_hold import _house as _hold_house
from .test_bridge_hold import _minutes

HOUR = 3600.0
FAST = "Fast Plug"
SLOW = "Slow Button"
FROZE = "Frozen Door"
DEAD = "Watering Kit"
FRESH = "New Sensor"


@pytest.fixture(autouse=True)
def _mid_afternoon(freezer):
    """1:00 PM Pacific, clear of the brief time and of midnight."""
    freezer.move_to("2026-09-23T20:00:00+00:00")


def _entity(entities):
    return entities[0] if isinstance(entities, list) else entities


async def _tick(hass, freezer, seconds: float = 60.0) -> None:
    freezer.tick(seconds)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _house(hass: HomeAssistant, freezer):
    """The rig in miniature, settled past its first grace.

    A fast reporter, a slow one, a device already frozen, the watering
    kit already listed unavailable, and a device added yesterday that
    has never reported and has no history.
    """
    devices = {
        name: register_device(hass, f"cl{index}", name=name)
        for index, name in enumerate((FAST, SLOW, FROZE, DEAD, FRESH))
    }
    for name, (_device, entities) in devices.items():
        hass.states.async_set(
            _entity(entities), "unavailable" if name == DEAD else "1"
        )
    phone = async_mock_service(hass, "notify", "phone")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]})
    coordinator = entry.runtime_data
    now = dt_util.utcnow().timestamp()
    long_ago = (dt_util.utcnow() - timedelta(days=60)).isoformat()
    for name, (device, _entities) in devices.items():
        record = coordinator.data[DATA_DEVICES][device.id]
        if name == FRESH:
            continue
        record[DEV_DAILY_MAX] = [
            600.0 if name == FAST else 20000.0
        ] * (FREEZE_ARMING_DAYS + 5)
        record[DEV_FIRST_OBSERVED] = long_ago
        record[DEV_EVENT_COUNT] = 500
        record[DEV_LAST_ACTIVITY] = now - (
            30 * HOUR if name in (FROZE, DEAD) else 300
        )
    for _ in range(int(STARTUP_GRACE_SECONDS // 60) + 3):
        await _tick(hass, freezer)
    return entry, devices, phone


async def _lose_the_clocks(hass, hass_storage, freezer, entry):
    """Stop, delete the clocks file, start: the owner's own steps."""
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    del hass_storage[STORAGE_CLOCKS_KEY]
    freezer.tick(60)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _verdict(coordinator, devices, name):
    device, _entities = devices[name]
    return coordinator.data[DATA_DEVICES][device.id].get(DEV_FROZEN_CATEGORY)


def _listed(coordinator) -> dict[str, list[str]]:
    return {
        item[TODO_SORT_NAME]: sorted(item[TODO_KINDS])
        for item in coordinator.data[DATA_TODO_ITEMS]
    }


async def test_the_house_before_the_loss_is_as_the_rig_was(
    hass: HomeAssistant, freezer
):
    """Guard: the scene is set as it stood on the rig."""
    entry, devices, _phone = await _house(hass, freezer)
    coordinator = entry.runtime_data
    assert _verdict(coordinator, devices, DEAD) == FREEZE_CATEGORY_UNAVAILABLE
    assert _verdict(coordinator, devices, FROZE) == FREEZE_CATEGORY_FROZEN
    assert _verdict(coordinator, devices, SLOW) is None


async def test_no_device_with_history_reads_never_reported(
    hass: HomeAssistant, hass_storage, freezer
):
    entry, devices, _phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    faults = record_events(hass, EVENT_FAULT)
    for _ in range(12):
        await _tick(hass, freezer)
    for name in (FAST, SLOW, FROZE, DEAD):
        assert _verdict(coordinator, devices, name) != (
            FREEZE_CATEGORY_NEVER_REPORTED
        ), name
    assert not [
        event for event in faults
        if event.get("kind") == FREEZE_CATEGORY_NEVER_REPORTED
        and event.get("name") != FRESH
    ]


async def test_the_clocks_restart_at_the_load(
    hass: HomeAssistant, hass_storage, freezer, caplog
):
    entry, devices, _phone = await _house(hass, freezer)
    caplog.set_level(logging.WARNING, logger="custom_components.device_sentinel")
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    loaded_at = dt_util.utcnow().timestamp()
    slow, _entities = devices[SLOW]
    clock = coordinator.data[DATA_DEVICES][slow.id][DEV_LAST_ACTIVITY]
    assert clock == pytest.approx(loaded_at, abs=5)
    said = [r.getMessage() for r in caplog.records if "clocks file" in r.getMessage()]
    assert said and "4 device clock(s) restart" in said[0], said


async def test_a_device_with_no_history_keeps_no_clock(
    hass: HomeAssistant, hass_storage, freezer
):
    """Guard: a device that has never reported must still read so."""
    entry, devices, _phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    fresh, _entities = devices[FRESH]
    assert coordinator.data[DATA_DEVICES][fresh.id][DEV_LAST_ACTIVITY] is None


async def test_a_frozen_device_stays_frozen_until_it_reports(
    hass: HomeAssistant, hass_storage, freezer
):
    """A restarted clock is not a report (the owner's ruling, on #124)."""
    entry, devices, _phone = await _house(hass, freezer)
    frozen_since = entry.runtime_data.data[DATA_DEVICES][
        devices[FROZE][0].id
    ][DEV_FROZEN_SINCE]
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    for _ in range(12):
        await _tick(hass, freezer)
    assert _verdict(coordinator, devices, FROZE) == FREEZE_CATEGORY_FROZEN
    record = coordinator.data[DATA_DEVICES][devices[FROZE][0].id]
    assert record[DEV_FROZEN_SINCE] == frozen_since
    assert not [
        row for row in coordinator.data[DATA_INCIDENTS]
        if row["name"] == FROZE and row[INC_EVENT] == INCIDENT_RESOLVED
    ]
    # A real report ends it.
    hass.states.async_set(_entity(devices[FROZE][1]), "2")
    await _tick(hass, freezer)
    assert _verdict(coordinator, devices, FROZE) is None


async def test_nothing_is_judged_inside_the_grace(
    hass: HomeAssistant, hass_storage, freezer
):
    entry, devices, _phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    before = _listed(coordinator)
    for _ in range(int(STARTUP_GRACE_SECONDS // 60) - 1):
        await _tick(hass, freezer)
        assert _listed(coordinator) == before
        assert _verdict(coordinator, devices, DEAD) == (
            FREEZE_CATEGORY_UNAVAILABLE
        )


async def test_the_unavailable_device_is_never_called_recovered(
    hass: HomeAssistant, hass_storage, freezer
):
    entry, _devices, _phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    for _ in range(12):
        await _tick(hass, freezer)
    assert not [
        row for row in coordinator.data[DATA_INCIDENTS]
        if row["name"] == DEAD
        and row[INC_EVENT] == INCIDENT_RESOLVED
        and row[INC_KIND] == FREEZE_CATEGORY_UNAVAILABLE
    ]


async def test_nothing_is_pushed_inside_the_grace(
    hass: HomeAssistant, hass_storage, freezer
):
    entry, _devices, phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    phone.clear()
    await coordinator.async_fire_events([("freeze", "At 1:01 pm, a test.", False)])
    await hass.async_block_till_done()
    assert phone == []
    for _ in range(int(STARTUP_GRACE_SECONDS // 60) - 1):
        await _tick(hass, freezer)
    assert phone == [], [call.data.get("message") for call in phone]


async def test_a_push_still_goes_after_the_grace(
    hass: HomeAssistant, hass_storage, freezer
):
    """Guard: the hold ends with the window."""
    entry, _devices, phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    for _ in range(int(STARTUP_GRACE_SECONDS // 60) + 1):
        await _tick(hass, freezer)
    phone.clear()
    await coordinator.async_fire_events([("freeze", "At 1:07 pm, a test.", False)])
    await hass.async_block_till_done()
    assert len(phone) == 1


async def test_no_upstream_is_announced_inside_the_grace(
    hass: HomeAssistant, hass_storage, freezer
):
    """Held, not dropped: its phase is not recorded, so it is owed later."""
    entry, _devices, _phone = await _house(hass, freezer)
    coordinator = await _lose_the_clocks(hass, hass_storage, freezer, entry)
    coordinator._upstream_announced["MQTT broker"] = 3
    coordinator._broker_down_at = None
    assert coordinator._upstream_messages() == []
    coordinator._grace_until = 0.0
    assert coordinator._upstream_messages() == [("MQTT broker", 3, True)]


async def test_the_repair_card_names_the_moment(
    hass: HomeAssistant, hass_storage, freezer
):
    entry, _devices, _phone = await _house(hass, freezer)
    await _lose_the_clocks(hass, hass_storage, freezer, entry)
    loaded_at = dt_util.as_local(dt_util.utcnow()).strftime("%-I:%M %p")
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, REPAIR_CLOCKS_RESET) is None
    for _ in range(int(STARTUP_GRACE_SECONDS // 60) + 1):
        await _tick(hass, freezer)
    issue = registry.async_get_issue(DOMAIN, REPAIR_CLOCKS_RESET)
    assert issue is not None
    assert issue.translation_placeholders["time"] == loaded_at
    assert issue.severity == ir.IssueSeverity.WARNING
    assert not issue.is_fixable


async def test_a_whole_clocks_file_raises_no_card(
    hass: HomeAssistant, hass_storage, freezer
):
    """Guard: an ordinary restart says nothing about clocks."""
    entry, _devices, _phone = await _house(hass, freezer)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(60)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for _ in range(int(STARTUP_GRACE_SECONDS // 60) + 1):
        await _tick(hass, freezer)
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, REPAIR_CLOCKS_RESET) is None


# A clock reset or a paused system restarts the clocks, with a Repair card (#538).


async def _stepped(hass, freezer, seconds: float):
    """A house whose wall clock steps by `seconds` between two checks,
    the monotonic clock standing still for the step."""
    coord, device, value, seen, heard, phone, bus = await _hold_house(hass, freezer)
    mono = {"now": 1000.0}
    coord._monotonic = lambda: mono["now"]  # type: ignore[method-assign]
    record = coord.data[DATA_DEVICES][device.id]
    hass.states.async_set(seen, dt_util.utcnow().isoformat())
    await hass.async_block_till_done()
    freezer.tick(60)
    mono["now"] += 60
    await coord._on_render_tick(None)
    await hass.async_block_till_done()
    freezer.tick(60 + seconds)
    mono["now"] += 60
    await coord._on_render_tick(None)
    await hass.async_block_till_done()
    return coord, device, record, bus

@pytest.mark.parametrize("seconds", [2 * HOUR, -2 * HOUR], ids=["forward", "backward"])
async def test_a_clock_reset_restarts_the_clocks_with_a_repair_card(hass: HomeAssistant, freezer, seconds):
    coord, device, record, bus = await _stepped(hass, freezer, seconds)
    now = dt_util.utcnow().timestamp()
    assert abs(record[DEV_LAST_ACTIVITY] - now) < 5, "the clock did not restart at the reset"
    assert record[DEV_FROZEN_CATEGORY] is None, "a healthy device was judged on time that did not pass"
    assert not [b for b in bus if b[0] == "fault"], bus
    events = [e for e in coord.data[DATA_SYSTEM_EVENTS] if e.get(SYS_KIND) == SYS_CLOCK_RESET]
    assert len(events) == 1 and abs(events[0][SYS_DURATION] - abs(seconds)) < 5, events
    assert ("+" if seconds > 0 else "-") in str(events[0].get("detail")), events
    issue = ir.async_get(hass).async_get_issue(DOMAIN, REPAIR_CLOCK_RESET)
    assert issue is not None and issue.translation_placeholders and "shift" in issue.translation_placeholders

async def test_a_small_correction_is_not_a_reset(hass: HomeAssistant, freezer):
    coord, device, record, bus = await _stepped(hass, freezer, 120.0)
    assert not [e for e in coord.data[DATA_SYSTEM_EVENTS] if e.get(SYS_KIND) == SYS_CLOCK_RESET]
    assert ir.async_get(hass).async_get_issue(DOMAIN, REPAIR_CLOCK_RESET) is None

async def test_a_frozen_device_stays_frozen_through_a_reset(hass: HomeAssistant, freezer):
    coord, device, value, seen, heard, phone, bus = await _hold_house(hass, freezer)
    mono = {"now": 1000.0}
    coord._monotonic = lambda: mono["now"]  # type: ignore[method-assign]
    await _minutes(hass, coord, freezer, 3)
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_FROZEN_CATEGORY] == "frozen"
    mono["now"] += 60
    await coord._on_render_tick(None)
    freezer.tick(60 - 2 * HOUR)
    mono["now"] += 60
    await coord._on_render_tick(None)
    await hass.async_block_till_done()
    assert record[DEV_FROZEN_CATEGORY] == "frozen"
    assert not [b for b in bus if b[0] == "recovered"], bus
    await _minutes(hass, coord, freezer, 3)
    assert record[DEV_FROZEN_CATEGORY] == "frozen"

async def test_a_dead_device_is_caught_after_a_backward_step(hass: HomeAssistant, freezer):
    """On 0.23.15 the catch came a step late: 155 minutes after a
    two-hour step, against 35 with none."""
    coord, device, record, bus = await _stepped(hass, freezer, -2 * HOUR)
    window = coord._freeze_window(record)
    await _minutes(hass, coord, freezer, int(window // 60) + 3)
    assert record[DEV_FROZEN_CATEGORY] == "frozen", "still blind after the step"

@pytest.mark.parametrize("seconds", [2 * HOUR, -2 * HOUR], ids=["forward", "backward"])
async def test_running_windows_keep_their_real_time_through_a_reset(hass: HomeAssistant, freezer, seconds):
    """The startup grace and a maintenance window are held as wall-clock
    moments; a reset must not stretch them by its size or end them."""
    coord, device, value, seen, heard, phone, bus = await _hold_house(hass, freezer)
    mono = {"now": 1000.0}
    coord._monotonic = lambda: mono["now"]  # type: ignore[method-assign]
    await coord._on_render_tick(None)
    now = dt_util.utcnow().timestamp()
    coord._grace_until = now + 200.0
    await coord.async_toggle_maintenance(30)
    maintenance_left = coord._maintenance_until - now
    freezer.tick(60 + seconds)
    mono["now"] += 60
    await coord._on_render_tick(None)
    await hass.async_block_till_done()
    now = dt_util.utcnow().timestamp()
    assert abs((coord._grace_until - now) - 140.0) < 2, coord._grace_until - now
    assert coord._maintenance_until is not None, "the maintenance window closed early"
    assert abs((coord._maintenance_until - now) - (maintenance_left - 60)) < 2, coord._maintenance_until - now


# The startup grace attacked: no device without entities judged never reported, nothing listed inside the grace, and a set-aside retire makes no sound.


JAMES = fleet_path("reference", "device_sentinel.storage")

TIM = fleet_path("second", "2026-08-26", "device_sentinel_storage.json")

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
        self.pushes: list[tuple] = []
        self.recoveries: list[dict] = record_events(hass, EVENT_RECOVERED)
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
    # Device Sentinel's view catches up with the new devices before
    # anything reads them, as it does within 2 seconds (0.24.2).
    await registry_settled(hass)
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


# A lost clocks file and a device with no learned day, found in the simulation of 23 September.


@pytest.fixture
def _mid_afternoon_fixes(freezer):
    freezer.move_to("2026-09-24T20:00:00+00:00")

async def _lose_clocks(hass, hass_storage, freezer, entry):
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    del hass_storage[STORAGE_CLOCKS_KEY]
    freezer.tick(60)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data

async def _settle(hass, freezer, minutes: int) -> None:
    for _ in range(minutes):
        freezer.tick(60)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

@pytest.mark.usefixtures("_mid_afternoon_fixes")
async def test_a_device_that_reported_without_a_learned_day_keeps_a_clock(
    hass: HomeAssistant, hass_storage, freezer
):
    """The fourth fleet's case: 22 events, three days old, no fold yet."""
    device, entities = register_device(hass, "nc1", name="Pico Remote")
    hass.states.async_set(entities[0] if isinstance(entities, list) else entities, "1")
    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = (dt_util.utcnow() - timedelta(days=3)).isoformat()
    record[DEV_EVENT_COUNT] = 22
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 3600
    coordinator = await _lose_clocks(hass, hass_storage, freezer, entry)
    assert coordinator.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] is not None
    await _settle(hass, freezer, int(STARTUP_GRACE_SECONDS // 60) + 2)
    assert coordinator.data[DATA_DEVICES][device.id].get(DEV_FROZEN_CATEGORY) != (
        FREEZE_CATEGORY_NEVER_REPORTED
    )

@pytest.mark.usefixtures("_mid_afternoon_fixes")
async def test_a_device_stored_as_never_reported_stays_so(
    hass: HomeAssistant, hass_storage, freezer
):
    """Guard: the verdict it carries is kept, and so is its empty clock."""
    device, _entities = register_device(hass, "nc2", name="Dead On Arrival")
    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = (dt_util.utcnow() - timedelta(days=5)).isoformat()
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_NEVER_REPORTED
    coordinator = await _lose_clocks(hass, hass_storage, freezer, entry)
    assert coordinator.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] is None

@pytest.mark.usefixtures("_mid_afternoon_fixes")
async def test_a_young_device_keeps_no_clock(
    hass: HomeAssistant, hass_storage, freezer
):
    """Guard: under 48 hours it still has its whole window to speak."""
    device, _entities = register_device(hass, "nc3", name="New Sensor")
    entry = await setup_entry(hass)
    record = entry.runtime_data.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = []
    record[DEV_FIRST_OBSERVED] = (dt_util.utcnow() - timedelta(hours=10)).isoformat()
    coordinator = await _lose_clocks(hass, hass_storage, freezer, entry)
    assert coordinator.data[DATA_DEVICES][device.id][DEV_LAST_ACTIVITY] is None
