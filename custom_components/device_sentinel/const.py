# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: const.py, Version: 0.10.20 (2026-08-03)

"""Constants for the Device Sentinel integration."""

from __future__ import annotations

import logging

DOMAIN = "device_sentinel"

# Coordinator stacks Device Sentinel can recognise in a house. Which
# are present is derived from the registry rather than asked, and each
# later intervention detector attaches only where its stack is found,
# so a house runs only the detector paths it can actually use (rulings
# #139 and #143). ZHA, Z-Wave, and Matter are told by their
# integration domain; Z2M is told by the presence of its bridge
# device, never the mqtt domain it shares with every other MQTT thing,
# because counting mqtt entities would find Z2M in a house that has
# never run it.
STACK_Z2M = "z2m"
STACK_ZHA = "zha"
STACK_ZWAVE = "zwave_js"
STACK_MATTER = "matter"
# The portable tell for the Z2M bridge device: Z2M publishes it via
# MQTT discovery with a name ending "Zigbee2MQTT Bridge", or a model of
# "Bridge" under manufacturer "Zigbee2MQTT". The name is matched first
# because it survives whatever coordinator hardware sits behind it.
Z2M_BRIDGE_NAME_MARK = "Zigbee2MQTT Bridge"
Z2M_BRIDGE_MODEL = "Bridge"
Z2M_BRIDGE_MANUFACTURER = "Zigbee2MQTT"

# Bridge liveness states, shown by the per-stack bridge sensor. The
# sensor reads what a coordinator publishes about itself; each stack
# reports only the states it can. Z2M distinguishes all four from its
# retained bridge/info and bridge/state topics (ruling #145). ZHA and
# Z-Wave,
# added later, reach their state through different doors but land on
# this same vocabulary, since the shared detector only needs to know
# whether pairing is open.
BRIDGE_RUNNING = "running"  # online, pairing closed
BRIDGE_BINDING = "binding"  # online, pairing window open
BRIDGE_DOWN = "down"  # offline, or the retained state has gone stale
BRIDGE_UNKNOWN = "unknown"  # nothing heard from the bridge yet
BRIDGE_STATES = [BRIDGE_RUNNING, BRIDGE_BINDING, BRIDGE_DOWN, BRIDGE_UNKNOWN]

# Z2M bridge topics (relative to the configured base topic). bridge/info
# is retained and carries permit_join and the absolute permit_join_end;
# bridge/state carries online/offline. Both arrive on subscribe because
# they are retained, so a restart mid-window loses nothing. Reading
# them means depending on MQTT properly: the manifest names it and the
# reader waits for the client, because MQTT may not be up when Device
# Sentinel starts (ruling #146).
Z2M_BASE_TOPIC_DEFAULT = "zigbee2mqtt"
Z2M_TOPIC_INFO = "bridge/info"
Z2M_TOPIC_STATE = "bridge/state"

# Bridge sensor attribute keys.
ATTR_BRIDGE_STACK = "stack"
ATTR_BRIDGE_PERMIT_JOIN_END = "permit_join_end"
ATTR_BRIDGE_BASE_TOPIC = "base_topic"
ATTR_BRIDGE_LAST_HEARD = "last_heard"

# How long after a pairing window closes a recovery is still counted
# as pairing-caused: a device that comes back during or just after
# pairing came back because of the hand on it, so its silence is set
# aside rather than learned (ruling #145). A device paired near the
# end of a window may
# not report until just after it closes, and the observed bridge
# publish lag makes that a real case. Small and soak-settleable; the
# episode records when the window was open so this can be tuned from
# real data rather than guessed.
PAIRING_GRACE_SECONDS_DEFAULT = 120.0
# The learned-column value for a gap discarded because the device
# recovered during pairing. Distinct from the taint discard so the
# episode report tells a pairing intervention apart from real downtime.
LEARNED_PAIRING = "no (pairing)"

# The resurrection cap. A gap completing while the device stands
# convicted of a freeze is a silent-then-speaks recovery that neither
# of the other two intervention detectors can see: the device never
# went unavailable, so nothing tainted it (ruling #137), and
# permit-join was never open, so no pairing window covers it (ruling
# #145). It may therefore be a battery pulled and pushed back, which
# the integration has no way to observe (ruling #138). It is learned
# at most as rhythm
# plus an allowance, and the allowance is a power curve solved through
# these two anchors: fifty percent of rhythm at the fast reference,
# ten percent at the slow one. The fixed anchors are deliberate; they
# graduate to sliders only once the mechanics are proven in the field.
# Anchored to the rhythm, the device's own measured fact, rather than
# the window, because the window is rhythm plus our patience, and
# learning it back is a feedback loop that diverges on the grace
# curve. Scope is the frozen verdict alone: an unavailable stretch is
# attributed silence, the outage explains the gap, and the taint's
# total discard remains correct for it.
RATCHET_FAST_RHYTHM = 600.0
RATCHET_FAST_ALLOWANCE = 300.0
RATCHET_SLOW_RHYTHM = 43200.0
RATCHET_SLOW_ALLOWANCE = 4320.0

# A taint records why learning was suppressed, not merely that it
# was, so a row can name the bridge that felled a device instead of
# always reading unavailable (ruling #164). The device field holds one
# of these reasons and is falsy
# when clean, so every truthiness test that read the old boolean
# still answers "is this tainted". The reasons split into the state
# the device was actually in and the cause standing above it.
TAINT_UNAVAILABLE = "unavailable"
TAINT_UNKNOWN = "unknown"
TAINT_BRIDGE_DOWN = "bridge down"
# The widest cause of all, and the one the reason field reserved a
# place for before anything could detect it (ruling #164): the system
# stopped without being asked to, so the device was not silent,
# nobody was listening. Named
# for the stop rather than its cause, because a power cut, a crash
# and a pulled plug leave the files in exactly the same state and
# nothing on disk can tell them apart. It outranks a bridge outage,
# since a bridge that went quiet during one went quiet because of it.
TAINT_UNCLEAN_SHUTDOWN = "unclean shutdown"
TAINT_REASONS = (
    TAINT_UNAVAILABLE,
    TAINT_UNKNOWN,
    TAINT_BRIDGE_DOWN,
    TAINT_UNCLEAN_SHUTDOWN,
)

