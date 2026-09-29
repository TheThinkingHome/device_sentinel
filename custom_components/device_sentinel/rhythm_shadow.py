# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: rhythm_shadow.py, Version: 0.23.18 (2026-09-29)

"""A second rhythm, computed beside the one judgment uses (ruling #542).

The trimmed maximum sets aside one day and keeps the next highest, so a
single bad day that survives the trim sets a device's rhythm outright,
for as long as the window holds it. On the reference rig two faults
since fixed (#536, #541) left an outage day and a stop day in the same
fortnight, and the stop day became the rhythm of 54 devices: Leak
Kitchen Sink read 17.7 minutes against its true 4.

The clipped rhythm answers from what is kept rather than from one day.
It works on the logarithm of each day's longest gap, because gaps are
skewed and a day twice as long is as far out as a day half as long.
Take the mean and the spread, set aside every day more than
CLIP_DEVIATIONS spreads above the mean, and repeat until nothing more
is set aside. The rhythm is the mean of what is kept plus
CLIP_TARGET_DEVIATIONS spreads: the 90th-percentile day, the same
target the trimmed maximum aims at. The spread never reads below
CLIP_SPREAD_FLOOR, so no device is treated as perfectly regular.

Simulated on the reference rig's 80 days and the second house's 39
before it was built: no more false alarms than today on the rig, the
window jumping on 0.1% of days against 8.1%, and five planted four-hour
days in a device's recent history moving its window not at all, where
they moved today's six and a half times.

Nothing reads it but the telemetry report and rhythm_shadow.md. No
verdict, list, push, brief or screen changes. The shadow records where
the two rules would disagree about a device, so the switch is ruled on
what the fleets showed rather than on a simulation.

Recorded alongside, and not built: a shared silence day, one on which
a large share of a house's steady reporters had a longest gap far past
their usual, so its cause was the house rather than the devices. The
simulation found clipping sets those days aside on its own; the name
is kept so the idea can be picked up here if the shadow shows it is
needed.
"""

from __future__ import annotations

import contextlib
import math
import os
import statistics
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    CLIP_DEVIATIONS,
    CLIP_MAX_DAYS,
    CLIP_SPREAD_FLOOR,
    CLIP_START_DAYS,
    CLIP_TARGET_DEVIATIONS,
    DATA_DEVICES,
    DEV_DAILY_MAX,
    FREEZE_ARMING_DAYS,
    LOGGER,
    PROBE_FILE_MAX_BYTES,
    PROBE_FILE_ROLLS,
    REPORT_DIR,
    REPORT_RHYTHM_SHADOW,
)

# The two rules' names as the file writes them.
_TODAY = "trimmed maximum"
_CLIPPED = "clipped"


def clipped_rhythm(daily: list[Any]) -> dict[str, Any] | None:
    """The clipped rhythm of a device's daily maxima, or None.

    None below CLIP_START_DAYS usable days: until then the trimmed
    maximum is the only rhythm, as it will stay after the switch. A day
    that is not a positive number is not read, as it is not by the
    trimmed maximum. Returns the rhythm in seconds and the figures it
    was built from, so the report can show its working.
    """
    days = [
        float(v)
        for v in daily
        if isinstance(v, (int, float))
        and not isinstance(v, bool)
        and math.isfinite(v)
        and v > 0
    ]
    if len(days) < CLIP_START_DAYS:
        return None
    read = days[-CLIP_MAX_DAYS:]
    logs = [math.log(v) for v in read]
    kept = list(logs)
    for _ in range(len(logs)):
        mean = statistics.fmean(kept)
        spread = max(statistics.pstdev(kept), CLIP_SPREAD_FLOOR)
        survivors = [v for v in kept if v <= mean + CLIP_DEVIATIONS * spread]
        if len(survivors) == len(kept):
            break
        kept = survivors
    mean = statistics.fmean(kept)
    spread = max(statistics.pstdev(kept), CLIP_SPREAD_FLOOR)
    # No rhythm rather than an overflow (ruling #544). The range check
    # keeps every stored gap within 360 days, so this cannot be reached
    # from storage; it stands behind that check, not instead of it.
    try:
        basis = math.exp(mean + CLIP_TARGET_DEVIATIONS * spread)
        typical = math.exp(mean)
    except OverflowError:
        return None
    if not (math.isfinite(basis) and basis > 0):
        return None
    return {
        "basis": basis,
        "typical": typical,
        "spread": spread,
        "read": len(read),
        "clipped": len(read) - len(kept),
    }


