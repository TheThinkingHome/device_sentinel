# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: const.py, Version: 0.18.2 (2026-08-26)

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
# The MQTT broker itself, which sits underneath every MQTT stack and
# belongs to none of them. Mosquitto publishes its uptime on a fixed
# interval, ten seconds by default, as a payload reading like
# "12355 seconds". Home Assistant exposes no broker entity at all, so
# this topic is the only source. Measured on the reference broker on
# 2026-08-06: 2,363 intervals, median 9.997s, maximum 10.350s,
# standard deviation 0.082s (ruling #224).
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
# seconds, so it drifts a little even when nothing happens. Measured
# across 2,458 intervals of the reference recording: the drift maxes
# at 2.95 seconds and its p99.9 is 0.34, while the three genuine
# restarts in the same recording moved the start by 564 seconds at
# the very least. Thirty sits two orders of magnitude clear of the
# noise. The cost is that a broker restarting twice inside thirty
# seconds reports one restart, which is the right trade.
BROKER_START_TOLERANCE_SECONDS = 30.0
# The largest uptime worth believing, a hundred years in seconds. A
# payload beyond it is not a broker that has been up that long, and
# an infinity would put the computed start before the epoch
# (ruling #231).
BROKER_UPTIME_CEILING = 3_155_760_000.0
BROKER_RUNNING = "running"
BROKER_DOWN = "down"
BROKER_UNKNOWN = "unknown"
BROKER_STATES = [BROKER_RUNNING, BROKER_DOWN, BROKER_UNKNOWN]

# The name the broker carries when it is the upstream a device is
# reported under (ruling #264). Not a stack: no bridge owns it, and
# it outranks every bridge, because a broker that is down takes them
# all with it.
# What a stack is called when a person reads it (ruling #266). The
# internal key is the domain the stacks module uses; a to-do row
# saying "z2m: upstream" is accurate and tells nobody anything.
STACK_DISPLAY_NAMES = {
    "z2m": "Zigbee2MQTT",
    "zha": "ZHA",
    "zwave_js": "Z-Wave",
    "matter": "Matter",
}

BROKER_LABEL = "MQTT broker"

# How long an upstream outage is allowed to settle before it is
# reported (ruling #265). Devices do not fall in one tick: Home
# Assistant marks each entity unavailable as it notices, so a count
# taken immediately is wrong and a message per tick is a burst. The
# same window is used on the way back, so a device that did not
# return is named once the others have.
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
# bridge/devices is the roll of what actually exists, retained. It
# carries the IEEE address Home Assistant knows a device by beside
# the friendly name the availability topics are keyed on, which is
# the only join between the two, and it is what rejects an
# availability topic naming a group or a device that is gone.
# The availability subscription is one level wildcard, so a friendly
# name containing a slash publishes deeper and is not seen; Z2M
# permits it and nothing on the reference fleet does it
# (ruling #221).
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
# The learned-column value for a gap discarded because the device
# recovered inside a declared maintenance window (rulings #225 and #238).
# Its own word for the same reason pairing has one: the episode report
# should say which intervention explained the discard.
LEARNED_MAINTENANCE = "no (maintenance)"
# A gap that spans a disabling is administrative, not the device's
# own rhythm (ruling #257). Same class as pairing and maintenance:
# a hand caused the silence, so the gap is refused and retracted.
LEARNED_DISABLED = "no (disabled)"

# The maintenance window (rulings #225 and #238): a button-declared span in
# which any recovery is attributed to the person's hands rather than
# learned. Short by design; a person fixing hardware is at the device
# for minutes, and a long default would swallow genuine
# self-recoveries all afternoon.
CONF_MAINTENANCE_MINUTES = "maintenance_minutes"
DEFAULT_MAINTENANCE_MINUTES = 10
MAINTENANCE_MINUTES_MIN = 5
MAINTENANCE_MINUTES_MAX = 60
MAINTENANCE_MINUTES_STEP = 5

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

# Every value the reason field may hold besides False, named here so
# the shape check can accept exactly these and nothing else, and so a
# fifth reason added later has one place to join rather than two that
# must be kept in step. Constants rather than literals, for the reason
# EPOCH_KEPT was corrected (ruling #207): a value changed in one place
# and spelled by hand in another parts silently.
TAINT_REASONS = (
    TAINT_UNAVAILABLE,
    TAINT_UNKNOWN,
    TAINT_BRIDGE_DOWN,
    TAINT_UNCLEAN_SHUTDOWN,
)

# The sensinel_type stem for a bridge sensor; the stack is appended so
# each stack's sensor has a stable unique id.
SENTINEL_TYPE_BRIDGE = "bridge"
SENTINEL_TYPE_BROKER = "broker"
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
DEV_SET_ASIDE_SINCE = "set_aside_since"
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
# cadence, so storm muting stops applying to it. Provisional per the
# soak, learned from the tplink_router finding (920 storms overnight).
STORM_EXEMPT_PER_HOUR = 10
STORM_HISTORY_SECONDS = 3600

# How long a resolved problem stays reopenable, in seconds. A device
# whose reading crosses a threshold back and forth writes a pair of
# incident rows every crossing, and the recorder had nothing to stop
# it until ruling #318: the first external fleet produced 3,637 rows
# for one propane sensor in five days, 94 percent of its whole
# incident history.
#
# Sixty seconds by measurement rather than by taste. Replayed over
# both fleets' stored incidents, sixty leaves the reference fleet's
# 509 rows untouched and turns the external fleet's 3,866 into 614.
# Past two minutes it begins collapsing real recoveries on a healthy
# fleet, which is the failure this must never have. Zero switches it
# off.
CONF_INCIDENT_SETTLE = "incident_settle_seconds"
DEFAULT_INCIDENT_SETTLE_SECONDS = 60
INCIDENT_SETTLE_SECONDS_MIN = 0
INCIDENT_SETTLE_SECONDS_MAX = 120

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

# The version that last ran, stored so a start can tell an upgrade
# from an ordinary restart (ruling #303). It lives beside the epoch
# marker at the top of the file rather than inside a device record,
# so it is outside everything the shape check reads and costs the
# record schema nothing. Absent on a file written by an older
# version, which reads as an upgrade, which it is.
DATA_LAST_VERSION = "last_version"

# The Data sensors read each area's depth from its own series
# (ruling #258), so nothing here names a version and nothing has to
# be bumped when a release changes what is recorded: a new series is
# empty, which makes it the shortest, which resets the area on its
# own. DATA_SERIES_STAMPS survives only as the key an older version
# wrote, pruned from storage on the first load.
DATA_SERIES_STAMPS = "series_stamps"

# One-shot marker for the signal day repair of ruling #256. Carries
# the version that ran it, so the repair happens once and a later
# restart cannot drop another day.
DATA_SIGNAL_DAY_REPAIR = "signal_day_repair"
SIGNAL_DAY_REPAIR_MARK = "0.12.21"

# The mean and deviation changed from counting readings to weighing
# minutes (ruling #259), so their recorded days are not comparable
# across the change. The series are cleared once, under this marker,
# rather than left mixed, because no later analysis could separate
# the two halves.
DATA_SIGNAL_WEIGHTING = "signal_weighting"
# Bumped once (ruling #261): 0.13.5 cleared the recorded days but
# left the day already accumulating, which had been built by counting
# readings and carried on by counting minutes. An install that had
# already passed the first marker would have folded that hybrid row,
# so the marker changes value to run the clearing once more, this
# time taking the day in progress with it.
SIGNAL_WEIGHTING_MARK = "minutes-2"
# Why a device is set aside: recorded rather than inferred, because
# the classification file has to say which, and because only one of
# the three can end (ruling #257).
SET_ASIDE_SERVICE = "service"
SET_ASIDE_DISABLED = "disabled"
SET_ASIDE_NO_ENTITIES = "no entities"
SET_ASIDE_EXCLUDED = "excluded"

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
)

