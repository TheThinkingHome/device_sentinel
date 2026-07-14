# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel

"""Step 2 telemetry recorder tests for Device Sentinel."""

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
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_LAST_ACTIVITY,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    STARTUP_GRACE_SECONDS,
    STORAGE_KEY,
    STORM_DEVICE_THRESHOLD,
)

DOMAIN = "device_sentinel"


async def _setup_sentinel(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _make_device(hass, source_entry, index, *, service=False, n_entities=1):
    """Create a device with entities; return (device, [entity_ids])."""
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=source_entry.entry_id,
        identifiers={("test", f"dev{index}")},
        name=f"Test Device {index}",
        entry_type=dr.DeviceEntryType.SERVICE if service else None,
    )
    entity_ids = []
    for n in range(n_entities):
        reg_entry = ent_reg.async_get_or_create(
            "sensor",
            "test",
            f"uid_{index}_{n}",
            device_id=device.id,
            config_entry=source_entry,
        )
        entity_ids.append(reg_entry.entity_id)
    return device, entity_ids


async def _pass_grace(hass, freezer):
    """Advance past the startup grace."""
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_classification_sets_service_devices_aside(
    hass: HomeAssistant,
):
    """Service devices get no telemetry records; hardware devices do."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    hw, _ = _make_device(hass, source, 1)
    svc, _ = _make_device(hass, source, 2, service=True)

    entry = await _setup_sentinel(hass)
    coord = entry.runtime_data

    assert hw.id in coord.data[DATA_DEVICES]
    assert svc.id not in coord.data[DATA_DEVICES]
    assert coord.set_aside_count >= 1
    # The integration's own device is service-type: it sets itself aside.
    own = dr.async_get(hass).async_get_device({(DOMAIN, entry.entry_id)})
    assert own is not None
    assert own.id not in coord.data[DATA_DEVICES]


async def test_grace_stamps_but_does_not_learn(hass: HomeAssistant, freezer):
    """Events inside the startup grace never complete gaps."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    _, (eid,) = _make_device(hass, source, 1)

    entry = await _setup_sentinel(hass)
    coord = entry.runtime_data
    rec = coord.data[DATA_DEVICES][list(coord.data[DATA_DEVICES])[0]]

    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=60))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    assert rec[DEV_LAST_ACTIVITY] is not None
    assert rec[DEV_TODAY_MAX] is None
    assert rec[DEV_EVENT_COUNT] == 2


async def test_gap_learning_after_grace(hass: HomeAssistant, freezer):
    """Completed gaps feed today's maximum after the grace."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, (eid,) = _make_device(hass, source, 1)

    entry = await _setup_sentinel(hass)
    coord = entry.runtime_data
    await _pass_grace(hass, freezer)

    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=120))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=45))
    hass.states.async_set(eid, "2")  # same value: state_reported
    await hass.async_block_till_done()

    rec = coord.data[DATA_DEVICES][device.id]
    assert rec[DEV_TODAY_MAX] == pytest.approx(120, abs=1)
    assert rec[DEV_EVENT_COUNT] == 3


async def test_taint_excludes_outage_gap(hass: HomeAssistant, freezer):
    """A gap spanning unavailability never feeds learning."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, (eid,) = _make_device(hass, source, 1)

    entry = await _setup_sentinel(hass)
    coord = entry.runtime_data
    await _pass_grace(hass, freezer)

    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=30))
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()

    rec = coord.data[DATA_DEVICES][device.id]
    assert rec[DEV_TAINTED] is False  # debounced: no taint yet

    freezer.tick(timedelta(seconds=3600))
    hass.states.async_set(eid, "5")  # recovery after a real outage
    await hass.async_block_till_done()
    assert rec[DEV_TAINTED] is False  # taint consumed by the same stamp
    assert rec[DEV_TODAY_MAX] is None

    freezer.tick(timedelta(seconds=90))
    hass.states.async_set(eid, "6")  # clean gap: learned
    await hass.async_block_till_done()
    assert rec[DEV_TODAY_MAX] == pytest.approx(90, abs=1)


