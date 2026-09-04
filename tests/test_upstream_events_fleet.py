# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_upstream_events_fleet.py, Version: 0.20.0 (2026-09-03)

"""The upstream event pair, driven against both reference fleets.

Not a unit test. Each case loads a real fleet's own record into a
live coordinator, registers every device it names, and then puts the
upstream through the shapes a house actually produces: a bridge
falling and returning, a broker taking every bridge with it, a link
that will not settle, an outage that spans a restart, and a fleet
where nothing is up at all.

What is judged is the bus. Every down owes a restored, every restored
owes a down before it, the device count is the membership behind the
upstream rather than the casualties so far, and nothing is said
during the startup grace.

Skips whole when the fleet files are absent, as every fleet case does.
"""

from __future__ import annotations

import glob
import json

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BRIDGE_SEEN_SINCE,
    BRIDGE_SEEN_STATE,
    BROKER_DOWN,
    BROKER_RUNNING,
    DATA_BRIDGE_SEEN,
    DATA_DEVICES,
    EVENT_UPSTREAM_DOWN,
    EVENT_UPSTREAM_RESTORED,
)

from tests.conftest import FLEET_ABSENT, fleet_path
from tests.helpers import setup_coordinator

JAMES = fleet_path("james", "device_sentinel.storage")
TIM = fleet_path("tim", "device_sentinel_storage.json")


# ------------------------------------------------------------ harness


def _stub(state):
    """The smallest thing the bridge sampler accepts."""
    from types import SimpleNamespace

    return SimpleNamespace(
        state=state,
        pairing_open=False,
        permit_join_end=None,
        async_stop=lambda: None,
        reachability=lambda key: None,
    )


def _broker_stub(state, started=1.0):
    from types import SimpleNamespace

    return SimpleNamespace(
        state=state,
        started_at=started,
        async_stop=lambda: None,
        regressed_since=lambda known: False,
        last_heard=None,
        cadence=None,
        threshold=None,
        topic="t",
    )


def _heard(hass):
    """Collect both halves of the pair, in order."""
    seen: list = []
    hass.bus.async_listen(
        EVENT_UPSTREAM_DOWN,
        lambda event: seen.append(("down", dict(event.data))),
    )
    hass.bus.async_listen(
        EVENT_UPSTREAM_RESTORED,
        lambda event: seen.append(("restored", dict(event.data))),
    )
    return seen


async def _fleet(hass, path, stack="z2m"):
    """Load a real fleet and return a coordinator past its grace.

    The records are keyed onto devices planted under the fleet's own
    identifiers, and every device is given the bridge's own domain so
    the stack owns it, which is what makes the membership count real
    rather than zero.
    """
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    data = loaded.get("data", loaded)
    records = data.get("devices") or {}

    found = glob.glob(str(path.parent / "config_entry*.json"))
    names = {}
    if found:
        with open(found[0], encoding="utf-8") as handle:
            dump = json.load(handle)
        names = {
            device_id: (record or {}).get("name") or device_id
            for device_id, record in (
                (dump.get("data") or {}).get("devices") or {}
            ).items()
        }

    source = MockConfigEntry(domain="mqtt", title="Zigbee")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    bridge = registry.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", "z2m_bridge")},
        name="SLZB-06M Zigbee2MQTT Bridge",
    )
    entities.async_get_or_create(
        "sensor", "mqtt", "z2m_bridge_0",
        device_id=bridge.id, config_entry=source,
    )
    planted = {}
    for index, device_id in enumerate(records):
        uid = f"zigbee2mqtt_0x{index:016x}"
        device = registry.async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("mqtt", uid)},
            name=names.get(device_id) or device_id,
        )
        entities.async_get_or_create(
            "sensor", "mqtt", uid,
            device_id=device.id, config_entry=source,
        )
        planted[device_id] = device.id

    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    for device_id, record in records.items():
        live = planted.get(device_id)
        if live is not None and isinstance(record, dict):
            coord.data[DATA_DEVICES][live] = dict(record)
    coord._grace_until = 0.0
    coord._bridge_readers[stack] = _stub(BRIDGE_RUNNING)
    coord._bridge_seen[stack] = BRIDGE_RUNNING
    # The watched count, not the record count. The bridge device is
    # itself watched and itself on the stack, so it is behind its own
    # outage and the membership is one larger than the file.
    return coord, len(coord._watched)


