# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_infrastructure.py, Version: 0.29.5 (2026-11-17)

"""Diagnostics says what the plumbing is, not only how it behaved
(rule DEV-16).

A report about a coordinator misbehaving can be matched against that
hardware's documentation only if something records what the hardware
is. So each device record carries its identity, and one block names
the stacks, the broker and any router integration the house runs.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)

from tests.helpers import setup_entry


async def test_a_device_carries_its_make_and_model(hass: HomeAssistant):
    """The two fields that turn a report into something lookupable."""
    entry = await setup_entry(hass)
    source = MockConfigEntry(domain="mqtt")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    made = registry.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", "sensor-1")},
        name="Fenetre Thomas",
        manufacturer="Third Reality",
        model="3RDS17BZ",
        sw_version="1.0.9",
    )

    data = await async_get_config_entry_diagnostics(hass, entry)

    # Named by its stand-in, never "Fenetre Thomas" (rule STOR-21).
    device = data["devices"][made.id]
    assert device["name"] == "Device 1"
    assert device["manufacturer"] == "Third Reality"
    assert device["model"] == "3RDS17BZ"
    assert device["sw_version"] == "1.0.9"


async def test_a_router_integration_is_named_with_its_hardware(
    hass: HomeAssistant,
):
    """Which router a house runs, and what that router is.

    Wider than what is supported today on purpose: a report from a
    router nobody has built for is the report worth having.
    """
    entry = await setup_entry(hass)
    router = MockConfigEntry(domain="fritz", title="FRITZ!Box 7590")
    router.add_to_hass(hass)
    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=router.entry_id,
        identifiers={("fritz", "box")},
        name="FRITZ!Box",
        manufacturer="AVM",
        model="FRITZ!Box 7590 AX",
        sw_version="7.57",
    )

    data = await async_get_config_entry_diagnostics(hass, entry)

    block = data["infrastructure"]["fritz"]
    # The entry's title is a person's wording and is not shown.
    assert block["entries"] == ["fritz entry 1"]
    assert block["devices"][0]["manufacturer"] == "AVM"
    assert block["devices"][0]["model"] == "FRITZ!Box 7590 AX"


async def test_a_domain_the_house_does_not_run_is_absent(
    hass: HomeAssistant,
):
    """The block names what is there, not every domain it knows of."""
    entry = await setup_entry(hass)

    data = await async_get_config_entry_diagnostics(hass, entry)

    assert "mikrotik" not in data["infrastructure"]


async def test_a_router_with_many_clients_does_not_bury_the_router(
    hass: HomeAssistant,
):
    """A tracked client is not infrastructure. The cap keeps the four
    lines that say what the router is readable."""
    entry = await setup_entry(hass)
    router = MockConfigEntry(domain="unifi", title="UniFi")
    router.add_to_hass(hass)
    registry = dr.async_get(hass)
    for index in range(30):
        registry.async_get_or_create(
            config_entry_id=router.entry_id,
            identifiers={("unifi", f"client-{index}")},
            name=f"Client {index}",
        )

    data = await async_get_config_entry_diagnostics(hass, entry)

    block = data["infrastructure"]["unifi"]
    assert block["device_count"] == 30
    assert len(block["devices"]) == 12


async def test_an_ignored_or_switched_off_entry_says_so(
    hass: HomeAssistant,
):
    """An ignored discovery is an entry that never loads: its source
    says so, as a switched-off entry's disabled state does, so neither
    reads as a second integration that failed."""
    from homeassistant.config_entries import SOURCE_IGNORE, ConfigEntryDisabler

    entry = await setup_entry(hass)
    MockConfigEntry(domain="fritz", title="FRITZ!Box 7590", source="user").add_to_hass(hass)
    MockConfigEntry(domain="fritz", title="FRITZ!Repeater", source=SOURCE_IGNORE).add_to_hass(hass)
    MockConfigEntry(
        domain="fritz", title="Old box", source="zeroconf", disabled_by=ConfigEntryDisabler.USER,
    ).add_to_hass(hass)

    data = await async_get_config_entry_diagnostics(hass, entry)

    block = data["infrastructure"]["fritz"]
    assert block["source"] == ["user", "ignore", "zeroconf"]
    assert block["disabled_by"] == [None, None, "user"]