async def test_storm_excludes_republish(hass: HomeAssistant, freezer):
    """A many-device burst on one entry is a storm; its stamps don't learn."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    devices = [
        _make_device(hass, source, i)
        for i in range(1, STORM_DEVICE_THRESHOLD + 3)
    ]

    entry = await _setup_sentinel(hass)
    coord = entry.runtime_data
    await _pass_grace(hass, freezer)

    # Give every device a prior stamp, spaced out (organic).
    for n, (_dev, (eid,)) in enumerate(devices):
        hass.states.async_set(eid, "1")
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=7))
        async_fire_time_changed(hass)
    freezer.tick(timedelta(seconds=600))

    # Republish: every device writes within the same instant.
    for _dev, (eid,) in devices:
        hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    assert coord._storm_active  # a storm was declared
    tainted_learning = [
        coord.data[DATA_DEVICES][dev.id][DEV_TODAY_MAX]
        for dev, _ in devices[STORM_DEVICE_THRESHOLD - 1 :]
    ]
    # Devices stamped at or after the declaration learned nothing.
    assert all(v is None for v in tainted_learning)

    # Quiet releases the storm; the next organic gap learns again.
    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    dev, (eid,) = devices[0]
    freezer.tick(timedelta(seconds=50))
    hass.states.async_set(eid, "3")
    await hass.async_block_till_done()
    assert not coord._storm_active


async def test_midnight_rollover(hass: HomeAssistant, freezer):
    """Today's maxima roll into the bounded daily set at midnight."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, (eid,) = _make_device(hass, source, 1)

    entry = await _setup_sentinel(hass)
    coord = entry.runtime_data
    await _pass_grace(hass, freezer)

    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=200))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    rec = coord.data[DATA_DEVICES][device.id]
    assert rec[DEV_TODAY_MAX] == pytest.approx(200, abs=1)

    now = dt_util.now()
    next_midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    freezer.move_to(next_midnight + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert rec[DEV_TODAY_MAX] is None
    assert len(rec[DEV_DAILY_MAX]) == 1
    assert rec[DEV_DAILY_MAX][0] == pytest.approx(200, abs=1)


async def test_seeding_from_last_seen(hass: HomeAssistant):
    """A device with a last_seen entity seeds its clock from it."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "seeded")},
        name="Seeded Device",
    )
    reg_entry = ent_reg.async_get_or_create(
        "sensor",
        "test",
        "seeded_ls",
        suggested_object_id="seeded_last_seen",
        device_id=device.id,
        config_entry=source,
    )
    seed = "2026-07-09T12:00:00+00:00"
    hass.states.async_set(reg_entry.entity_id, seed)
    await hass.async_block_till_done()

    entry = await _setup_sentinel(hass)
    coord = entry.runtime_data
    rec = coord.data[DATA_DEVICES][device.id]
    assert rec[DEV_LAST_ACTIVITY] == pytest.approx(
        dt_util.parse_datetime(seed).timestamp()
    )
    assert coord.clock_source_split["with_last_seen"] == 1


async def test_storage_roundtrip_with_devices(hass: HomeAssistant, hass_storage):
    """Per-device statistics survive a reload."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, (eid,) = _make_device(hass, source, 1)

    entry = await _setup_sentinel(hass)
    coord = entry.runtime_data
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    await coord._store.async_save(coord.data)

    assert device.id in hass_storage[STORAGE_KEY]["data"][DATA_DEVICES]

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord2 = entry.runtime_data
    assert device.id in coord2.data[DATA_DEVICES]
    assert coord2.data[DATA_DEVICES][device.id][DEV_EVENT_COUNT] == 1


async def test_coverage_sensors(hass: HomeAssistant):
    """The coverage and diagnostics sensors render the registry view."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    _make_device(hass, source, 1)
    _make_device(hass, source, 2)
    _make_device(hass, source, 3, service=True)

    entry = await _setup_sentinel(hass)
    coord = entry.runtime_data
    coord._notify()
    await hass.async_block_till_done()

    coverage = hass.states.get("sensor.device_sentinel_coverage")
    assert coverage is not None
    assert int(coverage.state) == coord.watched_count
    assert coverage.attributes["set_aside"] == coord.set_aside_count
    assert coverage.attributes["learning"]["observing"] >= 2

    classification = hass.states.get("sensor.device_sentinel_classification")
    assert classification is not None
    assert classification.attributes["by_integration"]["test"]["watched"] == 2
    assert (
        classification.attributes["by_integration"]["test"]["set_aside"] == 1
    )

    clock = hass.states.get("sensor.device_sentinel_clock_source")
    assert clock is not None
    assert int(clock.state) == coord.clock_source_split["without_last_seen"]

    learning = hass.states.get("sensor.device_sentinel_learning_progress")
    assert learning is not None
    assert learning.state == "0"
