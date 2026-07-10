"""Coordinator for the Device Sentinel integration.

Step 1 backbone: owns the persistent storage and proves the round-trip
that everything later depends on. The passive telemetry layer (event
intake, gap statistics, learned rhythms) arrives here in Step 2.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DATA_DEVICES,
    DATA_FIRST_INSTALLED,
    DATA_SETUP_COUNT,
    LOGGER,
    STORAGE_KEY,
    STORAGE_VERSION,
)


class DeviceSentinelCoordinator:
    """Owns Device Sentinel's persistent storage and status data."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, version: str
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.version = version
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self.data: dict[str, Any] = {}
        self.storage_healthy: bool = False

    async def async_setup(self) -> None:
        """Load storage, stamp the setup, and save it back.

        first_installed is written once and never rewritten.
        setup_count increments on every setup, meaning every restart,
        so the status sensor proves persistence on a dashboard with
        no tooling.
        """
        loaded = await self._store.async_load()
        if loaded is None:
            LOGGER.info(
                "Device Sentinel v%s: no existing storage, creating %s",
                self.version,
                STORAGE_KEY,
            )
            loaded = {
                DATA_FIRST_INSTALLED: dt_util.utcnow().isoformat(),
                DATA_SETUP_COUNT: 0,
                DATA_DEVICES: {},
            }

        loaded[DATA_SETUP_COUNT] = int(loaded.get(DATA_SETUP_COUNT, 0)) + 1
        loaded.setdefault(DATA_FIRST_INSTALLED, dt_util.utcnow().isoformat())
        loaded.setdefault(DATA_DEVICES, {})

        self.data = loaded
        await self._store.async_save(self.data)
        self.storage_healthy = True

        LOGGER.info(
            "Device Sentinel v%s setup complete: setup_count=%s, "
            "first_installed=%s",
            self.version,
            self.setup_count,
            self.first_installed,
        )

    @property
    def setup_count(self) -> int:
        """Return how many times the integration has set up."""
        return int(self.data.get(DATA_SETUP_COUNT, 0))

    @property
    def first_installed(self) -> str | None:
        """Return the ISO timestamp of the first ever setup."""
        return self.data.get(DATA_FIRST_INSTALLED)
