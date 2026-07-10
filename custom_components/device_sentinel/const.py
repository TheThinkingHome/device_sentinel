"""Constants for the Device Sentinel integration."""

from __future__ import annotations

import logging

DOMAIN = "device_sentinel"

# The literal logger name, per the Sentinel blueprint precedent
# (battery_sentinel, entity_sentinel). Users configure it under
# this exact name in their logger: settings.
LOGGER = logging.getLogger(DOMAIN)

# Persistent storage. Lives in Home Assistant's .storage directory,
# never in custom_components (code, overwritten on every update).
STORAGE_KEY = f"{DOMAIN}.storage"
STORAGE_VERSION = 1

# Storage field names.
DATA_FIRST_INSTALLED = "first_installed"
DATA_SETUP_COUNT = "setup_count"
DATA_DEVICES = "devices"

# Identity attributes carried on every entity, per blueprint precedent.
ATTR_SENTINEL_TYPE = "sentinel_type"
ATTR_SENTINEL_VERSION = "sentinel_version"
ATTR_FIRST_INSTALLED = "first_installed"
ATTR_STORAGE_HEALTHY = "storage_healthy"

SENTINEL_TYPE_STATUS = "status"
