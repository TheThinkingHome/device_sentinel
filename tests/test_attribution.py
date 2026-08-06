# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_attribution.py, Version: 0.12.6 (2026-08-06)

"""What explains an incident, and what a flood reads as.

The shape replayed here is the one the reference fleet produced on
2026-08-06: a sixteen-minute broker outage took 74 devices, they
recovered inside 8.5 seconds, and the brief gave four different
explanations for one event, with devices resolving in the same
millisecond disagreeing. The cause was borrowed from each device's
most recent silence episode, whenever that was (ruling #228).
"""

from __future__ import annotations

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
