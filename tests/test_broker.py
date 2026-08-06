# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_broker.py, Version: 0.12.4 (2026-08-06)

"""The MQTT broker watch, replayed against a real recording.

tests/fixtures/broker_uptime.json is 2,459 arrivals captured from the
reference broker on 2026-08-05 and 06, carrying three genuine restarts
of three different shapes: a whole-host reboot where nothing was
running to watch the silence, a nine-second broker bounce, and a
sixteen-minute outage with Home Assistant up throughout. The third is
the one this release exists for, because it produced no system event
of any kind under 0.12.3 while the bridge sensor read running.

Every assertion about cadence and thresholds comes out of that
recording rather than out of a chosen number.
"""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel import transport_mqtt
from custom_components.device_sentinel.const import (
    BROKER_DOWN,
    BROKER_RUNNING,
    BROKER_SCOPE,
    BROKER_UNKNOWN,
    DATA_BROKER_SEEN,
    DATA_SYSTEM_EVENTS,
    SYS_BROKER_DOWN,
    SYS_BROKER_UP,
    SYS_KIND,
)
from tests.helpers import setup_coordinator

FIXTURE = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "broker_uptime.json")
    .read_text()
)


def _stub(state, started_at, regressed=False):
    """The smallest reader the sampler and teardown both accept."""
    return SimpleNamespace(
        state=state,
        started_at=started_at,
        regressed_since=lambda known: regressed,
        async_stop=lambda: None,
    )


def _msg(uptime: float):
    """Return the shape the MQTT callback receives."""
    return SimpleNamespace(
        topic="$SYS/broker/uptime", payload=f"{uptime:.0f} seconds"
    )


def _feed(reader, rows, now_at=None):
    """Replay arrivals, driving the clock from the recording itself."""
    for row in rows:
        now_at(row["t"])
        reader._on_uptime(_msg(row["u"]))


class _Clock:
    """A settable clock, so the replay runs at the recorded times."""

    def __init__(self, monkeypatch, at):
        self.now = at
        monkeypatch.setattr(
            transport_mqtt.dt_util,
            "utcnow",
            lambda: __import__("datetime").datetime.fromtimestamp(
                self.now, __import__("datetime").timezone.utc
            ),
        )

    def set(self, when):
        self.now = when


def test_the_fixture_is_the_recording_it_claims_to_be():
    """Guard the fixture, so the replay cannot quietly drift."""
    assert len(FIXTURE) == 2459
    regressions = sum(
        1
        for before, after in zip(FIXTURE, FIXTURE[1:])
        if after["u"] < before["u"]
    )
    assert regressions == 3


def test_the_replay_finds_three_restarts_and_no_others(monkeypatch):
    """Every normal gap must pass, and every real restart must fire.

    A watch that cries wolf on ordinary jitter is worse than none, so
    this asserts the count in both directions across 2,458 intervals.
    """
    clock = _Clock(monkeypatch, FIXTURE[0]["t"])
    reader = transport_mqtt.MQTTBrokerReader(None)
    known = None
    found = []
    for row in FIXTURE:
        clock.set(row["t"])
        reader._on_uptime(_msg(row["u"]))
        if reader.regressed_since(known):
            found.append(reader.started_at)
        known = reader.started_at
    assert len(found) == 3


def test_the_cadence_and_threshold_come_out_of_the_recording(monkeypatch):
    """Learned, not set: 10 seconds observed gives 60 seconds of grace."""
    clock = _Clock(monkeypatch, FIXTURE[0]["t"])
    reader = transport_mqtt.MQTTBrokerReader(None)
    for row in FIXTURE[:60]:
        clock.set(row["t"])
        reader._on_uptime(_msg(row["u"]))
    assert 9.9 < reader.cadence < 10.2
    assert 59 < reader.threshold < 62


def test_the_sixteen_minute_outage_reads_as_down(monkeypatch):
    """The case that produced no event at all under 0.12.3."""
    clock = _Clock(monkeypatch, FIXTURE[0]["t"])
    reader = transport_mqtt.MQTTBrokerReader(None)
    # Find the longest hole in the recording and stand inside it.
    worst, at = 0.0, None
    for before, after in zip(FIXTURE, FIXTURE[1:]):
        hole = after["t"] - before["t"]
        if hole > worst:
            worst, at = hole, before
    assert worst > 900
    for row in FIXTURE:
        if row["t"] > at["t"]:
            break
        clock.set(row["t"])
        reader._on_uptime(_msg(row["u"]))
    assert reader.state == BROKER_RUNNING
    clock.set(at["t"] + reader.threshold + 1)
    assert reader.state == BROKER_DOWN


def test_nothing_is_claimed_before_two_arrivals(monkeypatch):
    """A broker with $SYS off never arms and costs nothing."""
    clock = _Clock(monkeypatch, FIXTURE[0]["t"])
    reader = transport_mqtt.MQTTBrokerReader(None)
    assert reader.state == BROKER_UNKNOWN
    assert reader.threshold is None
    reader._on_uptime(_msg(100))
    assert reader.state == BROKER_UNKNOWN
    clock.set(FIXTURE[0]["t"] + 10)
    reader._on_uptime(_msg(110))
    assert reader.state == BROKER_RUNNING


