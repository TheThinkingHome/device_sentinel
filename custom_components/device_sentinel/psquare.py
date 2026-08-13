# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: psquare.py, Version: 0.13.8 (2026-08-13)

"""Streaming percentiles in constant memory: the P-Square estimator.

Jain and Chlamtac, 1985. One estimator tracks one quantile of an
unbounded stream while holding exactly five markers, whatever the
stream's length. Each marker has a height (an estimated value on the
distribution) and a position (how many observations sit at or below
it); when a marker drifts from its ideal position, its height is
nudged along a parabola fitted through its neighbours, falling back
to linear interpolation when the parabola would break the ordering.

Why it is here (ruling #253): the daily minimum is a one-packet
statistic, and the fleet measured 47 percent of device-days carrying
a minimum more than three deviations below that day's own mean, a
reading the day itself disowns. A time-weighted percentile replaces
belief with duration: a value only registers as the day's sustained
low after the device has held it for its share of the day, about 72
cumulative minutes for the 5th percentile. The estimators feed the
two recorded series (daily P5 and P50) and judge nothing.

The state is a plain list so it can live inside a device record and
ride the clocks file untouched: [count, h1..h5, p1..p5]. Positions
are stored as floats for JSON simplicity; they hold integer values.
"""

from __future__ import annotations

STATE_LEN = 11  # count, five heights, five positions


def psquare_new() -> list[float]:
    """Return an empty estimator state."""
    return [0.0] + [0.0] * 5 + [0.0] * 5


def psquare_feed(state: list[float], quantile: float, value: float) -> None:
    """Feed one observation into the estimator, in place.

    The first five observations bootstrap the markers; from the
    sixth onward the marker machinery runs. Constant time, constant
    memory, no allocation beyond the bootstrap sort.
    """
    n = int(state[0])
    if n < 5:
        # Bootstrap: park the observation, sort the heights so far.
        state[1 + n] = value
        n += 1
        state[0] = float(n)
        heights = sorted(state[1 : 1 + n])
        state[1 : 1 + n] = heights
        # Positions are simply 1..n while bootstrapping.
        for i in range(5):
            state[6 + i] = float(min(i + 1, n))
        return

    h = state[1:6]
    pos = [int(p) for p in state[6:11]]

    # 1. Locate the cell, stretching the end markers as needed.
    if value < h[0]:
        h[0] = value
        k = 0
    elif value >= h[4]:
        h[4] = value
        k = 3
    else:
        k = 0
        for i in range(1, 5):
            if value < h[i]:
                k = i - 1
                break

    # 2. Actual positions above the cell shift up by one.
    for i in range(k + 1, 5):
        pos[i] += 1
    n += 1
    state[0] = float(n)

    # 3. Ideal positions for min, q/2, q, (1+q)/2, max.
    q = quantile
    ideal = [
        1.0,
        1.0 + (n - 1) * q / 2.0,
        1.0 + (n - 1) * q,
        1.0 + (n - 1) * (1.0 + q) / 2.0,
        float(n),
    ]

    # 4. Nudge the three interior markers toward their ideals.
    for i in range(1, 4):
        d = ideal[i] - pos[i]
        if (d >= 1.0 and pos[i + 1] - pos[i] > 1) or (
            d <= -1.0 and pos[i - 1] - pos[i] < -1
        ):
            step = 1 if d > 0 else -1
            # The piecewise-parabolic prediction.
            hp = h[i] + step / (pos[i + 1] - pos[i - 1]) * (
                (pos[i] - pos[i - 1] + step)
                * (h[i + 1] - h[i])
                / (pos[i + 1] - pos[i])
                + (pos[i + 1] - pos[i] - step)
                * (h[i] - h[i - 1])
                / (pos[i] - pos[i - 1])
            )
            if h[i - 1] < hp < h[i + 1]:
                h[i] = hp
            else:
                # Linear fallback when the parabola breaks ordering.
                h[i] = h[i] + step * (h[i + step] - h[i]) / (
                    pos[i + step] - pos[i]
                )
            pos[i] += step

    state[1:6] = h
    state[6:11] = [float(p) for p in pos]


