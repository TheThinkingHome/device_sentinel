"""Step 1 backbone tests for Device Sentinel."""

from unittest.mock import patch

import json
import pathlib

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "device_sentinel"
STORAGE_KEY = f"{DOMAIN}.storage"
MANIFEST_VERSION = json.loads(
    (
        pathlib.Path(__file__).parent.parent
        / "custom_components/device_sentinel/manifest.json"
    ).read_text()
)["version"]


async def test_flow_creates_entry_with_zero_questions(hass: HomeAssistant):
    """Opening the flow creates the entry immediately, no form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Device Sentinel"
    assert result["data"] == {}


async def test_second_instance_refused(hass: HomeAssistant):
    """single_config_entry makes HA refuse a second entry."""
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_setup_creates_status_sensor(hass: HomeAssistant):
    """Setup produces the status sensor with state 1 and identity attrs."""
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.device_sentinel_status")
    assert state is not None
    assert state.state == "1"
    assert state.attributes["sentinel_type"] == "status"
    assert state.attributes["sentinel_version"] == MANIFEST_VERSION
    assert state.attributes["storage_healthy"] is True
    assert state.attributes["first_installed"] is not None


async def test_restart_increments_count_and_keeps_first_installed(
    hass: HomeAssistant, hass_storage
):
    """Reload simulates a restart: count ticks up, first_installed holds."""
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    first = hass.states.get("sensor.device_sentinel_status").attributes[
        "first_installed"
    ]
    assert hass_storage[STORAGE_KEY]["data"]["setup_count"] == 1

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.device_sentinel_status")
    assert state.state == "2"
    assert state.attributes["first_installed"] == first
    assert hass_storage[STORAGE_KEY]["data"]["setup_count"] == 2
    assert hass_storage[STORAGE_KEY]["data"]["first_installed"] == first
    assert hass_storage[STORAGE_KEY]["data"]["devices"] == {}


async def test_unload_cleans_up(hass: HomeAssistant):
    """Unload removes the platform cleanly."""
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.device_sentinel_status")
    assert state.state == "unavailable"
