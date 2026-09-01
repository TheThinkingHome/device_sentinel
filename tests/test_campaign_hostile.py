"""Pre-stable campaign: hostile inputs at the paths 0.19.7 touched.

The judge, the rebuild, the sync and the retire all read persisted
data, and persisted data can be anything a damaged file holds. Each
is driven here with mutated real records and with shapes no writer
produces: wrong types in every field, items with no kinds, incidents
with no event, registries with disabled and orphaned entities,
integrations in every config-entry state. The requirement is that
nothing raises and the invariants of the previous campaign still
hold on whatever survives.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.normalise import repair_tables

from custom_components.device_sentinel.const import (
    CLOCK_FIELDS,
    DATA_DEVICES,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
    FREEZE_CATEGORY_NEVER_REPORTED,
)

from tests.conftest import fleet_path
from tests.helpers import register_device, setup_coordinator

JAMES = fleet_path("james", "2026-08-29", "device_sentinel.storage")
TIM = fleet_path("tim", "2026-08-29", "device_sentinel_storage.json")
CLOCKS_FOR = {
    "device_sentinel.storage": "device_sentinel.clocks",
    "device_sentinel_storage.json": "device_sentinel_clocks.json",
}
POISONS = [None, "junk", [1, 2], {"x": 1}, True, -7, float("nan"), 4.1e18, ""]


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


# ------------------------------------------------------- the judge


@pytest.mark.parametrize("seed", range(30))
async def test_the_sweep_survives_hostile_records(hass: HomeAssistant, seed):
    """A hostile record in memory can only arrive through a load,
    and the load repairs what the check cannot vouch for
    (ruling #370). The repair is run here the way the gate runs it,
    then the sweep must finish on the repaired fleet, and a
    never-reported verdict must still only land on a device that
    owns an entity."""
    rng = random.Random(seed)
    records = _fleet(JAMES if seed % 2 else TIM) if JAMES.exists() else [{}]
    devices = [register_device(hass, f"j{seed}_{i}")[0] for i in range(6)]
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    for device in devices:
        record = dict(rng.choice(records))
        for field in rng.sample(list(record) or ["daily_max"], k=min(3, len(record) or 1)):
            record[field] = rng.choice(POISONS)
        if rng.random() < 0.4:
            record[DEV_EVENT_COUNT] = 0
            record[DEV_LAST_ACTIVITY] = None
            record[DEV_FIRST_OBSERVED] = rng.choice(
                ["2026-07-08T00:00:00+00:00", "yesterday", None, 7, ""]
            )
        coord.data[DATA_DEVICES][device.id] = record
    # Repaired the way the gate repairs at load (ruling #370):
    # non-records dropped, damaged fields reset to defaults.
    coord._repair_records()
    for _ in range(5):
        try:
            coord._judge_all_devices()
            coord._sync_problem_list()
            await hass.async_block_till_done()
        except (KeyError, TypeError, ValueError, AttributeError) as err:
            pytest.fail(f"the sweep raised on a hostile record: {err!r}")
    for device in devices:
        record = coord.data[DATA_DEVICES][device.id]
        if record.get("frozen_category") == FREEZE_CATEGORY_NEVER_REPORTED:
            assert device.id in coord._devices_with_entities


# ------------------------------------------------------ the rebuild


@pytest.mark.parametrize("seed", range(30))
async def test_the_rebuild_keeps_the_entity_set_honest(
    hass: HomeAssistant, seed
):
    """Random registries: devices with entities, disabled entities,
    none, and integrations in every state. The retained entity set
    must equal what the registry actually holds for watched devices."""
    rng = random.Random(seed)
    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    owners = []
    for i in range(3):
        entry = MockConfigEntry(domain=f"stack{seed}_{i}", title="S")
        entry.add_to_hass(hass)
        if rng.random() < 0.5:
            entry.mock_state(hass, ConfigEntryState.LOADED)
        owners.append(entry)
    expected: set[str] = set()
    made = []
    for i in range(rng.randint(3, 14)):
        owner = rng.choice(owners)
        device = registry.async_get_or_create(
            config_entry_id=owner.entry_id,
            identifiers={(owner.domain, f"d{seed}-{i}")},
            name=f"Device {seed} {i}",
        )
        made.append(device)
        count = rng.choice([0, 0, 1, 3])
        for n in range(count):
            entities.async_get_or_create(
                "sensor", owner.domain, f"u{seed}-{i}-{n}",
                device_id=device.id,
                disabled_by=(
                    er.RegistryEntryDisabler.USER if rng.random() < 0.3 else None
                ),
            )
        if count:
            expected.add(device.id)
    coord = await setup_coordinator(hass)
    coord._grace_until = (
        dt_util.utcnow().timestamp() + 300.0 if rng.random() < 0.5 else 0.0
    )
    coord._rebuild_registry_view()
    watched_made = {d.id for d in made if d.id in coord._watched}
    for did in watched_made:
        assert (did in coord._devices_with_entities) == (did in expected), (
            f"entity set wrong for {did}"
        )
    # Outside grace, a watched device with no entities is impossible.
    if coord._grace_until == 0.0:
        assert not (watched_made - expected), (
            "an entity-less device stayed watched outside grace"
        )


# -------------------------------------------- the sync and retire


@pytest.mark.parametrize("seed", range(40))
async def test_the_sync_survives_hostile_persisted_items(
    hass: HomeAssistant, seed
):
    rng = random.Random(seed)
    device, _ = register_device(hass, f"s{seed}")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    hostile_items = []
    for _ in range(rng.randint(1, 8)):
        item = {
            "uid": rng.choice(["a", None, 7, ""]),
            "device_id": rng.choice([device.id, "ghost", None, 7, ""]),
            "summary": rng.choice(["s", None, 7]),
            "description": rng.choice(["d", None]),
            "status": rng.choice(["needs_action", "completed", "junk", None, 7]),
            "acked_at": rng.choice([None, 1.0, "x"]),
            "sort_name": rng.choice(["n", None, 7]),
            "kinds": rng.choice(
                [{"never_reported": 1.0}, {}, None, "junk", 7,
                 {"frozen": None}, {7: 1.0}, {"never_reported": "x"}]
            ),
        }
        if rng.random() < 0.2:
            item = rng.choice(["not an item", 7, None, [1]])
        hostile_items.append(item)
    coord.data["todo_items"] = hostile_items
    hostile_incidents = []
    for _ in range(rng.randint(0, 10)):
        hostile_incidents.append(
            {
                "device_id": rng.choice([device.id, "ghost", None]),
                "name": rng.choice(["n", None, 7]),
                "kind": rng.choice(["never_reported", "frozen", None, 7]),
                "event": rng.choice(["opened", "resolved", "action", None, 7]),
                "when": rng.choice([1_788_000_000.0, None, "x", -1]),
                "cause": rng.choice([None, "set_aside", "readded", 7]),
                "duration": rng.choice([None, 30.0, "x"]),
            }
        )
    coord.data["incidents"] = hostile_incidents
    # The gate repairs a damaged table at the moment it is found
    # (ruling #370); hostile persisted rows arrive only through a
    # load, so the load-style repair runs before any consumer.
    repair_tables(coord.data)
    try:
        coord._judge_all_devices()
        coord._sync_problem_list()
        await hass.async_block_till_done()
        # And once more with the device gone, which is the retire.
        coord._watched.pop(device.id, None)
        coord._sync_problem_list()
        await hass.async_block_till_done()
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        pytest.fail(f"sync raised on hostile persisted rows: {err!r}")


# ----------------------- a damaged record against every surface

SENSOR_PROPERTIES = [
    "awaiting_enable_counts", "battery_falling_count", "battery_falling_list",
    "battery_low_count", "battery_low_list", "battery_tracked_count",
    "battery_tracked_list", "bridge_stacks",
    "broker_attributes", "broker_state", "classification_breakdown",
    "deviceless_count", "freeze_tracked_count", "freeze_tracked_list",
    "frozen_devices_count", "frozen_devices_list", "last_good_taken",
    "learning_buckets", "recording_depth", "set_aside_count",
    "signal_problem_count", "signal_problem_list",
    "signal_tracked", "signal_tracked_count", "signal_weak_count",
    "signal_weak_list", "storage_healthy", "storage_load_faulty",
    "todo_items", "watched_count",
]

HELD_POISONS = [
    ("daily_max", None), ("daily_max", "rotten"), ("daily_max", {"x": 1}),
    ("signal_daily_p5", "x"),
    ("battery_daily_value", None), ("signal_daily_count", -1),
    ("first_observed", 7),
]


@pytest.mark.parametrize("field,poison", HELD_POISONS)
async def test_a_damaged_record_is_repaired_at_load(
    hass: HomeAssistant, hass_storage, field, poison
):
    """The #370 rule through the real load path: a damaged record
    field is repaired at the gate, every surface then runs on the
    repaired fleet, and the field itself checks clean afterwards."""
    from custom_components.device_sentinel.const import STORAGE_KEY
    from custom_components.device_sentinel.normalise import check_records

    device, _ = register_device(hass, "held_surface")
    coord = await setup_coordinator(hass)
    entry = coord.entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    stored = hass_storage.get(STORAGE_KEY)
    stored["data"][DATA_DEVICES][device.id][field] = poison
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord2 = entry.runtime_data
    assert coord2.storage_load_faulty, f"{field}={poison!r} not repaired"
    assert not check_records(coord2.data[DATA_DEVICES]), (
        f"{field}={poison!r} still faulty after the gate"
    )
    # Either gate may be the one that answers, depending on the
    # field: gate 1 owns the container fields, gate 2 the rest
    # (ruling #371).
    assert coord2._repair_notice or coord2._container_notice, (
        "the repair raised no notice"
    )
    failures = []
    for name in SENSOR_PROPERTIES:
        try:
            value = getattr(coord2, name)
            if callable(value):
                value = value()
        except Exception as err:  # noqa: BLE001 - reporting every failure
            failures.append(f"{name}: {err!r}")
    for stack in coord2.bridge_stacks:
        try:
            coord2.bridge_state(stack)
        except Exception as err:  # noqa: BLE001
            failures.append(f"bridge_state({stack}): {err!r}")
    assert not failures, "\n".join(failures)
    written = await coord2.async_regenerate_reports()
    assert written, "reports did not render with a held record present"
