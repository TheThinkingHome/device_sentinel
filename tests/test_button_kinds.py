# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_button_kinds.py, Version: 0.27.9 (2026-10-27)

"""Each button names its own kind (rule REL-16): the kind is the
button's key, not the retired Enable buttons' "enable_assist"."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from tests.helpers import setup_entry


async def test_each_button_names_its_kind(hass: HomeAssistant):
    await setup_entry(hass)
    await hass.async_block_till_done()
    buttons = [s for s in hass.states.async_all("button") if s.entity_id.startswith("button.device_sentinel")]
    kinds = {s.attributes.get("sentinel_type") for s in buttons}
    assert len(buttons) == 2
    assert "enable_assist" not in kinds
    assert len(kinds) == 2
    assert all(s.attributes.get("sentinel_version") for s in buttons)
