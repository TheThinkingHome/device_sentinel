# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: stack_z2m.py, Version: 0.12.1 (2026-08-05)

"""Zigbee2MQTT: everything Device Sentinel knows about this stack.

One file per coordinator stack (ruling #218). Before this file the
same knowledge sat in three places: the reader in bridge.py, the
bridge test in interventions.py, and a branch in the middle of
coordinator.py's registry walk. Adding a stack now touches one new
file and one line in stacks.py.

Three questions this module answers, and every stack module answers
the same three. Does this device prove the stack is present
(`detects`). Does this stack own a device on that integration domain
(`owns_domain`). Give me a reader for it, or None (`make_reader`).

Z2M is the stack this project was developed against and the only one
with a reader today. It is the clean case: two retained MQTT topics,
bridge/state (online or offline) and bridge/info (which carries
permit_join and the absolute permit_join_end). Retained means the
current state arrives the moment we subscribe, so a restart in the
middle of a pairing window loses nothing.

Everything in the reader is guarded. If MQTT is not available, if the
topics never arrive, or if a payload will not parse, the state stays
unknown and nothing raises. A bridge reader that cannot read simply
reports unknown, and the detector that reads it goes back to judging
by how long the silence lasted, which is what it did before this
reader existed. So a reader that fails can only cost a pairing it
would have caught, and can never make a judgment worse than the one
the project already trusted (rulings #138 and #147).
"""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    BRIDGE_BINDING,
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BRIDGE_UNKNOWN,
    LOGGER,
    STACK_Z2M,
    Z2M_BASE_TOPIC_DEFAULT,
    Z2M_BRIDGE_MANUFACTURER,
    Z2M_BRIDGE_MODEL,
    Z2M_BRIDGE_NAME_MARK,
    Z2M_TOPIC_INFO,
    Z2M_TOPIC_STATE,
)

STACK = STACK_Z2M


def owns_domain(domain: str) -> bool:
    """Return whether a device on this integration domain is Z2M's.

    Z2M is the one stack whose own name is not its integration
    domain: its devices arrive through MQTT discovery and carry the
    `mqtt` domain, shared with every other MQTT thing in the house.
    That is why presence is told by the bridge device rather than by
    this test (ruling #139), and why ownership is the widest claim
    this stack can make about a single device: a non-Z2M MQTT device
    reads as Z2M's here. The only consequence is a discarded gap,
    which is the fail-safe direction (ruling #145).
    """
    return domain == "mqtt"


def detects(domain: str, device: dr.DeviceEntry) -> bool:
    """Return whether this device proves Zigbee2MQTT is running.

    The bridge device is the tell, never a count of mqtt devices
    (rulings #139 and #143).
    """
    return owns_domain(domain) and is_bridge_device(device)


def make_reader(hass: HomeAssistant) -> Z2MBridgeReader:
    """Return a reader for this stack's bridge."""
    return Z2MBridgeReader(hass)


def is_bridge_device(device: dr.DeviceEntry) -> bool:
    """Recognise the Zigbee2MQTT bridge device (ruling #143).

    Z2M publishes its bridge through MQTT discovery with a name
    ending "Zigbee2MQTT Bridge", or a model of "Bridge" under the
    manufacturer "Zigbee2MQTT". The name is checked first because
    it holds whatever coordinator hardware sits behind it, so the
    tell does not depend on any one adapter. This is the clean
    signal that Z2M is running, since the mqtt domain alone cannot
    tell Z2M apart from any other MQTT device (ruling #139).
    """
    name = device.name_by_user or device.name or ""
    if Z2M_BRIDGE_NAME_MARK in name:
        return True
    return (
        device.model == Z2M_BRIDGE_MODEL
        and device.manufacturer == Z2M_BRIDGE_MANUFACTURER
    )


