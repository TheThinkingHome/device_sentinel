# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: store.py, Version: 0.16.8 (2026-08-20)

"""Storage: the two files, the merge, and the unclean restart.

One of six subject modules split out of coordinator.py, which
had reached four thousand lines. The seam is the subject, chosen
by measuring which methods call which: storage and interventions
call nothing outside themselves at all, and the three detectors
reach out fewer than ten times each (ruling #201).

A file split rather than a boundary. These are mixins on the
coordinator and read its state freely, so `self` is the
coordinator throughout and nothing here stands alone.
"""

from __future__ import annotations

from typing import Any
from homeassistant.core import Event, callback
from homeassistant.util import dt as dt_util
from .records import _new_device_record, _reset_signal_day, _span

from .const import (
    DATA_INCIDENTS,
    DATA_SYSTEM_EVENTS,
    MUTING_KEY_RENAMES,
    SYS_DETAIL,
    SYS_KIND,
    SYS_OPTIONS_CHANGED,
    DATA_TODO_JOURNAL,
    INC_KIND,
    LEGACY_KIND_RENAMES,
    TODO_KINDS,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_M2,
    DEV_SIGNAL_MEAN_RUN,
    DEV_SIGNAL_SUM,
    DEV_SIGNAL_SUM_SQ,
    DEV_SIGNAL_TODAY_MAX,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_VALUE,
    CLOCK_FIELDS,
    COALESCE_MINUTES_MAX,
    COALESCE_MINUTES_MIN,
    CONF_COALESCE_MINUTES,
    CONF_IGNORED_INTEGRATIONS,
    CONF_RETENTION_DAYS,
    DATA_CLEAN_STOP,
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_FIRST_INSTALLED,
    DATA_SAVED_AT,
    DATA_SETUP_COUNT,
    DATA_TODO_ITEMS,
    DEFAULT_COALESCE_MINUTES,
    DEFAULT_IGNORED_INTEGRATIONS,
    DEFAULT_RETENTION_DAYS,
    DEV_LAST_ACTIVITY,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    EPISODE_ENDED_REBOOT,
    EPISODE_ENDED_UNCLEAN,
    EPISODE_LEARNED_TRUNCATED,
    EP_AT,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LEARNED,
    EP_SINCE,
    LOGGER,
    RETENTION_DAYS_MAX,
    RETENTION_DAYS_MIN,
    STORAGE_CLOCKS_KEY,
    TODO_DEVICE_ID,
)