AREA_FREEZE = "freeze"
AREA_BATTERY = "battery"
AREA_SIGNAL = "signal"

# What each area counts toward, and the words at the end of the
# count. Freeze and signal arm at seven days and mature later: the
# freeze rhythm judges on the most recent fourteen (DAILY_MAX_KEEP),
# the signal floor on the most recent thirty (SIGNAL_DAYS_KEEP, the
# widening of ruling #196). Battery's slope reads a fixed seven, and
# has no second milestone, so it is a two-phase count.
DATA_STATE_ARMED = "Armed"
DATA_STATE_LEARNED = "Learned"
DATA_STATE_TRACKING = "Tracking"

SENTINEL_TYPE_DATA_FREEZE = "data_freeze"
SENTINEL_TYPE_DATA_BATTERY = "data_battery"
SENTINEL_TYPE_DATA_SIGNAL = "data_signal"

# Per-device signal fields (linkquality/RSSI, gather-first).
DEV_SIGNAL_VALUE = "signal_value"
DEV_SIGNAL_TODAY_MIN = "signal_today_min"
# The dwell record is erased (ruling #322): the daily minimum, the
# daily line, the dwell percentage, and the two live below-line
# clocks. The floor reads P5 (ruling #323) and the rail alert reads
# the rail column beside the reading count (ruling #322). The key
# strings survive only so the load sweep can remove them from
# stored files, including inside signal_alt blocks.
RETIRED_SIGNAL_KEYS = (
    "signal_daily_min",
    "signal_daily_line",
    "signal_dwell_daily_pct",
    "signal_below_since",
    "signal_below_today_seconds",
)

# How far under the mean the dwell line may sit at the very highest,
# in the device's own standard deviations. A margin taken as a
# percentage of the floor is the largest number of points exactly
# where there is the least room for it, because LQI stops at 255, so
# a device whose floor is already near that ceiling gets a margin
# wide enough to cover its whole operating range and reads as below
# its own line all day while running a strong link. Half a deviation
# under the mean is where the bound has to sit: the fault is a line
# crossing into the readings a healthy device makes every day, so it
# must bite before that rather than long after. A constant and not a
# setting, because it is a guard rather than a preference (ruling
# #193).
GOOD_STATE_CEILING_SD = 0.5
# The working band of each scale (ruling #250): where a link actually
# dies and where it is actually perfect. A Zigbee radio's receiver
# sensitivity sits near -95 to -100 dBm and links degrade below
# about -85, which maps to roughly LQI 40 to 60 on the common
# coordinator scales; and no working link reports RSSI near zero, a
# device beside the coordinator reads about -20. The margin is a
# percentage of the distance from perfect, so it is widest exactly
# at the dropout point, holds that width through the dropout zone
# below it (everything down there is hazard already), and dies to
# nothing at perfect. The old margin was a percentage of the floor
# itself, which measured distance from zero on both scales, and zero
# is dead on LQI and perfect on RSSI: one formula, two opposite
# behaviours, widest for the strongest LQI links on the fleet.
SIGNAL_LQI_DEAD = 50.0
SIGNAL_LQI_PERFECT = 255.0
SIGNAL_RSSI_DEAD = -90.0
SIGNAL_RSSI_PERFECT = -20.0
# The ceiling's minimum clearance below the mean, per scale (ruling #244).
# Half a deviation is the guard on a normal device, but on a device
# whose whole operating range spans a step or two (the motion-blind
# family holds an RSSI inside 2 dB for days), half a deviation is a
# fraction of one quantization step and the ceiling lands inside the
# readings a healthy device makes every hour. On 7 August that read
# three healthy blinds as 52 to 95 percent dwell in a single day. The
# clearance is one comfortable step outside the noise: two LQI
# quantization steps, or 3 dB of RSSI. On any device whose deviation
# is ordinary, half a deviation is larger and nothing changes.
SIGNAL_CEILING_CLEARANCE_LQI = 8.0
SIGNAL_CEILING_CLEARANCE_RSSI = 3.0

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
DEV_SIGNAL_SUM = "signal_sum"  # retired by #254; read once for migration
DEV_SIGNAL_SUM_SQ = "signal_sum_sq"  # retired by #254; read once for migration
DEV_SIGNAL_COUNT = "signal_count"
# The day's reading count, kept apart from DEV_SIGNAL_COUNT now that
# the latter counts minutes rather than reports (ruling #259). The
# daily count series is deliberately a count of reports: it answers
# how often a device spoke, which no time-weighted figure can.
DEV_SIGNAL_READS = "signal_reads"
# Welford accumulators (ruling #254): the day's running mean and its
# sum of squared distances from that mean (M2). The naive sum and
# sum-of-squares pair subtracts two large near-equal numbers at the
# fold, the textbook catastrophic-cancellation site, and can round a
# near-constant device to a negative variance. Welford carries the
# spread directly and cannot. Same mean, same deviation, stably.
DEV_SIGNAL_MEAN_RUN = "signal_mean_run"
DEV_SIGNAL_M2 = "signal_m2"
# Streaming percentile states (ruling #253): P-Square estimators for
# the day's time-weighted 5th percentile and median. Each state is
# eleven numbers, fed one minute of held value at a time, so a value
# must persist for about 72 cumulative minutes before it can be the
# day's sustained low. The daily minimum stays recorded beside them;
# the fleet measured 47 percent of device-days carrying a minimum
# the day itself disowns (three deviations under its own mean), and
# these series exist so the floor's input can be re-ruled on record.
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
# Three more daily series beside the mean and deviation (ruling #245),
# recorded ahead of the #172 successor on the record-first principle:
# how many real readings the day held (a 6-reading day and a
# 600-reading day should not weigh the same later), the danger line
# that was in effect (stored dwell is unreadable later without the
# line it was measured against), and how many rail readings arrived
# (a day of thin real statistics should say why).
DEV_SIGNAL_DAILY_COUNT = "signal_daily_count"
DEV_SIGNAL_DAILY_RAIL = "signal_daily_rail"
DEV_SIGNAL_RAIL_COUNT = "signal_rail_count"
# last_change is when the signal value last actually moved. Kept for
# the dwell timer and diagnostics; the rail detector reads the daily
# low series, not this.
DEV_SIGNAL_LAST_CHANGE = "signal_last_change"

# The two scales a link is measured on, and where the second one
# lives (rulings #282, #284, #285, #286).
#
# RSSI is the radio's own power reading in dBm and is negative at any
# Zigbee receiver; LQI is the mesh's quality score on 0 to 255. A
# device that publishes both had them landing in one series until
# 0.15.6: one ZHA device spanned -66 to 247 inside two hours, and
# every figure drawn from such a series is void.
#
# Scale is decided by the sign of the reading rather than by a label.
# Across the two fleets that have sent data, 4,209 negative readings
# and 4,040 non-negative, with no overlap: positives run 0 to 255 and
# negatives -106 to -1. Zero is a valid LQI meaning the worst the
# scale can express and is not a plausible RSSI, so it belongs with
# LQI. The rails below have told the scales apart by value since
# signal shipped.
SIGNAL_SCALE_RSSI = "rssi"
SIGNAL_SCALE_LQI = "lqi"
DEV_SIGNAL_SCALE = "signal_scale"

