# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: psquare.py, Version: 0.12.19 (2026-08-12)

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
