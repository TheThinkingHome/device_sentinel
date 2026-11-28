# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.

"""Keep only the config entry's options across an opted-in removal (STOR-24)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import (
    CONF_KEEP_CONFIG_ON_REMOVAL,
    CONF_TRIM_DEVICES,
    CONF_TRIM_INTEGRATIONS,
    DOMAIN,
    LOGGER,
)

KEPT_CONFIG_KEY = f"{DOMAIN}.kept_config"


def _store(hass: HomeAssistant) -> Store[dict[str, Any]]:
    return Store(hass, 1, KEPT_CONFIG_KEY, private=True, atomic_writes=True)


def _settings(options: Mapping[str, Any]) -> dict[str, Any]:
    # Trim picks are instructions to delete data, not reusable settings.
    return {
        key: value for key, value in options.items()
        if key not in (CONF_TRIM_DEVICES, CONF_TRIM_INTEGRATIONS)
    }


async def _async_read(hass: HomeAssistant) -> dict[str, Any] | None:
    try:
        payload = await _store(hass).async_load()
    except (
        HomeAssistantError, ValueError, OSError, KeyError, TypeError,
        AttributeError, NotImplementedError,
    ) as err:
        LOGGER.warning("Could not read kept Device Sentinel settings: %s", type(err).__name__)
        return None
    if payload is None:
        return None
    if (
        not isinstance(payload, dict)
        or type(payload.get("minor_version")) is not int
        or payload["minor_version"] < 1
        or not isinstance(payload.get("options"), dict)
    ):
        LOGGER.warning("Kept Device Sentinel settings have an invalid format")
        return None
    return payload


async def async_load_kept_options(hass: HomeAssistant) -> tuple[int, dict[str, Any]] | None:
    """Read a settings snapshot for use when creating a new entry."""
    payload = await _async_read(hass)
    if payload is None:
        return None
    return payload["minor_version"], _settings(payload["options"])


async def async_save_kept_options(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Save the final options only when explicitly requested, and verify the write."""
    if entry.options.get(CONF_KEEP_CONFIG_ON_REMOVAL) is not True:
        return False
    payload = {
        "minor_version": entry.minor_version,
        "options": _settings(entry.options),
    }
    try:
        await _store(hass).async_save(payload)
    except (HomeAssistantError, OSError) as err:
        LOGGER.warning("Could not save Device Sentinel settings: %s", type(err).__name__)
        return False
    if await _async_read(hass) == payload:
        return True
    LOGGER.warning("Could not save Device Sentinel settings for reinstallation")
    return False