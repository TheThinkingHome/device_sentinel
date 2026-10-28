# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: const.py, Version: 0.27.10 (2026-10-27)

"""Constants for the Device Sentinel integration."""

from __future__ import annotations

import logging

DOMAIN = "device_sentinel"

# Coordinator stacks Device Sentinel can recognize in a house. Which are
# present is read from the registry rather than asked, and each
# intervention detector attaches only where its stack is found, so a
# house runs only the detector paths it can use (rule STACK-01). ZHA,
# Z-Wave and Matter are told by their integration domain; Z2M by its
# bridge device, never the mqtt domain it shares with every other MQTT
# thing, because counting mqtt entities would find Z2M in a house that
# has never run it.
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
# reports only the states it can. Z2M tells all four from its retained
# bridge/info and bridge/state topics (rule STACK-03). ZHA reads its
# state from its config entry and never reads binding, because ZHA keeps
# no pairing window of its own (rule FRZ-17).
BRIDGE_RUNNING = "running"  # online, pairing closed
BRIDGE_BINDING = "binding"  # online, pairing window open
BRIDGE_DOWN = "down"  # offline, or the retained state has gone stale
BRIDGE_UNKNOWN = "unknown"  # nothing heard from the bridge yet
BRIDGE_STATES = [BRIDGE_RUNNING, BRIDGE_BINDING, BRIDGE_DOWN, BRIDGE_UNKNOWN]

# Z2M bridge topics (relative to the configured base topic). bridge/info
# is retained and carries permit_join and the absolute permit_join_end;
# bridge/state carries online/offline. Both arrive on subscribe because
# they are retained, so a restart mid-window loses nothing. The manifest
# names MQTT and the reader waits for the client, because MQTT may not
# be up when Device Sentinel starts (rule STACK-03).
# The MQTT broker itself, which sits under every MQTT stack and belongs
# to none of them. Mosquitto publishes its uptime on a fixed interval,
# ten seconds by default, as a payload like "12355 seconds". Home
# Assistant exposes no broker entity at all, so this topic is the only
# source. The interval holds steady: median 9.997 s, maximum 10.350 s,
# standard deviation 0.082 s over 2,363 intervals (rule UP-02).
BROKER_TOPIC_UPTIME = "$SYS/broker/uptime"
BROKER_SCOPE = "mqtt"
# Two arrivals before anything is claimed. A broker with $SYS
# switched off, or one that words its payload differently, never
# arms and costs nothing.
BROKER_ARM_SAMPLES = 2
# The silence threshold is learned from the cadence rather than set:
# this many times the observed median, floored, so an install with a
# different sys_interval is right without being asked. Six against a
# measured spread of 82 milliseconds is far outside anything a broker
# does, and the floor covers a broker publishing far faster than
# Mosquitto's default.
BROKER_SILENCE_MULTIPLE = 6
BROKER_SILENCE_FLOOR_SECONDS = 30.0
# How far the computed broker start may wander before it counts as a
# restart. The start is an arrival minus a value published in whole
# seconds, so it drifts a little even when nothing happens. Across 2,458
# measured intervals the drift peaks at 2.95 seconds and its p99.9 is
# 0.34, while a real restart moves the start by 564 seconds or more.
# Thirty sits well clear of the noise. A broker restarting twice inside
# thirty seconds reports one restart (rule UP-02).
BROKER_START_TOLERANCE_SECONDS = 30.0
# The largest uptime worth believing, a hundred years in seconds. A
# payload beyond it is not a broker that has been up that long, and an
# infinity would put the computed start before the epoch.
BROKER_UPTIME_CEILING = 3_155_760_000.0
BROKER_RUNNING = "running"
BROKER_DOWN = "down"
BROKER_UNKNOWN = "unknown"
BROKER_STATES = [BROKER_RUNNING, BROKER_DOWN, BROKER_UNKNOWN]

# Wi-Fi's display name, defined here because the map below reads it and
# a module runs top to bottom. One copy of the string: the problem list
# resolves Wi-Fi through that map and the sensor reads it directly, and
# the two must not drift apart.
WIFI_DISPLAY_NAME = "WiFi"

# Integrations whose devices reach Home Assistant only through the MQTT
# broker without being MQTT's own devices. The MQTT integration's page
# lists them beneath its own, because the broker failing takes them down
# too. Tasmota is the one Home Assistant ships that works no other way.
BROKER_RIDER_DOMAINS = ("tasmota",)

# What a stack is called when a person reads it (rule UP-11). The
# internal key is the domain the stacks module uses; a row saying
# "z2m: upstream" is accurate and tells nobody anything.
STACK_DISPLAY_NAMES = {
    "z2m": "Zigbee2MQTT",
    "zha": "ZHA",
    "zwave_js": "Z-Wave",
    "matter": "Matter",
    # Not a stack either, but a nameless UniFi client is named after its
    # integration (rule DEV-01), and "unifi" is not a name a person
    # recognizes on a report.
    "unifi": "UniFi Network",
    # Not a stack, but the problem list resolves every upstream's
    # display name through this map, and the Wi-Fi row must read the
    # way the sensor does.
    "wifi": WIFI_DISPLAY_NAME,
}

# The name the broker carries when it is the upstream a device is
# reported under. Not a stack: no bridge owns it, and it outranks every
# bridge, because a broker that is down takes them all with it (rule
# UP-01).
BROKER_LABEL = "MQTT broker"

# How long an upstream outage settles before it is reported (rule
# UP-09). Devices do not fall in one tick: Home Assistant marks each
# entity unavailable as it notices, so a count taken at once is wrong and
# a message per tick is a burst. The same window is used on the way back,
# so a device that did not return is named once the others have.
UPSTREAM_SETTLE_SECONDS = 60.0
BROKER_SENSOR_NAME = "Broker: MQTT"

ATTR_BROKER_STARTED = "broker_started"
ATTR_BROKER_UPTIME = "uptime_seconds"
ATTR_BROKER_LAST_HEARD = "last_heard"
ATTR_BROKER_CADENCE = "cadence_seconds"
ATTR_BROKER_THRESHOLD = "threshold_seconds"
ATTR_BROKER_TOPIC = "topic"

Z2M_BASE_TOPIC_DEFAULT = "zigbee2mqtt"
Z2M_TOPIC_INFO = "bridge/info"
Z2M_TOPIC_STATE = "bridge/state"
# bridge/devices is the retained roll of what exists. It carries the
# IEEE address Home Assistant knows a device by beside the friendly name
# the availability topics are keyed on, the only join between the two,
# and it rejects an availability topic naming a group or a device that
# is gone. The availability subscription is a one-level wildcard, so a
# friendly name containing a slash publishes deeper and is not seen; Z2M
# permits it but it is rare (rule STACK-03).
Z2M_TOPIC_DEVICES = "bridge/devices"
# The Z2M discovery identifier reads ('mqtt', 'zigbee2mqtt_0x282c...'),
# so the IEEE address follows this mark. It is the base topic by
# default and does not follow a renamed one, which is why it is a
# constant here rather than derived from the configured base.
Z2M_IDENTIFIER_MARK = "zigbee2mqtt_"
Z2M_TOPIC_AVAILABILITY_LEAF = "availability"
Z2M_TOPIC_AVAILABILITY = f"+/{Z2M_TOPIC_AVAILABILITY_LEAF}"

# Bridge sensor attribute keys.
ATTR_BRIDGE_STACK = "stack"
ATTR_BRIDGE_PERMIT_JOIN_END = "permit_join_end"
ATTR_BRIDGE_BASE_TOPIC = "base_topic"
ATTR_BRIDGE_LAST_HEARD = "last_heard"

# How long after a pairing window closes a recovery still counts as
# caused by pairing: a device that comes back during or just after
# pairing came back because of the hand on it, so its silence is set
# aside rather than learned (rule FRZ-16). A device paired near the end
# of a window may not report until just after it closes, and the bridge's
# publish lag makes that a real case. The episode records when the window
# was open, so this can be tuned from real data.
PAIRING_GRACE_SECONDS_DEFAULT = 120.0
# The learned-column value for a gap discarded because the device
# recovered during pairing. Distinct from the taint discard so the
# episode report tells a pairing intervention apart from real downtime.
LEARNED_PAIRING = "no (pairing)"
# The learned-column value for a gap discarded because the device
# recovered inside a declared maintenance window (rule FRZ-18). Its own
# word for the same reason pairing has one: the episode report says which
# intervention explained the discard.
LEARNED_MAINTENANCE = "no (maintenance)"
# A gap that spans a disabling is administrative, not the device's own
# rhythm. Same class as pairing and maintenance: a hand caused the
# silence, so the gap is refused and retracted (rule FRZ-15).
LEARNED_DISABLED = "no (disabled)"
# The same class again, for a device ZHA says was re-paired,
# reconfigured or removed while it was silent (rule FRZ-17). Its own
# word rather than pairing's, because the episode report should say what
# happened: nobody opened a pairing window, somebody handled this device.
LEARNED_HANDLED = "no (handled)"
# The learned-column value for a gap learned with Device Sentinel's own
# stops taken out of it (rule FRZ-12). Marked, so a rhythm built on it
# can be checked from the row: the figure is the silence that was
# watched, never the time nobody was listening.
LEARNED_DOWNTIME_OUT = "yes (downtime out)"

# The maintenance window: a button-declared span in which any recovery is
# put down to a person's hands rather than learned (rule FRZ-18). Short,
# because a person fixing hardware is at the device for minutes, and a
# long default would swallow real self-recoveries all afternoon.
CONF_MAINTENANCE_MINUTES = "maintenance_minutes"
DEFAULT_MAINTENANCE_MINUTES = 10
MAINTENANCE_MINUTES_MIN = 5
MAINTENANCE_MINUTES_MAX = 60
MAINTENANCE_MINUTES_STEP = 5

# A report that follows a command to the device clears a freeze verdict
# without teaching anything: the device answered, so it is reachable, but
# a toggle from a device card or an automation says nothing about the
# device's own rhythm (rule FRZ-19). The window is how long after the
# command a report still counts as its reply. On Zigbee2MQTT and ESPHome
# a reply arrives within a second or two; sixty seconds covers a slow
# mesh and costs, at worst, one discarded gap on a self-report that
# happened to follow a command, the same safe direction pairing takes.
COMMANDED_RECOVERY_SECONDS = 60.0
LEARNED_COMMANDED = "no (commanded)"

# A device whose wait in use is longer than this is slow to judge for
# freeze: it reports on a person's habits rather than a rhythm, so a
# freeze verdict comes late and is often noise (rule REC-06). Freeze days
# per device stay flat up to 48 hours of wait and jump above it; 36 hours
# sits inside the flat part, so the card offers a mute early and never
# late.
SLOW_REPORTER_SECONDS = 36.0 * 3600.0
# A hub reads down once its connection has been gone for two readings of
# the minute check, because the library's own reconnect after a dropped
# connection takes a few seconds and is not an outage (rule STACK-09).
HUB_DOWN_CONFIRM_SECONDS = 55.0

# A taint records why learning was suppressed, not merely that it was,
# so a row can name the bridge that felled a device instead of always
# reading unavailable (rule FRZ-14). The device field holds one of these
# reasons and is falsy when clean, so every truthiness test still answers
# "is this tainted". The reasons split into the state the device was in
# and the cause standing above it.
TAINT_UNAVAILABLE = "unavailable"
TAINT_UNKNOWN = "unknown"
TAINT_BRIDGE_DOWN = "bridge down"
# A completed gap that spanned an outage of the device's broker,
# integration or network (rule FRZ-12). Only ever a learning label; never
# stored as a device's taint.
TAINT_UPSTREAM_DOWN = "upstream down"
# A completed gap measured across a jump of the system clock that the
# minute check had not yet seen (rule FRZ-21). Only ever a learning label.
TAINT_CLOCK_JUMP = "clock jump"
# The widest cause of all: the system stopped without being asked to, so
# the device was not silent, nobody was listening (rule FRZ-20). Named
# for the stop rather than its cause, because a power cut, a crash and a
# pulled plug leave the files in the same state and nothing on disk can
# tell them apart. It outranks a bridge outage, since a bridge that went
# quiet during one went quiet because of it (rule FRZ-14).
TAINT_UNCLEAN_SHUTDOWN = "unclean shutdown"

# Every value the reason field may hold besides False, named here so the
# shape check accepts exactly these and nothing else, and a new reason
# has one place to join. Constants rather than literals, because a value
# changed in one place and spelled by hand in another parts silently.
TAINT_REASONS = (
    TAINT_UNAVAILABLE,
    TAINT_UNKNOWN,
    TAINT_BRIDGE_DOWN,
    TAINT_UNCLEAN_SHUTDOWN,
)

# The sentinel_type stem for a bridge sensor; the stack is appended so
# each stack's sensor has a stable unique id.
SENTINEL_TYPE_BRIDGE = "bridge"
SENTINEL_TYPE_BROKER = "broker"
# Display names per stack. The "Bridge:" prefix groups these with the
# other family sensors (Signal:, Battery:, Device:) so a house running
# several coordinators sees them in one block. Family prefixes sort the
# sensors however the panel orders them, which registration order alone
# could not do (rule CFG-06). One sensor per stack, on by default (rule
# CFG-08). Each bridge sensor's name lives in strings.json under this
# key, as every Device Sentinel entity's does (Home Assistant's
# entity-translations practice).
BRIDGE_SENSOR_NAMES = {
    STACK_Z2M: "Bridge: Zigbee2MQTT",
    STACK_ZHA: "Bridge: ZHA",
}
BRIDGE_TRANSLATION_KEYS = {
    STACK_Z2M: "bridge_zigbee2mqtt",
    STACK_ZHA: "bridge_zha",
}

# How long ZHA's config entry must stay unloaded before the reader calls
# the coordinator down (rule UP-03). Measured rather than chosen: a
# routine ZHA reload takes every entity unavailable for nine seconds and
# returns, while a coordinator with no power is still gone at sixty and
# takes four to six minutes to come back. Sixty seconds sits clear of
# the one and well inside the other.
ZHA_DOWN_DWELL_SECONDS = 60.0

# An integration is called down when its config entry has been in any
# state other than loaded for this long (rule UP-03). The same sixty
# seconds ZHA uses, for the same reason: a reload drops an entry for
# about nine seconds and an upgrade drops every entry it touches, so the
# first sighting of an unloaded entry is evidence of nothing. Home
# Assistant passes through setup_in_progress on the way back up, which
# clears well inside the dwell.
#
# Most integrations hold their entry loaded while their devices go
# unreachable, so what this catches there is an integration that failed
# to start. Z-Wave and Matter reload their entry on a dropped connection
# and are the case it is built for.
INTEGRATION_DOWN_DWELL_SECONDS = 60.0

# The dispatcher signal ZHA's split library emits gateway messages on,
# and the three message types that mean a device arrived. Named here
# rather than imported from ZHA, because a plain string cannot break on
# an upgrade the way an import can, and a signal renamed upstream simply
# stops delivering, which the observer's silence says as clearly as an
# error would (rule STACK-08).
ZHA_GATEWAY_SIGNAL = "zha_gateway_message"

ZHA_JOIN_MESSAGES = frozenset(
    {
        "device_joined",
        "raw_device_initialized",
        "device_fully_initialized",
        # A removal is a person acting too, and a sleeping battery device never
        # hears the leave request, so it rejoins by itself at the next start.
        # Both halves of that are handling, not recovery (rule FRZ-17).
        "device_removed",
    }
)

# How long a device stays tagged as handled after the last message
# naming it (rule FRZ-17). Measured rather than chosen: a reconfigure ran
# 15 seconds from first message to last, a re-pair 34 seconds, and the
# message always came 2 to 8 seconds before the recovery. Sixty covers
# both with room, and errs the safe way: a recovery wrongly called
# handled loses one measurement, while one wrongly called natural
# teaches a rhythm that is not real.
ZHA_HANDLED_TAIL_SECONDS = 60.0
# What a person's handling of a ZHA device looks like (rule FRZ-17). A
# full init alone is the device setting itself up again, as ZHA devices
# do after a restart. A join alone is no better: a device that changes
# its own network address sends a join and two full inits, exactly as a
# re-pair does, with nobody near it. So a join counts only while pairing
# is open, and the start of a reconfigure, a raw init, counts by itself,
# since zigpy sends one for a known device only when it is interviewed
# again. The full inits that follow count until ZHA says the device is
# initialized, or the window ends, because a slow battery device can
# take minutes to configure.
ZHA_FULL_INIT = "device_fully_initialized"
ZHA_JOINED = "device_joined"
ZHA_RAW_INIT = "raw_device_initialized"
# A handling filed as a re-pair: a full init after a join (rule FRZ-05).
ZHA_REPAIR = "re-pair"
ZHA_INITIALIZED = "INITIALIZED"
ZHA_HANDLING_WINDOW_SECONDS = 900.0
# Handlings begun and not yet answered are kept for at most this many
# addresses, the oldest dropped first.
ZHA_BEGUN_KEPT = 512
# Pairing is open. ZHA keeps no such state, so it is read from what
# opening it leaves: the zha.permit action, for as long as it asks, and
# the Add Device page, which relays ZHA's log as log_output messages
# while it is open. The longest a pairing can stay open is 254 seconds.
ZHA_LOG_OUTPUT = "log_output"
ZHA_PERMIT_SERVICE = "permit"
ZHA_PERMIT_DEFAULT_SECONDS = 60.0
ZHA_PERMIT_LONGEST_SECONDS = 254.0

# The package logger. __package__ resolves to
# custom_components.device_sentinel, which is the namespace Home
# Assistant's own debug-logging toggle and the logger: YAML block
# both target, so turning debug on the usual way reaches this.
LOGGER = logging.getLogger(__package__)

# Persistent storage. Lives in Home Assistant's .storage directory,
# never in custom_components (code, overwritten on every update).
STORAGE_KEY = f"{DOMAIN}.storage"
STORAGE_VERSION = 1

