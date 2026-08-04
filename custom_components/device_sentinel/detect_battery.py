# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: detect_battery.py, Version: 0.11.5 (2026-08-04)

"""Battery: the level threshold and what is tracked.

One of six subject modules split out of coordinator.py, which
had reached four thousand lines. The seam is the subject, chosen
by measuring which methods call which: storage and interventions
call nothing outside themselves at all, and the three detectors
reach out fewer than ten times each (ruling #201).

A file split rather than a boundary. These are mixins on the
coordinator and read its state freely, so `self` is the
coordinator throughout and nothing here stands alone.
"""

from __future__ import annotations

from typing import Any
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from .records import BAD_STATES

from .const import (
    BATTERY_CLEAR_MARGIN,
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_BATTERY_EXCLUDED_INTEGRATIONS,
    CONF_BATTERY_EXCLUDED_LABELS,
    CONF_LOW_THRESHOLD,
    DATA_DEVICES,
    DEFAULT_LOW_THRESHOLD,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    LOGGER,
)


class BatteryMixin:
    """Battery: the level threshold and what is tracked."""

    def _roll_battery(self, record: dict[str, Any]) -> None:
        """Append today's battery level to the daily discharge series.

        One point per day, sampled here at the rollover: the value,
        not the delta, so the series is self-describing (89, 89, 88,
        80, 65) and a missed midnight leaves a gap the velocity flag
        can later divide across rather than a false cliff. Only records
        when there is a level to record, so a device without a battery
        keeps an empty series. The velocity judgment waits until this
        history has depth, the way the dwell danger line waited on the
        floor; today this only records.
        """
        level = record.get(DEV_BATTERY_VALUE)
        if level is None:
            return
        record.setdefault(DEV_BATTERY_DAILY, []).append(level)
        del record[DEV_BATTERY_DAILY][:-self.retention_days]

    @staticmethod
    def _is_battery(ent: er.RegistryEntry) -> bool:
        """Recognize a battery entity from its registry device class.

        Percentage batteries are sensors with device_class battery;
        binary low flags are binary_sensors with device_class battery.
        Chargers, battery_charging flags, and the like carry other
        device classes and are correctly ignored.
        """
        if str(ent.original_device_class or ent.device_class) != "battery":
            return False
        return ent.entity_id.startswith(("sensor.", "binary_sensor."))

    @property
    def low_threshold(self) -> float:
        """Return the configured low threshold (options flow, live)."""
        return float(
            self.entry.options.get(
                CONF_LOW_THRESHOLD, DEFAULT_LOW_THRESHOLD
            )
        )

    @callback
    def _evaluate_battery(
        self, device_id: str, notify_on_change: bool = False
    ) -> None:
        """Judge one device's battery against the threshold.

        The hysteresis, carried from Battery Sentinel 1.2.0: flag at
        or below the threshold; once flagged, stay flagged until the
        value climbs past threshold plus the clear margin, so a cell
        hovering exactly at the line never flaps. The margin is small
        (2) because a load-driven rest-rebound is a genuine recovery
        and is allowed to clear the flag.

        below-threshold-since: the first crossing stamps the time,
        later evaluations carry it, recovery clears it. It lives in
        storage, so it survives restarts by construction.

        An unavailable or unknown battery value changes nothing: the
        last verdict holds, because liveness is Step 4's job and a
        dead reading is not a level reading.
        """
        election = self._battery_entity.get(device_id)
        record = self.data[DATA_DEVICES].get(device_id)
        if election is None or record is None:
            return
        battery_entity_id, is_binary = election
        state = self.hass.states.get(battery_entity_id)
        if state is None or state.state in BAD_STATES:
            return

        was_low = bool(record.get(DEV_BATTERY_LOW))
        if is_binary:
            is_low = state.state == "on"
            level = None
        else:
            try:
                level = float(state.state)
            except ValueError:
                return
            threshold = self.low_threshold
            if was_low:
                is_low = level < threshold + BATTERY_CLEAR_MARGIN
            else:
                is_low = level <= threshold

        changed = (
            is_low != was_low
            or record.get(DEV_BATTERY_VALUE) != level
        )
        record[DEV_BATTERY_VALUE] = level
        if is_low and not was_low:
            record[DEV_BATTERY_LOW] = True
            record[DEV_BATTERY_SINCE] = dt_util.utcnow().isoformat()
            LOGGER.debug(
                "Battery low: %s at %s (threshold %s)",
                battery_entity_id,
                "on" if is_binary else level,
                self.low_threshold,
            )
        elif was_low and not is_low:
            record[DEV_BATTERY_LOW] = False
            record[DEV_BATTERY_SINCE] = None
            LOGGER.debug(
                "Battery recovered: %s at %s",
                battery_entity_id,
                "off" if is_binary else level,
            )
        if is_low != was_low:
            # A flag flip reaches the list at once, both ways: the
            # item appears the moment the cell crosses the line and
            # deletes the moment it clears the margin. The flip and
            # its since stamp must survive a reboot, so it is
            # critical for the save tier too.
            self._critical = True
            self._sync_problem_list()
        if changed:
            self._dirty = True
            if notify_on_change:
                self._notify()

    @callback
    def _evaluate_all_batteries(self) -> None:
        """Judge every elected battery; used at setup and on options
        changes, so a threshold slid upward flags immediately."""
        for device_id in self._battery_entity:
            self._evaluate_battery(device_id)

    @property
    def battery_low_list(self) -> list[dict[str, Any]]:
        """Return the low list, one row per device, area then name.

        Row shape follows the blueprint contract: name, entity_id,
        area, level, since (below-threshold-since), last_seen (the
        battery entity's own last report), age, kind: device.
        """
        dev_reg = dr.async_get(self.hass)
        area_reg_names: dict[str, str] = {}
        rows: list[dict[str, Any]] = []
        for device_id, (entity_id, is_binary) in (
            self._battery_entity.items()
        ):
            # Judgment suppression: the verdict is still computed and
            # stored (observation), it is just never reported here.
            # Battery-only excludes stack on top of the global list.
            if (
                device_id in self._excluded_devices
                or entity_id in self._excluded_entities
                or self._battery_excluded(device_id)
            ):
                continue
            record = self.data[DATA_DEVICES].get(device_id)
            if not record or not record.get(DEV_BATTERY_LOW):
                continue
            device = dev_reg.async_get(device_id)
            device_name = (
                (device.name_by_user or device.name or device_id)
                if device
                else device_id
            )
            area_name = "Unassigned"
            if device and device.area_id:
                if device.area_id not in area_reg_names:
                    from homeassistant.helpers import area_registry as ar

                    area = ar.async_get(self.hass).async_get_area(
                        device.area_id
                    )
                    area_reg_names[device.area_id] = (
                        area.name if area else device.area_id
                    )
                area_name = area_reg_names[device.area_id]
            state = self.hass.states.get(entity_id)
            since = record.get(DEV_BATTERY_SINCE)
            since_dt = dt_util.parse_datetime(since) if since else None
            rows.append(
                {
                    "name": device_name,
                    "device_id": device_id,
                    "entity_id": entity_id,
                    "area": area_name,
                    "level": record.get(DEV_BATTERY_VALUE),
                    "since": since,
                    "last_seen": (
                        state.last_reported.isoformat()
                        if state and state.last_reported
                        else None
                    ),
                    "age": (
                        dt_util.get_age(since_dt) if since_dt else "unknown"
                    ),
                    "kind": "device",
                }
            )
        rows.sort(key=lambda row: (row["area"], row["name"]))
        return rows

    @property
    def battery_low_count(self) -> int:
        """Return the number of devices currently battery-low."""
        return sum(
            1
            for device_id, (entity_id, _) in self._battery_entity.items()
            if device_id not in self._excluded_devices
            and entity_id not in self._excluded_entities
            and not self._battery_excluded(device_id)
            and (self.data[DATA_DEVICES].get(device_id) or {}).get(
                DEV_BATTERY_LOW
            )
        )

    def _battery_excluded(self, device_id: str) -> bool:
        """Return whether a device is excluded from battery judgment
        only. Device-level by ruling, so a battery-entity re-election
        cannot dodge it; the integration test uses the owning domain,
        so one tick covers a whole family of phones. The label test
        reads the device's own labels, which is how a device can be
        excluded from battery judgment without opening this dialog."""
        options = self.entry.options
        if self._watched.get(device_id) in options.get(
            CONF_BATTERY_EXCLUDED_INTEGRATIONS, []
        ):
            return True
        if self._device_labels.get(device_id, frozenset()) & set(
            options.get(CONF_BATTERY_EXCLUDED_LABELS, [])
        ):
            return True
        return device_id in options.get(CONF_BATTERY_EXCLUDED_DEVICES, [])

    @property
    def battery_tracked_count(self) -> int:
        """Return how many devices we watch for battery, after excludes.

        A device is battery-tracked when a battery entity was elected
        for it and it is not battery-excluded. The battery analogue of
        Tracked Signals.
        """
        return sum(
            1
            for device_id in self._battery_entity
            if not self._battery_excluded(device_id)
        )

    @property
    def battery_tracked_list(self) -> list[dict[str, Any]]:
        """Return the devices watched for battery, for the attribute."""
        return sorted(
            (
                {"name": self._device_names.get(device_id)}
                for device_id in self._battery_entity
                if not self._battery_excluded(device_id)
            ),
            key=lambda row: row["name"] or "",
        )

    @property
    def detected_batteries(self) -> list[dict[str, Any]]:
        """Return every device with an elected battery, for the
        options picker: what you see is what is being judged."""
        rows = [
            {
                "device_id": device_id,
                "name": self._device_names.get(device_id, device_id),
                "entity_id": entity_id,
                "integration": self._watched.get(device_id, "?"),
                "labels": self._device_labels.get(
                    device_id, frozenset()
                ),
            }
            for device_id, (entity_id, _) in self._battery_entity.items()
        ]
        rows.sort(key=lambda row: row["name"].lower())
        return rows

    @staticmethod
    def _is_battery_percentage(ent: er.RegistryEntry) -> bool:
        """Recognize a battery-percentage sensor, excluding the binary
        low flag. The percentage is what feeds the discharge series."""
        if str(ent.original_device_class or ent.device_class) != "battery":
            return False
        return ent.entity_id.startswith("sensor.")
