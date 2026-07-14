# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel

"""Reproduction: a taint set during grace survives a grace recovery."""

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
    DEV_TAINTED,
    DEV_TODAY_MAX,
    STARTUP_GRACE_SECONDS,
)

DOMAIN = "device_sentinel"


async def test_grace_recovery_consumes_taint(hass: HomeAssistant, freezer):
    """A boot-blip taint must be consumed by the in-grace recovery,
    so the first post-grace gap still feeds learning."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "blippy")},
        name="Blippy Door",
    )
    reg = er.async_get(hass).async_get_or_create(
        "binary_sensor", "test", "blippy",
        device_id=device.id, config_entry=source,
    )
    eid = reg.entity_id

    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    rec = coord.data[DATA_DEVICES][device.id]

    # Boot blip inside the grace: unavailable, then retained value.
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    assert rec[DEV_TAINTED] is False  # debounced: a blip sets no taint
    freezer.tick(timedelta(seconds=5))
    hass.states.async_set(eid, "off")  # recovery, still inside grace
    await hass.async_block_till_done()
    assert rec[DEV_TAINTED] is False, "a 5 s blip must never taint"

    # Past the grace: the first real gap must feed learning.
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    hass.states.async_set(eid, "on")
    await hass.async_block_till_done()
    # The gap from the in-grace recovery stamp (grace ended 305 s in,
    # recovery at 5 s) to this first post-grace event is organic
    # silence and must be learned: 310 s.
    assert rec[DEV_TODAY_MAX] == pytest.approx(310, abs=1), (
        "first post-grace gap must be learned"
    )
    freezer.tick(timedelta(seconds=140))
    hass.states.async_set(eid, "off")
    await hass.async_block_till_done()
    assert rec[DEV_TODAY_MAX] == pytest.approx(310, abs=1)