# The sensinel_type stem for a bridge sensor; the stack is appended so
# each stack's sensor has a stable unique id.
SENTINEL_TYPE_BRIDGE = "bridge"
# Display names per stack. The "Bridge:" prefix groups these with the
# other family sensors (Signal:, Battery:, Device:) so a house running
# several coordinators sees them in one block. Family prefixes sort
# the sensors regardless of how the panel orders them, which
# registration order alone could not guarantee (ruling #81), and the
# sensor is one per stack and off by default (ruling #149).
BRIDGE_SENSOR_NAMES = {STACK_Z2M: "Bridge: Zigbee2MQTT"}

# The package logger. __package__ resolves to
# custom_components.device_sentinel, which is the namespace Home
# Assistant's own debug-logging toggle and the logger: YAML block
# both target, so turning debug on the usual way reaches this.
LOGGER = logging.getLogger(__package__)

# Persistent storage. Lives in Home Assistant's .storage directory,
# never in custom_components (code, overwritten on every update).
STORAGE_KEY = f"{DOMAIN}.storage"
STORAGE_VERSION = 1

# The storage split, which keeps the fast-changing clock fields in a
# small companion file so a routine save does not rewrite everything
# learned (rulings #101 and #130). The clocks
# holds only the fields that change on an ordinary device report.
# Every routine write rewrites the whole storage file to update a
# handful of timestamps, and that file is heading for roughly 300 KB
# as the ninety-day series fill, so the fifteen-minute cadence costs
# about 28 MB a day. Split, the same cadence costs under one.
#
# The file is both written and read. A routine save
# writes it alone; the main file is written when something changes
# that a restart must not lose, and on every clean stop. The load
# merges the two, taking the clocks from here when this file's stamp
# proves it the newer of the pair.
STORAGE_CLOCKS_KEY = f"{DOMAIN}.clocks"
STORAGE_CLOCKS_VERSION = 1


# When each file was last written, stamped into both of them. Since
# routine saves stopped writing the main file, the hot file is
# normally the newer of the two and its clocks are the ones to
# keep. Normally, but not provably: the main file is written first and
# the hot file second, so a failure between the two leaves a fresh
# main file beside a stale hot one. Overlaying that backwards would
# push a device's last-activity into the past, which reads as silence
# and earns a freeze verdict the device never deserved. The stamp is
# what lets the merge refuse. It is additive on purpose, so neither
# store version moves and no migration is owed: a file written before
# the split simply has no stamp, and a load that cannot compare
# declines to merge, which is safe because before the split the main
# file carried everything on its own.
DATA_SAVED_AT = "saved_at"

# The clean-stop marker. A stop that was not asked for leaves no
# stamp, and without one the arithmetic that credits a device the
# silence nobody was listening to cannot be trusted, so every device
# not already in trouble starts its clock over (ruling #163). Home
# Assistant's stop event runs the
# flush, and that flush writes this flag true; the load reads it and
# clears it in the same breath, so the flag on disk means "the last
# thing that happened to this file was a deliberate stop". Its
# absence means the machine went down without one, which no stamp can
# tell us: a power cut leaves a saved_at that looks exactly like an
# ordinary interval write. An install upgrading from a version that
# never wrote the marker therefore reads its first load as unclean,
# which is one harmless reset on a fleet that has just restarted
# anyway, and is preferred to trusting a flag no earlier version set.
DATA_CLEAN_STOP = "clean_stop"




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

# Provisional tunables from the telemetry layer. Set from reasoning
# rather than from data, and left open to correction by the soak's own
# logs; see the project document, Remaining Tunables.
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
# hiccup, not an outage; it sets no taint, so the silence around it
# is still learned, while a long absence is real downtime and its gap
# is discarded (ruling #137). The threshold is per device, floor plus
# a share of the device's freeze window, so a fleet whose windows
# range from seconds to hours is fitted rather than held to one
# number. The floor is deliberate even though a global minimum was
# refused under the settle delay (ruling #127): a blip is noise rather
# than a share of anything the device earned, so a minimum below which
# an absence cannot count as real is not the fixed number that ruling
# turned down. An
# unarmed device with no learned window falls back to the floor
# alone. Starting values are soak-settled tunables, exposed on the
# Advanced screen.
TAINT_DEBOUNCE_FLOOR_SECONDS = 600
TAINT_DEBOUNCE_SHARE_PCT = 10
CONF_TAINT_FLOOR = "taint_floor_minutes"
CONF_TAINT_SHARE = "taint_share_pct"
DEFAULT_TAINT_FLOOR_MINUTES = 10
DEFAULT_TAINT_SHARE_PCT = 10
TAINT_FLOOR_MINUTES_MIN = 1
TAINT_FLOOR_MINUTES_MAX = 60
# Shares reuse the existing SHARE_PCT bounds (10 to 90, step 10).

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
# The dwell recorder. Signal is reported as the share of a day spent
# below the line rather than as threshold crossings, because a radio
# link is noisy and always recovering, so crossings would be spam
# (ruling #59). Two clocks per device: below_since is
# the open timer stamped when a reading crosses under the danger
# line, and below_today_seconds is the day's accumulated time under
# it. The rolling daily history keeps the percentage of each day
# spent below, beside the daily minimum that feeds the floor: the
# minimum says how bad the worst moment was, the dwell says how long
# the bad lasted, and neither can stand in for the other.
DEV_SIGNAL_BELOW_SINCE = "signal_below_since"
DEV_SIGNAL_BELOW_TODAY = "signal_below_today_seconds"
DEV_SIGNAL_DWELL_DAILY = "signal_dwell_daily_pct"

