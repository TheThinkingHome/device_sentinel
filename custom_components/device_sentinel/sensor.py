# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: sensor.py, Version: 0.12.12 (2026-08-07)

"""Sensor platform for the Device Sentinel integration.

Every name here has to stand alone: Home Assistant gives entities no
helper text on the device page, so a label and its state are the
whole explanation a user gets. Names are title-cased like book
titles rather than following Home Assistant's own sentence case,
which is a deliberate divergence rather than a drift (ruling #48).
Counts carry a unit so a card reads "125 devices" rather than "125",
and any sensor whose state a user could not act on was renamed or
retired in an early release (0.3.12).

Clock source was retired there. It counted watched devices lacking a
last_seen entity, so a higher number read as better while meaning
worse, and it existed to answer a soak question that closed on
2026-07-18. Its registry entry is removed at setup rather than left
to linger unavailable.

Identity attributes on all, per blueprint precedent.

Which sensors ship enabled follows one test (ruling #239): a person reads
it daily or acts on it in their first week. Status, the coverage
pair, the maintenance timestamp, and the detected bridge and broker
are on; the per-family counts are off, because the problem list
already carries what is wrong and their audience is a dashboard
builder, who enables exactly what they chart. Detection, the brief,
and every report run regardless of what is enabled here.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DeviceSentinelConfigEntry
from .const import (
    ATTR_AWAITING_BATTERY,
    ATTR_AWAITING_LAST_SEEN,
    ATTR_AWAITING_SIGNAL,
    ATTR_BRIDGE_AVAILABILITY,
    BROKER_SENSOR_NAME,
    BROKER_STATES,
    SENTINEL_TYPE_BROKER,
    ATTR_BRIDGE_BASE_TOPIC,
    ATTR_BRIDGE_LAST_HEARD,
    ATTR_BRIDGE_PERMIT_JOIN_END,
    ATTR_BRIDGE_STACK,
    ATTR_FIRST_INSTALLED,
    ATTR_SENTINEL_TYPE,
    ATTR_SENTINEL_VERSION,
    ATTR_SETUP_COUNT,
    ATTR_STORAGE_HEALTHY,
    BATTERY_CLEAR_MARGIN,
    BRIDGE_SENSOR_NAMES,
    BRIDGE_STATES,
    BRIDGE_UNKNOWN,
    DOMAIN,
    SENTINEL_TYPE_BRIDGE,
    SENTINEL_TYPE_CLASSIFICATION,
    SENTINEL_TYPE_COVERAGE,
    SENTINEL_TYPE_FALLING_BATTERIES,
    SENTINEL_TYPE_FROZEN_DEVICES,
    SENTINEL_TYPE_LEARNING,
    SENTINEL_TYPE_LOW_BATTERIES,
    SENTINEL_TYPE_MAINTENANCE,
    SENTINEL_TYPE_SIGNAL_RAILS,
    SENTINEL_TYPE_SIGNAL_WEAK,
    SENTINEL_TYPE_STATUS,
    SENTINEL_TYPE_TRACKED_BATTERIES,
    SENTINEL_TYPE_TRACKED_DEVICES,
    SENTINEL_TYPE_TRACKED_SIGNALS,
    STATUS_LEARNING,
    STATUS_PROBLEM,
    STATUS_WATCHING,
    UNIT_BATTERIES,
    UNIT_DEVICES,
    UNIT_SIGNALS,
)
from .coordinator import DeviceSentinelCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceSentinelConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Device Sentinel sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            DeviceSentinelStatusSensor(coordinator),
            DeviceSentinelCoverageSensor(coordinator),
            DeviceSentinelLearningSensor(coordinator),
            DeviceSentinelClassificationSensor(coordinator),
            DeviceSentinelTrackedSignalsSensor(coordinator),
            DeviceSentinelTrackedBatteriesSensor(coordinator),
            DeviceSentinelTrackedDevicesSensor(coordinator),
            DeviceSentinelSignalRailsSensor(coordinator),
            DeviceSentinelSignalWeakSensor(coordinator),
            DeviceSentinelLowBatteriesSensor(coordinator),
            DeviceSentinelFallingBatteriesSensor(coordinator),
            DeviceSentinelFrozenDevicesSensor(coordinator),
            DeviceSentinelMaintenanceSensor(coordinator),
        ]
    )
    # One bridge sensor per detected coordinator stack, disabled by
    # default. Created from the readers the coordinator started, so a
    # house with no capable stack gets none and a house with several
    # gets one each.
    async_add_entities(
        DeviceSentinelBridgeSensor(coordinator, stack)
        for stack in coordinator.bridge_stacks
    )
    async_add_entities([DeviceSentinelBrokerSensor(coordinator)])


class DeviceSentinelBaseSensor(SensorEntity):
    """Base class: identity attributes and coordinator refresh wiring."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    sentinel_type: str = "base"

    def __init__(self, coordinator: DeviceSentinelCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{self.sentinel_type}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Device Sentinel",
            manufacturer="The Thinking Home",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=coordinator.version,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator refreshes."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_refresh)
        )

    @callback
    def _handle_refresh(self) -> None:
        """Write the current state on a coordinator refresh."""
        self.async_write_ha_state()

    def _identity(self) -> dict[str, Any]:
        """Return the identity attributes every entity carries."""
        return {
            ATTR_SENTINEL_TYPE: self.sentinel_type,
            ATTR_SENTINEL_VERSION: self._coordinator.version,
        }


