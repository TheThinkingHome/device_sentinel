# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_outage_pairs_and_counts.py, Version: 0.27.10 (2026-10-27)

"""Upstream outages: every down owes its restored, with one count
(rule UP-10).

Each config entry's outage gets its own down and restored pair, with
the device count the down was announced with. A one-device entry speaks
of that device, the broker counts only the devices that ride it, and a
device muted for unavailable is still counted. An outage still down
across a restart is owed its restored, inside the startup grace too; an
entry deleted while down is closed as removed, and an integration no
longer watched is closed as such, never as removed.
"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIDGE_RUNNING,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_FROZEN_CATEGORY,
    STACK_Z2M,
)

from custom_components.device_sentinel.interventions import BROKER_LABEL

from .helpers import record_events, register_device, setup_coordinator
from .outage_helpers import PIN, arm, entry_of, past_grace, restart, tick, walk
from .test_bridge_pairing import _Stub


# --------------------------------- the device count behind an upstream


# The device count reads the same on every upstream (rule UP-10).


async def test_a_bridge_counts_devices_muted_for_unavailable(hass: HomeAssistant):
    from tests.helpers import register_device, setup_coordinator

    one, _ = register_device(hass, "cm1", "Counted One")
    two, _ = register_device(hass, "cm2", "Counted Two")
    coord = await setup_coordinator(hass)
    for device_id in (one.id, two.id):
        coord._watched[device_id] = "mqtt"
    coord._stack_for_device = lambda device_id: "z2m"
    coord._unavailable_muted = lambda device_id: device_id == two.id
    assert coord._upstream_devices("z2m") == 2
    assert coord._upstream_devices(None) == 2


async def test_an_integration_counts_devices_muted_for_unavailable(hass: HomeAssistant):
    from tests.helpers import register_device, setup_coordinator

    one, _ = register_device(hass, "ci1", "Counted One")
    two, _ = register_device(hass, "ci2", "Counted Two")
    coord = await setup_coordinator(hass)
    for device_id in (one.id, two.id):
        coord._watched[device_id] = "shelly"
    coord._unavailable_muted = lambda device_id: device_id == two.id
    coord._entry_only_device = {}
    assert coord.upstream_membership("shelly") == 2
    # An entry that carries only the muted device is that device.
    coord._entry_only_device = {"e2": two.id}
    assert coord.upstream_membership("shelly") == 1


MUTE = None


try:
    from custom_components.device_sentinel.const import CONF_UNAVAILABLE_MUTED_DEVICES as MUTE
except ImportError:
    pass


def _one(hass, uid, domain="shelly"):
    source = MockConfigEntry(domain=domain, title=f"{domain} {uid}")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    reg = er.async_get(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, uid)}, name=f"Plug {uid}")
    main = reg.async_get_or_create("switch", domain, f"{uid}_main", device_id=device.id, config_entry=source).entity_id
    pw = reg.async_get_or_create("sensor", domain, f"{uid}_pw", device_id=device.id, config_entry=source).entity_id
    return source, device, (main, pw)


@pytest.mark.parametrize("mute_other", [False, True])
async def test_single_entry(hass: HomeAssistant, freezer, mute_other):
    freezer.move_to(PIN)
    plugs = [_one(hass, f"p{i}") for i in range(5)]
    for _, _, ids in plugs:
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    opts = {MUTE: [plugs[4][1].id]} if (mute_other and MUTE) else None
    coord = await setup_coordinator(hass, opts)
    recs = [arm(coord, d.id, rhythm=600.0) for _, d, _ in plugs]
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    for k in range(6):
        for _, _, ids in plugs:
            hass.states.async_set(ids[1], str(10 + k))
        await walk(hass, freezer, 600)
    src, dev, ids = plugs[0]
    src.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    for eid in ids:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    for k in range(60):
        for _, _, i2 in plugs[1:]:
            hass.states.async_set(i2[1], str(20 + k))
        await walk(hass, freezer, 60)
    cat = recs[0][DEV_FROZEN_CATEGORY]
    items = [(i.get("device_id"), i.get("summary")) for i in coord.todo_items]
    src.mock_state(hass, ConfigEntryState.LOADED)
    hass.states.async_set(ids[0], "on")
    hass.states.async_set(ids[1], "11")
    await hass.async_block_till_done()
    await walk(hass, freezer, 40 * 60)
    sys = [r for r in coord.data.get(DATA_SYSTEM_EVENTS) or [] if r.get("scope") == "shelly"]
    said = [coord._system_event_sentence(r) for r in sys]
    info = dict(mute_other=mute_other, cat=cat, items=items, downs=list(downs), ups=list(ups), sys=sys, said=said,
                membership=coord.upstream_membership("shelly"))
    # The pair agrees, and the brief speaks of this plug alone.
    assert [d["devices"] for d in downs] == [1], info
    assert [u["devices"] for u in ups] == [1], info
    assert not any("of its 5" in x or "of its 4" in x or "1 device" in x for x in said), info
    assert said[-1].startswith("Plug p0 is back"), info


async def test_multi_entries(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    plugs = [_one(hass, f"p{i}") for i in range(4)]
    for _, _, ids in plugs:
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    coord = await setup_coordinator(hass)
    recs = [arm(coord, d.id, rhythm=600.0) for _, d, _ in plugs]
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    for k in range(6):
        for _, _, ids in plugs:
            hass.states.async_set(ids[1], str(10 + k))
        await walk(hass, freezer, 600)
    for src, dev, ids in plugs[:3]:
        src.mock_state(hass, ConfigEntryState.SETUP_RETRY)
        for eid in ids:
            hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 20 * 60)
    for n, (src, dev, ids) in enumerate(plugs[:3]):
        src.mock_state(hass, ConfigEntryState.LOADED)
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "11")
        await hass.async_block_till_done()
        await walk(hass, freezer, 10 * 60)
    await walk(hass, freezer, 30 * 60)
    sys = [r for r in coord.data.get(DATA_SYSTEM_EVENTS) or [] if r.get("scope") == "shelly"]
    said = [coord._system_event_sentence(r) for r in sys]
    info = dict(downs=list(downs), ups=list(ups), said=said, cats=[r[DEV_FROZEN_CATEGORY] for r in recs])
    assert len(downs) == len(ups), info


async def test_broker_count(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    made = {}
    for i, dom in enumerate(["mqtt", "mqtt", "mqtt", "zwave_js", "zwave_js", "zha"]):
        d, _ = register_device(hass, f"b{i}", f"Dev {i}")
        coord._watched[d.id] = dom
        made[d.id] = dom
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    coord._bridge_readers["zwave_js"] = _Stub(BRIDGE_RUNNING)
    coord._bridge_readers["zha"] = _Stub(BRIDGE_RUNNING)
    rides = sum(1 for d in made if coord._rides_the_broker(d))
    count = coord.upstream_membership(BROKER_LABEL)
    assert count == rides, (count, rides)


# -------------------------- every down owes a restored, entry by entry


DOM = "acme"


def _entry(hass, uid, n):
    source = MockConfigEntry(domain=DOM, title=f"hub {uid}")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    reg = er.async_get(hass)
    out = []
    for i in range(n):
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id, identifiers={(DOM, f"{uid}{i}")}, name=f"Dev {uid}{i}")
        main = reg.async_get_or_create("switch", DOM, f"{uid}{i}_m", device_id=device.id, config_entry=source).entity_id
        pw = reg.async_get_or_create("sensor", DOM, f"{uid}{i}_p", device_id=device.id, config_entry=source).entity_id
        out.append((device, (main, pw)))
    return source, out


def _all(entries):
    return [x for _, devs in entries for x in devs]


async def _warm(hass, freezer, entries, k0=0):
    for k in range(6):
        for _, ids in _all(entries):
            hass.states.async_set(ids[1], str(10 + k0 + k))
        await walk(hass, freezer, 600)


def _down(hass, src, devs):
    src.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    for _, ids in devs:
        for e in ids:
            hass.states.async_set(e, "unavailable")


def _up(hass, src, devs):
    src.mock_state(hass, ConfigEntryState.LOADED)
    for _, ids in devs:
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "11")


async def test_two_multi_entries_overlap(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    a = _entry(hass, "a", 3)
    b = _entry(hass, "b", 2)
    for _, ids in _all([a, b]):
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    coord = await setup_coordinator(hass)
    for d, _ in _all([a, b]):
        arm(coord, d.id, rhythm=600.0)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await _warm(hass, freezer, [a, b])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    _down(hass, *b)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    rows_mid = [i.get("summary") for i in coord.todo_items]
    _up(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    _up(hass, *b)
    await hass.async_block_till_done()
    await walk(hass, freezer, 40 * 60)
    sys = [r for r in coord.data.get(DATA_SYSTEM_EVENTS) or [] if r.get("scope") == DOM]
    said = [coord._system_event_sentence(r) for r in sys]
    info = dict(downs=list(downs), ups=list(ups), said=said, rows_mid=rows_mid,
                sys=[(r.get("kind"), r.get("devices"), r.get("worst")) for r in sys])
    assert [d["devices"] for d in downs] == [3, 2], info
    assert [u["devices"] for u in ups] == [3, 2], info
    ups_rows = [r for r in sys if r.get("kind") == "integration_up"]
    assert ups_rows[0]["devices"] == 3 and ups_rows[0]["worst"] <= 3, info
    assert ups_rows[1]["devices"] == 2 and ups_rows[1]["worst"] <= 2, info


async def test_restart_while_down_pairs(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    a = _entry(hass, "a", 3)
    for _, ids in _all([a]):
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    coord = await setup_coordinator(hass)
    for d, _ in _all([a]):
        arm(coord, d.id, rhythm=600.0)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    n_before = len(downs)
    coord = await restart(hass, freezer, down=120)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 10 * 60)
    _up(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 40 * 60)
    sys = [r for r in coord.data.get(DATA_SYSTEM_EVENTS) or [] if r.get("scope") == DOM]
    info = dict(n_before=n_before, downs=list(downs), ups=list(ups),
                sys=[(r.get("kind"), r.get("devices"), r.get("worst")) for r in sys],
                said=[coord._system_event_sentence(r) for r in sys])
    assert n_before == 1, info
    assert len(ups) == 1, info


async def test_entry_removed_while_down(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    a = _entry(hass, "a", 3)
    b = _entry(hass, "b", 2)
    for _, ids in _all([a, b]):
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    coord = await setup_coordinator(hass)
    for d, _ in _all([a, b]):
        arm(coord, d.id, rhythm=600.0)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await _warm(hass, freezer, [a, b])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    await hass.config_entries.async_remove(a[0].entry_id)
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    # later the sibling entry has an outage and recovers
    _down(hass, *b)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    _up(hass, *b)
    await hass.async_block_till_done()
    await walk(hass, freezer, 40 * 60)
    outages = coord.integration_outages().get(DOM)
    info = dict(downs=list(downs), ups=list(ups), said=dict(coord._upstream_said),
                outages=outages, since=coord.upstream_down_since_for(DOM),
                rows=[i.get("summary") for i in coord.todo_items])
    assert len(ups) == len(downs), info
    assert not any(o["open"] for o in outages or []), info


async def test_shared_worst_and_row(hass: HomeAssistant, freezer):
    """B's device frozen before either outage; A and B down together; A back first."""
    freezer.move_to(PIN)
    a = _entry(hass, "a", 3)
    b = _entry(hass, "b", 2)
    for _, ids in _all([a, b]):
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    coord = await setup_coordinator(hass)
    for d, _ in _all([a, b]):
        arm(coord, d.id, rhythm=600.0)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    live = [x for x in _all([a, b]) if x[0].id != b[1][0][0].id]
    for k in range(12):
        for _, ids in live:
            hass.states.async_set(ids[1], str(10 + k))
        await walk(hass, freezer, 600)
    r0 = coord.data["devices"][b[1][0][0].id]
    for e in b[1][0][1]:
        hass.states.async_set(e, "unavailable")
    await hass.async_block_till_done()
    for k in range(20):
        for _, ids in live:
            hass.states.async_set(ids[1], str(50 + k))
        await walk(hass, freezer, 60)
    pre = r0.get("frozen_category")
    _down(hass, *b)
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    rows_mid = [i.get("summary") for i in coord.todo_items]
    counts = dict(coord.suppressed_down_counts)
    _up(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    sys = [r for r in coord.data.get(DATA_SYSTEM_EVENTS) or [] if r.get("scope") == DOM]
    info = dict(pre=pre, counts=counts, rows_mid=rows_mid, downs=list(downs), ups=list(ups),
                sys=[(r.get("kind"), r.get("devices"), r.get("worst")) for r in sys],
                said=[coord._system_event_sentence(r) for r in sys])
    up_a = [r for r in sys if r.get("kind") == "integration_up"][0]
    # A's three devices went down with it; B's devices, the one frozen
    # before and the one down under B's own outage, are not A's. Devices
    # behind a down entry are counted, so this reads 3, not 0 (rule UP-11).
    assert up_a["worst"] == 3, info


async def test_grace_two_entries_held(hass: HomeAssistant, freezer):
    """Two entries of one domain fall inside the grace; one comes back inside it."""
    from .outage_helpers import tick
    freezer.move_to(PIN)
    a = _entry(hass, "a", 3)
    b = _entry(hass, "b", 2)
    c = _entry(hass, "c", 2)
    for _, ids in _all([a, b, c]):
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await tick(hass, freezer, step=30, n=2)
    _down(hass, *a)
    _down(hass, *b)
    _down(hass, *c)
    await hass.async_block_till_done()
    await tick(hass, freezer, step=30, n=4)
    held1 = dict(coord._upstream_held)
    _up(hass, *c)
    await hass.async_block_till_done()
    await tick(hass, freezer, step=30, n=3)
    held2 = dict(coord._upstream_held)
    await walk(hass, freezer, 6 * 60)
    mid = (list(downs), list(ups))
    _up(hass, *a)
    _up(hass, *b)
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    sys = [r for r in coord.data.get(DATA_SYSTEM_EVENTS) or [] if r.get("scope") == DOM]
    info = dict(held1=held1, held2=held2, mid=mid, downs=list(downs), ups=list(ups),
                sys=[(r.get("kind"), r.get("devices"), r.get("worst")) for r in sys])
    assert [d["devices"] for d in downs] == [3, 2] or [d["devices"] for d in downs] == [2, 3], info
    assert sorted(u["devices"] for u in ups) == [2, 3], info


async def test_worst_words_table(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    out = {}
    for kind, scope in [("bridge_up", "z2m"), ("broker_up", "mqtt"), ("wifi_up", "wifi"),
                        ("integration_up", "shelly")]:
        for total, worst in [(1, 0), (1, 1), (3, 0), (3, 2), (None, 0), (None, 2), (0, 0)]:
            row = {"kind": kind, "scope": scope, "when": 1760000000.0, "duration": 600.0, "worst": worst}
            if total is not None:
                row["devices"] = total
            try:
                out[(kind, total, worst)] = (coord._system_event_sentence(row), coord._system_event_phrase(row))
            except Exception as err:  # noqa: BLE001
                out[(kind, total, worst)] = ("ERR", repr(err))
    bad = {k: v for k, v in out.items() if "ERR" in v[0] or "of its 0" in v[0] or "None of its 1" in v[0]}
    assert not bad, bad


async def test_broker_with_no_riders_brief(hass: HomeAssistant, freezer):
    """A house whose devices are all Z-Wave, with an MQTT broker watched."""
    from custom_components.device_sentinel.const import BRIDGE_RUNNING, BROKER_DOWN, BROKER_RUNNING, DATA_SYSTEM_EVENTS
    from .test_upstream_events_fleet import _broker_stub, _heard, _stub
    from .outage_helpers import past_grace
    coord = await setup_coordinator(hass)
    for i in range(4):
        d, _ = register_device(hass, f"z{i}", f"ZW {i}")
        coord._watched[d.id] = "zwave_js"
    await past_grace(hass, freezer)
    coord._bridge_readers["zwave_js"] = _stub(BRIDGE_RUNNING)
    _heard(hass)
    coord._broker_reader = _broker_stub(BROKER_RUNNING)
    coord._sample_bridges()
    coord._broker_reader = _broker_stub(BROKER_DOWN)
    coord._sample_bridges()
    freezer.tick(600)
    coord._broker_reader = _broker_stub(BROKER_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()
    rows = [r for r in coord.data.get(DATA_SYSTEM_EVENTS) or [] if r.get("kind") == "broker_up"]
    said = [coord._system_event_sentence(r) for r in rows]
    assert not any("of its 0" in s for s in said), said


# ------------- restored after a restart, removed, or no longer watched


def _riders(coord, hass, n=7):
    """Devices reaching HA through the MQTT broker (as Z2M devices do)."""
    for i in range(n):
        d, _ = register_device(hass, f"mq{i}", f"MQ {i}")
        coord._watched[d.id] = "mqtt"


async def _setup(hass, freezer, n=3):
    freezer.move_to(PIN)
    a = _entry(hass, "a", n)
    for _, ids in _all([a]):
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    coord = await setup_coordinator(hass)
    for d, _ in _all([a]):
        arm(coord, d.id, rhythm=600.0)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    return a, coord


def _sys(coord):
    return [r for r in coord.data.get(DATA_SYSTEM_EVENTS) or [] if r.get("scope") == DOM]


def _info(coord, downs, ups, **kw):
    sys = _sys(coord)
    return dict(downs=list(downs), ups=list(ups),
                sys=[(r.get("kind"), r.get("detail"), r.get("devices")) for r in sys],
                said=[coord._system_event_sentence(r) for r in sys],
                phrase=[coord._system_event_phrase(r) for r in sys],
                pending=dict(coord._upstream_said), **kw)


async def test_restart_then_removed_count(hass: HomeAssistant, freezer):
    """Down, announced; HA restarts; the entry is deleted afterwards."""
    a, coord = await _setup(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    coord = await restart(hass, freezer, down=120)
    _riders(coord, hass)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 5 * 60)
    await hass.config_entries.async_remove(a[0].entry_id)
    await hass.async_block_till_done()
    _riders(coord, hass)
    await walk(hass, freezer, 10 * 60)
    info = _info(coord, downs, ups)
    assert len(downs) == 1 and len(ups) == 1, info
    assert ups[0]["devices"] == downs[0]["devices"] == 3, info
    assert any("removed" in s for s in info["said"]), info


async def test_restart_then_back_count(hass: HomeAssistant, freezer):
    """Down, announced; restart; comes back. Count on the pair."""
    a, coord = await _setup(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    coord = await restart(hass, freezer, down=120)
    _riders(coord, hass)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 5 * 60)
    _up(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    info = _info(coord, downs, ups)
    assert len(ups) == 1 and ups[0]["devices"] == 3, info


async def test_removed_while_ha_off(hass: HomeAssistant, freezer):
    """Down, announced; Sentinel unloaded; entry deleted; Sentinel starts."""
    a, coord = await _setup(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    ds = entry_of(hass)
    assert await hass.config_entries.async_unload(ds.entry_id)
    await hass.async_block_till_done()
    await hass.config_entries.async_remove(a[0].entry_id)
    await hass.async_block_till_done()
    freezer.tick(120)
    assert await hass.config_entries.async_setup(ds.entry_id)
    await hass.async_block_till_done()
    coord = ds.runtime_data
    _riders(coord, hass)
    await walk(hass, freezer, 15 * 60)
    info = _info(coord, downs, ups)
    assert len(ups) == 1 and ups[0]["devices"] == 3, info
    assert any("removed" in s for s in info["said"]), info


async def test_removed_inside_grace(hass: HomeAssistant, freezer):
    """Entry falls and is deleted inside the startup grace."""
    from .outage_helpers import tick
    freezer.move_to(PIN)
    a = _entry(hass, "a", 3)
    for _, ids in _all([a]):
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    coord = await setup_coordinator(hass)
    await tick(hass, freezer, step=30, n=2)
    _down(hass, *a)
    await hass.async_block_till_done()
    await tick(hass, freezer, step=30, n=6)
    await hass.config_entries.async_remove(a[0].entry_id)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    info = _info(coord, downs, ups, held=dict(coord._upstream_held),
                 outages=coord.integration_outages().get(DOM))
    assert len(ups) == len(downs), info
    assert not any(o["open"] for o in info["outages"] or []), info


async def test_brief_and_attribution_after_removed(hass: HomeAssistant, freezer):
    a, coord = await _setup(hass, freezer)
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    await hass.config_entries.async_remove(a[0].entry_id)
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    errors = {}
    for name in ("integration_outages", "todo_items"):
        try:
            v = getattr(coord, name)
            v = v() if callable(v) else v
        except Exception as err:  # noqa: BLE001
            errors[name] = repr(err)
    for meth in ("build_brief", "brief_text", "daily_brief", "render_brief"):
        f = getattr(coord, meth, None)
        if f is not None:
            try:
                r = f()
                if hasattr(r, "__await__"):
                    await r
            except Exception as err:  # noqa: BLE001
                errors[meth] = repr(err)
    # restart after removed: nothing re-opens
    coord = await restart(hass, freezer, down=60)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 5 * 60)
    info = _info(coord, [], [], errors=errors, told=set(coord._integration_told),
                 down_at=dict(coord._entry_down_at))
    assert not errors, info
    assert not coord._integration_told and not coord._entry_down_at, info


async def test_back_inside_restart_grace(hass: HomeAssistant, freezer):
    """Down, announced; HA restarted; the integration loads at startup."""
    a, coord = await _setup(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    coord = await restart(hass, freezer, down=120, before_setup=lambda: _up(hass, *a))
    await past_grace(hass, freezer)
    await walk(hass, freezer, 30 * 60)
    info = _info(coord, downs, ups, outages=coord.integration_outages().get(DOM), grace=coord._grace_until)
    assert len(ups) == len(downs) == 1, info


async def test_back_late_in_grace(hass: HomeAssistant, freezer):
    """Down, announced; restart; loads 2 minutes into the grace."""
    from .outage_helpers import tick
    a, coord = await _setup(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    coord = await restart(hass, freezer, down=120)
    await tick(hass, freezer, step=60, n=2)
    _up(hass, *a)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    await walk(hass, freezer, 30 * 60)
    info = _info(coord, downs, ups, outages=coord.integration_outages().get(DOM), grace=coord._grace_until)
    assert len(ups) == len(downs) == 1, info


async def test_back_in_grace_walked(hass: HomeAssistant, freezer):
    """Down, announced; restart; loads at startup; minutes tick by one at a time."""
    a, coord = await _setup(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    coord = await restart(hass, freezer, down=120, before_setup=lambda: _up(hass, *a))
    await walk(hass, freezer, 30 * 60)
    info = _info(coord, downs, ups, outages=coord.integration_outages().get(DOM))
    assert len(ups) == len(downs) == 1, info


async def test_removed_after_restart_in_grace(hass: HomeAssistant, freezer):
    """Down, announced; restart; deleted two minutes later (inside the grace)."""
    a, coord = await _setup(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    coord = await restart(hass, freezer, down=120)
    await walk(hass, freezer, 120)
    await hass.config_entries.async_remove(a[0].entry_id)
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    info = _info(coord, downs, ups, outages=coord.integration_outages().get(DOM))
    assert len(ups) == len(downs) == 1, info


async def test_entities_deleted_while_down_not_removed(hass: HomeAssistant, freezer):
    """Devices set aside (no entities) while down: not removed."""
    a, coord = await _setup(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    reg = er.async_get(hass)
    for _, ids in a[1]:
        for e in ids:
            reg.async_remove(e)
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    a[0].mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, 30 * 60)
    info = _info(coord, downs, ups, outages=coord.integration_outages().get(DOM))
    assert not any("removed" in s for s in info["said"]), info
    # observe whether the pair closes at all
    assert len(ups) == len(downs), info


async def test_devices_excluded_while_down(hass: HomeAssistant, freezer):
    a, coord = await _setup(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    for d, _ in a[1]:
        entry_of(hass).runtime_data.page_set_excluded(d.id, True)
        await hass.async_block_till_done()
    coord = entry_of(hass).runtime_data
    await walk(hass, freezer, 10 * 60)
    _up(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    info = _info(coord, downs, ups, outages=coord.integration_outages().get(DOM))
    assert not any("removed" in s for s in info["said"]), info
    assert len(ups) == len(downs), info
    assert any("stopped watching" in s for s in info["said"]), info


async def test_integration_excluded_while_down(hass: HomeAssistant, freezer):
    a, coord = await _setup(hass, freezer)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    coord.page_set_integration_excluded(DOM, True)
    await hass.async_block_till_done()
    coord = entry_of(hass).runtime_data
    await walk(hass, freezer, 10 * 60)
    _up(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    info = _info(coord, downs, ups, outages=coord.integration_outages().get(DOM))
    assert not any("removed" in s for s in info["said"]), info
    assert len(ups) == len(downs), info


# ------------- a one-device entry, and an entry kept by a muted device


def _info_with_holds(coord, downs, ups, **kw):
    sys = _sys(coord)
    return dict(downs=list(downs), ups=list(ups),
                sys=[(r.get("kind"), r.get("detail"), r.get("devices")) for r in sys],
                said=[coord._system_event_sentence(r) for r in sys],
                told=set(coord._integration_told), down_at=dict(coord._entry_down_at),
                said_map=dict(coord._upstream_said), held=dict(coord._upstream_held), **kw)


async def _start(hass, freezer, n, options=None):
    freezer.move_to(PIN)
    a = _entry(hass, "a", n)
    for _, ids in _all([a]):
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    coord = await setup_coordinator(hass, options)
    for d, _ in _all([a]):
        arm(coord, d.id, rhythm=600.0)
    await hass.async_block_till_done()
    return a, coord


async def test_p2_two_devices_one_muted_other_excluded(hass: HomeAssistant, freezer):
    """Entry of two, one muted for unavailable (set once, long ago). Entry down,
    announced with 2. The unmuted device is excluded while down. The muted
    device is still watched and the entry still down."""
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    freezer.move_to(PIN)
    a = _entry(hass, "a", 2)
    muted = a[1][0][0].id
    for _, ids in _all([a]):
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    coord = await setup_coordinator(hass, {CONF_UNAVAILABLE_MUTED_DEVICES: [muted]})
    for d, _ in _all([a]):
        arm(coord, d.id, rhythm=600.0)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    n_down = len(downs)
    coord.page_set_excluded(a[1][1][0].id, True)
    await hass.async_block_till_done()
    coord = entry_of(hass).runtime_data
    await walk(hass, freezer, 10 * 60)
    still_watched = muted in coord._watched
    state = a[0].state
    info = _info_with_holds(coord, downs, ups, n_down=n_down, still_watched=still_watched, state=str(state))
    assert not ups, info  # still down, still watched through the muted device
    assert len(downs) == 1, info


    # The integration is still down and one of its devices still watched:


async def test_p3_two_devices_one_muted_other_deleted(hass: HomeAssistant, freezer):
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    freezer.move_to(PIN)
    a = _entry(hass, "a", 2)
    muted = a[1][0][0].id
    for _, ids in _all([a]):
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    coord = await setup_coordinator(hass, {CONF_UNAVAILABLE_MUTED_DEVICES: [muted]})
    for d, _ in _all([a]):
        arm(coord, d.id, rhythm=600.0)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    dr.async_get(hass).async_remove_device(a[1][1][0].id)
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    info = _info_with_holds(coord, downs, ups, still_watched=muted in coord._watched)
    assert not ups, info
    assert len(downs) == 1, info


async def test_p4_upgrade_row_from_0265_count(hass: HomeAssistant, freezer):
    """A down row from an older release (no devices) for an entry of 3 with
    one muted announced 2. Restored after the upgrade says 2, not 3."""
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    freezer.move_to(PIN)
    a = _entry(hass, "a", 3)
    muted = a[1][0][0].id
    for _, ids in _all([a]):
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    coord = await setup_coordinator(hass, {CONF_UNAVAILABLE_MUTED_DEVICES: [muted]})
    for d, _ in _all([a]):
        arm(coord, d.id, rhythm=600.0)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    # what an older release would have written: no devices on the row
    for r in _sys(coord):
        r.pop("devices", None)
    coord._dirty = True
    coord._critical = True
    coord = await restart(hass, freezer, down=120)
    await past_grace(hass, freezer)
    _up(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    info = _info_with_holds(coord, downs, ups)
    assert len(ups) == len(downs), info


async def test_p5_owed_then_unwatched_in_grace(hass: HomeAssistant, freezer):
    """Announced; restart; in the new grace the integration is excluded:
    one restored, inside grace, no second."""
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    a, coord = await _start(hass, freezer, 3)
    await past_grace(hass, freezer)
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    coord = await restart(hass, freezer, down=60)
    await tick(hass, freezer, step=30, n=2)
    coord.page_set_integration_excluded(DOM, True)
    await hass.async_block_till_done()
    coord = entry_of(hass).runtime_data
    await walk(hass, freezer, 10 * 60)
    coord.page_set_integration_excluded(DOM, False)
    await hass.async_block_till_done()
    coord = entry_of(hass).runtime_data
    await past_grace(hass, freezer)
    await walk(hass, freezer, 20 * 60)
    _up(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    info = _info_with_holds(coord, downs, ups)
    assert len(ups) == len(downs), info


async def test_p6_resume_with_down_row_count_zero_entry(hass: HomeAssistant, freezer):
    """Restart while down, and HA reloads the down integration during the new
    grace (NOT_LOADED -> SETUP_IN_PROGRESS -> SETUP_RETRY). Nothing closes."""
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    a, coord = await _start(hass, freezer, 3)
    await past_grace(hass, freezer)
    await _warm(hass, freezer, [a])
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)

    def flip():
        a[0].mock_state(hass, ConfigEntryState.NOT_LOADED)
    coord = await restart(hass, freezer, down=60, before_setup=flip)
    await tick(hass, freezer, step=60, n=2)
    a[0].mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    await tick(hass, freezer, step=60, n=1)
    a[0].mock_state(hass, ConfigEntryState.SETUP_RETRY)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 20 * 60)
    info = _info_with_holds(coord, downs, ups)
    assert len(ups) <= len(downs), info


async def _single(hass, freezer):
    """Two entries of one integration: a one-device entry and a three-device entry."""
    freezer.move_to(PIN)
    a = _entry(hass, "a", 1)
    b = _entry(hass, "b", 3)
    for _, ids in _all([a, b]):
        hass.states.async_set(ids[0], "on")
        hass.states.async_set(ids[1], "10")
    coord = await setup_coordinator(hass)
    for d, _ in _all([a, b]):
        arm(coord, d.id, rhythm=600.0)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    await _warm(hass, freezer, [a, b])
    return a, b, coord


async def test_p7_single_device_entry_excluded_wording(hass: HomeAssistant, freezer):
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    a, b, coord = await _single(hass, freezer)
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    said_down = [coord._system_event_sentence(r) for r in _sys(coord)]
    coord.page_set_excluded(a[1][0][0].id, True)
    await hass.async_block_till_done()
    coord = entry_of(hass).runtime_data
    await walk(hass, freezer, 10 * 60)
    outs = coord.integration_outages().get(DOM)
    info = _info_with_holds(coord, downs, ups, said_down=said_down, outages=outs,
                 phrase=[coord._system_event_phrase(r) for r in _sys(coord)])
    assert all("Dev a0" in line for line in info["said"]), info
    assert info["outages"][0]["what"] == "Dev a0 (acme connection)", info


async def test_p8_single_device_entry_deleted_wording(hass: HomeAssistant, freezer):
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    a, b, coord = await _single(hass, freezer)
    _down(hass, *a)
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    await hass.config_entries.async_remove(a[0].entry_id)
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    outs = coord.integration_outages().get(DOM)
    info = _info_with_holds(coord, downs, ups, outages=outs,
                 phrase=[coord._system_event_phrase(r) for r in _sys(coord)])
    assert all("Dev a0" in line for line in info["said"]), info
    assert info["outages"][0]["what"] == "Dev a0 (acme connection)", info
