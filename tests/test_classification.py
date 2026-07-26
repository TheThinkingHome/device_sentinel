# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_classification.py, Version: 0.9.9 (2026-07-26)

"""How devices are counted and attributed to integrations.

Every registry device is sorted into watched or set aside, and a
device that belongs to more than one config entry is attributed to its
primary one, so a camera also seen by a router tracker counts once,
under the camera. The classification report renders one combined table,
one row per device, watched and set-aside together and alphabetical,
where a globally excluded device keeps its watched check and names the
tier it was excluded at. This file holds that classification behaviour
and the combined table.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import CONF_EXCLUDED_DEVICES

from tests.helpers import setup_coordinator


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

    coord = await setup_coordinator(hass)
    breakdown = coord.classification_breakdown
    assert breakdown.get("camera_brand", {}).get("watched", 0) == 1
    assert breakdown.get("router_tracker", {}).get("watched", 0) == 0


# ==================================================================
# The classification report is one combined table.
# ==================================================================

def _class_device(hass, uid, name):
    src = MockConfigEntry(domain="test", title="Source")
    src.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=src.entry_id,
        identifiers={("test", uid)},
        name=name,
    )


def _class_rows(hass):
    text = open(
        hass.config.path("device_sentinel/diagnostics/classification.md")
    ).read()
    return [
        line
        for line in text.splitlines()
        if line.startswith("| ") and "---" not in line and "DEVICE |" not in line
    ]


async def test_one_table_three_states(hass: HomeAssistant):
    """A watched device, a globally excluded device, and a service
    device each read correctly in one table."""
    _class_device(hass, "w", "Bravo Watched")
    excluded = _class_device(hass, "e", "Alpha Excluded")
    coord = await setup_coordinator(
        hass, {CONF_EXCLUDED_DEVICES: [excluded.id]}
    )
    coord._excluded_devices[excluded.id] = "integration"
    await hass.async_add_executor_job(coord._write_reports, "manual")
    rows = _class_rows(hass)
    text = "\n".join(rows)

    # Excluded device: watched check kept, reason named.
    excl_row = next(r for r in rows if "Alpha Excluded" in r)
    assert "\u2713" in excl_row
    assert "Global (integration)" in excl_row

    # Watched device: watched check, no exclusion.
    w_row = next(r for r in rows if "Bravo Watched" in r)
    assert "\u2713" in w_row
    assert "Global" not in w_row

    # A service device is set aside, no watched check.
    service_row = next(r for r in rows if "Device Sentinel" in r)
    assert "\u2713" in service_row  # in the SET ASIDE column

    # Alphabetical: Alpha before Bravo.
    assert text.index("Alpha Excluded") < text.index("Bravo Watched")


async def test_global_reason_wording(hass: HomeAssistant):
    """The EXCLUDED cell names the tier: Global (label), (device)."""
    d = _class_device(hass, "x", "Label Excluded")
    coord = await setup_coordinator(hass)
    coord._excluded_devices[d.id] = "label"
    await hass.async_add_executor_job(coord._write_reports, "manual")
    row = next(r for r in _class_rows(hass) if "Label Excluded" in r)
    assert "Global (label)" in row
