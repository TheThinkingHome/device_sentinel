"""Reporting an upstream outage as one fault, not seventy-six.

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_upstream_reporting.py, Version: 0.13.10 (2026-08-13)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

Found by running it. Stopping Zigbee2MQTT on the reference system
raised 74 problems and pushed a notification naming 74 devices
without naming the bridge; stopping the broker raised 76 and did the
same. Every verdict was true and the record stayed clean, so this is
a reporting fault: the person is told the casualties and never the
cause, and the cause is the only thing they can act on.
"""

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    BROKER_LABEL,
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    UPSTREAM_SETTLE_SECONDS,
)

from .helpers import register_device, setup_coordinator


def _down(coord, device_id, category="unavailable", since=1000.0):
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_FROZEN_CATEGORY] = category
    record[DEV_FROZEN_SINCE] = since


async def test_devices_are_not_reported_while_their_broker_is_down(
    hass: HomeAssistant,
):
    """The fault is the broker. The devices are symptoms, and listing
    them buries the one sentence worth reading."""
    first, _ = register_device(hass, "up1", "First Device")
    second, _ = register_device(hass, "up2", "Second Device")
    coord = await setup_coordinator(hass)
    _down(coord, first.id, since=2000.0)
    _down(coord, second.id, since=2000.0)
    coord._broker_down_at = 1500.0

    assert coord.reportable_down_rows == []
    assert coord.suppressed_down_counts == {BROKER_LABEL: 2}
    # The verdicts themselves are untouched: the count sensor still
    # reads what is true.
    assert coord.frozen_devices_count == 2


async def test_a_device_broken_before_the_outage_keeps_its_row(
    hass: HomeAssistant,
):
    """A sensor with a dead battery yesterday is genuinely broken. It
    must not vanish into the outage and reappear when the outage
    clears, which is the same noise in the other direction."""
    old, _ = register_device(hass, "up3", "Already Broken")
    new, _ = register_device(hass, "up4", "Casualty")
    coord = await setup_coordinator(hass)
    _down(coord, old.id, since=1000.0)
    _down(coord, new.id, since=2000.0)
    coord._broker_down_at = 1500.0

    names = [row["name"] for row in coord.reportable_down_rows]

    assert names == ["Already Broken"]
    assert coord.suppressed_down_counts == {BROKER_LABEL: 1}


async def test_everything_is_reported_when_the_upstream_is_up(
    hass: HomeAssistant,
):
    """The suppression is conditional, not a new default: with the
    broker and every bridge up, a down device is its own fault and
    reads as one."""
    device, _ = register_device(hass, "up5", "Ordinary Casualty")
    coord = await setup_coordinator(hass)
    _down(coord, device.id)

    assert [row["name"] for row in coord.reportable_down_rows] == [
        "Ordinary Casualty"
    ]
    assert coord.suppressed_down_counts == {}


async def test_a_device_still_down_after_recovery_is_reported(
    hass: HomeAssistant,
):
    """The most useful row of the week: everything else came back and
    this one did not."""
    device, _ = register_device(hass, "up6", "Did Not Return")
    coord = await setup_coordinator(hass)
    _down(coord, device.id, since=2000.0)
    coord._broker_down_at = 1500.0
    assert coord.reportable_down_rows == []

    coord._broker_down_at = None

    assert [row["name"] for row in coord.reportable_down_rows] == [
        "Did Not Return"
    ]


async def test_an_outage_settles_before_it_is_announced(
    hass: HomeAssistant,
):
    """Ruling #265. The devices arrive over tens of seconds, so a
    count taken at the first one is wrong and a message per tick is
    the burst this fixes."""
    device, _ = register_device(hass, "up7", "Settling Device")
    coord = await setup_coordinator(hass)
    _down(coord, device.id, since=2000.0)
    from homeassistant.util import dt as dt_util

    coord._broker_down_at = dt_util.utcnow().timestamp()

    assert coord._upstream_messages() == []


async def test_the_count_is_pushed_again_only_when_it_changes(
    hass: HomeAssistant,
):
    """Silent after the first, and only when there is something new to
    say: the same tally twice is not worth a message even a quiet
    one."""
    device, _ = register_device(hass, "up8", "Counted Device")
    coord = await setup_coordinator(hass)
    from homeassistant.util import dt as dt_util

    # The outage began just over a settle ago, and the device fell
    # after it: the ordering is what decides whether a device is a
    # casualty or was broken already.
    down_at = dt_util.utcnow().timestamp() - UPSTREAM_SETTLE_SECONDS - 1
    coord._broker_down_at = down_at
    _down(coord, device.id, since=down_at + 1)

    first = coord._upstream_messages()
    assert first == [(BROKER_LABEL, 1, False)]

    coord._upstream_announced[BROKER_LABEL] = 1
    assert coord._upstream_messages() == []


async def test_the_recovery_is_announced_once(hass: HomeAssistant):
    """One message when the upstream returns, carrying how many had
    gone quiet, and nothing after it."""
    coord = await setup_coordinator(hass)
    coord._upstream_announced[BROKER_LABEL] = 12
    coord._broker_down_at = None

    assert coord._upstream_messages() == [(BROKER_LABEL, 12, True)]