class RhythmShadowMixin:
    """The clipped rhythm in shadow, and its record of disagreements."""

    # Provided by the coordinator and its other mixins.
    data: dict[str, Any]
    hass: Any
    version: str
    _watched: dict[str, str]
    _muted_devices: dict[str, str]

    def _init_rhythm_shadow(self) -> None:
        """The shadow's state, held in memory only.

        device_id -> (which rule alone would list it, since when, carried
        over a restart). A disagreement standing at a restart is written
        again on the first check after it, marked as carried, so the
        daily count does not take it for a new one.
        """
        self._shadow_open: dict[str, tuple[str, float, bool, str]] = {}
        self._shadow_first_check = True
        self._shadow_opened = 0
        self._shadow_closed = 0
        self._shadow_minutes = {_TODAY: 0, _CLIPPED: 0}
        self._shadow_last_check: float | None = None
        self._shadow_write_failed = False
        # When the counts on the next daily line began: the fold before
        # it, or this start if it came later. The counters live in
        # memory, so a restart begins them again, and the daily line
        # says from when rather than passing a part of a day off as
        # the whole of it.
        self._shadow_counting_from: float | None = None

    def clipped_for(self, device_id: str | None, daily: list[Any]) -> dict[str, Any] | None:
        """The clipped rhythm, worked out once until the days change.

        A device's daily maxima change only at the midnight fold or a
        repair, so the rule is computed once per change rather than
        every minute: 44 ms a minute on the second house with a year of
        history each, measured on 29 September 2026, to next to nothing.
        The key is the series' length and its last and first values,
        which any fold or repair moves.
        """
        if device_id is None:
            return clipped_rhythm(daily)
        cache: dict[str, tuple[tuple[Any, ...], dict[str, Any] | None]] | None = getattr(
            self, "_clip_cache", None
        )
        if cache is None:
            cache = {}
            self._clip_cache = cache
        key = (len(daily), daily[-1] if daily else None, daily[0] if daily else None)
        held = cache.get(device_id)
        if held is not None and held[0] == key:
            return held[1]
        found = clipped_rhythm(daily)
        cache[device_id] = (key, found)
        return found

    def clipped_window(
        self, record: dict[str, Any], device_id: str | None = None
    ) -> float | None:
        """The freeze window the clipped rhythm would give, or None.

        The same grace margin today's window adds (#85), and the same
        arming gate: a device with too few days has no window under
        either rule.
        """
        daily = record.get(DEV_DAILY_MAX) or []
        if len(daily) < FREEZE_ARMING_DAYS:
            return None
        found = self.clipped_for(device_id, daily)
        if found is None:
            return None
        rhythm = found["basis"]
        return rhythm + self._freeze_grace(rhythm)  # type: ignore[attr-defined]

    def shadow_check(self, now: float) -> None:
        """Compare the two rules on every judged device, this minute.

        Only the part the rhythm decides is compared: whether the
        device's silence has reached its window. Both rules read the
        same silence, with Device Sentinel's own stops and its
        upstreams' outages already taken out (#160, #536), so the only
        difference is the window. A device muted from freeze, held by
        its upstream, or with no clipped rhythm yet is not compared.
        Runs after the sweep, inside it the startup grace holds every
        verdict and the shadow holds too.
        """
        if self._in_startup_grace():  # type: ignore[attr-defined]
            return
        step = 60.0
        if self._shadow_last_check is not None:
            step = min(max(now - self._shadow_last_check, 0.0), 300.0)
        self._shadow_last_check = now
        if self._shadow_counting_from is None:
            self._shadow_counting_from = now
        lines: list[str] = []
        compared: set[str] = set()
        for device_id in self._watched:
            record = self.data[DATA_DEVICES].get(device_id)
            if not isinstance(record, dict):
                continue
            if device_id in self._muted_devices or self._freeze_muted(device_id):  # type: ignore[attr-defined]
                continue
            if self._held_by_upstream(device_id, now):  # type: ignore[attr-defined]
                continue
            try:
                today_window = self._freeze_window(record)  # type: ignore[attr-defined]
                clipped = self.clipped_window(record, device_id)
                if today_window is None or clipped is None:
                    continue
                silence = self._observed_silence(  # type: ignore[attr-defined]
                    record, now, device_id, today_window
                )
            except Exception as err:  # noqa: BLE001 - the shadow never stops a check
                LOGGER.debug(
                    "device_sentinel: rhythm shadow skipped %s this minute (%s)",
                    device_id,
                    err,
                )
                continue
            if silence is None:
                continue
            compared.add(device_id)
            listed_today = silence >= today_window
            listed_clipped = silence >= clipped
            alone = (
                _TODAY
                if listed_today and not listed_clipped
                else _CLIPPED
                if listed_clipped and not listed_today
                else None
            )
            if alone is not None:
                self._shadow_minutes[alone] += int(round(step / 60.0))
            standing = self._shadow_open.get(device_id)
            if alone is not None and (standing is None or standing[0] != alone):
                carried = self._shadow_first_check
                self._shadow_open[device_id] = (
                    alone, now, carried, self._shadow_name(device_id)
                )
                if not carried:
                    self._shadow_opened += 1
                lines.append(
                    self._shadow_line(
                        now, device_id, "opened", alone, silence,
                        today_window, clipped,
                        "carried over a restart" if carried else "",
                    )
                )
            elif alone is None and standing is not None:
                del self._shadow_open[device_id]
                self._shadow_closed += 1
                reset = getattr(self, "_clock_reset", None)
                ended = (
                    "both would list it"
                    if listed_today
                    else "the clocks restarted"
                    if reset is not None and now - reset[0] < 120.0
                    else "it spoke"
                )
                lines.append(
                    self._shadow_line(
                        now, device_id, "closed", standing[0], silence,
                        today_window, clipped,
                        f"after {self._shadow_span(now - standing[1])}, {ended}",
                        name=standing[3],
                    )
                )
        for device_id in list(self._shadow_open):
            if device_id not in compared:
                # No longer compared: muted, held, or gone. Closed
                # without a verdict on who was right.
                standing = self._shadow_open.pop(device_id)
                self._shadow_closed += 1
                lines.append(
                    self._shadow_line(
                        now, device_id, "closed", standing[0], None, None,
                        None, "no longer compared", name=standing[3],
                    )
                )
        self._shadow_first_check = False
        if lines:
            self.hass.async_add_executor_job(self._shadow_write, lines)

    def shadow_fold(self, now: float) -> None:
        """One line a day with the counts, written at the midnight fold.

        Every judged device's two windows are compared as they stand
        after the day's maxima were folded in.
        """
        narrower = same = wider = judged = 0
        for device_id in self._watched:
            record = self.data[DATA_DEVICES].get(device_id)
            if not isinstance(record, dict):
                continue
            try:
                today_window = self._freeze_window(record)  # type: ignore[attr-defined]
                clipped = self.clipped_window(record, device_id)
            except Exception as err:  # noqa: BLE001 - the count skips it
                LOGGER.debug(
                    "device_sentinel: rhythm shadow left %s out of the day's "
                    "count (%s)",
                    device_id,
                    err,
                )
                continue
            if today_window is None or clipped is None:
                continue
            judged += 1
            ratio = clipped / today_window
            if ratio < 0.95:
                narrower += 1
            elif ratio > 1.05:
                wider += 1
            else:
                same += 1
        since = self._shadow_counting_from
        counted = (
            f"Counted from {self._episode_stamp(since)}. "  # type: ignore[attr-defined]
            if since is not None
            else "Nothing counted since the last start. "
        )
        detail = (
            f"{counted}{judged} devices with both windows: clipped narrower on "
            f"{narrower}, within 5% on {same}, wider on {wider}. "
            f"Disagreements opened {self._shadow_opened}, closed "
            f"{self._shadow_closed}, still open {len(self._shadow_open)}. "
            f"Device-minutes only the trimmed maximum would list "
            f"{self._shadow_minutes[_TODAY]}, only the clipped rhythm "
            f"{self._shadow_minutes[_CLIPPED]}."
        )
        self._shadow_opened = 0
        self._shadow_closed = 0
        self._shadow_minutes = {_TODAY: 0, _CLIPPED: 0}
        self._shadow_counting_from = now
        line = (
            f"| {self._episode_stamp(now)} | day |  |  |  |  |  | "  # type: ignore[attr-defined]
            f"{self._report_cell(detail)} |"  # type: ignore[attr-defined]
        )
        self.hass.async_add_executor_job(self._shadow_write, [line])

    # ------------------------------------------------------------ the file

    @staticmethod
    def _shadow_span(seconds: float) -> str:
        minutes = seconds / 60.0
        if minutes < 90:
            return f"{minutes:.0f}m"
        return f"{minutes / 60.0:.1f}h"

    def _shadow_line(  # noqa: PLR0913 - one row, one call
        self,
        now: float,
        device_id: str,
        what: str,
        alone: str,
        silence: float | None,
        today_window: float | None,
        clipped: float | None,
        detail: str,
        name: str | None = None,
    ) -> str:
        if name is None:
            name = self._shadow_name(device_id)
        span = self._shadow_span
        return (
            f"| {self._episode_stamp(now)} "  # type: ignore[attr-defined]
            f"| {what} "
            f"| {self._report_cell(str(name))} "  # type: ignore[attr-defined]
            f"| {alone} "
            f"| {span(silence) if silence is not None else ''} "
            f"| {span(today_window) if today_window is not None else ''} "
            f"| {span(clipped) if clipped is not None else ''} "
            f"| {self._report_cell(detail)} |"  # type: ignore[attr-defined]
        )

    def _shadow_name(self, device_id: str) -> str:
        """The device's name as it stands, kept when a line opens so a
        device removed before its line closes is still named."""
        return str(self._device_name(device_id) or device_id)  # type: ignore[attr-defined]

    def _shadow_header(self) -> list[str]:
        return [
            f"# Device Sentinel v{self.version} Rhythm Shadow",
            "",
            f"Started {self._format_report_time(dt_util.now())}",  # type: ignore[attr-defined]
            "",
            "Two rhythms, and where they would disagree (ruling #542). "
            "Judgment uses the TRIMMED MAXIMUM: the highest of a "
            "device's last 14 daily longest gaps is set aside and the "
            "next highest is its rhythm. The CLIPPED rhythm is computed "
            "beside it and changes nothing: from a device's 28th day, "
            "over up to its last 42, it sets aside every day far above "
            "the device's usual and takes the usual plus its spread, "
            "aiming at the same 90th-percentile day. Each window is the "
            "rhythm plus the same grace margin.",
            "",
            "A line is written when the two rules first disagree about "
            "a device, one would list it frozen and the other would "
            "not (WHO LISTS names the one that would), and again when "
            "they agree once more: it spoke, or its silence passed both "
            "windows. SILENCE is the silence both rules read, with "
            "Device Sentinel's own stops and its upstreams' outages "
            "taken out. A device muted from freeze, held by an upstream "
            "outage, or younger than 28 days is not compared. One line "
            "a day, after the midnight fold, gives the counts, from the "
            "moment it names: the fold before, or the last start if that "
            "came later, since a restart begins the counts again. Only the "
            "rhythm is compared: the grace at startup, the holds and the "
            "list itself are the same under both. At "
            f"{PROBE_FILE_MAX_BYTES // 1_000_000} MB this file becomes "
            f"{REPORT_RHYTHM_SHADOW}.1, and older ones move up to "
            f".{PROBE_FILE_ROLLS}.",
            "",
            "| WHEN | EVENT | DEVICE | WHO LISTS | SILENCE | TRIMMED WINDOW "
            "| CLIPPED WINDOW | DETAIL |",
            "|---|---|---|---|---|---|---|---|",
        ]

    def _shadow_write(self, lines: list[str]) -> None:
        """Append lines to rhythm_shadow.md, rolling it at the cap.

        Runs in the executor. A lost line is only a lost line: one
        warning per start says so, and nothing else is affected.
        """
        directory = self.hass.config.path(REPORT_DIR)
        path = os.path.join(directory, REPORT_RHYTHM_SHADOW)
        try:
            with self._probe_lock:  # type: ignore[attr-defined]
                os.makedirs(directory, exist_ok=True)
                body = "\n".join(lines) + "\n"
                with contextlib.suppress(OSError):
                    if (
                        os.path.getsize(path) + len(body.encode("utf-8"))
                        > PROBE_FILE_MAX_BYTES
                    ):
                        for rung in range(PROBE_FILE_ROLLS, 0, -1):
                            older = f"{path}.{rung - 1}" if rung > 1 else path
                            if os.path.exists(older):
                                os.replace(older, f"{path}.{rung}")
                if not os.path.exists(path):
                    body = "\n".join(self._shadow_header()) + "\n" + body
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(body)
        except Exception as err:  # noqa: BLE001
            if self._shadow_write_failed:
                LOGGER.debug("device_sentinel: %s not written (%s)", path, err)
                return
            self._shadow_write_failed = True
            LOGGER.warning(
                "Device Sentinel could not write %s (%s). Rhythm shadow "
                "lines are lost until it can; detection is unaffected. "
                "Said once per start.",
                path,
                err,
            )
