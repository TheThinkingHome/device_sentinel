# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_integration_names.py, Version: 0.27.4 (2026-10-25)

"""An integration is named as Home Assistant shows it, never by its id.

The Daily Brief names an integration by its name, and the brief's
wording is the standard wherever surfaces disagree (James, 25 October
2026, rule GEN-07). Until 0.27.4 every mute text read
"integration: zwave_js" and classification.md wrote the id in its
INTEGRATION column, while the set-aside reason already used the name.

The test integration's id is "test"; its name is patched to "Test Hub"
so the two differ, as mqtt and MQTT do on a real house.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_FREEZE_MUTED_INTEGRATIONS,
    CONF_MUTED_INTEGRATIONS,
)

from tests.helpers import register_device, setup_coordinator


def _title(self, domain):
    return "Test Hub" if domain == "test" else domain


def _row(coord, name):
    return next(row for row in coord.classification_rows() if row["name"] == name)


async def _md_line(hass, coord, name):
    await hass.async_add_executor_job(coord._write_reports, "manual")
    with open(hass.config.path("device_sentinel/classification.md"), encoding="utf-8") as handle:
        return next(line for line in handle.read().splitlines() if line.startswith(f"| {name} |"))


async def test_a_global_integration_mute_names_the_integration(hass: HomeAssistant, monkeypatch):
    device, _ = register_device(hass, "a", name="Alpha Plug")
    coord = await setup_coordinator(hass, {CONF_MUTED_INTEGRATIONS: ["test"]})
    monkeypatch.setattr(type(coord), "_integration_title", _title)
    assert _row(coord, "Alpha Plug")["muted"] == "Global (integration: Test Hub)"
    # The device page and the Devices tab use the same words.
    assert coord.mute_text(device.id) == "Global (integration: Test Hub)"
    dev = next(r for r in coord.dashboard_devices() if r["name"] == "Alpha Plug")
    assert dev["muted"] == "Global (integration: Test Hub)"


async def test_a_family_integration_mute_names_the_integration(hass: HomeAssistant, monkeypatch):
    register_device(hass, "b", name="Bravo Plug")
    coord = await setup_coordinator(hass, {CONF_FREEZE_MUTED_INTEGRATIONS: ["test"]})
    monkeypatch.setattr(type(coord), "_integration_title", _title)
    assert _row(coord, "Bravo Plug")["muted"] == "freeze (integration: Test Hub)"


async def test_the_set_aside_reason_still_uses_the_name(hass: HomeAssistant, monkeypatch):
    register_device(hass, "c", name="Charlie TV")
    coord = await setup_coordinator(hass, {CONF_EXCLUDED_INTEGRATIONS: ["test"]})
    monkeypatch.setattr(type(coord), "_integration_title", _title)
    assert _row(coord, "Charlie TV")["set_aside"] == "excluded (integration: Test Hub)"


async def test_classification_md_writes_the_name(hass: HomeAssistant, monkeypatch):
    register_device(hass, "d", name="Delta Plug")
    coord = await setup_coordinator(hass)
    monkeypatch.setattr(type(coord), "_integration_title", _title)
    row = _row(coord, "Delta Plug")
    # The id stays in the row, for the tab's link to the integration.
    assert row["integration"] == "test"
    assert row["integration_name"] == "Test Hub"
    line = await _md_line(hass, coord, "Delta Plug")
    assert line.startswith("| Delta Plug | Test Hub |"), line


async def test_classification_md_names_a_muted_integration(hass: HomeAssistant, monkeypatch):
    register_device(hass, "e", name="Echo Plug")
    coord = await setup_coordinator(hass, {CONF_MUTED_INTEGRATIONS: ["test"]})
    monkeypatch.setattr(type(coord), "_integration_title", _title)
    line = await _md_line(hass, coord, "Echo Plug")
    assert "| Global (integration: Test Hub) |" in line, line
    assert "integration: test" not in line, line