# The good-state statistics. Percentile thresholding is the weakest
# of the established families and the intended successor is Bayesian,
# judged against a learned anchor rather than a global constant
# (ruling #172). The successor to percentile
# thresholding needs each device's mean and standard deviation, so
# they are recorded ahead of the method that will use them: a running
# sum, sum of squares, and count, three floats and no samples kept,
# rolled at midnight into a per-day mean and deviation and then reset.
# The daily maximum rides along so a widening spread is visible where
# before only a falling floor was. Rail values feed none of them, for
# the same reason they never feed the floor. The accumulators move
# with every reading, which makes them clock-shaped, so they live in
# the hot file with the other clocks; the rolled series is history and
# lives in the main file.
DEV_SIGNAL_SUM = "signal_sum"
DEV_SIGNAL_SUM_SQ = "signal_sum_sq"
DEV_SIGNAL_COUNT = "signal_count"
DEV_SIGNAL_TODAY_MAX = "signal_today_max"
DEV_SIGNAL_DAILY_MEAN = "signal_daily_mean"
DEV_SIGNAL_DAILY_SD = "signal_daily_sd"
DEV_SIGNAL_DAILY_MAX = "signal_daily_max"
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
# DAILY_MAX_KEEP above is the judgment window, and it governs every
# verdict: the freeze rhythm and the signal floor are both computed
# from the most recent fourteen days however many are stored. It is
# not a user setting, because a threshold that moved with a storage
# preference would mean two systems detecting differently for no
# reason anyone chose. Retention is the person's; the judgment window
# is not (ruling #131).
#
# How much is kept is a separate question and is the person's.
# Long series exist because a fortnight is far too short to see what
# they measure: nothing measurably discharges in two weeks, a signal
# floor wants a season, and three months of gap history is what will
# eventually let the fourteen-day window itself be questioned rather
# than assumed. The floor of thirty days is what makes the setting
# safe to expose, since no choice can starve a fourteen-day window.
CONF_RETENTION_DAYS = "history_days"
DEFAULT_RETENTION_DAYS = 90
RETENTION_DAYS_MIN = 30
RETENTION_DAYS_MAX = 360
RETENTION_DAYS_STEP = 30
# What the diagnostics download emits per series, so an issue report
# stays a readable size at any retention.
DIAGNOSTIC_SERIES_CAP = 30

# Provisional arming floor: a device with at least this many daily
# maxima counts as rhythm-established for the learning-progress
# sensor. Arming criteria proper are settled during the soak.
LEARNING_MIN_DAYS = 7

# Storage save cadence: at most one write per render tick when dirty.
RENDER_TICK_SECONDS = 60

# The routine-save coalescing window, which came out of an earlier
# analysis of how often storage was being rewritten.
# Routine activity-clock churn no longer writes the full store every
# dirty tick; it schedules one delayed write this many seconds out,
# and repeated ticks reschedule the same pending write. Anything a
# reboot must not lose (verdicts, battery flips, problem-list
# changes, acknowledgments) still saves immediately. On a hard crash
# the worst loss is this window of clock progress, which the next
# device report corrects naturally; a clean shutdown flushes.
STORAGE_COALESCE_SECONDS = 900

# Step 6: freeze detection. The freeze window is the learned rhythm
# plus a grace margin, and the margin follows a power curve of the
# rhythm shaped by two user sliders (ruling 85). grace = a *
# rhythm^p, where a and p are derived from the two deltas by fitting
# the curve through delta-low grace at a fast reference rhythm and
# delta-high grace at a slow one, then clamped to [delta-low,
# delta-high]. The deltas therefore reshape the whole curve, not just
# its ends, so a device in the middle of the fleet responds too, and
# they double as the hard floor and ceiling on grace. At the defaults
# a one-hour device gets about a two-times window, the knee the curve
# is normed around. The rhythm underneath is untouched by the sliders
# (it is measured, not chosen); the sliders tune only the grace.
CONF_FREEZE_DELTA_LOW = "freeze_delta_low"
CONF_FREEZE_DELTA_HIGH = "freeze_delta_high"
# delta-low: the fast-end grace floor, in minutes. A device reporting
# every few seconds is not called dead for missing a couple of
# reports. Range 1 to 8, default 3.
DEFAULT_FREEZE_DELTA_LOW_MIN = 3
FREEZE_DELTA_LOW_MIN_MIN = 1
FREEZE_DELTA_LOW_MIN_MAX = 8
# delta-high: the slow-end grace ceiling, in hours. The slowest
# devices are still caught in a bounded time. Range 2 to 8, default
# 6. The tops match at 8 on purpose; each default sits toward the end
# the user rarely moves.
# Widened, because the old 2 to 8 range was asymmetric (ruling #102).
# It
# allowed halving the ceiling but barely raising it, and the ceiling
# anchors the whole grace curve, so the midrange devices (a learned
# rhythm of hours) were stuck near 1.6x patience. The floor of 2
# hours produced a curve too twitchy to be useful and is gone; the
# default moves to 8 so a fresh install starts with midrange cover.
DEFAULT_FREEZE_DELTA_HIGH_HR = 8
FREEZE_DELTA_HIGH_HR_MIN = 4
FREEZE_DELTA_HIGH_HR_MAX = 12
# The reference rhythms the two deltas are pinned at when the curve
# is fit: delta-low grace at 10 seconds, delta-high grace at 24
# hours. They bracket any real device and are soak-settleable.
FREEZE_REF_RHYTHM_FAST = 10.0
FREEZE_REF_RHYTHM_SLOW = 24.0 * 3600.0

