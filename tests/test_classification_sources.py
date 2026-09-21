# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_classification_sources.py, Version: 0.22.13 (2026-09-21)

"""Classification says why: the source of every mute and exclusion.

From the second fleet's review of the dashboard. The MUTED cell named
only the level of a global mute, "Global (label)", never which label;
the battery, signal and freeze mutes did not appear at all; and an
excluded device read "excluded" without saying what was excluded.

Ruled 21 September 2026: name the source in the cell, show every
family mute in the same cell broadest first, and put a key under the
table for the set-aside reasons. The tab and classification.md are
built by one function, so each assertion is made on both.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, label_registry as lr

from custom_components.device_sentinel.const import (
    CONF_BATTERY_MUTED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_FREEZE_MUTED_INTEGRATIONS,
    CONF_MUTED_DEVICES,
    CONF_MUTED_INTEGRATIONS,
    CONF_MUTED_LABELS,
    CONF_SIGNAL_MUTED_LABELS,
    SET_ASIDE_MEANINGS,
)

from tests.helpers import register_device, setup_coordinator


def _label(hass: HomeAssistant, device, name: str) -> str:
    """Create a label, put it on the device, return its id."""
    label = lr.async_get(hass).async_create(name)
    dr.async_get(hass).async_update_device(device.id, labels={label.label_id})
    return label.label_id


def _row(coord, name: str) -> dict:
    return next(row for row in coord.classification_rows() if row["name"] == name)


def _md(hass: HomeAssistant) -> str:
    with open(hass.config.path("device_sentinel/classification.md"), encoding="utf-8") as handle:
        return handle.read()


def _md_row(hass: HomeAssistant, name: str) -> str:
    return next(line for line in _md(hass).splitlines() if line.startswith(f"| {name} |"))


async def _write(hass: HomeAssistant, coord) -> None:
    await hass.async_add_executor_job(coord._write_reports, "manual")


async def test_a_global_mute_by_integration_names_the_integration(hass: HomeAssistant):
    register_device(hass, "a", name="Alpha Plug")
    coord = await setup_coordinator(hass, {CONF_MUTED_INTEGRATIONS: ["test"]})
    assert _row(coord, "Alpha Plug")["muted"] == "Global (integration: test)"


async def test_a_global_mute_by_label_names_the_label(hass: HomeAssistant):
    device, _ = register_device(hass, "b", name="Bravo Plug")
    label_id = _label(hass, device, "Garage spares")
    coord = await setup_coordinator(hass, {CONF_MUTED_LABELS: [label_id]})
    assert _row(coord, "Bravo Plug")["muted"] == "Global (label: Garage spares)"


async def test_a_global_mute_by_device_needs_no_source(hass: HomeAssistant):
    device, _ = register_device(hass, "c", name="Charlie Plug")
    coord = await setup_coordinator(hass, {CONF_MUTED_DEVICES: [device.id]})
    assert _row(coord, "Charlie Plug")["muted"] == "Global (device)"


async def test_a_family_mute_shows_in_the_same_cell(hass: HomeAssistant):
    """A battery mute alone was invisible on the tab: an empty cell."""
    device, _ = register_device(hass, "d", name="Delta Phone")
    coord = await setup_coordinator(hass, {CONF_BATTERY_MUTED_DEVICES: [device.id]})
    assert _row(coord, "Delta Phone")["muted"] == "battery (device)"


async def test_every_mute_broadest_first_each_with_its_source(hass: HomeAssistant):
    device, _ = register_device(hass, "e", name="Echo Sensor")
    label_id = _label(hass, device, "Noisy links")
    coord = await setup_coordinator(hass, {
        CONF_MUTED_DEVICES: [device.id],
        CONF_BATTERY_MUTED_DEVICES: [device.id],
        CONF_SIGNAL_MUTED_LABELS: [label_id],
        CONF_FREEZE_MUTED_INTEGRATIONS: ["test"],
    })
    assert _row(coord, "Echo Sensor")["muted"] == (
        "Global (device); battery (device); signal (label: Noisy links); "
        "freeze (integration: test)"
    )


async def test_an_unmuted_device_has_an_empty_cell(hass: HomeAssistant):
    register_device(hass, "f", name="Foxtrot Plug")
    coord = await setup_coordinator(hass)
    assert _row(coord, "Foxtrot Plug")["muted"] == ""


async def test_an_exclusion_names_the_integration(hass: HomeAssistant):
    register_device(hass, "g", name="Golf TV")
    coord = await setup_coordinator(hass, {CONF_EXCLUDED_INTEGRATIONS: ["test"]})
    row = _row(coord, "Golf TV")
    assert row["watched"] is False
    assert row["set_aside"] == "excluded (integration: test)"


async def test_the_report_carries_the_same_cells(hass: HomeAssistant):
    """One builder behind the tab and the file, so they never disagree."""
    device, _ = register_device(hass, "h", name="Hotel Panel")
    coord = await setup_coordinator(hass, {
        CONF_MUTED_DEVICES: [device.id],
        CONF_BATTERY_MUTED_DEVICES: [device.id],
    })
    await _write(hass, coord)
    assert "| Global (device); battery (device) |" in _md_row(hass, "Hotel Panel")


async def test_the_report_names_an_exclusion_too(hass: HomeAssistant):
    register_device(hass, "i", name="India TV")
    coord = await setup_coordinator(hass, {CONF_EXCLUDED_INTEGRATIONS: ["test"]})
    await _write(hass, coord)
    assert "excluded (integration: test)" in _md_row(hass, "India TV")


async def test_the_integrations_tab_counts_only_global_mutes(hass: HomeAssistant):
    """A battery-only mute is not the integration's device muted.

    The Integrations tab counted a device as muted when its row's
    cell was not empty. The family mutes now fill that cell, and a
    phone muted for battery alone must not read as a muted device.
    """
    device, _ = register_device(hass, "j", name="Juliet Phone")
    coord = await setup_coordinator(hass, {CONF_BATTERY_MUTED_DEVICES: [device.id]})
    counts = next(row for row in coord.dashboard_integrations() if row["domain"] == "test")
    assert counts["muted"] == 0


async def test_the_integration_page_shows_only_the_global_mute(hass: HomeAssistant):
    device, _ = register_device(hass, "k", name="Kilo Panel")
    coord = await setup_coordinator(hass, {
        CONF_MUTED_DEVICES: [device.id],
        CONF_BATTERY_MUTED_DEVICES: [device.id],
    })
    page = coord.dashboard_integration("test")
    listed = next(d for d in page["devices"] if d["name"] == "Kilo Panel")
    assert listed["muted"] == "Global (device)"


async def test_the_report_keys_every_set_aside_reason(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    await _write(hass, coord)
    text = _md(hass)
    for reason, meaning in SET_ASIDE_MEANINGS:
        assert f"- {reason}: {meaning}" in text
    assert [reason for reason, _ in SET_ASIDE_MEANINGS] == [
        "excluded", "service", "disabled", "duplicate coordinator", "no entities",
    ]


async def test_the_summary_names_all_five_reasons_and_not_deviceless(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    await _write(hass, coord)
    text = _md(hass)
    assert "duplicate coordinators" in text
    assert "deviceless" not in text
    assert "entity level" not in text


async def test_the_tab_receives_the_same_key(hass: HomeAssistant, hass_ws_client):
    await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "device_sentinel/classification"})
    reply = await client.receive_json()
    assert reply["result"]["set_aside_meanings"] == [
        [reason, meaning] for reason, meaning in SET_ASIDE_MEANINGS
    ]


async def test_the_disabled_entities_advice_points_to_the_dashboard(hass: HomeAssistant):
    """The Enable buttons are at the top of the dashboard now.

    The advice sent a person to the Device Sentinel device page, while
    the reader of this line is already on the dashboard, where the
    same three buttons sit in the top row.
    """
    coord = await setup_coordinator(hass)
    coord.awaiting_enable_counts = lambda: {"battery": 1, "signal": 0, "last_seen": 0}
    line = next(
        item for item in coord._recommendation_items()
        if "disabled: Device Sentinel requires" in item
    )
    assert "Enable buttons at the top of the Device Sentinel dashboard" in line
    assert "device page" not in line


async def test_a_renamed_label_is_named_by_its_new_name(hass: HomeAssistant):
    """Renaming a label moves nothing in the device or entity registry.

    Without a listener on the label registry the cell kept the old
    name until something else happened to rebuild the view.
    """
    device, _ = register_device(hass, "l", name="Lima Plug")
    label_id = _label(hass, device, "Garage spares")
    coord = await setup_coordinator(hass, {CONF_MUTED_LABELS: [label_id]})
    lr.async_get(hass).async_update(label_id, name="Shed spares")
    await hass.async_block_till_done()
    assert _row(coord, "Lima Plug")["muted"] == "Global (label: Shed spares)"