# The storage split keeps the fast-changing clock fields in a small
# companion file, so a routine save does not rewrite everything learned
# (rule STOR-01). The clocks file holds only the fields that change on an
# ordinary device report. Rewriting the whole storage file, heading for
# about 300 KB as the ninety-day series fill, to update a handful of
# timestamps every fifteen minutes costs about 28 MB a day. Split, the
# same cadence costs under one.
#
# The file is both written and read. A routine save writes it alone; the
# main file is written when something changes that a restart must not
# lose, and on every clean stop. The load merges the two, taking the
# clocks from here when this file's stamp proves it the newer of the
# pair.
STORAGE_CLOCKS_KEY = f"{DOMAIN}.clocks"
# The history file: the part of each daily series older than its newest
# HISTORY_KEEP_ENTRIES entries, and the leading system events and signal
# stress rows older than the line. Written only when that part changes,
# in four steps (rule STOR-03).
STORAGE_HISTORY_KEY = f"{DOMAIN}.history"
STORAGE_HISTORY_VERSION = 1
HISTORY_KEEP_ENTRIES = 30
# A trim backup copy is kept this many days, except the newest copy,
# kept for the full History retention (rule STOR-13).
TRIM_BACKUP_KEEP_DAYS = 30
# On the main file: the generation of the history file it pairs with,
# None when nothing is held there, and the line rows cross at, set at
# each fold to local midnight less HISTORY_KEEP_ENTRIES days.
DATA_HISTORY_GENERATION = "history_generation"
DATA_HISTORY_LINE = "history_line"
STORAGE_CLOCKS_VERSION = 1


# When each file was last written, stamped into both. The clocks file
# is normally the newer. One older than the main file means a write
# pair was torn; the load uses it anyway and logs it, because a slightly
# stale clock heals at the device's next report while dropping it
# restarts every clock. A pair where either file has no stamp is not
# merged (rule STOR-02).
DATA_SAVED_AT = "saved_at"

# The clean-stop marker. A stop that was not asked for leaves no stamp,
# and without one the credit for silence nobody was listening to cannot
# be trusted, so every device not already in trouble starts its clock
# over (rule FRZ-20). Home Assistant's stop event runs the flush, which
# writes this flag true; the load reads it and clears it at once, so the
# flag on disk means "the last thing that happened to this file was a
# deliberate stop". Its absence means the machine went down without one,
# which no stamp can tell: a power cut leaves a saved_at that looks like
# an ordinary interval write. A file from a version that never wrote the
# marker reads its first load as unclean, one harmless reset on a house
# that has just restarted anyway, rather than trusting a flag nothing
# set.
DATA_CLEAN_STOP = "clean_stop"


# Storage field names.
DATA_FIRST_INSTALLED = "first_installed"
DATA_SETUP_COUNT = "setup_count"
DATA_DEVICES = "devices"

# Per-device storage field names.
DEV_LAST_ACTIVITY = "last_activity"
DEV_DAILY_MAX = "daily_max"
# Days the Log-Normal Percentile may read since the last reset (a
# firmware update, a battery replacement, a re-pair), or None when no
# reset limits it (rule FRZ-05). A record with no reset carries None, so
# its whole history counts. A reset sets 0, each fold adds one, and at
# CLIP_MAX_DAYS it returns to None, since the rule never reads further
# back than that.
DEV_LOGNORMAL_DAYS = "lognormal_days"
# The two freeze rules, by the names the device page and the reports
# give them, each preceded by the days it read: "14-Day Trimmed
# Maximum", "37-Day Log-Normal Percentile" (rule FRZ-04).
RULE_TRIMMED = "Trimmed Maximum"
RULE_LOGNORMAL = "Log-Normal Percentile"
# Days in a row the Log-Normal Percentile may set aside as longer than a
# device's usual before they count as a new habit rather than bad days
# (rule FRZ-05). On the third, its count starts again, as after a
# firmware update, and the Trimmed Maximum, which follows the slower
# habit within two days, carries the device until 28 new days. Two bad
# days are still set aside. Without this, a device that slowed for good
# would be listed frozen again and again for about two weeks.
SLOWDOWN_DAYS = 3
DEV_TODAY_MAX = "today_max"
DEV_FIRST_OBSERVED = "first_observed"
DEV_EVENT_COUNT = "event_count"
DEV_SET_ASIDE_SINCE = "set_aside_since"
# When the device as a whole went down, and the state it read (rule
# UNAV-04): every one of its own entities unavailable or unknown, or an
# ESPHome device's connection dropped. One moment per device, never per
# entity, so a rename or a removal cannot lose it. Saved with the record
# so a restart cannot lose it either: the gap spanning an outage longer
# than the taint debounce is not learned, whatever restarts happen
# inside it (rule FRZ-14).
DEV_DOWN_SINCE = "down_since"
# When a device set aside, excluded or removed was watched again, until
# it reports. Its silence is judged from here, not from its last report,
# because the time nobody watched it is not its silence (rule WATCH-08).
DEV_WATCHED_FROM = "watched_from"
# A device gone from Home Assistant keeps its record for
# REMOVED_HOLD_DAYS (rule WATCH-07). Home Assistant gives a re-added
# device back its old id, and the record, answers and mutes come back
# with it. The moment it left and the name it had then are kept, so the
# hold can be listed and purged by name.
DEV_REMOVED_SINCE = "removed_since"
DEV_REMOVED_NAME = "removed_name"
REMOVED_HOLD_DAYS = 30
DEV_TAINTED = "tainted"

# Startup grace: stamps update clocks but complete no gaps for
# learning while the restored-state echo wave and the boot republish
# pass (rule WATCH-10).
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
# cadence, so its storms are counted and never announced (rule UP-17).
# A router poller can otherwise raise hundreds of storms a night.
STORM_EXEMPT_PER_HOUR = 10
STORM_HISTORY_SECONDS = 3600

# How long a resolved problem stays reopenable, in seconds. A device
# whose reading crosses a threshold back and forth writes a pair of
# incident rows every crossing, and one sensor flapping this way can
# write thousands of rows in a few days (rule LIST-06).
#
# Sixty seconds by measurement rather than by taste. Replayed over
# stored incidents, sixty leaves a healthy house's rows untouched and
# cuts a flapping house's by more than four fifths. Past two minutes it
# begins collapsing real recoveries on a healthy house, the failure this
# must never have. A constant, not a setting, because sixty never needed
# moving.
INCIDENT_SETTLE_SECONDS = 60

# An outage of the device sets its gap aside at ten minutes plus ten
# percent of its freeze window. Fixed, not settings (rule FRZ-14).
TAINT_FLOOR_MINUTES = 10
TAINT_SHARE_PCT = 10


# Statistics epoch: when storage carries an older epoch, the learned
# rhythm and what was concluded from it (the fields EPOCH_KEPT does
# not name) are wiped once, so every rhythm is learned under the final
# rule set. Everything else survives.
STATS_EPOCH = "0.2.3"
DATA_STATS_EPOCH = "stats_epoch"

# The version that last ran, stored so a start can tell an upgrade from
# an ordinary restart. It lives beside the epoch marker at the top of the
# file rather than inside a device record, so it is outside everything
# the shape check reads and costs the record schema nothing. Absent on a
# file written by an older version, which reads as an upgrade, which it
# is.
DATA_LAST_VERSION = "last_version"
# The local day whose brief was last closed and sent, as an ISO date.
# Daylight saving is Device Sentinel's to handle (rule BRIEF-11): Home
# Assistant's time tracker fires twice for a time inside the hour the
# change repeats and never for one inside the hour it skips. The day
# closed is remembered here, so a second firing on the same day sends
# nothing, and the minute check closes a day whose brief time the clock
# skipped. Stored, so a restart cannot make either guard forget.
DATA_BRIEF_CLOSED_DAY = "brief_closed_day"

# Each area's recording depth is read from its own series, so nothing
# here names a version and nothing has to be bumped when a release
# changes what is recorded: a new series is empty, which makes it the
# shortest, which resets the area on its own. DATA_SERIES_STAMPS
# survives only as the key an older version wrote, pruned from storage
# on the first load.
DATA_SERIES_STAMPS = "series_stamps"

# One-shot marker for the signal day repair. Carries the version that
# ran it, so the repair happens once and a later restart cannot drop
# another day (rule STOR-19).
DATA_SIGNAL_DAY_REPAIR = "signal_day_repair"
SIGNAL_DAY_REPAIR_MARK = "0.12.21"

# The mean and deviation changed from counting readings to weighing
# minutes (rule SIG-05), so their recorded days are not comparable across
# the change. The series are cleared once, under this marker, rather
# than left mixed, because no later analysis could separate the two
# halves.
DATA_SIGNAL_WEIGHTING = "signal_weighting"
# The clearing also takes the day in progress, which mixed both counts,
# so the marker carries its second value (rule STOR-19).
SIGNAL_WEIGHTING_MARK = "minutes-2"
# What a device's page and the Devices tab say when it has no freeze
# verdict: it is reporting, it has never reported, or nobody is watching
# it.
STATUS_REPORTING = "reporting"
STATUS_NEVER_REPORTED = "never_reported"
STATUS_SET_ASIDE = "set_aside"

# Why a device is set aside: recorded rather than inferred, because the
# classification file has to say which (rule WATCH-03).
SET_ASIDE_SERVICE = "service"
SET_ASIDE_DISABLED = "disabled"
# "No entities of its own": a device whose only entities another
# integration added, such as Battery Notes, has nothing that is the
# device speaking (rule WATCH-02).
SET_ASIDE_NO_ENTITIES = "no entities"
SET_ASIDE_EXCLUDED = "excluded"
# A device whose only entities switched on are firmware notices, command
# buttons or a hub's word on it, whatever it has switched off (rule
# WATCH-04). The stored value is the words shown after "Set aside:".
SET_ASIDE_NOTICES_ONLY = "nothing switched on that can report"
# A coordinator already watched properly by something else, reaching the
# registry a second time as an ordinary device (rule WATCH-05). Today
# that is the Zigbee2MQTT bridge and nothing else; each stack answers
# for its own.
SET_ASIDE_DUPLICATE_COORDINATOR = "duplicate coordinator"
# Another registry device for the same hardware: Home Assistant lists a
# device two integrations see once for each. The hardware is watched
# once, through the device that reaches it most directly, and the others
# are its clones (hardware_copies.py, rule WATCH-06). Called "clone" on
# screen.
SET_ASIDE_COPY = "clone"
# An integration's standing on the Integrations tab. Service: its
# devices report themselves as services. No hardware: it owns no device
# at all and only adds entities to devices other integrations own, as
# Battery Notes does. The same words under the tab and in
# classification.md.
STANDING_NO_HARDWARE = "no_hardware"
# A Home Assistant helper a person linked to a device: the same rule as
# no hardware, told apart because Home Assistant marks its helper
# integrations as helpers, and a Derivative linked to one sensor is not
# what anyone pictures reading "as Battery Notes does".
STANDING_HELPER = "helper"
# An integration whose devices are all set aside for having nothing but
# firmware notices or command buttons switched on (rule WATCH-04).
STANDING_NOTICES_ONLY = "notices_only"
STANDING_MEANINGS: tuple[tuple[str, str], ...] = (
    ("Watched", "It owns devices Device Sentinel watches."),
    ("Excluded", "It is on your exclusion list, in Exclusions and Muting."),
    ("Muted", "It is muted, in Exclusions and Muting: its devices are watched but never reported."),
    ("Service only", "Its devices report themselves as services, so there is nothing to watch."),
    (
        "No hardware",
        "An add-on with no hardware of its own. It puts its entities on "
        "devices other integrations own, as Battery Notes does, and they "
        "never count as the device reporting.",
    ),
    (
        "Helper",
        "A Home Assistant helper you linked to a device. Its entities "
        "never count as the device reporting.",
    ),
    (
        "Nothing switched on to read",
        "Its devices have nothing switched on that can report.",
    ),
)
# What each reason means, in the order the classification ladder tries
# them: a person's exclusion first, since a decision outranks a fact
# about the device, then the facts, with no entities last. The key under
# the Classification tab and in classification.md, so the two say the
# same thing and a person can see which reasons exist (rule WATCH-03).
SET_ASIDE_MEANINGS: tuple[tuple[str, str], ...] = (
    (
        SET_ASIDE_EXCLUDED,
        "You excluded it, or its integration, in Exclusions and Muting "
        "or on its device page.",
    ),
    (
        SET_ASIDE_SERVICE,
        "Home Assistant marks it as a service rather than hardware, "
        "such as an add-on or a HACS card.",
    ),
    (
        SET_ASIDE_DISABLED,
        "It is disabled, by you, by its integration or with its config "
        "entry, so it cannot report.",
    ),
    (
        SET_ASIDE_DUPLICATE_COORDINATOR,
        "A coordinator already watched through its own bridge sensor, "
        "appearing a second time as an ordinary device.",
    ),
    (
        SET_ASIDE_COPY,
        "Another listing in Home Assistant for the same hardware. Device "
        "Sentinel watches the hardware once, through the device that "
        "reaches it most directly.",
    ),
    (
        SET_ASIDE_NOTICES_ONLY,
        "Switch on one of its other entities and Device Sentinel watches it.",
    ),
    (
        SET_ASIDE_NO_ENTITIES,
        "It has no entities of its own that can report, so nothing could "
        "ever report. "
        "Entities another integration added to it do not count.",
    ),
)

# The integrations a person has asked never to watch. Muting in
# every other place suppresses judgment and reporting and keeps the
# record; this suppresses the watching itself, because some
# integrations publish measurements of nothing this house can be
# judged on. A phone travels and carries a cellular radio, a wall
# tablet's battery is charged rather than replaced, Spook describes
# Home Assistant rather than hardware, and a ping probe answers on
# every poll so it can never fall silent. The default is a starting
# point rather than a rule: it is the person's list, and the first
# save makes it theirs.
CONF_EXCLUDED_INTEGRATIONS = "excluded_integrations"
DEFAULT_EXCLUDED_INTEGRATIONS = (
    "mobile_app",
    "fully_kiosk",
    "spook",
    "ping",
    "tplink_router",
    "unifi",
    # See AUTO_EXCLUDED_INTEGRATIONS (rule MUTE-02).
    "music_assistant",
    "webostv",
    "androidtv",
    "androidtv_remote",
    "samsungtv",
    "apple_tv",
    "dlna_dmr",
    # Seen only through Amazon's cloud, and switched off with the
    # television (rule MUTE-02).
    "alexa_media",
    "cast",
)

# The default list as it stood before the media integrations joined it
# (rule MUTE-02). A house that never saved its list follows the default,
# so on such a house that already exists this is written as its list
# once, and the names added to the default since reach it as a
# recommendation, not behind its back.
DEFAULT_EXCLUDED_BEFORE_0277 = tuple(
    name for name in DEFAULT_EXCLUDED_INTEGRATIONS if name not in ("alexa_media", "cast")
)

# Integrations excluded the first time a new install sees them, as
# routers are; on a house that already exists, each is recommended for
# exclusion instead (rule MUTE-02). Music Assistant adds a player for each speaker it
# drives, a copy of hardware watched through its own integration that
# nothing ties to it, and its player can bring back a television already
# excluded through webostv. Televisions and media renderers go away when
# switched off. A person who takes one off the list keeps it off.
AUTO_EXCLUDED_INTEGRATIONS = (
    "music_assistant",
    "webostv",
    "androidtv",
    "androidtv_remote",
    "samsungtv",
    "apple_tv",
    "dlna_dmr",
    # Alexa Media Player brings in devices, Bluetooth headphones among them,
    # seen only through Amazon's cloud; a Google Cast device goes unavailable
    # whenever it is switched off (rule MUTE-02).
    "alexa_media",
    "cast",
)

# Single devices a person excluded: the integration exclusion's rules
# applied to one device (rule MUTE-03). Set aside with the same reason,
# discarded at the same fold, so taking it back before midnight loses
# nothing. Picked in Settings beside the integrations, or from the
# device's page.
# Not "excluded_devices": that name once meant a mute, and a file from
# then is still renamed to muted_devices on load.
CONF_EXCLUDED_DEVICES = "devices_to_exclude"

# The integrations that publish a tracker per client on the network. A
# router integration registers every client as its own registry device,
# which duplicates hardware another integration already watches and lets
# a device be tied to its own tracker. A new install excludes one when it
# first sees it; a house that already exists is offered a card instead
# (rule MUTE-02).
ROUTER_INTEGRATIONS = (
    "tplink_router",
    "unifi",
    "asuswrt",
    "fritz",
    "keenetic_ndms2",
    "mikrotik",
    "netgear",
    "ubus",
    "upc_connect",
)
# Every integration excluded when first seen, routers and
# AUTO_EXCLUDED_INTEGRATIONS alike: once listed here, never new again
# (rule MUTE-02). The name is from when only routers were.
DATA_ROUTERS_SEEN = "routers_seen"

# On a house that already exists, a router or media integration seen for
# the first time is recommended for exclusion, not excluded (rule
# MUTE-02): the domains whose card stands, until the person excludes the
# integration. A tick on the card keeps it watching, kept as a written
# recommendation's tick is.
DATA_EXCLUSION_OFFERS = "exclusion_offers"
OFFER_OPEN = "open"
OFFER_CLOSED = "closed"
# Why each is usually excluded, as its card says it (rule MUTE-02).
EXCLUSION_OFFER_REASONS = {
    "router": (
        "it registers every client on your network as a device, copies "
        "of hardware other integrations already watch"
    ),
    "alexa_media": (
        "Device Sentinel sees its devices only through Amazon's cloud, "
        "and headphones paired to an Echo are listed as devices of their own"
    ),
    "music_assistant": (
        "it adds a player for each speaker it drives, a copy of hardware "
        "watched through its own integration"
    ),
    "media": "its devices go unavailable whenever they are switched off",
}

# The devices set aside (disabled, excluded or held after a removal) at
# the last registry rebuild (rule WATCH-08). Saved, so a device taken
# back while Device Sentinel was reloading or disabled is still dated as
# returned. Absent in a file from an older release, whose stretches are
# not dated: the upgrade is not a return.
DATA_ASIDE_SEEN = "aside_seen"

