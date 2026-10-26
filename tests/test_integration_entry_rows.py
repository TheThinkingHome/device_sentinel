# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_integration_entry_rows.py, Version: 0.27.5 (2026-10-26)

"""An integration's row, count, phase and push when it has several
config entries (rules UP-05, UP-09, UP-10, UP-11).

The row stands for the entries of several devices that are down: it is
dated from the first of them to fall and counts their own devices. An
entry that is its only device's claims nothing and takes no part in the
row or the push. One entry back while another is still down moves no
phase, so nothing is pushed until the integration is over, and then the
over push goes, across restarts too, telling the integration's own
outage. An entry's size is decided when it falls.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIDGE_HANDBACK_SECONDS,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    INTEGRATION_DOWN_DWELL_SECONDS,
    SYS_INTEGRATION_DOWN,
    SYS_KIND,
    UPSTREAM_SETTLE_SECONDS,
)
from custom_components.device_sentinel.interventions import DATA_INTEGRATION_SEEN

from tests.helpers import record_events, setup_coordinator
from tests.outage_helpers import past_grace, restart, walk
from tests.test_upstream_push_across_restart import _record_pushes

DOMAIN = "tuya"


def _hub(hass, uid, devices=2):
    source = MockConfigEntry(domain=DOMAIN, title=f"Hub {uid}")
    source.add_to_hass(hass)
    made = []
    for index in range(devices):
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={(DOMAIN, f"{uid}{index}")},
            name=f"Node {uid}{index}",
        )
        er.async_get(hass).async_get_or_create(
            "sensor", DOMAIN, f"{uid}{index}", device_id=device.id, config_entry=source,
        )
        made.append(device)
    return source, made


def _watch(coord, devices):
    coord._rebuild_registry_view()
    for device in devices:
        coord._watched[device.id] = DOMAIN


def _down(coord, devices, when):
    for device in devices:
        record = coord.data[DATA_DEVICES].setdefault(device.id, {})
        record[DEV_FROZEN_CATEGORY] = "unavailable"
        record[DEV_FROZEN_SINCE] = when


def _seen(coord):
    return dict(coord.data.get(DATA_INTEGRATION_SEEN) or {})


async def _both_down_pushed(hass, freezer):
    a, da = _hub(hass, "a")
    b, db = _hub(hass, "b")
    coord = await setup_coordinator(hass)
    await past_grace(hass, freezer)
    _watch(coord, da + db)
    sent: list = []
    _record_pushes(coord, sent)
    now = dt_util.utcnow().timestamp()
    a.mock_state(hass, ConfigEntryState.LOADED)
    b.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now)
    a.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    b.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    _down(coord, da + db, now + 30)
    await walk(hass, freezer, UPSTREAM_SETTLE_SECONDS + 120)
    assert [(n, r) for n, r, _s in sent] == [(DOMAIN, False)], sent
    seen = _seen(coord)
    assert all(v.get("pushed") is True for v in seen.values()), seen
    return coord, a, da, b, db


async def test_both_down_pushed_restart_one_returns_then_other(hass: HomeAssistant, freezer):
    coord, a, da, b, db = await _both_down_pushed(hass, freezer)
    coord = await restart(hass, freezer, down=120)
    _watch(coord, da + db)
    sent: list = []
    _record_pushes(coord, sent)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    await past_grace(hass, freezer)
    await walk(hass, freezer, 180)
    assert sent == []
    a.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, BRIDGE_HANDBACK_SECONDS + 240)
    # One entry back while the other is down: nothing is pushed.
    assert sent == [], sent
    b.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, BRIDGE_HANDBACK_SECONDS + 240)
    await hass.async_block_till_done()
    assert sent == [(DOMAIN, True, False)]
    assert list(downs) == []
    assert len(ups) == 2
    assert _seen(coord) == {}


async def test_one_returns_before_restart_other_still_down(hass: HomeAssistant, freezer):
    coord, a, da, b, db = await _both_down_pushed(hass, freezer)
    a.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, 240)
    coord = await restart(hass, freezer, down=120)
    _watch(coord, da + db)
    sent: list = []
    _record_pushes(coord, sent)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 240)
    assert sent == []
    b.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, BRIDGE_HANDBACK_SECONDS + 240)
    assert sent == [(DOMAIN, True, False)]
    assert _seen(coord) == {}


async def test_one_down_one_fine_restart(hass: HomeAssistant, freezer):
    a, da = _hub(hass, "a")
    b, db = _hub(hass, "b")
    coord = await setup_coordinator(hass)
    await past_grace(hass, freezer)
    _watch(coord, da + db)
    now = dt_util.utcnow().timestamp()
    a.mock_state(hass, ConfigEntryState.LOADED)
    b.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now)
    a.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    _down(coord, da, now + 30)
    sent: list = []
    _record_pushes(coord, sent)
    await walk(hass, freezer, UPSTREAM_SETTLE_SECONDS + 120)
    assert [(n, r) for n, r, _s in sent] == [(DOMAIN, False)]
    coord = await restart(hass, freezer, down=120)
    _watch(coord, da + db)
    sent = []
    _record_pushes(coord, sent)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 240)
    assert sent == []
    a.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, BRIDGE_HANDBACK_SECONDS + 240)
    assert sent == [(DOMAIN, True, False)]
    assert _seen(coord) == {}
    rows = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_INTEGRATION_DOWN]
    assert len(rows) == 1


async def test_both_down_pushed_one_returns_no_restart(hass: HomeAssistant, freezer):
    """The same story with no restart: one entry returning while the
    other is still down sends no push (rule UP-09: recovering sends no
    push; down and over once each)."""
    coord, a, da, b, db = await _both_down_pushed(hass, freezer)
    sent: list = []
    _record_pushes(coord, sent)
    a.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, BRIDGE_HANDBACK_SECONDS + 240)
    assert sent == [], sent

async def test_over_push_goes_while_a_one_device_entry_stays_down(hass: HomeAssistant, freezer):
    single, ds = _hub(hass, "s", devices=1)
    multi, dm = _hub(hass, "m", devices=3)
    coord = await setup_coordinator(hass)
    await past_grace(hass, freezer)
    _watch(coord, ds + dm)
    now = dt_util.utcnow().timestamp()
    single.mock_state(hass, ConfigEntryState.LOADED)
    multi.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now)
    # A one-device entry dead for good (the second fleet's freezers).
    single.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    await walk(hass, freezer, 3600)
    sent: list = []
    _record_pushes(coord, sent)
    # The hub entry goes down: pushed once, sounding.
    later = dt_util.utcnow().timestamp()
    multi.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    await walk(hass, freezer, INTEGRATION_DOWN_DWELL_SECONDS + 30)
    _down(coord, dm, later + 30)
    await walk(hass, freezer, UPSTREAM_SETTLE_SECONDS + 120)
    assert [(n, r) for n, r, _s in sent] == [(DOMAIN, False)], sent
    # The row is dated from the hub entry's fall, not the freezer's.
    since = coord.upstream_down_since_for(DOMAIN)
    # It comes back: its over push follows and its record goes.
    multi.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, BRIDGE_HANDBACK_SECONDS + 300)
    assert [(n, r) for n, r, _s in sent] == [(DOMAIN, False), (DOMAIN, True)], sent
    assert f"{DOMAIN}|{multi.entry_id}" not in _seen(coord)
    assert since >= later - 5, (since, later)

async def test_one_entry_down_row_and_push_count_its_own_devices(hass: HomeAssistant, freezer):
    a, da = _hub(hass, "a", devices=2)
    b, db = _hub(hass, "b", devices=5)
    coord = await setup_coordinator(hass)
    await past_grace(hass, freezer)
    _watch(coord, da + db)
    downs = record_events(hass, "device_sentinel_upstream_down")
    pushed: list = []

    async def _push(name, count, recovered=False):
        if not recovered:
            pushed.append(coord._upstream_down_words(name, count))
        coord._upstream_announced[name] = count

    coord.async_push_upstream = _push
    now = dt_util.utcnow().timestamp()
    a.mock_state(hass, ConfigEntryState.LOADED)
    b.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now)
    a.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    _down(coord, da, now + 30)
    await walk(hass, freezer, UPSTREAM_SETTLE_SECONDS + 120)
    await hass.async_block_till_done()
    assert [e["devices"] for e in downs] == [2]
    rows = [i for i in coord.todo_items if DOMAIN in str(i.get("summary", ""))]
    assert rows, coord.todo_items
    summary = rows[0]["summary"]
    assert "of 2 " in summary, summary
    assert pushed and "of 2 " in pushed[0], pushed


async def test_two_entries_down_read_as_one_row_counting_both(
    hass: HomeAssistant, freezer
):
    """Two entries of several devices down at once: one row for the
    integration, counting both entries' devices and nothing else."""
    a, da = _hub(hass, "a", devices=2)
    b, db = _hub(hass, "b", devices=3)
    c, dc = _hub(hass, "c", devices=4)
    coord = await setup_coordinator(hass)
    await past_grace(hass, freezer)
    _watch(coord, da + db + dc)
    now = dt_util.utcnow().timestamp()
    for source in (a, b, c):
        source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now)
    a.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    b.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    _down(coord, da + db, now + 30)
    await walk(hass, freezer, UPSTREAM_SETTLE_SECONDS + 120)
    rows = [i for i in coord.todo_items if DOMAIN in str(i.get("summary", ""))]
    assert len(rows) == 1, rows
    assert rows[0]["summary"].startswith(f"{DOMAIN} down: 5 of 5 "), rows[0]["summary"]


