# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: wifi.py, Version: 0.20.9 (2026-09-06)

"""Is the WiFi network up? Asked of the host's own radio.

Detection and attribution are separate jobs with separate sources
(#391). This file answers the first: whether the network exists at
all. It needs no router integration, so it works the same whatever
router a person owns, which matters because of sixteen router
integrations read from source, most publish nothing usable. Which
devices went down with it is the other question, answered by
`router_ties.py` where a supported router exists.

**The network is up while any access point broadcasts a chosen name**
(#392). Not a signal threshold. The scan reports what the host's
radio can hear from where the server sits, so a weak reading means
the host is far from that access point rather than that the access
point is failing: a mesh satellite fifty feet away behind three
concrete walls may serve the devices beside it perfectly while barely
reaching the server. Judging it by its signal at the server would be
judging the wrong thing.

Measured across a night of scans on a two satellite mesh: the near
satellite was missing from one sweep of about two hundred, the far
one from fifty nine, and both from none at all. The one real event
was the nightly router reboot, thirty seconds, confirmed
independently by the host's own association dropping and returning.
The confirmation delay defaults to sixty seconds, twice that.

An outage is dated from when the last access point went missing, not
from when the delay expired, so what is reported is the real length.

Absent everywhere it cannot work: no Supervisor, no wireless adapter,
or no networks chosen, and this file does nothing at all. On such a
system `router_ties.py` keeps its own trigger, exactly as it did
before this existed.
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
    WIFI_SCAN_SECONDS,
)

SUPERVISOR = "hassio"
NETWORK_INFO = "/network/info"


async def read_interfaces(hass) -> list[dict[str, Any]] | None:
    """Return the host's network interfaces, or None if it cannot be
    asked. Read-only: nothing here writes to the host."""
    handler = hass.data.get(SUPERVISOR)
    if handler is None:
        return None
    try:
        info = await handler.send_command(NETWORK_INFO, method="get")
    except Exception as err:  # noqa: BLE001 - absent is not broken
        LOGGER.debug("device_sentinel: supervisor network read failed: %s", err)
        return None
    payload = info.get("data") if isinstance(info, dict) else None
    return (payload or info or {}).get("interfaces") or []


async def wireless_interfaces(hass) -> list[dict[str, Any]]:
    """Every wireless interface the host has, configured or not."""
    return [
        row for row in (await read_interfaces(hass) or [])
        if row.get("type") == "wireless"
    ]


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
        LOGGER.debug("device_sentinel: wifi scan failed: %s", err)
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
            found = await wireless_interfaces(self.hass)
            if not found:
                return
            self._wifi_scan_interface = found[0].get("interface")
            if self._wifi_scan_interface is None:
                return

        points = await scan_networks(self.hass, self._wifi_scan_interface)
        if points is None:
            # The Supervisor did not answer. An unanswered question is
            # not a missing network, and treating it as one would
            # declare an outage every time Home Assistant shuts down.
            return

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
            self._wifi_scan_gone_at = None
            return

        if self._wifi_scan_down_at is not None:
            return
        if self._wifi_scan_gone_at is None:
            # The moment it went, kept so the outage can be dated from
            # here rather than from the end of the delay.
            self._wifi_scan_gone_at = now
            LOGGER.info(
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
        LOGGER.info(
            "device_sentinel: wifi outage, %s not heard since %s",
            ", ".join(missing),
            dt_util.utc_from_timestamp(since).isoformat(),
        )
        self.on_wifi_scan_down(since, missing)

    def _wifi_scan_restore(self, now: float) -> None:
        since = self._wifi_scan_down_at
        self._wifi_scan_down_at = None
        LOGGER.info(
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


WIFI_SWEEP_SECONDS = WIFI_SCAN_SECONDS
