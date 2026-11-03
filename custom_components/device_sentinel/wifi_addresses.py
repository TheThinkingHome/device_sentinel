# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: wifi_addresses.py, Version: 0.28.0 (2026-11-03)

"""Each Wi-Fi device's network address and access point (rule UP-19).

A device tied to its router's tracker (rule UP-13) is read for the
address its router gave it and, where the router says, the access point
it is joined to. Every router integration's tracker carries the address
as an ordinary state attribute, `ip`, the same for all of them; UniFi
also carries `ap_mac`. Nothing is read from an integration's private
state. Each change is kept, with when it happened, held to the History
setting, so the device page shows the address and access point it has
now, and a drop can be laid beside a change of either.

Two devices that hold the same address at once for 10 minutes are
flagged: two pieces of hardware answering to one address is a network
fault that makes either one look dead. Flagged on the Recommendations
tab, and by a Repair card a person can only acknowledge, which advises
reserving each device's address in the router (rule UP-19).
"""

from __future__ import annotations

from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    ADDR_AP,
    ADDR_DEVICE_ID,
    ADDR_IP,
    ADDR_WHEN,
    ADDRESS_MAX_LENGTH,
    ADDRESS_ROWS_PER_DEVICE,
    DATA_ADDRESS_CHANGES,
    SHARED_ADDRESS_SECONDS,
    TRACKER_ATTR_AP,
    TRACKER_ATTR_IP,
)
from .router_ties import normalize_mac


def _text(value: Any) -> str | None:
    """An attribute as text, or None for nothing usable or too long to
    be an address."""
    if isinstance(value, str):
        value = value.strip()
        return value if value and len(value) <= ADDRESS_MAX_LENGTH else None
    return None


