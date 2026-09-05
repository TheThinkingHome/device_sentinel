# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tools/simulation/generator.py, Version: 0.20.5 (2026-09-05)

"""Expand the scenario into a stream of report times.

Validated over six passes against both real fleets, each pass finding
an error in how the source data was read rather than a number to
adjust:

1. Episodes were planted at a flat rate. They are emergent: a drawn
   gap crossing that device's own window.
2. The window was fitted as a straight line. It is a power law, and
   the line was wrong by four and a half hours at the slow end, which
   is exactly where the model misbehaved.
3. Misses were applied per report, so a five minute device got twenty
   times more chances than an hourly one. They arrive per unit time.
4. The telemetry's gaps column was read as a series of gaps. It is a
   series of daily maxima, and reading it wrongly made every device on
   both fleets look ten to fourteen times slower than it is.
5. Miss magnitude was scaled by the rhythm. It scales with the basis.
6. The measured 2.27 overshoot is the median of episodes, which are
   misses that already crossed the window. Using that conditional
   figure as the distribution of every miss made nearly all of them
   fire.

Where it lands: episode rate 0.091 against a measured 0.12 on the
first fleet and 0.300 against 0.32 on the second; four of five rhythm
bands inside the measurement's own 95 percent interval; and a
conditional overshoot of 2.18 against a measured 2.27, which the
generator was not tuned on and which is the strongest evidence here.

Two limits, recorded rather than hidden. The ten minute to one hour
band generates no episodes against a real 0.57, on seven devices. And
the real band rates carry intervals of plus or minus 0.46 to 0.56 on
samples of six to fourteen devices, so differences smaller than that
cannot be resolved from the data either fleet holds today.


Deterministic: the workbook's seed plus the device name seeds each
device's own stream, so one device's history never shifts when another
is edited, and the same workbook always produces the same run.

The gaps are not drawn from each device's learned basis. That would be
circular, because the basis is what the judgment compares against, and
a generator built from it would agree with the code by construction
whatever the code did. They are drawn instead from the two things
measured off the real fleets and recorded in the validation targets:
the spread between a device's median and its worst ordinary gap, and
the rate at which real devices overshoot far enough to be capped.

Two fidelities, ruled 5 September. Report-boundary is the default: one
event per report, which is what the judgment reads, and the merged
fleet's fastest devices would otherwise emit millions of events that
nothing looks at. Full fidelity can be asked for on a named day, for a
storm or a tracker burst where the sub-gap shape is the thing under
test.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

from scenario import (
    BATTERY_NOISE, BATTERY_PLATEAU, BATTERY_REPLACED, BATTERY_STEP,
    BATTERY_ZERO, EXCLUDED, FREEZE, MUTED, NEVER, SIGNAL_BAD,
    SIGNAL_RAILED, UNAVAILABLE, UN_EXCLUDED, UN_MUTED, Device, Scenario,
)

DAY = 86400.0

# Measured on the reference fleets, 14 days each, and the standard the
# generated fortnight is checked against.
FLEET_PROFILE = {
    # episodes per device per 14 days, share ended by an intervention,
    # share of learned gaps that were capped
    # Share of completed gaps that overshot far enough to be capped,
    # and the share of episodes ended by an intervention rather than
    # by the device speaking again. Both measured over 14 days.
    # `tail` is the chance of a missed report per day. It is the one
    # fitted number here, fitted to the measured episode rate and to
    # nothing else: 0.35 and 0.60 reproduce 0.091 and 0.300 episodes
    # per device per fortnight against a measured 0.12 and 0.32.
    # Everything else is taken from the fleets directly.
    "james": dict(intervention=0.17, capped=0.00, tail=0.35),
    "tim": dict(intervention=0.28, capped=0.42, tail=0.60),
}

# An episode is not planted at a rate. It happens when a drawn gap
# crosses that device's own window, and the window is what the real
# fleets show it to be: fitted over 91 real episodes across both
# houses, window = 1.18 x basis + 1.77 hours, median error 54 minutes.
#
# That curve is why a rate cannot work. Its multiplier falls from
# about 4.7 at a six minute basis to 1.13 at fifty-nine hours, so a
# fast device must overshoot nearly five times its rhythm to register
# an episode and a slow one needs thirteen percent. On the second
# fleet that shows as ten devices under ten minutes producing no
# episodes at all in a fortnight, while the six to twenty-four hour
# band produced 0.86 each.
# Fitted over 91 real episodes across both houses. A power law, not a
# straight line: the line was off by nearly two hours in the twelve to
# thirty hour band and four and a half at the top, which is precisely
# where the slow devices over-fired, and this fits every band to
# within seven percent with a median error of 4.3 percent.
WINDOW_COEFF = 2.412
WINDOW_POWER = 0.798

# The basis comes from the telemetry's daily maxima series, which is
# what that column holds: one value per day, the worst gap of that
# day, trimmed. It is not a series of gaps, and reading it as one gave
# every device a rhythm ten to fourteen times slower than its real
# one. The rhythm is taken from event counts over the observation
# window instead, which is the only measure of it either fleet keeps.
#
# Measured after the correction: a device's basis sits about 14 times
# its rhythm on the first fleet and 12 on the second.

# A real episode's silence scales with the device's daily maxima, not
# with how often it normally speaks. But 2.27 is the median of
# episodes, and an episode is by definition a miss that already
# crossed the window, so that figure is conditional. Using it as the
# distribution of every miss made almost all of them large enough to
# fire, and the slowest band produced 0.77 episodes a fortnight
# against a real 0.23.
#
# Misses are drawn about the daily-max median itself, broadly. Which
# of them become episodes is then decided by the window, and the
# conditional median of those that do is checked against the measured
# 2.27 rather than assumed.
MISS_MEDIAN = 0.8
MISS_SIGMA = 0.55


def window_for(basis_s: float) -> float:
    """The window a device of this basis would be given, in seconds."""
    hours = max(basis_s, 1.0) / 3600.0
    return WINDOW_COEFF * (hours ** WINDOW_POWER) * 3600.0


@dataclass
class Report:
    """One moment a device spoke."""

    at: float
    device: str
    battery: float | None = None
    signal: float | None = None


@dataclass
class DeviceRun:
    """Everything one device did across the run."""

    device: Device
    reports: list[Report] = field(default_factory=list)
    silences: list[tuple[float, float, str]] = field(default_factory=list)
    excluded_from: list[tuple[float, float]] = field(default_factory=list)
    muted_from: list[tuple[float, float]] = field(default_factory=list)


def _seed_for(scenario: Scenario, name: str) -> int:
    """A stable per-device seed, so editing one row cannot move another."""
    digest = hashlib.sha256(f"{scenario.seed}:{name}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _gap(rng: random.Random, device: Device, capped_rate: float,
         tail: float = 0.3) -> float:
    """One ordinary gap for this device.

    Log-normal around the rhythm, with the spread taken from the
    device's own rhythm to basis ratio. Nothing here knows about the window, so an episode is
    a consequence of the draw rather than a decision.

    The capping rate is deliberately not applied here. Forty-two
    percent of the second fleet's *episodes* were capped, not
    forty-two percent of its gaps, and treating it as the latter
    produced 289 episodes in a fortnight against a real 21.
    """
    median = max(device.median_gap_s, 1.0)
    spread = max(device.max_gap_s / median, 1.05)
    # The basis is a multiple of the rhythm rather than a near
    # neighbour of it, so the spread is taken logarithmically.
    sigma = max(0.10, min(0.60, math.log(spread) / 4.0))
    gap = median * rng.lognormvariate(0.0, sigma)
    # The miss chance is per unit time, not per report. A device
    # reporting every five minutes does not miss twenty times more
    # often than one reporting hourly: a miss comes from something
    # outside the device, mesh congestion or a sleepy radio that did
    # not wake, and those arrive on the clock. Applied per gap it put
    # 3.7 episodes a fortnight on the fastest band, where both real
    # fleets show none at all.
    per_gap = tail * (median / DAY)
    if rng.random() < per_gap:
        # A missed report, in multiples of the rhythm: a sleepy end
        # device that did not wake, a mesh retry that never landed.
        # Ordinary jitter alone cannot produce the episodes both real
        # fleets show, because their median to worst ratios are tight
        # and a lognormal that narrow never reaches the window.
        scale = device.daily_max_median_s or device.max_gap_s
        gap = scale * MISS_MEDIAN * rng.lognormvariate(0.0, MISS_SIGMA)
    return max(0.5, gap)


def _battery_series(device: Device, codes: list[str]) -> dict[int, float]:
    """The battery level on each day it changes.

    Steps come from the device's own weekly rate where it has one. A
    plateau that breaks falls fast, which is the shape the one real
    proof device showed: 32 percent held for ten days, then gone.
    """
    if device.battery is None:
        return {}
    level = float(device.battery)
    out: dict[int, float] = {}
    step = abs(device.battery_rate_wk or 0.0) / 7.0 or 0.35
    for index, code in enumerate(codes):
        day = index + 1
        if code == BATTERY_STEP:
            level = max(0.0, level - step * 7.0)
        elif code == BATTERY_PLATEAU:
            level = max(0.0, level - 9.0)
        elif code == BATTERY_REPLACED:
            level = 100.0
        elif code == BATTERY_ZERO:
            level = 0.0
        elif code == BATTERY_NOISE:
            level = min(100.0, level + 1.0)
        else:
            continue
        out[day] = round(level, 1)
    return out


def _signal_for(device: Device, code: str, rng: random.Random) -> float | None:
    """A signal reading for the day, in that device's own units."""
    if device.signal_median is None:
        return None
    if code == SIGNAL_RAILED:
        # The rail value: reads as perfect and means no reading at all.
        return 255.0 if device.signal_median > 0 else 0.0
    floor = device.signal_floor if device.signal_floor is not None else device.signal_median
    if code == SIGNAL_BAD:
        return round(floor - abs(device.signal_median - floor) * 0.5, 2)
    return round(rng.uniform(min(floor, device.signal_median),
                             max(floor, device.signal_median)), 2)


