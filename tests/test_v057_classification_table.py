# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v057_classification_table.py, Version: 0.5.7 (2026-07-21)

"""0.5.7 tests: the classification report is one combined table.

One row per device, watched and set-aside together, alphabetical. A
watched device carries a WATCHED check; a service device carries a
SET ASIDE check; a globally excluded device keeps its WATCHED check
and names why in the EXCLUDED column (Global (integration/label/
device)). Section excludes are not shown here.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import CONF_EXCLUDED_DEVICES

DOMAIN = "device_sentinel"


def _device(hass, uid, name):
    src = MockConfigEntry(domain="test", title="Source")
    src.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=src.entry_id,
        identifiers={("test", uid)},
        name=name,
    )


async def _coordinator(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={}, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _class_rows(hass):
    text = open(
        hass.config.path("device_sentinel/classification.md")
    ).read()
    return [
        line
        for line in text.splitlines()
        if line.startswith("| ") and "---" not in line and "DEVICE |" not in line
    ]


async def test_one_table_three_states(hass: HomeAssistant):
    """A watched device, a globally excluded device, and a service
    device each read correctly in one table."""
    _device(hass, "w", "Bravo Watched")
    excluded = _device(hass, "e", "Alpha Excluded")
    coord = await _coordinator(
        hass, options={CONF_EXCLUDED_DEVICES: [excluded.id]}
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
    d = _device(hass, "x", "Label Excluded")
    coord = await _coordinator(hass)
    coord._excluded_devices[d.id] = "label"
    await hass.async_add_executor_job(coord._write_reports, "manual")
    row = next(r for r in _class_rows(hass) if "Label Excluded" in r)
    assert "Global (label)" in row
