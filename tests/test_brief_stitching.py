# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_brief_stitching.py, Version: 0.16.10 (2026-08-21)

"""A silence the restarts segmented is told as one silence.

The reference case, from the live fleet: an SLZB-06 unplugged on 18
August was told as twenty-one recoveries in a single morning brief,
"silent for 19.9h in total" against a true span of three days,
because each restart closed the open episode as an intervention
(ruling #163) and the incident surface worded that administrative
closure as "recovered". Ruling #308 stitches those fragments back
into one sentence.

The fixtures here are built to the shape the real storage file
carries, and that shape is the point. The first attempt at this rule
read a cause field on the resolution rows and shipped inert: of 462
real incident rows only ten carry any cause at all, and none of
SLZB-06's twenty-one recoveries carried one. The witness that does
survive the fragments is the standing verdict, which clears when a
device truly recovers and never cleared once here.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_INCIDENTS,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    FREEZE_CATEGORY_UNAVAILABLE,
    INCIDENT_OPENED,
    INCIDENT_RESOLVED,
    INC_CAUSE,
    INC_DEVICE_ID,
    INC_DURATION,
    INC_EVENT,
    INC_KIND,
    INC_NAME,
    INC_WHEN,
    SYS_KIND,
    SYS_RESTART,
    SYS_WHEN,
    TODO_KIND_UNAVAILABLE,
)

from tests.helpers import register_device, setup_coordinator


def _pairs(
    device_id: str,
    name: str,
    count: int,
    spacing: float = 3600.0,
    last_open: bool = True,
) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Return interruption pairs spaced back from now.

    Every resolution carries no cause, which is what the live
    journal writes: of the fleet's 462 rows, 452 have none. A
    fixture that supplied one would prove nothing about the house.
    """
    now = dt_util.utcnow().timestamp()
    start = now - count * spacing - 60.0
    built = []
    for step in range(count):
        at = start + step * spacing
        opened = {
            INC_DEVICE_ID: device_id, INC_NAME: name,
            INC_KIND: TODO_KIND_UNAVAILABLE, INC_EVENT: INCIDENT_OPENED,
            INC_WHEN: at, INC_CAUSE: None, INC_DURATION: None,
        }
        standing = last_open and step == count - 1
        resolved = None if standing else {
            INC_DEVICE_ID: device_id, INC_NAME: name,
            INC_KIND: TODO_KIND_UNAVAILABLE, INC_EVENT: INCIDENT_RESOLVED,
            INC_WHEN: at + spacing * 0.9, INC_CAUSE: None,
            INC_DURATION: spacing * 0.9,
        }
        built.append((opened, resolved))
    return built


def _restarts(count: int, spacing: float = 3600.0) -> list[dict[str, Any]]:
    """Return recorded restarts, the only source of the count."""
    now = dt_util.utcnow().timestamp()
    return [
        {SYS_KIND: SYS_RESTART, SYS_WHEN: now - (step + 1) * spacing}
        for step in range(count)
    ]


def _standing(coord, device_id: str, since: float) -> None:
    """Give the device a verdict that has stood since the moment."""
    record = coord.data["devices"][device_id]
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_UNAVAILABLE
    record[DEV_FROZEN_SINCE] = since


def _cleared(coord, device_id: str) -> None:
    """Give the device no standing verdict: it really came back."""
    record = coord.data["devices"][device_id]
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None


async def test_an_unbroken_silence_is_stitched_into_one_sentence(
    hass: HomeAssistant,
):
    """The live case: many claimed recoveries, one unbroken outage."""
    device, _ = register_device(hass, "sl1", "SLZB-06")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    _standing(coord, device.id, now - 3.0 * 86400.0)

    told = coord._tell_episodes(_pairs(device.id, "SLZB-06", 7), _restarts(7))

    assert len(told) == 1
    line = told[0]
    assert line.startswith("SLZB-06 has been silent since ")
    assert "3.0d so far" in line
    assert "across 7 restarts" in line
    assert "recovered" not in line
    assert "went silent" not in line


async def test_a_device_that_really_came_back_keeps_its_flapping_sentence(
    hass: HomeAssistant,
):
    """A cleared verdict is the proof the recoveries were real."""
    device, _ = register_device(hass, "pg1", "Presence Guest")
    coord = await setup_coordinator(hass)
    _cleared(coord, device.id)

    told = coord._tell_episodes(
        _pairs(device.id, "Presence Guest", 3, last_open=False), _restarts(3)
    )

    assert len(told) == 1
    assert "Presence Guest went unavailable 3 times" in told[0]
    assert "has been silent since" not in told[0]


