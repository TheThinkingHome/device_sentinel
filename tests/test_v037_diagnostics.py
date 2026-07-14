"""0.3.7 tests: the diagnostics download."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_DEVICES,
    CONF_HIGH_PRIORITY_TARGETS,
    DEV_DAILY_MAX,
)
from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)

DOMAIN = "device_sentinel"


async def test_diagnostics_carry_the_learned_state(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "diag")},
        name="Diag Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "diag", device_id=device.id, config_entry=source
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Device Sentinel",
        data={},
        options={
            CONF_HIGH_PRIORITY_TARGETS: ["notify.mobile_app_private"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data

    # A seven-day history with one spike: the trim must show through.
    coordinator.data["devices"][device.id][DEV_DAILY_MAX] = [
        500.0, 550.0, 600.0, 520.0, 9000.0, 580.0, 560.0,
    ]

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["version"]
    assert result["storage"]["setup_count"] >= 1
    assert result["tunables"]["taint_debounce_seconds"] == 180
    assert result["tunables"]["trim_top_k"] == 1
    assert result["classification"]["watched"] == 1
    assert result["battery"]["low_count"] == 0
    assert result["todo_items"] == []

    entry_device = result["devices"][device.id]
    assert entry_device["name"] == "Diag Device"
    assert entry_device["integration"] == "test"
    assert entry_device["clock_source"] == "recorded"
    assert entry_device["excluded"] is None
    assert entry_device["window_basis"] == 600.0  # spike set aside
    assert entry_device["set_aside_indices"] == [4]

    # Notification targets are the user's own device names: redacted.
    assert (
        result["entry_options"][CONF_HIGH_PRIORITY_TARGETS] == "**REDACTED**"
    )


async def test_diagnostics_report_exclusions(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "diagx")},
        name="Excluded Diag Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "diagx", device_id=device.id, config_entry=source
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Device Sentinel",
        data={},
        options={CONF_EXCLUDED_DEVICES: [device.id]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["devices"][device.id]["excluded"] == "device"
    assert result["classification"]["excluded_devices"] == {
        device.id: "device"
    }
