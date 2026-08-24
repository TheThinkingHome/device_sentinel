# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: detect_signal.py, Version: 0.16.12 (2026-08-21)

"""Signal: the learned floor, the line, and the rails.

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

import statistics

from typing import Any

from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_SIGNAL_MUTED_DEVICES,
    CONF_SIGNAL_MUTED_INTEGRATIONS,
    CONF_SIGNAL_MUTED_LABELS,
    BADDAY_MIN_BASELINE,
    BADDAY_MIN_SPREAD,
    BADDAY_BASELINE_DAYS_MAX,
    BADDAY_BASELINE_DAYS_MIN,
    BADDAY_DROP_LQI_MAX,
    BADDAY_DROP_LQI_MIN,
    BADDAY_DROP_RSSI_MAX,
    BADDAY_DROP_RSSI_MIN,
    BADDAY_SENSITIVITY_MAX,
    BADDAY_SENSITIVITY_MIN,
    CONF_BADDAY_BASELINE_DAYS,
    CONF_BADDAY_DROP_LQI,
    CONF_BADDAY_DROP_RSSI,
    CONF_BADDAY_SENSITIVITY,
    DATA_DEVICES,
    DEFAULT_BADDAY_BASELINE_DAYS,
    DEFAULT_BADDAY_DROP_LQI,
    DEFAULT_BADDAY_DROP_RSSI,
    DEFAULT_BADDAY_SENSITIVITY,
    DEV_SIGNAL_COUNT,
    DEV_SIGNAL_DAILY_COUNT,
    DEV_SIGNAL_DAILY_MAX,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_RAIL,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_LAST_CHANGE,
    DEV_SIGNAL_M2,
    DEV_SIGNAL_MEAN_RUN,
    DEV_SIGNAL_P5_STATE,
    DEV_SIGNAL_P50_STATE,
    DEV_SIGNAL_PSQ_TS,
    DEV_SIGNAL_PSQ_VALUE,
    DEV_SIGNAL_RAIL_COUNT,
    DEV_SIGNAL_READS,
    DEV_SIGNAL_TODAY_MAX,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_VALUE,
    GOOD_STATE_CEILING_SD,
    LOGGER,
    RAIL_CONFIRM_DAYS,
    SIGNAL_CEILING_CLEARANCE_LQI,
    SIGNAL_CEILING_CLEARANCE_RSSI,
    SIGNAL_DAYS_KEEP,
    SIGNAL_LQI_DEAD,
    SIGNAL_LQI_PERFECT,
    SIGNAL_ALT_FIELDS,
    SIGNAL_NAME_TERMS,
    SIGNAL_REFUSED_UNITS,
    SIGNAL_SCALE_LQI,
    TODO_KIND_RAILED_SIGNAL,
    SIGNAL_LIFT,
    SIGNAL_MARGIN,
    SIGNAL_SCALE_RSSI,
    DEV_SIGNAL_ALT,
    DEV_SIGNAL_SCALE,
    SIGNAL_RAIL_LQI,
    SIGNAL_RAIL_RSSI,
    SIGNAL_RSSI_DEAD,
    SIGNAL_RSSI_PERFECT,
    TODO_DEVICE_ID,
    TODO_KINDS,
)
from .psquare import (
    psquare_feed_many,
    psquare_new,
    psquare_read,
)
from .records import _reset_signal_day


def _usable(entry: Any) -> float | None:
    """Return a stored reading as a finite float, or None.

    Storage is a JSON file on a person's disk and the Data Trim tool
    exists because records do go wrong. A NaN in a baseline raises
    inside statistics.median, an infinity flags every day forever,
    and a string raises on comparison, so each would take down the
    fold or the report write rather than the one device. Nothing here
    assumes those values are unreachable; the outages of 20 August
    came from exactly that assumption.

    Booleans are refused although Python counts them as integers,
    because a True in a signal series is corruption rather than a
    reading of one.
    """
    if entry is None or isinstance(entry, bool):
        return None
    if not isinstance(entry, (int, float)):
        return None
    value = float(entry)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def scale_of(value: float) -> str:
    """Return which scale a reading is on, from its sign (ruling #284).

    RSSI is power in dBm and is negative at any Zigbee receiver. LQI
    runs 0 to 255. Across the two fleets that have sent data there is
    no overlap: 4,209 negative readings and 4,040 non-negative,
    positives spanning 0 to 255 and negatives -106 to -1.

    Zero goes to LQI. It is a valid link quality, the worst the scale
    can express, and it is not a plausible received power: 0 dBm is a
    milliwatt arriving at a Zigbee receiver.
    """
    return SIGNAL_SCALE_RSSI if value < 0 else SIGNAL_SCALE_LQI


def _new_alt_block(scale: str) -> dict[str, Any]:
    """An empty second-scale block, holding only what is recorded."""
    block: dict[str, Any] = {}
    for field in SIGNAL_ALT_FIELDS:
        if field == DEV_SIGNAL_SCALE:
            block[field] = scale
        elif field.endswith(("_state",)):
            block[field] = None
        elif field.startswith("signal_daily_"):
            block[field] = []
        elif field in ("signal_count", "signal_reads", "signal_rail_count"):
            block[field] = 0
        elif field in ("signal_mean_run", "signal_m2"):
            block[field] = 0.0
        else:
            block[field] = None
    return block


def signal_bucket(record: dict[str, Any], scale: str) -> dict[str, Any]:
    """Return the place a reading on this scale belongs.

    The primary scale's fields sit at the top of the record, where
    every report, sensor and chart already reads them. A second scale
    goes in signal_alt under the same names, recorded and not judged
    (rulings #285, #286).

    RSSI takes precedence where a device has both. A device whose LQI
    entity happened to report first therefore has to hand the primary
    over when its RSSI arrives, and the block already holding LQI
    becomes the alternate. Doing it by swapping the two rather than
    by discarding either keeps whatever each has already learned.
    """
    current = record.get(DEV_SIGNAL_SCALE)
    if current is None:
        record[DEV_SIGNAL_SCALE] = scale
        return record
    if scale == current:
        return record
    alt = record.get(DEV_SIGNAL_ALT)
    if scale == SIGNAL_SCALE_RSSI:
        # The new scale outranks the sitting one, so they trade
        # places: what was primary moves into the block, and the
        # block's contents, if any, come up to the top.
        demoted = {
            field: record.get(field) for field in SIGNAL_ALT_FIELDS
        }
        demoted[DEV_SIGNAL_SCALE] = current
        promoted = alt if alt is not None else _new_alt_block(scale)
        for field in SIGNAL_ALT_FIELDS:
            record[field] = promoted.get(field)
        record[DEV_SIGNAL_SCALE] = scale
        record[DEV_SIGNAL_ALT] = demoted
        return record
    if alt is None:
        alt = _new_alt_block(scale)
        record[DEV_SIGNAL_ALT] = alt
    return alt


def _entity_unit(ent: er.RegistryEntry) -> str:
    """Return an entity's unit, preferring the registry's override.

    A person can change a unit in the registry, and the changed one
    is what the state will carry, so it is the one that decides.
    """
    for name in ("unit_of_measurement", "original_unit_of_measurement"):
        value = getattr(ent, name, None)
        if value:
            return str(value).strip().lower()
    return ""


def _is_percentage(ent: er.RegistryEntry) -> bool:
    """Is this entity measured in percent (ruling #283)?"""
    return _entity_unit(ent) in SIGNAL_REFUSED_UNITS


class SignalMixin:
    """Signal: the learned floor, the line, and the rails."""

    def _roll_dwell(self, record: dict[str, Any], now: float) -> None:
        """Fold the day's signal statistics.

        The name survives its subject: the dwell record is erased
        (ruling #322) and the fold now writes only the statistics the
        detector reads. Kept as the coordinator's one entry point so
        the midnight roll calls what it always called.
        """
        self._roll_signal_stats(record, now)

    def _roll_signal_stats(
        self, record: dict[str, Any], fold_now: float
    ) -> None:
        """Fold the primary, then the second scale if there is one."""
        self._roll_one_scale(record, fold_now, judged=True)
        alt = record.get(DEV_SIGNAL_ALT)
        if alt is not None:
            self._roll_one_scale(alt, fold_now, judged=False)

    def _roll_one_scale(
        self, record: dict[str, Any], fold_now: float, judged: bool = True
    ) -> None:
        """Close the day's signal distribution into the daily series.

        Mean and standard deviation are what the Bayesian successor to
        the current thresholding needs (ruling #172), so they are recorded
        ahead of it: the day's Welford accumulators (ruling #254)
        become one mean and one deviation, the day's maximum rides
        beside them, the P-Square estimators (ruling #253) become the
        day's time-weighted 5th percentile and median, and everything
        resets for the new day. The deviation is the
        population form, and a one-reading day records zero deviation
        rather than none, because one reading genuinely varied by
        nothing.

        A row is written only for a day the device actually spoke
        (ruling #305). The Welford count alone cannot decide that:
        it is time-weighted and the held value keeps accruing
        minutes through silence (ruling #253), so a device that
        reported once and went quiet still weighed a full day at
        every following fold, and the fold wrote a fabricated row,
        statistics copied from the last real reading, deviation
        zero, and None in the maximum. Nine such rows on the first
        external fleet; the reference fleet cannot produce one
        because every device on it reports daily. So the gate is
        the reads counter, which only a real reading moves. A day
        of nothing but rail readings writes the row too, rail count
        real and every statistic null, because three consecutive
        rail days are the confirmation the rail verdict needs
        (rulings #78, #322) and dropping the day would break the count. A
        day with neither writes nothing, so these series stay
        aligned with each other.
        """
        # The day's tail: the held value has been accruing minutes
        # since its last feed, and they belong to the day being
        # folded (ruling #253).
        self._feed_percentiles(record, now=fold_now)
        count, mean, m2 = self._welford_state(record)
        if count == 0 and int(record.get(DEV_SIGNAL_READS) or 0) > 0:
            # Readings that never completed a whole held minute, so
            # the day weighs nothing (ruling #262). Without this the
            # reads counter survived the fold and was counted into
            # the next day, which put one device's report count on
            # the wrong row. The day is dropped, not carried.
            record[DEV_SIGNAL_READS] = 0
        reads = int(record.get(DEV_SIGNAL_READS) or 0)
        rails = int(record.get(DEV_SIGNAL_RAIL_COUNT) or 0)
        if count > 0 and reads > 0:
            variance = max(0.0, m2 / count)
            record.setdefault(DEV_SIGNAL_DAILY_MEAN, []).append(
                round(mean, 2)
            )
            record.setdefault(DEV_SIGNAL_DAILY_SD, []).append(
                round(variance**0.5, 2)
            )
            for key, state_key, q in (
                (DEV_SIGNAL_DAILY_P5, DEV_SIGNAL_P5_STATE, 0.05),
                (DEV_SIGNAL_DAILY_P50, DEV_SIGNAL_P50_STATE, 0.5),
            ):
                state = record.get(state_key)
                estimate = (
                    psquare_read(state, q) if state is not None else None
                )
                record.setdefault(key, []).append(
                    round(estimate, 2) if estimate is not None else None
                )
            folded_p5 = (record.get(DEV_SIGNAL_DAILY_P5) or [None])[-1]
            folded_p50 = (record.get(DEV_SIGNAL_DAILY_P50) or [None])[-1]
            if (
                folded_p5 is not None
                and folded_p50 is not None
                and folded_p5 > folded_p50
            ):
                # Cannot happen in the data, since both read the same
                # values through the same clock, so it is the
                # estimators crossing: two independent approximations
                # of numbers that a flat day makes nearly equal. The
                # marker states are written down because the reset
                # below destroys them, and one instance in seventy-nine
                # devices was not reproducible from the folded figures
                # alone.
                LOGGER.info(
                    "Signal percentiles crossed on a fold: P5 %.2f "
                    "above P50 %.2f, over %d minutes and %d reading(s). "
                    "P5 markers %s, P50 markers %s",
                    folded_p5,
                    folded_p50,
                    count,
                    int(record.get(DEV_SIGNAL_READS) or 0),
                    record.get(DEV_SIGNAL_P5_STATE),
                    record.get(DEV_SIGNAL_P50_STATE),
                )
            record.setdefault(DEV_SIGNAL_DAILY_MAX, []).append(
                record.get(DEV_SIGNAL_TODAY_MAX)
            )
            record.setdefault(DEV_SIGNAL_DAILY_COUNT, []).append(reads)
            record.setdefault(DEV_SIGNAL_DAILY_RAIL, []).append(
                int(record.get(DEV_SIGNAL_RAIL_COUNT) or 0)
            )
            trimmed = [
                DEV_SIGNAL_DAILY_MEAN,
                DEV_SIGNAL_DAILY_SD,
                DEV_SIGNAL_DAILY_P5,
                DEV_SIGNAL_DAILY_P50,
                DEV_SIGNAL_DAILY_MAX,
                DEV_SIGNAL_DAILY_COUNT,
                DEV_SIGNAL_DAILY_RAIL,
            ]
            for field in trimmed:
                del record[field][:-self.retention_days]
        elif rails > 0:
            # A rail-only day: the device spoke, and everything it
            # said was the stuck value the estimators refuse. There
            # is no statistic to record and there is evidence to
            # keep, so the row is written with the rail count real
            # and every statistic null (ruling #305). The count
            # entry is 0 because zero real readings arrived, which
            # is also what the one-time trim keys on, so the trim
            # skips rows whose rail entry is above zero.
            for key in (
                DEV_SIGNAL_DAILY_MEAN,
                DEV_SIGNAL_DAILY_SD,
                DEV_SIGNAL_DAILY_P5,
                DEV_SIGNAL_DAILY_P50,
                DEV_SIGNAL_DAILY_MAX,
            ):
                record.setdefault(key, []).append(None)
            record.setdefault(DEV_SIGNAL_DAILY_COUNT, []).append(0)
            record.setdefault(DEV_SIGNAL_DAILY_RAIL, []).append(rails)
            trimmed = [
                DEV_SIGNAL_DAILY_MEAN,
                DEV_SIGNAL_DAILY_SD,
                DEV_SIGNAL_DAILY_P5,
                DEV_SIGNAL_DAILY_P50,
                DEV_SIGNAL_DAILY_MAX,
                DEV_SIGNAL_DAILY_COUNT,
                DEV_SIGNAL_DAILY_RAIL,
            ]
            for field in trimmed:
                del record[field][:-self.retention_days]
        # The naive accumulators are legacy after #254: the fold
        # removes them so a migrated record sheds them at its first
        # midnight rather than carrying zeros forever.
        _reset_signal_day(record)
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
        # Which of the device's scales this reading belongs to. The
        # primary is the record itself; a second scale is its own
        # block, recorded and never judged (rulings #284, #285).
        bucket = signal_bucket(record, scale_of(value))

        previous = bucket.get(DEV_SIGNAL_VALUE)
        if previous is None or value != previous:
            bucket[DEV_SIGNAL_LAST_CHANGE] = now
        bucket[DEV_SIGNAL_VALUE] = value

        if value in (SIGNAL_RAIL_LQI, SIGNAL_RAIL_RSSI):
            bucket[DEV_SIGNAL_RAIL_COUNT] = (
                int(bucket.get(DEV_SIGNAL_RAIL_COUNT) or 0) + 1
            )
            return
        bucket[DEV_SIGNAL_READS] = int(bucket.get(DEV_SIGNAL_READS) or 0) + 1
        today_min = bucket.get(DEV_SIGNAL_TODAY_MIN)
        if today_min is None or value < today_min:
            bucket[DEV_SIGNAL_TODAY_MIN] = value
        today_max = bucket.get(DEV_SIGNAL_TODAY_MAX)
        if today_max is None or value > today_max:
            bucket[DEV_SIGNAL_TODAY_MAX] = value
        # The day's four figures all weigh minutes (ruling #259): the
        # mean and deviation are fed by _feed_percentiles on the same
        # clock as P5 and the median, so a device reporting once an
        # hour is measured the same way as one reporting every
        # minute, and the four can be read side by side. Counting
        # readings instead let a busy hour outvote a quiet one, and
        # on this fleet reporting rates differ by two orders of
        # magnitude.
        self._feed_percentiles(bucket, now=now, new_value=value)

    def _welford_state(
        self, record: dict[str, Any]
    ) -> tuple[int, float, float]:
        """Return the day's (count, running mean, M2).

        The conversion from the retired sum and sum-of-squares pair
        runs at load and not here (ruling #256): the reconciler
        deletes the legacy keys before any reading arrives, so a
        migration in this path read a record that only looked
        migrated, restarted the mean at zero against a full count,
        and drove every running mean toward a tenth of its true
        value. A count carried with no accumulator behind it is a day
        with no statistics, and resetting it is what keeps the fold
        from dividing by a ghost.
        """
        count = int(record.get(DEV_SIGNAL_COUNT) or 0)
        mean = record.get(DEV_SIGNAL_MEAN_RUN)
        if count > 0 and mean is None:
            record[DEV_SIGNAL_COUNT] = 0
            return 0, 0.0, 0.0
        return (
            count,
            float(mean or 0.0),
            float(record.get(DEV_SIGNAL_M2) or 0.0),
        )

    def _feed_percentiles(
        self,
        record: dict[str, Any],
        now: float,
        new_value: float | None = None,
    ) -> None:
        """Weigh the held value by its whole minutes, then hold the
        new one.

        A value counts by duration, not by arrival (ruling #253): a
        reading held for three hours is 180 observations, a one-off
        blip inside a busy minute is none. The fractional remainder
        stays on the clock rather than being dropped, so no time is
        lost across feeds. Rails never arrive here (the caller
        returns before the accumulators on a rail), and the held
        value keeps accruing through silence, matching how dwell
        reads a silent link.
        """
        held = record.get(DEV_SIGNAL_PSQ_VALUE)
        ts = record.get(DEV_SIGNAL_PSQ_TS)
        if held is not None and ts is not None:
            minutes = min(1440, int(max(0.0, now - float(ts)) // 60))
            if minutes > 0:
                for state_key, q in (
                    (DEV_SIGNAL_P5_STATE, 0.05),
                    (DEV_SIGNAL_P50_STATE, 0.5),
                ):
                    state = record.get(state_key)
                    if state is None:
                        state = psquare_new()
                        record[state_key] = state
                    psquare_feed_many(state, q, float(held), minutes)
                # Welford for a repeated value has a closed form, so
                # the day's mean and deviation cost the same whether
                # the value was held for a minute or a day (ruling
                # #262). This ran as a loop and a restart after an
                # outage could hand it a day's worth per device, on
                # the event loop, at the moment Home Assistant is
                # busiest. Identical arithmetic, proven against the
                # loop rather than assumed.
                count, mean, m2 = self._welford_state(record)
                delta = float(held) - mean
                count += minutes
                mean += minutes * delta / count
                m2 += minutes * delta * (float(held) - mean)
                record[DEV_SIGNAL_COUNT] = count
                record[DEV_SIGNAL_MEAN_RUN] = mean
                record[DEV_SIGNAL_M2] = m2
                record[DEV_SIGNAL_PSQ_TS] = float(ts) + minutes * 60.0
        if new_value is not None:
            if held is None or ts is None:
                record[DEV_SIGNAL_PSQ_TS] = now
            record[DEV_SIGNAL_PSQ_VALUE] = float(new_value)

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
        registers instead of reading zero all day. The margin is the
        sensitivity percentage of the distance from perfect plus the
        flat lift (rulings #250, #252): widest at the dropout point,
        dead at perfect, identical in shape on both scales. Dwell
        counts strictly below the line (ruling #251), so a zero
        margin at perfect means never, and a device sitting on its
        own floor no longer reads as dwelling there.

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
        floor = min(history)
        line = floor + self._anchored_margin(floor)
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
        # The most recent day that has statistics at all. A rail-only
        # day writes null into both series on purpose (ruling #305),
        # and the ceiling's job is to bound the line by the device's
        # real behaviour, so it rests on the last day that had any.
        # Reading [-1] unguarded took the integration down on the
        # first fleet where a device railed a whole day: the fold
        # wrote the row exactly as designed and this reader was the
        # one that had not learned to read it (#279, applied to
        # readers: accept what the code can write).
        mean = sd = None
        for index in range(len(means) - 1, -1, -1):
            if index < len(sds) and means[index] is not None and sds[
                index
            ] is not None:
                mean = means[index]
                sd = sds[index]
                break
        if mean is None or sd is None:
            return None
        # Half a deviation, but never less than one comfortable step
        # of the scale (ruling #244). On a device whose whole operating
        # range spans a quantization step or two, half a deviation is
        # a fraction of a step and the ceiling lands inside the
        # readings a healthy device makes every hour, which read
        # three steady blinds as 52 to 95 percent dwell in one day.
        clearance = (
            SIGNAL_CEILING_CLEARANCE_RSSI
            if mean < 0
            else SIGNAL_CEILING_CLEARANCE_LQI
        )
        return mean - max(GOOD_STATE_CEILING_SD * sd, clearance)

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
        floor = min(history)
        return floor + self._anchored_margin(floor) > ceiling

    @staticmethod
    def _signal_history(record: dict[str, Any]) -> list[float]:
        """Return the device's daily P5 window, nulls skipped.

        The floor reads the time-weighted 5th percentile rather than
        the retired one-packet daily minimum (rulings #322, #323):
        P5 already discards the worst five percent of every day by
        time, so no cross-day trim is applied and the floor is the
        plain minimum of this window. Rail-only days recorded null
        statistics (ruling #305) and are skipped, so a device whose
        whole history is rail has no floor rather than a false one.
        Only the most recent SIGNAL_DAYS_KEEP days are read, however
        many are stored; storage and judgment stay separate
        (ruling #126).
        """
        return [
            value
            for value in (record.get(DEV_SIGNAL_DAILY_P5) or [])[
                -SIGNAL_DAYS_KEEP:
            ]
            if value is not None
        ]

    def _signal_margin(self) -> float:
        """Return the sensitivity as a fraction of the working band.

        A constant since ruling #311, held at the value that was its
        default, so a fleet on the defaults records exactly what it
        recorded before. One that had moved it steps once, which is
        accepted: the comparison this history exists for was made and
        written into ruling #310 before the change.
        """
        return SIGNAL_MARGIN / 100.0

    def _signal_lift(self) -> float:
        """Return the flat lift added to every line, in scale units.

        The second sensitivity control (ruling #252): where the
        percentage sets the line's slope, the lift raises the whole
        line by the same amount at every floor, so it survives even
        where the margin has died to nothing at perfect. One value
        serves both scales because a quarter unit is deliberately
        small on each.

        A constant since ruling #311, held at its former default of
        zero, for the reason given on the margin above it.
        """
        return SIGNAL_LIFT

    def _anchored_margin(self, floor: float) -> float:
        """Return the margin above this floor, in scale units.

        The sensitivity percentage of the distance from perfect
        (ruling #250): widest at the dropout point, held at that
        width through the dropout zone below it, dead at perfect.
        The old margin was a percentage of the floor itself, which
        measures distance from zero, and zero is dead on LQI but
        perfect on RSSI: one formula, two opposite behaviours, and
        the widest bands on the fleet's strongest LQI links. Anchors
        are the working band, not the scale ends: no working link
        lives at LQI 0 or RSSI -100, and none reads LQI 255 (the
        rail) or RSSI 0.
        """
        if floor < 0:
            dead, perfect = SIGNAL_RSSI_DEAD, SIGNAL_RSSI_PERFECT
        else:
            dead, perfect = SIGNAL_LQI_DEAD, SIGNAL_LQI_PERFECT
        span = max(0.0, perfect - max(floor, dead))
        return self._signal_margin() * span + self._signal_lift()

    def _badday_setting(
        self, key: str, default: float, low: float, high: float
    ) -> float:
        """Return one bad-day setting, clamped to its own bounds."""
        return max(low, min(float(self.entry.options.get(key, default)), high))

    def _badday_baseline_days(self) -> int:
        """Return how many folded days form a device's normal."""
        return int(
            self._badday_setting(
                CONF_BADDAY_BASELINE_DAYS,
                DEFAULT_BADDAY_BASELINE_DAYS,
                BADDAY_BASELINE_DAYS_MIN,
                BADDAY_BASELINE_DAYS_MAX,
            )
        )

    def _badday_drop(self, scale: str | None) -> float:
        """Return the absolute fall a bad day needs, in the device's own
        units.

        Scale-native rather than a share, because a share of an RSSI
        number is meaningless: a link at -60 dBm losing a real 6 dB
        reads as ten percent (ruling #310, following #250).
        """
        if scale == SIGNAL_SCALE_RSSI:
            return self._badday_setting(
                CONF_BADDAY_DROP_RSSI,
                DEFAULT_BADDAY_DROP_RSSI,
                BADDAY_DROP_RSSI_MIN,
                BADDAY_DROP_RSSI_MAX,
            )
        return self._badday_setting(
            CONF_BADDAY_DROP_LQI,
            DEFAULT_BADDAY_DROP_LQI,
            BADDAY_DROP_LQI_MIN,
            BADDAY_DROP_LQI_MAX,
        )

    def _badday_sensitivity(self) -> float:
        """Return how many of a device's own spreads a bad day needs."""
        return self._badday_setting(
            CONF_BADDAY_SENSITIVITY,
            DEFAULT_BADDAY_SENSITIVITY,
            BADDAY_SENSITIVITY_MIN,
            BADDAY_SENSITIVITY_MAX,
        )

    def signal_badday(
        self, record: dict[str, Any], index: int = -1
    ) -> dict[str, float] | None:
        """Return the reading behind one device-day, or None.

        The question is not whether the device is near its floor,
        which is what dwell asked and answered badly, but whether it
        just got worse than it has been (ruling #310). The judge is
        P5, because the daily minimum is a one-packet statistic: on
        the reference fleet it sits a median 1.17 of the device's own
        deviations below P5, and on 56 percent of device-days more
        than a full one.

        Both gates must hold. The absolute fall stops a trivial move
        on a very steady device from reading as a catastrophe, which
        a ratio alone does: a device whose P5 varies by 1.5 counts a
        routine wobble as many deviations. The spread gate stops a
        large move on a jittery device from reading as news. Returned
        rather than a bare boolean so the report can say what it saw
        without recomputing it.

        None means the day cannot be judged: no reading, too little
        history, or a baseline so flat that dividing by its spread
        would say more about arithmetic than about radio.
        """
        series = record.get(DEV_SIGNAL_DAILY_P5) or []
        if not series:
            return None
        position = index if index >= 0 else len(series) + index
        if position < 0 or position >= len(series):
            return None
        today = _usable(series[position])
        if today is None:
            return None
        window = self._badday_baseline_days()
        base = [
            value
            for value in (
                _usable(entry)
                for entry in series[max(0, position - window):position]
            )
            if value is not None
        ]
        if len(base) < BADDAY_MIN_BASELINE:
            return None
        # A baseline holding both signs is two scales in one series,
        # which a ZHA reset can produce mid-life. Its median is a
        # number with no meaning and its spread is the distance
        # between two measuring systems, so the day is left unjudged
        # rather than judged from nonsense. Storage clears such a
        # series at the next fold; until then this is the guard.
        if min(base) < 0 <= max(base):
            return None
        if (today < 0) is not (base[0] < 0):
            return None
        middle = statistics.median(base)
        spread = statistics.pstdev(base)
        if spread < BADDAY_MIN_SPREAD:
            spread = BADDAY_MIN_SPREAD
        fall = middle - float(today)
        # The record's scale field is the first source and the
        # readings are the fallback, because the field can be absent
        # while the series is full: a 16 August snapshot of the
        # reference fleet carries a P5 series on 79 devices and a
        # scale on none of them, seven of those devices negative. A
        # missing field there would put the LQI gate on an RSSI
        # device and demand a 25 dB fall, which is deafness rather
        # than caution. The sign decides, the same rule the recorder
        # uses (ruling #284).
        scale = record.get(DEV_SIGNAL_SCALE)
        if scale is None:
            scale = scale_of(middle)
        drop = self._badday_drop(scale)
        deviations = fall / spread
        return {
            "today": float(today),
            "baseline": float(middle),
            "spread": float(spread),
            "fall": float(fall),
            "deviations": float(deviations),
            "drop_gate": float(drop),
            "bad": bool(
                fall >= drop and deviations >= self._badday_sensitivity()
            ),
        }

    def signal_railed(self, record: dict[str, Any]) -> bool:
        """Return whether this device's signal is stuck at the rail.

        A rail is the type's fill value, 255 for LQI or -128 for RSSI:
        the empty value of a field the device stopped populating,
        which reads as perfect signal and is the opposite. It is
        confirmed over time, not on a single reading: for
        RAIL_CONFIRM_DAYS consecutive days the device spoke and
        everything it said was the stuck value, read as a zero
        reading count beside a rail count above zero (rulings #78,
        #322). The retired daily-minimum test could not fire on data
        recorded after 0.12.15, because rails stopped reaching the
        minimum and rail-only days appended nothing to it, so its
        tail was the last three speaking days rather than the last
        three days (ruling #324). A silent day and a railed day both
        carry a zero count and differ only in the rail entry, which
        is why the rail column is the evidence. A rail that comes
        and goes within a day never confirms, while one that holds
        across days does.

        The plausible-value freeze, a real reading that stops moving,
        is not judged here: a device with a strong steady link reports
        the same value for hours and cannot be told from a stuck one.
        The project document records that rabbit hole and the learned
        flat-stretch approach that could restore it if it is ever
        worth building.
        """
        counts = record.get(DEV_SIGNAL_DAILY_COUNT) or []
        rails = record.get(DEV_SIGNAL_DAILY_RAIL) or []
        if len(counts) < RAIL_CONFIRM_DAYS or len(rails) < RAIL_CONFIRM_DAYS:
            return False
        # Non-strict on purpose (ruling #328): both tails are sliced
        # to the same length above, and a stored file whose two
        # series differ by a day must read as no rail rather than
        # raise inside a verdict.
        tail = zip(
            counts[-RAIL_CONFIRM_DAYS:],
            rails[-RAIL_CONFIRM_DAYS:],
            strict=False,
        )
        return all(count == 0 and (rail or 0) > 0 for count, rail in tail)

    @staticmethod
    def _is_signal(ent: er.RegistryEntry) -> bool:
        """Recognize a signal-strength entity from registry fields.

        The foreign-radio name test of ruling #248 was deleted here.
        A phone's bars are not a mesh link, but no name distinguishes
        them: the test caught an ESPHome node's own RSSI, whose
        sensor is called WiFi Signal, and missed the phone's cellular
        radio, whose sensor is not called cellular. A phone arrives on
        an integration the exclude list refuses whole, so nothing that
        reaches here is another device's radio.
        """
        if str(ent.original_device_class) == "signal_strength" or str(
            getattr(ent, "device_class", None)
        ) == "signal_strength":
            return True
        hay = " ".join(
            str(x)
            for x in (ent.entity_id, ent.unique_id, ent.original_name)
            if x
        ).lower()
        if not any(term in hay for term in SIGNAL_NAME_TERMS):
            return False
        # Matched by name only, so the unit decides (ruling #283). A
        # percentage here is a quality figure wearing the name of a
        # measurement, which is Tasmota's RSSI. Home Assistant allows
        # only dB and dBm for the signal_strength class, so nothing
        # carrying that class reaches this line.
        return not _is_percentage(ent)

    @property
    def signal_tracked(self) -> dict[str, int]:
        """Return counts of devices with a learned signal floor.

        Tracked means the device has a floor and so a live line: the
        signal analogue of Devices: Learned. Split by scale for the
        curious; the dwell rule is identical for both. Learning counts
        devices that report signal but have no floor yet, which since
        the floor exists from the first recorded day means a device
        whose history is entirely rail values (a floor of nothing
        rather than a false one). Muted devices still count here:
        muting suppresses judgment, not observation.
        """
        counts = {"lqi": 0, "rssi": 0, "learning": 0}
        for _device_id, record in self.watched_records():
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
        """Return how many devices have a signal line, after muting.

        The state for Tracked Signals: devices with a floor that are
        not signal-muted. Muting suppresses judgment, so an
        muted device is not something we are watching for signal.
        """
        counts = self.signal_tracked
        watched = counts["lqi"] + counts["rssi"]
        muted: int = sum(
            1
            for device_id, record in self.watched_records()
            if self._danger_line(record) is not None
            and self._signal_muted(device_id)
        )
        return watched - muted

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

        Signal-muted devices are observed but never judged, so
        they stay off this list until re-included by hand.
        """
        problems: list[dict[str, Any]] = []
        for device_id, record in self.watched_records():
            if self._signal_muted(device_id):
                continue
            if self.signal_railed(record):
                problems.append(
                    {
                        "name": self._display_names.get(device_id),
                        "device_id": device_id,
                        "kind": TODO_KIND_RAILED_SIGNAL,
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
        problems.sort(key=lambda row: (row["kind"] != TODO_KIND_RAILED_SIGNAL, row["name"] or ""))
        return problems

    @property
    def signal_weak_list(self) -> list[dict[str, Any]]:
        """Return devices whose link is weak right now.

        The Signal: Weak sensor. A device qualifies when its most
        recent folded day was a bad signal day: its own P5 fell far
        enough below its own recent normal, in its own units and its
        own spread (ruling #310). Until that ruling this read the
        dwell against a Red Threshold slider, and both are gone, so
        this is the same sensor answering a better question with the
        same one definition serving every surface (ruling #211).

        Separate from the rails for the same reason Battery: Low and
        Battery: Falling are separate. A rail is a broken
        measurement, confirmed over three days and persistent; a bad
        day is a reading about one day that may or may not repeat.

        Nothing notifies from this. A device drops off the next
        morning its signal holds, with no acknowledgment and no
        record, because it is a reading rather than an incident
        (ruling #59).
        """
        railed = {row["device_id"] for row in self.signal_problem_list}
        weak = []
        for device_id, record in (self.data.get(DATA_DEVICES) or {}).items():
            if device_id in railed:
                continue
            if (
                self._signal_muted(device_id)
                or device_id in self._muted_devices
            ):
                continue
            reading = self.signal_badday(record)
            if reading is None or not reading["bad"]:
                continue
            weak.append(
                {
                    "name": self._device_name(device_id),
                    "device_id": device_id,
                    "fall": reading["fall"],
                    "baseline": reading["baseline"],
                    "today": reading["today"],
                }
            )
        return weak

    @property
    def signal_weak_count(self) -> int:
        """Return how many links are weak right now."""
        return len(self.signal_weak_list)

    @property
    def signal_problem_count(self) -> int:
        """Return how many devices have a signal problem."""
        return len(self.signal_problem_list)

    def _signal_muted(self, device_id: str) -> bool:
        """Return whether a device is muted from signal judgment
        only. The same broad-to-narrow ladder as battery. Muting
        suppresses judgment, not observation: the device keeps
        recording its floor and dwell in storage, so re-inclusion is
        instant and arrives with history; it simply stops being
        reported. This is the manual removal from tracking the
        frozen-signal ruling requires, for a device that resists
        every recovery."""
        options = self.entry.options
        if self._watched.get(device_id) in options.get(
            CONF_SIGNAL_MUTED_INTEGRATIONS, []
        ):
            return True
        if self._device_labels.get(device_id, frozenset()) & set(
            options.get(CONF_SIGNAL_MUTED_LABELS, [])
        ):
            return True
        return device_id in options.get(CONF_SIGNAL_MUTED_DEVICES, [])

    @property
    def detected_signals(self) -> list[dict[str, Any]]:
        """Return every device with a signal reading, for the signal
        options picker: pick-from-detected, what you see is what is
        being judged. Muted devices are present, because an
        muted device is exactly the thing this picker exists to
        un-tick."""
        rows = [
            {
                "device_id": device_id,
                "name": self._display_names.get(device_id, device_id),
                "integration": self._watched.get(device_id, "?"),
                "labels": self._device_labels.get(
                    device_id, frozenset()
                ),
            }
            for device_id, record in self.data.get(
                DATA_DEVICES, {}
            ).items()
            if record.get(DEV_SIGNAL_VALUE) is not None
            or record.get(DEV_SIGNAL_DAILY_P5)
        ]
        rows.sort(key=lambda row: row["name"].lower())
        return rows