# The learned medium of every router tracker, persisted (rule UP-14).
# Keyed by tracker entity id, each value a dict of wired and wireless
# sample counts. Held only in memory, it would be empty after every
# restart, so on a house that restarts often the census would show only
# what was seen home since the last boot.
DATA_WIFI_MEDIUM = "wifi_medium"

# Readings the medium scoring discarded, per tracker, persisted (rule
# UP-14). Held only in memory, it would read empty after every restart,
# and the count exists so the case for a general source-restart grace
# can be judged over weeks rather than felt.
DATA_WIFI_MEDIUM_REJECTED = "wifi_medium_rejected"

# How long a device the outage claimed is given to come back before it
# becomes its own problem (rule UP-08). The outage closes when it closes;
# this only delays the hand-back. After a Wi-Fi outage, blinds needed 20
# seconds after the close and a PoE switch 149. Three minutes covers both
# with room, and is short enough that a device that is really gone is
# still reported promptly. The row it writes is dated from the outage,
# not from the end of this window, or the timeline would lie about when
# the device went.
WIFI_HANDBACK_SECONDS = 180.0
# How long after setup the tie ladder is retried while no tie formed and
# some tracker has no router state yet. A router integration answers
# within minutes of a start; an orphaned tracker reads Home Assistant's
# placeholder for ever, and without a limit the ladder would be rebuilt
# every minute for the life of the run. After the window, ties form at
# the next registry change (rule UP-13).
WIFI_TIE_RETRY_SECONDS = 30 * 60.0
# How long a fallen tracker of an open outage may go without a usable
# state (none, Home Assistant's placeholder, or unavailable or unknown)
# before it is let go as if removed. A router never reached again, or an
# integration disabled, leaves trackers that can never come home, and
# held in the fallen set they would keep the outage open for ever,
# claiming every device that failed. Two hours is far past any router
# reboot or reload (rule UP-16).
WIFI_FALLEN_UNUSABLE_SECONDS = 2 * 3600.0
# How far before its first tracker a Wi-Fi outage may reach for its
# start (rule UP-15). A router marks a client away only after its own
# detection time, five minutes by default for UniFi and three for Home
# Assistant's device trackers, while a device's own integration often
# notices at once: the first client can leave more than four minutes
# after the network did.
WIFI_LOOKBACK_SECONDS = 300.0

# The same window for a bridge (rule UP-08). A bridge claim that ends
# the instant the bridge comes back orphans devices still rejoining the
# mesh, as the network window does for Wi-Fi. Three minutes to start,
# taken from the Wi-Fi measurement because no Zigbee one exists yet. A
# device can take longer to rejoin a mesh than to reassociate with an
# access point, so this is a starting point, and the outage probe records
# what it should be.
BRIDGE_HANDBACK_SECONDS = 180.0

AREA_FREEZE = "freeze"
AREA_BATTERY = "battery"
AREA_SIGNAL = "signal"

# Per-device signal fields (linkquality/RSSI, gather-first).
DEV_SIGNAL_VALUE = "signal_value"
DEV_SIGNAL_TODAY_MIN = "signal_today_min"
# The dwell record is erased: the daily minimum, the daily line, the
# dwell percentage, the two live below-line clocks, and the clock of the
# last change (rule SIG-13). The rail alert reads the rail column beside
# the reading count (rule SIG-07). The retired names are listed below
# only so the load sweep can remove them from stored files, including
# inside signal_alt blocks.
# Every device field a released version wrote and a later one retired,
# read from the fresh-record schema at every release tag. Only these are
# removed from a stored record at load; any other field the schema does
# not know belongs to a newer version and is kept, unread, so going back
# to an earlier release and forward again loses nothing (rule STOR-19).
RETIRED_DEVICE_FIELDS = frozenset(
    {
        "signal_below_since",
        "signal_below_today_seconds",
        "signal_daily_line",
        "signal_daily_min",
        "signal_dwell_daily_pct",
        "signal_frozen_at",
        "signal_frozen_verdict",
        # When the signal value last moved, kept for the dwell timer and retired
        # with dwell's recording (rule SIG-13).
        "signal_last_change",
        "signal_rail_since",
        "signal_repeat_count",
        "signal_sum",
        "signal_sum_sq",
    }
)

# The classification report's trigger once the startup grace has closed
# and the registry has settled.
CLASSIFICATION_SETTLED_TRIGGER = "after startup"

RETIRED_SIGNAL_KEYS = (
    "signal_daily_min",
    "signal_daily_line",
    "signal_dwell_daily_pct",
    "signal_below_since",
    "signal_below_today_seconds",
    "signal_last_change",
)

# The good-state statistics, recorded ahead of any method that judges
# on them (rule SIG-01): running accumulators, no samples kept, rolled
# at midnight into a per-day mean and deviation and then reset (rule
# SIG-05). The daily maximum rides along so a widening spread shows, not
# only a falling floor. Rail values feed none of them. The accumulators
# move with every reading, so they live in the clocks file; the rolled
# series lives in the main file.
DEV_SIGNAL_SUM = "signal_sum"  # retired; read once for migration (rule SIG-05)
DEV_SIGNAL_SUM_SQ = "signal_sum_sq"  # retired; read once for migration (rule SIG-05)
DEV_SIGNAL_COUNT = "signal_count"
# The day's reading count, kept apart from DEV_SIGNAL_COUNT since that
# counts minutes rather than reports (rule SIG-05). The daily count
# series is a count of reports on purpose: it answers how often a device
# spoke, which no time-weighted figure can.
DEV_SIGNAL_READS = "signal_reads"
# Welford accumulators: the day's running mean and its sum of squared
# distances from that mean (M2) (rule SIG-05). The naive sum and
# sum-of-squares pair subtracts two large near-equal numbers at the
# fold, the textbook catastrophic-cancellation site, and can round a
# near-constant device to a negative variance. Welford carries the
# spread directly and cannot. Same mean, same deviation, stably.
DEV_SIGNAL_MEAN_RUN = "signal_mean_run"
DEV_SIGNAL_M2 = "signal_m2"
# Streaming percentile states: P-Square estimators for the day's
# time-weighted 5th percentile and median (rule SIG-05). Each state is
# eleven numbers, fed one minute of held value at a time, so a value
# must persist for about 72 cumulative minutes before it can be the
# day's sustained low. Nearly half of device-days carry a minimum the
# day itself disowns (three deviations under its own mean), which is why
# the daily minimum is gone and the bad-day judgment reads P5 (rules
# SIG-06, SIG-08).
DEV_SIGNAL_P5_STATE = "signal_p5_state"
DEV_SIGNAL_P50_STATE = "signal_p50_state"
DEV_SIGNAL_PSQ_VALUE = "signal_psq_value"
DEV_SIGNAL_PSQ_TS = "signal_psq_ts"
DEV_SIGNAL_TODAY_MAX = "signal_today_max"
DEV_SIGNAL_DAILY_MEAN = "signal_daily_mean"
DEV_SIGNAL_DAILY_SD = "signal_daily_sd"
DEV_SIGNAL_DAILY_P5 = "signal_daily_p5"
DEV_SIGNAL_DAILY_P50 = "signal_daily_p50"
DEV_SIGNAL_DAILY_MAX = "signal_daily_max"
# Two more daily series beside the mean and deviation, recorded ahead of
# the successor method (rules SIG-05, SIG-11): how many real readings
# the day held (a 6-reading day and a 600-reading day should not weigh
# the same later), and how many rail readings arrived (a day of thin
# real statistics should say why).
DEV_SIGNAL_DAILY_COUNT = "signal_daily_count"
DEV_SIGNAL_DAILY_RAIL = "signal_daily_rail"
DEV_SIGNAL_RAIL_COUNT = "signal_rail_count"

# The two scales a link is measured on, and where the second one lives
# (rule SIG-03).
#
# RSSI is the radio's own power reading in dBm and is negative at any
# Zigbee receiver; LQI is the mesh's quality score on 0 to 255. A device
# that publishes both would land them in one series, spanning -66 to 247
# inside two hours, and every figure drawn from such a series is void.
#
# Scale is decided by the sign of the reading rather than by a label.
# Thousands of readings of each kind show no overlap: positives run 0 to
# 255 and negatives -106 to -1. Zero is a valid LQI meaning the worst the
# scale can express and is not a plausible RSSI, so it belongs with LQI.
# The rails below tell the scales apart by value too.
SIGNAL_SCALE_RSSI = "rssi"
SIGNAL_SCALE_LQI = "lqi"
DEV_SIGNAL_SCALE = "signal_scale"

# The second scale, when a device has one: None, or a block holding the
# same recording fields under the same names (rule STOR-15). One key
# rather than a fixed set of extra fields, because JSON stores field
# names and an empty block of twenty-one of them costs 531 bytes on every
# record, most of which will never have a second scale. Null costs 20.
#
# The names inside are the record's own names rather than short forms.
# Short names save little and would need a map between two spellings of
# one field, a second copy that parts from the first the day somebody
# adds a field and updates only one of them.
DEV_SIGNAL_ALT = "signal_alt"

# What the alternate block carries: everything recorded, and nothing
# judged. Only the primary scale is judged, because both scales are
# recorded and only one judged until the data says which deserves it
# (rule SIG-03).
SIGNAL_ALT_FIELDS = (
    DEV_SIGNAL_SCALE,
    DEV_SIGNAL_VALUE,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_TODAY_MAX,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_READS,
    DEV_SIGNAL_MEAN_RUN,
    DEV_SIGNAL_M2,
    DEV_SIGNAL_P5_STATE,
    DEV_SIGNAL_P50_STATE,
    DEV_SIGNAL_PSQ_VALUE,
    DEV_SIGNAL_PSQ_TS,
    DEV_SIGNAL_RAIL_COUNT,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_RAIL,
)

# Signal-entity recognition terms (Z2M sets no device class on
# linkquality; ZHA/Z-Wave use device_class signal_strength).
SIGNAL_NAME_TERMS = ("linkquality", "lqi", "rssi")

# Units that mean the entity is not a signal measurement at all (rule
# SIG-02). Tasmota reports RSSI as a 0 to 100 quality figure and Signal
# as the dBm, inverted from every other vendor, so on a Tasmota device an
# entity called RSSI carries a percentage and reaches the recognizer
# through the name term above. It is derived rather than measured: every
# Tasmota device seen fits 2 x (dBm + 100) clamped to 0 and 100. It
# restates a number already recorded.
#
# The refusal is by unit and not by vendor, because naming entities by
# what somebody called them is wrong in both directions. Home Assistant
# permits only dB and dBm for device_class signal_strength, so an entity
# carrying that class can never be a percentage and is never reached by
# this test.
#
# It is narrow on purpose. Refusing every unit not recognized would be
# written against a guess, since no diagnostics carry the unit of a
# Zigbee2MQTT linkquality entity, and a wrong guess would take signal
# away from every Zigbee2MQTT device. Refusing one unit fails toward
# recording, which is visible and fixable, rather than toward silence.
SIGNAL_REFUSED_UNITS = ("%", "percent", "percentage")
# No entity is refused by its name: a name says what somebody called a
# sensor, not what it measures, and every entity a name list would
# refuse arrives on an integration the exclude list refuses whole (rule
# SIG-02).

# The freeze judgment window: the rhythm is computed from the newest
# DAILY_MAX_KEEP days of daily maxima, however many are stored (rule
# FRZ-03). How many are stored is the retention below (rule STOR-14).
DAILY_MAX_KEEP = 14
# Signal reads thirty days (SIGNAL_DAYS_KEEP), for its own reasons (rule
# SIG-06). Neither window is a user setting, because a threshold that
# moved with a storage preference would mean two systems detecting
# differently for no reason anyone chose. Retention is how much history
# is kept, which judges nothing.
CONF_RETENTION_DAYS = "history_days"
DEFAULT_RETENTION_DAYS = 90
RETENTION_DAYS_MIN = 30
RETENTION_DAYS_MAX = 360
RETENTION_DAYS_STEP = 30
# What the diagnostics download emits per series, so an issue report
# stays a readable size at any retention.
DIAGNOSTIC_SERIES_CAP = 30

# The arming floor: a device with at least this many daily maxima has a
# learned rhythm, for the freeze judgment and the learning-progress
# sensor (rule FRZ-01).
LEARNING_MIN_DAYS = 7

# Storage save cadence: at most one write per render tick when dirty.
RENDER_TICK_SECONDS = 60

# Freeze detection. The freeze window is the learned rhythm plus a grace
# margin, and the margin follows a power curve of the rhythm shaped by
# two user sliders (rule FRZ-06). grace = a * rhythm^p, where a and p are
# fitted so the curve passes through delta-low grace at a fast reference
# rhythm and delta-high grace at a slow one, then clamped to [delta-low,
# delta-high]. The deltas reshape the whole curve, not just its ends, so
# a device in the middle of the house responds too, and they are also
# the floor and ceiling on grace. At the defaults a one-hour device gets
# about a two-times window, the knee the curve is normed around. The
# rhythm underneath is measured, not chosen, and the sliders tune only
# the grace.
CONF_FREEZE_DELTA_LOW = "freeze_delta_low"
CONF_FREEZE_DELTA_HIGH = "freeze_delta_high"
# delta-low: the fast-end grace floor, in minutes. A device reporting
# every few seconds is not called dead for missing a couple of
# reports. Range 1 to 8, default 3.
DEFAULT_FREEZE_DELTA_LOW_MIN = 3
FREEZE_DELTA_LOW_MIN_MIN = 1
FREEZE_DELTA_LOW_MIN_MAX = 8
# delta-high: the slow-end grace ceiling, in hours, so the slowest
# devices are still caught in a bounded time. The ceiling anchors the
# whole curve, so the range reaches up to 12. Range 4 to 12, default 8
# (rule FRZ-06).
DEFAULT_FREEZE_DELTA_HIGH_HR = 8
FREEZE_DELTA_HIGH_HR_MIN = 4
FREEZE_DELTA_HIGH_HR_MAX = 12
# The reference rhythms the two deltas are pinned at when the curve
# is fit: delta-low grace at 10 seconds, delta-high grace at 24
# hours. They bracket any real device (rule FRZ-06).
FREEZE_REF_RHYTHM_FAST = 10.0
FREEZE_REF_RHYTHM_SLOW = 24.0 * 3600.0

# A device is judged for freeze only once it has a learned rhythm (the
# arming gate). There is no global learning mode and no timer: the gate
# is per device and permanent, so a device added years from now is
# simply unarmed until it has learned. Below the arming floor a device
# is watched for unavailable and unknown but never called frozen,
# because a device with no rhythm has no window to miss (rule FRZ-01).
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
# read as unavailable either (a stale registry entry, a device dead
# since before install). It is flagged on its own, ahead of the other
# checks, once it has been watched long enough that silence is not just
# a slow first report. Forty-eight hours since first seen clears even a
# once-a-day device, which will have spoken twice by then (rule FRZ-09).
FREEZE_CATEGORY_NEVER_REPORTED = "never_reported"
FREEZE_NOT_REPORTED_SECONDS = 48.0 * 3600.0

# A device mid-transition flips its entities to unavailable in quick
# succession, usually within seconds. This debounce lets that settle
# before an unavailable verdict is published, so a device caught
# mid-flip is not reported in a half-state (rule UNAV-03).
FREEZE_UNAVAILABLE_DEBOUNCE = 180.0

# Identity attributes carried on every entity (rule REL-16).
ATTR_SENTINEL_TYPE = "sentinel_type"
ATTR_SENTINEL_VERSION = "sentinel_version"
ATTR_FIRST_INSTALLED = "first_installed"
ATTR_STORAGE_HEALTHY = "storage_healthy"
# The backup's story on the Status sensor (rule STOR-12).
ATTR_LAST_GOOD_TAKEN = "last_good_taken"
ATTR_LAST_GOOD_AGE_DAYS = "last_good_age_days"
ATTR_REPAIRS_AT_LOAD = "repairs_at_load"

SENTINEL_TYPE_STATUS = "status"
SENTINEL_TYPE_COVERAGE = "coverage"
SENTINEL_TYPE_LEARNING = "learning_progress"
SENTINEL_TYPE_CLASSIFICATION = "classification"
SENTINEL_TYPE_MAINTENANCE = "maintenance"

# Whether Zigbee2MQTT's availability feature is on, read from bridge
# info and shown on the bridge sensor. Reported, never written: turning
# it on is Zigbee2MQTT's configuration, not Device Sentinel's (rules
# STACK-03, STACK-13).
ATTR_BRIDGE_AVAILABILITY = "availability_enabled"

# Diagnostic files, written at every setup and after every midnight
# rollover. They live under /config, never under custom_components
# (code, wiped on update). Markdown rather than plain text so the
# maxima lists
# can carry emphasis (set-aside outliers struck through, the window
# basis bold).
REPORT_DIR = "device_sentinel"
# The old subfolder of the three maintainer files, which sit a level
# up. The name is kept only so the folder can be emptied of those three
# files once and removed if nothing else is in it (rule BRIEF-14).
REPORT_DIAGNOSTIC_DIR = "diagnostics"
# The folder Home Assistant serves at /local, where the brief and the
# reports once lived. Home Assistant serves it to anyone who asks,
# signed in or not, and the files named devices, battery levels and
# outage times, so it is retired: a start moves the current brief out
# and deletes the folder. The name is kept for that deletion and for the
# uninstall, which removes a leftover copy (rule BRIEF-14).
REPORT_WWW_DIR = "www/device_sentinel"
# The HTML brief, written beside the other reports in REPORT_DIR, which
# Home Assistant does not serve. One rendering serves the file and the
# emailed body, so the two cannot drift (rule BRIEF-12).
REPORT_BRIEF_HTML = "daily_brief.html"
# The dashboard's address, under which a device's page is
# /device-sentinel/device/<id>. The brief's device names link there, to
# the page that says why a device is listed (rule BRIEF-13).
PANEL_URL_PATH = "device-sentinel"
# The Problem List tab's own address, the panel's slug for the tab. The
# persistent card links there whenever it lists anything, because the
# card names a few devices and counts the rest, and the list holds them
# all (rule NOTE-11).
PROBLEM_LIST_PATH = f"/{PANEL_URL_PATH}/problem-list"
# Which dashboard file Home Assistant serves this run, the hash in its
# address. The dashboard reads it from the status reply and the change
# marker, so a tab left open across an update can tell that the file it
# runs is no longer the one served, and offer a reload (rule DASH-14).
DATA_PANEL_FILE = f"{DOMAIN}_panel_file"

