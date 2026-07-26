# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_learning_rhythm.py, Version: 0.9.9 (2026-07-26)

"""How the integration learns each device's reporting rhythm.

The window a device is judged against is learned from its own gaps: a
trimmed maximum over a rolling fortnight, with a synchronized-poller
fleet exempted from the storm brake so it can still learn, and an
outage past the debounce floor set aside as a taint rather than
inflating the rhythm. This file holds the rhythm engine's behaviour:
the storm exemption, the trimmed maximum and how it renders, the taint
debounce, the daily epoch rollover, and the signal recording that
rides alongside the same clock.
"""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_STATS_EPOCH,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_VALUE,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    STARTUP_GRACE_SECONDS,
    STATS_EPOCH,
    STORAGE_KEY,
    STORM_DEVICE_THRESHOLD,
    STORM_EXEMPT_PER_HOUR,
    DEFAULT_TAINT_FLOOR_MINUTES,
)

from tests.helpers import register_fleet, setup_coordinator, setup_entry


# --------------------------------------------------- storm exemption

async def test_synchronized_poller_exempted(
    hass: HomeAssistant, freezer, caplog
):
    """A chronically storming entry is exempted; its devices then learn."""
    source = MockConfigEntry(domain="poller")
    source.add_to_hass(hass)
    fleet = register_fleet(hass, source, STORM_DEVICE_THRESHOLD + 2)

    coord = await setup_coordinator(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    # Poll cycles: the whole fleet writes in the same instant, every 30 s.
    value = 0
    for _cycle in range(STORM_EXEMPT_PER_HOUR + 1):
        value += 1
        for _dev, eid in fleet:
            hass.states.async_set(eid, str(value))
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=30))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    assert source.entry_id in coord._storm_exempt
    assert "reclassified as synchronized polling" in caplog.text

    # Post-exemption cycles complete learnable gaps at the poll cadence.
    for _cycle in range(2):
        value += 1
        for _dev, eid in fleet:
            hass.states.async_set(eid, str(value))
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=30))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    learned = [
        coord.data[DATA_DEVICES][dev.id][DEV_TODAY_MAX] for dev, _ in fleet
    ]
    assert all(v is not None and v == pytest.approx(30, abs=2) for v in learned)


async def test_rare_storm_still_storms_without_excluding(
    hass: HomeAssistant, freezer
):
    """A single reconnect-style burst still storms and is still not
    exempt from the duty cycle. Since 0.8.0 it no longer discards the
    gaps it completes (#124, #125): a device with a last-contact
    entity is protected by the timestamp, which a republish carries
    unchanged, and a device without one has nothing else to go on."""
    source = MockConfigEntry(domain="zigbee_like")
    source.add_to_hass(hass)
    fleet = register_fleet(hass, source, STORM_DEVICE_THRESHOLD + 2)

    coord = await setup_coordinator(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    for _dev, eid in fleet:
        hass.states.async_set(eid, "1")
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=9))
        async_fire_time_changed(hass)
    freezer.tick(timedelta(seconds=900))

    for _dev, eid in fleet:
        hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    assert coord._storm_active
    assert source.entry_id not in coord._storm_exempt
    tail = [
        coord.data[DATA_DEVICES][dev.id][DEV_TODAY_MAX]
        for dev, _ in fleet[STORM_DEVICE_THRESHOLD - 1 :]
    ]
    assert all(v is not None for v in tail)


# ------------------------------------------------ the trimmed maximum

def test_trimmed_maximum_rule():
    from custom_components.device_sentinel.coordinator import (
        DeviceSentinelCoordinator as C,
    )

    # Below the sample threshold: nothing trimmed, plain max.
    operative, set_aside = C._trimmed_maximum([500.0, 9000.0])
    assert operative == 9000.0 and set_aside == set()

    # At threshold: the single spike is set aside; survivors' max rules.
    gaps = [500.0, 550.0, 600.0, 520.0, 9000.0, 580.0, 560.0]
    operative, set_aside = C._trimmed_maximum(gaps)
    assert operative == 600.0
    assert set_aside == {4}

    # A recurring spike: one copy set aside, the second counts.
    gaps = [500.0, 9000.0, 600.0, 520.0, 9000.0, 580.0, 560.0]
    operative, set_aside = C._trimmed_maximum(gaps)
    assert operative == 9000.0
    assert len(set_aside) == 1

    # Empty history.
    assert C._trimmed_maximum([]) == (None, set())


async def test_markdown_render_marks_trim(hass: HomeAssistant):
    device, (eid,) = _md_device(hass)
    coord = await setup_coordinator(hass)

    # Inject a seven-day history with one spike, then rewrite reports.
    coord.data["devices"][device.id][DEV_DAILY_MAX] = [
        500.0, 550.0, 600.0, 520.0, 9000.0, 580.0, 560.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)

    text = open(
        hass.config.path("device_sentinel/diagnostics/device_telemetry.md")
    ).read()
    row = next(line for line in text.splitlines() if "Markdown Device" in line)
    assert "~~2.50h~~" in row          # the 9000 s spike, set aside
    assert "**600s**" in row           # the operative rhythm, bold
    # WINDOW BASIS was dropped at 0.4.4: the operative rhythm now
    # shows only as the bold value inside the GAPS series.
    # Newest first: the newest value (560) appears before the oldest (500).
    assert row.index("560s") < row.index("500s")


