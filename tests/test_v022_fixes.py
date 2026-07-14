# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel

"""0.2.2 tests: storm duty-cycle exemption and deterministic attribution."""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_TODAY_MAX,
    STARTUP_GRACE_SECONDS,
    STORM_DEVICE_THRESHOLD,
    STORM_EXEMPT_PER_HOUR,
)

DOMAIN = "device_sentinel"


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _fleet(hass, source, count, prefix="dev"):
    out = []
    for i in range(count):
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("test", f"{prefix}{i}")},
            name=f"{prefix} {i}",
        )
        reg = er.async_get(hass).async_get_or_create(
            "sensor", "test", f"{prefix}_uid{i}",
            device_id=device.id, config_entry=source,
        )
        out.append((device, reg.entity_id))
    return out


async def test_synchronized_poller_exempted(hass: HomeAssistant, freezer, caplog):
    """A chronically storming entry is exempted; its devices then learn."""
    source = MockConfigEntry(domain="poller")
    source.add_to_hass(hass)
    fleet = _fleet(hass, source, STORM_DEVICE_THRESHOLD + 2)

    entry = await _setup(hass)
    coord = entry.runtime_data
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


async def test_rare_storm_still_excludes(hass: HomeAssistant, freezer):
    """A single reconnect-style burst still storms and still excludes."""
    source = MockConfigEntry(domain="zigbee_like")
    source.add_to_hass(hass)
    fleet = _fleet(hass, source, STORM_DEVICE_THRESHOLD + 2)

    entry = await _setup(hass)
    coord = entry.runtime_data
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
    assert all(v is None for v in tail)


async def test_attribution_uses_primary_config_entry(hass: HomeAssistant):
    """A multi-homed device attributes to its primary entry's domain."""
    owner = MockConfigEntry(domain="camera_brand")
    owner.add_to_hass(hass)
    tracker = MockConfigEntry(domain="router_tracker")
    tracker.add_to_hass(hass)

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("camera_brand", "cam1")},
        name="Multi-homed Camera",
    )
    dev_reg.async_update_device(
        device.id, add_config_entry_id=tracker.entry_id
    )
    er.async_get(hass).async_get_or_create(
        "camera", "camera_brand", "cam1_uid",
        device_id=device.id, config_entry=owner,
    )

    entry = await _setup(hass)
    coord = entry.runtime_data
    breakdown = coord.classification_breakdown
    assert breakdown.get("camera_brand", {}).get("watched", 0) == 1
    assert breakdown.get("router_tracker", {}).get("watched", 0) == 0