# Days of battery history before the battery area of the recording
# depth reads armed: two whole weeks, the fewest that give one week to
# compare with another. Judging a battery's trend asks more (rule
# BAT-10).
BATTERY_ARMING_DAYS = 14
# A percentage that cannot be one. A device on Zigbee's raw scale reads
# around 196, which is proved and read as a percentage (rule BAT-02). A
# reading over 100 on a device not proved raw still cannot cross a low
# threshold and would distort any summary of the bank, so it is named as
# unreadable instead of counted as very healthy.
BATTERY_READABLE_MAX = 100.0

# A link needs three weeks before the Signal Trends tab compares its
# last week against its own normal: fewer days and the normal is
# mostly the week being judged.
SIGNAL_TREND_MIN_DAYS = 21

# ---------------------------------------------------------------
# A battery replacement, and the day one that follows it.
# ---------------------------------------------------------------
# A cell does not climb. When the level rises by this much between one
# day and the next, somebody changed it. The largest natural rise seen
# was 11.5 points, a sag under load recovering, so twenty-five is twice
# that with margin (rule BAT-06).
BATTERY_REPLACED_RISE = 25.0
# The other way a replacement looks: a cell that was at or below the
# second figure and lands at or above the first. A cell at 80 replaced
# reads 100, a rise of twenty, which the first test misses. The lower
# bound stops a cell already near full from qualifying by drifting: a
# cell going 94 to 99.5 on its own starts above ninety, so it is not one.
# No cell has been seen to cross from at or below ninety to at or above
# ninety-five naturally. Both figures come from data and stay open to a
# counterexample (rule BAT-06).
BATTERY_REPLACED_LANDS = 95.0
BATTERY_REPLACED_FROM_BELOW = 90.0
# On a replacement the daily series starts again at day one. The
# series it replaces is kept under this key and never read, so the
# history survives and the trend, the projection and every chart
# describe the cell that is in the device now.
DEV_BATTERY_DAILY_PREVIOUS = "battery_daily_previous"
DEV_BATTERY_REPLACED_AT = "battery_replaced_at"
# What the Battery Last Replaced row shows is kept in the answers file,
# one entry per device (rule BAT-07; battery_replacement.py).
# The reading a rise was measured against, held for one day while a
# suspected replacement waits for a second sample to confirm it (rule
# BAT-06). None when nothing is pending.
DEV_BATTERY_REPLACED_PENDING = "battery_replaced_pending"
# How many day-to-day falls of BATTERY_COARSE_STEP or more a cell has
# made since it last showed a smaller change (rule BAT-09). Stored
# because a cell that reports in 10-point steps may step once a month or
# two, and a second step can land after the first has aged out of the
# daily history. Two confirm a coarse reporter; any smaller change
# returns it to smooth.
DEV_BATTERY_COARSE_DROPS = "battery_coarse_drops"
# Whether a device reports its battery on Zigbee's raw scale, 0 to 200 in
# half-percents, rather than 0 to 100 (rule BAT-02). A raw device can
# report 200 down to 178 under a "%" unit, which is 100% down to 89%.
# Neither the unit nor the device class tells the two apart, since the
# raw value arrives labelled "%". The mark is cautious: a reading over
# BATTERY_RAW_PROOF on two different days, so a percent device that
# glitches once to 101 or 105 is never halved. Until then a reading over
# 100 is ignored; a raw device caught late is still caught. Once marked,
# every reading is halved, and the history stored before it was halved
# once when the mark was set. The mark lasts until the next battery
# change or firmware update, either of which can change the scale, and
# the device is then measured again.
DEV_BATTERY_RAW_SCALE = "battery_raw_scale"
# The local day of the first reading that would prove the raw scale,
# as an ISO date, or None. A reading on a different day confirms it.
DEV_BATTERY_RAW_FIRST_DAY = "battery_raw_first_day"
BATTERY_RAW_PROOF = 110.0
# The highest reading the raw scale gives; past it a reading is not a
# battery level on either scale and is ignored (rule BAT-02).
BATTERY_RAW_HIGHEST = 200.0
# The current run of drops of a device that goes unavailable again and
# again: when each drop began, when the run became a flap, when the
# device last came back, and the longest it stayed back between drops.
# Stored so a restart does not forget a flap (rule UNAV-06).
DEV_FLAP_DROPS = "flap_drops"
DEV_FLAP_SINCE = "flap_since"
DEV_FLAP_BACK = "flap_back"
DEV_FLAP_LONGEST = "flap_longest"
# Each firmware a device has reported, as [version, first seen] pairs,
# oldest first (rule DEV-15). Home Assistant's device registry keeps only
# the current version, so a change is recorded here or lost. Kept for the
# History setting's window like every daily series; the current version
# always stays, and an older one goes once the version that replaced it
# was first seen before the window opened.
DEV_FIRMWARE_HISTORY = "firmware_history"
# Each battery forecast, made at the midnight fold for a battery judged
# falling or accelerating, and scored when the battery reaches the level
# it ran to (rule BAT-15, battery_forecasts.py): rows of [day, level,
# accelerating, target, near, far, outcome, arrived]. The newest
# FORECAST_KEEP_ROWS are kept, about a year of daily rows; the house's
# tally of outcomes is kept without end under
# DATA_BATTERY_FORECAST_TALLY.
DEV_BATTERY_FORECASTS = "battery_forecasts"
DATA_BATTERY_FORECAST_TALLY = "battery_forecast_tally"
# The first time a cell was judged low since its last replacement: from
# then on its time left runs to empty, even if it reads above the
# threshold again, until a new battery goes in (rule BAT-13). Compared
# with DEV_BATTERY_REPLACED_AT rather than cleared, so a replacement
# detected, cancelled or dated by a person moves the latch with it.
DEV_BATTERY_FIRST_LOW = "battery_first_low"
# A battery's model pace is said only with at least this many other
# cells of its maker and model, giving the slowest and fastest of them
# (rule BAT-16).
BATTERY_MODEL_PACE_MIN_OTHERS = 2
# Each battery device's day: voltage, its own temperature, its running
# event count. Recording only; kept for the History setting (rule
# BAT-16).
DEV_BATTERY_EVIDENCE = "battery_evidence"
# What a reading may be before it is kept: a battery's volts (a mains
# reading on the same device is left out), and degrees Celsius.
EVIDENCE_VOLTAGE_RANGE = (0.5, 15.0)
EVIDENCE_TEMPERATURE_RANGE = (-50.0, 80.0)
# One row per battery replaced, for the house, kept for good (rule BAT-08).
DATA_BATTERY_LIVES = "battery_lives"
BATTERY_LIVES_KEEP = 5000
# The house's tally of forecasts to empty, kept apart from the tally of
# forecasts to the threshold, so each says how good its own are (rule
# BAT-15).
DATA_BATTERY_EMPTY_TALLY = "battery_empty_tally"
# A device silent for at least this many days before its battery was
# replaced gave out on the day it was last heard, so a forecast to empty
# is scored against that day (rule BAT-15).
FORECAST_SILENT_DAYS = 2
FORECAST_KEEP_ROWS = 400
FORECAST_INSIDE = "inside"
FORECAST_EARLIER = "earlier"
FORECAST_LATER = "later"
FORECAST_REPLACED = "replaced"
FORECAST_OUTCOMES = (FORECAST_INSIDE, FORECAST_EARLIER, FORECAST_LATER, FORECAST_REPLACED)
BATTERY_COARSE_STEP = 5.0
BATTERY_COARSE_CONFIRM = 2
BATTERY_STEPS_SMOOTH = "smooth"
BATTERY_STEPS_UNKNOWN = "not_enough"
BATTERY_STEPS_COARSE = "coarse"
BATTERY_STEPS_WORDS = {
    BATTERY_STEPS_SMOOTH: "Smooth",
    BATTERY_STEPS_UNKNOWN: "Not enough data",
    BATTERY_STEPS_COARSE: "Coarse",
}
SYS_BATTERY_REPLACED = "battery_replaced"

# What the reading can say. Ordered as the rules are tested.

# The person's answer to how far ahead a falling cell is called out.
# Seven to thirty, because under a week is too late to act and past a
# month the projection is guesswork (rule BAT-14).
CONF_BATTERY_DAYS = "battery_days_till_empty"
DEFAULT_BATTERY_DAYS = 30
# A cell is judged falling or accelerating, and given a time left, only
# at or under this many times the low threshold (rule BAT-10). Every
# method tried, the textbook ones included, misses a far-off date: most
# falling cells rest between steps, and a forecast is right more often
# the fewer points it covers (an accelerating warning 97 percent at 5
# points, 85 at 15, 77 at 30). Three times rather than twice, because the
# time left runs to the threshold, and a battery falling 4 or 5 points a
# week needs 20 or more points of room to be warned 30 days ahead. Above
# it a cell shows its weekly history only.
BATTERY_REPORT_CEILING_FACTOR = 3.0
BATTERY_DAYS_MIN = 7
BATTERY_DAYS_MAX = 30

# How time left is said, rather than printed as a number. A projection
# can move by about forty percent in an afternoon; the same relative
# error on a device reading 1122 days puts the truth anywhere between
# 670 and 1570, so printing 1122 claims a precision the arithmetic does
# not have. Precision falls with distance, which is how the error
# behaves, and the words are all a person needs (rule BAT-13).
BATTERY_LEFT_BANDS = (
    (7.0, "under a week"),
    (14.0, "about 2 weeks"),
    (30.0, "about a month"),
    (60.0, "about 2 months"),
    (90.0, "about 3 months"),
    (180.0, "about 6 months"),
    (365.0, "under a year"),
)
BATTERY_LEFT_BEYOND = "over a year"
REPORT_TELEMETRY = "device_telemetry.md"
REPORT_CLASSIFICATION = "classification.md"
REPORT_EPISODES = "silence_episodes.md"
# The stack probe's own file, written beside the other diagnostics while
# a stack is studied, so "send me the files in config/device_sentinel"
# covers it (rule STACK-12).
REPORT_STACK_PROBE = "stack_probe.md"
# Files an older release wrote that nothing writes now, deleted at
# startup: the .txt reports, and rhythm_shadow.md, the shadow of the
# Log-Normal Percentile from before it was put in use (rule STOR-19).
REPORT_STALE_FILES = ("device_telemetry.txt", "classification.txt", "rhythm_shadow.md")

# The trimmed maximum: one of the two rhythms a freeze window is built
# from (the other is the Log-Normal Percentile; the wait is the shorter,
# rule FRZ-05), and shown in the telemetry report. The top TRIM_TOP_K
# daily maxima are set aside as possible flukes and the rhythm is the
# maximum of the rest, so one bad day moves nothing while a recurring
# high value counts. Below TRIM_MIN_SAMPLES days there are too few
# samples to spare any, so nothing is trimmed (rule FRZ-03).
TRIM_TOP_K = 1
# The Log-Normal Percentile (rule FRZ-04). From the 28th usable day,
# over up to the last 42, on the logarithm of each day's longest gap:
# days more than 2.5 spreads from the mean are set aside, repeatedly,
# and the rhythm is the mean of the rest plus 1.2816 spreads, the
# 90th-percentile day the trimmed maximum aims at. A cut of 2.0 cleared
# every planted bad day but tripled false alarms; 3.0 let three bad days
# through. At 42 days five far-out bad days vanish, at 28 they do not. A
# spread floor of 0.15 keeps a device whose longest gap is nearly the
# same every day from reading as perfectly regular.
CLIP_START_DAYS = 28
CLIP_MAX_DAYS = 42
CLIP_DEVIATIONS = 2.5
CLIP_TARGET_DEVIATIONS = 1.2816
CLIP_SPREAD_FLOOR = 0.15
TRIM_MIN_SAMPLES = 7

# Battery detection judges the level only; liveness is the freeze
# detector's. The threshold is a setting, so a person can slide it above
# a real cell's level to see detection work (rule BAT-03).
CONF_LOW_THRESHOLD = "low_threshold"
# Fifteen by default. An entry that never stored a value keeps twenty
# through the migration, so nobody's alerts change without them asking
# (rule BAT-03).
DEFAULT_LOW_THRESHOLD = 15
LEGACY_LOW_THRESHOLD = 20

# The option keys step 4 of the migration removes, each now a constant
# in this file (rule STOR-19).
RETIRED_SLIDER_KEYS = (
    "settle_share_pct",
    "episode_share_pct",
    "incident_settle_seconds",
    "taint_floor_minutes",
    "taint_share_pct",
)
# The range both doors offer, one constant, so the options dialog and the
# dashboard slider cannot offer the one setting with two different
# ranges.
LOW_THRESHOLD_MIN = 1
LOW_THRESHOLD_MAX = 99
# A low battery clears only above the threshold plus this, because a
# cell hovers near the line and can recover by more than 2 points (rule
# BAT-03).
BATTERY_CLEAR_MARGIN = 3

# Per-device battery storage fields.
DEV_BATTERY_LOW = "battery_low"
DEV_BATTERY_SINCE = "battery_since"
DEV_BATTERY_VALUE = "battery_value"
# The discharge recorder. At each midnight the current battery value is
# appended here, so the history is a daily series of levels (89, 89, 88,
# 88, 80, 65), which the trend reads: the weekly averages, the fitted
# line and the curve (rule BAT-05). The value is stored rather than only
# the delta, because it is cheap and makes the series self-describing and
# gap-tolerant. Kept for the retention, like every daily series.
# The dates of a device's daily histories (rule STOR-16): per family, the
# newest entry's date, how many entries the dates cover, and the days
# skipped, as ranges. See daily_dates.py. Kept through an epoch wipe,
# which drops only the gap family's dates with the gap history it
# clears.
DEV_DAILY_DATES = "daily_dates"
DEV_BATTERY_DAILY = "battery_daily_value"
# Every per-day series a record keeps, each held to the retention at the
# fold whatever the day appended (rule STOR-14). The signal ones live in
# the record and in a second scale's block alike.
DAILY_SERIES_FIELDS = (
    DEV_DAILY_MAX,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_DAILY_PREVIOUS,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_RAIL,
)

# The series each area records, which its recording depth is read from:
# the learning summary and the diagnostics show it. Named here, below
# the fields they name.
SERIES_FREEZE = (DEV_DAILY_MAX,)
SERIES_BATTERY = (DEV_BATTERY_DAILY,)
SERIES_SIGNAL = (
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_RAIL,
)

# The freeze verdict, stored so it survives a reboot and so the sensor
# feed can compare and refresh only when it flips, not on every reading.
# The category is one of the three down states, or None when the device
# is alive. frozen_since is the UTC timestamp the verdict began, for the
# report and for "how long". down_began_as is the category the current
# trouble began as, so a freeze that turned unavailable still counts
# from the last report after a restart (rule UNAV-07).
DEV_FROZEN_CATEGORY = "frozen_category"
DEV_FROZEN_SINCE = "frozen_since"
DEV_DOWN_BEGAN_AS = "down_began_as"
# The last good value of each of the device's own entities, kept from
# the moment a verdict starts until it ends: {entity registry id: state}.
# Keyed by the registry id, so a renamed entity keeps its value. After a
# restart, a reload or an entity added again, the integration handing
# back the same value is its cache, not the device speaking. In the main
# file, written in the verdict's own save (rule WATCH-12).
DEV_HELD_VALUES = "held_values"
# The longest state Home Assistant keeps, and so the longest held value.
HELD_VALUE_LENGTH = 255
# Sensors whose value is worked out again at each start, so it never
# says whether the device spoke (rule WATCH-12).
UNHELD_DEVICE_CLASSES = frozenset({"timestamp", "duration"})


# What a statistics epoch keeps. The wipe is everything else, taken from
# the record schema, so a field added later is wiped by default and there
# is no second list to forget (rule STOR-19).
#
# The wipe takes the rhythm and the conclusions drawn from it: the daily
# maxima, today's maximum, the Log-Normal day count, the event count,
# the taint, and the verdict with its stamp, how it began, the saved
# outage start and the held values.
#
# Everything else is kept, because nothing is recoverable. There is no
# raw layer beneath these records: readings are folded into a daily
# figure as they arrive and never stored, so a wiped series cannot be
# rebuilt from anything. The signal statistics feed a later alert (rule
# SIG-11); the battery series cannot be collected again faster than it
# was collected. A rhythm rule changing is no reason to destroy either.
# Named by constant rather than by literal, as CLOCK_FIELDS is, because a
# constant's value changing would move CLOCK_FIELDS and leave a literal
# behind, and a field would quietly survive a wipe.
# The second scale's history is kept for the same reason the first
# one's is: an epoch reset drops learned rhythm and keeps signal history,
# and keeping one scale's while destroying the other's would leave a
# device half remembered. The scale label rides with it, because a block
# whose partner had been forgotten would let the next reading put the
# same scale on both sides of the record.
# A battery replacement is a fact about the hardware, not learned rhythm,
# so it survives an epoch reset with the series it splits (rule BAT-06).
# The comment sits outside the tuple because a guard reads the tuple's
# lines as names.
# The moment a device was watched again is kept, with the clock it
# corrects (rule WATCH-08).
EPOCH_KEPT = (
    DEV_WATCHED_FROM,
    DEV_DAILY_DATES,
    DEV_SIGNAL_SCALE,
    DEV_SIGNAL_ALT,
    DEV_BATTERY_DAILY_PREVIOUS,
    DEV_BATTERY_REPLACED_AT,
    DEV_BATTERY_FIRST_LOW,
    DEV_BATTERY_EVIDENCE,
    DEV_BATTERY_REPLACED_PENDING,
    DEV_BATTERY_COARSE_DROPS,
    DEV_BATTERY_RAW_SCALE,
    DEV_BATTERY_RAW_FIRST_DAY,
    DEV_FLAP_DROPS,
    DEV_FLAP_SINCE,
    DEV_FLAP_BACK,
    DEV_FLAP_LONGEST,
    DEV_FIRMWARE_HISTORY,
    DEV_BATTERY_FORECASTS,
    DEV_SIGNAL_READS,
    DEV_SET_ASIDE_SINCE,
    DEV_REMOVED_SINCE,
    DEV_REMOVED_NAME,
    DEV_LAST_ACTIVITY,
    DEV_FIRST_OBSERVED,
    DEV_SIGNAL_VALUE,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_MEAN_RUN,
    DEV_SIGNAL_M2,
    DEV_SIGNAL_P5_STATE,
    DEV_SIGNAL_P50_STATE,
    DEV_SIGNAL_PSQ_VALUE,
    DEV_SIGNAL_PSQ_TS,
    DEV_SIGNAL_TODAY_MAX,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_RAIL_COUNT,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
    DEV_BATTERY_DAILY,
)

