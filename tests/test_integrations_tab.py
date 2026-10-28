# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_integrations_tab.py, Version: 0.27.11 (2026-10-28)

"""The Integrations tab excludes and mutes whole integrations (rules
MUTE-02, MUTE-03, MUTE-04, MUTE-06, BRIEF-07, DASH-16).

Each press writes the list Settings writes, one row in the brief saying
it came from the Integrations tab. Mute everything settles the ladder
as a Settings save does; unavailable is never muted by integration.
Each row carries what is on, the reason Device Sentinel recommends
excluding it, and what is wrong now.
"""

from __future__ import annotations

import itertools

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_BATTERY_MUTED_INTEGRATIONS,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_FREEZE_MUTED_INTEGRATIONS,
    CONF_MUTED_INTEGRATIONS,
    DATA_SYSTEM_EVENTS,
    DATA_TODO_ITEMS,
    EXCLUSION_OFFER_REASONS,
    EXCLUDE_GROUP_COPIES,
    EXCLUDE_GROUP_REASONS,
    EXCLUDE_GROUP_VIRTUAL,
    SYS_DETAIL,
    SYS_INTEGRATION_PAGE,
    SYS_INTEGRATIONS_TAB,
    SYS_RECOMMENDATIONS_TAB,
    SYS_KIND,
    SYS_OPTIONS_CHANGED,
    SYS_SCOPE,
    TODO_KIND_UNAVAILABLE,
)

from .helpers import register_device, setup_entry

_ids = itertools.count(1)


async def _ws(client, **payload):
    await client.send_json({"id": next(_ids), **payload})
    return await client.receive_json()


def _rows(coord, kind):
    return [row for row in coord.data.get(DATA_SYSTEM_EVENTS) or [] if row[SYS_KIND] == kind]


async def _house(hass, options=None):
    register_device(hass, "keep", "Door Master")
    register_device(hass, "drop", "Old Plug")
    entry = await setup_entry(hass, {CONF_EXCLUDED_INTEGRATIONS: [], **(options or {})})
    return entry, entry.runtime_data


async def test_a_mute_press_writes_the_list_settings_writes(hass: HomeAssistant, hass_ws_client):
    entry, coord = await _house(hass)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/integration_mute", domain="test", kind="freeze", on=True)
    assert reply["success"], reply
    await hass.async_block_till_done()
    assert entry.options[CONF_FREEZE_MUTED_INTEGRATIONS] == ["test"]
    row = next(r for r in coord.dashboard_integrations() if r["domain"] == "test")
    assert row["mutes"] == {"everything": False, "freeze": True, "battery": False, "signal": False}
    events = _rows(coord, SYS_INTEGRATIONS_TAB)
    assert [(r[SYS_SCOPE], r[SYS_DETAIL]) for r in events] == [("test", "muted for freeze")]
    assert _rows(coord, SYS_OPTIONS_CHANGED) == [], "the press also wrote a Settings changed row"
    sentence = coord._system_event_sentence(events[0])
    assert sentence.startswith(f"{coord._integration_title('test')}: muted for freeze, from the Integrations tab, at "), sentence
    # Pressed again, it lifts.
    reply = await _ws(client, type="device_sentinel/integration_mute", domain="test", kind="freeze", on=False)
    await hass.async_block_till_done()
    assert reply["success"] and entry.options[CONF_FREEZE_MUTED_INTEGRATIONS] == []
    assert _rows(coord, SYS_INTEGRATIONS_TAB)[-1][SYS_DETAIL] == "freeze mute lifted"