async def test_a_verdict_younger_than_its_fragments_is_not_stitched(
    hass: HomeAssistant,
):
    """The case the third condition exists for.

    A device that recovered, failed again, and is still down holds a
    verdict that began after the window's earliest opening. Those
    recoveries were real and the sentence must stay a flapping one.
    """
    device, _ = register_device(hass, "fl1", "Flapper")
    coord = await setup_coordinator(hass)
    pairs = _pairs(device.id, "Flapper", 4)
    _standing(coord, device.id, pairs[-1][0][INC_WHEN])

    told = coord._tell_episodes(pairs, _restarts(4))

    assert len(told) == 1
    assert "Flapper went unavailable 4 times" in told[0]
    assert "has been silent since" not in told[0]


async def test_a_device_with_no_standing_verdict_is_not_stitched(
    hass: HomeAssistant,
):
    """No verdict means no witness, so nothing is claimed."""
    device, _ = register_device(hass, "nv1", "No Verdict")
    coord = await setup_coordinator(hass)
    _cleared(coord, device.id)

    told = coord._tell_episodes(
        _pairs(device.id, "No Verdict", 2, last_open=False), _restarts(2)
    )

    assert "has been silent since" not in told[0]


async def test_an_open_problem_with_no_recovery_claimed_is_untouched(
    hass: HomeAssistant,
):
    """Nothing to correct, so the ordinary sentence stands.

    This is the shape that refused the first version of this rule: a
    single open problem, no resolution anywhere, which must keep
    reading as a device that stopped reporting.
    """
    device, _ = register_device(hass, "op1", "Open Only")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    _standing(coord, device.id, now - 7200.0)
    opened = {
        INC_DEVICE_ID: device.id, INC_NAME: "Open Only",
        INC_KIND: TODO_KIND_UNAVAILABLE, INC_EVENT: INCIDENT_OPENED,
        INC_WHEN: now - 3600.0, INC_CAUSE: None, INC_DURATION: None,
    }

    told = coord._tell_episodes([(opened, None)], _restarts(1))

    assert "has been silent since" not in told[0]


async def test_the_restart_count_comes_from_recorded_restarts(
    hass: HomeAssistant,
):
    """Not from the resolution rows, which carry no cause at all."""
    device, _ = register_device(hass, "rc1", "SLZB-06")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    _standing(coord, device.id, now - 2.0 * 86400.0)

    told = coord._tell_episodes(
        _pairs(device.id, "SLZB-06", 9, spacing=1800.0), _restarts(2)
    )

    assert "across 2 restarts." in told[0]


async def test_a_restart_before_the_outage_is_not_counted(
    hass: HomeAssistant,
):
    """The count is bounded by the verdict's own start."""
    device, _ = register_device(hass, "rb1", "SLZB-06")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    _standing(coord, device.id, now - 7200.0)
    events = _restarts(2, spacing=1800.0) + [
        {SYS_KIND: SYS_RESTART, SYS_WHEN: now - 5.0 * 86400.0}
    ]

    told = coord._tell_episodes(
        _pairs(device.id, "SLZB-06", 3, spacing=1800.0), events
    )

    assert "across 2 restarts." in told[0]


async def test_the_table_drops_the_bookkeeping_rows(
    hass: HomeAssistant, freezer
):
    """The stitched sentence is not contradicted two sections down.

    The rows behind it say a dead device recovered many times;
    keeping them beside the sentence that corrects them would say
    the wrong thing more often than the right one. The counts count
    what the table shows (ruling #308).

    The clock is pinned (ruling #330). This test plants its rows at
    fixed offsets after the window start, so run inside the first
    half hour after the brief hour it planted them in the future and
    failed on the wall clock alone. Found by the 0.17.3 gate at
    08:06 local, having passed every earlier run that day.
    """
    freezer.move_to("2026-08-24T20:00:00+00:00")
    device, _ = register_device(hass, "tb1", "SLZB-06")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    start = coord._brief_window_start(now)
    _standing(coord, device.id, start - 86400.0)

    rows = []
    for step in range(3):
        at = start + 100.0 + step * 600.0
        rows.append({
            INC_DEVICE_ID: device.id, INC_NAME: "SLZB-06",
            INC_KIND: TODO_KIND_UNAVAILABLE, INC_EVENT: INCIDENT_OPENED,
            INC_WHEN: at, INC_CAUSE: None, INC_DURATION: None,
        })
        rows.append({
            INC_DEVICE_ID: device.id, INC_NAME: "SLZB-06",
            INC_KIND: TODO_KIND_UNAVAILABLE, INC_EVENT: INCIDENT_RESOLVED,
            INC_WHEN: at + 300.0, INC_CAUSE: None, INC_DURATION: 300.0,
        })
    coord.data[DATA_INCIDENTS] = rows

    await hass.async_add_executor_job(coord._write_reports, "manual")
    text = coord._last_brief_text

    assert text is not None
    assert "SLZB-06 has been silent since" in text
    assert "recovered after" not in text
    assert "| SLZB-06 | went unavailable |" not in text
    assert "0 problems started, 0 ended." in text
    assert now
