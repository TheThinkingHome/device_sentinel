# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_brief_stitching.py, Version: 0.16.9 (2026-08-20)

"""A silence the restarts segmented is told as one silence.

The reference case, from the live fleet on 20 August: an SLZB-06
unplugged on the 18th was told as eighteen recoveries across seven
restarts, "silent for 16.2h in total" against a true span of 2.5
days, because each restart closed the open episode as intervention
(reboot) (ruling #163) and the incident surface worded that
administrative closure as "recovered". The device's protocol clock
stood at the moment of the unplug the whole time, which is both the
proof of the fault and the discriminator the fix reads (ruling #308).

Presence Guest is the contrast case every test here protects: its
morning flaps were real reconnects, its clock moved, and its
flapping sentence must survive unchanged.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_INCIDENTS,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
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
    TODO_KIND_FROZEN,
    TODO_KIND_UNAVAILABLE,
)

from tests.helpers import register_device, setup_coordinator


def _pairs(coord, device_id, name, count, kind=TODO_KIND_FROZEN,
           cause="reboot", spacing=3600.0, last_open=True):
    """Return (opened, resolved) pairs spaced across the window.

    Each pair is one interruption: opened, then resolved with the
    given cause. When last_open is True the final opening stands
    unresolved, which is the live shape of a device still down.
    """
    now = dt_util.utcnow().timestamp()
    start = now - count * spacing - 60.0
    pairs = []
    for step in range(count):
        at = start + step * spacing
        opened = {
            INC_DEVICE_ID: device_id, INC_NAME: name,
            INC_KIND: kind, INC_EVENT: INCIDENT_OPENED,
            INC_WHEN: at, INC_CAUSE: None, INC_DURATION: None,
        }
        unresolved = last_open and step == count - 1
        resolved = None if unresolved else {
            INC_DEVICE_ID: device_id, INC_NAME: name,
            INC_KIND: kind, INC_EVENT: INCIDENT_RESOLVED,
            INC_WHEN: at + spacing * 0.9, INC_CAUSE: cause,
            INC_DURATION: spacing * 0.9,
        }
        pairs.append((opened, resolved))
    return pairs


def _record(coord, device_id, last_activity, frozen_since=None):
    record = coord.data["devices"][device_id]
    record[DEV_LAST_ACTIVITY] = last_activity
    if frozen_since is not None:
        record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_UNAVAILABLE
        record[DEV_FROZEN_SINCE] = frozen_since
    return record


async def test_an_unbroken_silence_is_stitched_into_one_sentence(
    hass: HomeAssistant,
):
    """Seven fake recoveries become one sentence with the true span."""
    device, _ = register_device(hass, "sl1", "SLZB-06")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    unplugged = now - 2.5 * 86400.0
    _record(coord, device.id, unplugged, frozen_since=unplugged + 60.0)
    pairs = _pairs(coord, device.id, "SLZB-06", 7)

    told = coord._tell_episodes(pairs, [])
    assert len(told) == 1
    line = told[0]
    assert line.startswith("SLZB-06 has been silent since ")
    # Seven interruptions, the last still standing: six were closed
    # by a restart, and the open seventh is the silence itself.
    assert "across 6 restarts" in line
    assert "recovered" not in line
    assert "went silent" not in line
    # The span is the verdict's, not the fragments': 2.5 days.
    assert "2.5d so far" in line


async def test_a_real_flapper_keeps_its_flapping_sentence(
    hass: HomeAssistant,
):
    """A clock that moved means the recoveries were real."""
    device, _ = register_device(hass, "pg1", "Presence Guest")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    # Last activity after every interruption: it really came back.
    _record(coord, device.id, now - 30.0)
    pairs = _pairs(
        coord, device.id, "Presence Guest", 3, cause=None,
        last_open=False,
    )

    told = coord._tell_episodes(pairs, [])
    assert len(told) == 1
    assert told[0].startswith("Presence Guest went silent 3 times")
    assert "has been silent since" not in told[0]


async def test_one_dead_and_one_live_device_get_their_own_sentences(
    hass: HomeAssistant,
):
    """The discriminator is per device, not per brief."""
    dead, _ = register_device(hass, "sl2", "SLZB-06")
    live, _ = register_device(hass, "pg2", "Presence Guest")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    _record(coord, dead.id, now - 2.0 * 86400.0)
    _record(coord, live.id, now - 30.0)
    pairs = (
        _pairs(coord, dead.id, "SLZB-06", 4)
        + _pairs(coord, live.id, "Presence Guest", 2,
                 cause=None, last_open=False)
    )

    told = coord._tell_episodes(pairs, [])
    stitched = [t for t in told if "has been silent since" in t]
    flapped = [t for t in told if "went silent" in t]
    assert len(stitched) == 1 and stitched[0].startswith("SLZB-06")
    assert len(flapped) == 1 and flapped[0].startswith("Presence Guest")


async def test_a_single_fake_recovery_is_stitched_too(
    hass: HomeAssistant,
):
    """One restart in the window is one lie fewer, not a threshold."""
    device, _ = register_device(hass, "sl3", "SLZB-06")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    _record(coord, device.id, now - 86400.0)
    pairs = _pairs(coord, device.id, "SLZB-06", 1, last_open=False)

    told = coord._tell_episodes(pairs, [])
    assert len(told) == 1
    assert told[0].startswith("SLZB-06 has been silent since ")
    assert "across 1 restart." in told[0]
    assert "recovered" not in told[0]


async def test_the_table_drops_the_bookkeeping_rows(
    hass: HomeAssistant,
):
    """The stitched sentence is not contradicted two sections down.

    The rows behind it say a dead device recovered eighteen times;
    keeping them beside the sentence that corrects them would say
    the wrong thing more often than the right one. The counts count
    what the table shows (ruling #308).
    """
    device, _ = register_device(hass, "sl4", "SLZB-06")
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    start = coord._brief_window_start(now)
    _record(coord, device.id, start - 86400.0,
            frozen_since=start - 86400.0 + 60.0)

    rows = []
    for step in range(3):
        at = start + 100.0 + step * 600.0
        rows.append({
            INC_DEVICE_ID: device.id, INC_NAME: "SLZB-06",
            INC_KIND: TODO_KIND_UNAVAILABLE,
            INC_EVENT: INCIDENT_OPENED,
            INC_WHEN: at, INC_CAUSE: None, INC_DURATION: None,
        })
        rows.append({
            INC_DEVICE_ID: device.id, INC_NAME: "SLZB-06",
            INC_KIND: TODO_KIND_UNAVAILABLE,
            INC_EVENT: INCIDENT_RESOLVED,
            INC_WHEN: at + 300.0, INC_CAUSE: "reboot",
            INC_DURATION: 300.0,
        })
    coord.data[DATA_INCIDENTS] = rows

    await hass.async_add_executor_job(coord._write_reports, "manual")
    text = coord._last_brief_text
    assert text is not None
    assert "SLZB-06 has been silent since" in text
    assert "recovered after" not in text
    assert "| SLZB-06 | went unavailable |" not in text
    assert "0 problems started, 0 ended." in text