def _md_device(hass):
    """The markdown test needs a device named exactly Markdown Device,
    which its row is then found by, so it registers inline rather than
    through the shared helper's uid-derived name."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "md")},
        name="Markdown Device",
    )
    entry = er.async_get(hass).async_get_or_create(
        "sensor", "test", "md", device_id=device.id, config_entry=source
    )
    return device, (entry.entity_id,)


# ------------------------------------------------- the taint debounce

async def test_long_outage_taints_short_blip_does_not(
    hass: HomeAssistant, freezer
):
    device, (eid,) = _plain_device(hass, "d1", "D1")
    coord = await setup_coordinator(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    rec = coord.data[DATA_DEVICES][device.id]

    # Short blip: 30 s < debounce -> gap learns normally.
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=10))
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=30))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()
    assert rec[DEV_TODAY_MAX] == pytest.approx(40, abs=1)

    # Long outage: past the debounce floor -> taint applies, gap
    # excluded. This device is unarmed (no learned window), so its
    # debounce is the floor alone (#137); the outage must exceed it.
    floor = DEFAULT_TAINT_FLOOR_MINUTES * 60
    freezer.tick(timedelta(seconds=20))
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=floor + 120))
    hass.states.async_set(eid, "3")
    await hass.async_block_till_done()
    assert rec[DEV_TODAY_MAX] == pytest.approx(40, abs=1)  # unchanged
    assert rec[DEV_TAINTED] is False  # consumed by the recovery stamp


async def test_taint_log_reports_bad_state(
    hass: HomeAssistant, freezer, caplog
):
    """The taint line names the bad state, not the recovery value."""
    device, (eid,) = _plain_device(hass, "logdev", "LogDev")
    await setup_entry(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=DEFAULT_TAINT_FLOOR_MINUTES * 60 + 60))
    hass.states.async_set(eid, "-42")
    await hass.async_block_till_done()

    assert "was unavailable for" in caplog.text
    assert "was -42 for" not in caplog.text


async def test_taint_episode_dedupes_across_siblings(
    hass: HomeAssistant, freezer, caplog
):
    """One outage on a two-entity device logs one taint, not two."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "dedupe")},
        name="Dedupe Device",
    )
    ent_reg = er.async_get(hass)
    entity_ids = []
    for n in range(2):
        reg = ent_reg.async_get_or_create(
            "sensor", "test", f"dedupe_{n}",
            device_id=device.id, config_entry=source,
        )
        entity_ids.append(reg.entity_id)

    await setup_entry(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    for eid in entity_ids:
        hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    for eid in entity_ids:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=DEFAULT_TAINT_FLOOR_MINUTES * 60 + 120))
    for eid in entity_ids:
        hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    assert caplog.text.count("Device tainted:") == 1


# ------------------------------------------- epoch rollover + signal

async def test_epoch_reset_wipes_stats_keeps_clocks(
    hass: HomeAssistant, hass_storage
):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "devx")},
        name="DevX",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "devx", device_id=device.id, config_entry=source
    )
    old_clock = 1752200000.0
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            "first_installed": "2026-07-01T00:00:00+00:00",
            "setup_count": 5,
            DATA_STATS_EPOCH: "0.2.0",
            DATA_DEVICES: {
                device.id: {
                    DEV_LAST_ACTIVITY: old_clock,
                    DEV_DAILY_MAX: [100.0, 200.0],
                    DEV_TODAY_MAX: 50.0,
                    "first_observed": "2026-07-01T00:00:00+00:00",
                    DEV_EVENT_COUNT: 999,
                    DEV_TAINTED: True,
                }
            },
        },
    }
    coord = await setup_coordinator(hass)
    rec = coord.data[DATA_DEVICES][device.id]
    assert rec[DEV_DAILY_MAX] == []
    assert rec[DEV_TODAY_MAX] is None
    assert rec[DEV_EVENT_COUNT] == 0
    assert rec[DEV_TAINTED] is False
    assert rec[DEV_LAST_ACTIVITY] == old_clock
    assert coord.data[DATA_STATS_EPOCH] == STATS_EPOCH
    assert coord.first_installed == "2026-07-01T00:00:00+00:00"


async def test_signal_recording_and_rollover(hass: HomeAssistant, freezer):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "sig")},
        name="Sig",
    )
    ent_reg = er.async_get(hass)
    lq = ent_reg.async_get_or_create(
        "sensor", "test", "sig_lq",
        suggested_object_id="sig_linkquality",
        device_id=device.id, config_entry=source,
    )
    coord = await setup_coordinator(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    for v in ("120", "87", "140"):
        hass.states.async_set(lq.entity_id, v)
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=10))

    rec = coord.data[DATA_DEVICES][device.id]
    assert rec[DEV_SIGNAL_VALUE] == 140.0
    assert rec[DEV_SIGNAL_TODAY_MIN] == 87.0
    assert coord.clock_source_split["with_signal"] == 1

    nxt = (dt_util.now() + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    freezer.move_to(nxt + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert rec[DEV_SIGNAL_DAILY_MIN] == [87.0]
    assert rec[DEV_SIGNAL_TODAY_MIN] is None


def _plain_device(hass, uid, name):
    """A single-entity device registered inline, returning the device
    and its one entity id. The name is set explicitly because these
    tests assert on log lines and records keyed by the given name."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    entry = er.async_get(hass).async_get_or_create(
        "sensor", "test", uid, device_id=device.id, config_entry=source
    )
    return device, (entry.entity_id,)
