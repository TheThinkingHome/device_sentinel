"""Replay a restart against both real fleets and count what it says.

The method this file exists to serve: reproduce the whole fault at
fleet scale before changing anything, then run the same simulation
after the fix and require it to come out silent, with real
recoveries still announcing.

What is real here and what is not, stated plainly:

  real  every device record, taken from the fleet's own storage
        file: its learned maxima, its first_observed, its clocks
  real  which devices leave the watched set, taken from what each
        fleet actually did: James's ZHA coordinator, and the eight
        devices Tim's brief names as never reported at every restart
        and recovering five minutes later
  not   the registry itself, which the harness builds

It reports counts rather than asserting them, so the same file
answers before and after.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    EVENT_RECOVERED,
)

from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.helpers import register_device, setup_coordinator

# The fleet files live outside the repository. When they are absent
# the fleet-scale runs are skipped and the behavioural tests below
# still run, so the suite is honest about what it checked rather
# than silently proving less.
JAMES = Path("/home/claude/fleets/james/2026-08-29/device_sentinel.storage")
TIM = Path(
    "/home/claude/fleets/tim/2026-08-29/device_sentinel_storage.json"
)

# What each fleet actually did. James's coordinator has no entities
# and is watched for the length of the startup grace at every
# restart. Tim's brief names eight devices going never reported at
# every restart and recovering after exactly five minutes, which is
# the same window closing.
JAMES_LEAVERS = 1
TIM_LEAVERS = 8

OBSERVED = "2026-07-08T00:00:00+00:00"


def _fleet_records(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return list(json.load(handle)["data"]["devices"].values())


async def _run_restart_cycle(
    hass: HomeAssistant, fleet: str, path: Path, leavers: int
) -> dict:
    """Watch a fleet, judge it, then take the leavers out of watch.

    This is the restart: grace holds the no-entity devices in the
    watched set, they are judged never reported because they have no
    clock, and when grace closes they leave. Nothing about any of
    them changed in the house.
    """
    records = _fleet_records(path)
    heard: list[dict] = []
    hass.bus.async_listen(EVENT_RECOVERED, lambda e: heard.append(e.data))

    # The leavers as they really are on both fleets: a registry
    # device with no entity of any kind, owned by an integration that
    # has not finished loading, inside the startup window. That is
    # the ZHA coordinator at every restart, and Tim's eight.
    owner = MockConfigEntry(domain="leaver_stack", title="Leaver Stack")
    owner.add_to_hass(hass)
    registry = dr.async_get(hass)
    devices = []
    for index in range(leavers):
        devices.append(
            registry.async_get_or_create(
                config_entry_id=owner.entry_id,
                identifiers={("leaver_stack", f"{fleet}-{index}")},
                name=f"{fleet.title()} Leaver {index}",
            )
        )
    coord = await setup_coordinator(hass)
    # Inside the startup window, which is what watches them.
    coord._grace_until = dt_util.utcnow().timestamp() + 300.0
    coord._rebuild_registry_view()
    watched_leavers = [d.id for d in devices if d.id in coord._watched]
    assert watched_leavers, (
        "the simulation is not reproducing the condition: no "
        "entity-less device was watched during grace"
    )

    # Seed the fleet's own records so the run carries real history.
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        coord.data[DATA_DEVICES].setdefault(f"{fleet}_bg{index}", dict(record))

    # The leavers: watched, no entities, no clock, so never reported.
    for device in devices:
        record = coord.data[DATA_DEVICES].setdefault(device.id, {})
        record[DEV_EVENT_COUNT] = 0
        record[DEV_LAST_ACTIVITY] = None
        record[DEV_FIRST_OBSERVED] = OBSERVED
        record[DEV_FROZEN_CATEGORY] = None
        record[DEV_FROZEN_SINCE] = None

    coord._judge_all_devices()
    coord._sync_problem_list()
    raised = [
        item
        for item in coord.data.get("todo_items", [])
        if item["device_id"] in {d.id for d in devices}
    ]

    # Grace closes. The leavers go, nothing else about them changes.
    for device in devices:
        coord._watched.pop(device.id, None)
    coord._sync_problem_list()
    await hass.async_block_till_done()

    mine = [
        h for h in heard if h.get("device_id") in {d.id for d in devices}
    ]
    return {
        "fleet": fleet,
        "records": len(records),
        "items_raised": len(raised),
        "false_recoveries": len(mine),
        "durations": [h.get("down_for") for h in mine],
    }


@pytest.mark.skipif(not JAMES.exists(), reason="fleet file absent")
async def test_simulate_james_fleet_restart(hass: HomeAssistant) -> None:
    result = await _run_restart_cycle(hass, "james", JAMES, JAMES_LEAVERS)
    print("JAMES:", result)
    assert result["false_recoveries"] == 0, (
        f"{result['false_recoveries']} device(s) announced a recovery "
        "they never had"
    )
    assert result["items_raised"] == 0, (
        f"{result['items_raised']} device(s) with no entity to report "
        "with were put on the list and notified about"
    )


@pytest.mark.skipif(not TIM.exists(), reason="fleet file absent")
async def test_simulate_tim_fleet_restart(hass: HomeAssistant) -> None:
    result = await _run_restart_cycle(hass, "tim", TIM, TIM_LEAVERS)
    print("TIM:", result)
    assert result["false_recoveries"] == 0, (
        f"{result['false_recoveries']} device(s) announced a recovery "
        "they never had"
    )
    assert result["items_raised"] == 0, (
        f"{result['items_raised']} device(s) with no entity to report "
        "with were put on the list and notified about"
    )


async def test_a_real_recovery_still_announces(hass: HomeAssistant) -> None:
    """The other half, and the one that must not be broken by any
    fix: a device whose problem genuinely ends still says so."""
    heard: list[dict] = []
    hass.bus.async_listen(EVENT_RECOVERED, lambda e: heard.append(e.data))
    device, _eids = register_device(hass, "real_recovery")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES].setdefault(device.id, {})
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_FIRST_OBSERVED] = OBSERVED
    coord._judge_all_devices()
    coord._sync_problem_list()

    # The device speaks. It stays watched throughout.
    record[DEV_EVENT_COUNT] = 1
    record[DEV_LAST_ACTIVITY] = 1_788_000_000.0
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    coord._judge_all_devices()
    coord._sync_problem_list()
    await hass.async_block_till_done()

    mine = [h for h in heard if h.get("device_id") == device.id]
    print("REAL RECOVERY EVENTS:", len(mine), [h.get("down_for") for h in mine])
    assert mine, "a device that genuinely recovered said nothing"


async def test_a_device_that_leaves_records_why_it_left(
    hass: HomeAssistant,
):
    """Silent is not the same as unrecorded. The timeline must say
    the device was set aside, and must not say it resolved."""
    from custom_components.device_sentinel.const import (
        ACTION_SET_ASIDE,
        INCIDENT_RESOLVED,
    )

    device, _eids = register_device(hass, "records_why")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES].setdefault(device.id, {})
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_FIRST_OBSERVED] = OBSERVED
    coord._judge_all_devices()
    coord._sync_problem_list()

    coord._watched.pop(device.id, None)
    coord._sync_problem_list()
    await hass.async_block_till_done()

    rows = [
        row
        for row in coord.data.get("incidents", [])
        if row.get("device_id") == device.id
    ]
    events = [row.get("event") for row in rows]
    causes = [row.get("cause") for row in rows]
    print("INCIDENT EVENTS:", events, "CAUSES:", causes)
    assert INCIDENT_RESOLVED not in events, (
        "the timeline claims the problem ended"
    )
    assert ACTION_SET_ASIDE in causes, (
        "the timeline does not say why the device left"
    )


async def test_a_problem_clearing_while_watched_still_announces(
    hass: HomeAssistant,
):
    """The fix keys on the watched set, so a device that is watched
    throughout must be unaffected however its problem ends."""
    heard: list[dict] = []
    hass.bus.async_listen(EVENT_RECOVERED, lambda e: heard.append(e.data))
    device, _eids = register_device(hass, "still_watched")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES].setdefault(device.id, {})
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_FIRST_OBSERVED] = OBSERVED
    coord._judge_all_devices()
    coord._sync_problem_list()
    assert device.id in coord._watched

    record[DEV_EVENT_COUNT] = 5
    record[DEV_LAST_ACTIVITY] = 1_788_000_000.0
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    coord._judge_all_devices()
    coord._sync_problem_list()
    await hass.async_block_till_done()

    mine = [h for h in heard if h.get("device_id") == device.id]
    print("WATCHED-THROUGHOUT RECOVERIES:", len(mine))
    assert mine, "a watched device's recovery was silenced"


async def test_a_device_that_leaves_and_returns_starts_a_new_incident(
    hass: HomeAssistant,
):
    """The next restart must open a fresh problem rather than
    reopening the old one, so nothing is dated to the last cycle."""
    device, _eids = register_device(hass, "leaves_returns")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES].setdefault(device.id, {})
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_FIRST_OBSERVED] = OBSERVED
    coord._judge_all_devices()
    coord._sync_problem_list()
    first = [
        i for i in coord.data["todo_items"] if i["device_id"] == device.id
    ][0]
    first_stamp = list(first["kinds"].values())[0]

    coord._watched.pop(device.id, None)
    coord._clear_verdicts_for_set_aside({device.id: ("n", "zha", "x")})
    coord._sync_problem_list()

    coord._watched[device.id] = "zha"
    coord._judge_all_devices()
    coord._sync_problem_list()
    second = [
        i for i in coord.data["todo_items"] if i["device_id"] == device.id
    ][0]
    second_stamp = list(second["kinds"].values())[0]
    print("STAMPS:", first_stamp, second_stamp)
    assert second_stamp >= first_stamp, "the new item is dated backwards"


async def test_a_device_whose_entities_are_all_disabled_still_qualifies(
    hass: HomeAssistant,
):
    """The case the fix must not silence.

    A device whose entities exist but are switched off is not the
    same as a device with none. Those entities can be switched on,
    and the never-reported row is the prompt to do it, so it keeps
    its verdict (ruling #257 and #369).
    """
    from homeassistant.helpers import entity_registry as er

    from custom_components.device_sentinel.const import (
        FREEZE_CATEGORY_NEVER_REPORTED,
    )

    owner = MockConfigEntry(domain="disabled_stack", title="Disabled")
    owner.add_to_hass(hass)
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("disabled_stack", "all-off")},
        name="Every Entity Disabled",
    )
    entities = er.async_get(hass)
    entities.async_get_or_create(
        "sensor",
        "disabled_stack",
        "off-uid",
        device_id=device.id,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()

    record = coord.data[DATA_DEVICES].setdefault(device.id, {})
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_FIRST_OBSERVED] = OBSERVED

    verdict = coord._device_down_category(
        device.id, record, 1_788_600_000.0
    )
    print("DISABLED-ENTITY VERDICT:", verdict)
    assert verdict == FREEZE_CATEGORY_NEVER_REPORTED, (
        "a device whose entities are merely switched off lost its "
        "prompt to switch them on"
    )


async def test_an_ordinary_silent_device_still_qualifies(
    hass: HomeAssistant,
):
    """The everyday case: a real device with real entities that has
    genuinely never spoken must still be reported."""
    from custom_components.device_sentinel.const import (
        FREEZE_CATEGORY_NEVER_REPORTED,
    )

    device, _eids = register_device(hass, "ordinary_silent")
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    record = coord.data[DATA_DEVICES].setdefault(device.id, {})
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_FIRST_OBSERVED] = OBSERVED
    verdict = coord._device_down_category(
        device.id, record, 1_788_600_000.0
    )
    print("ORDINARY SILENT VERDICT:", verdict)
    assert verdict == FREEZE_CATEGORY_NEVER_REPORTED, (
        "a real device that has never reported was silenced"
    )


async def test_a_set_aside_fires_a_withdrawal_not_a_recovery(
    hass: HomeAssistant,
):
    """#289 promised every fault an answer; #368 silenced the
    recovery for a device that never came back; #370 answers with a
    withdrawal instead. Exactly one, carrying the kinds and why."""
    from custom_components.device_sentinel.const import EVENT_WITHDRAWN

    withdrawn: list[dict] = []
    recovered: list[dict] = []
    hass.bus.async_listen(EVENT_WITHDRAWN, lambda e: withdrawn.append(e.data))
    hass.bus.async_listen(EVENT_RECOVERED, lambda e: recovered.append(e.data))
    device, _ = register_device(hass, "withdraw_dev")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    rec = coord.data[DATA_DEVICES].setdefault(device.id, {})
    rec[DEV_EVENT_COUNT] = 0
    rec[DEV_LAST_ACTIVITY] = None
    rec[DEV_FIRST_OBSERVED] = OBSERVED
    coord._judge_all_devices()
    coord._sync_problem_list()
    await hass.async_block_till_done()
    coord._watched.pop(device.id, None)
    coord._sync_problem_list()
    await hass.async_block_till_done()
    mine = [w for w in withdrawn if w.get("device_id") == device.id]
    assert len(mine) == 1, f"{len(mine)} withdrawals"
    assert mine[0]["reason"] == "set_aside"
    assert "never_reported" in mine[0]["kinds"]
    assert not [r for r in recovered if r.get("device_id") == device.id]