# A device is judged for freeze only once it has a learned rhythm
# (the arming gate). There is no global learning mode and no timer:
# the gate is per device and permanent, so a device added years from
# now is simply unarmed until it has learned (ruling #27). Below the
# arming floor a device is watched for
# unavailable and unknown but never called frozen, because a device
# with no established rhythm has no window to miss.
FREEZE_ARMING_DAYS = LEARNING_MIN_DAYS

# The three device-down categories, worst first. When a down device
# shows a mix (some entities unavailable, some frozen), the most
# definite category wins: unavailable is the surest sign of a dead
# device, so it dominates frozen, which dominates unknown.
FREEZE_CATEGORY_UNAVAILABLE = "unavailable"
FREEZE_CATEGORY_FROZEN = "frozen"
FREEZE_CATEGORY_UNKNOWN = "unknown"
FREEZE_CATEGORY_PRIORITY = (
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNKNOWN,
)

# A device that has never reported at all is a different case from
# one that reported and stopped: it has no rhythm to miss, so the
# freeze window can never catch it, and it may have no live entity to
# read as unavailable either (a registry ghost with no entities, a
# device dead since before install). It is flagged on its own, ahead
# of the other checks, once it has been watched long enough that
# silence is not just a slow first report. Forty-eight hours since
# first-observed clears even a once-a-day device, which will have
# spoken twice by then, so total silence past it is a device that
# never started, not one still warming up.
FREEZE_CATEGORY_NOT_REPORTED = "not_reported"
FREEZE_NOT_REPORTED_SECONDS = 48.0 * 3600.0

# A device mid-transition flips its entities to unavailable in quick
# succession, usually within seconds. This debounce lets that settle
# before an unavailable or unknown verdict is published, so a device
# caught mid-flip is not reported in a half-state. Shares the value
# of the taint debounce.
FREEZE_UNAVAILABLE_DEBOUNCE = 180.0

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
# (code, wiped on update). Markdown rather than plain text so the
# maxima lists
# can carry emphasis (set-aside outliers struck through, the window
# basis bold).
REPORT_DIR = "device_sentinel"
# The subfolder the three maintainer files used to live in. They sat
# there so the folder a person opened held the daily briefs and
# nothing else; that reason retired when what a person reads moved
# under www, and the files came back up a level (ruling #179). The
# name is kept only so the old folder can be emptied of those three
# files once and removed if nothing else is in it.
REPORT_DIAGNOSTIC_DIR = "diagnostics"
# The dwell chart. Under www rather than the reports folder,
# because www is what Home Assistant serves at /local, and a dashboard
# Webpage card pointed at /local/device_sentinel/signal_dwell.html is
# the whole reason the file is HTML.
REPORT_WWW_DIR = "www/device_sentinel"
REPORT_SIGNAL_DWELL = "signal_dwell.html"
REPORT_SIGNAL_DWELL_PREFIX = "signal_dwell_"
# The HTML brief. What a person reads lives under www, where a
# browser and a dashboard card can render it, and what a developer
# reads stays under config (ruling #178). One rendering serves the
# dated record, the undated current file, and the emailed body, so
# the three cannot drift (ruling #179).
REPORT_BRIEF_HTML = "daily_brief.html"
REPORT_BRIEF_HTML_URL = "/local/device_sentinel/daily_brief.html"
REPORT_SIGNAL_DWELL_URL = "/local/device_sentinel/signal_dwell.html"
REPORT_TELEMETRY = "device_telemetry.md"
REPORT_CLASSIFICATION = "classification.md"
REPORT_EPISODES = "silence_episodes.md"
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
# The discharge recorder. At each midnight the current battery
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

# Step 6 freeze verdict, stored so it survives a reboot and so the
# sensor feed can compare and refresh only when it flips, not on
# every reading. The category is one of the
# three down states, or None when the device is alive. frozen_since
# is the UTC timestamp the verdict began, for the report and for
# "how long".
DEV_FROZEN_CATEGORY = "frozen_category"
DEV_FROZEN_SINCE = "frozen_since"

# The hot set, read from the code rather than assumed: these are the
# fields _record_activity and the signal path write on an ordinary
# report. Everything else (learned series, verdicts, todo,
# incidents) is cold and stays where it is.
CLOCK_FIELDS = (
    DEV_LAST_ACTIVITY,
    DEV_EVENT_COUNT,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    DEV_SIGNAL_VALUE,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_BELOW_SINCE,
    DEV_SIGNAL_BELOW_TODAY,
    DEV_SIGNAL_LAST_CHANGE,
    DEV_SIGNAL_SUM,
    DEV_SIGNAL_SUM_SQ,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_TODAY_MAX,
)

SENTINEL_TYPE_LOW_BATTERIES = "low_batteries"
SENTINEL_TYPE_SIGNAL_PROBLEMS = "signal_problems"
SENTINEL_TYPE_FROZEN_DEVICES = "frozen_devices"
SENTINEL_TYPE_TRACKED_SIGNALS = "tracked_signals"
SENTINEL_TYPE_TRACKED_BATTERIES = "tracked_batteries"
SENTINEL_TYPE_TRACKED_DEVICES = "tracked_devices"