async def test_a_second_press_undoes_a_press_exactly(hass: HomeAssistant, hass_ws_client):
    """Nothing narrower is cleared by a press, so lifting it, or taking
    an exclusion back, leaves every mute as it was (rule MUTE-03)."""
    entry, coord = await _house(hass, {CONF_BATTERY_MUTED_INTEGRATIONS: ["test"]})
    client = await hass_ws_client(hass)
    for kind in ("everything",):
        assert (await _ws(client, type="device_sentinel/integration_mute", domain="test", kind=kind, on=True))["success"]
        await hass.async_block_till_done()
        assert entry.options[CONF_MUTED_INTEGRATIONS] == ["test"]
        assert entry.options[CONF_BATTERY_MUTED_INTEGRATIONS] == ["test"]
        assert (await _ws(client, type="device_sentinel/integration_mute", domain="test", kind=kind, on=False))["success"]
        await hass.async_block_till_done()
    assert entry.options[CONF_MUTED_INTEGRATIONS] == []
    assert entry.options[CONF_BATTERY_MUTED_INTEGRATIONS] == ["test"]
    for on in (True, False):
        assert (await _ws(client, type="device_sentinel/integration_exclude", domain="test", on=on, source="integrations_tab"))["success"]
        await hass.async_block_till_done()
    assert entry.options[CONF_EXCLUDED_INTEGRATIONS] == []
    assert entry.options[CONF_BATTERY_MUTED_INTEGRATIONS] == ["test"]


async def test_an_excluded_integration_is_not_muted(hass: HomeAssistant, hass_ws_client):
    entry, coord = await _house(hass, {CONF_EXCLUDED_INTEGRATIONS: ["test"]})
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/integration_mute", domain="test", kind="freeze", on=True)
    assert reply["error"]["code"] == "refused"
    assert entry.options.get(CONF_FREEZE_MUTED_INTEGRATIONS, []) == []


async def test_an_answered_recommendation_is_not_repeated(hass: HomeAssistant):
    """Muted for everything, or kept watching with the tick, the tab no
    longer recommends it (rules MUTE-02, REC-03)."""
    entry, coord = await _house(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_MUTED_INTEGRATIONS: ["mobile_app"]})
    await hass.async_block_till_done()
    assert "mobile_app" in coord._exclusion_settled()


async def test_an_exclusion_undone_is_not_an_answer(hass: HomeAssistant):
    """Excluded and taken back, the integration is recommended again on
    both tabs; only the tick answers it (rules MUTE-02, REC-03)."""
    hair = _hair(hass)
    entry, coord = await _house(hass)
    assert _card(coord, "hair") is not None
    for on in (True, False):
        coord.page_set_integration_excluded("hair", on, source="integrations_tab")
        await hass.async_block_till_done()
        coord._rebuild_registry_view()
        if on:
            assert _card(coord, "hair") is None
    assert hair.id in coord._watched
    assert _card(coord, "hair") is not None and not _card(coord, "hair")["acknowledged"]
    row = next(r for r in coord.dashboard_integrations() if r["domain"] == "hair")
    assert row["recommended"] == EXCLUDE_GROUP_REASONS[EXCLUDE_GROUP_VIRTUAL]
    coord.set_recommendation_ack(True, line="offer:hair")
    row = next(r for r in coord.dashboard_integrations() if r["domain"] == "hair")
    assert row["recommended"] is None
    assert _card(coord, "hair")["acknowledged"]


async def test_an_exclusion_from_its_card_says_the_recommendations_tab(hass: HomeAssistant, hass_ws_client):
    _hair(hass)
    entry, coord = await _house(hass)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/integration_exclude", domain="hair", on=True, source="recommendations_tab")
    assert reply["success"], reply
    await hass.async_block_till_done()
    events = _rows(coord, SYS_RECOMMENDATIONS_TAB)
    assert [(r[SYS_SCOPE], r[SYS_DETAIL]) for r in events] == [("hair", "excluded")]
    assert coord._system_event_sentence(events[0]).startswith("hair: excluded, from the Recommendations tab, at ")
    assert not _rows(coord, SYS_INTEGRATION_PAGE)


async def test_unavailable_is_never_muted_by_integration(hass: HomeAssistant, hass_ws_client):
    entry, coord = await _house(hass)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/integration_mute", domain="test", kind="unavailable", on=True)
    assert not reply["success"]
    reply = await _ws(client, type="device_sentinel/integration_mute", domain="nothing_here", kind="freeze", on=True)
    assert reply["error"]["code"] == "not_found"


