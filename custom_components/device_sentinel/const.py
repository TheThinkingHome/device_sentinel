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

# Per-device storage field names.
DEV_LAST_ACTIVITY = "last_activity"
DEV_DAILY_MAX = "daily_max"
DEV_TODAY_MAX = "today_max"
DEV_FIRST_OBSERVED = "first_observed"
DEV_EVENT_COUNT = "event_count"
DEV_TAINTED = "tainted"

# Step 2 provisional tunables (ruled 2026-07-10; the soak's own logs
# confirm or correct them; see the project document, Remaining Tunables).
#
# Startup grace: stamps update clocks but complete no gaps for
# learning while the restored-state echo wave and the boot republish
# pass. Descends from the blueprints' 240 s settling debounce.
STARTUP_GRACE_SECONDS = 300

# Storm detector: a storm is declared for a config entry when its
# events touch STORM_DEVICE_THRESHOLD distinct devices within
# STORM_WINDOW_SECONDS, and it ends after STORM_RELEASE_SECONDS below
# threshold. Distinct devices is the discriminator: one chatty plug
# can organically write dozens of times a second, but nothing organic
# makes fifteen separate devices speak inside two seconds.
STORM_DEVICE_THRESHOLD = 15
STORM_WINDOW_SECONDS = 2.0
STORM_RELEASE_SECONDS = 5.0

# Rolling statistics: daily maxima kept per device. 14 days records
# more than the rolling window will need, so the window-length
# tunable can be settled from soak data without re-collecting.
DAILY_MAX_KEEP = 14

# Provisional arming floor: a device with at least this many daily
# maxima counts as rhythm-established for the learning-progress
# sensor. Arming criteria proper are settled during the soak.
LEARNING_MIN_DAYS = 7

# Storage save cadence: at most one write per render tick when dirty.
RENDER_TICK_SECONDS = 60

# Identity attributes carried on every entity, per blueprint precedent.
ATTR_SENTINEL_TYPE = "sentinel_type"
ATTR_SENTINEL_VERSION = "sentinel_version"
ATTR_FIRST_INSTALLED = "first_installed"
ATTR_STORAGE_HEALTHY = "storage_healthy"

SENTINEL_TYPE_STATUS = "status"
SENTINEL_TYPE_COVERAGE = "coverage"
SENTINEL_TYPE_LEARNING = "learning_progress"
SENTINEL_TYPE_CLASSIFICATION = "classification"
SENTINEL_TYPE_CLOCK_SOURCE = "clock_source"
