# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_earlier_stops_not_silence.py, Version: 0.28.12 (2026-11-11)

"""An earlier stop counts against no device either (rule FRZ-10).

FRZ-10: "The time it was stopped counts against no device." The verdict
path (_silence_spans) takes out only the stop just before this start
(_last_alive, _downtime). A stop before that, already stored as a restart
row and already taken out of learned gaps by _stop_spans (rule FRZ-12),
is counted as the device's silence.

Real house: Home Assistant is shut down cleanly for three hours (a host
move, a backup, a UPS-ordered shutdown), started, and restarted again
twenty minutes later (an update, a config fix). An hourly sensor that
reported ten minutes before the first stop has not reported in the twenty
minutes between. At the second start its counted silence includes the
three hours nobody was listening, so it is listed frozen and pushed when
the grace closes, and told recovered at its next report.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    LEARNING_MIN_DAYS,
    SYS_DURATION,
    SYS_KIND,
    SYS_RESTART,
    SYS_WHEN,
)

from .helpers import register_device, setup_coordinator


async def test_an_earlier_clean_stop_is_not_counted_as_silence(hass: HomeAssistant):
    device, (entity_id,) = register_device(hass, "hourly", name="Hourly Sensor")
    hass.states.async_set(entity_id, "21.5")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_EVENT_COUNT] = 5000
    record[DEV_DAILY_MAX] = [3600.0] * (LEARNING_MIN_DAYS + 5)
    window = coord._freeze_window(record)
    assert window is not None

    now = dt_util.utcnow().timestamp()
    second_down = 60.0
    between = 20 * 60.0  # the first run lasted twenty minutes
    first_down = 3 * window  # the first stop, clean, far longer than the window
    first_start = now - second_down - between
    # The first start's restart row, as it is stored.
    coord.data.setdefault(DATA_SYSTEM_EVENTS, []).append(
        {SYS_KIND: SYS_RESTART, SYS_WHEN: first_start, SYS_DURATION: first_down}
    )
    # This start: the stop just before it was a minute.
    coord._last_alive = now - second_down
    coord._downtime = second_down
    # The sensor last reported ten minutes before the first stop.
    record[DEV_LAST_ACTIVITY] = first_start - first_down - 600.0

    watched = 600.0 + between  # all the silence anybody was listening to
    assert watched < window
    silence = coord._observed_silence(record, now, device.id, window)
    assert silence is not None and silence < window, (
        f"counted {silence:.0f} s of silence where {watched:.0f} s were watched"
    )
    coord._judge_all_devices()
    assert record[DEV_FROZEN_CATEGORY] is None, "listed frozen on time nobody was listening"
