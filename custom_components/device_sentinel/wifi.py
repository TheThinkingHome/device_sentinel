# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: wifi.py, Version: 0.30.0 (2026-11-21)

"""Is the WiFi network up? Asked of the host's own radio.

Seeing an outage and saying which devices went with it are separate
jobs with separate sources. This file answers the first: whether the
network exists at all. It needs no router integration, so it works
the same whatever router a person owns, because most router
integrations publish nothing usable. Which devices went down with it
is the other question, answered by `router_ties.py` where a
supported router exists (rule UP-12).

**The network is up while any access point broadcasts a chosen name**,
whatever its signal (rule UP-12). The scan reports what the host's
radio can hear from where the server sits, so a weak reading means
the host is far from that access point rather than that the access
point is failing: a mesh satellite fifty feet away behind three
concrete walls may serve the devices beside it perfectly while barely
reaching the server. Judging it by its signal at the server would be
judging the wrong thing.

On a two satellite mesh across a night of scans, the near satellite
was missing from one sweep of about two hundred, the far one from
fifty nine, and both from none at all. A router reboot takes about
thirty seconds, so the confirmation delay defaults to sixty, twice
that.

An outage is dated from when the last access point went missing, not
from when the delay expired, so what is reported is the real length.

Absent everywhere it cannot work: no Supervisor, no wireless adapter,
or no networks chosen, and this file does nothing at all. On such a
system `router_ties.py` keeps its own trigger (rule UP-12).
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_WIFI_CONFIRM_SECONDS,
    CONF_WIFI_NETWORKS,
    DEFAULT_WIFI_CONFIRM_SECONDS,
    LOGGER,
)

SUPERVISOR = "hassio"
NETWORK_INFO = "/network/info"
OS_INFO = "/os/info"


def said(err: BaseException) -> str:
    """An error as the log can read it: its kind, and its words when it
    has any. A request cut off as Home Assistant stops carries no words,
    so its kind is all there is to say."""
    text = str(err).strip()
    return f"{type(err).__name__}: {text}" if text else type(err).__name__


async def read_interfaces_why(hass) -> tuple[list[dict[str, Any]] | None, str]:
    """The host's network interfaces, or None, with why none came back:
    "no_supervisor" where Home Assistant runs without the Supervisor, as
    a Container or Core install does, or the kind of error the
    Supervisor gave. Read-only: nothing here writes to the host
    (rule UP-12)."""
    handler = hass.data.get(SUPERVISOR)
    if handler is None:
        return None, "no_supervisor"
    try:
        info = await handler.send_command(NETWORK_INFO, method="get")
    except Exception as err:  # noqa: BLE001 - absent is not broken
        LOGGER.debug("device_sentinel: supervisor network read failed: %s", said(err))
        return None, f"supervisor_error: {type(err).__name__}"
    payload = info.get("data") if isinstance(info, dict) else None
    rows = (payload or info or {}).get("interfaces") or []
    return [row for row in rows if isinstance(row, dict)], "ok"


async def read_interfaces(hass) -> list[dict[str, Any]] | None:
    """Return the host's network interfaces, or None if it cannot be
    asked. Read-only: nothing here writes to the host."""
    rows, _why = await read_interfaces_why(hass)
    return rows


async def wireless_interfaces(hass) -> list[dict[str, Any]]:
    """Every wireless interface the host has, configured or not."""
    return [
        row for row in (await read_interfaces(hass) or [])
        if row.get("type") == "wireless"
    ]


def pick_adapter(wireless: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The wireless adapter to scan with: the one connected to a network,
    then one switched on, then the first listed (rule UP-12).

    A server can have two, its own and a USB adapter plugged in for
    range, and the Supervisor lists them in no promised order. An
    adapter switched off, or on but joined to no network, hears
    nothing, so the first listed alone can be the wrong one.
    """
    for wanted in (
        lambda row: row.get("connected") is True,
        lambda row: row.get("enabled") is not False,
    ):
        for row in wireless:
            if wanted(row):
                return row
    return wireless[0] if wireless else None


def adapter_rows(wireless: list[dict[str, Any]], used: str | None) -> list[dict[str, Any]]:
    """Each wireless adapter for the diagnostics download: its name,
    whether it is switched on and connected, and whether it is the one
    in use. Never its network's name or its address (rule STOR-21)."""
    return [
        {
            "interface": row.get("interface"),
            "enabled": row.get("enabled"),
            "connected": row.get("connected"),
            "used": used is not None and row.get("interface") == used,
        }
        for row in wireless
    ]


