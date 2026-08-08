# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: detect_signal.py, Version: 0.12.15 (2026-08-08)

"""Signal: the learned floor, the line, dwell, and the rails.

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
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_SIGNAL_ANOMALY_TRIM,
    CONF_SIGNAL_EXCLUDED_DEVICES,
    CONF_SIGNAL_EXCLUDED_INTEGRATIONS,
    CONF_SIGNAL_EXCLUDED_LABELS,
    CONF_SIGNAL_MARGIN,
    CONF_SIGNAL_RED,
    DATA_DEVICES,
    DEFAULT_SIGNAL_ANOMALY_TRIM,
    DEFAULT_SIGNAL_MARGIN,
    DEFAULT_SIGNAL_RED,
    DEV_SIGNAL_BELOW_SINCE,
    DEV_SIGNAL_BELOW_TODAY,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_LINE,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_DWELL_DAILY,
    DEV_SIGNAL_RAIL_COUNT,
    DEV_SIGNAL_LAST_CHANGE,
    DEV_SIGNAL_SUM,
    DEV_SIGNAL_SUM_SQ,
    DEV_SIGNAL_TODAY_MAX,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_VALUE,
    GOOD_STATE_CEILING_SD,
    SIGNAL_CEILING_CLEARANCE_LQI,
    SIGNAL_CEILING_CLEARANCE_RSSI,
    RAIL_CONFIRM_DAYS,
    SIGNAL_ANOMALY_TRIM_MAX,
    SIGNAL_ANOMALY_TRIM_MIN,
    SIGNAL_DAYS_KEEP,
    SIGNAL_MARGIN_MAX,
    SIGNAL_MARGIN_MIN,
    SIGNAL_NAME_TERMS,
    SIGNAL_RAIL_LQI,
    SIGNAL_RAIL_RSSI,
    SIGNAL_RED_MAX,
    SIGNAL_RED_MIN,
    SIGNAL_TRIM_LADDER_MAX,
    SIGNAL_TRIM_PER_WEEK,
    TODO_DEVICE_ID,
    TODO_KINDS,
)


class SignalMixin:
    """Signal: the learned floor, the line, dwell, and the rails."""

    def _roll_dwell(self, record: dict[str, Any], now: float) -> None:
        """Close the day's dwell into the rolling daily percentages.

        An open below-timer closes at now rather than freezing at its
        last reading: a link that dies below the line was below the
        line the whole silence, so its day reads 100 percent, which is
        the truth (the completed-gap principle turned inside out,
        the completed-gap principle turned inside out). A device
        still below at midnight is
        re-stamped so the new day keeps accumulating without a seam.

        The percentage is against the full day. Recording starts from
        day one while the floor is still settling; the early numbers
        are provisional the same way rhythm floors were before day 7,
        and are recorded anyway rather than gated.
        """
        below_since = record.get(DEV_SIGNAL_BELOW_SINCE)
        accumulated = float(record.get(DEV_SIGNAL_BELOW_TODAY) or 0.0)
        if below_since is not None:
            accumulated += max(0.0, now - below_since)
            record[DEV_SIGNAL_BELOW_SINCE] = now
        had_line = self._danger_line(record) is not None
        if had_line:
            pct = min(100.0, 100.0 * accumulated / 86400.0)
            record.setdefault(DEV_SIGNAL_DWELL_DAILY, []).append(
                round(pct, 2)
            )
            del record[DEV_SIGNAL_DWELL_DAILY][:-self.retention_days]
        record[DEV_SIGNAL_BELOW_TODAY] = 0.0
        self._roll_signal_stats(record)

    def _roll_signal_stats(self, record: dict[str, Any]) -> None:
        """Close the day's signal distribution into the daily series.

        Mean and standard deviation are what the Bayesian successor to
        the current thresholding needs (ruling #172), so they are recorded
        ahead of it: the day's running sum, sum of squares, and count
        become one mean, one deviation, and the day's maximum, and the
        accumulators reset for the new day. The deviation is the
        population form, and a one-reading day records zero deviation
        rather than none, because one reading genuinely varied by
        nothing. A day with no real readings appends nothing, so the
        three series stay aligned with each other but may be shorter
        than the dwell series, which records whenever a line existed.
        """
        count = int(record.get(DEV_SIGNAL_COUNT) or 0)
        if count > 0:
            # The line first, while the mean and deviation series
            # still end on yesterday: this is the line that judged
            # the day being folded, and appending today's mean first
            # would move the ceiling under it (ruling #245).
            line = self._danger_line(record)
            total = float(record.get(DEV_SIGNAL_SUM) or 0.0)
            squares = float(record.get(DEV_SIGNAL_SUM_SQ) or 0.0)
            mean = total / count
            variance = max(0.0, squares / count - mean * mean)
            record.setdefault(DEV_SIGNAL_DAILY_MEAN, []).append(
                round(mean, 2)
            )
            record.setdefault(DEV_SIGNAL_DAILY_SD, []).append(
                round(variance**0.5, 2)
            )
            record.setdefault(DEV_SIGNAL_DAILY_MAX, []).append(
                record.get(DEV_SIGNAL_TODAY_MAX)
            )
            record.setdefault(DEV_SIGNAL_DAILY_COUNT, []).append(count)
            record.setdefault(DEV_SIGNAL_DAILY_LINE, []).append(
                round(line, 2) if line is not None else None
            )
            record.setdefault(DEV_SIGNAL_DAILY_RAIL, []).append(
                int(record.get(DEV_SIGNAL_RAIL_COUNT) or 0)
            )
            for field in (
                DEV_SIGNAL_DAILY_MEAN,
                DEV_SIGNAL_DAILY_SD,
                DEV_SIGNAL_DAILY_MAX,
                DEV_SIGNAL_DAILY_COUNT,
                DEV_SIGNAL_DAILY_LINE,
                DEV_SIGNAL_DAILY_RAIL,
            ):
                del record[field][:-self.retention_days]
        record[DEV_SIGNAL_SUM] = 0.0
        record[DEV_SIGNAL_SUM_SQ] = 0.0
        record[DEV_SIGNAL_COUNT] = 0
        record[DEV_SIGNAL_RAIL_COUNT] = 0
        record[DEV_SIGNAL_TODAY_MAX] = None

    def _feed_signal(
        self, record: dict[str, Any], value: float, now: float
    ) -> None:
        """Route one signal reading, and track whether it moves.

        The floor and the dwell timer see only real readings; a rail
        value (255, -128) is the type's fill value, not a measurement,
        so it feeds neither. But every reading,
        rail or real, updates the frozen clock, because a signal that
        never changes is not reporting whatever value it is frozen at.
        last_change advances only when the value actually differs, so
        the gap since last_change is how long the signal has been
        flat while the device kept reporting.
        """
        previous = record.get(DEV_SIGNAL_VALUE)
        if previous is None or value != previous:
            record[DEV_SIGNAL_LAST_CHANGE] = now
        record[DEV_SIGNAL_VALUE] = value

        if value in (SIGNAL_RAIL_LQI, SIGNAL_RAIL_RSSI):
            record[DEV_SIGNAL_RAIL_COUNT] = (
                int(record.get(DEV_SIGNAL_RAIL_COUNT) or 0) + 1
            )
            return
        today_min = record.get(DEV_SIGNAL_TODAY_MIN)
        if today_min is None or value < today_min:
            record[DEV_SIGNAL_TODAY_MIN] = value
        today_max = record.get(DEV_SIGNAL_TODAY_MAX)
        if today_max is None or value > today_max:
            record[DEV_SIGNAL_TODAY_MAX] = value
        # The good-state accumulators (ruling #172): sum, sum of squares,
        # count. Three floats carry the day's whole distribution well
        # enough for a mean and a deviation, and no samples are kept.
        record[DEV_SIGNAL_SUM] = (
            float(record.get(DEV_SIGNAL_SUM) or 0.0) + value
        )
        record[DEV_SIGNAL_SUM_SQ] = (
            float(record.get(DEV_SIGNAL_SUM_SQ) or 0.0) + value * value
        )
        record[DEV_SIGNAL_COUNT] = (
            int(record.get(DEV_SIGNAL_COUNT) or 0) + 1
        )
        self._feed_dwell(record, value, now)

    def _feed_dwell(
        self, record: dict[str, Any], value: float, now: float
    ) -> None:
        """Run the below-the-line timer for one real reading.

        Signal is reported as dwell, not crossings (ruling #59):
        a battery moves one direction, but signal is noisy and always
        recovering, so the unit is time spent below the danger line,
        accumulated by a timer and rolled into a daily percentage. A
        momentary dip that recovers never counts for more than the
        moment it lasted.

        At the floor counts as below it: a device sitting exactly on
        its trimmed floor is living at its lows, which is the thing
        being measured. The line exists from the first recorded day
        (k=0, floor = lowest real reading) and simply settles as the
        trim ladder matures.
        """
        line = self._danger_line(record)
        below_since = record.get(DEV_SIGNAL_BELOW_SINCE)
        if line is None:
            record[DEV_SIGNAL_BELOW_SINCE] = None
            return
        if value <= line:
            if below_since is None:
                record[DEV_SIGNAL_BELOW_SINCE] = now
        elif below_since is not None:
            record[DEV_SIGNAL_BELOW_TODAY] = (
                float(record.get(DEV_SIGNAL_BELOW_TODAY) or 0.0)
                + max(0.0, now - below_since)
            )
            record[DEV_SIGNAL_BELOW_SINCE] = None

    def _danger_line(self, record: dict[str, Any]) -> float | None:
        """Return this device's line: its trimmed floor plus the
        sensitivity margin, or None with no history.

        The floor is the trimmed minimum. Rail
        values never feed it: a device whose whole history is rail has
        no floor at all rather than a false one, which was the Door
        Laundry bug (a floor of 255 from the stuck period made a
        garbage line).

        The trim ladder grows with the soak: under a week nothing is
        dropped and the floor is the lowest real reading, so the line
        exists from the first day; thereafter one lowest reading is
        dropped per full week held, so the share discarded stays near
        a seventh however long the window is (ruling #196). The
        anomaly trim
        setting shifts k, clamped so at least one reading always
        survives to be the floor. Dropping the LOWEST values is the
        opposite of the rhythm trim, which drops the highest, because
        for signal the spuriously bad reading is the anomaly to set
        aside.

        The line sits a margin above that floor rather
        than on it, so a link hovering just above its own baseline
        registers instead of reading zero all day. The margin is a
        percentage of the floor's absolute value, which keeps the
        direction right for RSSI as well as LQI; at zero the line is
        the floor and the behaviour is what it was before.

        The margin is then bounded by the device's own spread, and
        the line can never sit higher than the mean of its readings
        less half a standard deviation (ruling #193). A percentage of
        the floor is the largest number of points where there is the
        least room for it, because LQI stops at 255: a device whose
        floor is already near the ceiling gets a margin wide enough
        to swallow its whole operating range. That is not theory. It
        put a line of 252 on a device averaging 246.2, which read as
        below its line for 97 percent of the day while running one of
        the strongest links on the fleet. Two of 71 devices are
        bounded at the default setting and five at the maximum, so
        for almost every device the setting still does exactly what
        it says; on a bounded device it becomes a maximum rather than
        an amount.

        min is right on both scales. The line is a lower bound
        whichever way the numbers run, so taking the smaller value
        always makes a device less sensitive rather than more.

        Where the device has no mean and deviation yet, nothing is
        bounded and the behaviour is unchanged, so a fresh install
        behaves as it did before the first midnight roll.
        """
        history = self._signal_history(record)
        if not history:
            return None
        effective_k = self._signal_effective_k(len(history))
        floor = sorted(history)[effective_k]
        line = floor + self._signal_margin() * abs(floor)
        ceiling = self._good_state_ceiling(record)
        if ceiling is not None:
            return min(line, ceiling)
        return line

    @staticmethod
    def _good_state_ceiling(record: dict[str, Any]) -> float | None:
        """Return the highest the line may sit, or None if unknown.

        The mean of yesterday's readings less half a deviation, from
        the good-state statistics #174 has been recording since
        0.10.15. This is the first thing that reads them to decide
        something rather than to print it.

        Half a deviation is a constant rather than a setting. It is a
        guard rather than a preference, and the screen has enough
        sliders on it already. It sits close under the mean on
        purpose: the fault it stops is a line crossing into the
        readings a healthy device makes every day, so the bound has
        to bite before that happens rather than long after.

        The deviation is used only as a boundary here, which is why
        one day of it is enough. #172's successor makes it the scale
        the whole judgment is drawn from, and that needs weeks rather
        than a day.
        """
        means = record.get(DEV_SIGNAL_DAILY_MEAN) or []
        sds = record.get(DEV_SIGNAL_DAILY_SD) or []
        if not means or not sds:
            return None
        # Half a deviation, but never less than one comfortable step
        # of the scale (ruling #244). On a device whose whole operating
        # range spans a quantization step or two, half a deviation is
        # a fraction of a step and the ceiling lands inside the
        # readings a healthy device makes every hour, which read
        # three steady blinds as 52 to 95 percent dwell in one day.
        clearance = (
            SIGNAL_CEILING_CLEARANCE_RSSI
            if means[-1] < 0
            else SIGNAL_CEILING_CLEARANCE_LQI
        )
        return means[-1] - max(GOOD_STATE_CEILING_SD * sds[-1], clearance)

    def _line_is_bounded(self, record: dict[str, Any]) -> bool:
        """Return whether the good-state ceiling is what set the line.

        Recorded in the diagnostics rather than derived from them, so
        the next time a device reads oddly the download says whether
        the bound was holding it (ruling #193). It is also the
        measurement of how badly the percentage fits: a guard that
        fires often is evidence for #172 rather than against it.
        """
        history = self._signal_history(record)
        if not history:
            return False
        ceiling = self._good_state_ceiling(record)
        if ceiling is None:
            return False
        floor = sorted(history)[self._signal_effective_k(len(history))]
        return floor + self._signal_margin() * abs(floor) > ceiling

    @staticmethod
    def _signal_history(record: dict[str, Any]) -> list[float]:
        """Return the device's daily signal lows with rail values
        removed. Rails are fill values, not readings, so they never
        feed the floor and never count toward the trim.

        Only the most recent SIGNAL_DAYS_KEEP days are read, however
        many are stored. Thirty rather than the fourteen the rhythm
        uses, because a floor is a trimmed minimum and a short window
        forgets a device's genuinely bad days: on the reference fleet
        fifty-one of seventy-eight had a worse day just outside the
        fortnight, and the floor jumping as one aged out is what made
        dwell spike to a hundred percent and back within days
        (ruling #196). The series is still kept for as long as the
        person asks, and reading all of it would slacken every floor,
        so storage and judgment stay separate (ruling #126).
        """
        return [
            value
            for value in (record.get(DEV_SIGNAL_DAILY_MIN) or [])[
                -SIGNAL_DAYS_KEEP:
            ]
            if value not in (SIGNAL_RAIL_LQI, SIGNAL_RAIL_RSSI)
        ]

    def _signal_trim(self) -> int:
        """Return the anomaly trim, clamped to its band. This is the k
        behind the SIGNAL header's trim word: it is global, the same
        for every device, unlike the per-device effective k which also
        carries each device's ladder rung.
        """
        slider = int(
            self.entry.options.get(
                CONF_SIGNAL_ANOMALY_TRIM, DEFAULT_SIGNAL_ANOMALY_TRIM
            )
        )
        return max(
            SIGNAL_ANOMALY_TRIM_MIN, min(slider, SIGNAL_ANOMALY_TRIM_MAX)
        )

    def _signal_margin(self) -> float:
        """Return the sensitivity margin as a fraction of the floor.

        Zero is the older behaviour, where the floor was the
        line. Clamped rather than trusted, because an options value
        can arrive from a hand-edited entry as well as from the
        slider.
        """
        margin = float(
            self.entry.options.get(CONF_SIGNAL_MARGIN, DEFAULT_SIGNAL_MARGIN)
        )
        return max(
            SIGNAL_MARGIN_MIN, min(margin, SIGNAL_MARGIN_MAX)
        ) / 100.0

    def _signal_red(self) -> float:
        """Return the red threshold for the dwell report, clamped."""
        red = float(
            self.entry.options.get(CONF_SIGNAL_RED, DEFAULT_SIGNAL_RED)
        )
        return max(SIGNAL_RED_MIN, min(red, SIGNAL_RED_MAX))

    def _signal_trim_label(self) -> str:
        """Return the anomaly trim as a word, not a number.

        The report used to show the slider as K, which collided with
        the trim depth the same report calls k. A word states what the
        setting does: shallow settings trim fewer lows so the floor
        sits lower and flags less, deep settings the reverse. The
        earlier mood words (Calm through Sensitive) were replaced in
        0.10.13, because the last of them collided with the new
        Sensitivity setting beside it, which is a different control
        entirely.
        """
        return {
            -2: "None",
            -1: "Light",
            0: "Normal",
            1: "Deep",
            2: "Deepest",
        }.get(self._signal_trim(), "Normal")

    def _signal_effective_k(self, days: int) -> int:
        """Return how many of the lowest readings the floor trims.

        One per full week held, shifted by the slider and clamped so
        at least one reading survives (ruling #196). A count rather
        than a share, so it stays a whole number of days, but chosen
        per week so the share stays near a seventh at every rung
        instead of thinning as the window grows: two rungs discarded
        fourteen percent of a fortnight and would discard nine
        percent of a month, lowering every floor on the fleet as a
        side effect of a change meant to be about stability.
        """
        base_k = min(days // SIGNAL_TRIM_PER_WEEK, SIGNAL_TRIM_LADDER_MAX)
        return max(0, min(base_k + self._signal_trim(), days - 1))

    def signal_railed(self, record: dict[str, Any]) -> bool:
        """Return whether this device's signal is stuck at the rail.

        A rail is the type's fill value, 255 for LQI or -128 for RSSI:
        the empty value of a field the device stopped populating,
        which reads as perfect signal and is the opposite. It is
        confirmed over time, not on a single reading: the daily low
        has sat at a rail for RAIL_CONFIRM_DAYS consecutive days
        (ruling #78, which replaced the live repeat counter
        the frozen rework proved unreliable). Reading the daily-low
        series the report already keeps means no live counter and no
        per-reading state: a rail that comes and goes within a day
        never confirms, while one that holds across days does.

        The plausible-value freeze, a real reading that stops moving,
        is not judged here: a device with a strong steady link reports
        the same value for hours and cannot be told from a stuck one.
        The project document records that rabbit hole and the learned
        flat-stretch approach that could restore it if it is ever
        worth building.
        """
        lows = record.get(DEV_SIGNAL_DAILY_MIN) or []
        if len(lows) < RAIL_CONFIRM_DAYS:
            return False
        rails = (SIGNAL_RAIL_LQI, SIGNAL_RAIL_RSSI)
        recent = lows[-RAIL_CONFIRM_DAYS:]
        return all(value in rails for value in recent)

    @staticmethod
    def _is_signal(ent: er.RegistryEntry) -> bool:
        """Recognize a signal-strength entity from registry fields."""
        if str(ent.original_device_class) == "signal_strength" or str(
            getattr(ent, "device_class", None)
        ) == "signal_strength":
            return True
        hay = " ".join(
            str(x)
            for x in (ent.entity_id, ent.unique_id, ent.original_name)
            if x
        ).lower()
        return any(term in hay for term in SIGNAL_NAME_TERMS)

    @property
    def signal_tracked(self) -> dict[str, int]:
        """Return counts of devices with a learned signal floor.

        Tracked means the device has a floor and so a live line: the
        signal analogue of Devices Learned. Split by scale for the
        curious; the dwell rule is identical for both. Learning counts
        devices that report signal but have no floor yet, which since
        the floor exists from the first recorded day means a device
        whose history is entirely rail values (a floor of nothing
        rather than a false one). Excluded devices still count here:
        exclusion suppresses judgment, not observation.
        """
        counts = {"lqi": 0, "rssi": 0, "learning": 0}
        for record in self.data.get(DATA_DEVICES, {}).values():
            line = self._danger_line(record)
            if line is None:
                if record.get(DEV_SIGNAL_VALUE) is not None:
                    counts["learning"] += 1
                continue
            if line >= 0:
                counts["lqi"] += 1
            else:
                counts["rssi"] += 1
        return counts

    @property
    def signal_tracked_count(self) -> int:
        """Return how many devices have a signal line, after excludes.

        The state for Tracked Signals: devices with a floor that are
        not signal-excluded. Exclusion suppresses judgment, so an
        excluded device is not something we are watching for signal.
        """
        counts = self.signal_tracked
        watched = counts["lqi"] + counts["rssi"]
        excluded = sum(
            1
            for device_id, record in self.data.get(DATA_DEVICES, {}).items()
            if self._danger_line(record) is not None
            and self._signal_excluded(device_id)
        )
        return watched - excluded

    def _todo_signal_since(self, device_id: str) -> float | None:
        """Return when a device's signal fault was added to the list.

        A rail carries no physical start time (it is derived from the
        daily-low series), so its age is measured from the todo item's
        signal-kind stamp, the moment the sync first listed it. This
        keeps the section consistent with the list it mirrors.
        """
        for record in self.todo_items:
            if record.get(TODO_DEVICE_ID) == device_id:
                return (record.get(TODO_KINDS) or {}).get("signal")
        return None

    @property
    def signal_problem_list(self) -> list[dict[str, Any]]:
        """Return devices whose signal reading is stuck at a rail.

        A rail is the type's fill value, 255 for LQI or -128 for
        RSSI: the empty value of a field the device stopped
        populating, which reads as perfect signal and is the
        opposite. Confirmed over three days rather than on a single
        reading (ruling #78), so what lands here is a fault rather
        than a bad afternoon.

        Rails only, and deliberately. This list feeds the problem
        list and therefore the todo entity, the card and the phone,
        so a rail is the one signal condition solid enough to
        interrupt somebody. Weak links are a live reading that moves
        day to day and live on signal_weak_list, which notifies
        nothing (rulings #59 and #211).

        Signal-excluded devices are observed but never judged, so
        they stay off this list until re-included by hand.
        """
        problems: list[dict[str, Any]] = []
        for device_id, record in self.data.get(DATA_DEVICES, {}).items():
            if self._signal_excluded(device_id):
                continue
            if self.signal_railed(record):
                problems.append(
                    {
                        "name": self._device_names.get(device_id),
                        "device_id": device_id,
                        "kind": "rail",
                        "value": record.get(DEV_SIGNAL_VALUE),
                    }
                )
        # Rails only, and deliberately. This list feeds the problem
        # list, which feeds the todo entity, the card and the phone,
        # so anything added here becomes a notification. Dwell has no
        # day-to-day persistence to notify on: on the reference fleet
        # only three of twelve device-days above twenty percent were
        # still above it the next morning, so a low arriving here
        # would push tonight and clear tomorrow. Signal reports and
        # does not push (ruling #59), and the low kind lives on
        # signal_weak_list below, which nothing notifies from
        # (ruling #211).
        # Rail problems first, then by name: a rail is a fault and a
        # low is a weak link.
        problems.sort(key=lambda row: (row["kind"] != "rail", row["name"] or ""))
        return problems

    @property
    def signal_weak_list(self) -> list[dict[str, Any]]:
        """Return devices whose link is weak right now.

        The Signal: Weak sensor. A device qualifies while its dwell
        on the last closed day is over the red threshold, which is
        the rule the brief's anomaly line and the chart's colouring
        already use, so one definition serves all three and a device
        cannot be named in one and absent from another (ruling #211).

        Separate from the rails for the same reason Battery: Low and
        Battery: Falling are separate. A rail is a broken measurement,
        confirmed over three days and persistent; a weak link is a
        live reading that moves. On the reference fleet only three of
        twelve device-days above twenty percent were still above it
        the next morning, so counting the two together produced one
        number that meant two things and read zero on a fleet with no
        rails.

        Nothing notifies from this. A device drops off the moment its
        dwell falls back under the threshold, with no acknowledgment
        and no record, because it is a reading rather than an
        incident: what a dashboard shows is the fleet as it stands
        (ruling #59).
        """
        railed = {row["device_id"] for row in self.signal_problem_list}
        return [
            {
                "name": anomaly["name"],
                "device_id": anomaly["device_id"],
                "dwell": anomaly.get("dwell"),
                "floor": anomaly.get("floor"),
                "area": anomaly.get("area"),
            }
            for anomaly in self._dwell_anomalies(self._signal_red())
            if anomaly["device_id"] not in railed
        ]

    @property
    def signal_weak_count(self) -> int:
        """Return how many links are weak right now."""
        return len(self.signal_weak_list)

    @property
    def signal_problem_count(self) -> int:
        """Return how many devices have a signal problem."""
        return len(self.signal_problem_list)

    def _signal_excluded(self, device_id: str) -> bool:
        """Return whether a device is excluded from signal judgment
        only. The same broad-to-narrow ladder as battery. Exclusion
        suppresses judgment, not observation: the device keeps
        recording its floor and dwell in storage, so re-inclusion is
        instant and arrives with history; it simply stops being
        reported. This is the manual removal from tracking the
        frozen-signal ruling requires, for a device that resists
        every recovery."""
        options = self.entry.options
        if self._watched.get(device_id) in options.get(
            CONF_SIGNAL_EXCLUDED_INTEGRATIONS, []
        ):
            return True
        if self._device_labels.get(device_id, frozenset()) & set(
            options.get(CONF_SIGNAL_EXCLUDED_LABELS, [])
        ):
            return True
        return device_id in options.get(CONF_SIGNAL_EXCLUDED_DEVICES, [])

    @property
    def detected_signals(self) -> list[dict[str, Any]]:
        """Return every device with a signal reading, for the signal
        options picker: pick-from-detected, what you see is what is
        being judged. Excluded devices are present, because an
        excluded device is exactly the thing this picker exists to
        un-tick."""
        rows = [
            {
                "device_id": device_id,
                "name": self._device_names.get(device_id, device_id),
                "integration": self._watched.get(device_id, "?"),
                "labels": self._device_labels.get(
                    device_id, frozenset()
                ),
            }
            for device_id, record in self.data.get(
                DATA_DEVICES, {}
            ).items()
            if record.get(DEV_SIGNAL_VALUE) is not None
            or record.get(DEV_SIGNAL_DAILY_MIN)
        ]
        rows.sort(key=lambda row: row["name"].lower())
        return rows