def test_a_payload_that_will_not_parse_is_refused(monkeypatch):
    """A broker wording it differently leaves the watch unarmed."""
    _Clock(monkeypatch, FIXTURE[0]["t"])
    reader = transport_mqtt.MQTTBrokerReader(None)
    for payload in (None, "", "up for ages", b"\xff\xfe", "-5 seconds"):
        reader._on_uptime(SimpleNamespace(topic="x", payload=payload))
    assert reader.state == BROKER_UNKNOWN
    assert transport_mqtt._uptime_seconds(b"12355 seconds") == 12355.0
    assert transport_mqtt._uptime_seconds("0 seconds") == 0.0


def test_the_computed_start_matches_the_recorded_reboot(monkeypatch):
    """The signal that survives Home Assistant being down too.

    The whole-host reboot left a 140 second hole in the recording,
    because nothing here was running through it. The first arrival
    afterwards still says when the broker came up.
    """
    clock = _Clock(monkeypatch, FIXTURE[0]["t"])
    reader = transport_mqtt.MQTTBrokerReader(None)
    for index, row in enumerate(FIXTURE[1:], start=1):
        clock.set(row["t"])
        reader._on_uptime(_msg(row["u"]))
        if row["u"] < FIXTURE[index - 1]["u"] and row["u"] > 40:
            # The reboot: uptime 23488 -> 44 across a 140s hole.
            assert FIXTURE[index]["t"] - FIXTURE[index - 1]["t"] > 130
            assert abs(reader.started_at - (row["t"] - row["u"])) < 0.01
            return
    raise AssertionError("the reboot was not found in the fixture")


async def test_the_broker_pair_is_written(hass: HomeAssistant):
    """A broker that goes and returns writes two events and a duration."""
    coord = await setup_coordinator(hass)
    coord._broker_reader = _stub(BROKER_RUNNING, 1000.0)
    coord._sample_broker(2000.0)
    before = len(coord.data[DATA_SYSTEM_EVENTS])

    coord._broker_reader.state = BROKER_DOWN
    coord._sample_broker(2100.0)
    coord._broker_reader.state = BROKER_RUNNING
    coord._sample_broker(2200.0)

    kinds = [
        event[SYS_KIND]
        for event in coord.data[DATA_SYSTEM_EVENTS][before:]
    ]
    assert kinds == [SYS_BROKER_DOWN, SYS_BROKER_UP]
    up = coord.data[DATA_SYSTEM_EVENTS][-1]
    assert up["duration"] == 100.0
    assert up["scope"] == BROKER_SCOPE


async def test_a_reboot_does_not_report_the_broker_twice(
    hass: HomeAssistant,
):
    """The attribution rule.

    A restart of the whole machine takes the broker with it, and the
    restart event already carries the span nothing was listening.
    Without this the nightly reboot would write a broker outage
    describing the same two minutes.
    """
    coord = await setup_coordinator(hass)
    coord._last_alive = 5000.0
    coord._started_at = 5140.0
    coord.data[DATA_BROKER_SEEN] = {"state": BROKER_RUNNING, "started": 1.0}
    coord._broker_reader = _stub(BROKER_RUNNING, 5100.0, regressed=True)
    before = len(coord.data[DATA_SYSTEM_EVENTS])
    coord._sample_broker(5200.0)
    assert len(coord.data[DATA_SYSTEM_EVENTS]) == before

    # The same regression outside the unwatched span is reported.
    coord._broker_reader.started_at = 9000.0
    coord.data[DATA_BROKER_SEEN] = {"state": BROKER_RUNNING, "started": 1.0}
    coord._sample_broker(9100.0)
    kinds = [
        event[SYS_KIND]
        for event in coord.data[DATA_SYSTEM_EVENTS][before:]
    ]
    assert kinds == [SYS_BROKER_DOWN, SYS_BROKER_UP]


async def test_no_bridge_event_while_the_broker_is_down(
    hass: HomeAssistant,
):
    """The broker is the outer scope.

    A bridge that cannot be heard is not a bridge that is down, so
    one event is written rather than two.
    """
    coord = await setup_coordinator(hass)
    coord.data[DATA_BROKER_SEEN] = {"state": BROKER_RUNNING}
    coord._broker_reader = _stub(BROKER_DOWN, 1.0)
    coord._bridge_readers["z2m"] = SimpleNamespace(
        state="down", pairing_open=False, async_stop=lambda: None
    )
    coord._bridge_seen["z2m"] = "running"
    before = len(coord.data[DATA_SYSTEM_EVENTS])
    coord._sample_bridges()
    kinds = [
        event[SYS_KIND]
        for event in coord.data[DATA_SYSTEM_EVENTS][before:]
    ]
    assert SYS_BROKER_DOWN in kinds
    assert "bridge_down" not in kinds


async def test_the_sensor_reads_unknown_without_a_broker(
    hass: HomeAssistant,
):
    """No MQTT at all costs one disabled entity reading unknown."""
    coord = await setup_coordinator(hass)
    coord._broker_reader = None
    assert coord.broker_state == BROKER_UNKNOWN
    assert coord.broker_attributes["topic"] == "$SYS/broker/uptime"


async def test_a_reader_that_raises_is_no_opinion(hass: HomeAssistant):
    """A watch can never break the tick every judgment runs on."""

    class Broken:
        started_at = None

        @property
        def state(self):
            raise RuntimeError("no")

        def async_stop(self):
            return None

    coord = await setup_coordinator(hass)
    coord._broker_reader = Broken()
    assert coord.broker_state == BROKER_UNKNOWN
    assert coord._sample_broker(1.0) == BROKER_UNKNOWN
