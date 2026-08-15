# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_ignored_integrations.py, Version: 0.14.1 (2026-08-14)

"""Integrations a person asks never to be watched.

Every other removal in this project suppresses judgment and reporting
and keeps the record, because a device excluded today may be included
tomorrow and its history is worth having when it is. This one
suppresses the watching itself, for integrations that publish
measurements of nothing a house can be judged on: a phone travels and
carries a cellular radio, a wall tablet's battery is charged rather
than replaced, Spook describes Home Assistant rather than hardware,
and a ping probe answers on every poll so it can never fall silent.

It replaced two lists of refused words. Those named entities by what
somebody had called them, which caught an ESPHome node's own RSSI
because its sensor is called WiFi Signal, and missed a phone's
cellular radio because its sensor is not called cellular. Four
mobile_app devices were recording live signal series on the reference
fleet at the moment the terms were deleted, one of them a cellular
radio reading -109 to -123 dBm against a dropout anchor of -90.

The discard happens at the fold rather than on the save, because the
fold is already the one place the record changes size: lowering how
much history to keep does not delete anything when the slider moves
either. So a person who ignores an integration by mistake has until
midnight to take it back with nothing lost.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.const import (
    CONF_IGNORED_INTEGRATIONS,
    DATA_DEVICES,
    DEFAULT_IGNORED_INTEGRATIONS,
    SET_ASIDE_IGNORED,
)

from .helpers import register_device, setup_entry


async def _coordinator(hass: HomeAssistant, options: dict | None = None):
    entry = await setup_entry(hass, options)
    return entry.runtime_data, entry


async def test_the_default_list_applies_before_the_screen_is_saved(
    hass: HomeAssistant,
):
    """A fresh install starts with the four, without storing them.

    The list is the person's, so it is not written into their options
    behind them. Until the screen is submitted the default stands in
    for it, which is what makes an upgrade and a fresh install behave
    the same way.
    """
    coordinator, _entry = await _coordinator(hass)
    assert coordinator.ignored_integrations == frozenset(
        DEFAULT_IGNORED_INTEGRATIONS
    )
    assert "mobile_app" in coordinator.ignored_integrations
    assert "ping" in coordinator.ignored_integrations


async def test_a_saved_empty_list_stays_empty(hass: HomeAssistant):
    """The default must not reassert itself over a deliberate choice.

    A default that came back on restart would make the setting
    impossible to switch off, and a person who cleared the list would
    find it refilled by morning with no explanation.
    """
    coordinator, _entry = await _coordinator(
        hass, {CONF_IGNORED_INTEGRATIONS: []}
    )
    assert coordinator.ignored_integrations == frozenset()


async def test_a_device_on_an_ignored_integration_is_set_aside(
    hass: HomeAssistant,
):
    """Not watched, and the classification file says which reason.

    The reason recorded is the person's choice even where another
    would also fit, because everything else on that ladder is a fact
    about the device and this is a decision about it.
    """
    device, _eids = register_device(hass, "phone", name="James S24+")
    coordinator, _entry = await _coordinator(
        hass, {CONF_IGNORED_INTEGRATIONS: ["test"]}
    )
    coordinator._rebuild_registry_view()
    assert device.id not in coordinator._watched
    assert device.id in coordinator._set_aside
    _name, _domain, reason = coordinator._set_aside[device.id]
    assert reason == SET_ASIDE_IGNORED


async def test_ignoring_keeps_the_record_until_the_fold(
    hass: HomeAssistant,
):
    """The undo window: a mistake costs nothing before midnight.

    Set aside immediately so nothing new is learned, and the record
    left alone so putting the integration back restores it untouched.
    """
    device, _eids = register_device(hass, "probe", name="SLZB_06M")
    coordinator, _entry = await _coordinator(hass)
    coordinator._rebuild_registry_view()
    assert device.id in coordinator.data[DATA_DEVICES]

    hass.config_entries.async_update_entry(
        _entry, options={CONF_IGNORED_INTEGRATIONS: ["test"]}
    )
    await hass.async_block_till_done()
    coordinator._rebuild_registry_view()

    assert device.id not in coordinator._watched
    assert device.id in coordinator.data[DATA_DEVICES]


async def test_the_fold_discards_what_an_ignored_integration_recorded(
    hass: HomeAssistant,
):
    """Midnight is where the record changes size, for this as for
    retention. One deletion path, not two."""
    device, _eids = register_device(hass, "probe", name="SLZB_06M")
    coordinator, _entry = await _coordinator(
        hass, {CONF_IGNORED_INTEGRATIONS: ["test"]}
    )
    coordinator._rebuild_registry_view()
    coordinator.data[DATA_DEVICES][device.id] = {"anything": 1}
    assert device.id in coordinator.data[DATA_DEVICES]

    coordinator._discard_ignored_records()
    assert device.id not in coordinator.data[DATA_DEVICES]


async def test_a_watched_device_survives_the_discard(hass: HomeAssistant):
    """The discard reaches exactly the ignored ones.

    A device set aside for any other reason keeps its record
    untouched (ruling #257): a disabling is Home Assistant's doing
    and may last an afternoon.
    """
    device, _eids = register_device(hass, "door", name="Door Master")
    coordinator, _entry = await _coordinator(
        hass, {CONF_IGNORED_INTEGRATIONS: []}
    )
    coordinator._rebuild_registry_view()
    assert device.id in coordinator.data[DATA_DEVICES]

    coordinator._discard_ignored_records()
    assert device.id in coordinator.data[DATA_DEVICES]


async def test_an_ignored_integration_is_still_offered_by_the_picker(
    hass: HomeAssistant,
):
    """The choice must be reversible from the screen that made it.

    Ignoring an integration takes it out of the watched set, so a
    picker built from watched rows alone would forget it existed and
    strand the person with a setting they could not undo.
    """
    register_device(hass, "phone", name="James S24+")
    coordinator, _entry = await _coordinator(
        hass, {CONF_IGNORED_INTEGRATIONS: ["test"]}
    )
    coordinator._rebuild_registry_view()
    assert "test" in coordinator.classification_breakdown


async def test_the_registry_still_holds_the_device(hass: HomeAssistant):
    """Ignoring is Device Sentinel's business and nobody else's.

    Nothing here disables an entity, hides a device, or touches the
    registry: the device goes on working in Home Assistant exactly as
    it did, and only this integration stops looking at it.
    """
    device, eids = register_device(hass, "phone", name="James S24+")
    coordinator, _entry = await _coordinator(
        hass, {CONF_IGNORED_INTEGRATIONS: ["test"]}
    )
    coordinator._rebuild_registry_view()
    assert dr.async_get(hass).async_get(device.id) is not None
    assert eids

async def test_a_set_aside_device_reaches_no_surface(hass: HomeAssistant):
    """The fault 0.14.1 exposed and 0.14.2 fixes.

    Every surface but one walked the record store directly, on the
    assumption that a record implies a watched device. Ruling #257
    broke that assumption and the ignore list made twenty-two of them
    at once: the battery report called ignored phones watched cells,
    and one of them reached the problem list.
    """
    device, _eids = register_device(hass, "phone", name="Oneplus Pad")
    coordinator, _entry = await _coordinator(
        hass, {CONF_IGNORED_INTEGRATIONS: []}
    )
    coordinator._rebuild_registry_view()
    assert device.id in dict(coordinator.watched_records())

    hass.config_entries.async_update_entry(
        _entry, options={CONF_IGNORED_INTEGRATIONS: ["test"]}
    )
    await hass.async_block_till_done()
    coordinator._rebuild_registry_view()

    # The record is still there, and no surface may read it.
    assert device.id in coordinator.data[DATA_DEVICES]
    assert device.id not in dict(coordinator.watched_records())


async def test_the_picker_hides_an_integration_already_set_aside(
    hass: HomeAssistant,
):
    """Offering it would change nothing, and it buries the real
    choices under add-ons and dashboard cards. On the reference fleet
    this took the list from thirty-two entries to fifteen."""
    coordinator, _entry = await _coordinator(
        hass, {CONF_IGNORED_INTEGRATIONS: []}
    )
    coordinator._rebuild_registry_view()
    breakdown = coordinator.classification_breakdown
    offered = {d for d, c in breakdown.items() if c.get("watched")}
    hidden = {d for d, c in breakdown.items() if not c.get("watched")}
    assert hidden, "expected at least one wholly set-aside integration"
    assert not (offered & hidden)
