# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: detect_freeze.py, Version: 0.15.8 (2026-08-18)

"""Freeze: the learned rhythm, the window, and the verdict.

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

import math
from typing import Any
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.util import dt as dt_util
from .records import BAD_STATES
from .stacks import reader_for_domain

from .const import (
    CONF_FREEZE_DELTA_HIGH,
    CONF_FREEZE_DELTA_LOW,
    CONF_FREEZE_EXCLUDED_DEVICES,
    CONF_FREEZE_EXCLUDED_INTEGRATIONS,
    CONF_FREEZE_EXCLUDED_LABELS,
    CONF_TAINT_FLOOR,
    CONF_TAINT_SHARE,
    DAILY_MAX_KEEP,
    DATA_DEVICES,
    DEFAULT_FREEZE_DELTA_HIGH_HR,
    DEFAULT_FREEZE_DELTA_LOW_MIN,
    DEFAULT_TAINT_FLOOR_MINUTES,
    DEFAULT_TAINT_SHARE_PCT,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_NEVER_REPORTED,
    FREEZE_CATEGORY_PRIORITY,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_UNKNOWN,
    FREEZE_NOT_REPORTED_SECONDS,
    FREEZE_REF_RHYTHM_FAST,
    FREEZE_REF_RHYTHM_SLOW,
    FREEZE_UNAVAILABLE_DEBOUNCE,
    LEARNING_MIN_DAYS,
    LOGGER,
    PAIRING_GRACE_SECONDS_DEFAULT,
    RATCHET_FAST_ALLOWANCE,
    RATCHET_FAST_RHYTHM,
    RATCHET_SLOW_ALLOWANCE,
    RATCHET_SLOW_RHYTHM,
    TAINT_UNAVAILABLE,
    TRIM_MIN_SAMPLES,
    TRIM_TOP_K,
)


class FreezeMixin:
    """Freeze: the learned rhythm, the window, and the verdict."""

    @staticmethod
    def _trimmed_maximum(
        daily_maximum_gaps: list[float],
    ) -> tuple[float | None, set[int]]:
        """Return (operative rhythm, indices of set-aside outliers).

        The trimmed maximum is the Step 4 window rhythm, previewed
        here for display: the top TRIM_TOP_K daily maxima are set
        aside as suspected anomalies, and the rhythm is the maximum
        of the survivors. One anomalous day therefore moves nothing,
        while a spike that recurs leaves a second high value among
        the survivors and correctly raises the rhythm. Below
        TRIM_MIN_SAMPLES days nothing is trimmed: with so few samples
        an apparent outlier cannot be told from the true rhythm.

        Only the most recent DAILY_MAX_KEEP days are read, however
        many are stored (ruling #131). The trimmed maximum of ninety
        days
        is higher than of fourteen, because more days mean more
        chances at a long gap, so reading the whole series would
        quietly widen every freeze window on the fleet. Sliced here,
        in the one place the rhythm is computed, so no caller can
        forget; the two callers that use the returned indices to
        style a cell slice their own copy to match.
        """
        daily_maximum_gaps = daily_maximum_gaps[-DAILY_MAX_KEEP:]
        if not daily_maximum_gaps:
            return None, set()
        if len(daily_maximum_gaps) < TRIM_MIN_SAMPLES:
            return max(daily_maximum_gaps), set()
        by_value_descending = sorted(
            range(len(daily_maximum_gaps)),
            key=lambda index: daily_maximum_gaps[index],
            reverse=True,
        )
        set_aside_indices = set(by_value_descending[:TRIM_TOP_K])
        survivors = [
            gap
            for index, gap in enumerate(daily_maximum_gaps)
            if index not in set_aside_indices
        ]
        return max(survivors), set_aside_indices

    def _freeze_deltas(self) -> tuple[float, float]:
        """Return (delta_low, delta_high) in seconds from the options.

        The two freeze-config sliders: delta-low a fast-end grace
        floor in minutes, delta-high a slow-end grace ceiling in
        hours. Stored in their slider units, returned in seconds
        because the margin math is all in seconds.
        """
        options = self.entry.options
        low_min = options.get(
            CONF_FREEZE_DELTA_LOW, DEFAULT_FREEZE_DELTA_LOW_MIN
        )
        high_hr = options.get(
            CONF_FREEZE_DELTA_HIGH, DEFAULT_FREEZE_DELTA_HIGH_HR
        )
        return float(low_min) * 60.0, float(high_hr) * 3600.0

    def _freeze_grace(self, rhythm: float) -> float:
        """Return the grace margin for a rhythm, in seconds (ruling #85).

        grace = a * rhythm^p, where a and p are solved so the curve
        passes through delta-low grace at the fast reference rhythm
        and delta-high grace at the slow one. The two deltas therefore
        set the whole shape, not just the ends, and the result is
        clamped to [delta-low, delta-high] so they double as the hard
        floor and ceiling. The rhythm itself is never touched here: it
        is the measured trimmed maximum, and grace is only the
        patience added on top of it.
        """
        delta_low, delta_high = self._freeze_deltas()
        # Solve the power curve through the two reference points.
        p = math.log(delta_high / delta_low) / math.log(
            FREEZE_REF_RHYTHM_SLOW / FREEZE_REF_RHYTHM_FAST
        )
        a = delta_low / (FREEZE_REF_RHYTHM_FAST**p)
        grace = a * (rhythm**p)
        return min(delta_high, max(delta_low, grace))

    def _resurrection_cap(self, record: dict[str, Any]) -> float | None:
        """Return the most a convicted device's gap may teach (ruling #166).

        rhythm plus a * rhythm^p, the same power-curve solver as the
        grace (ruling #85) through the ratchet anchors: fast devices may step
        half their rhythm, slow ones a tenth, falling continuously
        between. The rhythm is read as it stands at the moment of
        recovery, ordinary staleness accepted, no special midnight
        handling. None means the device is unarmed, and an unarmed
        device can never stand convicted, so no cap is needed.
        """
        daily = record[DEV_DAILY_MAX]
        if len(daily) < FREEZE_ARMING_DAYS:
            return None
        rhythm, _ = self._trimmed_maximum(daily)
        if rhythm is None or rhythm <= 0:
            return None
        p = math.log(RATCHET_SLOW_ALLOWANCE / RATCHET_FAST_ALLOWANCE) / math.log(
            RATCHET_SLOW_RHYTHM / RATCHET_FAST_RHYTHM
        )
        a = RATCHET_FAST_ALLOWANCE / (RATCHET_FAST_RHYTHM**p)
        return rhythm + a * (rhythm**p)

    def _freeze_window(self, record: dict[str, Any]) -> float | None:
        """Return the freeze window for a device, in seconds, or None.

        The window is the learned rhythm plus the grace margin. None
        means the device is not yet armed for freeze: it has too few
        learned days for a trustworthy rhythm (the arming gate, ruling #27),
        so it is watched for unavailable and unknown but never called
        frozen, because there is no window to miss.
        """
        daily = record[DEV_DAILY_MAX]
        if len(daily) < FREEZE_ARMING_DAYS:
            return None
        rhythm, _ = self._trimmed_maximum(daily)
        if rhythm is None or rhythm <= 0:
            return None
        return rhythm + self._freeze_grace(rhythm)

    def _recovered_during_pairing(self, device_id: str, now: float) -> bool:
        """Return whether this device recovered during a pairing window.

        A pairing window is a coordinator-wide state, so any device
        behind that coordinator which recovers while the window is
        open (or within the grace after it closed) is a pairing
        candidate (ruling #145). The available per-device signal is the
        integration domain, and which stack owns a domain is that
        stack's own question rather than this detector's (ruling #218):
        a domain no stack claims, or a stack with no reader, gives no
        reader here. Ownership is the widest claim a stack can make
        about one device, so a device that merely shares a domain with
        the stack would also be caught, but the only cost is a single
        discarded gap, which is the conservative, fail-safe direction.
        Everything is guarded: no reader, no bridge, or any failure
        returns False and the taint decision stands (ruling #147).
        """
        reader = reader_for_domain(
            self._bridge_readers, self._watched.get(device_id)
        )
        if reader is None:
            return False
        try:
            return reader.pairing_active_within(
                PAIRING_GRACE_SECONDS_DEFAULT, now
            )
        except Exception as err:  # noqa: BLE001 - a fault falls to the taint
            LOGGER.debug(
                "Pairing reader for %s faulted, treating as not pairing: %s",
                device_id,
                err,
            )
            return False

    @staticmethod
    def _retract_today_max(record: dict[str, Any], gap: float) -> None:
        """Undo a daily-max bump a now-discarded pairing gap just made.

        The gap update runs before the pairing check, so a pairing gap
        that was the day's largest has to be pulled back out, or it
        would widen the learned rhythm it should never touch. Only the
        exact value is retracted, and only when it is the current max,
        so an unrelated larger gap is left alone.
        """
        if record[DEV_TODAY_MAX] is not None and record[DEV_TODAY_MAX] == gap:
            record[DEV_TODAY_MAX] = None

    def _taint_debounce(self, record: dict[str, Any]) -> float:
        """Return the unavailable a device tolerates before a taint.

        Short absences are mesh blips and the silence around them is
        still learned; a long one is real downtime and its gap is
        discarded (ruling #137).

        A blip under this is a hiccup and the surrounding silence is
        learned; an unavailable at or over it is real downtime and
        the completed gap is discarded. The value is a floor plus a
        share of the device's own freeze window, so a fast device
        keeps the floor while a slow one earns proportionally more
        patience. An unarmed device has no window yet, so it falls
        back to the floor alone, which is correct: with nothing
        learned there is no grace to take a share of.
        """
        floor = (
            float(
                self.entry.options.get(
                    CONF_TAINT_FLOOR, DEFAULT_TAINT_FLOOR_MINUTES
                )
            )
            * 60.0
        )
        share = (
            float(
                self.entry.options.get(
                    CONF_TAINT_SHARE, DEFAULT_TAINT_SHARE_PCT
                )
            )
            / 100.0
        )
        window = self._freeze_window(record)
        if window is None:
            return floor
        return floor + window * share

    def _device_down_category(
        self, device_id: str, record: dict[str, Any], now: float
    ) -> str | None:
        """Return the down category for a device, or None if alive.

        The rule (#device-level): if any live entity is fresh, the
        device is alive, whatever its other entities read. A device is
        down only when nothing on it is reporting. Then the category
        is read from what the entities show, and a mix resolves to the
        most definite state (unavailable dominates frozen dominates
        unknown), because a device with most entities unavailable is a
        dead device whose remaining entities have simply not flipped
        yet.
        """
        # A globally-excluded or freeze-excluded device keeps its
        # clock and rhythm but is never given a verdict of any kind.
        # Global exclusion suppresses all judgment, so it is checked
        # here rather than only filtered from the report: no verdict
        # is computed or stored for a device the person has told the
        # integration to ignore.
        if (
            device_id in self._excluded_devices
            or self._freeze_excluded(device_id)
        ):
            return None

        # Never reported: zero lifetime events past the grace window.
        # Checked first because it is categorically different from a
        # device that reported and stopped, and because such a device
        # has no rhythm to miss and may have no live entity to read.
        if record[DEV_EVENT_COUNT] == 0 and record[DEV_LAST_ACTIVITY] is None:
            first = record.get(DEV_FIRST_OBSERVED)
            if first is not None:
                try:
                    observed = dt_util.parse_datetime(first)
                    age = now - observed.timestamp() if observed else 0.0
                except (ValueError, AttributeError):
                    age = 0.0
                if age >= FREEZE_NOT_REPORTED_SECONDS:
                    return FREEZE_CATEGORY_NEVER_REPORTED
            return None

        window = self._freeze_window(record)

        # Frozen: armed, and silent past its window while entities
        # still hold values. Judged first because it is the timer's
        # own verdict.
        silence = self._observed_silence(record, now)
        frozen = (
            window is not None
            and silence is not None
            and silence >= window
        )

        states = self._live_entity_states(device_id)
        if not states:
            # No live entities to read. A silent armed device with no
            # readable state is still a freeze by its clock.
            return FREEZE_CATEGORY_FROZEN if frozen else None

        any_unavailable = STATE_UNAVAILABLE in states
        any_unknown = STATE_UNKNOWN in states
        all_bad = all(s in BAD_STATES for s in states)

        # If every live entity reads bad, the device is down now,
        # regardless of the clock: this is the unavailable/unknown
        # path, which needs no arming because it reads present state.
        if all_bad:
            present = {
                FREEZE_CATEGORY_UNAVAILABLE: any_unavailable,
                FREEZE_CATEGORY_UNKNOWN: any_unknown,
                FREEZE_CATEGORY_FROZEN: frozen,
            }
            for category in FREEZE_CATEGORY_PRIORITY:
                if present.get(category):
                    return category
            return FREEZE_CATEGORY_UNAVAILABLE

        # Some entity is not bad. If the clock says frozen and the
        # non-bad entities are stale (not fresh), the device is
        # frozen; a genuinely fresh entity would have re-armed the
        # timer, so reaching here with frozen True means the values
        # are held, not live.
        if frozen:
            return FREEZE_CATEGORY_FROZEN
        return None

    def _apply_freeze_verdict(
        self, device_id: str, record: dict[str, Any], now: float
    ) -> bool:
        """Judge one device and store the verdict if it changed.

        Returns True when the verdict flipped, so the caller can
        refresh the sensor once per flip rather than on every reading.
        A debounce holds an unavailable or unknown verdict
        until the device has been down long enough to rule out a
        mid-transition flip; the frozen verdict needs no debounce
        because its window already is the wait.
        """
        category = self._device_down_category(device_id, record, now)
        # Records written before the freeze family existed predate
        # these fields, and the storage
        # prune removes unknown keys but never adds missing ones, so
        # such a record arrives here without them. Default them before
        # reading, or the direct read raises KeyError and, with the
        # sweep's per-device guard, that record is skipped.
        record.setdefault(DEV_FROZEN_CATEGORY, None)
        record.setdefault(DEV_FROZEN_SINCE, None)
        current = record[DEV_FROZEN_CATEGORY]

        if category in (
            FREEZE_CATEGORY_UNAVAILABLE,
            FREEZE_CATEGORY_UNKNOWN,
        ):
            # Debounce the transition: only publish once the device
            # has read down for longer than a quick-succession flip.
            since = record.get(DEV_FROZEN_SINCE)
            if current is None:
                if since is None:
                    record[DEV_FROZEN_SINCE] = now
                    self._dirty = True
                    # Critical, not merely dirty. This stamp is what
                    # the debounce counts from, and its clear below is
                    # an earlier fix; a crash between one reaching
                    # disk and the other not is how a device comes
                    # back reported down for hours.
                    self._critical = True
                    return False
                if (now - since) < FREEZE_UNAVAILABLE_DEBOUNCE:
                    return False

        if category == current:
            # A blip stamps a down-since before any verdict is
            # published. If the device came back by republishing a
            # retained value, its contact clock never advanced, so the
            # report path never ran and nothing there cleared the
            # stamp. Clear it here instead: a stamp with no verdict
            # behind it has nothing left to time, and leaving it dates
            # the next outage from the old blip, which both overstates
            # how long the device has been down and skips the debounce
            # that outage was owed. A published verdict is untouched,
            # so a republish still cannot erase a standing silence
            # (ruling #124).
            if (
                category is None
                and record.get(DEV_FROZEN_SINCE) is not None
            ):
                record[DEV_FROZEN_SINCE] = None
                self._dirty = True
                self._critical = True
            return False

        record[DEV_FROZEN_CATEGORY] = category
        if category is None:
            record[DEV_FROZEN_SINCE] = None
        elif current is None:
            record[DEV_FROZEN_SINCE] = record.get(DEV_FROZEN_SINCE) or now
        self._dirty = True
        self._critical = True
        LOGGER.debug(
            "Device %s freeze verdict: %s",
            self._device_name(device_id),
            category or "alive",
        )
        return True

    def _clear_freeze_verdict(
        self, device_id: str, record: dict[str, Any]
    ) -> None:
        """Clear a device's freeze verdict on its first real report.

        A device that reports is alive by definition, so its verdict
        and the down-since stamp are cleared at once. Called from the
        report path, this is the live-recovery half of detection: the
        moment a frozen device speaks, it leaves the report.
        """
        if record.get(DEV_FROZEN_CATEGORY) is not None:
            record[DEV_FROZEN_CATEGORY] = None
            record[DEV_FROZEN_SINCE] = None
            self._dirty = True
            self._critical = True
            # The moment a down device speaks, its item goes: the
            # recovery half of the lifecycle runs here in the report
            # path, not on the next tick.
            self._sync_problem_list()
            self._notify()
        elif record.get(DEV_FROZEN_SINCE) is not None:
            # A pending, un-published down stamp (inside the debounce);
            # clear it silently, no verdict was ever shown.
            record[DEV_FROZEN_SINCE] = None
            self._dirty = True

    def _judge_all_devices(self) -> None:
        """Judge every watched device for a freeze verdict.

        Runs on a timer tick and at startup. A flip on any device
        refreshes the sensors once. This is the sweep that fires the
        frozen verdict when a window closes with no report, and the
        unavailable/unknown verdict once the debounce clears.
        """
        now = dt_util.utcnow().timestamp()
        self._note_silences(now)
        self._trim_episodes(now)
        flipped = False
        for device_id in self._watched:
            record = self.data[DATA_DEVICES].get(device_id)
            if not isinstance(record, dict):
                continue
            # Guard each device: one malformed record must never kill
            # the whole sweep, which would stop verdicts, saving, and
            # refreshing for every device, which once crashed the
            # sixty-second tick.
            try:
                if self._apply_freeze_verdict(device_id, record, now):
                    flipped = True
            except Exception:  # noqa: BLE001
                LOGGER.warning(
                    "Skipped a device in the freeze sweep after an "
                    "unexpected error judging it: %s",
                    self._device_name(device_id),
                )
        if flipped:
            self._notify()

    def _observed_silence(
        self, record: dict[str, Any], now: float
    ) -> float | None:
        """How long this device was silent while anyone was listening.

        Wall-clock silence counts the time the system was off, which
        no device is responsible for. On return the fastest reporters
        cross their windows first, purely by arithmetic: a six-minute
        power cut once produced twenty-three frozen verdicts against
        devices whose windows are two to four minutes, and touched
        nothing with an hour-scale window (ruling #160). What is counted
        instead is the silence before the last save plus the silence
        since this start, so the unwatched middle counts against
        nobody. The credit lapses the moment a device reports, its
        clock then postdating the outage, and it needs no cap: a
        device already silent beforehand carries that silence into
        the sum and is still caught the instant the system returns.
        """
        last = record.get(DEV_LAST_ACTIVITY)
        if not isinstance(last, (int, float)):
            return None
        silence = now - last
        if (
            self._downtime > 0.0
            and self._last_alive is not None
            and last <= self._last_alive
        ):
            silence -= self._downtime
        return max(0.0, silence)

    @property
    def freeze_tracked_count(self) -> int:
        """Return how many devices are eligible for freeze detection.

        A device with a learned rhythm (an established reporting
        cadence) is freeze-judgeable, minus the global device
        excludes. This counts the set freeze detection judges; the
        per-section freeze exclude narrows it further.
        """
        return sum(
            1
            for device_id, record in self.watched_records()
            if len(record.get(DEV_DAILY_MAX) or []) >= LEARNING_MIN_DAYS
            and device_id not in self._excluded_devices
        )

    @property
    def freeze_tracked_list(self) -> list[dict[str, Any]]:
        """Return the freeze-eligible devices, for the attribute."""
        return sorted(
            (
                {"name": self._display_names.get(device_id)}
                for device_id, record in self.data.get(
                    DATA_DEVICES, {}
                ).items()
                if len(record.get(DEV_DAILY_MAX) or []) >= LEARNING_MIN_DAYS
                and device_id not in self._excluded_devices
            ),
            key=lambda row: row["name"] or "",
        )

    @property
    def frozen_devices_list(self) -> list[dict[str, Any]]:
        """Return devices judged frozen, unknown, or unavailable.

        The Device: Frozen problem sensor. One row per down device,
        carrying its category (the
        worst of what its entities show) and the UTC time the verdict
        began, so a person sees what is down, how, and for how long.
        Excluded devices are suppressed from the report but keep their
        verdict, so undoing an exclude shows them again at once.
        """
        rows: list[dict[str, Any]] = []
        for device_id, record in self.watched_records():
            if device_id in self._excluded_devices:
                continue
            category = record.get(DEV_FROZEN_CATEGORY)
            if category is None:
                continue
            rows.append(
                {
                    "device_id": device_id,
                    "name": self._device_name(device_id),
                    "integration": self._watched.get(device_id, "?"),
                    "category": category,
                    "since": record.get(DEV_FROZEN_SINCE),
                }
            )
        rows.sort(key=lambda row: (row["category"], row["name"]))
        return rows

    @property
    def reportable_down_rows(self) -> list[dict[str, Any]]:
        """Return the down devices worth reporting on their own.

        Ruling #264: while a device's upstream is down, its verdict is
        recorded and not reported, because the fault is the upstream
        and the devices are its symptoms. Stopping one add-on on the
        reference system raised seventy-four problems and pushed a
        notification naming seventy-four devices without naming the
        bridge, which is the one thing a person can act on.

        Two devices survive the suppression. One whose verdict began
        before the upstream went down is genuinely broken and was
        broken already, so it keeps its row rather than vanishing into
        the outage and reappearing when the outage clears. One still
        down after the upstream returns is the most useful row of the
        week: everything else came back and this did not.
        """
        rows: list[dict[str, Any]] = []
        for row in self.frozen_devices_list:
            upstream = self.upstream_down_since(row["device_id"])
            if upstream is None:
                rows.append(row)
                continue
            _name, down_since = upstream
            since = row.get("since")
            if since is not None and since < down_since:
                rows.append(row)
        return rows

    @property
    def suppressed_down_counts(self) -> dict[str, int]:
        """Return how many devices each downed upstream is masking."""
        counts: dict[str, int] = {}
        for row in self.frozen_devices_list:
            upstream = self.upstream_down_since(row["device_id"])
            if upstream is None:
                continue
            name, down_since = upstream
            since = row.get("since")
            if since is not None and since < down_since:
                continue
            counts[name] = counts.get(name, 0) + 1
        return counts

    @property
    def frozen_devices_count(self) -> int:
        """Return how many devices are down (frozen, unavailable, or
        unknown) right now."""
        return len(self.frozen_devices_list)

    def _freeze_excluded(self, device_id: str) -> bool:
        """Return whether a device is excluded from freeze judgment
        only. The same broad-to-narrow ladder as battery and signal,
        and the same principle: the device keeps its clock and its
        learned rhythm, so re-including it is instant and arrives with
        history; it simply is never given a freeze, unavailable,
        unknown, or not-reported verdict. This is the release valve
        for a device that is intermittent by nature, silenced in the
        freeze report without being hidden from the rest.
        """
        options = self.entry.options
        if self._watched.get(device_id) in options.get(
            CONF_FREEZE_EXCLUDED_INTEGRATIONS, []
        ):
            return True
        if self._device_labels.get(device_id, frozenset()) & set(
            options.get(CONF_FREEZE_EXCLUDED_LABELS, [])
        ):
            return True
        return device_id in options.get(CONF_FREEZE_EXCLUDED_DEVICES, [])

    @staticmethod
    def _coerce_taint_reasons(devices: dict[str, dict[str, Any]]) -> int:
        """Give a stored boolean taint the reason it always meant.

        Before ruling #164 the field was true or false, and the only writer
        was the unavailable path, so a stored true means exactly that.
        False is left alone: falsy is still how every caller asks
        whether a device is tainted. Returns how many were converted,
        zero once storage has been written by this version.
        """
        converted = 0
        for record in devices.values():
            if record.get(DEV_TAINTED) is True:
                record[DEV_TAINTED] = TAINT_UNAVAILABLE
                converted += 1
        return converted