async def _two_device_entry_pushed(hass, freezer):
    a, da = _hub(hass, "a", devices=2)
    coord = await setup_coordinator(hass)
    await past_grace(hass, freezer)
    _watch(coord, da)
    sent: list = []
    _record_pushes(coord, sent)
    now = dt_util.utcnow().timestamp()
    a.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now)
    a.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    _down(coord, da, now + 30)
    await walk(hass, freezer, UPSTREAM_SETTLE_SECONDS + 120)
    assert [(n, r) for n, r, _s in sent] == [(DOMAIN, False)], sent
    return coord, a, da, sent


async def test_entry_that_fell_with_several_devices_keeps_its_row_when_one_is_excluded(
    hass: HomeAssistant, freezer
):
    """A two-device entry is down and pushed, and one of its devices is
    excluded while it is still down. Its size was decided when it fell,
    so its row stays and no over push goes until it returns."""
    coord, a, da, sent = await _two_device_entry_pushed(hass, freezer)
    # Excluded by the person: no longer in the watched set.
    coord._watched.pop(da[1].id, None)
    await walk(hass, freezer, 300)
    assert a.entry_id in coord._integration_told  # still down on the bus
    assert a.state is ConfigEntryState.SETUP_RETRY
    # UP-09: pushed when down, and when it is over. It is not over.
    assert [(n, r) for n, r, _s in sent] == [(DOMAIN, False)], sent