# Signal preview, display-only when it was first added. The floor is
# the trimmed
# minimum of the rolling daily signal minima (mirror of the gap
# rule: drop the bottom TRIM_TOP_K as anomalies once
# TRIM_MIN_SAMPLES days exist). The candidate danger line is
# family-specific because one number cannot serve both unit
# families: LQI is positive (bigger is better, scale varies by
# stack), dBm RSSI is negative. Family is detected by sign. These
# formulas are previewed in device_telemetry.md and ruled from real
# data before any detection acts on them.
SIGNAL_ARMING_DAYS = 7

# The floor is the line. It replaced a 70 percent factor and a dB
# offset after the first clean dwell day read near-zero across the
# whole fleet. Dwell counts time spent at or
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
CONF_SIGNAL_ANOMALY_TRIM = "signal_sensitivity"
DEFAULT_SIGNAL_ANOMALY_TRIM = 0
SIGNAL_ANOMALY_TRIM_MIN = -2
SIGNAL_ANOMALY_TRIM_MAX = 2

# The margin above the floor, as a percentage of the floor itself.
#
# The floor used to be the line itself: only a reading at or under it
# counted as weak. The fleet showed why that is too narrow, and the
# line moved a settable margin above the floor (ruling #171). Across 84
# devices and 21 days, 82 percent of device-days recorded exactly zero
# dwell, because the floor is derived from the device's own recent
# minima and so the share of days that reach it is set by the
# arithmetic rather than by the health of the mesh. Moving the trim
# does not help: it only chooses a different historical day to call
# the floor, so the touch rate stays near (k+1)/14 whatever the
# setting. Replayed against the fleet, the trim spans 7 percent of
# days at its calmest to 38 percent at its most aggressive, and never
# gives the resolution wanted.
#
# A margin above the floor breaks that self-reference. A link hovering
# just above its own floor all day registers dwell where it used to
# register nothing, so a slow degradation shows as a rising number
# rather than staying silent until it crosses a line.
#
# The percentage is taken against the absolute value of the floor,
# which matters because the two signal types have opposite signs. LQI
# runs 0 to 255 upward; RSSI is negative dBm. Ten percent of an RSSI
# floor of -69 is -75.9, which is worse signal, so a naive percentage
# would invert the setting's meaning on every RSSI device. Adding
# pct * abs(floor) moves both types the same way: -69 becomes -62.1,
# and 150 becomes 165.
#
# The band therefore scales with the device: five percent of a
# 200-point floor is 10 points, of a 40-point floor is 2. Ruled
# deliberately, on the reasoning that a strong link can absorb larger
# swings than a weak one before either is worth reporting.
#
# Zero reproduces the older behaviour exactly, where the floor was
# the line, so the setting can be turned off and an existing install
# is unaffected until somebody moves it.
CONF_SIGNAL_MARGIN = "signal_margin"
DEFAULT_SIGNAL_MARGIN = 5
SIGNAL_MARGIN_MIN = 0
SIGNAL_MARGIN_MAX = 10

# Where yellow turns red on the dwell report. The dwell
# chart bands every nonzero device: 0 to 5 percent is green always,
# because a healthy link brushing its line is the design working; 5 to
# this setting is yellow; above it is red, and every red device is
# also pulled out as an anomaly and described in full. The bands are
# report coloring only. Signal is reported as dwell rather than as
# threshold crossings, and it does not push at all yet (ruling #59):
# nothing alerts from these bands, nothing joins
# the problem list, and moving the slider repaints the next report
# rather than changing any judgment.
CONF_SIGNAL_RED = "signal_red_threshold"
DEFAULT_SIGNAL_RED = 10
SIGNAL_RED_MIN = 5
SIGNAL_RED_MAX = 20
SIGNAL_GREEN_CEILING = 5.0

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

# Freeze-only excludes, the same three-tier ladder as battery and
# signal. A device on this list is still watched and clocked, so its
# rhythm keeps learning and re-including it is instant, but it is
# never given a freeze, unavailable, unknown, or not-reported verdict.
# For a device that is intermittent by nature (a car sensor that
# travels, a seasonal device) this silences the freeze report without
# hiding the device from everything.
CONF_FREEZE_EXCLUDED_DEVICES = "freeze_excluded_devices"
CONF_FREEZE_EXCLUDED_INTEGRATIONS = "freeze_excluded_integrations"
CONF_FREEZE_EXCLUDED_LABELS = "freeze_excluded_labels"

# The rails. A rail is a value that is flat and at
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
# -128) for this many consecutive days, which is how a rail is
# confirmed: it is a kind of signal problem rather than a sensor of
# its own (ruling #78). The
# live repeat counter that preceded this was removed with the frozen
# rework: it could not tell a stuck signal from a healthy steady link,
# because some devices report the same value for hours. Reading the
# daily-low series instead means a rail that comes and goes within a
# day never confirms, while one that holds across days does, with no
# per-reading state to keep.
RAIL_CONFIRM_DAYS = 3

# Notification backbone, built ahead of the engine that reads it.
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
# The brief's targets and mode. The two reminder keys keep their
# original names: they now drive the daily brief rather than
# Sentinel Notify's reminder, but renaming a stored key costs a
# migration for a cosmetic gain, so only the visible labels changed.
CONF_BRIEF_TARGETS = "brief_document_targets"
# Where a target name is parsed rather than merely stored. Both moved
# here from config_flow: the sending engine has to read a
# stored target and turn it back into a service call, and a module
# that composes messages should not import the configuration screens
# to learn how a target is spelled.
NOTIFY_DOMAIN = "notify"
PERSISTENT_TARGET = "persistent_notification"
PERSISTENT_CREATE = "create"
PERSISTENT_DISMISS = "dismiss"

