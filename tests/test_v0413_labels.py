# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v0413_labels.py, Version: 0.4.13 (2026-07-27)

"""0.4.13 tests: the sensitivity slider renders as a word in the
report header, across its whole band.

The header used to show the slider as K, which collided with the trim
depth the same report calls k. Each slider value now maps to a word.
"""

import pytest

from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import CONF_SIGNAL_SENSITIVITY

DOMAIN = "device_sentinel"


async def _coord(hass, sensitivity):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Device Sentinel",
        data={},
        options={CONF_SIGNAL_SENSITIVITY: sensitivity},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


@pytest.mark.parametrize(
    "value,word",
    [
        (-2, "Calm"),
        (-1, "Stable"),
        (0, "Normal"),
        (1, "Watchful"),
        (2, "Sensitive"),
    ],
)
async def test_slider_renders_as_a_word(
    hass: HomeAssistant, value: int, word: str
):
    """Each slider value shows its word in the SIGNAL header."""
    coord = await _coord(hass, value)
    assert coord._signal_slider_label() == word


async def test_out_of_band_slider_falls_back_to_normal(hass: HomeAssistant):
    """A slider value outside the band clamps, so its word is a real
    one, never blank."""
    coord = await _coord(hass, 99)
    assert coord._signal_slider_label() == "Sensitive"