async def test_entry_that_shrank_while_down_pushes_over_once_across_a_restart(
    hass: HomeAssistant, freezer
):
    """Same, across a restart: one over push, when it returns."""
    coord, a, da, sent = await _two_device_entry_pushed(hass, freezer)
    coord._watched.pop(da[1].id, None)
    await walk(hass, freezer, 300)
    first = [(n, r) for n, r, _s in sent]
    coord = await restart(hass, freezer, down=120)
    _watch(coord, da[:1])
    sent2: list = []
    _record_pushes(coord, sent2)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 300)
    a.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, BRIDGE_HANDBACK_SECONDS + 300)
    assert first == [(DOMAIN, False)], first
    assert sent2 == [(DOMAIN, True, False)], sent2
    assert _seen(coord) == {}, _seen(coord)


def _record_words(coord, sent):
    async def _push(name, count, recovered=False):
        if recovered:
            sent.append((name, True, coord._upstream_return_words(name)))
            coord._upstream_announced.pop(name, None)
        else:
            sent.append((name, False, coord._upstream_down_words(name, count)))
            coord._upstream_announced[name] = count

    coord.async_push_upstream = _push


async def test_strip_and_plug_down_together_over_push_tells_the_integration(
    hass: HomeAssistant, freezer
):
    """A TP-Link house: a power strip (one entry, three outlets) and a
    plug (an entry of its own) both drop with the router. The strip's
    row is pushed down. Both come back, the plug a minute after the
    strip. The over push tells the integration's own outage in the
    brief's words, not the plug's return ("Node s0 is back")."""
    single, ds = _hub(hass, "s", devices=1)
    multi, dm = _hub(hass, "m", devices=3)
    coord = await setup_coordinator(hass)
    await past_grace(hass, freezer)
    _watch(coord, ds + dm)
    sent: list = []
    _record_words(coord, sent)
    now = dt_util.utcnow().timestamp()
    single.mock_state(hass, ConfigEntryState.LOADED)
    multi.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now)
    single.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    multi.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    _down(coord, ds + dm, now + 30)
    await walk(hass, freezer, UPSTREAM_SETTLE_SECONDS + 120)
    assert [(n, r) for n, r, _w in sent] == [(DOMAIN, False)], sent
    multi.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, 60)
    single.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, BRIDGE_HANDBACK_SECONDS + 300)
    overs = [w for _n, r, w in sent if r]
    assert len(overs) == 1, sent
    assert "Node s0" not in overs[0], overs[0]
    assert overs[0].startswith(f"The {DOMAIN} integration came back at "), overs[0]
    assert "3 of its 3 devices went down." in overs[0], overs[0]


async def test_two_entries_over_push_counts_both_entries(
    hass: HomeAssistant, freezer
):
    """Two hubs of one integration go down together: the down push says
    5 of 5, and the over push counts the same 5, timed from the first
    fall to the last return (UP-09: "that number")."""
    a, da = _hub(hass, "a", devices=2)
    b, db = _hub(hass, "b", devices=3)
    coord = await setup_coordinator(hass)
    await past_grace(hass, freezer)
    _watch(coord, da + db)
    sent: list = []
    _record_words(coord, sent)
    now = dt_util.utcnow().timestamp()
    a.mock_state(hass, ConfigEntryState.LOADED)
    b.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now)
    a.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    b.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    _down(coord, da + db, now + 30)
    await walk(hass, freezer, UPSTREAM_SETTLE_SECONDS + 120)
    downs = [w for _n, r, w in sent if not r]
    assert downs and "of 5 " in downs[0], sent
    a.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, 60)
    b.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, BRIDGE_HANDBACK_SECONDS + 300)
    overs = [w for _n, r, w in sent if r]
    assert len(overs) == 1, sent
    assert "5 of its 5 devices went down." in overs[0], overs[0]
