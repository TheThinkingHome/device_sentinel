# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_names_hidden.py, Version: 0.28.12 (2026-11-11)

"""Names that must not reach the diagnostics download
(rule STOR-21: the house's Wi-Fi networks are named by stand-ins, and an
integration entry is named by its domain and a number, not its title).

1. UniFi registers each Wi-Fi network (WLAN) as a device whose name is
   the network's name (homeassistant/components/unifi/entity.py,
   async_wlan_device_info_fn: name=wlan.name, model "UniFi WLAN").
   diagnostics._infrastructure lists the unifi entry's devices by name,
   on every house, with no opt-in. The stand-ins only cover networks in
   Settings or heard by the host's scan, which most houses never set, so
   the SSID goes out whole.

2. Tado's entry title is the Tado home's name (tado/config_flow.py:
   title=home["name"]), often a family name or a street address. The
   Tado study (new in 0.28.x) puts entry.title into the download under
   classification.study.tado[].entry, the one place an entry title is
   still printed.

Asserts the safe behaviour.
"""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_STUDY_HARDWARE,
    STUDIABLE,
    TADO_KEY,
)
from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)

from tests.helpers import setup_entry

OWN_SSID = "Lander Family 5G"
HOME_NAME = "14 Calle Bolivar"


async def test_a_unifi_wlan_device_does_not_carry_the_ssid_into_the_download(
    hass: HomeAssistant,
):
    entry = await setup_entry(hass)
    unifi = MockConfigEntry(domain="unifi", title="UniFi Network")
    unifi.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=unifi.entry_id,
        identifiers={("unifi", "5f1c0aa1b2c3d4e5f6a7b8c9")},
        entry_type=dr.DeviceEntryType.SERVICE,
        manufacturer="Ubiquiti Networks",
        model="UniFi WLAN",
        name=OWN_SSID,
    )
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert "unifi" in data["infrastructure"]  # precondition: listed
    assert OWN_SSID not in json.dumps(data, default=str)


async def test_the_tado_study_does_not_print_the_tado_home_name(
    hass: HomeAssistant,
):
    tado = MockConfigEntry(domain="tado", title=HOME_NAME)
    tado.add_to_hass(hass)
    tado.mock_state(hass, ConfigEntryState.LOADED)
    tado.runtime_data = SimpleNamespace(
        last_update_success=True,
        update_interval=timedelta(minutes=5),
        data={"device": {}, "rate_limit": {"granted": 20000, "remaining": 19000}},
    )
    entry = await setup_entry(hass, {CONF_STUDY_HARDWARE: [STUDIABLE[TADO_KEY]]})
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert "tado" in json.dumps(data["classification"]["study"])  # precondition
    assert HOME_NAME not in json.dumps(data, default=str)