class WifiAddressMixin:
    """Records each tied device's address and access point."""

    _address_now: dict[str, dict[str, Any]] | None
    _shared_addresses: dict[str, list[str]]

    def _forget_address_index(self) -> None:
        """Build the index again from the table, after a trim."""
        self._address_now = None

    def _address_index(self) -> dict[str, dict[str, Any]]:
        """The latest row per device, built once from the stored table
        and kept in step as rows are added."""
        index = getattr(self, "_address_now", None)
        if index is None:
            index = {}
            for row in self.data.get(DATA_ADDRESS_CHANGES) or []:  # type: ignore[attr-defined]
                if not isinstance(row, dict) or not isinstance(row.get(ADDR_DEVICE_ID), str):
                    continue
                when = row.get(ADDR_WHEN)
                if not isinstance(when, (int, float)) or isinstance(when, bool):
                    continue
                held = index.get(row[ADDR_DEVICE_ID])
                if held is None or when >= held[ADDR_WHEN]:
                    index[row[ADDR_DEVICE_ID]] = row
            self._address_now = index
        return index

    def _sample_addresses(self, now: float) -> None:
        """Read each tied tracker's address and access point, keep a row
        when either changes, and look for an address held by two
        devices at once (rule UP-19)."""
        ties = getattr(self, "_wifi_ties", None) or {}
        index = self._address_index()
        holders: dict[str, set[str]] = {}
        trackers: dict[str, str] = {}
        for device_id, tracker in list(ties.items()):
            state = self.hass.states.get(tracker)  # type: ignore[attr-defined]
            if state is None:
                continue
            attributes = state.attributes or {}
            ip = _text(attributes.get(TRACKER_ATTR_IP))
            ap = _text(attributes.get(TRACKER_ATTR_AP))
            if ip is None and ap is None:
                continue
            held = index.get(device_id)
            if held is None or held.get(ADDR_IP) != ip or held.get(ADDR_AP) != ap:
                row = {ADDR_DEVICE_ID: device_id, ADDR_WHEN: now, ADDR_IP: ip, ADDR_AP: ap}
                table = self.data.setdefault(DATA_ADDRESS_CHANGES, [])  # type: ignore[attr-defined]
                table.append(row)
                self._hold_address_rows(table, device_id)
                index[device_id] = row
                self._mark_cold_dirty()  # type: ignore[attr-defined]
            # Only a device its router sees connected now can hold an
            # address against another: a tracker away keeps its last
            # address as a stale attribute.
            # One piece of hardware seen by two routers' trackers is
            # still one: it is counted by the MAC its trackers carry.
            if ip is not None and state.state == "home":
                holders.setdefault(ip, set()).add(device_id)
                trackers[device_id] = normalize_mac(attributes.get("mac")) or tracker
        self._judge_shared_addresses(holders, trackers, now)

    @staticmethod
    def _hold_address_rows(table: list[Any], device_id: str) -> None:
        """Keep one device's newest rows only, so a device moving between
        access points all day cannot fill storage (rule UP-19)."""
        mine = [i for i, r in enumerate(table) if isinstance(r, dict) and r.get(ADDR_DEVICE_ID) == device_id]
        extra = len(mine) - ADDRESS_ROWS_PER_DEVICE
        if extra > 0:
            for i in reversed(mine[:extra]):
                del table[i]

    def _judge_shared_addresses(
        self, holders: dict[str, set[str]], trackers: dict[str, str], now: float
    ) -> None:
        """Flag an address two devices hold at once for 10 minutes,
        through two different pieces of hardware: two trackers with
        two MACs (rule UP-19)."""
        since: dict[str, float] = self._shared_since  # type: ignore[attr-defined]
        shared_now: dict[str, list[str]] = {}
        for ip, devices in holders.items():
            if len({trackers[d] for d in devices}) < 2:
                continue
            first = since.setdefault(ip, now)
            if now - first >= SHARED_ADDRESS_SECONDS:
                shared_now[ip] = sorted(devices)
        for ip in list(since):
            ids = holders.get(ip) or set()
            if len({trackers[d] for d in ids if d in trackers}) < 2:
                since.pop(ip, None)
        if shared_now != self._shared_addresses:  # type: ignore[attr-defined]
            self._shared_addresses = shared_now
            self._shared_addresses_changed()

    def _shared_addresses_changed(self) -> None:
        """Raise or clear the Repair card at once, and let the dashboard
        refresh, when the flagged addresses change (rule UP-19)."""
        from .repairs import async_evaluate_shared_addresses

        names = {
            ip: [str(self._device_name(d)) for d in ids]  # type: ignore[attr-defined]
            for ip, ids in self._shared_addresses.items()  # type: ignore[attr-defined]
        }
        try:
            async_evaluate_shared_addresses(self.hass, self.entry, names)  # type: ignore[attr-defined]
        except Exception as err:  # noqa: BLE001 - a card never breaks the tick
            from .const import LOGGER

            LOGGER.debug("Device Sentinel could not update the shared address card: %s", err)
        mark = getattr(self, "_mark_changed", None)
        if mark is not None:
            mark()

    def shared_addresses(self) -> dict[str, list[str]]:
        """The addresses held by two devices at once for 10 minutes, each
        with the devices holding it (rule UP-19)."""
        return dict(self._shared_addresses)  # type: ignore[attr-defined]

    def address_of(self, device_id: str) -> dict[str, Any] | None:
        """The device page's address and access point, each with when it
        last changed, or None for a device no tracker reports (rule UP-19)."""
        row = self._address_index().get(device_id)
        if row is None:
            return None
        rows = [
            r for r in self.data.get(DATA_ADDRESS_CHANGES) or []  # type: ignore[attr-defined]
            if isinstance(r, dict) and r.get(ADDR_DEVICE_ID) == device_id
            and isinstance(r.get(ADDR_WHEN), (int, float))
        ]
        rows.sort(key=lambda r: r[ADDR_WHEN])

        def since(field: str) -> str | None:
            value = row.get(field)
            moment = None
            for r in reversed(rows):
                if r.get(field) != value:
                    break
                moment = r[ADDR_WHEN]
            return dt_util.utc_from_timestamp(moment).isoformat() if moment is not None else None

        return {
            "ip": row.get(ADDR_IP),
            "ip_since": since(ADDR_IP),
            "ap": row.get(ADDR_AP),
            "ap_since": since(ADDR_AP),
            "shared": any(device_id in ids for ids in self._shared_addresses.values()),  # type: ignore[attr-defined]
        }
