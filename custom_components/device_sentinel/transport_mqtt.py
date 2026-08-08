# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: transport_mqtt.py, Version: 0.12.16 (2026-08-08)

"""The MQTT broker itself, watched directly.

Not a stack. The broker sits underneath every MQTT stack and belongs
to none of them, which is why this is its own file rather than part
of stack_z2m.py: a house running Tasmota or ESPHome over MQTT and no
Zigbee at all has a broker, and it can fail the same way.

WHY IT EXISTS. A bridge reader cannot see its own broker die. When
the broker stops, nothing delivers Zigbee2MQTT's last will, because
the broker is the deliverer, so the bridge's last known state stands
and no transition is recorded. Measured on the reference fleet on
2026-08-06: sixteen minutes with the broker stopped took 75 devices
unavailable and swelled the problem list from 3 to 75, and the system
events log recorded nothing at all while the bridge sensor read
running throughout. The daily brief would have described a night in
which nothing happened. That is the failure this project exists to
catch, occurring inside the project (ruling #224).

TWO SIGNALS, DIFFERENT JOBS. A regression, where the uptime value is
lower than the last one seen, means the broker restarted, and the
value says when: the start is the arrival minus the uptime. It needs
no continuity of its own, which is why it catches an outage that
spanned a restart of Home Assistant, when nothing here was running to
observe the silence. Silence past a threshold covers the other case,
a broker that dies while we stay alive, which is precisely the case
above and which the regression alone would miss until the broker came
back.

THE THRESHOLD IS LEARNED, NOT SET. The cadence is read from the
arrivals themselves and the threshold is a multiple of it, so a
broker publishing on a different interval is judged correctly without
being asked about. Measured on the reference broker: 2,363 intervals,
median 9.997 seconds, maximum 10.350, standard deviation 0.082. The
multiple is far outside anything that spread produces.

EVERYTHING IS GUARDED. Nothing is claimed until two arrivals have
parsed, so a broker with $SYS switched off, or one whose payload is
worded differently, leaves the state unknown forever and costs
nothing. A watch that cannot read reports unknown, which every
consumer treats as no opinion.
"""

from __future__ import annotations

import statistics
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import (
    BROKER_ARM_SAMPLES,
    BROKER_DOWN,
    BROKER_RUNNING,
    BROKER_SILENCE_FLOOR_SECONDS,
    BROKER_SILENCE_MULTIPLE,
    BROKER_START_TOLERANCE_SECONDS,
    BROKER_TOPIC_UPTIME,
    BROKER_UPTIME_CEILING,
    BROKER_UNKNOWN,
    LOGGER,
)

# How many intervals the cadence is taken from. Enough that one odd
# arrival cannot move it, short enough that a broker whose interval
# is changed is followed within a couple of minutes.
_CADENCE_SAMPLES = 12