# The notification engine. Three self-overwriting surfaces, each a
# fixed id so it always replaces its own last message rather than
# stacking, always showing the most recent picture rather than a pile
# of stale ones (ruling #147).
#
# The persistent card: one id, always the current home state, re-sent
# on every change, never gated by quiet hours because a card wakes no
# one. The per-family high-priority pushes: one id per family so each
# always shows its most recent event and summary; faults are audible
# on the device's own system sound, recoveries are sent silently.
NOTIFY_CARD_ID = "device_sentinel_state"
NOTIFY_FAMILY_IDS = {
    "battery": "device_sentinel_battery",
    "signal": "device_sentinel_signal",
    "freeze": "device_sentinel_freeze",
}
# The freeze family covers every liveness kind; a battery or signal
# kind maps to its own family, and anything else is a freeze-family
# event. This is the map from a problem kind to its notification family.
NOTIFY_KIND_FAMILY = {
    "battery": "battery",
    "signal": "signal",
    "rail": "signal",
    "frozen": "freeze",
    "unavailable": "freeze",
    "unknown": "freeze",
    "not_reported": "freeze",
}
NOTIFY_FAMILY_TITLES = {
    "battery": "Battery",
    "signal": "Signal",
    "freeze": "Device",
}
# The email's subject, and the brief's own title, kept as one string
# so the document and the message it arrives in cannot disagree.
BRIEF_TITLE = "Device Sentinel Daily Brief"
CONF_REMINDER_MODE = "daily_reminder_mode"
CONF_REMINDER_TIME = "daily_reminder_time"

DEFAULT_PERSISTENT_ENABLED = True
DEFAULT_QUIET_ENABLED = False
DEFAULT_QUIET_START = "22:00:00"
DEFAULT_QUIET_END = "08:00:00"
DEFAULT_REMINDER_MODE = "none"
DEFAULT_REMINDER_TIME = "08:00:00"

# The Advanced screen: cross-cutting settings a person may change and
# most never will, exposed rather than buried as constants, while
# anything that tunes one detector stays on that detector's own screen
# (ruling #117). Each is a
# share of something the device already earned, or a plain interval,
# so no value here can produce a nonsensical result.
CONF_SETTLE_SHARE = "settle_share_pct"
DEFAULT_SETTLE_SHARE_PCT = 30
CONF_EPISODE_SHARE = "episode_share_pct"
DEFAULT_EPISODE_SHARE_PCT = 50
SHARE_PCT_MIN = 10
SHARE_PCT_MAX = 90
SHARE_PCT_STEP = 10
CONF_COALESCE_MINUTES = "storage_write_minutes"
DEFAULT_COALESCE_MINUTES = 15
COALESCE_MINUTES_MIN = 1
COALESCE_MINUTES_MAX = 60

# Daily reminder modes, semantics carried from Sentinel Notify.
REMINDER_MODE_NONE = "none"
REMINDER_MODE_OVERNIGHT = "overnight"
REMINDER_MODE_DAILY = "daily"

# The problem list. One todo entity, not
# one per family: the type lives on each item, so a single list
# matches the novice-first thesis while losing nothing. Items are
# stored under their own storage key, separate from per-device
# telemetry, because they are problem records rather than device
# statistics. Every item is engine-owned and keyed by
# device_id: one item per device however many detections tag it, so a
# device is never duplicated across the frozen, battery, and signal
# lists. Hand-typed items are gone with the create feature; anything
# stored without a device_id is purged at setup.
DATA_TODO_ITEMS = "todo_items"

TODO_UID = "uid"
TODO_SUMMARY = "summary"
TODO_DESCRIPTION = "description"
TODO_STATUS = "status"
TODO_SORT_NAME = "sort_name"
TODO_DEVICE_ID = "device_id"
# The kind map: detection kind -> since (epoch seconds, or None when
# the detection carries no start time, as a rail does). One map per
# item is what makes one-item-per-device work: a frozen device whose
# battery then dies gains a second key, not a second item.
TODO_KINDS = "kinds"
# When the person checked the box, ISO. None while open. Drives the
# acknowledged block's order: oldest acknowledgment first, so the
# checked section reads as a history rather than reshuffling.
TODO_ACKED_AT = "acked_at"

# Item kinds, one per detection family. The freeze family's kinds are
# its verdict strings: the sync passes a verdict straight through as
# a kind, so these alias the categories rather than restating them
# rather than restating them. Aliasing rather than repeating means
# each string is
# defined once, and it puts the verdict-becomes-kind relationship at
# the definition instead of leaving it implied at every use site.
# Everything that turns a kind into words keys off these names, so a
# rename fails at import rather than quietly printing a raw kind
# into somebody's daily brief.
TODO_KIND_BATTERY = "battery"
TODO_KIND_FROZEN = FREEZE_CATEGORY_FROZEN
TODO_KIND_UNAVAILABLE = FREEZE_CATEGORY_UNAVAILABLE
TODO_KIND_UNKNOWN = FREEZE_CATEGORY_UNKNOWN
TODO_KIND_NOT_REPORTED = FREEZE_CATEGORY_NOT_REPORTED
TODO_KIND_SIGNAL = "signal"

# The additions journal. Every item added and every kind that joins
# an existing item is recorded here and announced on the dispatcher
# signal, so the notification engine is a pure listener over the
# problem list rather than a second judge: an addition to the list is
# the trigger, and newness is never re-derived from raw detections. Bounded so storage stays
# small; the journal is a feed, not an archive.
DATA_TODO_JOURNAL = "todo_journal"

