# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: stack_z2m.py, Version: 0.30.9 (2026-11-27)

"""Zigbee2MQTT: everything Device Sentinel knows about this stack.

One file per coordinator stack, so adding a stack touches one new
file and one line in stacks.py (rule STACK-01).

Three questions this module answers, and every stack module answers
the same three. Does this device prove the stack is present
(`detects`). Does this stack own a device on that integration domain
(`owns_domain`). Give me a reader for it, or None (`make_reader`).

Z2M is the one stack that publishes a pairing window. It is the
clean case: two retained MQTT topics,
bridge/state (online or offline) and bridge/info (which carries
permit_join and the absolute permit_join_end). Retained means the
current state arrives the moment Device Sentinel subscribes, so a restart in the
middle of a pairing window loses nothing.

A third topic, bridge/event, names the device that joins while the
window is open, so a re-pair restarts that one device's 42-day count
rather than every device that happens to come back during the window
(rule FRZ-05). It is not retained: a window already open when Device
Sentinel starts has joins it never heard, and for that window the
detector falls back to judging by the silence.

Everything in the reader is guarded. If MQTT is not available, if the
topics never arrive, or if a payload will not parse, the state stays
unknown and nothing raises. A bridge reader that cannot read simply
reports unknown, and the detector that reads it goes back to judging
by how long the silence lasted. So a reader that fails can only cost
a pairing it would have caught, and can never make a judgment worse
than one made without it (rule FRZ-15).
"""

from __future__ import annotations

import json
from math import isfinite
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from homeassistant.util import dt as dt_util

from .const import (
    BRIDGE_BINDING,
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BRIDGE_UNKNOWN,
    LOGGER,
    PAIRING_GRACE_SECONDS_DEFAULT,
    STACK_Z2M,
    Z2M_BASE_TOPIC_DEFAULT,
    Z2M_BRIDGE_MANUFACTURER,
    Z2M_BRIDGE_MODEL,
    Z2M_BRIDGE_NAME_MARK,
    Z2M_IDENTIFIER_MARK,
    Z2M_TOPIC_AVAILABILITY,
    Z2M_TOPIC_AVAILABILITY_LEAF,
    Z2M_EVENT_JOINED,
    Z2M_TOPIC_DEVICES,
    Z2M_TOPIC_EVENT,
    Z2M_TOPIC_INFO,
    Z2M_TOPIC_STATE,
)
from .device_fields import device_field, identifier_values

STACK = STACK_Z2M

# This stack shares its domain. Z2M's devices arrive through MQTT
# discovery and carry the mqtt domain, which anything else publishing
# its own discovery carries too, such as an NSPanel Pro on MQTT and Wi-Fi. Owning the domain is
# therefore not enough to own a device, and `device_key` is asked as
# well. The other three stacks own their domain outright.
SHARED_DOMAIN = True


def owns_domain(domain: str) -> bool:
    """Return whether a device on this integration domain is Z2M's.

    Z2M is the one stack whose own name is not its integration
    domain: its devices arrive through MQTT discovery and carry the
    `mqtt` domain, shared with every other MQTT thing in the house.
    Presence is told by the bridge device rather than by this test
    (rule STACK-01). This only selects the stack's resolver; actual
    ownership requires a registry parent or an unambiguous device roll
    (rule STACK-03), so unrelated MQTT devices are not claimed.
    """
    return domain == "mqtt"


def detects(domain: str, device: dr.DeviceEntry) -> bool:
    """Return whether this device proves Zigbee2MQTT is running.

    The bridge device is the tell, never a count of mqtt devices
    (rule STACK-01).
    """
    return owns_domain(domain) and is_bridge_device(device)


def is_plumbing(domain: str, device: dr.DeviceEntry) -> bool:
    """Return whether this device is the stack itself, not hardware.

    Zigbee2MQTT publishes its bridge through MQTT discovery, so the
    registry holds the coordinator as an ordinary device on the mqtt
    domain. It is not ordinary. It speaks only when something changes,
    so a rhythm learned from it measures the intervals between
    unrelated events rather than a heartbeat, anywhere from 16 to 71
    hours, and it can read frozen while the Bridge sensor for the same
    coordinator reads running. Watched twice, the coordinator gives two
    answers that disagree (rule WATCH-05).

    This is not `detects`. That question asks which device proves the
    stack is present, and for ZHA, Z-Wave and Matter every device on
    the domain answers yes. This question asks whether the device is
    the plumbing, and only Z2M has a device that is.
    """
    return owns_domain(domain) and is_bridge_device(device)


