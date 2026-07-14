"""0.2.3 tests: taint debounce, epoch reset, signal recording, assist."""

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
    TAINT_DEBOUNCE_SECONDS,
)

DOMAIN = "device_sentinel"


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_long_outage_taints_short_blip_does_not(
    hass: HomeAssistant, freezer
):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "d1")},
        name="D1",
    )
    reg = er.async_get(hass).async_get_or_create(
        "sensor", "test", "d1", device_id=device.id, config_entry=source
    )
    eid = reg.entity_id
    entry = await _setup(hass)
    coord = entry.runtime_data
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

    # Long outage: >= debounce -> taint applies, gap excluded.
    freezer.tick(timedelta(seconds=20))
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=TAINT_DEBOUNCE_SECONDS + 400))
    hass.states.async_set(eid, "3")
    await hass.async_block_till_done()
    assert rec[DEV_TODAY_MAX] == pytest.approx(40, abs=1)  # unchanged
    assert rec[DEV_TAINTED] is False  # consumed by the recovery stamp


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
    entry = await _setup(hass)
    coord = entry.runtime_data
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
    entry = await _setup(hass)
    coord = entry.runtime_data
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


async def test_enable_assist(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "ea")},
        name="EA",
    )
    ent_reg = er.async_get(hass)
    int_disabled = ent_reg.async_get_or_create(
        "sensor", "test", "ea_ls",
        suggested_object_id="ea_last_seen",
        device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    user_disabled = ent_reg.async_get_or_create(
        "sensor", "test", "ea_lq",
        suggested_object_id="ea_linkquality",
        device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    plain = ent_reg.async_get_or_create(
        "sensor", "test", "ea_temp",
        suggested_object_id="ea_temperature",
        device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    entry = await _setup(hass)
    coord = entry.runtime_data

    result = await coord.async_enable_signal_entities()
    assert result == {"last_seen": 1, "signal": 0, "skipped_user": 1}
    assert ent_reg.async_get(int_disabled.entity_id).disabled_by is None
    assert (
        ent_reg.async_get(user_disabled.entity_id).disabled_by
        is er.RegistryEntryDisabler.USER
    )
    assert ent_reg.async_get(plain.entity_id).disabled_by is not None

    # Button exists and presses without error.
    state = hass.states.get("button.device_sentinel_enable_signal_entities")
    assert state is not None
    await hass.services.async_call(
        "button", "press",
        {"entity_id": "button.device_sentinel_enable_signal_entities"},
        blocking=True,
    )


async def test_taint_log_reports_bad_state(
    hass: HomeAssistant, freezer, caplog
):
    """The taint line names the bad state, not the recovery value."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "logdev")},
        name="LogDev",
    )
    reg = er.async_get(hass).async_get_or_create(
        "sensor", "test", "logdev", device_id=device.id, config_entry=source
    )
    entry = await _setup(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    hass.states.async_set(reg.entity_id, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=TAINT_DEBOUNCE_SECONDS + 60))
    hass.states.async_set(reg.entity_id, "-42")
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

    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    for eid in entity_ids:
        hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    for eid in entity_ids:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=TAINT_DEBOUNCE_SECONDS + 600))
    for eid in entity_ids:
        hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    assert caplog.text.count("Device tainted:") == 1