# The silence-episode record, which is forensic rather than
# judgmental: it explains freeze verdicts and decides nothing
# (ruling #103). One entry per episode: a
# device whose silence passed its own learned basis, closed when it
# reported again or when something intervened. The file it feeds
# answers a question no other record can: whether a long silence
# ended because the device chose to speak (a rhythm the statistics
# should learn) or because a reboot or bridge reconnect made it
# speak (a wedge that patience would never have fixed).
# The share of a device's patience that must be spent before its
# silence opens an episode (ruling #105). A row opens at basis plus
# this fraction of the device's grace, which is the same as saying
# the silence has used this much of the multiplier between rhythm
# and freeze line. Basis alone was too sensitive at the fast end: a
# 36-second rhythm exceeds itself constantly, so trivial silences
# filled the file, while the same rule was properly selective for a
# device measured in hours. Expressed as a share of grace, the
# threshold scales with the patience each device has earned.
EPISODE_OPEN_SHARE = 0.5
# The incident log, the single memory every channel renders over:
# the push, the brief, the email and the card all read this and none
# derives its own truth (ruling #107). The journal before it recorded
# only openings, which was enough to trigger a notification and not
# enough to tell a story: a brief built on it could announce that a
# device broke and never that it came back, so a night of problems
# that opened and healed while the house slept would read as
# nothing at all. The log widens it to the whole life of a problem,
# and every renderer (phone, brief, email, voice) reads this and
# nothing else.

DATA_INCIDENTS = "incidents"
INCIDENT_KEEP_DAYS = 14
INC_DEVICE_ID = "device_id"
INC_NAME = "name"
INC_KIND = "kind"
INC_EVENT = "event"
INC_WHEN = "when"
INC_CAUSE = "cause"
INC_DURATION = "duration"
# Event types. ACTION is reserved for Step 9: a recovery attempt and
# its outcome belong on the same timeline as the problem it answers,
# so the brief can one day say what was tried as well as what broke.
INCIDENT_OPENED = "opened"
INCIDENT_RESOLVED = "resolved"
# Legacy. Retired in favour of INCIDENT_ACTION carrying
# ACTION_ACKNOWLEDGED. Nothing writes it any more; both renderers keep
# a branch for it so rows already in storage still read correctly.
# The log keeps 14 days and the last of those rows was written on
# 2026-07-28, so this constant and both branches can go after
# 2026-08-11.
INCIDENT_ACKNOWLEDGED = "acknowledged"
# One event for everything a person does to the list, with the cause
# saying which. A person checking a box is not the house producing a
# fault, and putting item events in the problem timeline made the
# brief say a device had been discovered at the moment someone
# deleted a row.
INCIDENT_ACTION = "action"
ACTION_ACKNOWLEDGED = "acknowledged"
ACTION_UNACKNOWLEDGED = "unacknowledged"
ACTION_DELETED = "deleted"
ACTION_READDED = "readded"

# The kinds whose recovery can name a cause. Only a silence has a
# lever to credit: a battery rising or a rail clearing has no
# reconnect or restart behind it, so those resolutions stay silent
# about why rather than guessing.
FREEZE_KINDS_FOR_CAUSE = frozenset(
    {"frozen", "unavailable", "unknown", "not_reported"}
)

# The daily brief (ruling #116). One file per day beside the other
# reports,
# written for a person rather than a maintainer: what is wrong now,
# what happened in the last 24 hours, plain language, no machinery.
# What a recovery says when no lever was observed. Not "on
# its own": the integration sees restarts and reconnects, and sees
# nothing at all when a person rebinds a device or pulls a battery,
# so the absence of a known lever is not evidence of self-recovery.
# A rebind by hand read as "on its own" in a live brief on
# 2026-07-23, which is exactly the claim the wedge-versus-quiet
# reading rests on.
# The trigger that closes a brief's window rather than opening one.
# Named once, because the writer and the scheduler have to agree and
# a typo between them would silently leave every brief in progress,
# which is the fault this constant exists to prevent recurring.
BRIEF_TRIGGER = "daily brief"
RECOVERY_CAUSE_UNOBSERVED = "no intervention recorded"
# The wording this replaced, still sitting in stored incidents from
# before the wording changed. Migrated at load rather than left to
# age out, because the composer tests for the current string and
# would otherwise write "revived by a on its own" for a fortnight.
LEGACY_CAUSE_UNOBSERVED = "on its own"

REPORT_BRIEF_PREFIX = "daily_brief_"
BRIEF_KEEP_DAYS = 14

# The system events log: what happened to the house rather than to a
# device. Every other record here is device-scoped, so when a bridge
# reconnect quiets fifty devices at once the record can only conjugate
# it through the fifty, and a reader months later sees fifty faults
# rather than one cause. These rows sit above the device rows and
# explain them; they never suppress them, because the suppressed
# evidence is exactly what a person goes looking for afterwards.
#
# Kept for the retention the person chose for device statistics
# rather than the fourteen days an incident keeps. An incident older
# than a fortnight has been fixed or is still standing, but how often
# this house loses power is a question about the house, and it is
# only answerable over seasons.
DATA_SYSTEM_EVENTS = "system_events"
SYS_WHEN = "when"
SYS_KIND = "kind"
# What the event applies to: the whole system, or one stack, or one
# integration. A bridge belongs to its stack; a restart belongs to
# everything.
SYS_SCOPE = "scope"
SYS_SCOPE_SYSTEM = "system"
# The specific thing, where a kind alone is not enough to be useful
# later: which setting moved, which bridge went quiet.
SYS_DETAIL = "detail"
# Present only where the event has a span. A bridge outage lasts; a
# restart is an instant, and carries instead the time nothing was
# listening, which is the one number that explains the gaps around it.
SYS_DURATION = "duration"