def device_key(device: Any) -> str | None:
    """Return the IEEE address Zigbee2MQTT knows this device by.

    Z2M publishes through MQTT discovery with an identifier of the
    shape ('mqtt', 'zigbee2mqtt_0x282c02bfffeafa5b'), so the address
    is the tail of the second element. It is the only reliable join:
    matching on name fails where a switch carries one name in Home
    Assistant and another in Zigbee2MQTT (rule STACK-03). An MQTT device that is not Z2M's, such
    as a panel publishing its own discovery, has no such identifier
    and returns None, which rejects it without a special case.
    """
    for domain, parts in identifier_values(device):
        if domain != "mqtt":
            continue
        # Any length, since an integration may register more than a
        # pair.
        for value in parts:
            if not isinstance(value, str):
                continue
            _, marker, address = value.partition(Z2M_IDENTIFIER_MARK)
            if marker and address.startswith("0x"):
                return address
    return None


def make_reader(hass: HomeAssistant) -> Z2MBridgeReader:
    """Return a reader for this stack's bridge."""
    return Z2MBridgeReader(hass)


def is_instance(key: str) -> bool:
    """Whether a bridge scope belongs to this stack (rule STACK-03)."""
    return key == STACK or key.startswith(f"{STACK}:")


def instance_label(reader: Z2MBridgeReader | None) -> str:
    """Show the exact MQTT prefix, or a readable name before discovery."""
    if reader is not None:
        return reader.base_topic or reader.name or "Zigbee2MQTT"
    return "Zigbee2MQTT"


# How deep a bridge's base topic is looked for: "zigbee2mqtt" is one
# level, "home/zigbee2mqtt" two, up to "a/b/c/zigbee2mqtt" (rule STACK-03).
# MQTT's "+" stands for exactly one level and "#" only ends a topic, so
# each depth is its own subscription; one with nothing behind it costs
# the broker nothing.
Z2M_TOPIC_DEPTHS = 4
_BRIDGE_ID_MARK = f"{Z2M_IDENTIFIER_MARK}bridge_"


def coordinator_address(device: Any) -> str | None:
    """The coordinator address in a bridge device's MQTT identifier.

    Zigbee2MQTT names its bridge device "zigbee2mqtt_bridge_" and the
    coordinator's address, so it survives a rename (rule STACK-03).
    """
    for domain, parts in identifier_values(device):
        if domain != "mqtt":
            continue
        for value in parts:
            if isinstance(value, str) and value.startswith(_BRIDGE_ID_MARK):
                address = value[len(_BRIDGE_ID_MARK):].strip().lower()
                if address:
                    return address
    return None


