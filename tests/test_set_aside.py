"""Tests for setting disabled devices aside.

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_set_aside.py, Version: 0.13.6 (2026-08-13)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

Reported by teskanoo in issue #1: entities of disabled integrations
were monitored and reported, which is white noise, since a disabled
device cannot report and its silence says nothing about the hardware.

The rule is drawn at the device (ruling #257). A device Home
Assistant has disabled is set aside, and so is a device with no
entities at all, because neither can ever speak and neither has
anything a person could switch on. A device whose entities are all
disabled stays watched: those entities exist, the never-reported row
is the prompt, and a person can enable them or exclude the device.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_SET_ASIDE_SINCE,
    LEARNED_DISABLED,
    SET_ASIDE_DISABLED,
    SET_ASIDE_NO_ENTITIES,
    SET_ASIDE_SERVICE,
)

from .helpers import register_device, setup_coordinator


def _device(hass, uid, name, entities=1, disabled=None, entity_disabled=None):
    """Build a registry device, optionally disabled, with N entities."""
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
        disabled_by=disabled,
    )
    for index in range(entities):
        er.async_get(hass).async_get_or_create(
            "sensor", "test", f"{uid}_{index}",
            device_id=device.id, config_entry=source,
            disabled_by=entity_disabled,
        )
    return device


async def test_a_disabled_device_is_set_aside(hass: HomeAssistant):
    """Issue #1, at the device level: a disabled device cannot report,
    so watching for its silence produces a problem row about nothing."""
    device = _device(
        hass, "sa1", "Disabled Device",
        disabled=dr.DeviceEntryDisabler.USER,
    )
    coord = await setup_coordinator(hass)

    assert device.id not in coord._watched
    assert coord._set_aside[device.id][2] == SET_ASIDE_DISABLED


async def test_a_device_with_no_entities_is_set_aside(hass: HomeAssistant):
    """Nothing exists that could report and nothing a person could
    switch on, so the silence says nothing either way."""
    device = _device(hass, "sa2", "Empty Device", entities=0)
    coord = await setup_coordinator(hass)
    # Past the startup window: during it a device with no entities is
    # usually one whose integration has not finished loading, so the
    # rule is held (ruling #260).
    coord._grace_until = 0.0
    coord._rebuild_registry_view()

    assert device.id not in coord._watched
    assert coord._set_aside[device.id][2] == SET_ASIDE_NO_ENTITIES


async def test_a_device_whose_entities_are_disabled_stays_watched(
    hass: HomeAssistant,
):
    """Ruled deliberately against the simpler rule: those entities
    exist, so the device is one press from reporting again, and the
    never-reported row is the prompt that says so."""
    device = _device(
        hass, "sa3", "Silenced Device",
        entity_disabled=er.RegistryEntryDisabler.USER,
    )
    coord = await setup_coordinator(hass)

    assert device.id in coord._watched
    assert device.id not in coord._set_aside


async def test_a_service_device_keeps_its_own_reason(hass: HomeAssistant):
    """The reason is recorded rather than inferred: a disabled device
    and a service device both read as set aside, and the audit view
    has to say which."""
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "sa4")},
        name="Service Device",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    coord = await setup_coordinator(hass)

    assert coord._set_aside[device.id][2] == SET_ASIDE_SERVICE


async def test_a_set_aside_device_keeps_everything_it_learned(
    hass: HomeAssistant,
):
    """The fault this rule would have caused if the record pruning
    had been left alone: disabling an integration for an afternoon
    would have deleted every rhythm, floor, and series it owned, and
    re-enabling it would have started from nothing with a seven-day
    re-arm and no explanation.
    """
    device, _ = register_device(hass, "sa5", "Learned Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * 30

    dr.async_get(hass).async_update_device(
        device.id, disabled_by=dr.DeviceEntryDisabler.USER
    )
    await hass.async_block_till_done()

    assert device.id not in coord._watched
    kept = coord.data[DATA_DEVICES][device.id]
    assert kept[DEV_DAILY_MAX] == [3600.0] * 30
    assert kept[DEV_SET_ASIDE_SINCE] is not None


async def test_a_departed_device_still_loses_its_record(
    hass: HomeAssistant,
):
    """Set aside is not gone. A device the registry no longer holds
    has nothing left to describe, and its record goes as before."""
    device, _ = register_device(hass, "sa6", "Leaving Device")
    coord = await setup_coordinator(hass)
    assert device.id in coord.data[DATA_DEVICES]

    dr.async_get(hass).async_remove_device(device.id)
    await hass.async_block_till_done()

    assert device.id not in coord.data[DATA_DEVICES]


async def test_the_gap_that_spans_a_disabling_is_refused(
    hass: HomeAssistant,
):
    """A fortnight switched off must not teach a fortnight-long
    window. The stamp survives the registry rebuild that brings the
    device back, because that rebuild runs before the device speaks,
    and it is spent by the device's own first report.
    """
    device, (entity_id,) = register_device(hass, "sa7", "Returning Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SET_ASIDE_SINCE] = 1000.0

    assert record[DEV_SET_ASIDE_SINCE] is not None
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()

    assert record[DEV_SET_ASIDE_SINCE] is None


async def test_the_refusal_reason_is_its_own_word(hass: HomeAssistant):
    """Named apart from pairing and maintenance so the episode file
    says which hand caused the silence."""
    assert LEARNED_DISABLED == "no (disabled)"
    assert LEARNED_DISABLED.startswith("no (")
