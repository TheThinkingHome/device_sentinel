# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.4.12 (2026-07-19)

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
# The dwell recorder (0.4.0). Two clocks per device: below_since is
# the open timer stamped when a reading crosses under the danger
# line, and below_today_seconds is the day's accumulated time under
# it. The rolling daily history keeps the percentage of each day
# spent below, beside the daily minimum that feeds the floor: the
# minimum says how bad the worst moment was, the dwell says how long
# the bad lasted, and neither can stand in for the other.
DEV_SIGNAL_BELOW_SINCE = "signal_below_since"
DEV_SIGNAL_BELOW_TODAY = "signal_below_today_seconds"
DEV_SIGNAL_DWELL_DAILY = "signal_dwell_daily_pct"
# last_change is when the signal value last actually moved. Kept for
# the dwell timer and diagnostics; the rail detector reads the daily
# low series, not this.
DEV_SIGNAL_LAST_CHANGE = "signal_last_change"

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
# The discharge recorder (0.4.2). At each midnight the current battery
# value is appended here, so the history is a daily series of levels
# (89, 89, 88, 88, 80, 65). The daily delta the velocity flag will
# read is derived from consecutive points, which lets a missed day
# spread its drop across the elapsed time rather than reading as a
# false cliff. The value is stored, not only the delta, because it is
# cheap and makes the series self-describing and gap-tolerant. Kept
# for the same 14 days as every other daily series: at two weeks and
# a day the oldest point retires, which is the minimum span a lithium
# cliff needs to show its acceleration. The velocity flag itself
# waits until this history has depth, the way the dwell danger line
# waited on the floor.
DEV_BATTERY_DAILY = "battery_daily_value"

SENTINEL_TYPE_LOW_BATTERIES = "low_batteries"
SENTINEL_TYPE_SIGNAL_PROBLEMS = "signal_problems"
SENTINEL_TYPE_FROZEN_DEVICES = "frozen_devices"
SENTINEL_TYPE_TRACKED_SIGNALS = "tracked_signals"
SENTINEL_TYPE_TRACKED_BATTERIES = "tracked_batteries"
SENTINEL_TYPE_TRACKED_DEVICES = "tracked_devices"

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

# The floor is the line (ruled 2026-07-19, replacing the 70 percent
# factor and the dB offset after the first clean dwell day read
# near-zero across the whole fleet). Dwell counts time spent at or
# below the device's own trimmed floor. A line set below the floor
# could only catch catastrophe, so it read zero on every healthy day
# and proved nothing; a line at the trimmed floor is brushed by a
# healthy device on its bad moments (the small 0 to 5 percent that
# proves the detector has teeth) and clearly exceeded by a device
# living at its lows (the anomaly). One rule for both scales: below
# is below, whether the number is an LQI index or negative dBm.
#
# The floor is chosen by a trim ladder that grows with the soak:
# under a week no reading is dropped, at a week the single lowest is,
# at two weeks the two lowest are, so the floor settles from "worst
# ever seen" to "typical worst" as the history earns trust. The trim
# drops the LOWEST values, the opposite of the rhythm trim which
# drops the highest, because for signal the spuriously bad reading is
# the anomaly to set aside.
SIGNAL_TRIM_LADDER_WEEK = 1
SIGNAL_TRIM_LADDER_FORTNIGHT = 2

# The user's sensitivity adjustment, added to the ladder's k and
# clamped so the effective k always leaves at least one reading to be
# the floor. Left (negative) trims less: the floor sits at the rawest
# low and is rarely crossed. Right (positive) trims more: the floor
# sits higher and is brushed more often. Not retroactive: a change
# recomputes the floor for readings that follow; time already counted
# stays counted, so a full clean day is needed to see its true
# effect, which is why this lives on the config screen rather than as
# a live entity.
CONF_SIGNAL_SENSITIVITY = "signal_sensitivity"
DEFAULT_SIGNAL_SENSITIVITY = 0
SIGNAL_SENSITIVITY_MIN = -2
SIGNAL_SENSITIVITY_MAX = 2

