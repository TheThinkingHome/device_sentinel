# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: custom_components/device_sentinel/backup_power.py, Version: 0.30.7 (2026-11-26)

"""Whether a wired device runs on a UPS or a battery backup (rule DEV-20).

A tick box on the device page, under Power, for that one device. A UPS
is where a device is plugged in, not what powers it: a plug on a UPS
still runs on mains, and a USB device charging from one still runs on
USB, so Powered By keeps one answer per model (rule DEV-06) and this
mark belongs to the device alone. It is shown only while the device's
power is wired. Today it changes no judgment: it records the fact, which
the Mains Power work will read as the device's backup mark.

The answers file's part: {"backup_power": {device_id: {"set": time}}}.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import DATA_DEVICES


class BackupPowerMixin:
    """The coordinator's side of the UPS or Battery Backup line."""

    def _backup(self) -> dict[str, dict[str, str]]:
        """This coordinator's marks, never a dictionary shared between two."""
        if "_backup_power" not in self.__dict__:
            self._backup_power = {}
        return self._backup_power

    def _backup_read(self, payload: Any) -> int:
        """Take the marks from the answers file; a malformed one is dropped
        and counted (rule STOR-09)."""
        kept: dict[str, dict[str, str]] = {}
        dropped = 0
        if isinstance(payload, dict):
            for device_id, raw in payload.items():
                when = raw.get("set") if isinstance(raw, dict) else None
                if isinstance(device_id, str) and isinstance(when, str):
                    kept[device_id] = {"set": when[:64]}
                else:
                    dropped += 1
        elif payload is not None:
            dropped += 1
        self._backup_power = kept
        return dropped

    def _backup_payload(self) -> dict[str, dict[str, str]]:
        return {device_id: dict(entry) for device_id, entry in self._backup().items()}

    def device_backup(self, device_id: str) -> bool:
        """Whether the person ticked UPS or Battery Backup for the device."""
        return device_id in self._backup()

    def page_set_backup(self, device_id: str, on: bool) -> None:
        """Tick or untick UPS or Battery Backup for one device (rule DEV-20).

        Only a wired device takes it: a battery device, or one whose
        power is not known, is refused, as the page does not offer it.
        Untick is always allowed, so a mark left from when the device
        was wired can be taken off.
        """
        self._device(device_id)  # type: ignore[attr-defined]
        marks = self._backup()
        if on:
            known = self.power_of(device_id)  # type: ignore[attr-defined]
            if not known or known.get("kind") == "battery":
                raise ValueError("UPS or Battery Backup is for a wired device. Set what powers it first.")
            if device_id in marks:
                return
            marks[device_id] = {"set": dt_util.utcnow().isoformat()}
            what = "UPS or Battery Backup ticked"
        else:
            if device_id not in marks:
                return
            del marks[device_id]
            what = "UPS or Battery Backup cleared"
        self._answers_save()  # type: ignore[attr-defined]
        self._page_done(device_id, what)  # type: ignore[attr-defined]

    def _settle_backup(self) -> None:
        """A mark goes when its device has left Home Assistant and its
        held record is gone, as a note does (rules DEV-19, DEV-20)."""
        devices = self.data.get(DATA_DEVICES) or {}  # type: ignore[attr-defined]
        registry = dr.async_get(self.hass)  # type: ignore[attr-defined]
        marks = self._backup()
        gone = [
            device_id for device_id in marks
            if device_id not in devices and registry.async_get(device_id) is None
        ]
        for device_id in gone:
            del marks[device_id]
        if gone:
            self._answers_save()  # type: ignore[attr-defined]