class DeviceSentinelStatusSensor(DeviceSentinelBaseSensor):
    """The status sensor: is Device Sentinel alive and fine.

    This once published the setup count, which proved that storage
    survived a restart and meant nothing to anyone else. A sensor
    named Status must answer its own name, so the count moved to an
    attribute, where it still proves persistence (changed in 0.3.12).

    Learning shows only until the first device establishes a rhythm.
    Partial learning is permanent rather than a phase (every new
    device starts unlearned), so keying the word to "any device
    unlearned" would read Learning forever and mean nothing. Devices
    Learned carries the per-device detail.
    """

    _attr_name = "Status"
    _attr_icon = "mdi:shield-check-outline"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATUS_WATCHING, STATUS_LEARNING, STATUS_PROBLEM]
    sentinel_type = SENTINEL_TYPE_STATUS

    @property
    def native_value(self) -> str:
        """Return the state a person would want to read."""
        if not self._coordinator.storage_healthy:
            return STATUS_PROBLEM
        if self._coordinator.learning_buckets["established"] == 0:
            return STATUS_LEARNING
        return STATUS_WATCHING

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the identity and storage-proof attributes, plus one
        exact count per enable button (ruling #237): non-zero means a press
        would do something, so a dashboard can show each button only
        while it has work. No entity lists; the count is the reader's
        whole question and a hundred names on a fresh install would be
        recorder weight with no reader.
        """
        counts = self._coordinator.awaiting_enable_counts()
        return {
            **self._identity(),
            ATTR_FIRST_INSTALLED: self._coordinator.first_installed,
            ATTR_STORAGE_HEALTHY: self._coordinator.storage_healthy,
            ATTR_SETUP_COUNT: self._coordinator.setup_count,
            ATTR_AWAITING_SIGNAL: counts["signal"],
            ATTR_AWAITING_LAST_SEEN: counts["last_seen"],
            ATTR_AWAITING_BATTERY: counts["battery"],
        }


class DeviceSentinelCoverageSensor(DeviceSentinelBaseSensor):
    """How many devices Device Sentinel is watching.

    Named for what it counts rather than for the abstraction:
    "Coverage: 125" left a user to guess the unit and the population.
    The rest of the split rides in attributes.
    """

    _attr_name = "Devices Watched"
    _attr_icon = "mdi:radar"
    _attr_native_unit_of_measurement = UNIT_DEVICES
    _attr_state_class = SensorStateClass.MEASUREMENT
    sentinel_type = SENTINEL_TYPE_COVERAGE

    @property
    def native_value(self) -> int:
        """Return the watched device count as the state."""
        return self._coordinator.watched_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the coverage breakdown."""
        return {
            **self._identity(),
            "total_devices": (
                self._coordinator.watched_count
                + self._coordinator.set_aside_count
            ),
            "set_aside": self._coordinator.set_aside_count,
            "deviceless_entities": self._coordinator.deviceless_count,
            "learning": self._coordinator.learning_buckets,
        }


class DeviceSentinelLearningSensor(DeviceSentinelBaseSensor):
    """Devices whose rhythm is established, past the arming floor.

    An integer rather than "115 of 125" by ruling: a string state
    cannot be compared in an automation and forfeits the state class.

    This is not expected to reach Devices Watched. Devices with no
    heartbeat (buttons, remotes) never establish a rhythm and are
    never judged frozen, by design, so a permanent gap between the
    two counts is the system working.
    """

    _attr_name = "Devices Learned"
    _attr_icon = "mdi:school-outline"
    _attr_native_unit_of_measurement = UNIT_DEVICES
    _attr_state_class = SensorStateClass.MEASUREMENT
    sentinel_type = SENTINEL_TYPE_LEARNING

    @property
    def native_value(self) -> int:
        """Return the count of rhythm-established devices."""
        return self._coordinator.learning_buckets["established"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the full learning buckets."""
        return {**self._identity(), **self._coordinator.learning_buckets}


class DeviceSentinelClassificationSensor(DeviceSentinelBaseSensor):
    """Soak diagnostic: the per-integration classification breakdown."""

    _attr_name = "Service Devices Ignored"
    _attr_native_unit_of_measurement = UNIT_DEVICES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:filter-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
        # Off by default. It answers why a particular device is not
    # watched, which is a question asked once if ever, so it
    # belongs in the registry rather than on the page
    # (ruling #212).
    _attr_entity_registry_enabled_default = False
    sentinel_type = SENTINEL_TYPE_CLASSIFICATION

    @property
    def native_value(self) -> int:
        """Return the set-aside count as the state."""
        return self._coordinator.set_aside_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the per-integration breakdown."""
        return {
            **self._identity(),
            "by_integration": self._coordinator.classification_breakdown,
        }


class DeviceSentinelTrackedSignalsSensor(DeviceSentinelBaseSensor):
    """How many devices we watch for signal, after signal excludes.

    A device is tracked once it has a learned floor and so a live
    danger line, minus the signal-excluded. The signal member of the
    Tracked family. The scale split and the still-learning count ride
    in attributes.
    """

    _attr_name = "Signal: Tracked"
    _attr_icon = "mdi:access-point-network"
    _attr_native_unit_of_measurement = UNIT_SIGNALS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    sentinel_type = SENTINEL_TYPE_TRACKED_SIGNALS

    @property
    def native_value(self) -> int:
        """Return how many devices we watch for signal."""
        return self._coordinator.signal_tracked_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the scale split and the still-learning count."""
        counts = self._coordinator.signal_tracked
        return {
            **self._identity(),
            "lqi": counts["lqi"],
            "rssi": counts["rssi"],
            "still_learning": counts["learning"],
        }


class DeviceSentinelTrackedBatteriesSensor(DeviceSentinelBaseSensor):
    """How many devices we watch for battery, after battery excludes.

    A device is battery-tracked when a battery entity was elected for
    it and it is not battery-excluded. The battery member of the
    Tracked family. The devices ride in attributes.
    """

    _attr_name = "Battery: Tracked"
    _attr_icon = "mdi:battery-heart-outline"
    _attr_native_unit_of_measurement = UNIT_BATTERIES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    sentinel_type = SENTINEL_TYPE_TRACKED_BATTERIES

    @property
    def native_value(self) -> int:
        """Return how many devices we watch for battery."""
        return self._coordinator.battery_tracked_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the tracked devices."""
        return {
            **self._identity(),
            "devices": self._coordinator.battery_tracked_list,
        }


class DeviceSentinelTrackedDevicesSensor(DeviceSentinelBaseSensor):
    """How many devices are eligible for freeze detection.

    A device with a learned rhythm, minus the global device excludes.
    The freeze member of the Tracked family: the set freeze detection
    judges. The devices ride in attributes.
    """

    _attr_name = "Device: Tracked"
    _attr_icon = "mdi:heart-pulse"
    _attr_native_unit_of_measurement = UNIT_DEVICES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    sentinel_type = SENTINEL_TYPE_TRACKED_DEVICES

    @property
    def native_value(self) -> int:
        """Return how many devices are freeze-eligible."""
        return self._coordinator.freeze_tracked_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the freeze-eligible devices."""
        return {
            **self._identity(),
            "devices": self._coordinator.freeze_tracked_list,
        }


class DeviceSentinelSignalRailsSensor(DeviceSentinelBaseSensor):
    """How many devices report a signal stuck at its rail.

    A rail is the type's fill value, 255 for LQI or -128 for RSSI:
    the empty value of a field the device stopped populating, which
    reads as perfect signal and is the opposite. Confirmed over three
    days rather than on one reading (ruling #78), so this counts
    faults rather than bad afternoons, and it is the one signal
    condition that reaches the problem list and the phone.

    Weak links are counted next door. They were counted here until
    0.11.10, under the name Signal: Problems, and one number meaning
    two things read zero on a fleet with no rails (ruling #211).
    """

    _attr_name = "Signal: Rails"
    _attr_icon = "mdi:access-point-off"
    _attr_native_unit_of_measurement = UNIT_SIGNALS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    # On by default (ruling #212). The reasoning for hiding these
    # was that the todo list carries trouble devices, which is
    # true of two of the five and false of the rest: a weak link
    # and a falling battery never reach that list, so hiding
    # them meant a person had to know the sensor existed before
    # they could see the problem.
    sentinel_type = SENTINEL_TYPE_SIGNAL_RAILS

    @property
    def native_value(self) -> int:
        """Return how many devices are stuck at a rail."""
        return self._coordinator.signal_problem_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the railed devices."""
        return {
            **self._identity(),
            "devices": self._coordinator.signal_problem_list,
        }


class DeviceSentinelSignalWeakSensor(DeviceSentinelBaseSensor):
    """How many links are weak right now.

    A device is here while its dwell on the last closed day is over
    the red threshold, which is the rule the daily brief and the
    chart already use, so the three cannot name different devices
    (ruling #211).

    Live rather than remembered. A device drops off the moment its
    dwell falls back under the threshold, with no acknowledgment and
    no record, because it is a reading rather than an incident. That
    also means the count moves: on the reference fleet only three of
    twelve device-days above twenty percent were still above it the
    next morning, which is why nothing notifies from it
    (ruling #59).
    """

    _attr_name = "Signal: Weak"
    _attr_icon = "mdi:wifi-strength-1-alert"
    _attr_native_unit_of_measurement = UNIT_SIGNALS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    sentinel_type = SENTINEL_TYPE_SIGNAL_WEAK

    @property
    def native_value(self) -> int:
        """Return how many links are weak right now."""
        return self._coordinator.signal_weak_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the weak devices and the threshold in force."""
        return {
            **self._identity(),
            "devices": self._coordinator.signal_weak_list,
            "red_threshold": self._coordinator._signal_red(),
        }


class DeviceSentinelLowBatteriesSensor(DeviceSentinelBaseSensor):
    """How many devices have a low battery right now.

    The battery member of the Problems family, merging the former
    Battery Low Count and Battery Low List into one sensor: state is
    the count, the device rows ride in attributes. Value-only by
    ruling: an unavailable battery is a freeze matter, not a low one,
    so this stays clean for dashboards and automations.
    """

    _attr_name = "Battery: Low"
    _attr_icon = "mdi:battery-alert"
    _attr_native_unit_of_measurement = UNIT_BATTERIES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    # On by default (ruling #212). The reasoning for hiding these
    # was that the todo list carries trouble devices, which is
    # true of two of the five and false of the rest: a weak link
    # and a falling battery never reach that list, so hiding
    # them meant a person had to know the sensor existed before
    # they could see the problem.
    sentinel_type = SENTINEL_TYPE_LOW_BATTERIES

    @property
    def native_value(self) -> int:
        """Return the number of battery-low devices."""
        return self._coordinator.battery_low_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the device rows and the thresholds in effect."""
        return {
            **self._identity(),
            "devices": self._coordinator.battery_low_list,
            "low_threshold": self._coordinator.low_threshold,
            "clear_margin": BATTERY_CLEAR_MARGIN,
        }


class DeviceSentinelFallingBatteriesSensor(DeviceSentinelBaseSensor):
    """How many cells are projected to reach empty inside the horizon.

    A different set from Battery: Low and a different question. Low is
    a level that has been crossed; falling is a level that is going to
    be, and the two rarely name the same device: a cell at 80 percent
    dropping steadily can have less life left than one sitting at 30
    that has not moved in a month (ruling #209).

    The count is read from the battery report's own rows, so this
    sensor, the report and the daily brief cannot disagree about which
    cells are near the end or how long they have. Cells already low
    are absent, because they are counted by the sensor above and one
    thing should be counted once.

    Time left is a phrase rather than a number, for the reason it is a
    phrase everywhere else: the projection moved from twelve days to
    seven in an afternoon on the cell that proved it, so the words say
    what the arithmetic supports and the number would not
    (ruling #197).
    """

    _attr_name = "Battery: Falling"
    _attr_icon = "mdi:battery-arrow-down"
    _attr_native_unit_of_measurement = UNIT_BATTERIES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    # On by default (ruling #212). The reasoning for hiding these
    # was that the todo list carries trouble devices, which is
    # true of two of the five and false of the rest: a weak link
    # and a falling battery never reach that list, so hiding
    # them meant a person had to know the sensor existed before
    # they could see the problem.
    sentinel_type = SENTINEL_TYPE_FALLING_BATTERIES

    @property
    def native_value(self) -> int:
        """Return how many cells are inside the horizon."""
        return self._coordinator.battery_falling_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the cells, nearest the end first, and the horizon."""
        return {
            **self._identity(),
            "devices": self._coordinator.battery_falling_list,
            "days_till_empty": self._coordinator._battery_days(),
        }


class DeviceSentinelFrozenDevicesSensor(DeviceSentinelBaseSensor):
    """How many devices are frozen, unavailable, unknown, or not
    reported.

    The freeze member of the Problems family. Each device rides in the
    attributes with its category and how long it has been down.
    """

    _attr_name = "Device: Frozen"
    _attr_icon = "mdi:snowflake-alert"
    _attr_native_unit_of_measurement = UNIT_DEVICES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    # On by default (ruling #212). The reasoning for hiding these
    # was that the todo list carries trouble devices, which is
    # true of two of the five and false of the rest: a weak link
    # and a falling battery never reach that list, so hiding
    # them meant a person had to know the sensor existed before
    # they could see the problem.
    sentinel_type = SENTINEL_TYPE_FROZEN_DEVICES

    @property
    def native_value(self) -> int:
        """Return how many devices are down right now."""
        return self._coordinator.frozen_devices_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the down devices, each with its category."""
        return {
            **self._identity(),
            "devices": self._coordinator.frozen_devices_list,
        }


class DeviceSentinelMaintenanceSensor(DeviceSentinelBaseSensor):
    """When the open maintenance window ends, or unknown when closed.

    A timestamp rather than seconds remaining (ruling #238): a dashboard
    renders a countdown from a timestamp natively, where a
    seconds-remaining state would need a write every second to stay
    true. The state is the whole surface: a time means a window is
    open and recoveries are being attributed to the person's hands,
    unknown means the integration is learning normally.
    """

    _attr_name = "Maintenance: Ends"
    _attr_icon = "mdi:progress-wrench"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    sentinel_type = SENTINEL_TYPE_MAINTENANCE

    @property
    def native_value(self) -> Any:
        """Return the declared end of the open window, or None."""
        until = self._coordinator.maintenance_until
        if until is None:
            return None
        return dt_util.utc_from_timestamp(until)


class DeviceSentinelBrokerSensor(DeviceSentinelBaseSensor):
    """The MQTT broker's own liveness, which nothing else can show.

    Created wherever the integration runs, not only where a stack was
    detected, because a house on Tasmota or ESPHome over MQTT has a
    broker and no bridge. Where there is no MQTT at all it reads
    unknown forever and costs one disabled entity.

    Its default follows detection (ruling #239): enabled where a bridge
    stack was found, because that house demonstrably runs on this
    broker and the sensor belongs on its first page; disabled
    otherwise, so a house without MQTT never meets a dead sensor. The
    watch itself runs off the subscription either way, so a person who
    never enables it still gets the broker events in the log and the
    brief (ruling #224).
    """

    _attr_icon = "mdi:transit-connection-variant"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = BROKER_STATES
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    sentinel_type = SENTINEL_TYPE_BROKER

    def __init__(self, coordinator: DeviceSentinelCoordinator) -> None:
        """Initialize the broker sensor, defaulting on with a bridge.

        Detection rather than the reader decides (ruling #239): a house
        whose registry shows a bridge stack runs on this broker even
        if the reader could not start, and the default is a statement
        about the house rather than about this session's wiring.
        """
        super().__init__(coordinator)
        self._attr_name = BROKER_SENSOR_NAME
        self._attr_entity_registry_enabled_default = bool(
            coordinator._stacks
        )

    @property
    def native_value(self) -> str:
        """Return running, down, or unknown."""
        return self._coordinator.broker_state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return when the broker came up, and how it is being judged.

        broker_started answers a question that had no answer before:
        whether the broker has been restarting unnoticed. The cadence
        and threshold are shown because the threshold is learned
        rather than set, so a person can see what it settled on.
        """
        return {
            **self._identity(),
            **self._coordinator.broker_attributes,
        }


class DeviceSentinelBridgeSensor(DeviceSentinelBaseSensor):
    """One per detected coordinator bridge: is it running, in binding
    mode, or down.

    This is the visible surface of the intervention-detection work and,
    just as much, the acceptance test for each stack. Reading a stack's
    pairing state is the hard, stack-specific part; when this sensor
    flips to binding as a pairing window opens, the reader underneath
    is proven, and the shared detector follows: a device that comes
    back while that window is open came back because of the hand on
    it, so its silence is set aside rather than learned as the
    device's normal rhythm (ruling #145).

    Enabled by default (ruling #239): a bridge sensor is only created
    where its stack was detected, so its very existence is the
    condition that used to justify keeping it off, and the house it
    appears in demonstrably runs that coordinator. Intervention
    detection works whether or not it is enabled, because the reader
    and the detector run off the subscription, not off this entity
    (the NUT-integration lesson: a disabled diagnostic with no
    documentation is a feature nobody finds).
    """

    _attr_icon = "mdi:zigbee"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = BRIDGE_STATES
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: DeviceSentinelCoordinator, stack: str
    ) -> None:
        """Initialize the bridge sensor for one stack."""
        self._stack = stack
        self.sentinel_type = f"{SENTINEL_TYPE_BRIDGE}_{stack}"
        super().__init__(coordinator)
        # A stack-specific display name. Z2M reads as its full product
        # name to match the wiki and reports; other stacks name their
        # own coordinator when they arrive.
        self._attr_name = BRIDGE_SENSOR_NAMES.get(stack, f"{stack} Bridge")

    @property
    def native_value(self) -> str:
        """Return the bridge state a person would read."""
        state = self._coordinator.bridge_state(self._stack)
        return state if state is not None else BRIDGE_UNKNOWN

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the stack, the pairing window end when open, and the
        base topic and last-heard time for diagnosis."""
        reader = self._coordinator.bridge_reader(self._stack)
        attrs: dict[str, Any] = {
            **self._identity(),
            ATTR_BRIDGE_STACK: self._stack,
        }
        if reader is not None:
            attrs[ATTR_BRIDGE_PERMIT_JOIN_END] = reader.permit_join_end
            attrs[ATTR_BRIDGE_BASE_TOPIC] = reader.base_topic
            attrs[ATTR_BRIDGE_LAST_HEARD] = reader.last_heard
            # Whether the stack's availability feature is on, where
            # the reader knows (ruling #236). Z2M reports it in bridge
            # info; a stack that cannot say simply lacks the
            # property and writes nothing. Reported, never written:
            # turning it on is the stack's configuration.
            if hasattr(reader, "availability_enabled"):
                attrs[ATTR_BRIDGE_AVAILABILITY] = (
                    reader.availability_enabled
                )
        return attrs