# The second scale, when a device has one: None, or a block holding
# the same recording fields under the same names. One key rather than
# a fixed set of extra fields, because JSON stores field names and an
# empty block of twenty-one of them costs 531 bytes on every record
# in every fleet, most of which will never have a second scale. Null
# costs 20 (ruling #286).
#
# The names inside are the record's own names rather than short
# forms. Short names measured 8 KB smaller on a 276-device ZHA fleet
# and would need a map between two spellings of one field, which is
# the object #277 refused: a second copy that parts from the first
# the day somebody adds a field and updates only one of them.
DEV_SIGNAL_ALT = "signal_alt"

# What the alternate block carries: everything recorded, and nothing
# judged. The line, the dwell timer and the below-the-line clock stay
# on the primary alone, because #285 records both scales and judges
# only one until the data says which deserves it.
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
    DEV_SIGNAL_LAST_CHANGE,
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

# Units that mean the entity is not a signal measurement at all
# (ruling #283). Tasmota reports RSSI as a 0 to 100 quality figure
# and Signal as the dBm, inverted from every other vendor, so on a
# Tasmota device an entity called RSSI carries a percentage and
# reaches the recognizer through the name term above. It is derived
# rather than measured: on the first ZHA fleet to send data, all
# seven Tasmota devices were consistent with 2 x (dBm + 100) clamped
# to 0 and 100, one of them sitting exactly on the clamp at -50 dBm
# against 100 percent. It restates a number already recorded.
#
# The refusal is by unit and not by vendor, because #248 named
# entities by what somebody had called them and was wrong in both
# directions. Home Assistant permits only dB and dBm for
# device_class signal_strength, so an entity carrying that class can
# never be a percentage and is never reached by this test.
#
# It is also deliberately narrow. A rule that refused every unit it
# did not recognize was rejected: nothing in any diagnostics carries
# the unit of a Zigbee2MQTT linkquality entity, and a rule written
# against a guess would have taken signal away from 74 devices on
# the reference fleet if the guess were wrong. Refusing one unit
# fails toward recording, which is visible and fixable, rather than
# toward silence.
SIGNAL_REFUSED_UNITS = ("%", "percent", "percentage")
# The foreign-measurement terms of ruling #248 were deleted here. They
# named entities by what somebody had called them, which caught an
# ESPHome node's own RSSI because the sensor is called WiFi Signal and
# missed a phone's cellular radio because the sensor is not called
# cellular. Every entity they existed to refuse arrives on an
# integration the exclude list now refuses whole, so nothing reaches
# either recognizer to be filtered by name.

# Rolling statistics: daily maxima kept per device. 14 days records
# more than the rolling window will need, so the window-length
# tunable can be settled from soak data without re-collecting.
DAILY_MAX_KEEP = 14
# DAILY_MAX_KEEP above is the freeze judgment window: the rhythm is
# computed from the most recent fourteen days however many are
# stored. The signal floor reads thirty (SIGNAL_DAYS_KEEP): it was
# fourteen when this note was written and ruling #196 widened it,
# and the note went stale until the Data sensors of #255 made every
# window a published number. It is
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
FREEZE_CATEGORY_NEVER_REPORTED = "never_reported"
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
# The backup's story on the Status sensor (ruling #341).
ATTR_LAST_GOOD_TAKEN = "last_good_taken"
ATTR_LAST_GOOD_AGE_DAYS = "last_good_age_days"
ATTR_REPAIRS_AT_LOAD = "repairs_at_load"
ATTR_SHAPE_FAULTS = "shape_faults"

SENTINEL_TYPE_STATUS = "status"
SENTINEL_TYPE_COVERAGE = "coverage"
SENTINEL_TYPE_LEARNING = "learning_progress"
SENTINEL_TYPE_CLASSIFICATION = "classification"
SENTINEL_TYPE_CLOCK_SOURCE = "clock_source"
SENTINEL_TYPE_MAINTENANCE = "maintenance"

# The awaiting-enable counts on Status (ruling #237): one exact number
# per enable button, no entity lists, so a dashboard can show each
# button exactly while there is something for it to do.
ATTR_AWAITING_SIGNAL = "signal_awaiting_enable"
ATTR_AWAITING_LAST_SEEN = "last_seen_awaiting_enable"
ATTR_AWAITING_BATTERY = "battery_awaiting_enable"

# Whether Zigbee2MQTT's availability feature is on, read from bridge
# info and surfaced on the bridge sensor (ruling #236). Reported, never
# written: enabling it is Zigbee2MQTT's configuration, not this
# integration's.
ATTR_BRIDGE_AVAILABILITY = "availability_enabled"

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
# The signal report. Under www rather than the reports folder,
# because www is what Home Assistant serves at /local, and a dashboard
# Webpage card pointed at /local/device_sentinel/signal_report.html is
# the whole reason the file is HTML.
REPORT_WWW_DIR = "www/device_sentinel"
# The parent Home Assistant looks for, and the address our folder is
# reachable at. Home Assistant registers /local only where the parent
# already existed when the frontend set up, and it checks that once,
# so on a system with no www folder the first boot after installing
# leaves these files unreachable. Where that is the case the
# integration registers this one folder for itself (ruling #186).
REPORT_WWW_PARENT = "www"
REPORT_WWW_URL = "/local/device_sentinel"
REPORT_SIGNAL = "signal_report.html"
REPORT_SIGNAL_PREFIX = "signal_report_"
# The HTML brief. What a person reads lives under www, where a
# browser and a dashboard card can render it, and what a developer
# reads stays under config (ruling #178). One rendering serves the
# dated record, the undated current file, and the emailed body, so
# the three cannot drift (ruling #179).
REPORT_BRIEF_HTML = "daily_brief.html"
REPORT_SIGNAL_URL = "/local/device_sentinel/signal_report.html"
# The battery report. A third page for a person, beside the brief and
# the dwell chart, answering what a threshold alone cannot: not which
# cells are low, but which are going to be (ruling #194). Its dated
# copy is named for the day it was written, and under the same rule
# as the chart (#190): its headline figures are the levels now, so
# the day it covers and the day it is written are the same day.
REPORT_BATTERY_HTML = "battery_report.html"
REPORT_BATTERY_PREFIX = "battery_report_"
REPORT_BATTERY_URL = "/local/device_sentinel/battery_report.html"

# How many recent daily levels the fall is measured over. Seven is
# the shortest span that survives a single bad pair: the cell that
# proved this reported a ten point drop and an eight and a half point
# rebound on consecutive days, which is a coin cell sagging under
# load and recovering, not a battery that refilled. The slope is a
# median of every pairwise slope in the window rather than a fit, so
# both of those readings land in the tails and neither moves the
# answer (ruling #194).
BATTERY_SLOPE_DAYS = 7
# Below this the device is called flat rather than falling. A cell
# reporting in half point steps produces a slope of a few hundredths
# from rounding alone, and projecting a lifetime from rounding gives
# numbers in the thousands of days.
BATTERY_FALLING_SLOPE = -0.05
# A percentage that cannot be one. Seen on the reference fleet: an
# MQTT device reporting around 196 every day, which is a raw scale
# rather than a percentage. It can never cross a low threshold and it
# distorts any summary of the bank, so it is named as unreadable
# instead of counted as very healthy.
BATTERY_READABLE_MAX = 100.0
# How near the end a cell has to be before the daily brief names it.
# The report lists every cell that is measurably falling, which on a
# real fleet is a third of it, most of them a season away. The brief
# is read at an hour a person chose and has to be worth that hour, so
# it names only what is close (ruling #195). Deliberately shorter
# than the report's own reading, because a page a person opened is a
# different thing from a page that arrives.
# The person's answer to how far ahead a falling cell is called out.
# Seven to thirty, because under a week is too late to act and past a
# month the projection is guesswork (ruling #197).
CONF_BATTERY_DAYS = "battery_days_till_empty"
DEFAULT_BATTERY_DAYS = 30
BATTERY_DAYS_MIN = 7
BATTERY_DAYS_MAX = 30