# The legacy tail of the hot set: the naive accumulators are read once at
# upgrade from the clocks file, shed at the first fold, and never written
# for a fresh record (rule SIG-05). They stay listed in CLOCK_FIELDS so
# the merge still carries an upgraded install's partial day; this subset
# names them so tests can expect their absence from newer records.
LEGACY_CLOCK_FIELDS = (
    DEV_SIGNAL_SUM,
    DEV_SIGNAL_SUM_SQ,
)

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
    DEV_SIGNAL_SUM,
    DEV_SIGNAL_SUM_SQ,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_MEAN_RUN,
    DEV_SIGNAL_M2,
    DEV_SIGNAL_P5_STATE,
    DEV_SIGNAL_P50_STATE,
    DEV_SIGNAL_PSQ_VALUE,
    DEV_SIGNAL_PSQ_TS,
    # Written on every reading like the rest of the day's working set. A hot
    # field kept only in the cold file is written only when something else
    # forces a cold save, so a restart would bring back a stale count beside
    # a current mean and the day would fold a report count too low (rule
    # STOR-15).
    DEV_SIGNAL_READS,
    DEV_SIGNAL_TODAY_MAX,
    DEV_SIGNAL_RAIL_COUNT,
    # The saved outage start changes with the states, so it is written with
    # each routine save: kept only in the main file, a start already cleared
    # could come back after a power cut (rule UNAV-04).
    DEV_DOWN_SINCE,
)

SENTINEL_TYPE_LOW_BATTERIES = "low_batteries"
# A different set and a different question from the one above: low is a
# level that has been crossed, falling is one that is going to be (rule
# BAT-14).
SENTINEL_TYPE_FALLING_BATTERIES = "falling_batteries"
# The two signal conditions, counted apart because they are not the same
# kind of thing: a rail is a broken measurement confirmed over three days
# and it persists, a weak link is a live reading that moves day to day.
# Counted together they would give one number that meant two things
# (rule SIG-09).
SENTINEL_TYPE_SIGNAL_RAILS = "signal_rails"
SENTINEL_TYPE_SIGNAL_WEAK = "signal_weak"
SENTINEL_TYPE_FROZEN_DEVICES = "frozen_devices"

# The days of signal readings a device needs before the learning
# summary counts it as armed for signal.
SIGNAL_ARMING_DAYS = 7

# How many days of a device's daily signal low the reports and the
# dashboard show, and how many it takes to count as learned for signal.
# Thirty rather than the rhythm's fourteen, because a signal record read
# across days needs its bad days to stay in view; the rhythm stays at
# fourteen because a longer window can only raise a trimmed maximum
# (rule SIG-06). The bad-day judgment reads its own baseline window (rule
# SIG-08).
SIGNAL_DAYS_KEEP = 30


# The bad signal day (rule SIG-08). A device has a bad day when its own
# P5 falls well below its own recent normal, judged in that device's
# units and in its own spread, both gates together. The absolute gate is
# scale-native rather than a percentage, because a percentage of an RSSI
# number is meaningless: near -60 dBm a real 6 dB loss reads as ten
# percent. Defaults come from one ground-truth event, a router unplugged,
# and are settings rather than constants because one event cannot
# settle them.
CONF_BADDAY_DROP_LQI = "badday_drop_lqi"
DEFAULT_BADDAY_DROP_LQI = 25
BADDAY_DROP_LQI_MIN = 10
BADDAY_DROP_LQI_MAX = 60

CONF_BADDAY_DROP_RSSI = "badday_drop_rssi"
DEFAULT_BADDAY_DROP_RSSI = 6
BADDAY_DROP_RSSI_MIN = 3
BADDAY_DROP_RSSI_MAX = 15

CONF_BADDAY_SENSITIVITY = "badday_sensitivity"
DEFAULT_BADDAY_SENSITIVITY = 4.0
BADDAY_SENSITIVITY_MIN = 2.0
BADDAY_SENSITIVITY_MAX = 8.0

# How many folded days form the normal a day is judged against (rule
# SIG-08). Seven is a starting figure, not a measured one.
CONF_BADDAY_BASELINE_DAYS = "badday_baseline_days"
DEFAULT_BADDAY_BASELINE_DAYS = 7
BADDAY_BASELINE_DAYS_MIN = 4
BADDAY_BASELINE_DAYS_MAX = 14

# A baseline needs this many readings before it can be judged
# against. Fewer than four days of P5 cannot supply a spread worth
# dividing by, and a spread near zero makes any ratio explode.
BADDAY_MIN_BASELINE = 4
BADDAY_MIN_SPREAD = 1.0

# Signal-only muting, the same broad-to-narrow ladder as battery:
# integration, label, device (rule MUTE-04). Muting stops judgment, not
# observation: a muted device keeps recording its readings and daily
# statistics, so re-including it is instant and arrives with history; it
# simply stops being reported. A device that resists every recovery can
# be silenced without blinding the watcher.
CONF_SIGNAL_MUTED_DEVICES = "signal_muted_devices"
CONF_SIGNAL_MUTED_INTEGRATIONS = "signal_muted_integrations"
CONF_SIGNAL_MUTED_LABELS = "signal_muted_labels"

# Entities that are never the device (rule WATCH-04): a firmware notice
# is Home Assistant or the coordinator checking for firmware, and a
# command button (restart, identify, safe mode) is a thing Home Assistant
# can tell the device to do, holding only when it was last pressed there.
# Neither moves the device's clock, ends a verdict, or shows the device
# alive or gone. A device with nothing else switched on is set aside with
# a reason of its own, whatever it has switched off, unless it is an
# ESPHome device, whose connection is its report, or a device its hub
# speaks for, such as a Lutron Pico.
NOTICE_DOMAINS = frozenset({"update", "button"})

# How long a report through another entity keeps a device whose main
# entities are unavailable alive, while it has no freeze window yet. With
# a window, the window decides (rule UNAV-01).
ACTIVE_REPORT_SECONDS = 3600.0

# What a device whose only live entities are at rest reads as: like
# unknown, it says nothing, so the device is judged by its clock and a
# standing verdict is held (rule UNAV-02).
EVENT_RESTING = "resting"

# Freeze-only muting, the same three-tier ladder as battery and signal
# (rule MUTE-04). A device on this list is still watched and clocked, so
# its rhythm keeps learning and re-including it is instant, but it is
# never given a frozen or not-reported verdict; it is still told when it
# becomes unavailable (rule MUTE-06).
# For a device that is intermittent by nature (a car sensor that travels,
# a seasonal device) this silences the freeze report without hiding the
# device from everything.
CONF_FREEZE_MUTED_DEVICES = "freeze_muted_devices"
# The unavailable mute, by label or device: no integration list, since
# muting a whole stack for unavailable would hide every device on it
# going at once. It silences unavailable and dropping out only; frozen
# and never reported are the freeze mute's (rule MUTE-06).
CONF_UNAVAILABLE_MUTED_LABELS = "unavailable_muted_labels"
CONF_UNAVAILABLE_MUTED_DEVICES = "unavailable_muted_devices"
CONF_FREEZE_MUTED_INTEGRATIONS = "freeze_muted_integrations"
CONF_FREEZE_MUTED_LABELS = "freeze_muted_labels"

# The rails. A rail is a value that is flat and at the type's extreme:
# healthy LQI tops out near 224, so a flat 255 is the fill value of a
# field the device never filled, not a reading. -128 is the dBm rail on
# the RSSI side. Rail readings never feed the day's statistics; they are
# counted for the rail detector instead (rule SIG-04). A railed device
# stays watched until a person mutes it for signal (rule SIG-07).
SIGNAL_RAIL_LQI = 255.0
SIGNAL_RAIL_RSSI = -128.0
# The physical range of the two scales (rule SIG-04). LQI is a byte, 0 to
# 255; RSSI is received power in dBm, and nothing a Zigbee, Z-Wave or
# Wi-Fi radio reports sits below about -130. A finite reading outside the
# range is not a reading and is ignored, never brought into range: the
# edge of each scale is the rail value read as a stale reading (rule
# SIG-07), so a clamped value would raise a false rail problem. A finite
# check alone is not enough, because a reading near 1e308 overflows the
# day's running mean into NaN.
SIGNAL_LQI_HIGHEST = 255.0
SIGNAL_RSSI_LOWEST = -130.0
# The same rule for a battery (rule BAT-02): an entity of device class
# battery reports a percentage, so a finite reading outside 0 to 100 is
# not a level and is ignored, the last verdict holding. A reading near
# 1e308 would overflow the day's battery average to infinity.
BATTERY_LEVEL_LOWEST = 0.0
BATTERY_LEVEL_HIGHEST = 100.0

# A signal is railed when the device spoke on this many consecutive days
# and said nothing but the fill value (255, -128), read as a zero reading
# count beside a rail count above zero (rule SIG-07): a kind of signal
# problem rather than a sensor of its own. A live repeat counter cannot
# tell a stuck signal from a healthy steady link, because some devices
# report the same value for hours. Reading whole days means a rail that
# comes and goes within a day never confirms, while one that holds across
# days does, with no per-reading state to keep.
RAIL_CONFIRM_DAYS = 3

# Where messages go: the two target lists, the persistent card, the quiet
# hours and the daily brief. The engine that reads them is `notifier.py`.
#
# Two target lists. High-priority targets get each live push at any
# hour, Quiet Hours included; normal-priority targets get each live push
# outside Quiet Hours, and the brief goes to neither (rule NOTE-02). A
# normal-priority push inside Quiet Hours is dropped, and the brief
# carries the night (rule NOTE-07). A target in both lists is treated as
# high, normalized on save. Either list may be empty.
CONF_HIGH_PRIORITY_TARGETS = "high_priority_targets"
CONF_NORMAL_PRIORITY_TARGETS = "normal_priority_targets"
CONF_PERSISTENT_ENABLED = "persistent_enabled"

# The dashboard each window opens in: Simple on a new install, Advanced
# on one that upgraded (options step 7). The dashboard's own switch holds
# only while the person stays on it (rule DASH-03).
CONF_DASHBOARD_MODE = "dashboard_mode"
DASHBOARD_SIMPLE = "simple"
DASHBOARD_ADVANCED = "advanced"
DASHBOARD_MODES = (DASHBOARD_SIMPLE, DASHBOARD_ADVANCED)
DEFAULT_DASHBOARD_MODE = DASHBOARD_SIMPLE
CONF_QUIET_ENABLED = "quiet_hours_enabled"
CONF_QUIET_START = "quiet_hours_start"
CONF_QUIET_END = "quiet_hours_end"
# The brief's targets and mode. The two reminder keys below drive the
# daily brief and keep their stored names, because renaming a stored key
# costs a migration for a cosmetic gain.
CONF_BRIEF_TARGETS = "brief_document_targets"
# Which address the reports put in a link, if any. A report is a file a
# person shares: attached to an issue, mailed to whoever helps them with
# their house. Putting the address of that house in it is their decision,
# so nothing is linked until they make it, and the screen shows the
# address each choice would publish before they choose it (rule
# BRIEF-13).
CONF_REPORT_LINKS = "report_link_address"
REPORT_LINKS_NONE = "none"
REPORT_LINKS_EXTERNAL = "external"
REPORT_LINKS_INTERNAL = "internal"
DEFAULT_REPORT_LINKS = REPORT_LINKS_NONE
# Where a target name is parsed rather than merely stored. Kept here
# because the sending engine turns a stored target back into a service
# call, and a module that composes messages should not import the
# configuration screens to learn how a target is spelled.
NOTIFY_DOMAIN = "notify"
PERSISTENT_TARGET = "persistent_notification"

# An SMTP recipient, chosen as its notify entity and sent through
# smtp.send_message, the action that still carries the HTML page (rule
# BRIEF-11). Stored as "smtp:notify.<entity>" so it can never be mistaken
# for an old-style notify action of the same name: Home Assistant retires
# those for SMTP in 2027.3, and until then both may exist side by side,
# the old one chosen and working as before.
SMTP_TARGET_PREFIX = "smtp:"
SMTP_DOMAIN = "smtp"
SMTP_SEND_MESSAGE = "send_message"
PERSISTENT_CREATE = "create"
# The restore notice title, used by the email and the push. The durable
# surface is a repair card, not a persistent notification, so no
# notification id is kept for it (rule REP-08).
RESTORE_NOTICE_TITLE = "Device Sentinel restored its storage"

# The notification engine. Three self-overwriting surfaces, each a fixed
# id so it always replaces its own last message rather than stacking,
# always showing the most recent picture rather than a pile of stale ones
# (rule NOTE-03).
#
# The persistent card: one id, always the current home state, re-sent on
# every change, never held by quiet hours because a card wakes no one
# (rule NOTE-11). The per-family pushes: one id per family so each
# always shows its most recent event and summary; faults play the
# phone's own notification sound, recoveries are sent silently (rule
# NOTE-04).
NOTIFY_CARD_ID = "device_sentinel_state"

# The three notification families. A family is not a problem kind, and
# spelling a family the same as a kind would make "battery" mean a fault
# in one table and a family in another. The families are named here so
# neither has to be guessed from context (rules LIST-02, NOTE-03).
NOTIFY_FAMILY_BATTERY = "battery"
NOTIFY_FAMILY_SIGNAL = "signal"
NOTIFY_FAMILY_FREEZE = "freeze"
# The phone's notification tag per family: a push carrying a tag replaces
# the previous one rather than stacking beside it, so all battery news
# collapses into one entry on the lock screen (rule NOTE-03). These values
# must not be swept up by a rename of the kinds. They are identities
# already living on every installed phone, and changing one costs a
# duplicate notification for no gain.
NOTIFY_FAMILY_IDS = {
    NOTIFY_FAMILY_BATTERY: "device_sentinel_battery",
    NOTIFY_FAMILY_SIGNAL: "device_sentinel_signal",
    NOTIFY_FAMILY_FREEZE: "device_sentinel_freeze",
}
NOTIFY_FAMILY_TITLES = {
    NOTIFY_FAMILY_BATTERY: "Battery",
    NOTIFY_FAMILY_SIGNAL: "Signal",
    NOTIFY_FAMILY_FREEZE: "Device",
}
# The email's subject, and the brief's own title, kept as one string
# so the document and the message it arrives in cannot disagree.
BRIEF_TITLE = "Device Sentinel Daily Brief"
CONF_REMINDER_MODE = "daily_reminder_mode"
CONF_REMINDER_TIME = "daily_reminder_time"

# Off for a new install, because the dashboard shows what the card
# showed. An older install that never saved the setting keeps the card,
# through options migration step 5 (rule NOTE-11).
DEFAULT_PERSISTENT_ENABLED = False
DEFAULT_QUIET_ENABLED = False
DEFAULT_QUIET_START = "22:00:00"
DEFAULT_QUIET_END = "08:00:00"
DEFAULT_REMINDER_MODE = "none"
DEFAULT_REMINDER_TIME = "08:00:00"

# The share of its device's learned gap a fault waits before it is
# pushed. A constant, since a share of what the device already earned
# cannot be set to nonsense (rule NOTE-06).
SETTLE_SHARE_PCT = 30

# How many unexplained interruptions put a device in the brief's repeat
# offenders section (rule BRIEF-09). An interruption is unexplained when
# no restart, bridge outage, broker outage, reload or pairing window
# covers it, judged by the same attribution the rest of the brief uses.
# The filter is the detector: counting every opening puts dozens of
# devices at exactly 2 from a nightly reboot, while counting unexplained
# openings leaves only the real flappers. The floor is a judgment:
# anything the filter cannot explain twice is worth one line, and a house
# where 2 turns out noisy has the slider.
CONF_REPEAT_FLOOR = "repeat_floor"
DEFAULT_REPEAT_FLOOR = 2
REPEAT_FLOOR_MIN = 1
REPEAT_FLOOR_MAX = 4
# The section reads up to this many days of incidents, growing from day
# one rather than waiting for the window to exist. Seven so that noise
# which stopped repeating drops off the table sooner, and the paragraph
# beneath the table says seven to match: the number is stated in one
# place and the prose follows it, never the reverse (rule BRIEF-09).
REPEAT_WINDOW_DAYS = 7.0
# The share of the grace a silence passes before its episode opens. A
# constant: it shapes one record and nothing a person is alerted about
# (rule FRZ-08).
EPISODE_SHARE_PCT = 50
CONF_COALESCE_MINUTES = "storage_write_minutes"
DEFAULT_COALESCE_MINUTES = 15
COALESCE_MINUTES_MIN = 1
COALESCE_MINUTES_MAX = 60

# How Often the brief is sent (rule BRIEF-11).
REMINDER_MODE_NONE = "none"
REMINDER_MODE_OVERNIGHT = "overnight"
REMINDER_MODE_DAILY = "daily"

