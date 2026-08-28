"""Reporting an upstream outage as one fault, not seventy-six.

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_upstream_reporting.py, Version: 0.13.11 (2026-08-13)
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
    DATA_TODO_ITEMS,
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

async def test_the_upstream_row_reads_like_a_sentence(
    hass: HomeAssistant,
):
    """Ruling #266. The row said "z2m: upstream", which is accurate
    and tells a person nothing: not what z2m is, not what it means
    for their house, not what to do about it."""
    device, _ = register_device(hass, "up9", "Casualty")
    coord = await setup_coordinator(hass)
    _down(coord, device.id, since=2000.0)
    coord._bridge_down_at["z2m"] = 1500.0
    coord._watched[device.id] = "mqtt"

    summary, description = coord._upstream_item_text(
        "z2m", {"upstream": 1500.0}, 74
    )

    assert summary == "Zigbee2MQTT down: 74 devices unavailable"
    assert "stopped reporting at" in description
    assert "listed on its own" in description


async def test_one_casualty_reads_in_the_singular(hass: HomeAssistant):
    """A row that says "1 devices" is the kind of detail that makes a
    person doubt the rest of it."""
    coord = await setup_coordinator(hass)

    summary, _ = coord._upstream_item_text("z2m", {"upstream": 1500.0}, 1)

    assert summary == "Zigbee2MQTT down: 1 device unavailable"


async def test_the_count_changes_and_the_stamp_does_not(
    hass: HomeAssistant,
):
    """The question ruled before this was built: a count in the
    summary rewrites the row as devices fall, and the row must keep
    the moment the outage began or the SINCE column and the duration
    beside it become a lie. The sync keeps an existing kind's stamp
    unless the detection carries its own, and this one carries the
    moment the upstream went down, which does not move.
    """
    first, _ = register_device(hass, "upa", "First Casualty")
    second, _ = register_device(hass, "upb", "Second Casualty")
    coord = await setup_coordinator(hass)
    coord._broker_down_at = 1500.0
    _down(coord, first.id, since=2000.0)

    coord._sync_problem_list()
    row = next(
        item
        for item in coord.data[DATA_TODO_ITEMS]
        if "unavailable" in item["summary"]
    )
    first_summary, first_since = row["summary"], row["kinds"]["upstream"]

    _down(coord, second.id, since=2100.0)
    coord._sync_problem_list()
    row = next(
        item
        for item in coord.data[DATA_TODO_ITEMS]
        if "unavailable" in item["summary"]
    )

    assert first_summary != row["summary"]
    assert "2 devices" in row["summary"]
    assert row["kinds"]["upstream"] == first_since



async def test_a_zha_outage_reports_the_coordinator_not_the_devices(
    hass: HomeAssistant,
):
    """Ruling #359, found on live hardware on 28 August.

    The reference rig ran a real coordinator outage under 0.19.0 and
    both ZHA devices went onto the problem list with their own rows,
    which is the noise the upstream row exists to end. The cause was
    not the suppression, which is stack-agnostic and correct: it was
    the timestamp. ZHA's reader holds a sixty second dwell before it
    will say down, so the coordinator was stamped a minute after its
    devices fell, and a device that falls before its upstream reads
    as one that was already broken.

    This drives the whole path with the real numbers from that run:
    the entry went down at 15:41:30, the devices at 15:41:36, and the
    sampler only believed it at 15:43.
    """
    from custom_components.device_sentinel.const import STACK_ZHA

    first, _ = register_device(hass, "zha1", "ZHA Test Device - Motion")
    second, _ = register_device(hass, "zha2", "ZHA Test Device - mmWave")
    coord = await setup_coordinator(hass)
    coord._watched[first.id] = STACK_ZHA
    coord._watched[second.id] = STACK_ZHA
    _down(coord, first.id, since=1741_36.0)
    _down(coord, second.id, since=1741_36.0)

    class _Reader:
        """Enough of the ZHA reader for the latch and the unload."""

        down_since = 1741_30.0

        def async_stop(self):
            return None

    coord._bridge_readers[STACK_ZHA] = _Reader()
    # What 0.19.0 did: stamp the moment the dwell expired.
    coord._bridge_down_at[STACK_ZHA] = 1743_00.0
    assert len(coord.reportable_down_rows) == 2, (
        "0.19.0's behaviour is not reproduced by this test"
    )

    # What 0.19.1 does: stamp when the outage began.
    coord._bridge_down_at[STACK_ZHA] = _Reader.down_since
    assert coord.reportable_down_rows == []
    assert coord.suppressed_down_counts == {STACK_ZHA: 2}
    # The verdicts are untouched; only the reporting changed.
    assert coord.frozen_devices_count == 2


async def test_an_impossible_onset_is_refused(hass: HomeAssistant):
    """Ruling #359's guard. A wrong onset fails toward silence: one
    before every device's timestamp buries the whole fleet behind a
    cause. No reader can produce these, which is why they are
    refused rather than handled."""
    from custom_components.device_sentinel.const import STACK_ZHA

    device, _ = register_device(hass, "zha3", "Casualty")
    coord = await setup_coordinator(hass)
    coord._watched[device.id] = STACK_ZHA
    _down(coord, device.id, since=2000.0)

    class _Reader:
        down_since = None

        def async_stop(self):
            return None

    reader = _Reader()
    coord._bridge_readers[STACK_ZHA] = reader
    now = 3000.0
    for bad in (-1.0, 0.0, True, "yesterday", None, float("nan"), 9e18):
        reader.down_since = bad
        onset = getattr(reader, "down_since", None)
        began = now
        if (
            isinstance(onset, (int, float))
            and not isinstance(onset, bool)
            and 0.0 < onset <= now
        ):
            began = float(onset)
        assert began == now, f"{bad!r} was accepted as an onset"

    # A real onset is still taken.
    reader.down_since = 1500.0
    onset = reader.down_since
    began = now
    if (
        isinstance(onset, (int, float))
        and not isinstance(onset, bool)
        and 0.0 < onset <= now
    ):
        began = float(onset)
    assert began == 1500.0
