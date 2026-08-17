# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_attribution.py, Version: 0.15.3 (2026-08-17)

"""What explains an incident, and what a flood reads as.

The shape replayed here is the one the reference fleet produced on
2026-08-06: a sixteen-minute broker outage took 74 devices, they
recovered inside 8.5 seconds, and the brief gave four different
explanations for one event, with devices resolving in the same
millisecond disagreeing. The cause was borrowed from each device's
most recent silence episode, whenever that was (ruling #228).
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel import attribution
from custom_components.device_sentinel.const import (
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    SYS_BRIDGE_DOWN,
    SYS_BROKER_DOWN,
    SYS_BROKER_UP,
    SYS_DEVICES,
    SYS_DURATION,
    SYS_KIND,
    SYS_RESTART,
    SYS_SCOPE,
    SYS_STORM_CLOSED,
    SYS_STORM_OPEN,
    SYS_WHEN,
)
from tests.helpers import setup_coordinator

T0 = 1786000000.0


def _event(kind, scope, when, duration=None, devices=None):
    """Return one system event row."""
    row = {SYS_KIND: kind, SYS_SCOPE: scope, SYS_WHEN: when}
    if duration is not None:
        row[SYS_DURATION] = duration
    if devices is not None:
        row[SYS_DEVICES] = devices
    return row


def _incident(device_id, name, when, event=INCIDENT_OPENED, cause=None):
    """Return one incident row."""
    return {
        INC_DEVICE_ID: device_id,
        INC_NAME: name,
        INC_KIND: "unavailable",
        INC_EVENT: event,
        INC_WHEN: when,
        INC_CAUSE: cause,
    }


# The outage as it happened: down at 01:47, back at 02:04.
BROKER_OUTAGE = [
    _event(SYS_BROKER_DOWN, "mqtt", T0),
    _event(SYS_BROKER_UP, "mqtt", T0 + 1020, duration=1020.0),
]


def test_a_pair_becomes_one_window():
    """A down and an up are one thing, not two moments."""
    spans = attribution.windows(BROKER_OUTAGE)
    assert len(spans) == 1
    assert spans[0].start == T0
    assert spans[0].end == T0 + 1020


def test_an_unclosed_opening_stays_open():
    """A bridge still down is still down."""
    spans = attribution.windows([_event(SYS_BRIDGE_DOWN, "z2m", T0)])
    assert len(spans) == 1
    assert spans[0].end is None
    assert spans[0].in_effect_at(T0 + 5000)


def test_the_broker_reaches_mqtt_devices_and_nothing_else():
    """Scope is the half that matters."""
    span = attribution.windows(BROKER_OUTAGE)[0]
    assert span.covers("mqtt", "z2m") is True
    assert span.covers("mqtt", None) is True
    assert span.covers("homekit_controller", None) is False
    assert span.covers("zha", "zha") is False


def test_a_bridge_cannot_revive_a_homekit_accessory():
    """The fault this file exists to prevent."""
    span = attribution.windows([_event(SYS_BRIDGE_DOWN, "z2m", T0)])[0]
    assert span.covers("mqtt", "z2m") is True
    assert span.covers("homekit_controller", None) is False


def test_a_storm_reaches_only_its_own_integration():
    """An integration reload explains its devices and no others."""
    span = attribution.windows(
        [_event(SYS_STORM_OPEN, "reolink", T0)]
    )[0]
    assert span.covers("reolink", None) is True
    assert span.covers("mqtt", "z2m") is False


def test_a_restart_reaches_everything():
    """Whatever the stack, a reboot took it down."""
    span = attribution.windows(
        [_event(SYS_RESTART, "system", T0, duration=107.0)]
    )[0]
    for domain in ("mqtt", "zha", "homekit_controller", "reolink"):
        assert span.covers(domain, None) is True


def test_the_earliest_thing_under_way_wins():
    """Where two were in effect, the outer one is the cause.

    Narrowness was the old rule and it was wrong: an outage produces
    the burst that follows it, so the narrower record is the
    consequence (ruling #229).
    """
    spans = attribution.windows(
        [
            _event(SYS_STORM_OPEN, "mqtt", T0 + 10),
            _event(SYS_STORM_CLOSED, "mqtt", T0 + 20, duration=10.0),
            _event(SYS_RESTART, "system", T0 + 60, duration=120.0),
        ]
    )
    # The restart's window opens at T0 - 60, before the storm.
    found = attribution.attribute(spans, "mqtt", "z2m", T0 + 12, T0 + 18)
    assert found.kind == SYS_RESTART


def test_an_unexplained_recovery_gets_nothing():
    """A device that came back on its own is not credited a lever."""
    spans = attribution.windows(BROKER_OUTAGE)
    # Days later, same device, nothing happening.
    assert attribution.attribute(
        spans, "mqtt", "z2m", T0 + 400000, T0 + 400100
    ) is None
    # Right time, wrong integration.
    assert attribution.attribute(
        spans, "homekit_controller", None, T0 + 100, T0 + 200
    ) is None


def test_the_phrase_names_the_scope():
    """One wording table, so no surface can invent a second."""
    spans = attribution.windows(
        BROKER_OUTAGE + [_event(SYS_STORM_OPEN, "reolink", T0)]
    )
    said = {attribution.phrase(span) for span in spans}
    assert "the MQTT broker going down and coming back" in said
    assert "the reolink integration reloading" in said


async def test_the_flood_collapses_to_one_sentence(hass: HomeAssistant):
    """74 devices, one event, one line.

    The live brief carried a single paragraph of 7,375 characters and
    74 sentences for this. Each device's stored cause is deliberately
    different here, reproducing the fault, so the test also proves
    the reader ignores the stored cause and works it out afresh.
    """
    coord = await setup_coordinator(hass)
    stale = ["bridge reconnect", "reboot", "no intervention recorded", None]
    pairs = []
    for index in range(74):
        device_id = f"d{index}"
        coord._watched[device_id] = "mqtt"
        opened = _incident(device_id, f"Device {index}", T0 + 180)
        closed = _incident(
            device_id,
            f"Device {index}",
            T0 + 1024 + index * 0.1,
            event=INCIDENT_RESOLVED,
            cause=stale[index % 4],
        )
        pairs.append((opened, closed))

    told = coord._tell_episodes(pairs, BROKER_OUTAGE)
    assert len(told) == 1
    assert told[0].startswith("74 devices went unavailable at ")
    assert told[0].endswith(
        "revived by the MQTT broker going down and coming back."
    )
    for wrong in ("bridge reconnect", "reboot", "no intervention recorded"):
        assert wrong not in told[0]


async def test_openings_collapse_too(hass: HomeAssistant):
    """The same event fills the list going in as well as coming out."""
    coord = await setup_coordinator(hass)
    pairs = []
    for index in range(74):
        device_id = f"d{index}"
        coord._watched[device_id] = "mqtt"
        pairs.append((_incident(device_id, f"Device {index}", T0 + 180), None))
    told = coord._tell_episodes(pairs, BROKER_OUTAGE)
    assert len(told) == 1
    assert told[0].startswith("74 devices went unavailable at ")


async def test_one_device_keeps_its_own_sentence(hass: HomeAssistant):
    """A flood of one is not a flood.

    It keeps its time and its duration and gains only the corrected
    cause, because collapsing it would throw away detail to solve a
    problem it does not have.
    """
    coord = await setup_coordinator(hass)
    coord._watched["d1"] = "mqtt"
    opened = _incident("d1", "Door 2nd Bedroom", T0 + 180)
    closed = _incident(
        "d1", "Door 2nd Bedroom", T0 + 1024,
        event=INCIDENT_RESOLVED, cause="reboot",
    )
    closed["duration"] = 844.0
    told = coord._tell_episodes([(opened, closed)], BROKER_OUTAGE)
    assert len(told) == 1
    assert told[0].startswith("Door 2nd Bedroom went unavailable at ")
    assert "revived by the MQTT broker" in told[0]
    assert "reboot" not in told[0]


async def test_unrelated_devices_are_not_swept_in(hass: HomeAssistant):
    """A hundred in a minute is not a flood; two on one event is."""
    coord = await setup_coordinator(hass)
    coord._watched["m1"] = "mqtt"
    coord._watched["m2"] = "mqtt"
    coord._watched["h1"] = "homekit_controller"
    pairs = [
        (_incident("m1", "MQTT One", T0 + 180), None),
        (_incident("m2", "MQTT Two", T0 + 181), None),
        (_incident("h1", "HomeKit One", T0 + 182), None),
    ]
    told = coord._tell_episodes(pairs, BROKER_OUTAGE)
    assert len(told) == 2
    assert any(line.startswith("2 devices went unavailable") for line in told)
    assert any(line.startswith("HomeKit One") for line in told)


# The two shapes the reference fleet produces every night, and the
# ones that were wrong until 0.12.6 (ruling #229).
STORM_AFTER_BROKER = BROKER_OUTAGE + [
    _event(SYS_STORM_OPEN, "mqtt", T0 + 1024),
    _event(SYS_STORM_CLOSED, "mqtt", T0 + 1032, duration=8.0),
]
REBOOT_WITH_BURST = [
    _event(SYS_RESTART, "system", T0 + 104, duration=104.0),
    _event(SYS_STORM_OPEN, "mqtt", T0 + 110),
    _event(SYS_STORM_CLOSED, "mqtt", T0 + 118, duration=8.0),
]


def test_a_symptom_never_masks_its_cause():
    """The burst of devices returning is not why they left.

    Both windows cover the device and both overlap the incident.
    Only the broker was under way when the device went quiet, and
    ranking by narrowness named the consequence instead.
    """
    spans = attribution.windows(STORM_AFTER_BROKER)
    found = attribution.attribute(spans, "mqtt", "z2m", T0 + 180, T0 + 1024)
    assert attribution.phrase(found) == (
        "the MQTT broker going down and coming back"
    )


def test_a_reboot_is_not_an_integration_reloading():
    """The burst inside startup grace is the restart itself."""
    spans = attribution.windows(REBOOT_WITH_BURST)
    found = attribution.attribute(spans, "mqtt", "z2m", T0 + 20, T0 + 112)
    assert attribution.phrase(found) == "a restart"


def test_a_device_already_silent_is_not_blamed_on_the_outage():
    """Nothing was under way when it went quiet, so nothing caused it.

    It is still credited with the revival, because the outage ending
    is plausibly what brought it back, and that is more useful than
    saying nothing.
    """
    spans = attribution.windows(BROKER_OUTAGE)
    found = attribution.attribute(
        spans, "mqtt", "z2m", T0 - 40000, T0 + 1024
    )
    assert attribution.phrase(found) == (
        "the MQTT broker going down and coming back"
    )


def test_an_outage_older_than_the_brief_window_still_explains():
    """The attributor reads every event, not only today's."""
    spans = attribution.windows(BROKER_OUTAGE)
    assert attribution.attribute(
        spans, "mqtt", "z2m", T0 + 180, None
    ) is not None


async def test_a_grace_storm_writes_no_event(hass: HomeAssistant):
    """A burst during startup grace is the restart, already recorded.

    Driven through the detector rather than the recorder, because
    the guard is in the detector and testing the recorder would
    prove only that it records.
    """
    from custom_components.device_sentinel.const import (
        DATA_STORMS,
        STORM_DEVICE_THRESHOLD,
    )

    coord = await setup_coordinator(hass)
    entry_id = coord.entry.entry_id

    coord._grace_until = T0 + 1000
    for index in range(STORM_DEVICE_THRESHOLD + 2):
        coord._storm_feed(entry_id, f"g{index}", T0)
    assert coord.data.get(DATA_STORMS) == []

    # The same burst after grace is a storm and is recorded.
    coord._storm_active.clear()
    coord._storm_feed_q.clear()
    after = T0 + 2000
    for index in range(STORM_DEVICE_THRESHOLD + 2):
        coord._storm_feed(entry_id, f"d{index}", after)
    assert len(coord.data[DATA_STORMS]) == 1


async def test_a_grace_storm_records_neither_half(hass: HomeAssistant):
    """Suppressing the opening alone left an orphan in the brief.

    0.12.6 stopped writing the opening inside startup grace and went
    on writing the closing, so the live brief carried a sentence
    saying an integration had settled when nothing was ever said to
    have started (ruling #230).
    """
    from custom_components.device_sentinel.const import (
        DATA_STORMS,
        DATA_SYSTEM_EVENTS,
        STORM_DEVICE_THRESHOLD,
        SYS_STORM_CLOSED,
        SYS_STORM_OPEN,
    )

    coord = await setup_coordinator(hass)
    entry_id = coord.entry.entry_id
    coord._grace_until = T0 + 1000
    for index in range(STORM_DEVICE_THRESHOLD + 2):
        coord._storm_feed(entry_id, f"g{index}", T0)
    coord._sweep_storms(T0 + 60)

    kinds = [row[SYS_KIND] for row in coord.data[DATA_SYSTEM_EVENTS]]
    assert SYS_STORM_OPEN not in kinds
    assert SYS_STORM_CLOSED not in kinds
    assert coord.data.get(DATA_STORMS) == []


async def test_an_exempted_storm_is_closed_not_abandoned(
    hass: HomeAssistant,
):
    """The row must not be left open by the early return.

    Once an integration is read as a poller, its feed is never
    sampled again, so nothing would ever finish the storm that was
    open when the verdict landed. The live fleet left eleven of
    twenty storms unclosed that way, and the exemption went on
    counting rows it could no longer update (ruling #230).
    """
    from custom_components.device_sentinel.const import (
        DATA_STORMS,
        STORM_DEVICE_THRESHOLD,
        STORM_DURATION,
        STORM_EXEMPT_PER_HOUR,
    )

    coord = await setup_coordinator(hass)
    entry_id = coord.entry.entry_id
    coord._grace_until = 0.0

    at = T0
    for _cycle in range(STORM_EXEMPT_PER_HOUR + 2):
        coord._storm_active.clear()
        coord._storm_feed_q.clear()
        for index in range(STORM_DEVICE_THRESHOLD + 2):
            coord._storm_feed(entry_id, f"d{index}", at)
        coord._sweep_storms(at + 30)
        at += 60

    rows = coord.data[DATA_STORMS]
    assert rows
    assert all(row[STORM_DURATION] is not None for row in rows), (
        "a storm row was left open"
    )
    assert coord._is_polling_integration(entry_id, at)


async def test_the_exemption_ignores_an_unfinished_storm(
    hass: HomeAssistant,
):
    """A row a crash left open cannot be updated, so it cannot count."""
    from custom_components.device_sentinel.const import (
        DATA_STORMS,
        STORM_AT,
        STORM_DOMAIN,
        STORM_DURATION,
        STORM_ENTRY,
        STORM_EXEMPT_PER_HOUR,
    )

    coord = await setup_coordinator(hass)
    coord.data[DATA_STORMS] = [
        {
            STORM_AT: T0 + index,
            STORM_ENTRY: "e1",
            STORM_DOMAIN: "poller",
            STORM_DURATION: None,
        }
        for index in range(STORM_EXEMPT_PER_HOUR + 5)
    ]
    assert not coord._is_polling_integration("e1", T0 + 100)
    for row in coord.data[DATA_STORMS]:
        row[STORM_DURATION] = 5.0
    assert coord._is_polling_integration("e1", T0 + 100)


async def test_a_repeated_storm_reads_as_one_line(hass: HomeAssistant):
    """Twenty reloads in an hour are one sentence, not forty."""
    from custom_components.device_sentinel.const import (
        SYS_DEVICES,
        SYS_STORM_CLOSED,
        SYS_STORM_OPEN,
    )

    coord = await setup_coordinator(hass)
    rows = []
    for index in range(20):
        when = T0 + index * 36
        rows.append(_event(SYS_STORM_OPEN, "tplink_router", when))
        rows.append(
            _event(
                SYS_STORM_CLOSED, "tplink_router", when + 5, duration=5.0
            )
        )
        rows[-1][SYS_DEVICES] = 5
    said = coord._house_sentences(rows)
    assert len(said) == 1
    assert said[0].startswith("The tplink_router integration reloaded 20 times")
    assert "the largest affecting 5 devices" in said[0]


async def test_one_storm_keeps_its_own_two_sentences(hass: HomeAssistant):
    """A single reload is not repetition and reads as it always did."""
    from custom_components.device_sentinel.const import (
        SYS_DEVICES,
        SYS_STORM_CLOSED,
        SYS_STORM_OPEN,
    )

    coord = await setup_coordinator(hass)
    closed = _event(SYS_STORM_CLOSED, "reolink", T0 + 5, duration=5.0)
    closed[SYS_DEVICES] = 4
    said = coord._house_sentences(
        [_event(SYS_STORM_OPEN, "reolink", T0), closed]
    )
    assert len(said) == 2
    assert said[0].startswith("The reolink integration reloaded at ")


async def test_an_orphan_closing_is_never_spoken(hass: HomeAssistant):
    """Even beside a real storm on the same integration.

    Counting openings per scope was not enough: the live fleet had a
    genuine mqtt storm and an orphan mqtt closing in the same window,
    and the orphan was spoken anyway.
    """
    from custom_components.device_sentinel.const import (
        SYS_DEVICES,
        SYS_STORM_CLOSED,
        SYS_STORM_OPEN,
    )

    coord = await setup_coordinator(hass)
    good_close = _event(SYS_STORM_CLOSED, "mqtt", T0 + 6, duration=6.0)
    good_close[SYS_DEVICES] = 50
    orphan = _event(SYS_STORM_CLOSED, "mqtt", T0 + 2600, duration=7.0)
    orphan[SYS_DEVICES] = 47
    said = coord._house_sentences(
        [_event(SYS_STORM_OPEN, "mqtt", T0), good_close, orphan]
    )
    assert len(said) == 2
    assert "47 devices" not in " ".join(said)
    assert "50 devices" in " ".join(said)


async def test_a_hostile_device_name_cannot_reach_the_dwell_page(
    hass: HomeAssistant,
):
    """The signal dwell page escaped nothing until 0.12.8.

    A device name is not always the reader's own words: MQTT
    discovery lets a device advertise its own, so an angle bracket
    can arrive from the network. The page is served to a dashboard,
    so raw markup there is script running in the reader's session
    (ruling #231).
    """
    coord = await setup_coordinator(hass)
    evil = "<img src=x onerror=alert(1)>"
    chart = coord._dwell_bar_svg([("d1", evil, 64.0)], 40.0)
    assert "<img" not in chart
    assert "&lt;img" in chart


async def test_a_corrupt_storm_row_cannot_break_the_listener(
    hass: HomeAssistant,
):
    """One malformed row would have stopped event processing.

    The exemption is read inside the event listener, so an
    AttributeError there breaks the device that triggered it. The
    restore path beside it has always checked shape (ruling #231).
    """
    from custom_components.device_sentinel.const import DATA_STORMS

    coord = await setup_coordinator(hass)
    coord.data[DATA_STORMS] = [
        None,
        "not a row",
        {},
        {"entry_id": "e1", "at": "yesterday"},
        {"entry_id": "e1", "at": T0, "duration": 5.0},
    ]
    assert coord._is_polling_integration("e1", T0 + 10) is False
    assert coord._close_storm_row("nobody", T0, 1.0, 1) is False
    coord._trim_storms(T0 + 10)
    assert coord.data[DATA_STORMS] == [
        {"entry_id": "e1", "at": T0, "duration": 5.0}
    ]


def test_an_absurd_uptime_is_refused():
    """An infinity would put the broker's start before the epoch."""
    from custom_components.device_sentinel import transport_mqtt

    read = transport_mqtt._uptime_seconds
    assert read("12355 seconds") == 12355.0
    assert read("0 seconds") == 0.0
    assert read("1e400 seconds") is None
    assert read("nan seconds") is None
    assert read("-1 seconds") is None
    assert read("999999999999999 seconds") is None


async def test_a_poller_is_recognized_once_and_stays_recognized(
    hass: HomeAssistant,
):
    """The loop the reference fleet ran for four hours.

    An integration read as a poller was never fed again, so its
    history stopped accruing, its rows aged out of the hour, the
    verdict lapsed, and it stormed ten more times. The fleet's own
    log shows exactly ten storms an hour for four hours, which is the
    exemption threshold rather than anything the router was doing
    (ruling #232).

    Four hours of a burst every 36 seconds, which is the reference
    integration's own cadence.
    """
    from custom_components.device_sentinel.const import (
        DATA_STORMS,
        DATA_SYSTEM_EVENTS,
        STORM_DEVICE_THRESHOLD,
        STORM_EXEMPT_PER_HOUR,
        SYS_STORM_OPEN,
    )

    coord = await setup_coordinator(hass)
    entry_id = coord.entry.entry_id
    coord._grace_until = 0.0
    before = len(coord.data.get(DATA_SYSTEM_EVENTS) or [])

    at = T0
    for _cycle in range(400):
        coord._storm_active.clear()
        coord._storm_feed_q.clear()
        for index in range(STORM_DEVICE_THRESHOLD + 2):
            coord._storm_feed(entry_id, f"d{index}", at)
        coord._sweep_storms(at + 30)
        at += 36

    events = [
        row
        for row in coord.data[DATA_SYSTEM_EVENTS][before:]
        if row[SYS_KIND] == SYS_STORM_OPEN
    ]
    # Announced while it was still an unknown integration, and never
    # again once it was read as a poller.
    assert len(events) == STORM_EXEMPT_PER_HOUR, (
        f"a poller announced {len(events)} storms over four hours"
    )
    assert coord._is_polling_integration(entry_id, at)
    # Counting continued, which is what makes the verdict hold.
    assert len(coord.data[DATA_STORMS]) > STORM_EXEMPT_PER_HOUR * 4


async def test_an_integration_that_settles_stops_being_a_poller(
    hass: HomeAssistant,
):
    """The recompute still does its job in the other direction."""
    from custom_components.device_sentinel.const import (
        STORM_DEVICE_THRESHOLD,
        STORM_EXEMPT_PER_HOUR,
    )

    coord = await setup_coordinator(hass)
    entry_id = coord.entry.entry_id
    coord._grace_until = 0.0

    at = T0
    for _cycle in range(STORM_EXEMPT_PER_HOUR + 4):
        coord._storm_active.clear()
        coord._storm_feed_q.clear()
        for index in range(STORM_DEVICE_THRESHOLD + 2):
            coord._storm_feed(entry_id, f"d{index}", at)
        coord._sweep_storms(at + 30)
        at += 60
    assert coord._is_polling_integration(entry_id, at)

    # It stops storming. An hour later the verdict lapses on its own.
    assert not coord._is_polling_integration(entry_id, at + 3700)


async def test_a_poller_stamps_no_episode(hass: HomeAssistant):
    """Its devices learn their poll cadence as rhythm.

    That is the whole point of recognising a poller, and it is the
    half that must survive the fix (ruling #232).
    """
    from custom_components.device_sentinel.const import (
        STORM_DEVICE_THRESHOLD,
        STORM_EXEMPT_PER_HOUR,
    )

    coord = await setup_coordinator(hass)
    entry_id = coord.entry.entry_id
    coord._grace_until = 0.0
    stamped: list[str] = []
    coord._stamp_intervention = lambda *a, **k: stamped.append(a[0])

    at = T0
    for _cycle in range(STORM_EXEMPT_PER_HOUR + 6):
        coord._storm_active.clear()
        coord._storm_feed_q.clear()
        for index in range(STORM_DEVICE_THRESHOLD + 2):
            coord._storm_feed(entry_id, f"d{index}", at)
        coord._sweep_storms(at + 30)
        at += 60

    assert len(stamped) == STORM_EXEMPT_PER_HOUR, (
        "a poller kept stamping interventions after being recognised"
    )


async def test_a_poller_says_nothing_in_the_log(
    hass: HomeAssistant, caplog
):
    """The fourth surface a poller is silent on (ruling #232).

    #232 named three, the opening event, the closing event and the
    episode stamp, and the debug line was gated on the report count
    instead. On 17 August the reference fleet wrote 742 of them in
    seven and a half hours, 379 after tplink_router had been
    reclassified, in a log a person reads to find out what is wrong.
    An integration whose bursts are its own polling cadence is
    behaving normally, and normal behaviour is not information.
    """
    from custom_components.device_sentinel.const import (
        STORM_DEVICE_THRESHOLD,
        STORM_EXEMPT_PER_HOUR,
    )

    coord = await setup_coordinator(hass)
    entry_id = coord.entry.entry_id
    coord._grace_until = 0.0

    at = T0
    for _cycle in range(STORM_EXEMPT_PER_HOUR):
        coord._storm_active.clear()
        coord._storm_feed_q.clear()
        for index in range(STORM_DEVICE_THRESHOLD + 2):
            coord._storm_feed(entry_id, f"d{index}", at)
            storm = coord._storm_active.get(entry_id)
            if storm is not None:
                storm["stamps"] += 1
        coord._sweep_storms(at + 30)
        at += 60
    assert coord._is_polling_integration(entry_id, at)

    # Now it is a known poller. Everything after this is its cadence.
    with caplog.at_level(logging.DEBUG, logger="custom_components.device_sentinel"):
        caplog.clear()
        for _cycle in range(4):
            coord._storm_active.clear()
            coord._storm_feed_q.clear()
            for index in range(STORM_DEVICE_THRESHOLD + 2):
                coord._storm_feed(entry_id, f"d{index}", at)
                storm = coord._storm_active.get(entry_id)
                if storm is not None:
                    storm["stamps"] += 1
            coord._sweep_storms(at + 30)
            at += 60
    assert "Storm on" not in caplog.text, (
        "a reclassified poller went on announcing every burst"
    )


async def test_a_real_storm_still_says_so_and_no_longer_claims_an_exclusion(
    hass: HomeAssistant, caplog
):
    """The half that must survive the gate.

    A hub reconnecting is not normal and stays in the log. What
    changed is the wording: a storm excludes nothing from learning
    and has not since taint became the only surviving exclusion
    (rulings #124 and #125), so the count is named for what it is.
    """
    from custom_components.device_sentinel.const import (
        STORM_DEVICE_THRESHOLD,
    )

    coord = await setup_coordinator(hass)
    entry_id = coord.entry.entry_id
    coord._grace_until = 0.0

    with caplog.at_level(logging.DEBUG, logger="custom_components.device_sentinel"):
        for index in range(STORM_DEVICE_THRESHOLD + 2):
            coord._storm_feed(entry_id, f"d{index}", T0)
            storm = coord._storm_active.get(entry_id)
            if storm is not None:
                storm["stamps"] += 1
        coord._sweep_storms(T0 + 30)

    assert "Storm on" in caplog.text
    assert "report(s) inside the burst" in caplog.text
    assert "excluded from learning" not in caplog.text


async def test_storm_rows_are_trimmed_at_two_days(hass: HomeAssistant):
    """Nothing reads them past an hour, so nothing keeps them past two days."""
    from custom_components.device_sentinel.const import (
        DATA_STORMS,
        STORM_KEEP_SECONDS,
    )

    coord = await setup_coordinator(hass)
    coord.data[DATA_STORMS] = [
        {"at": T0 - STORM_KEEP_SECONDS - 60, "entry_id": "e", "duration": 5.0},
        {"at": T0 - 3600, "entry_id": "e", "duration": 5.0},
    ]
    coord._trim_storms(T0)
    assert len(coord.data[DATA_STORMS]) == 1
    assert STORM_KEEP_SECONDS == 172800.0
