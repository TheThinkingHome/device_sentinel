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
debounce, the daily epoch rollover, the signal recording that
rides alongside the same clock, and the contact clock that reads a
device's own last-contact entity every time rather than stamping the
moment a payload arrived.
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
    DATA_INCIDENTS,
    DATA_STATS_EPOCH,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_TODAY_MIN,
    DEV_SIGNAL_VALUE,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    FREEZE_CATEGORY_FROZEN,
    INC_CAUSE,
    LEGACY_CAUSE_UNOBSERVED,
    RECOVERY_CAUSE_UNOBSERVED,
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


# ==================================================================
# The contact clock: records contact, not arrival.
# ==================================================================

def _contact_device(hass, uid, name, with_contact=True):
    """Register a device, optionally with a last_seen entity."""
    source = MockConfigEntry(domain="test", title=f"Source {uid}")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    reg = er.async_get(hass)
    plain = reg.async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    contact = None
    if with_contact:
        contact = reg.async_get_or_create(
            "sensor", "test", f"{uid}_last_seen",
            device_id=device.id, config_entry=source,
            original_name="Last seen",
            suggested_object_id=f"{uid}_last_seen",
        ).entity_id
    return device, plain.entity_id, contact, source


def _iso(offset_seconds: float = 0.0) -> str:
    return (
        dt_util.utcnow() + timedelta(seconds=offset_seconds)
    ).isoformat()


def _record(coord, device_id):
    return coord.data[DATA_DEVICES][device_id]


async def test_contact_entity_is_found_and_used(hass: HomeAssistant):
    device, _entity, contact, _src = _contact_device(hass, "c1", "Zigbee Thing")
    coord = await setup_coordinator(hass)
    assert device.id in coord._last_seen_entity
    assert coord._last_seen_entity[device.id] == contact


async def test_a_republish_does_not_advance_the_clock(
    hass: HomeAssistant, freezer
):
    """The heart of it. A replayed payload carries the coordinator's
    old reading, so the silence behind it keeps running."""
    device, entity_id, contact, _src = _contact_device(hass, "c2", "Republished")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0

    heard = _iso()
    hass.states.async_set(contact, heard)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    first = _record(coord, device.id)[DEV_LAST_ACTIVITY]
    assert first is not None

    # An hour later the payload is replayed: same last_seen value.
    freezer.tick(timedelta(hours=1))
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()
    assert _record(coord, device.id)[DEV_LAST_ACTIVITY] == first
    assert _record(coord, device.id)[DEV_TODAY_MAX] is None


async def test_a_genuine_report_advances_and_learns(
    hass: HomeAssistant, freezer
):
    device, entity_id, contact, _src = _contact_device(hass, "c3", "Genuine")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0

    hass.states.async_set(contact, _iso())
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    first = _record(coord, device.id)[DEV_LAST_ACTIVITY]

    freezer.tick(timedelta(hours=2))
    hass.states.async_set(contact, _iso())
    await hass.async_block_till_done()
    record = _record(coord, device.id)
    assert record[DEV_LAST_ACTIVITY] > first
    assert record[DEV_TODAY_MAX] == pytest.approx(7200, abs=5)


async def test_an_unavailable_contact_entity_stops_the_clock(
    hass: HomeAssistant, freezer
):
    """Door Master's read unavailable for the ten hours it was
    wedged. That is information, not a missing value."""
    device, entity_id, contact, _src = _contact_device(hass, "c4", "Wedged")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0

    hass.states.async_set(contact, _iso())
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    first = _record(coord, device.id)[DEV_LAST_ACTIVITY]

    freezer.tick(timedelta(hours=4))
    hass.states.async_set(contact, "unavailable")
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()
    assert _record(coord, device.id)[DEV_LAST_ACTIVITY] == first


async def test_a_republish_does_not_clear_a_freeze_verdict(
    hass: HomeAssistant, freezer
):
    """A four-second bridge blip erased a nine-hour silence once."""
    device, entity_id, contact, _src = _contact_device(hass, "c5", "Still Frozen")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    hass.states.async_set(contact, _iso(-36000))
    await hass.async_block_till_done()

    record = _record(coord, device.id)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 3600

    hass.states.async_set(entity_id, "republished")
    await hass.async_block_till_done()
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN

    # A real report clears it.
    hass.states.async_set(contact, _iso())
    await hass.async_block_till_done()
    assert record[DEV_FROZEN_CATEGORY] is None


async def test_a_clock_never_runs_backwards_or_ahead(
    hass: HomeAssistant, freezer
):
    device, entity_id, contact, _src = _contact_device(hass, "c6", "Time Traveller")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0

    hass.states.async_set(contact, _iso())
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    first = _record(coord, device.id)[DEV_LAST_ACTIVITY]

    # A device clock running fast must not push ours into the future.
    hass.states.async_set(contact, _iso(3600))
    await hass.async_block_till_done()
    assert _record(coord, device.id)[DEV_LAST_ACTIVITY] <= (
        dt_util.utcnow().timestamp()
    )

    # And an older reading must not drag it back.
    hass.states.async_set(contact, _iso(-3600))
    await hass.async_block_till_done()
    assert _record(coord, device.id)[DEV_LAST_ACTIVITY] >= first


async def test_events_are_still_counted_when_nothing_advances(
    hass: HomeAssistant,
):
    device, entity_id, contact, _src = _contact_device(hass, "c7", "Counted")
    coord = await setup_coordinator(hass)
    hass.states.async_set(contact, "unavailable")
    hass.states.async_set(entity_id, "1")
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()
    assert _record(coord, device.id)[DEV_EVENT_COUNT] >= 2


async def test_without_a_contact_entity_arrival_time_counts(
    hass: HomeAssistant, freezer
):
    """#125: the reboot stamp is a report, because it is the only
    evidence there is."""
    device, entity_id, _none, _src = _contact_device(
        hass, "n1", "HomeKit Like", with_contact=False
    )
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0

    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=5))
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()

    record = _record(coord, device.id)
    assert record[DEV_TODAY_MAX] == pytest.approx(18000, abs=5)


async def test_a_gap_completed_inside_grace_is_learned(
    hass: HomeAssistant, freezer
):
    """The reversal that matters. The nightly restart is part of the
    home, and discarding what it completes left quiet devices with
    baselines describing half a night."""
    device, entity_id, _none, _src = _contact_device(
        hass, "n2", "Quiet Overnight", with_contact=False
    )
    coord = await setup_coordinator(hass)
    coord._grace_until = dt_util.utcnow().timestamp() + 300

    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=6))
    hass.states.async_set(entity_id, "2")
    await hass.async_block_till_done()

    assert _record(coord, device.id)[DEV_TODAY_MAX] == pytest.approx(
        21600, abs=5
    )


async def test_the_legacy_cause_wording_is_migrated(
    hass: HomeAssistant,
):
    """0.7.6 renamed a stored value without rewriting what was
    already stored, and the composer then wrote "revived by a on its
    own" into a live brief."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data

    coord.data[DATA_INCIDENTS].append(
        {
            "device_id": "d",
            "name": "Door Master",
            "kind": "unavailable",
            "event": "resolved",
            "when": dt_util.utcnow().timestamp(),
            INC_CAUSE: LEGACY_CAUSE_UNOBSERVED,
            "duration": 15480.0,
        }
    )
    await coord._save_now()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    reloaded = entry.runtime_data.data[DATA_INCIDENTS]
    assert reloaded[-1][INC_CAUSE] == RECOVERY_CAUSE_UNOBSERVED
    assert all(
        row[INC_CAUSE] != LEGACY_CAUSE_UNOBSERVED for row in reloaded
    )