# Signal-only excludes, the same broad-to-narrow ladder as battery:
# integration, label, device. Exclusion suppresses judgment, not
# observation: an excluded device keeps recording its floor and dwell
# in storage, so re-including it is instant and arrives with history;
# it simply stops being reported. This is the manual removal from
# tracking the frozen-signal ruling requires, given a surface: a
# device that resists every recovery (the development system's living
# room router plug) can be silenced without blinding the watcher.
CONF_SIGNAL_EXCLUDED_DEVICES = "signal_excluded_devices"
CONF_SIGNAL_EXCLUDED_INTEGRATIONS = "signal_excluded_integrations"
CONF_SIGNAL_EXCLUDED_LABELS = "signal_excluded_labels"

# The rails (ruled 2026-07-18). A rail is a value that is flat and at
# the type's extreme: healthy LQI across the fleet tops out at 224,
# so a flat 255 is the fill value of a field the device never
# populated, not a reading. -128 is the dBm rail on the RSSI side.
# Rail readings never feed the floor and never feed the dwell timer;
# they feed the stuck detector instead. Recovery was validated by
# hand (force a report, then power cycle or battery pull, then
# re-interview or re-bind); removal from tracking is manual only.
SIGNAL_RAIL_LQI = 255.0
SIGNAL_RAIL_RSSI = -128.0

# A signal is railed when its daily low sits at the fill value (255,
# -128) for this many consecutive days (ruled 2026-07-19 evening). The
# live repeat counter that preceded this was removed with the frozen
# rework: it could not tell a stuck signal from a healthy steady link,
# because some devices report the same value for hours. Reading the
# daily-low series instead means a rail that comes and goes within a
# day never confirms, while one that holds across days does, with no
# per-reading state to keep.
RAIL_CONFIRM_DAYS = 3

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

# The problem list (0.3.5). One todo entity, not one per family:
# the type lives on each item, so a single list matches the
# novice-first thesis while losing nothing. Items are stored under
# their own storage key, separate from per-device telemetry, because
# they are problem records rather than device statistics.
DATA_TODO_ITEMS = "todo_items"

TODO_UID = "uid"
TODO_SUMMARY = "summary"
TODO_DESCRIPTION = "description"
TODO_STATUS = "status"
TODO_SORT_NAME = "sort_name"
TODO_KIND = "kind"
TODO_OURS = "ours"

# Item kinds, one per detection family. The engine sets these at
# Step 5; the backbone only carries them.
TODO_KIND_BATTERY = "battery"
TODO_KIND_FROZEN = "frozen"
TODO_KIND_UNAVAILABLE = "unavailable"
TODO_KIND_SIGNAL = "signal"

# The exclude surface (0.3.6). One list, four selectors, governing
# every detection family present and future. Exclusion suppresses
# judgment, not observation: excluded devices and entities keep
# their clocks, statistics, and vouching, so an undo is instant and
# free and the rhythm history carries no holes. An excluded entity
# still vouches for its device's freeze clock; only its own
# reporting is suppressed.
#
# The four kinds form a priority ladder, broadest first: integration,
# label, device, entity. A broader exclusion supersedes a narrower
# one and prunes it on save, so a pick can never be shadowed by an
# invisible parent (ruled 2026-07-16).
#
# Area was a fifth kind through 0.3.10 and is removed at 0.3.11.
# Area membership is set for dashboards, voice, and automations, so
# letting it also switch off monitoring means a room reorganization
# silently changes what is watched. A label carries one meaning and
# is set for one reason, which is what this surface needs.
CONF_EXCLUDED_DEVICES = "excluded_devices"
CONF_EXCLUDED_LABELS = "excluded_labels"
CONF_EXCLUDED_INTEGRATIONS = "excluded_integrations"

# Option keys no longer read by any code path. Cleared once at setup
# so a retired surface cannot linger in diagnostics and read as a
# live setting.
#
# excluded_areas is the area exclusion kind retired at 0.3.11. The
# rest are the 0.3.3 notification shapes that 0.3.4 replaced when the
# surface was rebuilt to mirror Sentinel Notify: notify_targets became
# the high and normal priority pair, quiet_start and quiet_end became
# quiet_hours_start and quiet_hours_end, reminder_time became
# daily_reminder_time, and high_priority_pierces_quiet became
# unconditional (high priority always pierces, so the knob had nothing
# left to decide). They survived in stored options for nine releases,
# reading as live settings in every diagnostics download, which is the
# exact rot ruling 49 was made to stop.
DEAD_OPTION_KEYS = (
    "excluded_areas",
    "notify_targets",
    "quiet_start",
    "quiet_end",
    "reminder_time",
    "high_priority_pierces_quiet",
)