SYS_RESTART = "restart"
SYS_BRIDGE_DOWN = "bridge_down"
SYS_BRIDGE_UP = "bridge_up"
SYS_PAIRING_OPEN = "pairing_open"
SYS_PAIRING_CLOSED = "pairing_closed"
SYS_EPOCH_RESET = "epoch_reset"
SYS_OPTIONS_CHANGED = "options_changed"
# A restart with no clean-stop marker behind it (ruling #163).
# Distinct from SYS_RESTART because the consequences differ: an
# ordinary restart keeps every clock, this one resets all but the
# devices already in trouble. The reset never ships without this row,
# because a clock
# that jumps with no explanation above it is the silent oddity this
# project exists to prevent.
SYS_UNCLEAN_RESTART = "unclean_restart"

# The backup backbone (ruling #130). A copy of both storage files
# taken once,
# on the first boot of a release that is about to remove something it
# cannot put back. It ships inert: nothing in this release calls it,
# and the phase that prunes the clock fields is what turns it on,
# before it strips anything. Named for the state it preserves rather
# than the release that took it, and kept beside the older backups
# rather than replacing them.
BACKUP_SUFFIX_PREPHASE_C = "prephase-c"
BACKUP_TAKEN_KEY = "backup_taken"

DATA_EPISODES = "silence_episodes"
EPISODE_KEEP_DAYS = 14
EP_DEVICE_ID = "device_id"
EP_NAME = "name"
EP_SINCE = "since"
EP_BASIS = "basis"
EP_WINDOW = "window"
EP_ENDED = "ended"
EP_AT = "at"
EP_LAG = "lag"
EP_LEARNED = "learned"
# The unavailable duration that tainted this episode, in seconds, or
# None if it was not tainted by an unavailable stretch, which is the
# debounce that tells a mesh blip from real downtime (ruling #137).
# Recorded
# so the rig can measure the real spread the floor-plus-share defaults
# were guessed from, the recorder-then-flag pattern: record now, rule
# the defaults after the soak.
EP_TAINT_SECONDS = "taint_seconds"
EPISODE_ENDED_RESUMED = "resumed"
EPISODE_ENDED_REBOOT = "intervention (reboot)"
EPISODE_ENDED_RECONNECT = "intervention (bridge reconnect)"
# A storm inside startup grace is the restart itself: every device
# reports at once when Home Assistant returns, which looks exactly
# like a bridge reconnecting. Naming it correctly matters because
# the two are different rungs of the recovery ladder, and the brief
# quotes the cause verbatim.
EPISODE_ENDED_RESTART = "intervention (restart)"

# Where more than one reason fits a taint, the widest cause wins
# (ruling #164): a device felled by its bridge should say so rather
# than
# reporting the symptom it showed. The promotion is resolved when the
# episode closes rather than when the device reports, because the
# storm that names a reconnect releases after five seconds while the
# devices behind it trickle back over the following hour: on fourteen
# days of the development fleet, deciding at the report would have
# caught two of fifty-six. A reboot is absent deliberately, being an
# intervention but not a reason a gap goes unlearned.
EPISODE_ENDED_UNCLEAN = "intervention (unclean shutdown)"

# What a truncated pre-cut gap reads in the LEARNED cell
# (ruling #169). It
# is a lower bound rather than a measurement: the device was silent
# at least this long before the lights went out, and how much longer
# it would have stayed quiet is unknowable. Banked rather than
# discarded because the day's maximum keeps the larger of what it
# holds and what arrives, so a lower bound can only move the figure
# toward the truth and never past it. Labelled so a widened rhythm
# traceable to one is auditable from the row, in the same family as
# the taint reasons (ruling #164).
EPISODE_LEARNED_TRUNCATED = "yes (truncated)"

TAINT_PROMOTIONS = {
    EPISODE_ENDED_RECONNECT: TAINT_BRIDGE_DOWN,
    EPISODE_ENDED_UNCLEAN: TAINT_UNCLEAN_SHUTDOWN,
}
TODO_JOURNAL_KEEP = 100
SIGNAL_PROBLEM_ADDITION = f"{DOMAIN}_problem_addition"

# The exclude surface. One list, four selectors, governing
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
# invisible parent.
#
# Area was a fifth kind once and was removed (ruling #46).
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
# excluded_areas is the area exclusion kind, retired because area
# membership is set for dashboards and automations, so repurposing it
# to switch off monitoring would make reorganizing a room a silent
# failure (ruling #46). The rest are the first notification shapes,
# replaced when the
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

# Battery-only exclusions. Scoped on top of the global
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
# yet. The set is a map of the wiki rather than a
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
WIKI_LINK_NOTIFICATIONS = _wiki_link("Notifications-and-Daily-Brief")
WIKI_LINK_ADVANCED = _wiki_link("Advanced")
WIKI_LINK_EXCLUSIONS = _wiki_link("Global-Exclusions")
WIKI_LINK_BATTERY = _wiki_link("Low-Battery")
WIKI_LINK_SIGNAL = _wiki_link("Signal-Strength")
WIKI_LINK_FREEZE = _wiki_link("Freeze-Detection")
WIKI_LINK_RECOVERY = _wiki_link("Recovery")
WIKI_LINK_LEARNING = _wiki_link("How-Device-Sentinel-Learns")
WIKI_LINK_DEVICE_PAGE = _wiki_link("The-Device-Page")
WIKI_LINK_PROBLEM_LIST = _wiki_link("The-Problem-List")
WIKI_LINK_REPORTS = _wiki_link("The-Reports")
WIKI_LINK_FAQ = _wiki_link("FAQ-and-Troubleshooting")


# The device page's vocabulary. Home Assistant gives entities no
# helper text there, so a name and its state are the whole
# explanation; units exist so a card reads "125 devices" rather than
# a bare number.
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
