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
import os
import random
import re
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    ACTION_SET_ASIDE,
    CLOCK_FIELDS,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DATA_INCIDENTS,
    TODO_KIND_UNAVAILABLE,
    SYS_WHEN,
    SYS_SCOPE,
    SYS_RESTART,
    SYS_KIND,
    SYS_DURATION,
    SYS_BRIDGE_UP,
    SYS_BRIDGE_DOWN,
    INC_WHEN,
    INC_NAME,
    INC_KIND,
    INC_EVENT,
    INC_DURATION,
    INC_DEVICE_ID,
    DEV_SIGNAL_DAILY_P5,
    DEV_BATTERY_VALUE,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_LOW,
    DEV_BATTERY_DAILY,
    REPORT_WWW_DIR,
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
# The newest copy of each fleet, for the forward simulation below. The
# dated pair above is the campaign's fixed ground; these move.
JAMES_LIVE = fleet_path("james", "device_sentinel.storage")
TIM_LIVE = fleet_path("tim", "device_sentinel_storage.json")
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


# Forward simulation: both real fleets through the current readers.
#
# The campaign above drives synthetic rounds. This drives the real
# thing: each reference fleet's own storage loaded into a live
# coordinator, every device registered, every report written and read
# back. A replay over existing data proves what wrote it; only
# rendering the whole output surface proves what reads it (#306).


def _fleet_names(path):
    """Return the device names, which the storage file does not carry.

    The record holds statistics and no name. The name lives in the
    registry, and the diagnostics dump beside the fleet file is the
    only copy of that registry available here.
    """
    found = sorted(path.parent.glob("config_entry*.json"))
    if not found:
        return {}
    with open(found[0], encoding="utf-8") as handle:
        dump = json.load(handle)
    devices = (dump.get("data") or {}).get("devices") or {}
    return {
        device_id: (record or {}).get("name") or device_id
        for device_id, record in devices.items()
    }


async def _render_fleet(hass, path):
    """Load a fleet, write every report, return the pages by name."""
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    data = loaded.get("data", loaded)
    records = data.get("devices") or {}
    names = _fleet_names(path)

    source = MockConfigEntry(domain="test", title="Fleet")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    for device_id in records:
        device = registry.async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("test", device_id)},
            name=names.get(device_id) or device_id,
        )
        entities.async_get_or_create(
            "sensor", "test", device_id,
            device_id=device.id, config_entry=source,
        )

    coord = await setup_coordinator(hass)
    # The registry ids the harness mints are not the fleet's, so each
    # record is keyed onto the device planted under the fleet's own id.
    live_for = {
        ident: device.id
        for device in registry.devices.values()
        for domain, ident in device.identifiers
        if domain == "test"
    }
    carried = 0
    for device_id, record in records.items():
        live = live_for.get(device_id)
        if live is None or not isinstance(record, dict):
            continue
        coord.data[DATA_DEVICES][live] = dict(record)
        carried += 1
    for key in ("system_events", "incidents", "storm_days",
                "silence_episodes"):
        coord.data[key] = data.get(key) or []
    coord._rebuild_registry_view()

    await hass.async_add_executor_job(coord._write_reports, "manual")
    directory = hass.config.path(REPORT_WWW_DIR)
    pages = {}
    for name in os.listdir(directory):
        if name.endswith((".html", ".md")):
            with open(
                os.path.join(directory, name), encoding="utf-8"
            ) as handle:
                pages[name] = handle.read()
    return carried, pages


def _agree(page, heading, stop, pattern, pairs=False):
    """Assert a section shows as many devices as it claims.

    Rulings #379 and #380 put the count and the list in one source.
    This is that promise checked against real data rather than a
    fixture.
    """
    if heading not in page:
        return
    block = page[page.index(heading):]
    if stop in block:
        block = block[: block.index(stop)]
    found = re.search(pattern, block)
    if found is None:
        return
    counted = int(found.group(1))
    rows = re.findall(r"<tr><td>.*?</tr>", block)
    step = 2 if pairs else 1
    shown = sum(
        1
        for row in rows
        for cell in re.findall(r"<td>(.*?)</td>", row)[::step]
        if cell.strip()
    )
    assert shown == counted, (heading, counted, shown)


def _check_pages(pages):
    """Every page renders, agrees with itself, and names no raw id."""
    for name in ("daily_brief.html", "battery_report.html",
                 "signal_report.html"):
        assert name in pages, name

    battery = pages["battery_report.html"]
    _agree(battery, "<h2>Steady</h2>", "<h2>Unreadable</h2>",
           r"(\d+) cell\(s\) holding steady", pairs=True)
    _agree(battery, "<h2>No Battery Reported</h2>", "<footer>",
           r"(\d+) watched device\(s\)")
    _agree(pages["signal_report.html"], "<h2>Steady Signals</h2>",
           "<h2>Devices That Had a Bad Day",
           r"(\d+) device\(s\) stayed within")

    # A registry id in reader-facing text is the fault #307 found on
    # the first live trim: a name lookup that missed and printed the
    # id at a person.
    for name, page in pages.items():
        body = re.sub(r"<svg.*?</svg>", "", page, flags=re.S)
        assert not re.findall(r">\s*[0-9a-f]{32}\s*<", body), name