SENTINEL_TYPE_PROBLEM_LIST = "problem_list"

# Battery-only exclusions (0.3.9). Scoped on top of the global
# exclude list: a device here is excluded from battery judgment
# only, keeping its freeze, unavailability, and signal watching for
# the later steps. Keyed at the device level so a re-election
# (percentage entity vanishing, binary elected instead) cannot dodge
# it. The integration list makes "everything mobile_app" one tick,
# covering phones present and future. No entity kind here for the
# same re-election reason.
CONF_BATTERY_EXCLUDED_DEVICES = "battery_excluded_devices"
CONF_BATTERY_EXCLUDED_INTEGRATIONS = "battery_excluded_integrations"
CONF_BATTERY_EXCLUDED_LABELS = "battery_excluded_labels"


# The documentation links the options screens append to their step
# descriptions. They live here rather than inside the translation
# files because hassfest rejects a literal URL in strings.json and
# directs integrations to pass links in as description placeholders,
# which the flow supplies at render time.
#
# One per wiki page, including the pages whose screens do not exist
# yet (ruled 2026-07-17). The set is a map of the wiki rather than a
# list of what happens to be wired today, so a screen built later
# finds its link already waiting.
#
# The link text stays the same on every screen while the target
# differs: a description reading "Full documentation: Device Sentinel
# wiki" says what the link is, and where it lands is the screen's own
# business.
WIKI_BASE_URL = "https://github.com/TheThinkingHome/device_sentinel/wiki"


def _wiki_link(page: str | None = None) -> str:
    """Return the markdown link a step description renders.

    Page names are the wiki's own titles with spaces as hyphens,
    which is how GitHub builds a wiki URL from a page title. A name
    that does not match a real page yields a link to a page-not-found
    screen rather than an error, so these are checked against the
    live wiki rather than trusted.
    """
    url = f"{WIKI_BASE_URL}/{page}" if page else WIKI_BASE_URL
    return f"[Device Sentinel wiki]({url})"


WIKI_LINK_HOME = _wiki_link()
WIKI_LINK_NOTIFICATIONS = _wiki_link("Notifications")
WIKI_LINK_EXCLUSIONS = _wiki_link("Global-Exclusions")
WIKI_LINK_BATTERY = _wiki_link("Low-Battery")
WIKI_LINK_SIGNAL = _wiki_link("Signal-Strength")
WIKI_LINK_FREEZE = _wiki_link("Freeze-Detection")
WIKI_LINK_RECOVERY = _wiki_link("Recovery")
WIKI_LINK_LEARNING = _wiki_link("How-Device-Sentinel-Learns")
WIKI_LINK_DEVICE_PAGE = _wiki_link("The-Device-Page")
WIKI_LINK_REPORTS = _wiki_link("The-Reports")
WIKI_LINK_FAQ = _wiki_link("FAQ-and-Troubleshooting")


# The device page's vocabulary. Home Assistant gives entities no
# helper text there, so a name and its state are the whole
# explanation; units exist so a card reads "125 devices" rather than
# a bare number (ruled 2026-07-17).
UNIT_DEVICES = "devices"
UNIT_BATTERIES = "batteries"
UNIT_SIGNALS = "signals"

# The status sensor's states. Learning shows only until the first
# device establishes a rhythm: partial learning is permanent, not a
# phase, so keying it to "any device unlearned" would read Learning
# forever.
STATUS_WATCHING = "watching"
STATUS_LEARNING = "learning"
STATUS_PROBLEM = "problem"

ATTR_SETUP_COUNT = "setup_count"

# Entities from retired surfaces. Deleting the code does not remove
# the registry entry, so a retired sensor would linger on the device
# page as an unavailable row. Removed once at setup, the same
# treatment DEAD_OPTION_KEYS gets. Append a sentinel type here when a
# sensor is retired, and drop it again once every install is past it.
DEAD_ENTITY_SENTINEL_TYPES = (SENTINEL_TYPE_CLOCK_SOURCE,)