class StorageMixin:
    """Storage: the two files, the merge, and the unclean restart."""

    @staticmethod
    def _reconcile_records(
        devices: dict[str, dict[str, Any]], now_iso: str
    ) -> tuple[int, int]:
        """Bring stored records into line with the schema, both ways.

        _new_device_record is the one authoritative field set. Any
        key a stored record carries that a fresh one does not was
        written by a past version and is dead, like the frozen fields
        the rail rework dropped; any key a fresh record carries that
        a stored one does not belongs to a version newer than the
        file and has to arrive with a value.

        Only the removing half existed until 0.10.22, and the filling
        half was a hand-maintained list of setdefault calls in the
        load path. That is the shape of fault this exists to end
        (ruling #189): the list had already drifted, omitting seven
        signal fields on the branch that runs when the statistics
        epoch changes, and its failure mode is invisible to the
        tests, which build fresh records and so never meet a stored
        one that is missing anything.

        A fresh record is built per device rather than once, because
        the schema's defaults include lists and one shared list
        handed to every device would make them the same list.

        Returns (keys removed, keys filled), both zero once storage
        has been written by this version.
        """
        removed = 0
        filled = 0
        for record in devices.values():
            schema = _new_device_record(now_iso, None)
            for key in [k for k in record if k not in schema]:
                del record[key]
                removed += 1
            for key, value in schema.items():
                if key not in record:
                    record[key] = value
                    filled += 1
        return removed, filled

    @staticmethod
    def _migrate_signal_accumulators(
        devices: dict[str, dict[str, Any]], repair: bool
    ) -> tuple[int, int]:
        """Convert the day's signal accumulators to Welford's pair.

        Ruling #256. The conversion was written into the reading path
        in 0.12.19 and never ran: the reconciler below removes any
        key the schema has dropped and fills any key it has gained,
        so by the time a reading arrived the legacy sum was already
        deleted and the running mean already present as zero. The
        migration read a record that had been made to look migrated.
        With the legacy count kept and the mean restarted at zero,
        each later reading moved the mean by only value over count,
        so a fleet of links averaging 118 carried running means near
        ten, and the deviation with them.

        So the conversion belongs here, at load, before the
        reconciler runs, which is also the only moment the legacy
        pair still exists. Two paths: convert where the legacy pair
        is present (exact: the mean is the sum over the count, M2 the
        squares less count times the squared mean), and reset the
        day where a previous version already destroyed it, which
        cannot be recovered because the sums it needed are gone.

        The repair is one-shot, gated by a marker in storage, so a
        later restart cannot drop another day.

        Returns (converted, reset), both zero on an install that
        never ran the broken versions.
        """
        converted = 0
        reset = 0
        for record in devices.values():
            count = int(record.get(DEV_SIGNAL_COUNT) or 0)
            if DEV_SIGNAL_SUM in record:
                # Untouched by the broken versions: they deleted this
                # pair on their first load, so its presence proves
                # the day is sound and the conversion is exact.
                if count > 0:
                    total = float(record.get(DEV_SIGNAL_SUM) or 0.0)
                    squares = float(record.get(DEV_SIGNAL_SUM_SQ) or 0.0)
                    mean = total / count
                    record[DEV_SIGNAL_MEAN_RUN] = mean
                    record[DEV_SIGNAL_M2] = max(
                        0.0, squares - count * mean * mean
                    )
                    converted += 1
            elif repair and count > 0:
                # Ran a broken version: the running mean is a partial
                # sum against a full count and there is nothing left
                # to rebuild it from. Dropping the day in progress
                # costs the hours since midnight and keeps a false
                # mean and deviation out of the ninety-day series,
                # which is the trade this repair exists to make.
                _reset_signal_day(record)
                reset += 1
        return converted, reset

    def _rename_stored_kinds(self, loaded: dict[str, Any]) -> int:
        """Bring stored history onto the one kind vocabulary (#299).

        Four problem kinds were renamed for 0.15.8, before the event
        payload could publish them and make them a contract nobody
        could change again. Stored history keeps whatever spelling was
        written at the time, so a brief drawing on it would have read
        one vocabulary out of a file holding two, which is #215
        arriving by a different road.

        Three named passes and never a walk over every "kind" in the
        file. The system events list carries fourteen values of its
        own under that same field name, and a sweep would rewrite
        every one of them into nonsense. Each list here is named
        because it holds a problem kind, and a list not named is a
        list that does not.

        Idempotent by construction: a value already correct is not a
        key in the map and is left alone, so the second start rewrites
        nothing. An unrecognized value passes through untouched rather
        than being dropped, so a record written by a later version
        survives a downgrade.
        """
        renamed = 0

        # The incident timeline, which the brief and the maintainer
        # report both read to write their sentences.
        for entry in loaded.get(DATA_INCIDENTS) or []:
            fresh = LEGACY_KIND_RENAMES.get(entry.get(INC_KIND))
            if fresh is not None:
                entry[INC_KIND] = fresh
                renamed += 1

        # The additions journal, capped at a count rather than an age,
        # so on a quiet fleet an old spelling could sit here for
        # months. It stops being write-only the moment events fire
        # from this same boundary (ruling #289).
        for entry in loaded.get(DATA_TODO_JOURNAL) or []:
            fresh = LEGACY_KIND_RENAMES.get(entry.get(INC_KIND))
            if fresh is not None:
                entry[INC_KIND] = fresh
                renamed += 1

        # The list itself, where a kind is a dictionary key and the
        # value is the moment it was added, so the entry is rebuilt
        # rather than reassigned.
        for item in loaded.get(DATA_TODO_ITEMS) or []:
            kinds = item.get(TODO_KINDS)
            if not isinstance(kinds, dict):
                continue
            rebuilt = {
                LEGACY_KIND_RENAMES.get(kind, kind): when
                for kind, when in kinds.items()
            }
            if rebuilt != kinds:
                renamed += sum(
                    1 for kind in kinds if kind in LEGACY_KIND_RENAMES
                )
                item[TODO_KINDS] = rebuilt

        if renamed:
            LOGGER.info(
                "Renamed %d stored problem kind(s) onto the current "
                "vocabulary: %s",
                renamed,
                ", ".join(
                    f"{was} to {now}"
                    for was, now in LEGACY_KIND_RENAMES.items()
                ),
            )
        return renamed

    def _rename_stored_option_keys(self, loaded: dict[str, Any]) -> int:
        """Bring stored settings-changed rows onto the muting names.

        A settings-changed row records which option keys moved, as a
        comma-joined string, and the brief turns each key into the
        label a person read on the screen by looking it up in
        strings.json (ruling #314). Rename the keys and every row
        written before the upgrade points at a label that no longer
        exists, so the brief falls back to the raw key and prints
        `excluded_devices` at a person for as long as the row is
        kept. The same reasoning as #299: stored history speaks one
        vocabulary or the surface reading it speaks two.

        One named list, not a sweep. The detail field carries option
        keys only on this one kind; on others it carries counts and
        device names, and rewriting those would be nonsense.

        Idempotent: a key already renamed is not in the map. An
        unrecognized key passes through untouched, so a row written
        by a later version survives a downgrade.
        """
        renamed = 0
        for entry in loaded.get(DATA_SYSTEM_EVENTS) or []:
            if entry.get(SYS_KIND) != SYS_OPTIONS_CHANGED:
                continue
            detail = entry.get(SYS_DETAIL)
            if not isinstance(detail, str) or not detail:
                continue
            keys = [part.strip() for part in detail.split(",")]
            rebuilt = [MUTING_KEY_RENAMES.get(key, key) for key in keys]
            if rebuilt != keys:
                renamed += sum(
                    1 for key in keys if key in MUTING_KEY_RENAMES
                )
                entry[SYS_DETAIL] = ", ".join(rebuilt)
        if renamed:
            LOGGER.info(
                "Renamed %d stored option key(s) in the system events "
                "log onto the muting vocabulary (ruling #316)",
                renamed,
            )
        return renamed

    def _clear_mixed_signal(self, devices: dict[str, Any]) -> list[str]:
        """Discard a signal history that holds two scales at once.

        Until 0.15.6 every entity matching the signal recognizer fed
        one series, so a ZHA device's RSSI in dBm and its LQI on 0 to
        255 both landed in the same numbers (ruling #282). Nothing in
        the stored figures says which reading came from which sensor,
        so the mixture cannot be separated after the fact and the
        history has to go.

        The test is the data rather than a version marker: a retained
        series that runs from negative to positive is not one
        measurement, whatever wrote it. That finds the Tasmota
        devices too, whose percentage 0.15.4 stopped accepting but
        whose recorded days still hold it, and it keeps working for a
        device that grows a second entity next month. On the fleet
        that found this, the test picks out 7 of 7 Tasmota devices
        and 34 of 39 ZHA devices, and none of the 118 on a fleet that
        publishes one scale per device.
        """
        cleared: list[str] = []
        for device_id, record in devices.items():
            seen: list[float] = []
            for field in (
                DEV_SIGNAL_DAILY_MAX,
                DEV_SIGNAL_DAILY_MEAN,
                DEV_SIGNAL_DAILY_MIN,
                DEV_SIGNAL_DAILY_P5,
                DEV_SIGNAL_DAILY_P50,
            ):
                seen.extend(
                    value
                    for value in (record.get(field) or [])
                    if isinstance(value, (int, float))
                    and not isinstance(value, bool)
                )
            for field in (
                DEV_SIGNAL_VALUE,
                DEV_SIGNAL_TODAY_MIN,
                DEV_SIGNAL_TODAY_MAX,
            ):
                value = record.get(field)
                if isinstance(value, (int, float)) and not isinstance(
                    value, bool
                ):
                    seen.append(value)
            if not seen or min(seen) >= 0 or max(seen) < 0:
                continue
            fresh = _new_device_record("", None)
            for field in fresh:
                if field.startswith("signal_"):
                    record[field] = fresh[field]
            cleared.append(device_id)
        return cleared

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        """Return the live data, stamped, for a save of the main file.

        The stamp is what the next load compares against the hot
        file to decide which holds the newer clocks. Serializing the
        main file is what the cold flag asks for, so it clears here,
        in the one place every main-file write passes through.

        The clock fields are stripped out of the main file here
        (ruling #101), unconditionally: they are the hot file's job,
        written every interval, and the copies the main file once
        carried existed only as a net during the transition, which is
        over (ruling #241). The strip is a filtered view built for the write
        rather than a mutation, because the live records must keep
        their clocks for every reader in this process; only the file
        sheds them.
        """
        self._cold_dirty = False
        self.data[DATA_SAVED_AT] = dt_util.utcnow().timestamp()
        out = dict(self.data)
        out[DATA_DEVICES] = {
            device_id: (
                {
                    field: value
                    for field, value in record.items()
                    if field not in CLOCK_FIELDS
                }
                if isinstance(record, dict)
                else record
            )
            for device_id, record in self.data[DATA_DEVICES].items()
        }
        return out

    def _merge_clocks(
        self, loaded: dict[str, Any], hot: dict[str, Any] | None
    ) -> int:
        """Overlay the hot file's clocks onto the loaded record set.

        The hot file is the only place clocks live, so this is not a
        merge of two opinions but the restoration of the one that
        exists (ruling #101). The main file never carries copies, and the
        transitional case where it might, along with the branch that
        preferred them, is gone (ruling #241).

        The hot file is used whatever its age, because a slightly
        stale clock self-heals on the device's next report while no
        clock at all is a fleet-wide reset. A device the main file has
        never heard of is skipped, because nine fields cannot rebuild
        a record. Returns how many devices took their clocks from
        here.
        """
        devices = loaded.get(DATA_DEVICES) or {}
        if not hot:
            if devices:
                LOGGER.warning(
                    "The activity clocks file %s is missing, so every "
                    "device's clock starts over from this boot. This "
                    "is expected only if it was deleted by hand",
                    STORAGE_CLOCKS_KEY,
                )
            return 0
        hot_at = hot.get(DATA_SAVED_AT)
        cold_at = loaded.get(DATA_SAVED_AT)
        if hot_at is None or cold_at is None:
            # One of the pair predates the stamp. Both files are
            # written together, so the pair is already consistent and
            # nothing is owed.
            return 0
        if hot_at < cold_at:
            LOGGER.warning(
                "Activity clocks on disk are %.0f s older than the "
                "main storage file, which means the last write pair "
                "was torn between its two files. The hot file is used "
                "regardless: a clock this slightly stale heals on the "
                "device's next report, while discarding it would reset "
                "the whole fleet",
                cold_at - hot_at,
            )
        merged = 0
        for device_id, fields in (hot.get("clocks") or {}).items():
            record = devices.get(device_id)
            if record is None or not isinstance(fields, dict):
                continue
            for field in CLOCK_FIELDS:
                if field in fields:
                    record[field] = fields[field]
            merged += 1
        return merged

    @callback
    def _mark_cold_dirty(self) -> None:
        """Note a change to something the hot file does not carry.

        An episode, an incident, a system event, or a device record
        joining or leaving the registry. Setting the flag is the whole
        job: the render tick's scheduler reads it when the storage
        write interval closes and takes the main file along with the
        hot one, main file first so the hot stamp is always the newer
        of the pair (ruling #165). Nothing here schedules a write of its own.
        The old arrangement did, on its own debounce with its own cap,
        and two independent schedules against one pair of files is the
        race that produced a main file newer than the clocks file, the
        state the final phase of the storage split cannot survive.

        The wait this buys is bounded by the interval and is spent on
        forensic rows alone: anything judgment-bearing is critical and
        writes both files within the tick that detected it (ruling #100).
        """
        self._cold_dirty = True
        self._dirty = True

    def _clocks_to_save(self) -> dict[str, Any]:
        """Return only the fields an ordinary report changes.

        Nine of them, taken from what _record_activity and the signal
        path actually write. Everything else is cold and stays in the
        main file.
        """
        clocks: dict[str, Any] = {}
        for device_id, record in self.data[DATA_DEVICES].items():
            if not isinstance(record, dict):
                continue
            # Only fields the record actually holds. Writing a
            # missing one as None would put the key in the hot file,
            # and the merge would then plant that None back on load
            # ahead of the defaults that fill an old record in, so a
            # device stored before the signal fields existed would
            # come back with None where it
            # should have gained a zero.
            clocks[device_id] = {
                field: record[field]
                for field in CLOCK_FIELDS
                if field in record
            }
        return {
            DATA_SAVED_AT: dt_util.utcnow().timestamp(),
            "clocks": clocks,
        }

    async def _save_now(self) -> None:
        """The single immediate-save path.

        Every direct save runs through here so the bookkeeping can
        never be missed at one of the scattered sites: both tier
        flags clear, and the pending flag clears because the store
        cancels its pending delayed write when a direct save lands.
        """
        # Order matters. The main file goes first so that if the pair
        # is ever torn, the survivor is the one holding everything;
        # the hot file's stamp then tells the next load that it is the
        # older of the two and must not be merged over the newer.
        await self._store.async_save(self._data_to_save())
        await self._clock_store.async_save(self._clocks_to_save())
        self._dirty = False
        self._critical = False
        self._next_routine_save = (
            self.hass.loop.time() + self.coalesce_seconds
        )

    @property
    def coalesce_seconds(self) -> float:
        """Return the routine-save interval in seconds.

        Live from options (ruling #117), clamped to the offered band. Only
        routine activity waits: verdicts, battery flips, list changes
        and acknowledgments always write immediately, so this governs
        wear and crash-window, never correctness.
        """
        raw = int(
            self.entry.options.get(
                CONF_COALESCE_MINUTES, DEFAULT_COALESCE_MINUTES
            )
        )
        minutes = min(
            COALESCE_MINUTES_MAX, max(COALESCE_MINUTES_MIN, raw)
        )
        return minutes * 60.0

    def watched_records(self) -> list[tuple[str, dict[str, Any]]]:
        """Return the records of devices currently being watched.

        A record used to imply a watched device, so every surface
        walked the record store directly. That stopped being true
        when a set-aside device began keeping what it had learned
        (ruling #257), and the ignore list made twenty-two of them at
        once: the battery report went on calling phones watched cells
        while the classification file three columns over called them
        ignored, and one of them reached the problem list asking a
        person to act on a device this integration had been told to
        stop looking at.

        So the rule is one line and lives in one place: a surface
        that reads the record store filters to the watched set first.
        The record survives, unjudged and unreported, exactly as the
        muting ladders promise; what stops is the reporting of it.
        """
        devices = self.data.get(DATA_DEVICES) or {}
        return [
            (device_id, record)
            for device_id, record in devices.items()
            if device_id in self._watched
        ]

    @property
    def ignored_integrations(self) -> frozenset[str]:
        """Return the integrations never to watch.

        A person's list, defaulting to the four that publish
        measurements of nothing this house can be judged on. The
        default applies only while the option has never been saved:
        once the screen is submitted the list is theirs, empty
        included, because a default that reasserted itself would make
        the setting impossible to switch off.
        """
        stored = self.entry.options.get(CONF_IGNORED_INTEGRATIONS)
        if stored is None:
            return frozenset(DEFAULT_IGNORED_INTEGRATIONS)
        return frozenset(stored)

    @property
    def retention_days(self) -> int:
        """Return how many days of the long series to keep.

        The user's, and about memory rather than judgment: every
        verdict is computed from the most recent DAILY_MAX_KEEP days
        whatever this says (ruling #131). The floor of thirty is what makes
        that safe, since no setting can starve a fourteen-day window.
        """
        return max(
            RETENTION_DAYS_MIN,
            min(
                RETENTION_DAYS_MAX,
                int(
                    self.entry.options.get(
                        CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS
                    )
                ),
            ),
        )

    def _handle_unclean_restart(self, loaded: dict[str, Any]) -> None:
        """Reset the clocks a power cut made unreadable (ruling #163).

        A clean stop stamps the moment it happened, so ruling #160 can credit
        every device the silence nobody was listening to and the
        arithmetic is right. A power cut leaves no such stamp: the
        newest thing on disk is up to a whole write interval old, and
        any device that reported inside that unsaved window carries a
        clock later than the anchor, fails the test that grants the
        credit, and is judged across an outage it could not have
        reported through. That is not a hypothetical: on 2026-07-31 a
        thirty-minute cut on the development fleet produced nine
        frozen verdicts, one of them a device whose clock read nine
        minutes past the anchor.

        Crediting every device instead does not fix it either, because
        a device whose single daily report fell inside the blackout
        has a genuinely stale clock and would be convicted hours
        before it was ever going to speak.

        So the clock is reset, with one exception that carries all the
        weight. A device already on the problem list keeps its clock,
        whatever the kind: a battery flagged two days ago, a device
        still unavailable, a device already frozen. Resetting those
        would forgive a fault already known and make the integration
        do what the blueprints did, reporting a device recovered
        because a restart swept it back to life. Everything else was
        merely churning along, the integration cannot know what it did
        while the house was dark, and a restart of the server, the
        router and the coordinator together is an intervention in the
        same sense a hand on the battery is.

        The silence a reset device had genuinely accumulated before
        the cut is banked rather than thrown away. It is a lower bound
        and not a measurement, but the day's maximum keeps the larger
        of what it holds and what arrives, so a lower bound can only
        move that figure toward the truth and never past it;
        discarding it leaves the maximum lower than the device
        actually earned. Only the clock fields move: the event count,
        the learned series, the first-observed stamp, and every
        battery and signal field are what the device earned and are
        untouched.
        """
        now = dt_util.utcnow().timestamp()
        anchor = self._last_alive
        if anchor is None:
            # No stamp on either file, so there is no last known-alive
            # moment. Every part of this rule is measured from that
            # moment: the truncated gap is anchored to it, the episode
            # closes at it, and the credit it exists to protect (ruling #160)
            # is itself inert without it. Resetting here would destroy
            # every device's real last activity and buy nothing, so
            # the safe reading of an unstamped file is to leave it
            # alone. Only a file written before the split can be in
            # this
            # state, and those were written by versions that always
            # wrote the pair together.
            LOGGER.debug(
                "Unclean restart: no storage stamp to measure against, "
                "so every clock is left as it was"
            )
            return
        protected = {
            item.get(TODO_DEVICE_ID)
            for item in loaded.get(DATA_TODO_ITEMS) or []
            if item.get(TODO_DEVICE_ID)
        }
        reset = 0
        bankers: set[str] = set()
        for device_id, record in (loaded.get(DATA_DEVICES) or {}).items():
            if not isinstance(record, dict) or device_id in protected:
                continue
            last = record.get(DEV_LAST_ACTIVITY)
            if not isinstance(last, (int, float)):
                continue
            if anchor is not None and anchor > last:
                truncated = anchor - last
                current = record.get(DEV_TODAY_MAX)
                if current is None or truncated > current:
                    record[DEV_TODAY_MAX] = truncated
                    bankers.add(device_id)
            record[DEV_LAST_ACTIVITY] = now
            # A clock that no longer describes a real report cannot
            # go on carrying a taint earned before it, because the
            # gap that taint was waiting to mute no longer exists.
            record[DEV_TAINTED] = False
            reset += 1

        # Open episodes close at the last known-alive moment, so the
        # episode record and the clock cannot contradict each other.
        # A row whose device banked a truncated gap says so in the
        # LEARNED cell, so a widened rhythm traceable to a lower bound
        # is auditable from the row rather than looking like an
        # ordinary measurement.
        stamped = 0
        for episode in loaded.get(DATA_EPISODES) or []:
            if episode.get(EP_ENDED) is not None:
                continue
            episode[EP_ENDED] = EPISODE_ENDED_UNCLEAN
            episode[EP_AT] = anchor
            if episode.get(EP_DEVICE_ID) in bankers:
                episode[EP_LEARNED] = EPISODE_LEARNED_TRUNCATED
            stamped += 1
        banked = len(bankers)

        self._pending_unclean = reset
        LOGGER.warning(
            "Unclean restart: no clean-stop marker on the storage file, "
            "so %d device clock(s) were reset to this start and %d kept "
            "for devices already on the problem list. %d banked a "
            "truncated pre-cut gap; %d open silence episode(s) closed as "
            "an unclean shutdown",
            reset,
            len(protected),
            banked,
            stamped,
        )

    @staticmethod
    def _count_orphan_episodes(loaded: dict[str, Any]) -> dict[str, Any]:
        """Count episodes with no ending, and report nothing else.

        Observation only: a non-zero count is a finding to read rather
        than a fault to act on (ruling #167).

        After a clean stop every open episode has been stamped, and
        after an unclean one ruling #163 has just stamped them too, so by the
        time this runs an episode carrying no ending is an orphan: a
        row whose closing never reached disk. The window in which one
        is visible is narrow, because the next intervention of any
        kind stamps every open row it finds, which would give this one
        an ending at the wrong moment and make it look correct
        forever. Boot is the only place it can be seen.

        The test is the ending, never the lag. An episode legitimately
        sits ended-but-awaiting-lag until the device speaks again, and
        counting those would cry wolf every morning.

        It closes nothing. ruling #163 is the only thing that closes an
        episode at a restart, because two independent mechanisms
        against one record is a fault class rather than a safeguard,
        and when a row later reads wrong you want to know which one
        wrote it.
        """
        now = dt_util.utcnow().timestamp()
        orphans = [
            episode
            for episode in loaded.get(DATA_EPISODES) or []
            if episode.get(EP_ENDED) is None
        ]
        oldest = None
        if orphans:
            since = [
                episode.get(EP_SINCE)
                for episode in orphans
                if isinstance(episode.get(EP_SINCE), (int, float))
            ]
            if since:
                oldest = now - min(since)
        found = {
            "count": len(orphans),
            "devices": len({episode.get(EP_DEVICE_ID) for episode in orphans}),
            "oldest_seconds": oldest,
        }
        if orphans:
            LOGGER.warning(
                "Episode integrity: %d silence episode(s) across %d "
                "device(s) carry no ending, the oldest %s old. A closing "
                "did not reach disk; nothing has been changed",
                found["count"],
                found["devices"],
                _span(oldest) if oldest else "unknown",
            )
        else:
            LOGGER.debug("Episode integrity: no episode without an ending")
        return found

    @callback
    def _note_downtime(
        self, loaded: dict[str, Any], hot: dict[str, Any] | None
    ) -> None:
        """Record how long nothing was listening before this start.

        The newer of the two file stamps is the last moment the system
        is known to have been running. After a clean stop that is
        exact, because shutdown writes both files; after a crash it is
        up to one hot-file window early, which errs toward crediting
        too much rather than too little and is the safer direction.
        """
        self._started_at = dt_util.utcnow().timestamp()
        stamps = [
            v
            for v in (loaded.get(DATA_SAVED_AT), (hot or {}).get(DATA_SAVED_AT))
            if isinstance(v, (int, float))
        ]
        if not stamps:
            return
        self._last_alive = max(stamps)
        self._downtime = max(
            0.0, dt_util.utcnow().timestamp() - self._last_alive
        )
        if self._downtime > 0.0:
            LOGGER.debug(
                "Nothing was listening for %.0f s before this start; "
                "that silence is not counted against any device",
                self._downtime,
            )

    async def _on_hass_stop(self, _event: Event) -> None:
        """Stamp open silences as intervention-ended, then flush.

        A restart is an intervention: it can revive a stuck radio,
        so any silence running when it happens is truncated rather
        than completed. Stamping here, before the flush, is what
        makes the distinction survive into the next boot.

        The flush is unconditional, and that is the point of it. It
        used to run only when something was outstanding, but the
        stamp above reaches _mark_cold_dirty, whose last act is to
        clear the very flag that condition read. So a stop with any
        silence running skipped its own flush, left a scheduled write
        on each store, and let Home Assistant's final-write stage
        write them afterwards. That stage stamps each file as it goes
        and in no fixed order, so the small file could come out the
        older of the two, and the next start then refuses to merge it
        (ruling #101). Under the current phase that costs nothing, because
        the main file still carries the clocks; under the phase that
        removes them it would leave every device with no clock at all.
        One write on a stop is not worth a condition.

        Flushing also cancels both scheduled writes, so the stop is
        the last thing to touch either file. That is what makes the
        saved stamp the true moment of stopping, which is the value
        ruling #160 measures observed silence against.
        """
        self._stamp_intervention(
            EPISODE_ENDED_REBOOT, dt_util.utcnow().timestamp()
        )
        # The clean-stop marker (ruling #163). Set before the flush, so the
        # write below carries it. Its absence at the next load is the
        # only evidence that the machine went down without being
        # asked to: a power cut leaves a saved_at stamp that looks
        # exactly like an ordinary interval write, so no comparison
        # of stamps can tell the two apart.
        self.data[DATA_CLEAN_STOP] = True
        await self._save_now()

    @property
    def downtime(self) -> float:
        """Return how long nothing was listening before this start.

        Exposed for the diagnostics rather than computed there,
        because the value is settled once at load from the two file
        stamps and any second derivation would be a second opinion
        about the same fact.
        """
        return self._downtime

    @property
    def last_alive(self) -> float | None:
        """Return the last moment the system is known to have run."""
        return self._last_alive

    @property
    def orphan_episodes(self) -> dict[str, Any]:
        """Return what the boot integrity count found (ruling #167)."""
        return dict(self._orphan_episodes)

    @property
    def setup_count(self) -> int:
        """Return how many times the integration has set up."""
        return int(self.data.get(DATA_SETUP_COUNT, 0))

    @property
    def first_installed(self) -> str | None:
        """Return the ISO timestamp of the first ever setup."""
        return self.data.get(DATA_FIRST_INSTALLED)