async def read_board(hass) -> str | None:
    """The hardware Home Assistant OS reports, such as "rpi4-64", "green"
    or "generic-x86-64", or None where it cannot be asked."""
    handler = hass.data.get(SUPERVISOR)
    if handler is None:
        return None
    try:
        info = await handler.send_command(OS_INFO, method="get")
    except Exception as err:  # noqa: BLE001 - absent is not broken
        LOGGER.debug("device_sentinel: supervisor os read failed: %s", said(err))
        return None
    payload = info.get("data") if isinstance(info, dict) else None
    board = (payload or info or {}).get("board")
    return board if isinstance(board, str) and board else None


async def scan_networks(hass, interface: str) -> list[dict[str, Any]] | None:
    """Return every access point the radio can hear, or None.

    Each carries its own hardware address, so two satellites of one
    mesh broadcasting the same name are two entries rather than one.
    """
    handler = hass.data.get(SUPERVISOR)
    if handler is None:
        return None
    try:
        result = await handler.send_command(
            f"/network/interface/{interface}/accesspoints", method="get"
        )
    except Exception as err:  # noqa: BLE001 - absent is not broken
        LOGGER.debug("device_sentinel: wifi scan failed: %s", said(err))
        return None
    payload = result.get("data") if isinstance(result, dict) else None
    return (payload or result or {}).get("accesspoints") or []