def expand(scenario: Scenario, day_from: int = 1,
           day_to: int | None = None) -> dict[str, DeviceRun]:
    """Expand the scenario into per-device report streams."""
    day_to = day_to or scenario.days
    epoch = datetime(scenario.start.year, scenario.start.month,
                     scenario.start.day, tzinfo=timezone.utc).timestamp()
    runs: dict[str, DeviceRun] = {}

    for device in scenario.devices:
        rng = random.Random(_seed_for(scenario, device.name))
        profile = FLEET_PROFILE[device.fleet]
        capped = profile["capped"]
        window = window_for(device.max_gap_s)
        run = DeviceRun(device=device)
        batteries = _battery_series(device, device.days)
        battery = device.battery
        excluded_since = muted_since = None

        now = epoch + (day_from - 1) * DAY
        end = epoch + day_to * DAY
        silent_until = None

        while now < end:
            day = int((now - epoch) // DAY) + 1
            if day > day_to:
                break
            code = device.code(day)

            if code == EXCLUDED and excluded_since is None:
                excluded_since = now
            elif code == UN_EXCLUDED and excluded_since is not None:
                run.excluded_from.append((excluded_since, now))
                excluded_since = None
            if code == MUTED and muted_since is None:
                muted_since = now
            elif code == UN_MUTED and muted_since is not None:
                run.muted_from.append((muted_since, now))
                muted_since = None

            if code in (FREEZE, UNAVAILABLE, NEVER):
                if silent_until is None:
                    silent_until = now + DAY
                    run.silences.append((now, silent_until, code))
                else:
                    began, _, kind = run.silences[-1]
                    silent_until = now + DAY
                    run.silences[-1] = (began, silent_until, kind)
                now += DAY
                continue

            if silent_until is not None and now >= silent_until:
                silent_until = None

            # Ordinary silence, emergent rather than planted. Both
            # houses produce episodes with nothing wrong: 12 in a
            # fortnight on the first fleet and 79 on the second. The
            # scenario grid owns the deliberate faults; this is the
            # house's own noise, and without it a run is quieter than
            # reality and the false positive control proves nothing.
            step = _gap(rng, device, capped, profile["tail"])
            if step > window:
                run.silences.append((now, now + step, "ordinary"))
            run.reports.append(Report(
                at=now, device=device.name, battery=battery,
                signal=_signal_for(device, code, rng),
            ))
            now += step
            continue

            if day in batteries:
                battery = batteries[day]

        if excluded_since is not None:
            run.excluded_from.append((excluded_since, end))
        if muted_since is not None:
            run.muted_from.append((muted_since, end))
        runs[device.name] = run

    return runs


def episode_profile(runs: dict[str, DeviceRun], scenario: Scenario,
                    days: int = 14) -> dict[str, dict]:
    """What the generated run looks like, in the terms the real fleets
    were measured in. This is what validation compares."""
    epoch = datetime(scenario.start.year, scenario.start.month,
                     scenario.start.day, tzinfo=timezone.utc).timestamp()
    window = epoch + days * DAY
    out: dict[str, dict] = {}
    for fleet in ("james", "tim"):
        members = [d.name for d in scenario.by_fleet(fleet)]
        overshoot = total = 0
        for name in members:
            run = runs[name]
            basis = max(run.device.max_gap_s, run.device.median_gap_s)
            times = [r.at for r in run.reports if r.at < window]
            for first, second in zip(times, times[1:]):
                total += 1
                if second - first > basis:
                    overshoot += 1
        episodes = sum(
            1 for name in members
            for began, _, _ in runs[name].silences if began < window
        )
        out[fleet] = dict(
            devices=len(members),
            episodes=episodes,
            episode_rate=round(episodes / max(len(members), 1), 3),
            gaps=total,
            overshoot_rate=round(overshoot / max(total, 1), 3),
        )
    return out