def psquare_read(state: list[float], quantile: float) -> float | None:
    """Return the current quantile estimate, or None with no data.

    Under five observations the estimate is read from the sorted
    bootstrap directly (nearest-rank), so a sparse day still reports
    an honest value rather than nothing.
    """
    n = int(state[0])
    if n == 0:
        return None
    if n < 5:
        heights = sorted(state[1 : 1 + n])
        rank = min(n - 1, max(0, int(quantile * n)))
        return heights[rank]
    return state[3]

def psquare_feed_many(
    state: list[float], quantile: float, value: float, times: int
) -> None:
    """Feed one value repeatedly, without paying per observation.

    Time weighting feeds a held value once per minute it lasted
    (ruling #253), so a device that reports twice a day hands the
    estimator hundreds of identical observations in one call, and a
    restart after an outage can hand it a full day's worth. The loop
    that did this ran on the event loop at exactly the moment Home
    Assistant is busiest.

    The marker machinery has no closed form for a repeat, because
    each observation moves the ideal positions and the markers chase
    them one step at a time, so this still iterates. What it avoids
    is the per-observation cost of psquare_feed: the state slicing,
    the list rebuilding, and the write-back, which is the greater
    part of the work. Identical results, not an approximation: the
    same steps in the same order over hoisted locals.
    """
    if times <= 0:
        return
    n = int(state[0])
    # The bootstrap is rare and short, so it stays on the simple path.
    while n < 5 and times > 0:
        psquare_feed(state, quantile, value)
        n = int(state[0])
        times -= 1
    if times <= 0:
        return

    h0, h1, h2, h3, h4 = state[1:6]
    p0, p1, p2, p3, p4 = (int(p) for p in state[6:11])
    q = quantile

    for _ in range(times):
        if value < h0:
            h0 = value
            k = 0
        elif value >= h4:
            h4 = value
            k = 3
        elif value < h1:
            k = 0
        elif value < h2:
            k = 1
        elif value < h3:
            k = 2
        else:
            k = 3

        if k < 1:
            p1 += 1
        if k < 2:
            p2 += 1
        if k < 3:
            p3 += 1
        p4 += 1
        n += 1

        span = n - 1
        ideals = (
            1.0 + span * q / 2.0,
            1.0 + span * q,
            1.0 + span * (1.0 + q) / 2.0,
        )
        heights = [h0, h1, h2, h3, h4]
        positions = [p0, p1, p2, p3, p4]
        for i in range(1, 4):
            d = ideals[i - 1] - positions[i]
            if (d >= 1.0 and positions[i + 1] - positions[i] > 1) or (
                d <= -1.0 and positions[i - 1] - positions[i] < -1
            ):
                step = 1 if d > 0 else -1
                predicted = heights[i] + step / (
                    positions[i + 1] - positions[i - 1]
                ) * (
                    (positions[i] - positions[i - 1] + step)
                    * (heights[i + 1] - heights[i])
                    / (positions[i + 1] - positions[i])
                    + (positions[i + 1] - positions[i] - step)
                    * (heights[i] - heights[i - 1])
                    / (positions[i] - positions[i - 1])
                )
                if heights[i - 1] < predicted < heights[i + 1]:
                    heights[i] = predicted
                else:
                    heights[i] = heights[i] + step * (
                        heights[i + step] - heights[i]
                    ) / (positions[i + step] - positions[i])
                positions[i] += step
        h0, h1, h2, h3, h4 = heights
        p0, p1, p2, p3, p4 = positions

    state[0] = float(n)
    state[1:6] = [h0, h1, h2, h3, h4]
    state[6:11] = [float(p0), float(p1), float(p2), float(p3), float(p4)]