# The Problem List. One todo entity, not one per family: the kind lives
# on each item. Items are stored under their own key, apart from
# per-device telemetry, because they are problem records rather than
# device statistics. Each item is Device Sentinel's own and keyed by
# device_id, one per device however many detections tag it. An item
# stored without a device_id, as a hand-typed one is, is removed at
# setup (rule LIST-01).
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
# its verdict strings: the sync passes a verdict straight through as a
# kind, so these alias the categories rather than restating them, and
# each string is defined once.
# Everything that turns a kind into words keys off these names, so a
# rename fails at import rather than quietly printing a raw kind
# into somebody's daily brief.
TODO_KIND_LOW_BATTERY = "low_battery"
# A cell projected to reach empty inside the person's horizon. A
# different kind from the one above and not a lesser version of it: low
# is a level that has been crossed, falling is one that is going to be,
# and a cell at eighty percent dropping steadily can have less life left
# than one sitting at thirty that has not moved in a month. They combine
# into one line when a device has both (rule BAT-14).
TODO_KIND_FALLING_BATTERY = "falling_battery"
TODO_KIND_FROZEN = FREEZE_CATEGORY_FROZEN
TODO_KIND_UNAVAILABLE = FREEZE_CATEGORY_UNAVAILABLE
TODO_KIND_UNKNOWN = FREEZE_CATEGORY_UNKNOWN
TODO_KIND_NEVER_REPORTED = FREEZE_CATEGORY_NEVER_REPORTED
TODO_KIND_RAILED_SIGNAL = "railed_signal"
# A device that keeps dropping out (rule UNAV-06). A door sensor can go
# unavailable for a few minutes dozens of times a day, each drop past the
# three-minute wait, each opening and closing a problem. Three drops in
# two hours make a device flapping; it stays so until it has stayed back
# longer than the longest it stayed back between drops, plus the freeze
# grace for a gap that size. One item, one push when it starts and one
# when it clears; each drop is still recorded.
TODO_KIND_FLAPPING = "flapping"
FLAP_DROPS_TO_START = 3
FLAP_WINDOW_SECONDS = 2.0 * 3600.0
FLAP_CHECK_WORDS = "Check its signal and the router it connects through."
# The signal problem rows tag a railed link with the kind above and
# leave a merely low one untagged. This names that default so the
# absence reads as a decision rather than an oversight; it is a row
# tag and not a problem kind, so it is not in TODO_KINDS_ALL.
SIGNAL_ROW_LOW = "low"

# The old spellings of four problem kinds, and the only place the old
# words may appear. Stored history keeps whatever was written at the
# time, so the incidents, the additions journal and the to-do items are
# rewritten once at load and the house then speaks one vocabulary rather
# than two (rule LIST-02).
#
# Three named passes rather than one walk over every "kind" in the file:
# the system events list carries its own vocabulary of fourteen values
# under the same field name, and a generic sweep would destroy every one
# of them.
LEGACY_KIND_RENAMES = {
    "battery": TODO_KIND_LOW_BATTERY,
    "battery_falling": TODO_KIND_FALLING_BATTERY,
    "signal": TODO_KIND_RAILED_SIGNAL,
    "rail": TODO_KIND_RAILED_SIGNAL,
    "not_reported": TODO_KIND_NEVER_REPORTED,
}
# Not a TODO_KIND_: those are device faults, and every one has a route to
# the card, an event wording, and a state template, which a test asserts.
# This names a cause rather than a device, carries its own sentence, and
# takes no part in the incident timeline, so it is outside that family
# (rule UP-11).
UPSTREAM_KIND = "upstream"

# Every problem kind, in one place. Several tables map a kind to words,
# and one written by hand can miss a kind and leave a raw key such as
# "battery_falling" in a person's brief; a guard listing the kinds by
# hand would miss it too. Anything that maps kinds reads this (rule
# LIST-02).
TODO_KINDS_ALL = (
    TODO_KIND_FLAPPING,
    TODO_KIND_FROZEN,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_UNKNOWN,
    TODO_KIND_NEVER_REPORTED,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_FALLING_BATTERY,
    TODO_KIND_RAILED_SIGNAL,
)

# Which kinds are the same problem said differently. A device that is
# not reporting can be called frozen, unavailable, unknown or never
# reported, and which it earns depends on what its entities read at the
# moment of judgment, so a restart that hides a device's states for a
# minute moves it from one to another and back. That is a re-description,
# not a new problem: the item never left the list and nothing about the
# device changed (rule LIST-06).
#
# A battery and a signal are their own families, because a cell dying on
# a device that is already silent is new and a person wants to hear it.
TODO_KIND_FAMILIES = {
    TODO_KIND_FLAPPING: "down",
    TODO_KIND_FROZEN: "down",
    TODO_KIND_UNAVAILABLE: "down",
    TODO_KIND_UNKNOWN: "down",
    TODO_KIND_NEVER_REPORTED: "down",
    TODO_KIND_LOW_BATTERY: "battery",
    TODO_KIND_FALLING_BATTERY: "battery",
    TODO_KIND_RAILED_SIGNAL: "signal",
}

# What Device Sentinel says on the bus. Separate names rather than one
# type with an action field, because an automation triggers on event_type
# and a distinct name is what a person types into the trigger box (rule
# NOTE-12).
EVENT_FAULT = "device_sentinel_fault"
EVENT_RECOVERED = "device_sentinel_recovered"
EVENT_ACKNOWLEDGED = "device_sentinel_acknowledged"
# Fired when a line leaves the list because its device left the watched
# set, not because anything recovered. An automation pairing faults to
# recoveries needs every fault to get an answer, and a device that never
# came back must not be called recovered; this answer keeps both (rules
# LIST-09, NOTE-12).
EVENT_WITHDRAWN = "device_sentinel_withdrawn"
WITHDRAWN_REASON_SET_ASIDE = "set_aside"
WITHDRAWN_REASON_MUTED = "muted"
# A device removed from Home Assistant, its record held (rule WATCH-07).
WITHDRAWN_REASON_REMOVED = "removed"

# The upstream pair. A stopped broker or bridge silences every device
# behind it on purpose (rule UP-05), so without these the one failure
# that takes a house quiet would be the one an automation could not see.
# Two names rather than one with an action field, for the same reason as
# the names above (rule UP-10).
EVENT_UPSTREAM_DOWN = "device_sentinel_upstream_down"
EVENT_UPSTREAM_RESTORED = "device_sentinel_upstream_restored"

# What kind of upstream the payload is about. A property of the
# subject rather than of the action, so it rides in the payload (rule
# UP-10).
UPSTREAM_BROKER = "broker"
UPSTREAM_BRIDGE = "bridge"
UPSTREAM_INTEGRATION = "integration"
UPSTREAM_WIFI = "wifi"

# The Wi-Fi outage watch (rule UP-12). Not a stack: it exists only where
# watched devices have router trackers tied to them, the way signal
# detection exists only where a device reports signal. The numbers are
# measured, not chosen: a real outage put nine watched trackers not_home
# inside sixty seconds, and ordinary churn never exceeded three, once, in
# a wobble after a restart that the hold absorbed.
WIFI_KEY = "wifi"
WIFI_SENSOR_NAME = "Bridge: WiFi"
# The dashboard's status band says it as people write it.
WIFI_BAND_NAME = "Wi-Fi"
# How many tied trackers falling together declares an outage (rule
# UP-12). A bare count suits a small house, where three is a quarter of
# it; in a house of a hundred devices three is three percent, a hair
# trigger. The threshold is the greater of the floor and a share of the
# tied set. Churn tops out near five percent of tied trackers in a
# minute, against a staged outage peaking at 44 percent, and the smallest
# real event measured is 25 percent. Ten percent sits in that gap, and
# anything from six to twenty behaves the same on the data held. The
# floor governs up to thirty tied trackers and the share above it. Large
# houses are extrapolated and want checking when one reports.
WIFI_BURST_FLOOR = 3
WIFI_BURST_SHARE = 0.10
WIFI_BURST_WINDOW_SECONDS = 60.0
WIFI_HOLD_SECONDS = 60.0
# How long a burst of tied devices' rows wait for the router before they
# are shown (rule UP-15): the router's detection time, the outage's own
# hold, and one tick for the sampler to see it. An outage can be declared
# more than five minutes after its first device failed.
WIFI_BURST_HOLD_SECONDS = WIFI_LOOKBACK_SECONDS + WIFI_HOLD_SECONDS + 60.0

# How an outage ends (rule UP-16). Restoring while fewer than
# WIFI_BURST_FLOOR tied trackers read not_home answers a different
# question from the one that declared the outage: three falling together
# is a fair threshold for declaring one, three still away is not a fair
# threshold for ending one, because a house with three devices switched
# off could never recover.
#
# Recovery is judged against the set that fell instead. A share and no
# floor: on a three-device outage a floor requires all three back, the
# very hold this removes. Closing early is the cheap error, since
# whatever is still away goes back to per-device detection.
#
# The settle rides the burst out rather than cutting it at a fixed delay.
# A quiet period fails, because it reads the tail of a recovery, where
# the variance is, and a pause inside a real recovery can run to 375
# seconds. Every long pause measured falls after the 40 percent mark, so
# a share reads the burst and never meets them.
#
# Reopening reuses WIFI_BURST_FLOOR rather than a number of its own:
# three trackers falling together is what declares an outage in the
# first place, so three falling during a settle is a new event by the
# same evidence.
WIFI_RECOVERY_SHARE = 0.4
WIFI_SETTLE_TICKS = 2

# Wi-Fi detection from the host's own radio (rule UP-12). Independent of
# every router integration: the host scans for access points and the
# network is up while any of them broadcasts a chosen name.
CONF_WIFI_NETWORKS = "wifi_networks"
CONF_WIFI_CONFIRM_SECONDS = "wifi_confirm_seconds"
DEFAULT_WIFI_CONFIRM_SECONDS = 60

# How often the radio is asked what it can hear. A scan is not free
# and an outage is held for a minute anyway, so a faster sweep would
# buy nothing a person could act on.
WIFI_SCAN_SECONDS = 60.0

# What the person volunteered for study: each toggle turns on the
# gathering for one integration or stack, in `study.py` and
# `study_stacks.py`, for the diagnostics download (rule STACK-11).
CONF_STUDY_HARDWARE = "study_hardware"

# The router integrations whose device trackers the tie reader can use,
# named so the diagnostics can say which one a house runs (rule DEV-16).
# Wider than what is supported today on purpose: a report from a router
# nobody has built for is the report worth having.
ROUTER_DOMAINS = (
    "tplink_router",
    "unifi",
    "fritz",
    "asuswrt",
    "netgear",
    "mikrotik",
)
# How many devices one infrastructure entry reports. A router with
# two hundred tracked clients would otherwise bury the four lines
# that say what the router is.
INFRASTRUCTURE_DEVICE_CAP = 12

# What may be volunteered for study, and nothing else (rule STACK-11).
# Only what support is still being built for: TP-Link is supported and
# proven on hardware, so it is not here, and asking for data nobody needs
# would waste the one thing this screen spends, a person's willingness
# to help.
STUDIABLE = {
    "unifi": "Router: UniFi",
    "fritz": "Router: FRITZ!Box",
    "asuswrt": "Router: AsusWRT",
    "netgear": "Router: NETGEAR",
    "mikrotik": "Router: MikroTik",
    "zwave_js": "Z-Wave",
    "matter": "Matter",
    # Stacks whose support is still being built (rule STACK-11).
    "hue": "Philips Hue",
    "smartthings": "SmartThings",
    "tuya": "Tuya",
    "lutron_caseta": "Lutron Caséta",
}

# A study keeps the shapes it has seen, not every reading: one stored
# example per distinct transition, counted thereafter. Capped so a
# varied fleet cannot grow the file without bound, and the cap is
# recorded when reached rather than silently dropping.
STUDY_SHAPE_CAP = 200

# How many devices a phone push names before it counts the rest (rule
# NOTE-05): worst first, then most recent, because fifty devices down
# would make a push of over two thousand characters. The push only: the
# brief's In Short names every device and is never capped (rule
# BRIEF-02).
SUMMARY_NAMES = 3

# Worst first, so kinds[0] is the headline and an automation reads it
# without a template. Unavailable leads because FREEZE_CATEGORY_PRIORITY
# puts it above frozen: an unavailable device is honestly absent and a
# frozen one is lying (rule LIST-02).
TODO_KIND_SEVERITY = (
    # First, so a drop while flapping is never announced as news and a
    # return between drops is never a recovery: the flap is the problem, and
    # it outranks each of its drops (rule UNAV-06).
    TODO_KIND_FLAPPING,
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_FROZEN,
    TODO_KIND_UNKNOWN,
    TODO_KIND_NEVER_REPORTED,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_FALLING_BATTERY,
    TODO_KIND_RAILED_SIGNAL,
)


# What the payload says when a device has no area, because a template
# joining a null into a message renders the word None at a person.
UNASSIGNED_AREA = "Unassigned"

# The freeze family covers every liveness kind; a battery or signal
# kind maps to its own family, and anything else is a freeze-family
# event. This is the map from a problem kind to its notification family.
NOTIFY_KIND_FAMILY = {
    TODO_KIND_FLAPPING: NOTIFY_FAMILY_FREEZE,
    TODO_KIND_LOW_BATTERY: NOTIFY_FAMILY_BATTERY,
    TODO_KIND_FALLING_BATTERY: NOTIFY_FAMILY_BATTERY,
    TODO_KIND_RAILED_SIGNAL: NOTIFY_FAMILY_SIGNAL,
    TODO_KIND_FROZEN: NOTIFY_FAMILY_FREEZE,
    TODO_KIND_UNAVAILABLE: NOTIFY_FAMILY_FREEZE,
    TODO_KIND_UNKNOWN: NOTIFY_FAMILY_FREEZE,
    TODO_KIND_NEVER_REPORTED: NOTIFY_FAMILY_FREEZE,
}

# The additions journal. Every item added and every kind that joins an
# existing item is recorded here, with when (rule LIST-05). Bounded so
# storage stays small; the journal is a feed, not an archive.
DATA_TODO_JOURNAL = "todo_journal"

# The incident log, the single memory every channel renders over: the
# push, the brief, the email and the card all read this and none derives
# its own truth (rule NOTE-01). It covers the whole life of a problem,
# not only its opening, so a night of problems that opened and healed
# while the house slept still tells a story: a device broke, and it came
# back.

DATA_INCIDENTS = "incidents"
INCIDENT_KEEP_DAYS = 14
INC_DEVICE_ID = "device_id"
INC_NAME = "name"
INC_KIND = "kind"
INC_EVENT = "event"
INC_WHEN = "when"
INC_CAUSE = "cause"
# Whether this kind ended because a worse one replaced it (rule LIST-07).
# Without it, the record could say a device recovered in the same second
# it was declared unavailable. An older row carries no flag and reads as
# it did.
INC_SUPERSEDED = "superseded"
INC_DURATION = "duration"
# The device's signal when it went unavailable, on the opening row only:
# the reading and the day's mean and spread so far, the same snapshot a
# silence episode takes, kept as evidence for a later signal alert (rule
# SIG-11).
INC_SIGNAL = "signal"
# When an unavailable or unknown problem began, on its opening row only:
# the row is written when the device is listed, minutes after it went,
# and the recovery counts from when it went (rule UNAV-07). An older row
# has none and reads as it did.
INC_SINCE = "since"
# How far before the listing a kept start may lie: the debounce and a
# late sweep. A start further back, such as one held while an unavailable
# mute hid the device, keeps the listing time (rule BRIEF-07).
INC_SINCE_MAX_LEAD = 900.0
# Event types: a problem opening and a problem resolving. What a
# person does to the list is an ACTION, below.
INCIDENT_OPENED = "opened"
INCIDENT_RESOLVED = "resolved"
# One event for everything a person does to the list, with the cause
# saying which. A person checking a box is not the house producing a
# fault, so these rows never count as a device failing (rule BRIEF-06).
INCIDENT_ACTION = "action"
ACTION_ACKNOWLEDGED = "acknowledged"
ACTION_UNACKNOWLEDGED = "unacknowledged"
ACTION_DELETED = "deleted"
ACTION_READDED = "readded"
# A device that left the watched set with a problem standing. Not a
# resolution: nothing about the device changed, and the watching stopped.
# Recorded so the timeline says what happened rather than claiming an
# ending (rule LIST-09).
ACTION_SET_ASIDE = "set_aside"
# The watching stopped because the device was removed from Home
# Assistant, told apart from being set aside (rule LIST-09).
ACTION_REMOVED = "removed"
# A kind a person muted away, by device, integration or label. A mute is
# a person's act, not a recovery: nothing is pushed, no recovery reaches
# the bus, and the brief never says "recovered" (rule MUTE-07).
ACTION_MUTED = "muted"

# How far before an incident opened an episode may have ended and still
# be its explanation. A sampler notices an intervention up to one tick
# late, so an episode closed a minute early is the same event; one closed
# on Tuesday is not (rule BRIEF-05).
CAUSE_EPISODE_SLACK_SECONDS = 120.0

# The kinds whose recovery can name a cause. Only a silence has a lever
# to credit: a battery rising or a rail clearing has no reconnect or
# restart behind it, so those resolutions stay silent about why rather
# than guessing.
# Named from the constants rather than spelled by hand, so a rename of
# the kinds cannot leave this set behind and quietly stop crediting a
# cause to a never-reported recovery (rule LIST-02).
FREEZE_KINDS_FOR_CAUSE = frozenset(
    {
        TODO_KIND_FROZEN,
        TODO_KIND_UNAVAILABLE,
        TODO_KIND_UNKNOWN,
        TODO_KIND_NEVER_REPORTED,
    }
)

# The daily brief: one file beside the other reports, daily_brief.html,
# written for a person rather than a maintainer: what is wrong now, what
# happened in the last 24 hours, plain language, no machinery (rule
# BRIEF-01).
#
# The trigger that closes a brief's window rather than opening one. Named
# once, because the writer and the scheduler have to agree, and a typo
# between them would silently leave every brief in progress.
BRIEF_TRIGGER = "daily brief"
# What a recovery says when no lever was observed. Not "on its own":
# Device Sentinel sees restarts and reconnects, and sees nothing at all
# when a person rebinds a device or pulls a battery, so the absence of a
# known lever is not evidence that the device recovered by itself.
RECOVERY_CAUSE_UNOBSERVED = "no intervention recorded"

