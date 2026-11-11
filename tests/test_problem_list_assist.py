# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_problem_list_assist.py, Version: 0.28.11 (2026-11-10)

"""The Problem List is hidden from Assist until a person shows it
(rule LIST-14).

Home Assistant shows a to-do list to Assist by default, and with it any
conversation agent, an AI one included, which could read the house's
problems and mark an item done, taking it off the card and out of the
alerts. It is hidden once, the first time the list is set up, and a
person who shows it keeps that choice.
"""

from __future__ import annotations

from homeassistant.components.homeassistant.exposed_entities import (
    KNOWN_ASSISTANTS,
    async_expose_entity,
    async_should_expose,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.device_sentinel.const import DOMAIN

from .helpers import setup_entry
from .test_history_file import restart_with


def _todo(hass: HomeAssistant) -> str:
    return next(
        entry.entity_id for entry in er.async_get(hass).entities.values()
        if entry.platform == DOMAIN and entry.domain == "todo"
    )


async def test_the_list_is_hidden_from_every_assistant(hass: HomeAssistant):
    assert await async_setup_component(hass, "homeassistant", {})
    await setup_entry(hass)
    entity_id = _todo(hass)
    for assistant in KNOWN_ASSISTANTS:
        assert async_should_expose(hass, assistant, entity_id) is False, assistant


async def test_a_person_who_shows_it_keeps_that_choice(hass: HomeAssistant):
    assert await async_setup_component(hass, "homeassistant", {})
    entry = await setup_entry(hass)
    entity_id = _todo(hass)
    async_expose_entity(hass, "conversation", entity_id, True)
    await restart_with(hass, entry)
    assert async_should_expose(hass, "conversation", entity_id) is True


async def test_shown_before_the_upgrade_it_is_hidden_once(hass: HomeAssistant):
    """A house that showed it on an older release has it hidden at the
    upgrade, once: from then on the person's choice stands."""
    assert await async_setup_component(hass, "homeassistant", {})
    entry = await setup_entry(hass)
    entity_id = _todo(hass)
    registry = er.async_get(hass)
    # As an older release left it: shown, and no mark of ours.
    registry.async_update_entity_options(entity_id, DOMAIN, {})
    async_expose_entity(hass, "conversation", entity_id, True)
    await restart_with(hass, entry)
    assert async_should_expose(hass, "conversation", entity_id) is False


async def test_without_the_exposure_settings_it_waits_for_the_next_start(hass: HomeAssistant):
    entry = await setup_entry(hass)
    entity_id = _todo(hass)
    assert not (er.async_get(hass).async_get(entity_id).options.get(DOMAIN) or {}).get("assist_hidden")
    assert await async_setup_component(hass, "homeassistant", {})
    await restart_with(hass, entry)
    assert async_should_expose(hass, "conversation", entity_id) is False
