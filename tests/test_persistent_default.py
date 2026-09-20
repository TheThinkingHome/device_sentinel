# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_persistent_default.py, Version: 0.22.5 (2026-09-20)

"""A new install starts with the persistent card off (ruling #462).

The dashboard now shows what the card showed. An install from before
this release that never saved the setting was running with the card
on, so the options migration writes that down rather than letting the
new default switch it off. An install that saved the setting keeps it.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_PERSISTENT_ENABLED,
    DEFAULT_PERSISTENT_ENABLED,
    DOMAIN,
    OPTIONS_MINOR_VERSION,
)


async def _entry(hass: HomeAssistant, options: dict, minor_version: int) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={}, options=options,
        version=1, minor_version=minor_version,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_the_default_is_off(hass: HomeAssistant):
    assert DEFAULT_PERSISTENT_ENABLED is False
    assert OPTIONS_MINOR_VERSION == 5


async def test_a_new_install_starts_with_the_card_off(hass: HomeAssistant):
    entry = await _entry(hass, {}, OPTIONS_MINOR_VERSION)
    assert CONF_PERSISTENT_ENABLED not in entry.options
    assert entry.options.get(CONF_PERSISTENT_ENABLED, DEFAULT_PERSISTENT_ENABLED) is False


async def test_an_older_install_that_never_saved_it_keeps_the_card(hass: HomeAssistant):
    entry = await _entry(hass, {}, 4)
    assert entry.options[CONF_PERSISTENT_ENABLED] is True
    assert entry.minor_version == OPTIONS_MINOR_VERSION


async def test_an_older_install_that_turned_it_off_keeps_it_off(hass: HomeAssistant):
    entry = await _entry(hass, {CONF_PERSISTENT_ENABLED: False}, 4)
    assert entry.options[CONF_PERSISTENT_ENABLED] is False


async def test_an_older_install_that_turned_it_on_keeps_it_on(hass: HomeAssistant):
    entry = await _entry(hass, {CONF_PERSISTENT_ENABLED: True}, 4)
    assert entry.options[CONF_PERSISTENT_ENABLED] is True


async def test_an_install_from_long_ago_takes_every_step(hass: HomeAssistant):
    entry = await _entry(hass, {}, 1)
    assert entry.options[CONF_PERSISTENT_ENABLED] is True
    assert entry.minor_version == OPTIONS_MINOR_VERSION
