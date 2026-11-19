# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_share_names.py, Version: 0.29.8 (2026-11-19)

"""Share Names in Diagnostics (rule STOR-21).

On, the default: the download carries the house's device, entity, area
and label names as Home Assistant names them. Off: each is a stand-in,
such as Device 12. Either way, Wi-Fi network names and router trackers
are stand-ins, addresses never appear, the download carries no key, and
the key is written to the reports folder with every name in it.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import label_registry as lr

from custom_components.device_sentinel.const import (
    CONF_SHARE_NAMES,
    CONF_WIFI_NETWORKS,
    REPORT_DIR,
)
from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics
from custom_components.device_sentinel.stand_ins import KEY_FILE

from tests.helpers import register_device, setup_entry, share_names_off

OWN_SSID = "Lander Family 5G"


async def _house(hass: HomeAssistant, options: dict | None = None):
    terrace = ar.async_get(hass).async_create("Terrace")
    spare = lr.async_get(hass).async_create("Spare Parts")
    door, (door_entity,) = register_device(hass, "door", "Terrace Door")
    lamp, _ = register_device(hass, "lamp", "Lamp Of Janet")
    dr.async_get(hass).async_update_device(door.id, area_id=terrace.id, labels={spare.label_id})
    # A muting label is named in the settings the download carries.
    entry = await setup_entry(
        hass, {CONF_WIFI_NETWORKS: [OWN_SSID], "muted_labels": [spare.label_id], **(options or {})}
    )
    entry.runtime_data._rebuild_registry_view()
    return entry, door, lamp, door_entity, spare


def _key_file(hass: HomeAssistant) -> str:
    return Path(hass.config.path(REPORT_DIR, KEY_FILE)).read_text(encoding="utf-8")


async def test_names_are_shared_by_default(hass: HomeAssistant):
    entry, door, lamp, door_entity, spare = await _house(hass)
    download = await async_get_config_entry_diagnostics(hass, entry)
    assert download["devices"][door.id]["name"] == "Terrace Door"
    assert download["devices"][door.id]["area"] == "Terrace"
    assert download["devices"][lamp.id]["name"] == "Lamp Of Janet"
    assert download["entry_options"]["muted_labels"] == [spare.label_id]
    ids = {row["entity_id"] for row in download["devices"][door.id]["all_entities"]}
    assert door_entity in ids
    # No key travels in the download.
    assert "key" not in download and "read_me" not in download


async def test_wifi_names_are_stand_ins_even_when_names_are_shared(hass: HomeAssistant):
    entry, *_ = await _house(hass)
    text = json.dumps(await async_get_config_entry_diagnostics(hass, entry), ensure_ascii=False)
    assert OWN_SSID not in text
    assert "SSID-01" in text


async def test_turned_off_each_name_is_a_stand_in(hass: HomeAssistant):
    entry, door, lamp, door_entity, spare = await _house(hass, {CONF_SHARE_NAMES: False})
    download = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(download, ensure_ascii=False)
    for name in ("Terrace Door", "Lamp Of Janet", "Terrace", "Spare Parts", OWN_SSID, "terrace_door", "lamp_of_janet"):
        assert name not in text, name
    assert download["devices"][door.id]["name"].startswith("Device ")
    assert download["devices"][door.id]["area"] == "Area 1"


async def test_the_key_file_is_written_whole_either_way(hass: HomeAssistant):
    entry, door, lamp, door_entity, spare = await _house(hass)
    shared = await async_get_config_entry_diagnostics(hass, entry)
    key = _key_file(hass)
    assert "| Area 1 | Terrace |" in key
    assert "| Label 1 | Spare Parts |" in key
    assert f"| {OWN_SSID} |" in key
    assert "Share Names in Diagnostics" in key
    assert "never with a public issue" not in key
    # A device keeps its number when the setting changes.
    word = next(line.split("|")[1].strip() for line in key.splitlines() if "| Terrace Door |" in line)
    share_names_off(hass, entry)
    hidden = await async_get_config_entry_diagnostics(hass, entry)
    assert hidden["devices"][door.id]["name"] == word
    assert shared["devices"][door.id]["name"] == "Terrace Door"


async def test_share_names_is_offered_first_on_by_default_and_saved(hass: HomeAssistant):
    entry, *_ = await _house(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "extended"}
    )
    fields = [str(key) for key in result["data_schema"].schema]
    assert fields[0] == CONF_SHARE_NAMES
    assert result["data_schema"]({})[CONF_SHARE_NAMES] is True
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SHARE_NAMES: False, "study_hardware": []}
    )
    assert entry.options[CONF_SHARE_NAMES] is False