class WifiScanMixin:
    """Watch the host's radio for the networks a person named."""

    # ------------------------------------------------------- settings

    @property
    def wifi_networks(self) -> list[str]:
        """The network names being watched, as chosen."""
        chosen = self.entry.options.get(CONF_WIFI_NETWORKS) or []
        return [name for name in chosen if isinstance(name, str) and name]

    @property
    def wifi_confirm_seconds(self) -> float:
        return float(
            self.entry.options.get(
                CONF_WIFI_CONFIRM_SECONDS, DEFAULT_WIFI_CONFIRM_SECONDS
            )
        )

    @property
    def wifi_scan_configured(self) -> bool:
        """Whether this house can detect an outage from its own radio.

        A network was chosen and an interface was found. Where this is
        false the scan does nothing and the router ties keep their own
        trigger.
        """
        return bool(self.wifi_networks and self._wifi_scan_interface)

    async def async_check_unused_adapter(self) -> None:
        """Note a wireless adapter that no chosen network puts to use.

        Asked before each report is written, because the brief is
        composed in the executor and the Supervisor answers on the
        loop. Only where no network is chosen: once one is, the sweep
        finds the adapter itself and the question has been answered.
        Held in memory, since the adapter is read again at every
        write (rule REC-02).
        """
        self._wifi_adapter_unused = None
        self._wifi_adapter_off = False
        if self.wifi_networks:
            return
        adapter = pick_adapter(await wireless_interfaces(self.hass))
        if adapter is not None:
            self._wifi_adapter_unused = adapter.get("interface") or "wireless"
            # The Supervisor says whether the interface is switched on.
            # Only a plain False reads as off: a field it leaves out
            # says nothing (rule REC-02).
            self._wifi_adapter_off = adapter.get("enabled") is False

    @property
    def wifi_scan_down_at(self) -> float | None:
        """When the last chosen network stopped being heard."""
        return self._wifi_scan_down_at

    @property
    def wifi_missing_networks(self) -> list[str]:
        """Chosen networks the radio cannot currently hear.

        Reported on the status sensor, because a network chosen while
        it was up and never heard since is a thing a person needs
        told: it may have been renamed, or it may be gone.
        """
        return sorted(set(self.wifi_networks) - set(self._wifi_heard))

    # ---------------------------------------------------------- sweep

    async def async_sweep_wifi(self, _now=None) -> None:
        """Ask the radio what it can hear, and judge it.

        One sweep per WIFI_SCAN_SECONDS. Where nothing is configured
        this returns on its first line, so a house without a wireless
        adapter pays a dictionary lookup a minute.
        """
        chosen = self.wifi_networks
        if not chosen:
            return
        if self._wifi_scan_interface is None:
            adapter = pick_adapter(await wireless_interfaces(self.hass))
            if adapter is None:
                return
            self._wifi_scan_interface = adapter.get("interface")
            if self._wifi_scan_interface is None:
                return

        points = await scan_networks(self.hass, self._wifi_scan_interface)
        if points is None:
            # The Supervisor did not answer. An unanswered question is
            # not a missing network, and treating it as one would
            # declare an outage every time Home Assistant shuts down.
            return
        # The same scan tells which channel each network uses (rule
        # SIG-19): no second scan where a network is chosen.
        note_air = getattr(self, "_note_air", None)
        if callable(note_air):
            note_air(points, dt_util.utcnow().timestamp())

        heard = {
            point.get("ssid")
            for point in points
            if isinstance(point.get("ssid"), str) and point.get("ssid")
        }
        self._wifi_heard = heard
        now = dt_util.utcnow().timestamp()
        missing = [name for name in chosen if name not in heard]

        if not missing:
            if self._wifi_scan_down_at is not None:
                self._wifi_scan_restore(now)
            elif self._wifi_scan_gone_at is not None:
                # Back inside the wait: no outage, and the log says so, so
                # a "holding" line is never left without its ending.
                LOGGER.debug(
                    "device_sentinel: %s heard again after %ds, no outage",
                    ", ".join(chosen),
                    int(max(0.0, now - self._wifi_scan_gone_at)),
                )
            self._wifi_scan_gone_at = None
            return

        if self._wifi_scan_down_at is not None:
            return
        if self._wifi_scan_gone_at is None:
            # The moment it went, kept so the outage can be dated from
            # here rather than from the end of the delay.
            self._wifi_scan_gone_at = now
            LOGGER.debug(
                "device_sentinel: %s not heard, holding %ds before "
                "reporting",
                ", ".join(missing),
                int(self.wifi_confirm_seconds),
            )
            return
        if now - self._wifi_scan_gone_at >= self.wifi_confirm_seconds:
            self._wifi_scan_declare(self._wifi_scan_gone_at, missing)

    # ----------------------------------------------------- the verdict

    def _wifi_scan_declare(self, since: float, missing: list[str]) -> None:
        self._wifi_scan_down_at = since
        LOGGER.debug(
            "device_sentinel: wifi outage, %s not heard since %s",
            ", ".join(missing),
            dt_util.utc_from_timestamp(since).isoformat(),
        )
        self.on_wifi_scan_down(since, missing)

    def _wifi_scan_restore(self, now: float) -> None:
        since = self._wifi_scan_down_at
        self._wifi_scan_down_at = None
        LOGGER.debug(
            "device_sentinel: wifi outage over after %.0fs",
            max(0.0, now - (since or now)),
        )
        self.on_wifi_scan_restored(since, now)

    # These two are what the coordinator overrides to join the scan to
    # the rest of the upstream machinery. Defined here so this file
    # can be read, and tested, without it.
    @callback
    def on_wifi_scan_down(self, since: float, missing: list[str]) -> None:
        """A chosen network stopped being heard."""

    @callback
    def on_wifi_scan_restored(
        self, since: float | None, now: float
    ) -> None:
        """Every chosen network is heard again."""

    # ---------------------------------------------------- diagnostics

    async def async_adapter_diagnostics(self) -> dict[str, Any]:
        """Why the server can or cannot watch Wi-Fi, read fresh for the
        download: whether the Supervisor answered, every wireless adapter
        it listed and which one is in use, and the hardware (rule UP-12)."""
        rows, why = await read_interfaces_why(self.hass)
        wireless = [row for row in rows or [] if row.get("type") == "wireless"]
        if rows is not None and not wireless:
            why = "no_adapter"
        used = self._wifi_scan_interface
        if used is None:
            picked = pick_adapter(wireless)
            used = picked.get("interface") if picked is not None else None
        return {
            "why": why,
            "adapters": adapter_rows(wireless, used),
            "board": await read_board(self.hass),
        }

    @property
    def wifi_scan_diagnostics(self) -> dict[str, Any]:
        """What the scan knows, for a diagnostics download."""
        return {
            "configured": self.wifi_scan_configured,
            "interface": self._wifi_scan_interface,
            "networks": self.wifi_networks,
            "heard": sorted(self._wifi_heard),
            "missing": self.wifi_missing_networks,
            "confirm_seconds": self.wifi_confirm_seconds,
            "gone_at": self._wifi_scan_gone_at,
            "down_since": (
                dt_util.utc_from_timestamp(self._wifi_scan_down_at).isoformat()
                if self._wifi_scan_down_at is not None
                else None
            ),
        }

