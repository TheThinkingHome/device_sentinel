"""Diagnostics says what the plumbing is, not only how it behaved.

A report about a coordinator misbehaving could not be matched
against that hardware's documentation, because nothing recorded
what the hardware was. Two additions answer it: identity on every
device record, and one block naming the stacks, the broker and any
router integration the house runs (ruling #398).
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
    registry.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", "sensor-1")},
        name="Fenetre Thomas",
        manufacturer="Third Reality",
        model="3RDS17BZ",
        sw_version="1.0.9",
    )

    data = await async_get_config_entry_diagnostics(hass, entry)

    device = next(
        row
        for row in data["devices"].values()
        if row["name"] == "Fenetre Thomas"
    )
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
    assert block["entries"] == ["FRITZ!Box 7590"]
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
