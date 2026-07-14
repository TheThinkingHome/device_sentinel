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

# Storm duty-cycle exemption: an integration storming chronically is a
# synchronized poller (all its devices update in the same instant every
# scan), not a republisher. Its devices' honest rhythm is the poll
# cadence, so storm exclusion stops applying to it. Provisional per the
# soak, learned from the tplink_router finding (920 storms overnight).
STORM_EXEMPT_PER_HOUR = 10
STORM_HISTORY_SECONDS = 3600

# Taint debounce: an unavailable or unknown shorter than this is a
# hiccup, not an outage; it sets no taint. Matches the blueprints'
# three-minute unavailable debounce. Provisional per the soak.
TAINT_DEBOUNCE_SECONDS = 180

# Statistics epoch: when storage carries an older epoch, learned
# statistics (daily maxima, event counts, signal minima) are wiped
# once so every rhythm is learned under the final rule set. Clocks
# and identity survive.
STATS_EPOCH = "0.2.3"
DATA_STATS_EPOCH = "stats_epoch"

# Per-device signal fields (linkquality/RSSI, gather-first).
DEV_SIGNAL_VALUE = "signal_value"
DEV_SIGNAL_TODAY_MIN = "signal_today_min"
DEV_SIGNAL_DAILY_MIN = "signal_daily_min"

# Signal-entity recognition terms (Z2M sets no device class on
# linkquality; ZHA/Z-Wave use device_class signal_strength).
SIGNAL_NAME_TERMS = ("linkquality", "lqi", "rssi")

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

# Diagnostic files, written at every setup and after every midnight
# rollover. They live under /config, never under custom_components
# (code, wiped on update). Markdown since 0.2.6 so the maxima lists
# can carry emphasis (set-aside outliers struck through, the window
# basis bold).
REPORT_DIR = "device_sentinel"
REPORT_TELEMETRY = "device_telemetry.md"
REPORT_CLASSIFICATION = "classification.md"
REPORT_STALE_FILES = ("device_telemetry.txt", "classification.txt")

# The trimmed maximum, previewed in the telemetry report (display
# only during the soak; becomes the Step 4 window rhythm). The top
# TRIM_TOP_K daily maxima are set aside as suspected anomalies and
# the operative rhythm is the maximum of the survivors, so one
# anomalous day moves nothing while a recurring high value counts.
# Below TRIM_MIN_SAMPLES days there are too few samples to spare
# any, so nothing is trimmed. Both are soak-settled provisionals.
TRIM_TOP_K = 1
TRIM_MIN_SAMPLES = 7

# Step 3: battery detection (value-only; liveness belongs to Step 4).
# The threshold is user-configurable through the options flow because
# batteries drift slowly: proving detection live means sliding the
# threshold above a real cell's level. The clear margin is small (2)
# because a load-driven rest-rebound is a genuine recovery that
# should clear the flag, not a flap to suppress; widen only if the
# soak shows flapping.
CONF_LOW_THRESHOLD = "low_threshold"
DEFAULT_LOW_THRESHOLD = 20
BATTERY_CLEAR_MARGIN = 2

# Per-device battery storage fields.
DEV_BATTERY_LOW = "battery_low"
DEV_BATTERY_SINCE = "battery_since"
DEV_BATTERY_VALUE = "battery_value"

SENTINEL_TYPE_BATTERY_COUNT = "battery_low_count"
SENTINEL_TYPE_BATTERY_LIST = "battery_low_list"

# Signal preview (0.3.1, display-only). The floor is the trimmed
# minimum of the rolling daily signal minima (mirror of the gap
# rule: drop the bottom TRIM_TOP_K as anomalies once
# TRIM_MIN_SAMPLES days exist). The candidate danger line is
# family-specific because one number cannot serve both unit
# families: LQI is positive (bigger is better, scale varies by
# stack), dBm RSSI is negative. Family is detected by sign. These
# formulas are previewed in device_telemetry.md and ruled from real
# data before any detection acts on them.
SIGNAL_ARMING_DAYS = 7
SIGNAL_LQI_DANGER_FACTOR = 0.5
SIGNAL_RSSI_DANGER_OFFSET = 10.0

# Notification backbone (0.3.3, mirrored to Sentinel Notify at 0.3.4).
# The configuration surface only: where high and normal pushes go,
# the persistent card, the quiet-hours window, and the daily reminder.
# Stored and inert until the Step 5 engine reads them; nothing sends,
# gates, or diffs yet. The engine is separable from its configuration,
# so the backbone is built and tested alone.
#
# Two target lists, matching the blueprint: high-priority targets
# bypass Do Not Disturb and pierce quiet hours; normal-priority
# targets get standard delivery and are held during quiet hours. A
# target in both lists is treated as high (normalized on save so the
# engine inherits the rule). Either list may be empty.
CONF_HIGH_PRIORITY_TARGETS = "high_priority_targets"
CONF_NORMAL_PRIORITY_TARGETS = "normal_priority_targets"
CONF_PERSISTENT_ENABLED = "persistent_enabled"
CONF_QUIET_ENABLED = "quiet_hours_enabled"
CONF_QUIET_START = "quiet_hours_start"
CONF_QUIET_END = "quiet_hours_end"
CONF_REMINDER_MODE = "daily_reminder_mode"
CONF_REMINDER_TIME = "daily_reminder_time"

DEFAULT_PERSISTENT_ENABLED = True
DEFAULT_QUIET_ENABLED = False
DEFAULT_QUIET_START = "22:00:00"
DEFAULT_QUIET_END = "08:00:00"
DEFAULT_REMINDER_MODE = "none"
DEFAULT_REMINDER_TIME = "08:00:00"

# Daily reminder modes, semantics carried from Sentinel Notify.
REMINDER_MODE_NONE = "none"
REMINDER_MODE_OVERNIGHT = "overnight"
REMINDER_MODE_DAILY = "daily"