class Z2MTopicFinder:
    """Each bridge's base topic, from the retained bridge/info message every
    Zigbee2MQTT bridge publishes, by its coordinator address (rule STACK-03).

    Only MQTT's public subscribe is used. A message that names no
    coordinator is not Zigbee2MQTT's and is ignored, and an address two
    topics claim gives no topic.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Hold the subscriptions and what they have heard."""
        self._hass = hass
        self._unsubs: list[Any] = []
        self._address_of: dict[str, str] = {}

    @property
    def started(self) -> bool:
        """Whether the subscriptions are in place."""
        return bool(self._unsubs)

    async def async_start(self) -> bool:
        """Subscribe at each depth; False where MQTT is not there yet."""
        if self._unsubs:
            return True
        if not any(
            entry.state is ConfigEntryState.LOADED
            for entry in self._hass.config_entries.async_entries("mqtt")
        ):
            return False
        try:
            for depth in range(1, Z2M_TOPIC_DEPTHS + 1):
                topic = "/".join(["+"] * depth) + f"/{Z2M_TOPIC_INFO}"
                self._unsubs.append(
                    await mqtt.async_subscribe(self._hass, topic, self._on_info)
                )
        except Exception as err:  # noqa: BLE001 - asked again next time
            LOGGER.debug("Zigbee2MQTT topic search could not subscribe: %s", err)
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
                LOGGER.debug("Zigbee2MQTT topic search unsubscribe failed: %s", err)
        self._unsubs.clear()

    @callback
    def _on_info(self, msg: Any) -> None:
        """Note which base topic speaks for which coordinator."""
        topic = getattr(msg, "topic", None)
        suffix = f"/{Z2M_TOPIC_INFO}"
        if not isinstance(topic, str) or not topic.endswith(suffix):
            return
        base = topic[: -len(suffix)]
        text = _decode(msg.payload)
        if not text.strip():
            # A retained message cleared: that bridge is gone.
            self._address_of.pop(base, None)
            return
        data = _load(text)
        coordinator = data.get("coordinator") if isinstance(data, dict) else None
        address = coordinator.get("ieee_address") if isinstance(coordinator, dict) else None
        if not isinstance(address, str) or not address.strip():
            return
        self._address_of[base] = address.strip().lower()

    def base_for(self, address: str | None) -> str | None:
        """The one base topic for this coordinator, or None."""
        if not address:
            return None
        bases = [base for base, held in self._address_of.items() if held == address]
        return bases[0] if len(bases) == 1 else None


def make_finder(hass: HomeAssistant) -> Z2MTopicFinder:
    """Return the base topic search for this stack (rule STACK-03)."""
    return Z2MTopicFinder(hass)


def make_readers(
    hass: HomeAssistant, finder: Z2MTopicFinder | None = None
) -> dict[str, Z2MBridgeReader]:
    """Discover every registry bridge without assuming its topic (rule STACK-03)."""
    readers: dict[str, Z2MBridgeReader] = {}
    registry = dr.async_get(hass)
    devices = {
        device.id: device
        for entry in hass.config_entries.async_entries("mqtt")
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
    }
    found: list[tuple[Any, str | None]] = []
    for device in devices.values():
        if not is_bridge_device(device) or device.disabled_by is not None:
            continue
        address = coordinator_address(device)
        if address is None:
            continue
        found.append((device, finder.base_for(address) if finder is not None else None))
    # The bridge on the default topic keeps the scope, Bridge sensor and
    # saved outages older releases gave it, so a house with one bridge on
    # zigbee2mqtt sees no change; any other bridge is named by its own
    # registry device, so adding or removing a bridge renames none of
    # the others (rule STACK-03).
    # A bridge whose topic is not known yet is pending: it holds on to a
    # reader it already has, and gets none, and no sensor, until its topic
    # is known, since that decides its scope.
    for device, base in found:
        key = STACK if base == Z2M_BASE_TOPIC_DEFAULT else f"{STACK}:{device.id}"
        reader = Z2MBridgeReader(hass, base)
        reader.pending = base is None
        reader.bridge_device_id = device.id
        reader.instance_key = key
        reader.name = device.name_by_user or device.name
        readers[key] = reader
    return readers


