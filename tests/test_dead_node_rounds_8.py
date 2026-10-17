# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_dead_node_rounds_8.py, Version: 0.26.5 (2026-10-16)

"""The eighth adversarial round on 0.26.5 (whole-release closing pass).

Finding 1 (wording, house with no Z-Wave): strings.json and
translations/en.json add two fixed sentences about the Z-Wave status
sensor to both steps of the entities_disabled Repairs dialog. They are
literal text, not a placeholder, so a Zigbee, ESPHome or Wi-Fi house
whose card is raised for a disabled battery entity now reads "A Z-Wave
device also needs its Z-Wave status sensor ..." and "Enable Last Seen
also turns on the Z-Wave status sensors", which 0.26.4 never said. The
brief's own sentence (report_brief.py, the "Enable Last Seen also turns
on the Z-Wave status" tail) is conditional on counts["node_status"];
the card is not.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from custom_components.device_sentinel.const import (
    DOMAIN,
    REPAIR_ENTITIES_DISABLED,
    REPAIR_MOMENT_GRACE,
)

from tests.helpers import register_device, setup_entry

_COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "device_sentinel"


def _steps(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    steps = data["issues"][REPAIR_ENTITIES_DISABLED]["fix_flow"]["step"]
    return {name: step["description"] for name, step in steps.items()}


async def test_a_house_with_no_z_wave_is_not_told_about_z_wave_status_on_the_repairs_card(
    hass: HomeAssistant,
):
    _, entity_ids = register_device(hass, "zb", name="Hall Motion")
    registry = er.async_get(hass)
    for entity_id in entity_ids:
        registry.async_update_entity(
            entity_id,
            device_class="battery",
            disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        )
        registry.async_update_entity(entity_id, unit_of_measurement="%")
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    coordinator._rebuild_registry_view()
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, REPAIR_ENTITIES_DISABLED)
    assert issue is not None
    placeholders = dict(issue.translation_placeholders or {})
    assert coordinator.awaiting_enable_counts().get("node_status", 0) == 0
    for source in (_COMPONENT / "strings.json", _COMPONENT / "translations" / "en.json"):
        for step, description in _steps(source).items():
            shown = description.format(**placeholders)
            assert "Z-Wave" not in shown, (source.name, step, shown)


async def test_a_z_wave_house_with_a_status_sensor_off_is_told_on_the_repairs_card(
    hass: HomeAssistant, freezer
):
    from .test_zwave_dead_node import _house

    coordinator, _device, _ids, _record = await _house(hass, freezer, status_on=False)
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, REPAIR_ENTITIES_DISABLED)
    assert issue is not None
    placeholders = dict(issue.translation_placeholders or {})
    for source in (_COMPONENT / "strings.json", _COMPONENT / "translations" / "en.json"):
        for step, description in _steps(source).items():
            shown = description.format(**placeholders)
            assert "also needs its Z-Wave status sensor" in shown, (source.name, step)
            assert "Enable Last Seen also turns on the Z-Wave status sensors." in shown, shown