def _pairs_close(seen):
    """Every down is answered and no restored arrives unanswered."""
    open_names: dict[str, dict] = {}
    for word, payload in seen:
        name = payload["name"]
        if word == "down":
            assert name not in open_names, f"two downs for {name}"
            open_names[name] = payload
        else:
            assert name in open_names, f"restored with no down: {name}"
            began = open_names.pop(name)
            assert payload["since"] == began["since"]
            assert payload["devices"] == began["devices"]
            assert payload["for_seconds"] >= 0.0
    return open_names


# --------------------------------------------------------- the shapes


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
async def test_the_reference_fleet_pairs_a_bridge_outage(
    hass: HomeAssistant,
):
    """One bridge, down and back, on a real fleet's own record."""
    coord, count = await _fleet(hass, JAMES)
    seen = _heard(hass)

    coord._bridge_readers["z2m"] = _stub(BRIDGE_DOWN)
    coord._sample_bridges()
    await hass.async_block_till_done()
    coord._bridge_readers["z2m"] = _stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()

    assert [word for word, _ in seen] == ["down", "restored"], seen
    assert _pairs_close(seen) == {}
    # Membership, and a real fleet has some.
    assert 0 < seen[0][1]["devices"] <= count
    assert seen[0][1]["kind"] == "bridge"


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
async def test_the_second_fleet_pairs_a_bridge_outage(
    hass: HomeAssistant,
):
    """The same on a fleet more than twice the size."""
    coord, count = await _fleet(hass, TIM)
    seen = _heard(hass)

    coord._bridge_readers["z2m"] = _stub(BRIDGE_DOWN)
    coord._sample_bridges()
    await hass.async_block_till_done()
    coord._bridge_readers["z2m"] = _stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()

    assert [word for word, _ in seen] == ["down", "restored"], seen
    assert _pairs_close(seen) == {}
    assert 0 < seen[0][1]["devices"] <= count


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
async def test_a_link_that_will_not_settle_stays_paired(
    hass: HomeAssistant,
):
    """Fifty cycles on a real fleet.

    The failure this looks for is a pair that drifts: two downs with
    no restored between them, or a restored with nothing open, either
    of which leaves an automation holding a fault that never closes.
    """
    coord, _count = await _fleet(hass, JAMES)
    seen = _heard(hass)

    for _cycle in range(50):
        coord._bridge_readers["z2m"] = _stub(BRIDGE_DOWN)
        coord._sample_bridges()
        coord._bridge_readers["z2m"] = _stub(BRIDGE_RUNNING)
        coord._sample_bridges()
    await hass.async_block_till_done()

    assert len(seen) == 100, len(seen)
    assert _pairs_close(seen) == {}


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
async def test_a_sample_that_repeats_says_nothing_new(
    hass: HomeAssistant,
):
    """Twenty samples of an unchanged outage are one event.

    The pair sits on the transition, not the state, so a sampler that
    runs every few seconds during a long outage must not announce it
    every few seconds.
    """
    coord, _count = await _fleet(hass, JAMES)
    seen = _heard(hass)

    coord._bridge_readers["z2m"] = _stub(BRIDGE_DOWN)
    for _tick in range(20):
        coord._sample_bridges()
    await hass.async_block_till_done()

    assert [word for word, _ in seen] == ["down"], seen


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
async def test_an_outage_that_spans_a_restart_is_announced_once(
    hass: HomeAssistant,
):
    """Down before the restart, still down after, back later.

    The grace is silent. What survived it is announced when it ends,
    carrying the moment it really failed, so the recovery that
    follows has a failure to pair with (ruling #291).
    """
    coord, _count = await _fleet(hass, JAMES)
    seen = _heard(hass)

    failed_at = dt_util.utcnow().timestamp() - 3600.0
    coord.data[DATA_BRIDGE_SEEN] = {
        "z2m": {
            BRIDGE_SEEN_STATE: BRIDGE_DOWN,
            BRIDGE_SEEN_SINCE: failed_at,
        }
    }
    coord._bridge_seen.clear()
    coord._bridge_down_at.clear()
    coord._upstream_held.clear()
    coord._upstream_said.clear()
    coord._restore_bridge_state()

    # Inside the grace: silent, whatever the sampler sees.
    coord._grace_until = dt_util.utcnow().timestamp() + 300.0
    coord._bridge_readers["z2m"] = _stub(BRIDGE_DOWN)
    for _tick in range(5):
        coord._sample_bridges()
    await hass.async_block_till_done()
    assert seen == [], seen

    # Grace over: announced once, with the true onset.
    coord._grace_until = 0.0
    coord._sample_bridges()
    coord._sample_bridges()
    await hass.async_block_till_done()
    assert [word for word, _ in seen] == ["down"], seen
    said = dt_util.parse_datetime(seen[0][1]["since"])
    assert abs(said.timestamp() - failed_at) < 2.0

    coord._bridge_readers["z2m"] = _stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()
    assert [word for word, _ in seen] == ["down", "restored"]
    assert seen[1][1]["for_seconds"] > 3500.0


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
async def test_the_broker_outranks_the_bridge_on_the_bus(
    hass: HomeAssistant,
):
    """A stopped broker takes every bridge with it (ruling #224).

    The sampler returns before it reads a bridge, so a broker outage
    announces one thing rather than one per bridge, which is the same
    noise in a smaller font.
    """
    coord, count = await _fleet(hass, JAMES)
    seen = _heard(hass)

    coord._broker_reader = _broker_stub(BROKER_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()

    coord._broker_reader = _broker_stub(BROKER_DOWN)
    coord._bridge_readers["z2m"] = _stub(BRIDGE_DOWN)
    coord._sample_bridges()
    await hass.async_block_till_done()

    words = [(word, payload["kind"]) for word, payload in seen]
    assert words == [("down", "broker")], words
    assert 0 < seen[0][1]["devices"] <= count

    coord._broker_reader = _broker_stub(BROKER_RUNNING)
    coord._bridge_readers["z2m"] = _stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()
    assert _pairs_close(seen) == {}


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
async def test_a_fleet_where_nothing_is_up(hass: HomeAssistant):
    """Broker down, bridge down, and the record intact underneath.

    Nothing here should produce a second announcement or an orphan,
    however long the outage runs.
    """
    coord, _count = await _fleet(hass, TIM)
    seen = _heard(hass)

    coord._broker_reader = _broker_stub(BROKER_RUNNING)
    coord._sample_bridges()
    coord._broker_reader = _broker_stub(BROKER_DOWN)
    coord._bridge_readers["z2m"] = _stub(BRIDGE_DOWN)
    for _tick in range(30):
        coord._sample_bridges()
    await hass.async_block_till_done()

    assert [word for word, _ in seen] == ["down"], seen
    assert seen[0][1]["kind"] == "broker"


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
async def test_the_count_never_exceeds_the_watched_fleet(
    hass: HomeAssistant,
):
    """A number a person acts on cannot be larger than the truth."""
    coord, _count = await _fleet(hass, JAMES)
    seen = _heard(hass)

    watched = len(coord._watched)
    coord._bridge_readers["z2m"] = _stub(BRIDGE_DOWN)
    coord._sample_bridges()
    await hass.async_block_till_done()

    assert seen, "nothing announced"
    assert 0 < seen[0][1]["devices"] <= watched, (
        seen[0][1]["devices"],
        watched,
    )