class MQTTBrokerReader:
    """Hold the broker's liveness, read from its own uptime topic."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Prepare the reader. Nothing is subscribed until start."""
        self._hass = hass
        self._unsubs: list[Any] = []
        self._uptime: float | None = None
        self._last_heard: float | None = None
        self._last_heard_iso: str | None = None
        self._intervals: list[float] = []
        self._arrivals = 0
        self._started_at: float | None = None

    async def async_start(self) -> bool:
        """Subscribe to the uptime topic. Never raises.

        A broker that is not up yet is not a failure: MQTT may come up
        after Device Sentinel does, and the topic is published on an
        interval rather than retained, so the first reading simply
        arrives when it arrives (ruling #146).

        The presence of a loaded MQTT entry is checked before waiting
        for its client. Waiting is what a bridge reader does, and it
        is safe there because a bridge reader only starts where a
        bridge device was found, which means MQTT is configured. This
        watch starts everywhere, so on a house with no MQTT at all
        the wait would never return and setup would never finish.
        """
        try:
            if not any(
                entry.state is ConfigEntryState.LOADED
                for entry in self._hass.config_entries.async_entries("mqtt")
            ):
                LOGGER.debug(
                    "Device Sentinel: no MQTT integration, so the "
                    "broker watch stays unknown"
                )
                return False
            if not await mqtt.async_wait_for_mqtt_client(self._hass):
                LOGGER.debug(
                    "Device Sentinel: no MQTT client, so the broker "
                    "watch stays unknown"
                )
                return False
            self._unsubs.append(
                await mqtt.async_subscribe(
                    self._hass, BROKER_TOPIC_UPTIME, self._on_uptime
                )
            )
        except Exception as err:  # noqa: BLE001 - a reader never raises up
            LOGGER.debug(
                "Device Sentinel: could not watch %s, so the broker "
                "state stays unknown (%s)",
                BROKER_TOPIC_UPTIME,
    BROKER_UPTIME_CEILING,
                err,
            )
            return False
        return True

    @callback
    def async_stop(self) -> None:
        """Drop every subscription."""
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception as err:  # noqa: BLE001 - never raise on teardown
                LOGGER.debug(
                    "Device Sentinel: broker unsubscribe failed on "
                    "teardown, ignoring (%s)",
                    err,
                )
        self._unsubs.clear()

    @property
    def armed(self) -> bool:
        """Return whether enough has been heard to claim anything."""
        return self._arrivals >= BROKER_ARM_SAMPLES

    @property
    def cadence(self) -> float | None:
        """Return the observed publish interval, or None.

        The median rather than the mean, so a single long interval
        after a reconnect does not stretch the threshold.
        """
        if len(self._intervals) < BROKER_ARM_SAMPLES - 1:
            return None
        return statistics.median(self._intervals)

    @property
    def threshold(self) -> float | None:
        """Return the silence that would count as the broker gone."""
        cadence = self.cadence
        if cadence is None:
            return None
        return max(
            BROKER_SILENCE_FLOOR_SECONDS, cadence * BROKER_SILENCE_MULTIPLE
        )

    @property
    def state(self) -> str:
        """Return running, down, or unknown.

        Unknown until armed, and unknown forever on a broker that
        publishes nothing here. Down once the silence passes the
        learned threshold, which is the only way a broker that dies
        while we stay alive can be seen at all.
        """
        if not self.armed or self._last_heard is None:
            return BROKER_UNKNOWN
        threshold = self.threshold
        if threshold is None:
            return BROKER_UNKNOWN
        silence = dt_util.utcnow().timestamp() - self._last_heard
        return BROKER_DOWN if silence > threshold else BROKER_RUNNING

    @property
    def uptime(self) -> float | None:
        """Return the last uptime value published, in seconds."""
        return self._uptime

    @property
    def started_at(self) -> float | None:
        """Return when the broker came up, as an epoch.

        Computed from an arrival and its uptime rather than observed,
        which is what makes a restart legible after the fact even
        where nothing was running to watch it happen. It answers a
        question that had no answer before: whether the broker has
        been restarting unnoticed.
        """
        return self._started_at

    @property
    def last_heard(self) -> str | None:
        """Return when the last message arrived, as an ISO string."""
        return self._last_heard_iso

    @callback
    def _on_uptime(self, msg: mqtt.ReceiveMessage) -> None:
        """Record one arrival and learn the cadence from it."""
        seconds = _uptime_seconds(msg.payload)
        if seconds is None:
            return
        now = dt_util.utcnow()
        arrived = now.timestamp()
        if self._last_heard is not None:
            interval = arrived - self._last_heard
            if interval > 0:
                self._intervals.append(interval)
                del self._intervals[:-_CADENCE_SAMPLES]
        self._arrivals += 1
        self._uptime = seconds
        self._last_heard = arrived
        self._last_heard_iso = now.isoformat()
        self._started_at = arrived - seconds

    def regressed_since(self, known_start: float | None) -> bool:
        """Return whether the broker has restarted since known_start.

        The primary signal. A start later than the one last recorded
        means the broker went down and came back, whether or not
        anything was running to watch it. The tolerance is measured
        rather than guessed: the computed start drifts by up to three
        seconds when nothing has happened, because it is an arrival
        minus a whole-second value, while a real restart moves it by
        hundreds.
        """
        if self._started_at is None or known_start is None:
            return False
        return (
            self._started_at - known_start > BROKER_START_TOLERANCE_SECONDS
        )


def _uptime_seconds(payload: Any) -> float | None:
    """Return the seconds out of a payload like "12355 seconds".

    The wording is Mosquitto's and is not a contract, so the number is
    taken as the first token and anything else is refused rather than
    guessed at. A broker that publishes something else here leaves the
    watch unarmed, which is the correct outcome for a reader that
    cannot read its source.
    """
    if payload is None:
        return None
    if isinstance(payload, bytes):
        text = payload.decode("utf-8", "ignore")
    else:
        text = str(payload)
    token = text.strip().split(" ")[0] if text.strip() else ""
    try:
        value = float(token)
    except ValueError:
        return None
    # Finite and not absurd. A broker cannot have been up longer than
    # this and an infinity would put its computed start before the
    # epoch, which every consumer would then read as a restart that
    # never happened (ruling #231).
    # value != value is the NaN test: NaN is the one float that is
    # not equal to itself, and a JSON payload can carry one.
    if value < 0 or value != value or value > BROKER_UPTIME_CEILING:
        return None
    return value