@pytest.mark.skipif(not JAMES_LIVE.exists(), reason=FLEET_ABSENT)
async def test_the_reference_fleet_renders_every_page(
    hass: HomeAssistant,
):
    """The whole output surface, over the first fleet's own record."""
    carried, pages = await _render_fleet(hass, JAMES_LIVE)
    assert carried > 90, carried
    _check_pages(pages)


@pytest.mark.skipif(not TIM_LIVE.exists(), reason=FLEET_ABSENT)
async def test_the_second_fleet_renders_every_page(
    hass: HomeAssistant,
):
    """The same, on a fleet twice the size and differently shaped."""
    carried, pages = await _render_fleet(hass, TIM_LIVE)
    assert carried > 200, carried
    _check_pages(pages)


async def test_the_worst_night_a_fleet_could_have(hass: HomeAssistant):
    """Everything at once, on a fleet with two stacks.

    Restarts, a bridge outage, freezes, a bank at the floor, signal
    falls, and one device nobody can explain. The single question is
    whether every page still writes and every count still matches the
    list beside it when nothing is quiet.
    """
    source = MockConfigEntry(domain="mqtt", title="Zigbee")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    entities = er.async_get(hass)

    def plant(count, prefix, domain, entry):
        made = []
        for index in range(count):
            uid = f"{prefix}{index}"
            device = registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(domain, uid)},
                name=f"{prefix.upper()} {index}",
            )
            entities.async_get_or_create(
                "sensor", domain, uid,
                device_id=device.id, config_entry=entry,
            )
            made.append(device)
        return made

    zha_entry = MockConfigEntry(domain="zha", title="Radio")
    zha_entry.add_to_hass(hass)
    zigbee = plant(60, "zb", "mqtt", source)
    zha = plant(25, "zh", "zha", zha_entry)

    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    now = dt_util.utcnow().timestamp()

    coord.data[DATA_SYSTEM_EVENTS] = [
        {SYS_WHEN: now - 70000.0, SYS_KIND: SYS_RESTART,
         SYS_SCOPE: "system", SYS_DURATION: 900.0},
        {SYS_WHEN: now - 60000.0, SYS_KIND: SYS_BRIDGE_DOWN,
         SYS_SCOPE: "z2m"},
        {SYS_WHEN: now - 58000.0, SYS_KIND: SYS_BRIDGE_UP,
         SYS_SCOPE: "z2m", SYS_DURATION: 2000.0},
        {SYS_WHEN: now - 3600.0, SYS_KIND: SYS_RESTART,
         SYS_SCOPE: "system", SYS_DURATION: 30.0},
    ]

    def incident(device, when, event=INCIDENT_OPENED, duration=None):
        return {
            INC_DEVICE_ID: device.id,
            INC_NAME: device.name,
            INC_KIND: TODO_KIND_UNAVAILABLE,
            INC_EVENT: event,
            INC_WHEN: when,
            INC_DURATION: duration,
        }

    incidents = []
    for device in zigbee[:40]:
        incidents.append(incident(device, now - 59900.0))
        incidents.append(
            incident(device, now - 57900.0, INCIDENT_RESOLVED, 2000.0)
        )
    # One device nobody can explain, four times, hours from any event.
    rogue = zha[0]
    for index in range(4):
        incidents.append(
            incident(rogue, now - 400000.0 + index * 90000.0)
        )
    coord.data[DATA_INCIDENTS] = incidents

    for index, device in enumerate(zigbee):
        record = coord.data[DATA_DEVICES][device.id]
        level = float(5 + index)
        record[DEV_BATTERY_VALUE] = level
        record[DEV_BATTERY_DAILY] = [
            level + step for step in range(9, -1, -1)
        ]
        if level <= 10.0:
            record[DEV_BATTERY_LOW] = True
            record[DEV_BATTERY_SINCE] = "2026-08-28T06:00:00+00:00"
        record[DEV_SIGNAL_DAILY_P5] = (
            [165.0] * 9 + [95.0] + [163.0] * 4
            if index % 3 == 0
            else [165.0] * 14
        )
    coord._sync_problem_list()

    await hass.async_add_executor_job(coord._write_reports, "manual")
    directory = hass.config.path(REPORT_WWW_DIR)
    pages = {}
    for name in os.listdir(directory):
        if name.endswith((".html", ".md")):
            with open(
                os.path.join(directory, name), encoding="utf-8"
            ) as handle:
                pages[name] = handle.read()

    _check_pages(pages)

    # The one unexplained device is named, and only it.
    brief = pages["daily_brief.html"]
    assert "<h2>Repeat Offenders</h2>" in brief
    block = brief[brief.index("<h2>Repeat Offenders</h2>"):]
    block = block[: block.index("<h2>", 30)]
    rows = re.findall(r"<tr><td>.*?</tr>", block)
    assert len(rows) == 1, len(rows)
    assert rogue.name in rows[0]
