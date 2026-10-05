# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: detect_signal.py, Version: 0.24.6 (2026-10-05)

"""Signal: the day's statistics, the bad-day judgment, and the rails.

Every device is judged against its own history and never against a
fixed number or against another device: a sensor two rooms away
lives its whole life at a level that would mean trouble in the same
room, and both can be reliable. A day is bad only when the fall
clears two gates, far enough in the device's own units and far
enough outside its own everyday bounce, because either gate alone
flags a steady device for a wobble or a jittery one every day.

Two findings come out of this file and they are not the same thing.
A weak day is recorded, charted and reported and never reaches a
phone, because nobody has yet shown which signal pattern predicts a
real failure and an alert that cries wolf teaches its owner to
ignore it. A railed reading, pinned at exactly 255 LQI or -128 RSSI
for three days, is a false reading rather than a weak link, and it
does notify. Anything written for a reader has to keep those two
apart; saying signal never alerts is wrong.

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

from datetime import timedelta

import math
import statistics

from typing import Any

from homeassistant.helpers import entity_registry as er

from homeassistant.util import dt as dt_util

from .daily_dates import FAMILY_SIGNAL, FAMILY_SIGNAL_ALT, dates_for, day_appended
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
    LOGGER,
    RAIL_CONFIRM_DAYS,
    SIGNAL_ALT_FIELDS,
    SIGNAL_NAME_TERMS,
    SIGNAL_REFUSED_UNITS,
    SIGNAL_SCALE_LQI,
    TODO_KIND_RAILED_SIGNAL,
    SIGNAL_SCALE_RSSI,
    DEV_SIGNAL_ALT,
    DEV_SIGNAL_SCALE,
    SIGNAL_RAIL_LQI,
    SIGNAL_RAIL_RSSI,
    TODO_DEVICE_ID,
    TODO_KINDS,
)
from .psquare import (
    psquare_feed_many,
    psquare_new,
    psquare_read,
)
from .records import _reset_signal_day


def _spread(values: list[float]) -> float:
    """Return the population standard deviation, in floating point.

    `statistics.pstdev` works in exact fractions, and the Signal Trends
    tab judges every stored day of every device through it: 3,122
    judgments on the reference fleet and 3,763 on the second, where it
    took 72 percent of the tab's time (0.22.20). The two-pass sum here
    is the textbook stable form. Measured against the exact answer on
    four storage files at every setting the screens allow, 1,292,967
    judgments, it changed no verdict, no normal and no fall, and no
    spread by more than one unit in the last binary place. It loses
    precision only for values near a billion, which no signal reading
    comes near, and a flat baseline that reads a trace above zero is
    lifted to the spread floor as zero is.
    """
    count = len(values)
    mean = sum(values) / count
    return math.sqrt(sum((value - mean) ** 2 for value in values) / count)


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



def _badday_of(
    days: tuple[Any, ...],
    today_raw: Any,
    stored_scale: str | None,
    drop_rssi: float,
    drop_other: float,
    sensitivity: float,
) -> dict[str, float] | None:
    """One device-day's bad-day reading, from the days before it and
    the settings (ruling #310). Pure: the same inputs always give the
    same reading. See `signal_badday` for the rule itself."""
    today = _usable(today_raw)
    if today is None:
        return None
    base = [value for value in (_usable(entry) for entry in days) if value is not None]
    if len(base) < BADDAY_MIN_BASELINE:
        return None
    if min(base) < 0 <= max(base):
        return None
    if (today < 0) is not (base[0] < 0):
        return None
    middle = statistics.median(base)
    spread = _spread(base)
    if spread < BADDAY_MIN_SPREAD:
        spread = BADDAY_MIN_SPREAD
    fall = middle - float(today)
    scale = stored_scale if stored_scale is not None else scale_of(middle)
    drop = drop_rssi if scale == SIGNAL_SCALE_RSSI else drop_other
    deviations = fall / spread
    return {
        "today": float(today),
        "baseline": float(middle),
        "spread": float(spread),
        "fall": float(fall),
        "deviations": float(deviations),
        "drop_gate": float(drop),
        "bad": bool(fall >= drop and deviations >= sensitivity),
    }

class SignalMixin:
    """Signal: the day's statistics, the bad-day judgment, and the rails."""

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
        """Fold the primary, then the second scale if there is one.

        Each scale's row is dated with the day being folded (0.24.4,
        issue #18): a day with no reading writes no row, and its date
        is recorded as skipped, so the history keeps its calendar.
        """
        day = getattr(self, "_folding_day", None)
        for bucket, judged, family in (
            (record, True, FAMILY_SIGNAL),
            (record.get(DEV_SIGNAL_ALT), False, FAMILY_SIGNAL_ALT),
        ):
            if bucket is None:
                continue
            before = len(bucket.get(DEV_SIGNAL_DAILY_COUNT) or [])
            wrote = self._roll_one_scale(bucket, fold_now, judged=judged)
            after = len(bucket.get(DEV_SIGNAL_DAILY_COUNT) or [])
            added = bool(wrote) or after > before
            # The roll says whether it wrote the day's row (0.24.6): at
            # the History days limit a row added is a row trimmed.
            if day is not None and (added or after != before):
                day_appended(record, family, before, after, day, added=added)

    def _roll_one_scale(
        self, record: dict[str, Any], fold_now: float, judged: bool = True
    ) -> bool:
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

        Returns whether a row was written (0.24.6), so the fold can date
        it even when the History days limit trims a row as it adds one.

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
        wrote = False
        if count > 0 and reads > 0:
            wrote = True
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
            wrote = True
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
        return wrote

    def _feed_signal(
        self, record: dict[str, Any], value: float, now: float
    ) -> None:
        """Route one signal reading to the device's statistics.

        Only real readings feed the day's statistics; a rail value
        (255, -128) is the type's fill value, not a measurement, so it
        is counted as a rail instead, which the rail detector reads.
        """
        # Which of the device's scales this reading belongs to. The
        # primary is the record itself; a second scale is its own
        # block, recorded and never judged (rulings #284, #285).
        bucket = signal_bucket(record, scale_of(value))

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
        value keeps accruing through silence, as a time-weighted
        percentile should read a silent link.
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
        reads as ten percent (ruling #310, keeping the lesson of #250,
        which was rescinded with dwell).
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
        if _usable(series[position]) is None:
            return None
        window = self._badday_baseline_days()
        # The arithmetic is a pure function of the window and the
        # settings. It is not cached: kept for every day of every
        # device, the answers held 29.5 MB on the second house to save
        # Signal Trends a tenth of a second off the loop (measured in
        # the 0.23.19 adversarial round).
        found = _badday_of(
            tuple(series[max(0, position - window):position]),
            series[position],
            record.get(DEV_SIGNAL_SCALE),
            self._badday_drop(SIGNAL_SCALE_RSSI),
            self._badday_drop(None),
            self._badday_sensitivity(),
        )
        return found

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
        three days (ruling #324). A railed day writes a row with a zero
        count and a real rail entry; a silent day writes no row at all
        (see `_roll_one_scale`), so the rail column is the evidence. The
        three rows must fall on three consecutive calendar days (0.24.4,
        issue #18): a rail broken by a silent day is not proven to have
        held. A rail that comes and goes within a day never confirms,
        while one that holds across days does.

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
        if not all(count == 0 and (rail or 0) > 0 for count, rail in tail):
            return False
        yesterday = dt_util.as_local(dt_util.utcnow() - timedelta(days=1)).date()
        dates = dates_for(record, FAMILY_SIGNAL, len(counts), yesterday)[-RAIL_CONFIRM_DAYS:]
        # Each date beside the next: one pair fewer than dates, on purpose.
        return all(
            (later - earlier).days == 1
            for earlier, later in zip(dates, dates[1:], strict=False)
        )

    @staticmethod
    def _is_signal(ent: er.RegistryEntry) -> bool:
        """Recognize a signal-strength entity from registry fields.

        By device class first; where there is none, by the words a
        signal entity's name carries, with the unit deciding (ruling
        #283). What is never done is refusing an entity by its name
        (ruling #267, replacing #248's word lists of refused terms): no
        word tells a phone's bars from a mesh link, and a phone arrives
        on an integration the exclude list refuses whole, so nothing
        that reaches here is another device's radio.
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

    def _todo_signal_since(self, device_id: str) -> float | None:
        """Return when a device's signal fault was added to the list.

        A rail carries no physical start time (it is confirmed from
        the daily rail column, #322), so its age is measured from the
        list item's stamp, the moment the sync first listed it. This
        keeps the section consistent with the list it mirrors.
        """
        for record in self.todo_items:
            if record.get(TODO_DEVICE_ID) == device_id:
                # By the kind's name since the kinds took one vocabulary
                # (ruling #299). The lookup kept the old name, "signal",
                # so every signal fault read "for ?" with its start
                # stored beside it; found on the reference rig's two
                # rails (0.23.19).
                return (record.get(TODO_KINDS) or {}).get(TODO_KIND_RAILED_SIGNAL)
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
        nothing (rulings #59, kept by #310, and #211).

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
        # so anything added here becomes a notification. A weak day has
        # no day-to-day persistence to notify on: measured when dwell
        # was the judge, on the reference fleet
        # only three of twelve device-days above twenty percent were
        # still above it the next morning, so a low arriving here
        # would push tonight and clear tomorrow. Signal reports and
        # does not push (ruling #59, kept by #310), and the low kind
        # lives on signal_weak_list below, which nothing notifies
        # from (ruling #211).
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
        (ruling #59, kept by #310).
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
        recording its readings and daily statistics, so re-inclusion is
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
