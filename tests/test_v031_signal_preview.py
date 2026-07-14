"""0.3.1 tests: the signal floor and danger-line preview."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import DEV_SIGNAL_DAILY_MIN
from custom_components.device_sentinel.coordinator import (
    DeviceSentinelCoordinator as C,
)

DOMAIN = "device_sentinel"


def test_trimmed_minimum_rule():
    # Below threshold: plain minimum, nothing trimmed.
    assert C._trimmed_minimum([120.0, 40.0]) == 40.0
    # At threshold: the single bad day is set aside.
    week = [120.0, 118.0, 40.0, 122.0, 119.0, 121.0, 117.0]
    assert C._trimmed_minimum(week) == 117.0
    # A recurring drop counts: one copy trimmed, the second rules.
    week = [120.0, 40.0, 41.0, 122.0, 119.0, 121.0, 117.0]
    assert C._trimmed_minimum(week) == 41.0
    assert C._trimmed_minimum([]) is None


def test_family_and_danger():
    family, danger = C._signal_family_and_danger(120.0)
    assert family == "LQI" and danger == 60.0
    family, danger = C._signal_family_and_danger(-70.0)
    assert family == "RSSI" and danger == -80.0


async def test_preview_in_report(hass: HomeAssistant):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "sig31")},
        name="Signal Preview Device",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "sig31",
        suggested_object_id="sig31_linkquality",
        device_id=device.id, config_entry=source,
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data

    # Six signal days: preview must stay blank (arming floor is 7).
    coord.data["devices"][device.id][DEV_SIGNAL_DAILY_MIN] = [
        120.0, 118.0, 122.0, 119.0, 121.0, 117.0,
    ]
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    row = next(l for l in text.splitlines() if "Signal Preview Device" in l)
    assert row.rstrip().endswith("| - | - | - |")

    # Seventh day with one anomaly: floor trims it, danger = floor/2.
    coord.data["devices"][device.id][DEV_SIGNAL_DAILY_MIN].append(40.0)
    await hass.async_add_executor_job(coord._write_reports)
    text = open(
        hass.config.path("device_sentinel/device_telemetry.md")
    ).read()
    row = next(l for l in text.splitlines() if "Signal Preview Device" in l)
    assert "| 117 | LQI | 58.5 |" in row