# How time left is said, rather than printed as a number. The
# projection moved from twelve days to seven in one afternoon on the
# cell that proved it, roughly forty percent; the same relative error
# on a device reading 1122 days puts the truth anywhere between 670
# and 1570, so printing 1122 claims a precision the arithmetic does
# not have. Precision degrades with distance, which is how the error
# behaves, and the words are all a person needs (ruling #197).
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
# The range both doors offer. Written twice and shared nowhere until
# 0.11.8: the options dialog and the dashboard slider each carried
# their own copy, so the one setting could have been offered with two
# different ranges the moment either was edited. Every range added
# since this one has had a constant; this one predates the habit
# (ruling #205).
LOW_THRESHOLD_MIN = 1
LOW_THRESHOLD_MAX = 99
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

# The series each area records, published in the Data sensors so a
# reset explains itself: a person seeing zero complete days can read
# which series the set now holds. Named here, below the fields they
# name, and read nowhere else.
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

# Step 6 freeze verdict, stored so it survives a reboot and so the
# sensor feed can compare and refresh only when it flips, not on
# every reading. The category is one of the
# three down states, or None when the device is alive. frozen_since
# is the UTC timestamp the verdict began, for the report and for
# "how long".
DEV_FROZEN_CATEGORY = "frozen_category"
DEV_FROZEN_SINCE = "frozen_since"


# What a statistics epoch keeps. The wipe is everything else, taken
# from the record schema, so a field added later is wiped by default
# and there is no second list to forget (ruling #204).
#
# Seven fields are wiped: the rolling maxima, today's maximum, the
# event count, the taint flag, the freeze verdict with its stamp, and
# the daily dwell. The rhythm, the conclusion drawn from it, and the
# one series that is a verdict rather than a measurement.
#
# Dwell is the exception that had to be argued. It looks like the
# signal statistics beside it and behaves like the freeze verdict: it
# accrues in real time against the line as that line stands at each
# second, then rolls into a daily figure. So a change to the margin
# (#171), the ceiling (#193) or the window (#196) leaves every figure
# already recorded measured against a line that no longer exists, and
# it cannot be recomputed, because the readings behind it are gone.
# It was in the kept set on the first cut of this list, which would
# have meant an epoch bump sparing the single series most likely to
# need clearing.
#
# Everything else is kept, and the reason is that nothing is
# recoverable. There is no raw layer beneath these records: readings
# are folded into a daily figure as they arrive and the readings
# themselves are never stored, so a wiped series cannot be rebuilt
# from anything. The signal statistics are what the Bayesian
# successor is accumulating (#172) and what the good-state ceiling
# already judges against (#193); the battery series is a ninety-day
# soak that cannot be re-collected faster than it was collected. A
# rhythm rule changing is no reason to destroy either.
# Named by constant rather than by literal, as CLOCK_FIELDS is. The
# first cut of this tuple spelled the stored keys out as strings,
# which works and is proven by the partition test, but it was the
# only place in the package naming a stored field by literal: a
# constant's value changing would have moved CLOCK_FIELDS and left
# this behind, and the failure would have been a field quietly
# surviving a wipe (ruling #207).
# The second scale's soak is kept for the same reason the first
# one's is: an epoch reset drops learned rhythm and keeps signal
# history, and keeping one scale's while destroying the other's would
# leave a device half remembered. The scale label rides with it,
# because a block whose partner had been forgotten would let the next
# reading put the same scale on both sides of the record.
EPOCH_KEPT = (
    DEV_SIGNAL_SCALE,
    DEV_SIGNAL_ALT,
    DEV_SIGNAL_READS,
    DEV_SET_ASIDE_SINCE,
    DEV_LAST_ACTIVITY,
    DEV_FIRST_OBSERVED,
    DEV_SIGNAL_VALUE,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_LAST_CHANGE,
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

# The legacy tail of the hot set (#254): the naive accumulators are
# read once at upgrade from the clocks file, shed at the first fold,
# and never written for a fresh record. They stay listed in
# CLOCK_FIELDS so the merge still carries an upgraded install's
# partial day; this subset names them so tests can expect their
# absence from records born after the swap.
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
    DEV_SIGNAL_LAST_CHANGE,
    DEV_SIGNAL_SUM,
    DEV_SIGNAL_SUM_SQ,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_MEAN_RUN,
    DEV_SIGNAL_M2,
    DEV_SIGNAL_P5_STATE,
    DEV_SIGNAL_P50_STATE,
    DEV_SIGNAL_PSQ_VALUE,
    DEV_SIGNAL_PSQ_TS,
    # Written on every reading like the rest of the day's
    # working set, and left out of this tuple when it was added
    # (ruling #263). A hot field kept only in the cold file is
    # written when something else forces a cold save, so a
    # restart brought back a stale count beside a current mean
    # and the day folded a report count too low.
    DEV_SIGNAL_READS,
    DEV_SIGNAL_TODAY_MAX,
    DEV_SIGNAL_RAIL_COUNT,
)

SENTINEL_TYPE_LOW_BATTERIES = "low_batteries"
# A different set and a different question from the one above:
# low is a level that has been crossed, falling is one that is
# going to be (ruling #209).
SENTINEL_TYPE_FALLING_BATTERIES = "falling_batteries"
# The two signal conditions, counted apart because they are not the
# same kind of thing: a rail is a broken measurement confirmed over
# three days and it persists, a weak link is a live reading that moves
# day to day. Counting them together gave one number that meant two
# things and read zero on a fleet with no rails (ruling #211).
SENTINEL_TYPE_SIGNAL_RAILS = "signal_rails"
SENTINEL_TYPE_SIGNAL_WEAK = "signal_weak"
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
# The floor is chosen by a trim ladder that grows with the soak: one
# lowest reading dropped per full week held, so the floor settles
# from "worst ever seen" to "typical worst" as the history earns
# trust. A count per week rather than a fixed number, so the share
# discarded stays near a seventh however long the window is
# (ruling #196). The trim
# drops the LOWEST values, the opposite of the rhythm trim which
# drops the highest, because for signal the spuriously bad reading is
# the anomaly to set aside.
#
# The ladder is one trimmed reading per full week held, so the share
# discarded stays near a seventh at every rung instead of thinning as
# the window grows (ruling #196). Two rungs were enough while the
# window was a fortnight; on thirty days a fixed k of two would drop
# nine percent where it used to drop fourteen, which lowers every
# floor on the fleet by about a tenth as a side effect of a change
# meant to be about stability. Measured on the reference fleet: one
# per week holds the median floor within a few points and still cuts
# the devices whose floor swings twenty points in a week from fifteen
# to five.
SIGNAL_TRIM_PER_WEEK = 7

# The window every signal verdict is computed over. Thirty days
# rather than the fourteen the rhythm uses, because the two measure
# different shapes (ruling #196). A floor is a trimmed minimum, so a
# short window forgets a device's genuinely bad days and sits too
# high: on the reference fleet fifty-one of seventy-eight devices had
# a worse day just outside the fortnight, and the floor jumping as
# one aged out is what made dwell spike to a hundred percent and back
# to zero within days. A line that moves under the device cannot be
# read across days, and dwell is only useful read across days.
#
# The rhythm stays at fourteen. It is a trimmed maximum, so a longer
# window can only raise it, and on the same fleet a longer window
# left seventy-nine of ninety-four devices identical while making the
# rest less sensitive. Battery stays at seven, because it is watching
# for the moment a plateau ends and a fortnight averages the plateau
# in with the fall, halving the apparent rate.
SIGNAL_DAYS_KEEP = 30