# How a silence ended, in the words the payload uses. Three values,
# because two would mean guessing: most resolved incidents store no
# cause, and those are a battery with no lever to name or a silence whose
# episode fell outside the slack, which one value would blur (rule
# BRIEF-05).
RECOVERY_BY_SELF = "self"
RECOVERY_BY_INTERVENTION = "intervention"
RECOVERY_BY_UNKNOWN = "unknown"
# Only a person's own act is credited with a recovery. A restart or an
# outage says nothing about the devices, on any stack (rule UP-06), so
# "bridge reconnect", "reboot", "restart" and "unclean shutdown" are not
# in this set, and a recovery after one is the device's own.
# A person's pairing window open when the device came back is credited on
# every surface, the brief's windows and the stored cause alike, so the
# bus says intervention where the brief says revived (rule BRIEF-05).
RECOVERY_CAUSE_PAIRING = "pairing window"
RECOVERY_CAUSES_INTERVENTION = frozenset(
    {"handled at the device", RECOVERY_CAUSE_PAIRING}
)
# Integrations whose reading after a restart or a reconnect is fetched
# from the device itself, so it is the device answering (rule FRZ-11).
# Each is here only because its source shows it: HomeKit Device polls
# every characteristic from the accessory when it connects
# (homekit_controller/connection.py, async_setup), and an ESPHome device
# sends its current states when its connection opens (esphome/manager.py,
# on_connect). ZHA restores each entity's last state from Home
# Assistant's store, Zigbee2MQTT's broker hands back retained messages,
# and Matter and Z-Wave serve their own caches, so none of those is here.
# Any integration not listed gets the literal reading: a value it
# restores is not the device speaking (rule UNAV-05).
FETCHING_INTEGRATIONS = frozenset({"homekit_controller", "esphome"})
# The restart and outage causes still stored on older incidents,
# recognized so they are told plainly rather than credited (rule UP-06).
RECOVERY_CAUSES_RESTART = frozenset(
    {"bridge reconnect", "reboot", "restart", "unclean shutdown"}
)
RECOVERY_CAUSES_SELF = frozenset({RECOVERY_CAUSE_UNOBSERVED})
# An older wording still found in stored incidents. Migrated at load,
# because the composer tests for the current string and would otherwise
# write "revived by a on its own".
LEGACY_CAUSE_UNOBSERVED = "on its own"

# The span the live copy of the brief covers, as opposed to the closed
# brief, which runs brief hour to brief hour and is the one emailed. A
# window measured from the brief time would hold almost nothing for most
# of the day, so the file would read as a quiet house after a full day of
# events; a rolling day fixes that (rule BRIEF-10).
BRIEF_LIVE_WINDOW_SECONDS = 86400.0

# The last bridge state each stack was seen in, kept across a restart so
# an outage that spans one still closes with its real duration. A
# comparison against the previous boot is the one thing memory cannot
# hold (rule UP-04).
DATA_BRIDGE_SEEN = "bridge_seen"
# The broker state, kept across a restart for the same reason (rules
# UP-02, UP-04).
DATA_BROKER_SEEN = "broker_seen"
# A Wi-Fi outage still open, kept across a restart so it is resumed as it
# stood: its start, the trackers that fell in it, its worst count, what
# its down announced and the scan's down mark. Absent while no outage is
# open (rule UP-04).
DATA_WIFI_OUTAGE = "wifi_outage"
WIFI_OUTAGE_SINCE = "since"
WIFI_OUTAGE_DECLARED = "declared"
WIFI_OUTAGE_FALLEN = "fallen"
WIFI_OUTAGE_WORST = "worst"
WIFI_OUTAGE_DEVICES = "devices"
WIFI_OUTAGE_TOLD = "told"
WIFI_OUTAGE_PUSHED = "pushed"
WIFI_OUTAGE_SCAN_DOWN = "scan_down"
# When its recovery began, or None, so a restart does not begin it again.
WIFI_OUTAGE_RECOVERING = "recovering"
BRIDGE_SEEN_STATE = "state"
BRIDGE_SEEN_SINCE = "since"

# The system events log: what happened to the house rather than to a
# device. Every other record here is device-scoped, so when a bridge
# reconnect quiets fifty devices at once the record can only tell it
# through the fifty. These rows sit above the device rows and explain
# them; they never suppress them, because the suppressed evidence is
# what a person goes looking for afterwards (rule STOR-15).
#
# Kept for the retention the person chose for device statistics rather
# than the fourteen days an incident keeps, because how often a house
# loses power is answerable only over seasons (rule STOR-14).
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
# The system clock moved while Device Sentinel ran (rule FRZ-21): the
# detail says how far and which way, the duration is the size.
SYS_CLOCK_RESET = "clock_reset"
# The clocks file was missing or damaged at a start, so each device's
# clock restarted. Told in the brief, not on a Repairs card (rules
# LIST-12, STOR-10).
SYS_CLOCKS_LOST = "clocks_lost"
SYS_INTEGRATION_DOWN = "integration_down"
SYS_INTEGRATION_UP = "integration_up"
SYS_BRIDGE_DOWN = "bridge_down"
SYS_WIFI_DOWN = "wifi_down"
SYS_WIFI_UP = "wifi_up"
# When a Wi-Fi outage starts recovering, and when a recovery stalls and
# the outage stands again. The problem list row shows both, and recording
# them means nobody has to catch them in a screenshot (rule BRIEF-07).
SYS_WIFI_RECOVERING = "wifi_recovering"
SYS_WIFI_RECOVERY_WITHDRAWN = "wifi_recovery_withdrawn"
SYS_BRIDGE_UP = "bridge_up"
# A storm: many devices on one integration reporting at once, most often
# that integration reloading or its hub reconnecting. Recorded, so the
# rule that reclassifies a polling integration survives a restart and an
# integration outage is readable at all: a camera integration reloading
# and dropping its cameras would otherwise leave nothing a person could
# read (rule UP-17).
SYS_STORM_OPEN = "storm_open"
SYS_STORM_CLOSED = "storm_closed"
# Fields the storm rows carry beyond the shared ones.
SYS_DEVICES = "devices"
# The most devices an outage had down at once, written when it ends
# beside SYS_DEVICES, which then holds every device behind the upstream
# (rule UP-11). The figure the outage's problem list row reached at its
# peak, so the brief tells an outage by its worst moment rather than by a
# count taken partway through.
SYS_WORST = "worst"
# The device an act from its page names; absent on every other system
# event.
SYS_DEVICE_ID = "device_id"

# The state saved with a device's outage start when its stack called its
# node dead, so the dead word outlives a restart (rule STACK-05).
NODE_DEAD_STATE = "dead"

# How long a registry rebuild waits after the last one before the next
# (rule WATCH-11). Every device, entity or label change rebuilds Device
# Sentinel's whole view of the registry on Home Assistant's main loop,
# where nothing else runs meanwhile: on a house of 1,500 devices one
# rebuild takes about 45 ms, 100 changes hold the loop about 4.5 s, and
# one press of Enable Last Seen on 1,500 entities holds it over a minute.
# A change rebuilds at once when no rebuild ran in the last this-many
# seconds, and otherwise once when they end, so a burst costs two
# rebuilds and a steady stream at most one per cooldown, about 2% of the
# loop on that house.
REGISTRY_REBUILD_COOLDOWN_SECONDS = 2.0

DATA_STORMS = "storms"
# How long a raw storm row is kept. One hour, not the person's retention:
# the only reader of the raw rows is the polling verdict, which looks
# back STORM_HISTORY_SECONDS, and a real reload is already kept for the
# full retention in the system events log. A longer window would store
# unread hours that can grow to most of the storage file. The daily
# record lives in DATA_STORM_DAYS instead (rule UP-17).
STORM_KEEP_SECONDS = 3600.0
# A storm is explained, and stays out of the day's tally, when it began
# inside an upstream outage or a maintenance window, or within this long
# after one closed or Home Assistant restarted. A whole-house republish
# by zha and battery_notes begins while the coordinator is pulled or
# within seconds of its return, and counting those would advise
# excluding the house's own Zigbee stack (rule UP-17).
STORM_EXPLAINED_SECONDS = 300.0
# The noisy-integration advice: at least this many unexplained storms in
# a day, on at least this many days within the window. A person testing
# hardware makes a bad day; a poller makes a bad week (rule UP-18).
FLOOD_MIN_STORMS = 3
FLOOD_MIN_DAYS = 2
FLOOD_WINDOW_DAYS = 7
# The library: integrations whose devices come and go for reasons that
# are not faults, grouped by that reason, because a category travels
# further than a list of names. Shipped as data so the brief can say
# something useful on the first day, before anything is learned (rule
# REC-03). Router trackers are not here: they have their own exclusion
# (rule MUTE-02) and a line of their own.
LIBRARY_FALSE_ALERTS = "false_alerts"
LIBRARY_NO_DEVICES = "no_devices"
RECOMMENDATION_LIBRARY: dict[str, tuple[str, ...]] = {
    # Devices that go offline by design: phones and computers leave
    # the house, televisions are switched off.
    LIBRARY_FALSE_ALERTS: (
        "ping", "mobile_app",
        "webostv", "androidtv", "samsungtv", "apple_tv",
        "dlna_dmr", "samsung_infrared",
    ),
    # Integrations that add tools rather than hardware.
    LIBRARY_NO_DEVICES: ("spook",),
}

# The daily storm tally: one row per domain per day, written at the fold
# from the day's storms, kept on the retention setting (rule UP-17).
# Count, median seconds between storms, median device count, median
# duration. The noisy-integration advice is its reader (rule UP-18).
DATA_STORM_DAYS = "storm_days"
STORM_DAY_DATE = "day"
STORM_DAY_DOMAIN = "domain"
STORM_DAY_COUNT = "count"
STORM_DAY_INTERVAL = "median_interval"
STORM_DAY_DEVICES = "median_devices"
STORM_DAY_DURATION = "median_duration"
STORM_AT = "at"
STORM_ENTRY = "entry_id"
STORM_DOMAIN = "domain"
STORM_DEVICES = "devices"
STORM_DURATION = "duration"

# The broker going and returning. Its own pair rather than a bridge
# event, because a bridge reader is blind to it: when the broker dies
# nothing delivers the bridge's last will, since the broker is the
# deliverer. A broker outage can take every Zigbee2MQTT device
# unavailable while bridge_state reads running throughout (rule UP-02).
SYS_BROKER_DOWN = "broker_down"
SYS_BROKER_UP = "broker_up"
SYS_PAIRING_OPEN = "pairing_open"
# A person handled one device: re-paired it, reconfigured it, or removed
# it. Its own kind rather than a pairing window, because ZHA keeps no
# window state anywhere, and what it does announce is the device, so the
# wording says what happened (rule FRZ-17).
SYS_DEVICE_HANDLED = "device_handled"
SYS_PAIRING_CLOSED = "pairing_closed"
# A person declared they are working on the hardware, and the declaration
# ended, by expiry or by a second press (rule FRZ-18). Recorded so the
# events log explains the discards between them.
SYS_MAINTENANCE_OPEN = "maintenance_open"
SYS_MAINTENANCE_CLOSED = "maintenance_closed"
SYS_EPOCH_RESET = "epoch_reset"
SYS_OPTIONS_CHANGED = "options_changed"
# A person acted on a device from its page: renamed it, moved it,
# labelled it, switched on its Last Seen, or muted it (rule DASH-09). The
# one system event that names a device, so the brief puts it on that
# device's line.
SYS_DEVICE_PAGE = "device_page"
# A person excluded an integration, or took it back, from its page on the
# dashboard (rule MUTE-03). Its scope is the integration.
SYS_INTEGRATION_PAGE = "integration_page"
# An integration added to the exclusion list the first time a new
# install sees it, its domain in the scope (rule MUTE-02).
SYS_FIRST_SEEN_EXCLUDED = "first_seen_excluded"
# On a house that already exists, the same integration recommended for
# exclusion instead, told once in the brief (rule MUTE-02).
SYS_EXCLUSION_OFFERED = "exclusion_offered"

# A person erased a device's or an integration's learned history from the
# Advanced screen (rule CFG-10). Recorded because it is the one
# destructive act Device Sentinel performs on a person's instruction, and
# because the statistics after it begin from nothing: an event log that
# did not say so would leave a device looking newly discovered for no
# reason. It also keeps attribution correct, since a trimmed device's
# first incidents must not be explained by windows from before the trim.
SYS_TRIMMED = "trimmed"

# Where a trim writes its copy of storage before deleting anything.
# One stamped pair per trim, never overwritten, so a sequence of
# trims cannot bury the state the first one started from, and never
# the nightly last-good pair, which stays exactly what the fold left.
# Old copies are pruned at the fold (rule STOR-13).
TRIM_BACKUP_DIR = "device_sentinel/trim_backups"

# The two pickers. Both are actions wearing an option's clothes: the
# save applies them and then writes them back empty, so a reload
# cannot delete a second time.
CONF_TRIM_INTEGRATIONS = "trim_integrations"
CONF_TRIM_DEVICES = "trim_devices"

# The storage check refused a row a writer made, and dropped it at once,
# because a fault in this version's own writer is a bug the person should
# see and report (rule STOR-06). Older rows of this kind recorded a shape
# fault found at a load or a fold, and may still be in the events log.
SYS_STORAGE_SHAPE = "storage_shape"
# A repair or a restore Device Sentinel performed on its own storage,
# recorded so a silent action cannot exist (rule STOR-12): the detail
# names what was done and what it was done from.
SYS_STORAGE_REPAIR = "storage_repair"

# The Repairs surface (rule REP-01). Each identifier names a problem
# class rather than an occurrence, because one issue per class keeps a
# recurrence from stacking a second row beside the first. They stay the
# same across releases, so an issue that gains a fix flow later attaches
# to the one a person already has open rather than appearing beside it
# as a stranger (rule REP-03).
#
# These are also the translation keys, so a value here has a matching
# entry under "issues" in strings.json and translations/en.json. Repairs
# renders from the translation files alone, so an identifier without one
# shows a person a raw key.
#
# storage_shape is no longer raised: storage is repaired where the fault
# is found (rule STOR-09), and the identifier is only cleared, for
# installs that raised it before. It shares its spelling with the system
# event above and is a separate constant on purpose: one names a row in
# the events log and the other a card in Settings, and a single name read
# by both would make a later rename of either look safe when it is not.
REPAIR_STORAGE_SHAPE = "storage_shape"
# The buttonless notice a completed repair raises (rule REP-02).
REPAIR_STORAGE_REPAIRED = "storage_repaired"
# The first shape check's notice: a container of the wrong kind, repaired before the
# load-time steps could crash on it (rule STOR-05).
REPAIR_CONTAINERS_REPAIRED = "containers_repaired"
REPAIR_ENTITIES_DISABLED = "entities_disabled"
REPAIR_NOTIFY_TARGET_MISSING = "notify_target_missing"
REPAIR_NO_DELIVERY = "no_delivery_configured"
# The restore report (rule REP-08). A repair card rather than a
# persistent notification: it sits in Settings, Repairs where a person
# looks for things that need attention, it survives a restart, and it
# carries a severity. The problem is over by the time it is raised, so it
# is a warning rather than an error, and its only action is to say it has
# been read (rule REP-05).
REPAIR_STORAGE_RESTORED = "storage_restored"
# A retired card for a lost clocks file, which the brief tells now
# (rule LIST-12). Named so an install that still holds one has it
# cleared (rule REP-02).
REPAIR_CLOCKS_RESET = "clocks_reset"
# A retired card for a system clock step, which the brief tells now
# (rule FRZ-21). Named so it can be cleared (rule REP-02).
REPAIR_CLOCK_RESET = "clock_reset"
REPAIRS_ALL = (
    REPAIR_STORAGE_REPAIRED,
    REPAIR_CONTAINERS_REPAIRED,
    REPAIR_NOTIFY_TARGET_MISSING,
    REPAIR_STORAGE_RESTORED,
)
# Retired cards: a card is for what stops Device Sentinel working now, or
# a repair it made (rule REP-01). Switched-off sensors moved to the
# Recommendations tab, a house with no target has its recommendation, and
# the two clock notices are told in the brief. Cleared at every
# evaluation, so an install that held one loses it.
REPAIRS_RETIRED = (
    REPAIR_ENTITIES_DISABLED,
    REPAIR_NO_DELIVERY,
    REPAIR_CLOCKS_RESET,
    REPAIR_CLOCK_RESET,
)

# How far the wall clock may disagree with a clock nobody can set,
# between one minute check and the next, before the difference is a reset
# rather than drift (rule FRZ-21). Time synchronization corrects by
# seconds and is harmless, and so is a step of two minutes; a step of two
# hours backward leaves detection blind for two hours, and forward lists
# healthy devices frozen in one check.
CLOCK_RESET_THRESHOLD_SECONDS = 300.0

# The two moments a Repair is evaluated (rule REP-07): when the startup
# grace closes, and when the daily brief is sent. Not the render tick,
# because an issue that reappears while a person is reading it is worse
# than one raised a few hours late, and none of these conditions changes
# on a timescale a tick would catch. Not the fold either, since a nightly
# reboot after midnight closes grace and clears a card raised hours
# earlier, before anybody was awake to read it. The brief hour is the
# hour a person looks.
REPAIR_MOMENT_GRACE = "grace"
REPAIR_MOMENT_BRIEF = "brief"

# How many things a Repair card names before it starts counting.
# A card is read in a dialog rather than scrolled, and the full list
# is already in the log and the diagnostics.
REPAIR_DETAIL_MAX = 3
# How many devices the retired disabled-entities card named for each
# kind. Nothing reads it now.
REPAIR_NAMED_PER_KIND = 10

# How long the retired no-delivery card let an install go with nowhere
# to send anything. Nothing reads it now; a house with no target has its
# recommendation instead (rule REC-02).
NO_DELIVERY_MIN_DAYS = 7.0