async def test_an_exclusion_from_the_tab_says_so(hass: HomeAssistant, hass_ws_client):
    entry, coord = await _house(hass)
    client = await hass_ws_client(hass)
    reply = await _ws(client, type="device_sentinel/integration_exclude", domain="test", on=True, source="integrations_tab")
    assert reply["success"], reply
    await hass.async_block_till_done()
    assert entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["test"]
    events = _rows(coord, SYS_INTEGRATIONS_TAB)
    assert [(r[SYS_SCOPE], r[SYS_DETAIL]) for r in events] == [("test", "excluded")]
    row = next(r for r in coord.dashboard_integrations() if r["domain"] == "test")
    assert row["excluded"] is True and row["devices"] == 2 and row["recommended"] is None


async def test_each_row_carries_its_trouble(hass: HomeAssistant):
    entry, coord = await _house(hass)
    keep = next(d for d in coord._watched if coord._device_name(d) == "Door Master")
    coord.data.setdefault(DATA_TODO_ITEMS, []).append({"uid": "x", "device_id": keep, "summary": "Door Master: unavailable",
                             "status": "needs_action", "kinds": {TODO_KIND_UNAVAILABLE: 1.0}})
    row = next(r for r in coord.dashboard_integrations() if r["domain"] == "test")
    assert row["trouble"] == {TODO_KIND_UNAVAILABLE: 1}
    assert row["devices"] == 2 and row["excluded"] is False and row["down_since"] is None


async def test_the_reasons_come_from_one_list(hass: HomeAssistant):
    entry, coord = await _house(hass)
    assert coord.exclusion_reason("unifi") == EXCLUSION_OFFER_REASONS["router"]
    assert coord.exclusion_reason("alexa_media") == EXCLUSION_OFFER_REASONS["alexa_media"]
    assert coord.exclusion_reason("cast") == EXCLUSION_OFFER_REASONS["media"]
    assert coord.exclusion_reason("kodi") == EXCLUSION_OFFER_REASONS["media"]
    assert coord.exclusion_reason("hair") == EXCLUDE_GROUP_REASONS[EXCLUDE_GROUP_VIRTUAL]
    assert coord.exclusion_reason("tank_volume") == EXCLUDE_GROUP_REASONS[EXCLUDE_GROUP_COPIES]
    # A printer is watched: one that goes off is a fault worth telling.
    assert coord.exclusion_reason("brother") is None
    assert coord.exclusion_reason("ipp") is None
    assert coord.exclusion_reason("test") is None


async def test_each_recommended_integration_has_its_own_card(hass: HomeAssistant):
    """One card per integration, the same recommendation the
    Integrations tab shows under its name (rule REC-03)."""
    _hair(hass)
    entry, coord = await _house(hass)
    card = _card(coord, "hair")
    assert card is not None and card["exclude"] == "hair" and card["devices"] == ["Pinguino"]
    assert "because it drives a virtual remote" in card["text"]
    assert not any(line["key"].startswith("library_") for line in coord.recommendation_lines())
    row = next(r for r in coord.dashboard_integrations() if r["domain"] == "hair")
    assert row["recommended"] == EXCLUDE_GROUP_REASONS[EXCLUDE_GROUP_VIRTUAL]


async def test_a_library_line_tick_answers_each_card_it_named(hass: HomeAssistant):
    """A tick given to the line that named hair before each integration
    had a card answers hair's card, and moves onto it at midnight
    (rule REC-03)."""
    _hair(hass)
    entry, coord = await _house(hass)
    coord._acks()["lines"]["library_copies"] = True
    assert _card(coord, "hair")["acknowledged"]
    assert "hair" in coord._exclusion_settled()
    coord.prune_recommendation_acks()
    assert coord._acks()["lines"] == {"offer:hair": True}
    assert _card(coord, "hair")["acknowledged"]


def _hair(hass):
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    source = MockConfigEntry(domain="hair", title="HAIR")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("hair", "pinguino")}, name="Pinguino",
    )
    er.async_get(hass).async_get_or_create("switch", "hair", "pinguino", device_id=device.id, config_entry=source)
    return device


def _card(coord, domain):
    return next((line for line in coord.recommendation_lines() if line["key"] == f"offer:{domain}"), None)