def reader_for_device(
    readers: dict[str, Any], hass: HomeAssistant, device_id: str
) -> Any | None:
    """Use the registry parent first, then an unambiguous IEEE (rule STACK-03)."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    key = device_key(device)
    candidates = [reader for scope, reader in readers.items() if is_instance(scope)]
    parent = device_field(device, "via_device_id")
    if parent is not None:
        matches = [reader for reader in candidates if getattr(reader, "bridge_device_id", None) == parent]
        # A known parent must never fall through to another bridge's old roll.
        if matches or any(getattr(reader, "bridge_device_id", None) for reader in candidates):
            return matches[0] if len(matches) == 1 else None
    if key:
        matches = [reader for reader in candidates if callable(getattr(reader, "has_device", None)) and reader.has_device(key)]
        if matches:
            return matches[0] if len(matches) == 1 else None
    # Legacy readers are used only by callers with no discovered bridge.
    legacy = readers.get(STACK)
    return legacy if legacy is not None and getattr(legacy, "bridge_device_id", None) is None else None


def is_bridge_device(device: dr.DeviceEntry) -> bool:
    """Recognize the Zigbee2MQTT bridge device (rule STACK-01).

    The MQTT identifier survives display-name changes. Manufacturer/model
    and the original bridge name also recognise older discovery data;
    the shared mqtt domain alone never proves the stack is present.
    """
    for domain, parts in identifier_values(device):
        if domain == "mqtt" and any(
            isinstance(value, str) and value.startswith(f"{Z2M_IDENTIFIER_MARK}bridge_")
            for value in parts
        ):
            return True
    name = device.name_by_user or device.name or ""
    if isinstance(name, str) and Z2M_BRIDGE_NAME_MARK in name:
        return True
    return (
        device_field(device, "model") == Z2M_BRIDGE_MODEL
        and device_field(device, "manufacturer") == Z2M_BRIDGE_MANUFACTURER
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
        self, hass: HomeAssistant, base_topic: str | None = Z2M_BASE_TOPIC_DEFAULT
    ) -> None:
        """Initialize the reader for one Z2M bridge."""
        self._hass = hass
        self._base = base_topic
        self.bridge_device_id: str | None = None
        self.pending = False
        self.instance_key = STACK
        self.name: str | None = None
        self._unsubs: list[Any] = []
        # What the reader has heard. online is None until bridge/state arrives;
        # permit_join and its end come from bridge/info. last_heard is
        # the timestamp of the most recent message from either topic.
        self._online: bool | None = None
        self.went_offline_at: float | None = None
        self.came_online_at: float | None = None
        self._permit_join: bool = False
        self._permit_join_end: str | None = None
        self._permit_join_deadline: float | None = None
        self._last_heard: str | None = None
        # When a pairing window last closed, as a UTC timestamp. A
        # device paired near the end of a window may not report until
        # just after it closes, so the detector counts a recovery in
        # a short window after this moment as pairing too, rather
        # than crediting the device with recovering on its own
        # (rule FRZ-16). None until a window has closed.
        self._pairing_closed_at: float | None = None
        # Joins (rule FRZ-05). The recorder is the coordinator's, given
        # after the reader is made, and is called with the registry id
        # of a device that joined while pairing was open. joins_live is
        # set once bridge/event is subscribed; info_heard once a
        # bridge/info has been read, so the retained one that arrives at
        # subscribe is told apart from a window opening later. A window
        # whose opening was heard live, with bridge/event already
        # subscribed, is one whose joins were all heard.
        # When the bridge last said pairing opened or closed, as a UTC
        # timestamp, so the window is dated from the bridge's own
        # message rather than from the next check (rule FRZ-16).
        self._pairing_changed_at: float | None = None
        self._join_recorder: Any = None
        self._joins_live: bool = False
        self._info_heard: bool = False
        self._window_heard: bool = False
        # Reachability. Zigbee2MQTT publishes its own verdict on every
        # device to <name>/availability, retained, and the verdict is
        # keyed by friendly name while Home Assistant knows a device
        # by its IEEE address. bridge/devices is the only thing that
        # joins the two, and it is also what rejects a topic with no
        # device behind it: a group, or a retained topic left by a
        # device that was renamed or removed (rule STACK-03).
        self._availability: dict[str, tuple[str, str]] = {}
        self._devices_by_name: dict[str, dict[str, Any]] = {}
        # How long Z2M waits before it calls a device offline, read
        # from the bridge rather than assumed, because it is a per
        # install setting and the two classes differ by two orders of
        # magnitude. A mains device is pinged; a sleeping end device
        # cannot be, so it is judged on silence alone.
        self._availability_enabled: bool | None = None
        self._active_timeout: int | None = None
        self._passive_timeout: int | None = None
        # Where the coordinator is, from bridge/info's serial port: a
        # network coordinator reads tcp://host:port, which
        # names the device a coordinator's own integration shows.
        self._serial_port: str | None = None
        # The coordinator's hardware and the network it runs, from the
        # same bridge/info, for the Networks tab's network page. Shown,
        # never judged (rule DASH-17).
        self._coordinator_type: str | None = None
        self._coordinator_firmware: str | None = None
        self._channel: int | None = None
        self._z2m_version: str | None = None

    @property
    def hardware(self) -> dict[str, Any]:
        """The coordinator and network as bridge/info last gave them.

        Each field None until Zigbee2MQTT has said it. Read only: a
        person changes these in Zigbee2MQTT (rule STACK-13).
        """
        return {
            "type": self._coordinator_type,
            "firmware": self._coordinator_firmware,
            "channel": self._channel,
            "version": self._z2m_version,
            "port": self._serial_port,
        }

    @property
    def serial_port(self) -> str | None:
        """The coordinator's port as Zigbee2MQTT reports it, or None."""
        return self._serial_port

    def zigbee_role(self, ieee: str) -> str | None:
        """What Zigbee2MQTT calls a device in its network: "Router",
        "EndDevice" or "Coordinator", or None if it does not say."""
        for entry in self._devices_by_name.values():
            if entry.get("ieee_address") == ieee:
                role = entry.get("type")
                return role if isinstance(role, str) else None
        return None

    def has_device(self, ieee: str) -> bool:
        """Whether the bridge's current device roll owns this IEEE."""
        return any(entry.get("ieee_address") == ieee for entry in self._devices_by_name.values())

    @property
    def subscribed(self) -> bool:
        """Whether setup has established this reader's subscriptions."""
        return bool(self._unsubs)

    @property
    def availability_enabled(self) -> bool | None:
        """Return whether Zigbee2MQTT's availability feature is on.

        Read from bridge info: True or False once info has
        arrived, None before it. Surfaced on the bridge sensor so a
        person can see the setting without opening Zigbee2MQTT;
        never written, because enabling it is Zigbee2MQTT's own
        configuration (rule STACK-13).
        """
        return self._availability_enabled

    @property
    def reachability_known(self) -> bool:
        """Return whether this bridge can answer reachability at all.

        False where availability is switched off in Zigbee2MQTT, or
        where nothing has arrived yet. Every consumer reads that as
        "no opinion" and carries on with the verdict it already had.
        """
        return bool(self._availability_enabled and self._devices_by_name)

    def power_source(self, key: str | None) -> str | None:
        """What Zigbee2MQTT says powers one device, as it words it
        ("Battery", "Mains (single phase)"), or None (rule DEV-06)."""
        if not key:
            return None
        for entry in self._devices_by_name.values():
            if entry.get("ieee_address") == key:
                said = entry.get("power_source")
                return said if isinstance(said, str) else None
        return None

    def reachability(self, key: str | None) -> dict[str, Any] | None:
        """Return what Zigbee2MQTT says about one device, or None.

        key is the IEEE address out of the Home Assistant device
        identifier. None comes back for a device this bridge does not
        have, for a topic with no device behind it, and for a bridge
        that cannot answer. The reply carries the state and the class
        it was judged in, because the two are not comparable: a mains
        device is pinged on a short timer, while a sleeping device is
        called offline only after a silence far longer than any window
        this integration learns. A caller that shows the state without
        the timeout would tell a person a dead battery device is fine
        (rule STACK-03).
        """
        if not key or not self.reachability_known:
            return None
        for name, entry in self._devices_by_name.items():
            if entry.get("ieee_address") != key:
                continue
            state = self._availability.get(name)
            if state is None:
                return None
            passive = entry.get("power_source") == "Battery"
            timeout = (
                self._passive_timeout if passive else self._active_timeout
            )
            return {
                "state": state[0],
                "at": state[1],
                "class": "passive" if passive else "active",
                "timeout_minutes": timeout,
            }
        return None

    @property
    def reachability_rejected(self) -> list[str]:
        """Return availability topics with no device behind them.

        Groups, and topics left behind by a device that was renamed or
        removed, which keep publishing whatever they last said. Such a
        topic can read online while naming nothing, which would
        otherwise contradict a true verdict.
        """
        return sorted(
            name
            for name in self._availability
            if name not in self._devices_by_name
        )

    @property
    def stack(self) -> str:
        """Return the stack this reader speaks for."""
        return STACK_Z2M

    @property
    def base_topic(self) -> str | None:
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
    def loaded(self) -> bool:
        """Whether the bridge has said it is online (rule UP-03)."""
        return self._online is True

    @property
    def state(self) -> str:
        """Return the bridge state a person would read.

        The order matters. Nothing heard at all is unknown. A bridge
        that has said it is offline, or that has never confirmed it is
        online, is down. An online bridge with pairing open is binding;
        otherwise it is running. Pairing is only meaningful on a bridge
        known to be online, so an open permit_join with no online
        confirmation still reads down rather than binding.
        """
        if self._online is None and self._last_heard is None:
            return BRIDGE_UNKNOWN
        if self._online is not True:
            return BRIDGE_DOWN
        self._expire_pairing(dt_util.utcnow().timestamp())
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
        than the device (rule FRZ-16). Open now is the clear case;
        the grace covers a device that reports just after the window
        closes, which the observed publish lag on a real bridge makes
        a real case.
        """
        if self.pairing_open:
            return True
        if self._pairing_closed_at is None:
            return False
        return (now - self._pairing_closed_at) <= grace_seconds

    def set_join_recorder(self, recorder: Any) -> None:
        """Name who is told when a device joins while pairing is open:
        called with the stack and the device's address."""
        self._join_recorder = recorder

    @property
    def pairing_changed_at(self) -> float | None:
        """When the bridge last said pairing opened or closed, or None."""
        self._expire_pairing(dt_util.utcnow().timestamp())
        return self._pairing_changed_at

    def joins_seen(self) -> bool:
        """Whether every join of the current or last window was heard.

        False when the window was already open when Device Sentinel
        subscribed, since bridge/event is not retained: the caller then
        falls back to judging a recovery by its silence (rule FRZ-05).
        """
        return self._window_heard

    async def async_start(self) -> bool:
        """Subscribe to the bridge topics once MQTT is available.

        Returns True if the subscriptions were established. Waits for
        the MQTT client rather than assuming it is up, because Device
        Sentinel may start before MQTT. Any failure is logged and
        swallowed: the reader simply stays at unknown, and every
        consumer treats unknown as "cannot tell", which is safe.
        """
        if self._base is None:
            return False
        # Ask before waiting. async_wait_for_mqtt_client answers an
        # absent MQTT integration by waiting its full timeout, fifty
        # seconds, so calling it unconditionally would hold Device
        # Sentinel's setup that long in any house with a Zigbee2MQTT
        # bridge whenever MQTT is not yet loaded. The broker transport
        # has the same guard (rule STACK-03).
        if not any(
            entry.state is ConfigEntryState.LOADED
            for entry in self._hass.config_entries.async_entries("mqtt")
        ):
            LOGGER.debug(
                "Device Sentinel: no MQTT integration loaded, so the "
                "Z2M bridge state will read unknown"
            )
            return False
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
            # bridge/event first, so a window opening is never heard
            # before its joins can be (rule FRZ-05).
            self._unsubs.append(
                await mqtt.async_subscribe(
                    self._hass,
                    f"{self._base}/{Z2M_TOPIC_EVENT}",
                    self._on_event,
                )
            )
            self._joins_live = True
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
            self._unsubs.append(
                await mqtt.async_subscribe(
                    self._hass,
                    f"{self._base}/{Z2M_TOPIC_DEVICES}",
                    self._on_devices,
                )
            )
            self._unsubs.append(
                await mqtt.async_subscribe(
                    self._hass,
                    f"{self._base}/{Z2M_TOPIC_AVAILABILITY}",
                    self._on_availability,
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
        self._joins_live = False

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
        online = isinstance(text, str) and text.strip() == "online"
        # When the bridge last went offline and came back: every device's
        # entity follows bridge/state, so the values written back in the
        # minute after are the bridge handing back what it kept, not the
        # devices speaking (rule UNAV-05).
        now = dt_util.utcnow().timestamp()
        if online and self._online is not True:
            self.came_online_at = now
        elif not online and self._online is True:
            self.went_offline_at = now
            self.came_online_at = None
        self._online = online

    @callback
    def _expire_pairing(self, now: float) -> None:
        """Close a heard window at its deadline even if MQTT misses the close."""
        end = self._permit_join_deadline
        if self._permit_join and end is not None and end <= now:
            self._permit_join = False
            self._pairing_closed_at = end
            self._pairing_changed_at = end

    @callback
    def _on_info(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle bridge/info: read permit_join and permit_join_end.

        Reads the absolute permit_join_end, never the legacy
        permit_join_timeout. A payload that will not parse leaves the
        prior pairing state untouched rather than dropping it.
        """
        received = dt_util.utcnow()
        self._last_heard = received.isoformat()
        data = _load(_decode(msg.payload))
        if not isinstance(data, dict):
            return
        now = received.timestamp()
        self._expire_pairing(now)
        was_open = self._permit_join
        end = data.get("permit_join_end")
        deadline = _pairing_deadline(end)
        self._permit_join = data.get("permit_join") is True and (deadline is None or deadline > now)
        # Note the moment a window closes, so a device that reports
        # just after it can still be credited to the pairing rather
        # than to itself (rule FRZ-16).
        if was_open and not self._permit_join:
            self._pairing_closed_at = now
        if was_open != self._permit_join:
            self._pairing_changed_at = now
        # A window opening heard live, after bridge/event was
        # subscribed, is one whose joins are all heard. The retained
        # info read at subscribe, already open, is not; nor is the one
        # Home Assistant's MQTT client replays after it reconnects to
        # the broker, which carries the retain flag, since joins sent
        # while it was cut off were never heard (rule FRZ-05).
        replayed = bool(getattr(msg, "retain", False))
        if self._permit_join and not was_open:
            self._window_heard = (
                self._info_heard and self._joins_live and not replayed
            )
        elif self._permit_join and replayed:
            # Still open, or open again, when the client reconnects:
            # joins sent while it was cut off were never heard.
            self._window_heard = False
        self._info_heard = True
        self._permit_join_end = str(end) if end is not None else None
        self._permit_join_deadline = deadline
        self._read_hardware(data)
        # The availability settings, read rather than assumed. Absent
        # or malformed leaves the previous reading alone, so one bad
        # payload cannot silently turn reachability off.
        config = data.get("config")
        if isinstance(config, dict):
            serial = config.get("serial")
            if isinstance(serial, dict) and isinstance(serial.get("port"), str):
                self._serial_port = serial["port"]
            availability = config.get("availability")
            if isinstance(availability, dict):
                self._availability_enabled = bool(
                    availability.get("enabled", False)
                )
                active = availability.get("active")
                if isinstance(active, dict):
                    timeout = active.get("timeout")
                    if isinstance(timeout, (int, float)):
                        self._active_timeout = int(timeout)
                passive = availability.get("passive")
                if isinstance(passive, dict):
                    timeout = passive.get("timeout")
                    if isinstance(timeout, (int, float)):
                        self._passive_timeout = int(timeout)
            elif isinstance(availability, bool):
                # Older configurations wrote a bare boolean with the
                # timeouts left at their defaults, which are not
                # published. Enabled is known; the timeouts are not,
                # and a caller reads None as "cannot say how long".
                self._availability_enabled = availability

    def _read_hardware(self, data: dict[str, Any]) -> None:
        """The coordinator's type and firmware, the channel and the
        Zigbee2MQTT version. A field missing or of the wrong shape
        leaves what was read before (rule DASH-17)."""
        version = data.get("version")
        if isinstance(version, str) and version.strip():
            self._z2m_version = version.strip()[:40]
        coordinator = data.get("coordinator")
        if isinstance(coordinator, dict):
            kind = coordinator.get("type")
            if isinstance(kind, str) and kind.strip():
                self._coordinator_type = kind.strip()[:40]
            meta = coordinator.get("meta")
            if isinstance(meta, dict):
                revision = meta.get("revision")
                if isinstance(revision, (str, int)) and not isinstance(revision, bool):
                    text = str(revision).strip()
                    if text:
                        self._coordinator_firmware = text[:60]
        network = data.get("network")
        if isinstance(network, dict):
            channel = network.get("channel")
            if isinstance(channel, int) and not isinstance(channel, bool) and 11 <= channel <= 26:
                self._channel = channel

    @callback
    def _on_event(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle bridge/event: a device joining while pairing is open.

        device_joined names the device by its IEEE address. Counted only
        while pairing is open, or within the grace after it closed. An
        interview on its own is not a re-pair: Zigbee2MQTT interviews a
        half-interviewed device again when it announces itself, and a
        person can ask for one by hand, with nobody re-pairing it; a
        real re-pair always sends device_joined first. The device
        is named by the address Zigbee2MQTT gives Home Assistant; a
        device Device Sentinel does not know yet is a new one, with no
        count to restart (rule FRZ-05).
        """
        self._last_heard = dt_util.utcnow().isoformat()
        data = _load(_decode(msg.payload))
        if not isinstance(data, dict):
            return
        kind = data.get("type")
        body = data.get("data")
        if not isinstance(body, dict):
            return
        if kind != Z2M_EVENT_JOINED:
            return
        ieee = body.get("ieee_address")
        if not isinstance(ieee, str) or not ieee.startswith("0x"):
            return
        now = dt_util.utcnow().timestamp()
        if not self.pairing_active_within(PAIRING_GRACE_SECONDS_DEFAULT, now):
            LOGGER.debug("Zigbee2MQTT %s for %s with pairing closed; not a re-pair", kind, ieee)
            return
        if self._join_recorder is None:
            return
        try:
            # Named by its address, the key Device Sentinel already
            # keeps for each Zigbee2MQTT device (`device_key`); the
            # recorder finds the device it belongs to.
            self._join_recorder(self.instance_key, ieee)
        except Exception as err:  # noqa: BLE001 - a join never breaks the reader
            LOGGER.debug("Zigbee2MQTT join for %s not recorded: %s", ieee, err)

    @callback
    def _on_devices(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle bridge/devices: the roll of what actually exists.

        The join and the filter in one topic. It carries the IEEE
        address Home Assistant knows a device by, the friendly name
        the availability topics are keyed on, and the power source
        that decides which timeout the device is judged against. A
        payload that will not parse leaves the previous roll standing,
        because an empty roll would silently reject every topic.
        """
        self._last_heard = dt_util.utcnow().isoformat()
        data = _load(_decode(msg.payload))
        if not isinstance(data, list):
            return
        roll: dict[str, dict[str, Any]] = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            name = entry.get("friendly_name")
            ieee = entry.get("ieee_address")
            if not isinstance(name, str) or not isinstance(ieee, str):
                continue
            roll[name] = {
                "ieee_address": ieee,
                "power_source": entry.get("power_source"),
                "type": entry.get("type"),
            }
        if roll:
            self._devices_by_name = roll

    @callback
    def _on_availability(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle <name>/availability: online or offline, retained.

        The name is taken from the topic rather than the payload,
        which carries only the state. Nothing is reconciled here: the
        topic is recorded as heard and the join rejects it later if no
        device answers to that name, so a device that appears in the
        roll after its availability arrives is not lost.
        """
        topic = msg.topic or ""
        prefix = f"{self._base}/"
        suffix = f"/{Z2M_TOPIC_AVAILABILITY_LEAF}"
        if not topic.startswith(prefix) or not topic.endswith(suffix):
            return
        name = topic[len(prefix):-len(suffix)]
        if not name:
            return
        payload = _load(_decode(msg.payload))
        state: Any = payload
        if isinstance(payload, dict):
            state = payload.get("state")
        elif payload is None:
            state = _decode(msg.payload).strip()
        if not isinstance(state, str) or state not in ("online", "offline"):
            return
        self._availability[name] = (state, dt_util.utcnow().isoformat())


def _pairing_deadline(value: Any) -> float | None:
    """Read Zigbee2MQTT's epoch deadline, in seconds or milliseconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        stamp = float(value)
    except (ValueError, OverflowError):
        return None
    if not isfinite(stamp):
        return None
    return stamp / 1000 if stamp >= 1_000_000_000_000 else stamp


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