class Z2MBridgeReader:
    """Holds the current Z2M bridge state, fed by its retained topics.

    The reader owns no judgment. It records what the bridge says about
    itself and exposes it as a small piece of state (running, binding,
    down, or unknown) plus the pairing window end when one is open. The
    sensor displays it and the pairing detector reads it; neither is
    coupled to how the state arrives.
    """

    def __init__(
        self, hass: HomeAssistant, base_topic: str = Z2M_BASE_TOPIC_DEFAULT
    ) -> None:
        """Initialize the reader for one Z2M bridge."""
        self._hass = hass
        self._base = base_topic
        self._unsubs: list[Any] = []
        # What we have heard. online is None until bridge/state arrives;
        # permit_join and its end come from bridge/info. last_heard is
        # the timestamp of the most recent message from either topic.
        self._online: bool | None = None
        self._permit_join: bool = False
        self._permit_join_end: str | None = None
        self._last_heard: str | None = None
        # When a pairing window last closed, as a UTC timestamp. A
        # device paired near the end of a window may not report until
        # just after it closes, so the detector counts a recovery in
        # a short window after this moment as pairing too, rather
        # than crediting the device with recovering on its own
        # (ruling #145). None until a window has closed.
        self._pairing_closed_at: float | None = None

    @property
    def stack(self) -> str:
        """Return the stack this reader speaks for."""
        return STACK_Z2M

    @property
    def base_topic(self) -> str:
        """Return the configured Z2M base topic."""
        return self._base

    @property
    def last_heard(self) -> str | None:
        """Return when the bridge was last heard from, if ever."""
        return self._last_heard

    @property
    def permit_join_end(self) -> str | None:
        """Return the absolute end of the open pairing window, if open."""
        if self.state == BRIDGE_BINDING:
            return self._permit_join_end
        return None

    @property
    def state(self) -> str:
        """Return the bridge state a person would read.

        The order matters. Nothing heard at all is unknown. A bridge
        that has said it is offline, or that has never confirmed it is
        online, is down. An online bridge with pairing open is binding;
        otherwise it is running. Pairing is only meaningful on a bridge
        we know to be online, so an open permit_join with no online
        confirmation still reads down rather than binding.
        """
        if self._online is None and self._last_heard is None:
            return BRIDGE_UNKNOWN
        if self._online is not True:
            return BRIDGE_DOWN
        if self._permit_join:
            return BRIDGE_BINDING
        return BRIDGE_RUNNING

    @property
    def pairing_open(self) -> bool:
        """Return whether a pairing window is currently open.

        This is what the shared detector reads. It is deliberately
        derived from state, so a bridge that is down never reports
        pairing open even if a stale info payload said permit_join.
        """
        return self.state == BRIDGE_BINDING

    def pairing_active_within(self, grace_seconds: float, now: float) -> bool:
        """Return whether pairing was open now or within a recent grace.

        The detector asks this when a device recovers: a device that
        comes back while a pairing window is open, or within a short
        grace after it closed, recovered because somebody was pairing
        it, not on its own. That silence is then discarded instead of
        being learned, because its ending measures the hand rather
        than the device (ruling #145). Open now is the clear case;
        the grace covers a device that reports just after the window
        closes, which the observed publish lag on a real bridge makes
        a real case.
        """
        if self.pairing_open:
            return True
        if self._pairing_closed_at is None:
            return False
        return (now - self._pairing_closed_at) <= grace_seconds

    async def async_start(self) -> bool:
        """Subscribe to the bridge topics once MQTT is available.

        Returns True if the subscriptions were established. Waits for
        the MQTT client rather than assuming it is up, because Device
        Sentinel may start before MQTT. Any failure is logged and
        swallowed: the reader simply stays at unknown, and every
        consumer treats unknown as "cannot tell", which is safe.
        """
        try:
            await mqtt.async_wait_for_mqtt_client(self._hass)
        except Exception as err:  # noqa: BLE001 - any failure means no MQTT
            LOGGER.warning(
                "Device Sentinel: MQTT client unavailable, bridge "
                "state will read unknown (%s)",
                err,
            )
            return False
        try:
            self._unsubs.append(
                await mqtt.async_subscribe(
                    self._hass,
                    f"{self._base}/{Z2M_TOPIC_STATE}",
                    self._on_state,
                )
            )
            self._unsubs.append(
                await mqtt.async_subscribe(
                    self._hass,
                    f"{self._base}/{Z2M_TOPIC_INFO}",
                    self._on_info,
                )
            )
        except Exception as err:  # noqa: BLE001 - subscribe can fail many ways
            LOGGER.warning(
                "Device Sentinel: could not subscribe to Z2M bridge "
                "topics, state will read unknown (%s)",
                err,
            )
            self.async_stop()
            return False
        return True

    @callback
    def async_stop(self) -> None:
        """Release the subscriptions."""
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception as err:  # noqa: BLE001 - never raise on teardown
                LOGGER.debug(
                    "Device Sentinel: bridge unsubscribe failed on "
                    "teardown, ignoring (%s)",
                    err,
                )
        self._unsubs.clear()

    @callback
    def _on_state(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle bridge/state: the payload is online or offline."""
        self._last_heard = dt_util.utcnow().isoformat()
        payload = _decode(msg.payload)
        # bridge/state is sometimes a bare string, sometimes JSON with a
        # state field. Accept either without letting a surprise raise.
        text = payload
        if isinstance(payload, str) and payload.strip().startswith("{"):
            data = _load(payload)
            if isinstance(data, dict):
                text = data.get("state", "")
        self._online = isinstance(text, str) and text.strip() == "online"

    @callback
    def _on_info(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle bridge/info: read permit_join and permit_join_end.

        Reads the absolute permit_join_end, never the legacy
        permit_join_timeout. A payload that will not parse leaves the
        prior pairing state untouched rather than dropping it.
        """
        self._last_heard = dt_util.utcnow().isoformat()
        data = _load(_decode(msg.payload))
        if not isinstance(data, dict):
            return
        was_open = self._permit_join
        self._permit_join = bool(data.get("permit_join", False))
        # Note the moment a window closes, so a device that reports
        # just after it can still be credited to the pairing rather
        # than to itself (ruling #145).
        if was_open and not self._permit_join:
            self._pairing_closed_at = dt_util.utcnow().timestamp()
        end = data.get("permit_join_end")
        self._permit_join_end = str(end) if end is not None else None


def _decode(payload: Any) -> str:
    """Return a string from an MQTT payload that may be bytes."""
    if isinstance(payload, bytes):
        try:
            return payload.decode("utf-8")
        except Exception as err:  # noqa: BLE001 - undecodable is not fatal
            LOGGER.debug("Undecodable MQTT payload ignored: %s", err)
            return ""
    return payload if isinstance(payload, str) else ""


def _load(text: str) -> Any:
    """Parse JSON, returning None rather than raising on bad input."""
    try:
        return json.loads(text)
    except Exception as err:  # noqa: BLE001 - malformed reads as nothing
        LOGGER.debug("Malformed MQTT payload ignored: %s", err)
        return None