# The user's sensitivity adjustment, added to the ladder's k and
# clamped so the effective k always leaves at least one reading to be
# the floor. Left (negative) trims less: the floor sits at the rawest
# low and is rarely crossed. Right (positive) trims more: the floor
# sits higher and is brushed more often. Not retroactive: a change
# recomputes the floor for readings that follow; time already counted
# stays counted, so a full clean day is needed to see its true
# effect, which is why this lives on the config screen rather than as
# a live entity.

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
# The lift (ruling #252): a flat amount added to the line after the
# margin, one value for both scales. Zero, the default, is the
# formula as designed, with the line dying to nothing at perfect.
# Raising it keeps a thin band alive even at the top of the scale,
# a deliberate minimum vigilance. Capped at 2 because the top three
# detents of the proposed 0-to-5 range re-flagged the exact devices
# the formula change was built to free: on the reference fleet a
# lift of 5 put Door Entryway back from 7 reporting days to 11.


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
# The bad signal day (ruling #310). A device has a bad day when its
# own P5 falls well below its own recent normal, judged in that
# device's units and in its own spread, both gates together. The
# absolute gate is scale-native rather than a percentage, because a
# percentage of an RSSI number is meaningless: seven RSSI devices on
# the reference fleet sit near -60 dBm, where a real 6 dB loss reads
# as ten percent. That is ruling #250's lesson applying a second
# time. Defaults come from the one ground-truth event on record, a
# router unplugged on 18 August 2026, and are settings rather than
# constants precisely because one event cannot settle them.
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

# How many folded days form the normal a day is judged against. Seven
# is a starting position rather than a measured one: the analysis
# that produced this rule had nine days in hand and used every prior
# day, so the shape of the baseline is the least settled thing here.
CONF_BADDAY_BASELINE_DAYS = "badday_baseline_days"
DEFAULT_BADDAY_BASELINE_DAYS = 7
BADDAY_BASELINE_DAYS_MIN = 4
BADDAY_BASELINE_DAYS_MAX = 14

# A baseline needs this many readings before it can be judged
# against. Fewer than four days of P5 cannot supply a spread worth
# dividing by, and a spread near zero makes any ratio explode.
BADDAY_MIN_BASELINE = 4
BADDAY_MIN_SPREAD = 1.0

SIGNAL_MARGIN = 5
SIGNAL_LIFT = 0.0

SIGNAL_GREEN_CEILING = 5.0

# Signal-only muting, the same broad-to-narrow ladder as battery:
# integration, label, device. Muting suppresses judgment, not
# observation: a muted device keeps recording its floor and dwell
# in storage, so re-including it is instant and arrives with history;
# it simply stops being reported. This is the manual removal from
# tracking the frozen-signal ruling requires, given a surface: a
# device that resists every recovery (the development system's living
# room router plug) can be silenced without blinding the watcher.
CONF_SIGNAL_MUTED_DEVICES = "signal_muted_devices"
CONF_SIGNAL_MUTED_INTEGRATIONS = "signal_muted_integrations"
CONF_SIGNAL_MUTED_LABELS = "signal_muted_labels"

# Freeze-only muting, the same three-tier ladder as battery and
# signal. A device on this list is still watched and clocked, so its
# rhythm keeps learning and re-including it is instant, but it is
# never given a freeze, unavailable, unknown, or not-reported verdict.
# For a device that is intermittent by nature (a car sensor that
# travels, a seasonal device) this silences the freeze report without
# hiding the device from everything.
CONF_FREEZE_MUTED_DEVICES = "freeze_muted_devices"
CONF_FREEZE_MUTED_INTEGRATIONS = "freeze_muted_integrations"
CONF_FREEZE_MUTED_LABELS = "freeze_muted_labels"

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
# The restore notice keeps an id of its own (ruling #345). The three
# standing surfaces overwrite themselves; this one must survive until
# a person dismisses it.
RESTORE_NOTICE_ID = "device_sentinel_storage_restored"
RESTORE_NOTICE_TITLE = "Device Sentinel restored its storage"
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

# The three notification families. A family is not a problem kind and
# never was, but until 0.15.8 two of them were spelled the same as a
# kind, so "battery" meant a fault in one table and a family in
# another and the reader had to know which table they were in. The
# kinds were renamed (ruling #299) and the families are named here so
# neither has to be guessed from context again.
NOTIFY_FAMILY_BATTERY = "battery"
NOTIFY_FAMILY_SIGNAL = "signal"
NOTIFY_FAMILY_FREEZE = "freeze"
NOTIFY_FAMILIES_ALL = (
    NOTIFY_FAMILY_BATTERY,
    NOTIFY_FAMILY_SIGNAL,
    NOTIFY_FAMILY_FREEZE,
)

# The phone's notification tag per family: a push carrying a tag
# replaces the previous one rather than stacking beside it, so all
# battery news collapses into one entry on the lock screen. These
# values are deliberately not renamed and must not be swept up by a
# rename of the kinds. They are identities already living on every
# installed phone, and changing one costs a duplicate notification
# for no gain (ruling #299).
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

# How many unexplained interruptions put a device in the brief's
# repeat-offender section (ruling #305). An interruption is
# unexplained when no restart, bridge outage, broker outage, reload
# or pairing window covers it, judged by the same attribution the
# rest of the brief uses. The filter is the detector: counting every
# opening put 71 reference devices at exactly 2 from the nightly
# reboot and the SLZB-06's one continuous fault at the top of the
# list; counting unexplained openings left one genuine flapper on
# the reference fleet and named, on the first external fleet, the
# exact TV its owner had written about, unprompted. Neither fleet
# had a device at exactly 2, so the floor is a judgment: anything
# the filter cannot explain twice is worth one line, and a fleet
# where 2 turns out noisy has the slider.
CONF_REPEAT_FLOOR = "repeat_floor"
DEFAULT_REPEAT_FLOOR = 2
REPEAT_FLOOR_MIN = 1
REPEAT_FLOOR_MAX = 4
# The section reads up to this many days of incidents, growing from
# day one rather than waiting for a full week (ruling #305).
REPEAT_WINDOW_DAYS = 7.0
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
TODO_KIND_LOW_BATTERY = "low_battery"
# A cell projected to reach empty inside the person's horizon. A
# different kind from the one above and not a lesser version of it:
# low is a level that has been crossed, falling is one that is going
# to be, and a cell at eighty percent dropping steadily can have less
# life left than one sitting at thirty that has not moved in a month.
# They combine into one line when a device has both (ruling #213).
TODO_KIND_FALLING_BATTERY = "falling_battery"
TODO_KIND_FROZEN = FREEZE_CATEGORY_FROZEN
TODO_KIND_UNAVAILABLE = FREEZE_CATEGORY_UNAVAILABLE
TODO_KIND_UNKNOWN = FREEZE_CATEGORY_UNKNOWN
TODO_KIND_NEVER_REPORTED = FREEZE_CATEGORY_NEVER_REPORTED
TODO_KIND_RAILED_SIGNAL = "railed_signal"
# The signal problem rows tag a railed link with the kind above and
# leave a merely low one untagged. This names that default so the
# absence reads as a decision rather than an oversight; it is a row
# tag and not a problem kind, so it is not in TODO_KINDS_ALL.
SIGNAL_ROW_LOW = "low"