# How long an interruption must last before the daily brief says anything
# about it (rule BRIEF-03). In Short is read rather than scanned, so a
# normal event earns no sentence: the tables below carry every one for
# anyone looking. Five minutes is measured, not chosen. Restarts fall in
# two bands, most under 40 seconds and a nightly reboot between 99 and
# 126 seconds, and bridge outages from reboots run 1 to 4 minutes against
# 17 or more for real ones. Two minutes would name the nightly reboot
# every night; five names only what was abnormal.
BRIEF_NOTEWORTHY_SECONDS = 300.0
# A restart with no clean-stop marker behind it (rule FRZ-20). Distinct
# from SYS_RESTART because the consequences differ: an ordinary restart
# keeps every clock, this one resets all but the devices already in
# trouble. The reset never ships without this row, because a clock that
# jumps with no explanation above it is the silent oddity Device Sentinel
# exists to prevent.
SYS_UNCLEAN_RESTART = "unclean_restart"

# The one-shot backup of both storage files, taken once before a release
# removed something it could not put back. Nothing takes it any more; the
# name survives only so the load can drop its stale marker from storage
# written by an older version. The statistics epoch takes its own copy
# under a suffix naming the epoch (rule STOR-19).
BACKUP_SUFFIX_PREPHASE_C = "prephase-c"
BACKUP_TAKEN_KEY = "backup_taken"

# The last-good copy of the main file (rule STOR-04): before each clean
# save, the file about to be replaced is renamed to it, so it is always
# the most recent clean file. A load that finds damage restores from it
# (rule STOR-08). The clocks file has no last-good copy.
BACKUP_LAST_GOOD_SUFFIX = "last-good"

DATA_EPISODES = "silence_episodes"
EPISODE_KEEP_DAYS = 14
# The long-lived half of the anchor dataset (rule SIG-11): when an
# episode closes, a compact row (who, when, how long, how it ended, and
# the signal snapshot from its open) folds into this series, kept on the
# history retention setting rather than the fourteen-day episode trim
# (rule STOR-14). Episodes explain two weeks; the anchor needs seasons.
DATA_SIGNAL_STRESS = "signal_stress"
# The key the stack probe's lines were once stored under. The lines are
# now appended to stack_probe.md (below), and any stored here are moved
# into the file once, at the first start that finds them (rule STACK-12).
DATA_STACK_PROBE = "stack_probe"
PROBE_WHEN = "when"
PROBE_STACK = "stack"
PROBE_NODE = "node"
PROBE_DEVICE_ID = "device_id"
PROBE_WAS = "was"
PROBE_NOW = "now"
PROBE_DETAIL = "detail"
# Device Sentinel's own view of the node's device at that moment, and
# whether the stack and it agree the device is quiet. Absent from older
# lines (rule STACK-12).
PROBE_SENTINEL = "sentinel"
PROBE_AGREES = "agrees"
# The probe file: lines are appended to stack_probe.md rather than kept
# in storage, and the file rolls to .1, .2 and .3 at this size, the
# oldest dropped. Every stack writes to the one file, so storage stays
# small (rule STACK-12).
PROBE_FILE_MAX_BYTES = 1_000_000
PROBE_FILE_ROLLS = 3
EP_DEVICE_ID = "device_id"
EP_NAME = "name"
EP_SINCE = "since"
EP_BASIS = "basis"
EP_WINDOW = "window"
EP_ENDED = "ended"
EP_AT = "at"
EP_LAG = "lag"
EP_LEARNED = "learned"
# The unavailable duration that tainted this episode, in seconds, or None
# if it was not tainted by an unavailable stretch, the debounce that
# tells a mesh blip from real downtime (rule FRZ-14). Recorded so the
# real spread behind the floor-plus-share figures can be measured.
EP_TAINT_SECONDS = "taint_seconds"
# The device's signal context stamped when the episode opens: the last
# reading, and the day's running mean and deviation so far (rule
# SIG-11). An episode is the one source of rhythm stress, and a later
# signal alert needs the link between signal level and that stress. The
# join has to be captured at the moment the silence begins, because by
# any later analysis the statistics have moved on.
EP_SIGNAL = "signal"
EP_SIG_VALUE = "value"
EP_SIG_MEAN = "mean"
EP_SIG_SD = "sd"
EPISODE_ENDED_RESUMED = "resumed"
EPISODE_ENDED_REBOOT = "intervention (reboot)"
EPISODE_ENDED_RECONNECT = "intervention (bridge reconnect)"
# A storm inside startup grace is the restart itself: every device
# reports at once when Home Assistant returns, which looks exactly
# like a bridge reconnecting. Naming it correctly matters because
# the two are different events with different reach, and the brief
# quotes the cause verbatim.
EPISODE_ENDED_RESTART = "intervention (restart)"

EPISODE_ENDED_UNCLEAN = "intervention (unclean shutdown)"

# A label older rows may carry in the LEARNED cell. An unclean stop
# learns nothing of the silence before it, so nothing writes it now
# (rule FRZ-20).
EPISODE_LEARNED_TRUNCATED = "yes (truncated)"

# Where more than one reason fits a taint, the widest cause wins (rule
# FRZ-14): a device felled by its bridge should say so rather than report
# the symptom it showed. The promotion is resolved when the episode
# closes rather than when the device reports, because the storm that
# names a reconnect releases after five seconds while the devices behind
# it trickle back over the following hour, so deciding at the report
# catches only a few of them. A reboot is absent on purpose, being an
# intervention but not a reason a gap goes unlearned.
TAINT_PROMOTIONS = {
    EPISODE_ENDED_RECONNECT: TAINT_BRIDGE_DOWN,
    EPISODE_ENDED_UNCLEAN: TAINT_UNCLEAN_SHUTDOWN,
}
TODO_JOURNAL_KEEP = 100

# The mute surface. Three selectors, governing every detection family
# present and future. Muting stops judgment, not observation: muted
# devices keep their clocks, statistics, and vouching, so an undo is
# instant and free and the rhythm history carries no holes. A muted label
# mutes the device that carries it; on an entity it mutes nothing (rule
# MUTE-05). There is no entity kind of mute.
#
# The three kinds form a ladder, broadest first: integration, label,
# device. A broader mute supersedes a narrower one and prunes it on save,
# so a pick can never be shadowed by an invisible parent (rule MUTE-04).
#
# There is no area kind. Area membership is set for dashboards, voice
# and automations, so letting it also switch off monitoring would mean a
# room reorganization silently changes what is watched. A label carries
# one meaning and is set for one reason, which is what this surface
# needs.
CONF_MUTED_DEVICES = "muted_devices"
CONF_MUTED_LABELS = "muted_labels"
CONF_MUTED_INTEGRATIONS = "muted_integrations"

# Option keys no longer read by any code path. Cleared once at setup so
# a retired surface cannot linger in diagnostics and read as a live
# setting (rule STOR-19).
#
# excluded_areas is the retired area muting kind, because area
# membership is set for dashboards and automations, so using it to
# switch off monitoring would make reorganizing a room a silent failure.
# The rest are the first notification shapes, replaced when the surface
# was rebuilt: notify_targets became the high and normal priority pair,
# quiet_start and quiet_end became quiet_hours_start and
# quiet_hours_end, reminder_time became daily_reminder_time, and
# high_priority_pierces_quiet had nothing left to decide. The four signal
# keys became constants when the sliders they fed were retired (rule
# SIG-13). Left in stored options, each would read as a live setting in
# every diagnostics download.
DEAD_OPTION_KEYS = (
    "excluded_areas",
    "notify_targets",
    "quiet_start",
    "quiet_end",
    "reminder_time",
    "high_priority_pierces_quiet",
    "signal_lift",
    "signal_margin",
    "signal_red_threshold",
    "signal_sensitivity",
)

# The options migration, numbered so that a person who upgrades one
# release at a time and a person who jumps several run the same code in
# the same order. The entry's minor version records how far it has come;
# each step below moves it one further (rule STOR-19).
#
# Step 2 renames the twelve muting keys from their exclude spellings,
# and step 3 gives the ignore list the word they vacated, so excluding
# discards the record and muting only silences (rule MUTE-01).
# Step 5 writes the persistent card's old default into an install that
# never saved it, so the new default of off reaches new installs only
# (rule NOTE-11).
# Step 6 gives each label and device muted for freeze an unavailable
# mute too, since a freeze mute once covered unavailable, so nothing
# changes on an upgraded house. An integration's freeze mute stays
# freeze only: Home Assistant reports a device unavailable well, and a
# freeze mute hiding it would be a fault (rule MUTE-06).
OPTIONS_MINOR_VERSION = 7

# Step 3's rename: the ignore list takes the exclude spelling.
IGNORE_KEY_RENAMES = {
    "ignored_integrations": "excluded_integrations",
}



# The muting keys, old spelling to new, in the order a person meets
# them on the screens. Read by the migration and by the guard that
# rewrites stored history, so there is one list rather than two.
MUTING_KEY_RENAMES = {
    "excluded_integrations": "muted_integrations",
    "excluded_labels": "muted_labels",
    "excluded_devices": "muted_devices",
    "battery_excluded_integrations": "battery_muted_integrations",
    "battery_excluded_labels": "battery_muted_labels",
    "battery_excluded_devices": "battery_muted_devices",
    "signal_excluded_integrations": "signal_muted_integrations",
    "signal_excluded_labels": "signal_muted_labels",
    "signal_excluded_devices": "signal_muted_devices",
    "freeze_excluded_integrations": "freeze_muted_integrations",
    "freeze_excluded_labels": "freeze_muted_labels",
    "freeze_excluded_devices": "freeze_muted_devices",
}

# Every retired option name, both steps together, read by the pass
# that rewrites stored history and by the guard that keeps the old
# spellings out of the source. One list, so a later step cannot be
# added to the migration and forgotten by the two things that have to
# follow it.
OPTION_KEY_RENAMES = {**MUTING_KEY_RENAMES, **IGNORE_KEY_RENAMES}

# The same renames, each stamped with the release that made it, for the
# pass that rewrites stored history.
#
# A flat map cannot do this job. `excluded_integrations` was first the
# muting key and later the ignore key, so the same string means two
# different settings depending on when the row was written. Read flat, a
# row written today would be rewritten tomorrow into a setting the person
# never touched.
#
# What tells them apart is the version stamp the storage file already
# carries: a rename is applied only to a file last written before the
# release that made it, and never to one written by that release or
# later. Nothing new is stored to make this work (rule STOR-19).
OPTION_KEY_RENAME_STEPS = (
    ((0, 16, 18), MUTING_KEY_RENAMES),
    ((0, 16, 19), IGNORE_KEY_RENAMES),
)


SENTINEL_TYPE_PROBLEM_LIST = "problem_list"

# Battery-only muting. Scoped on top of the global mute list: a device
# here is muted from battery judgment only, and keeps its freeze,
# unavailability and signal watching. Keyed at the device level so a
# re-election (percentage entity vanishing, binary elected instead)
# cannot dodge it. The integration list makes "everything mobile_app"
# one tick, covering phones present and future. No entity kind here
# for the same re-election reason (rule BAT-04).
CONF_BATTERY_MUTED_DEVICES = "battery_muted_devices"
CONF_BATTERY_MUTED_INTEGRATIONS = "battery_muted_integrations"
CONF_BATTERY_MUTED_LABELS = "battery_muted_labels"


# The documentation links the options screens append to their step
# descriptions. They live here rather than inside the translation
# files because hassfest rejects a literal URL in strings.json and
# directs integrations to pass links in as description placeholders,
# which the flow supplies at render time. One per page a screen links
# to, and each screen's link names the page it opens (rule CFG-03); a
# test checks each is a published wiki page (rule REL-14).
WIKI_BASE_URL = "https://github.com/TheThinkingHome/device_sentinel/wiki"
# Each release's notes, by its tag, which is the version itself. The
# dashboard's foot names the version running and links here (rule
# DASH-15).
RELEASE_NOTES_URL = "https://github.com/TheThinkingHome/device_sentinel/releases/tag/{version}"


def _wiki_link(page: str | None = None) -> str:
    """Return the URL of one wiki page.

    Page names are the wiki's own titles with spaces as hyphens, which is
    how GitHub builds a wiki URL from a page title. A name that does not
    match a real page yields a link to a page-not-found screen rather than
    an error, so these are checked against the live wiki rather than
    trusted.

    The URL only, so the link text lives in the strings where a translator
    can reach it, each screen names the page it opens, and no screen nests
    one link inside its own words (rule CFG-03).
    """
    return f"{WIKI_BASE_URL}/{page}" if page else WIKI_BASE_URL


WIKI_LINK_HOME = _wiki_link()
WIKI_LINK_NOTIFICATIONS = _wiki_link("Notifications-and-Daily-Brief")
WIKI_LINK_ADVANCED = _wiki_link("Advanced")
WIKI_LINK_WIFI = _wiki_link("WiFi")
WIKI_LINK_EXTENDED = _wiki_link("Extended-Diagnostics")
WIKI_LINK_EXCLUSIONS = _wiki_link("Exclusions-and-Muting")
WIKI_LINK_BATTERY = _wiki_link("Low-Battery")
WIKI_LINK_SIGNAL = _wiki_link("Signal-Strength")
WIKI_LINK_FREEZE = _wiki_link("Freeze-Detection")
WIKI_LINK_REPORTS = _wiki_link("The-Diagnostic-Reports")
WIKI_LINK_REPAIRS = _wiki_link("Repairs")


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
DEAD_ENTITY_SENTINEL_TYPES: tuple[str, ...] = (
    # The three retired Enable buttons (rule REC-05). The unique id is the
    # entry id and the button's key, so Regenerate Reports and Maintenance
    # Mode, which share the platform, are untouched.
    "enable_signal_entities",
    "enable_last_seen_entities",
    "enable_battery_entities",
)


# The longest device name any surface shows (rule DEV-03). No real name
# measured reaches it; see naming._fit.
NAME_LENGTH_MAX = 60


# Model groups (rule DEV-14). Devices of the same maker, model and
# hardware version are read as a group, so one device's behavior can be
# told from its model's. Recorded for the diagnostics download: no
# verdict, list, push, screen or bus event reads the groups yet. The
# firmware history they draw on is read elsewhere: an update restarts
# the Log-Normal Percentile's count (rule FRZ-05) and has the battery
# scale measured again (rule BAT-02).
#
# The window each device's figures are read over: the battery rate is the
# same 30-day rate Battery Trends shows, and signal is judged over thirty
# days (rule SIG-06).
MODEL_GROUP_WINDOW_DAYS = 30
# Words the section writes where Home Assistant gives no value.
MODEL_GROUP_NOT_GIVEN = "not given"


# Battery trends by the week (rule BAT-11). A seven-day slope calls a
# cell falling at 0.05 points a day, smaller than the half-point steps
# most cells report in, so a cell wobbling by half a point would read as
# falling and as accelerating, and cells near full would be listed as
# "over a year" while going nowhere.
#
# A week's average level is the measure instead: the ups and downs of a
# wobble cancel inside it. A cell is falling when its last seven days
# average at least a point below the seven before.
BATTERY_WEEK_DAYS = 7
BATTERY_WEEKS_SHOWN = 5
BATTERY_FALLING_WEEK_DROP = 1.0
# And, once four weeks are held, the six-week fitted line must be going
# down at least this many points a week. One week can dip a point by
# chance on a cell that flips between two levels, such as 84 and 80.5 by
# turns, so a single week is not trusted; the fitted line is the longer
# look (rule BAT-11).
BATTERY_FALLING_MIN_PACE = 0.5
# Six weeks of history are fitted, with a straight line and with a
# curve, for the falling test, the accelerating test and the time
# left, and nothing is fitted until four weeks of them were heard.
BATTERY_FIT_WINDOW_DAYS = 42
BATTERY_FIT_MIN_DAYS = 28
# One test for accelerating (rule BAT-12): the same six-week curve the
# time left reads (rule BAT-13), so the word, the sentence and the range
# agree.
#
# The curve passes when it bends down and fits clearly better than the
# line (an F of BATTERY_CURVE_MIN_F or more); it is still falling today,
# with no floor on the pace; and the heard days among the newest
# BATTERY_CURVE_RECENT_DAYS hold at least BATTERY_CURVE_MIN_FALLS
# day-to-day drops, so one step down is not a curve. Without the drops,
# steady cells read accelerating on hundreds of days. Measured against
# 28, 56 and 84 days, 28 missed a real bend and called steady cells, and
# the longer ones only came later. The time left uses this same test to
# choose the curve.
BATTERY_CURVE_MIN_F = 10.0
BATTERY_CURVE_RECENT_DAYS = 14
BATTERY_CURVE_MIN_FALLS = 3
# The curve must also fit better by a measurable amount, at least one
# square point over the six weeks. A perfectly straight fall leaves the
# curve no error at all, so the F test would divide by nothing and the
# straight line would read accelerating. The smallest gain on any real
# accelerating day is far above this floor, so it changes no real call
# (rule BAT-12).
BATTERY_CURVE_MIN_GAIN = 1.0
READING_ACCELERATING = "accelerating"
READING_FALLING = "falling"


# Firmware history. A version is recorded only once it has held this
# long, counted from when it first appeared and read on the minute tick
# after the startup grace (rule DEV-15). At a restart, Home Assistant's
# registry can hold a stale value while the MQTT devices come back up, so
# a device records an older version and its current one again within the
# same second. Waiting on the tick rather than the midnight fold means a
# house that restarts before midnight, or reboots across it, still
# records an update. A flicker lasts under a second; a real update or
# downgrade holds.
FIRMWARE_HOLD_SECONDS = 600
# A recorded version replaced within this long by the version before it
# is a flicker, removed from older histories (rule DEV-15).
FIRMWARE_FLICKER_SECONDS = 600


# How a device connects, from its integration's own declaration (its
# manifest's iot_class), in the device page's words (rule DEV-13). A
# device's class is its integration's: a Tuya device paired through
# Zigbee2MQTT is local, as it should be.
CONNECTS_WORDS = {
    "local_push": "On your network. It reports changes as they happen.",
    "local_polling": "On your network. Home Assistant asks it for updates at set times.",
    "cloud_push": "Through the maker's cloud. It stops reporting if their servers or your internet go down.",
    "cloud_polling": (
        "Through the maker's cloud, checked at set times. It stops reporting "
        "if their servers or your internet go down."
    ),
    "assumed_state": "It can't report back, so Home Assistant shows what it last told it.",
    "calculated": "Worked out by Home Assistant from other readings.",
}