# The spellings four problem kinds carried before 0.15.8, and the
# only place the old vocabulary is allowed to appear. Stored history
# keeps whatever was written at the time, so the incidents, the
# additions journal and the to-do items are rewritten once at load
# and the fleet then speaks one vocabulary rather than two (ruling
# #299).
#
# Three named passes rather than one walk over every "kind" in the
# file: the system events list carries its own vocabulary of fourteen
# values under the same field name, and a generic sweep would destroy
# every one of them.
LEGACY_KIND_RENAMES = {
    "battery": TODO_KIND_LOW_BATTERY,
    "battery_falling": TODO_KIND_FALLING_BATTERY,
    "signal": TODO_KIND_RAILED_SIGNAL,
    "rail": TODO_KIND_RAILED_SIGNAL,
    "not_reported": TODO_KIND_NEVER_REPORTED,
}
# Not a TODO_KIND_: those are device faults, and every one has a
# route to the card, an event wording, and a state template, which a
# test asserts. This names a cause rather than a device, carries its
# own sentence, and takes no part in the incident timeline, so it is
# deliberately outside that family (ruling #266).
UPSTREAM_KIND = "upstream"

# Every problem kind, in one place. Five tables map a kind to words
# and each was written by hand, so adding the falling kind gave it
# wording in one of them and left a raw key reading "battery_falling"
# in a person's brief. The guard against exactly that listed the
# kinds by hand too, so it kept passing while checking six of seven
# (ruling #215). Anything that maps kinds reads this.
TODO_KINDS_ALL = (
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
# reported, and which of the four it earns depends on what its
# entities read at the moment of judgment, so a restart that hides a
# device's states for a minute moves it from one to another and back.
# That is a re-description, not a new problem: the item never left the
# list and nothing about the device changed (ruling #318).
#
# A battery and a signal are their own families, because a cell dying
# on a device that is already silent is genuinely new and a person
# wants to hear it.
TODO_KIND_FAMILIES = {
    TODO_KIND_FROZEN: "down",
    TODO_KIND_UNAVAILABLE: "down",
    TODO_KIND_UNKNOWN: "down",
    TODO_KIND_NEVER_REPORTED: "down",
    TODO_KIND_LOW_BATTERY: "battery",
    TODO_KIND_FALLING_BATTERY: "battery",
    TODO_KIND_RAILED_SIGNAL: "signal",
}

# What Device Sentinel says on the bus. Three names rather than one
# type with an action field, because an automation triggers on
# event_type and a distinct name is what a person types into the
# trigger box (ruling #289).
EVENT_FAULT = "device_sentinel_fault"
EVENT_RECOVERED = "device_sentinel_recovered"
EVENT_ACKNOWLEDGED = "device_sentinel_acknowledged"

# Worst first, so kinds[0] is the headline and an automation reads it
# without a template. Unavailable leads because
# FREEZE_CATEGORY_PRIORITY already ruled it above frozen: an
# unavailable device is honestly absent and a frozen one is lying.
TODO_KIND_SEVERITY = (
    TODO_KIND_UNAVAILABLE,
    TODO_KIND_FROZEN,
    TODO_KIND_UNKNOWN,
    TODO_KIND_NEVER_REPORTED,
    TODO_KIND_LOW_BATTERY,
    TODO_KIND_FALLING_BATTERY,
    TODO_KIND_RAILED_SIGNAL,
)


# What the payload says when a device has no area. The reports have
# said this for as long as they have existed, and a template joining
# a null into a message renders the word None at a person.
UNASSIGNED_AREA = "Unassigned"

# The freeze family covers every liveness kind; a battery or signal
# kind maps to its own family, and anything else is a freeze-family
# event. This is the map from a problem kind to its notification family.
NOTIFY_KIND_FAMILY = {
    TODO_KIND_LOW_BATTERY: NOTIFY_FAMILY_BATTERY,
    TODO_KIND_FALLING_BATTERY: NOTIFY_FAMILY_BATTERY,
    TODO_KIND_RAILED_SIGNAL: NOTIFY_FAMILY_SIGNAL,
    TODO_KIND_FROZEN: NOTIFY_FAMILY_FREEZE,
    TODO_KIND_UNAVAILABLE: NOTIFY_FAMILY_FREEZE,
    TODO_KIND_UNKNOWN: NOTIFY_FAMILY_FREEZE,
    TODO_KIND_NEVER_REPORTED: NOTIFY_FAMILY_FREEZE,
}

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
# Event types. ACTION is reserved: anything the integration one day
# does, rather than observes, belongs on the same timeline as the
# problem it answers. Nothing writes it today (ruling #235).
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
# How far before an incident opened an episode may have ended and
# still be its explanation. A sampler notices an intervention up to
# one tick late, so an episode closed a minute early is the same
# event; one closed on Tuesday is not (ruling #228).
CAUSE_EPISODE_SLACK_SECONDS = 120.0

# Named from the constants rather than spelled by hand. Written as
# literals, this set survived the 0.15.8 rename untouched and would
# have quietly stopped crediting a cause to a never-reported
# recovery, which is #215 in its sixth table (ruling #299).
FREEZE_KINDS_FOR_CAUSE = frozenset(
    {
        TODO_KIND_FROZEN,
        TODO_KIND_UNAVAILABLE,
        TODO_KIND_UNKNOWN,
        TODO_KIND_NEVER_REPORTED,
    }
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

# How a silence ended, in the words the payload uses. Three values
# because two would have meant guessing: the stored cause is null on
# 180 of the reference fleet's 256 resolved incidents, and those nulls
# are a battery with no lever to name and a silence whose episode fell
# outside #228's slack wearing one value (ruling #291).
RECOVERY_BY_SELF = "self"
RECOVERY_BY_INTERVENTION = "intervention"
RECOVERY_BY_UNKNOWN = "unknown"
RECOVERY_CAUSES_INTERVENTION = frozenset(
    {"bridge reconnect", "reboot", "unclean shutdown"}
)
RECOVERY_CAUSES_SELF = frozenset({RECOVERY_CAUSE_UNOBSERVED})
# The wording this replaced, still sitting in stored incidents from
# before the wording changed. Migrated at load rather than left to
# age out, because the composer tests for the current string and
# would otherwise write "revived by a on its own" for a fortnight.
LEGACY_CAUSE_UNOBSERVED = "on its own"

# The span the live copy of the brief covers, as opposed to the
# closed record, which runs brief hour to brief hour (ruling
# #116). The undated file is the dashboard's address, and a
# window measured from the brief time held almost nothing for
# most of the day, so the card read as a quiet house while a
# full day of events sat in yesterday's dated file. A rolling
# day fixes that and costs the record nothing, because the
# dated file is still named for the brief day and is rewritten
# as the true closed window when the day closes (ruling #187).
BRIEF_LIVE_WINDOW_SECONDS = 86400.0
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
# The last bridge state each stack was seen in, kept across a restart
# so an outage that spans one still closes with its real duration.
# Derived rather than measured, but a comparison against the previous
# boot is the one thing memory cannot hold (ruling #222).
DATA_BRIDGE_SEEN = "bridge_seen"
# The broker state, kept across a restart for the same reason
# (ruling #222 applied to #224).
DATA_BROKER_SEEN = "broker_seen"
BRIDGE_SEEN_STATE = "state"
BRIDGE_SEEN_SINCE = "since"

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
# The broker going and returning. Its own pair rather than a bridge
# event, because a bridge reader is blind to it: when the broker dies
# nothing delivers the bridge's last will, since the broker is the
# deliverer. Measured on 2026-08-06, a sixteen-minute broker outage
# took 75 devices unavailable and wrote no system event at all, while
# bridge_state read running throughout (ruling #224).
# A storm: many devices on one integration reporting at once, most
# often that integration reloading or its hub reconnecting. It was a
# runtime concept that stamped episodes and then forgot, so the rule
# that reclassifies a polling integration counted storms only within
# one uptime and reset at every nightly reboot. Recorded now, so the
# rule survives a restart and so an integration outage is legible at
# all: before this, Reolink reloading and dropping four cameras
# produced nothing a person could read (ruling #227).
SYS_STORM_OPEN = "storm_open"
SYS_STORM_CLOSED = "storm_closed"
# Fields the storm rows carry beyond the shared ones.
SYS_DEVICES = "devices"

# The per-integration storm series, kept on the person's retention
# rather than the judgment window, because its purpose is to be
# looked back over. Nothing is learned from it yet: an integration
# reloading is not periodic, and inventing a cadence for it would be
# the global constant this project keeps overruling (ruling #227).
# The highest ruling recorded in the decision history. A citation in
# the source past this number cannot be followed, and two such
# citations sat in the tree unnoticed for weeks: one a typo, one
# pointing at reasoning that was never written down. The guard in
# tests/test_citations.py reads this, so a stale number fails the
# suite rather than passing quietly (ruling #233).
HIGHEST_RULING = 347

DATA_STORMS = "storms"
# How long a raw storm row is kept. Two days rather than the person's
# retention: the polling test looks back one hour, and a real reload
# is already kept for the full retention in the system events log, so
# a longer window here would store 2.66 MB of a constant against a
# storage file of about 880 KB (ruling #232).
# One hour, not two days (ruling #320, amending #232). The only
# reader of the raw rows is the polling verdict, which looks back
# STORM_HISTORY_SECONDS; two days held 47 unread hours and reached
# 64 percent of the reference fleet's storage file. The daily
# record lives in DATA_STORM_DAYS instead.
STORM_KEEP_SECONDS = 3600.0

# The daily storm tally (ruling #320): one row per domain per day,
# written at the fold from the day's storms, kept on the retention
# setting. Count, median seconds between storms, median device
# count, median duration. The brief's flood sentence (ruling #321)
# is its reader.
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

SYS_BROKER_DOWN = "broker_down"
SYS_BROKER_UP = "broker_up"
SYS_PAIRING_OPEN = "pairing_open"
SYS_PAIRING_CLOSED = "pairing_closed"
# A person declared they are working on the hardware, and the
# declaration ended, by expiry or by a second press (rulings #225 and
# #238). Recorded so the events log explains the discards between them.
SYS_MAINTENANCE_OPEN = "maintenance_open"
SYS_MAINTENANCE_CLOSED = "maintenance_closed"
SYS_EPOCH_RESET = "epoch_reset"
SYS_OPTIONS_CHANGED = "options_changed"

# A person deliberately erased a device's or an integration's learned
# history from the Advanced screen (ruling #307). Recorded because it
# is the one destructive act the integration performs on a person's
# instruction, and because the statistics after it begin from nothing:
# an event log that did not say so would leave a device looking newly
# discovered for no reason. It is also what keeps attribution correct,
# since a trimmed device's first incidents must not be explained by
# windows that predate its rebirth.
SYS_TRIMMED = "trimmed"

# Where a trim writes its copy of storage before deleting anything.
# One stamped pair per trim, never overwritten, so a sequence of
# trims cannot bury the state the first one started from, and never
# the nightly last-good pair, which stays exactly what the fold left.
# The folder does not clean itself; the help text says so rather than
# any silent expiry.
TRIM_BACKUP_DIR = "device_sentinel/trim_backups"

# The two pickers. Both are actions wearing an option's clothes: the
# save applies them and then writes them back empty, so a reload
# cannot delete a second time.
CONF_TRIM_INTEGRATIONS = "trim_integrations"
CONF_TRIM_DEVICES = "trim_devices"

# A load or a fold found a stored record whose shape did not match
# what the code expects (ruling #278). Recorded as a system event so it
# reaches the brief and the diagnostics, because a warning in the log
# is read once and a diagnostics file is read by the maintainer. This
# release only reports; nothing is repaired until a week of loads and
# folds has shown the checks fire on nothing good.
SYS_STORAGE_SHAPE = "storage_shape"
# A repair or a restore the integration performed on its own storage,
# recorded so a silent action cannot exist (ruling #342): the detail
# names what was done and what it was done from.
SYS_STORAGE_REPAIR = "storage_repair"

# The Repairs surface (rulings #292 to #297, #300 and #301). Four
# identifiers, each naming a problem class rather than an occurrence,
# because one issue per class is what keeps a recurrence from stacking
# a second row beside the first. They are deliberately stable across
# releases: storage_shape gains its fix flow when Heal ships and must
# attach to the issue a person already has open rather than appearing
# beside it as a stranger.
#
# These are also the translation keys, so a value here has a matching
# entry under "issues" in strings.json and translations/en.json.
# Repairs renders from the translation files alone, so an identifier
# without one shows a person a raw key.
#
# storage_shape shares its spelling with the system event above and
# is a separate constant on purpose: one names a row in the events
# log and the other names a card in Settings, and a single name read
# by both would make a later rename of either look safe when it is
# not.
REPAIR_STORAGE_SHAPE = "storage_shape"
REPAIR_ENTITIES_DISABLED = "entities_disabled"
REPAIR_NOTIFY_TARGET_MISSING = "notify_target_missing"
REPAIR_NO_DELIVERY = "no_delivery_configured"
REPAIRS_ALL = (
    REPAIR_STORAGE_SHAPE,
    REPAIR_ENTITIES_DISABLED,
    REPAIR_NOTIFY_TARGET_MISSING,
    REPAIR_NO_DELIVERY,
)

# The two moments a Repair is evaluated (ruling #300, amended by
# #309): when the startup grace closes, and when the daily brief is
# sent. Not the render tick, because an issue that reappears while a
# person is reading it is worse than one raised a few hours late,
# and none of these four conditions changes on a timescale a tick
# would catch. Not the fold either, since a nightly reboot scheduled
# after midnight closes grace and clears a card raised hours earlier,
# before anybody was awake to read it. The brief hour is the hour a
# person looks.
REPAIR_MOMENT_GRACE = "grace"
REPAIR_MOMENT_BRIEF = "brief"

# How many things a Repair card names before it starts counting.
# A card is read in a dialog rather than scrolled, and the full list
# is already in the log and the diagnostics.
REPAIR_DETAIL_MAX = 3

# How long an install may go with nowhere to send anything before it
# is worth saying so (ruling #301). Seven days rather than
# immediately, because a person setting the integration up must not
# be interrupted on their first evening by a badge telling them they
# have not finished. Seven is the week freeze detection already asks
# for, and by then a person has had seven daily briefs they never
# received, which is what makes it a settled state rather than one
# they are passing through.
NO_DELIVERY_MIN_DAYS = 7.0

# How long an interruption must last before the daily brief says
# anything about it (ruling #275). In Short is read rather than
# scanned, so a normal event earns no sentence: the tables below
# carry every one for anyone looking. Five minutes was measured, not
# chosen. On the reference fleet 113 restarts fall in two bands, 92
# of them under 40 seconds and 20 between 99 and 126 seconds for the
# nightly reboot, and one at 45 minutes; and 11 bridge outages run
# 1.0 to 4.0 minutes for reboot artefacts against 11, 17 and 22 for
# the real ones. Two minutes would have named the nightly reboot
# twenty times; five names the one restart and the three outages that
# were genuinely abnormal.
BRIEF_NOTEWORTHY_SECONDS = 300.0
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
# Retired (ruling #241). Nothing takes this backup any more; the name
# survives only so the load can drop its stale marker from storage
# written by an older version.
BACKUP_SUFFIX_PREPHASE_C = "prephase-c"
BACKUP_TAKEN_KEY = "backup_taken"

# The rolling copy of both storage files, overwritten only after a
# load or a fold whose shape check reported nothing (ruling #278). It
# is a byte copy of what was on disk, so it is only ever a copy of a
# file the checks passed, and it can never hold a value they would
# reject. Nothing reads it yet; the release that repairs from it comes
# after the checks have proved themselves quiet on good data.
BACKUP_LAST_GOOD_SUFFIX = "last-good"

DATA_EPISODES = "silence_episodes"
EPISODE_KEEP_DAYS = 14
# The long-lived half of the anchor dataset (ruling #246): when an
# episode closes, a compact row (who, when, how long, how it ended,
# and the signal snapshot from its open) folds into this series,
# kept on the history retention setting rather than the fourteen-day
# episode trim. Episodes explain a fortnight; the anchor needs
# seasons.
DATA_SIGNAL_STRESS = "signal_stress"
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
# The device's signal context stamped when the episode opens (ruling #246):
# the last reading, the day's running mean and deviation so far, and
# the line in effect. An episode is the fleet's one source of rhythm
# stress, and the anchor #172 waits on is the correlation between
# signal level and that stress. The join has to be captured at the
# moment the silence begins, because by any later analysis the
# statistics have moved on.
EP_SIGNAL = "signal"
EP_SIG_VALUE = "value"
EP_SIG_MEAN = "mean"
EP_SIG_SD = "sd"
EP_SIG_LINE = "line"
EPISODE_ENDED_RESUMED = "resumed"
EPISODE_ENDED_REBOOT = "intervention (reboot)"
EPISODE_ENDED_RECONNECT = "intervention (bridge reconnect)"
# A storm inside startup grace is the restart itself: every device
# reports at once when Home Assistant returns, which looks exactly
# like a bridge reconnecting. Naming it correctly matters because
# the two are different events with different reach, and the brief
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

# The mute surface. One list, four selectors, governing
# every detection family present and future. Muting suppresses
# judgment, not observation: muted devices and entities keep
# their clocks, statistics, and vouching, so an undo is instant and
# free and the rhythm history carries no holes. A muted entity
# still vouches for its device's freeze clock; only its own
# reporting is suppressed.
#
# The four kinds form a priority ladder, broadest first: integration,
# label, device, entity. A broader muting supersedes a narrower
# one and prunes it on save, so a pick can never be shadowed by an
# invisible parent.
#
# Area was a fifth kind once and was removed (ruling #46).
# Area membership is set for dashboards, voice, and automations, so
# letting it also switch off monitoring means a room reorganization
# silently changes what is watched. A label carries one meaning and
# is set for one reason, which is what this surface needs.
CONF_MUTED_DEVICES = "muted_devices"
CONF_MUTED_LABELS = "muted_labels"
CONF_MUTED_INTEGRATIONS = "muted_integrations"

# Option keys no longer read by any code path. Cleared once at setup
# so a retired surface cannot linger in diagnostics and read as a
# live setting.
#
# excluded_areas is the area muting kind, retired because area
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
# The four signal keys became constants at #311 when the sliders they
# fed were retired, and were never added here, so they sat in every
# stored entry reading as live settings, which is the same rot the
# six above were removed for. Swept at #316, the release that was
# already opening the options.
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
# release at a time and a person who jumps several run the same code
# in the same order (ruling #316). The entry's minor version records
# how far it has come; each step below moves it one further.
#
# Step 2 renames the twelve muting keys from their exclude spellings.
# The words were backward: excluding sounded like the harsher act and
# only silences, while ignoring sounds like the softer one and
# discards the record.
# Step 3 renames the ignore list to the word it vacated. Excluding
# now means what it looks like, the record discarded, and muting
# carries the gentler act (ruling #317).
OPTIONS_MINOR_VERSION = 3

# The muting keys, old spelling to new, in the order a person meets
# them on the screens. Read by the migration and by the guard that
# rewrites stored history, so there is one list rather than two.
IGNORE_KEY_RENAMES = {
    "ignored_integrations": "excluded_integrations",
}



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

# The same renames, each stamped with the release that made it, for
# the pass that rewrites stored history.
#
# A flat map cannot do this job any more. `excluded_integrations` was
# the muting key until 0.16.18 moved it and is the ignore key since
# 0.16.19 moved into the word it vacated, so the same string means
# two different settings depending on when the row was written. Read
# flat, a row written today would be rewritten tomorrow into a
# setting the person never touched.
#
# What tells them apart is the version stamp the storage file already
# carries: a rename is applied only to a file last written before the
# release that made it, and never to one written by that release or
# later. Nothing new is stored to make this work.
OPTION_KEY_RENAME_STEPS = (
    ((0, 16, 18), MUTING_KEY_RENAMES),
    ((0, 16, 19), IGNORE_KEY_RENAMES),
)


SENTINEL_TYPE_PROBLEM_LIST = "problem_list"

# Battery-only muting. Scoped on top of the global
# mute list: a device here is muted from battery judgment
# only, keeping its freeze, unavailability, and signal watching for
# the later steps. Keyed at the device level so a re-election
# (percentage entity vanishing, binary elected instead) cannot dodge
# it. The integration list makes "everything mobile_app" one tick,
# covering phones present and future. No entity kind here for the
# same re-election reason.
CONF_BATTERY_MUTED_DEVICES = "battery_muted_devices"
CONF_BATTERY_MUTED_INTEGRATIONS = "battery_muted_integrations"
CONF_BATTERY_MUTED_LABELS = "battery_muted_labels"


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
    """Return the URL of one wiki page.

    Page names are the wiki's own titles with spaces as hyphens,
    which is how GitHub builds a wiki URL from a page title. A name
    that does not match a real page yields a link to a page-not-found
    screen rather than an error, so these are checked against the
    live wiki rather than trusted.

    The URL only (ruling #242). This used to return a whole Markdown link
    reading "Device Sentinel wiki", which put the link text in Python
    where no translator could reach it, made all six configuration
    screens advertise the same destination when each goes somewhere
    different, and produced a nested link on the three screens that
    wrote their own words around it. Each string now names the page
    it opens.
    """
    return f"{WIKI_BASE_URL}/{page}" if page else WIKI_BASE_URL


WIKI_LINK_HOME = _wiki_link()
WIKI_LINK_NOTIFICATIONS = _wiki_link("Notifications-and-Daily-Brief")
WIKI_LINK_ADVANCED = _wiki_link("Advanced")
WIKI_LINK_EXCLUSIONS = _wiki_link("Exclusions-and-Muting")
WIKI_LINK_BATTERY = _wiki_link("Low-Battery")
WIKI_LINK_SIGNAL = _wiki_link("Signal-Strength")
WIKI_LINK_FREEZE = _wiki_link("Freeze-Detection")
WIKI_LINK_MAINTENANCE = _wiki_link("Maintenance-Mode")
WIKI_LINK_INSTALLATION = _wiki_link("Installation-and-Setup")
WIKI_LINK_LEARNING = _wiki_link("How-Device-Sentinel-Learns")
WIKI_LINK_DEVICE_PAGE = _wiki_link("The-Device-Page")
WIKI_LINK_PROBLEM_LIST = _wiki_link("The-Problem-List")
WIKI_LINK_REPORTS = _wiki_link("The-Diagnostic-Reports")
WIKI_LINK_BATTERY_REPORT = _wiki_link("The-Battery-Report")
WIKI_LINK_FAQ = _wiki_link("FAQ-and-Troubleshooting")
WIKI_LINK_EVENTS = _wiki_link("Automation-Events")
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
DEAD_ENTITY_SENTINEL_TYPES = (
    SENTINEL_TYPE_CLOCK_SOURCE,
    # The battery threshold slider, retired in 0.11.10 with the
    # whole number platform (ruling #209).
    "battery_low_threshold",
    # Signal: Problems, split into Signal: Rails and Signal: Weak in
    # the same release (ruling #211).
    "signal_problems",
)
