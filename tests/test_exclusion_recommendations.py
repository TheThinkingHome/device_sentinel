# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_exclusion_recommendations.py, Version: 0.27.11 (2026-10-28)

"""On a house that already exists, a router or media integration seen for
the first time is recommended for exclusion, not excluded (rule MUTE-02).

The card is on the Recommendations tab in Simple and Advanced. It names
the integration, says why it is usually excluded, lists its devices, and
offers Exclude and a tick to keep watching it. The brief says once that
it is there. Once excluded or ticked, it does not come back. A house
that never saved its exclusion list keeps the list it had before the
card existed, so Alexa Media Player and Google Cast reach it as cards
too.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_MUTED_DEVICES,
    CONF_MUTED_INTEGRATIONS,
    DATA_SETUP_COUNT,
    DATA_SYSTEM_EVENTS,
    DEFAULT_EXCLUDED_BEFORE_0277,
    DEFAULT_EXCLUDED_INTEGRATIONS,
    SYS_EXCLUSION_OFFERED,
    SYS_FIRST_SEEN_EXCLUDED,
    SYS_KIND,
    SYS_SCOPE,
)

from .helpers import setup_coordinator


def _integration(hass, domain, names):
    source = MockConfigEntry(domain=domain, title=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    devices = []
    for name in names:
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id, identifiers={(domain, name)}, name=name)
        er.async_get(hass).async_get_or_create(
            "media_player", domain, f"{name}_player", device_id=device.id, config_entry=source)
        devices.append(device)
    return devices


async def _house(hass, saved=None, **options):
    """A house that already exists: set up before, nothing seen yet."""
    coord = await setup_coordinator(hass)
    coord.data[DATA_SETUP_COUNT] = 40
    coord.data["routers_seen"] = []
    coord.data[DATA_SYSTEM_EVENTS] = []
    changed = dict(options)
    if saved is not None:
        changed[CONF_EXCLUDED_INTEGRATIONS] = list(saved)
    if changed:
        hass.config_entries.async_update_entry(coord.entry, options={**coord.entry.options, **changed})
        await hass.async_block_till_done()
    return coord


def _told(coord, kind):
    return [r[SYS_SCOPE] for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == kind]


def _line(coord, domain):
    found = [e for e in coord.recommendation_lines() if e["key"] == f"offer:{domain}"]
    return found[0] if found else None


async def test_alexa_on_an_existing_house_is_recommended_not_excluded(hass: HomeAssistant):
    echo = _integration(hass, "alexa_media", ["Echo Kitchen", "Headphones Randy"])
    coord = await _house(hass, ["mobile_app"])
    await coord._sight_router_integrations()

    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app"]
    coord._rebuild_registry_view()
    assert echo[0].id in coord._watched
    line = _line(coord, "alexa_media")
    assert line is not None and line["simple"] and not line["acknowledged"]
    assert line["exclude"] == "alexa_media"
    assert line["devices"] == ["Echo Kitchen", "Headphones Randy"]
    assert "with 2 devices" in line["text"] and "Amazon's cloud" in line["text"]
    assert _told(coord, SYS_EXCLUSION_OFFERED) == ["alexa_media"]
    assert not _told(coord, SYS_FIRST_SEEN_EXCLUDED)
    # Told once: seen again, nothing more.
    await coord._sight_router_integrations()
    assert _told(coord, SYS_EXCLUSION_OFFERED) == ["alexa_media"]


async def test_the_card_is_in_the_brief_every_morning_until_answered(hass: HomeAssistant):
    _integration(hass, "cast", ["Basement Chromecast"])
    coord = await _house(hass, ["mobile_app"])
    await coord._sight_router_integrations()
    coord._rebuild_registry_view()
    row = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_EXCLUSION_OFFERED][0]
    assert "the Recommendations tab has a card for it" in coord._system_event_sentence(row)
    assert any("Google Cast Is Usually Excluded" in item or "cast Is Usually Excluded" in item
               for item in coord._recommendations_section())
    coord.set_recommendation_ack(True, line="offer:cast")
    assert not any("Is Usually Excluded" in item for item in coord._recommendations_section())


async def test_a_list_never_saved_keeps_what_it_had(hass: HomeAssistant):
    _integration(hass, "alexa_media", ["Echo Kitchen"])
    coord = await _house(hass)
    # As read at load from a file 0.27.6 wrote (see the test below).
    coord._pin_before_0277 = True
    assert CONF_EXCLUDED_INTEGRATIONS not in coord.entry.options
    assert "alexa_media" not in coord.excluded_integrations
    await coord._sight_router_integrations()
    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == list(DEFAULT_EXCLUDED_BEFORE_0277)
    assert _line(coord, "alexa_media") is not None


async def test_a_new_install_starts_with_alexa_and_cast_excluded(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    assert {"alexa_media", "cast"} <= coord.excluded_integrations
    assert {"alexa_media", "cast"} <= set(DEFAULT_EXCLUDED_INTEGRATIONS)


async def test_a_router_is_recommended_too(hass: HomeAssistant):
    _integration(hass, "fritz", ["Box"])
    coord = await _house(hass, ["mobile_app"])
    coord._first_seen_exclusions_present = lambda: {"fritz"}
    await coord._sight_router_integrations()
    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app"]
    assert "copies of hardware" in _line(coord, "fritz")["text"]


async def test_muted_for_everything_it_has_no_card_until_unmuted(hass: HomeAssistant):
    _integration(hass, "cast", ["Basement Chromecast"])
    coord = await _house(hass, ["mobile_app"], **{CONF_MUTED_INTEGRATIONS: ["cast"]})
    await coord._sight_router_integrations()
    coord._rebuild_registry_view()
    assert _line(coord, "cast") is None
    # And the brief does not point to a card that is not there.
    assert _told(coord, SYS_EXCLUSION_OFFERED) == []
    assert "cast" in coord.data["routers_seen"]
    hass.config_entries.async_update_entry(coord.entry, options={**coord.entry.options, CONF_MUTED_INTEGRATIONS: []})
    await hass.async_block_till_done()
    assert _line(coord, "cast") is not None


async def test_a_device_muted_does_not_answer_the_card(hass: HomeAssistant):
    chromecast = _integration(hass, "cast", ["Basement Chromecast"])
    coord = await _house(hass, ["mobile_app"], **{CONF_MUTED_DEVICES: [chromecast[0].id]})
    await coord._sight_router_integrations()
    coord._rebuild_registry_view()
    assert _line(coord, "cast") is not None
    assert _told(coord, SYS_EXCLUSION_OFFERED) == ["cast"]


async def test_excluded_and_taken_back_the_card_comes_back(hass: HomeAssistant):
    _integration(hass, "cast", ["Basement Chromecast"])
    coord = await _house(hass, ["mobile_app"])
    await coord._sight_router_integrations()
    coord.page_set_integration_excluded("cast", True, source="recommendations_tab")
    await hass.async_block_till_done()
    assert "cast" in coord.excluded_integrations
    assert _line(coord, "cast") is None
    # Not "excluded when first seen": the person did it.
    assert coord.dashboard_integration("cast")["first_seen"] is False
    coord.page_set_integration_excluded("cast", False)
    await hass.async_block_till_done()
    await coord._sight_router_integrations()
    coord._rebuild_registry_view()
    assert _line(coord, "cast") is not None and not _line(coord, "cast")["acknowledged"]


async def test_excluded_in_settings_the_card_goes_and_comes_back(hass: HomeAssistant):
    _integration(hass, "cast", ["Basement Chromecast"])
    coord = await _house(hass, ["mobile_app"])
    await coord._sight_router_integrations()
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_EXCLUDED_INTEGRATIONS: ["mobile_app", "cast"]})
    await hass.async_block_till_done()
    assert _line(coord, "cast") is None
    await coord._sight_router_integrations()
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_EXCLUDED_INTEGRATIONS: ["mobile_app"]})
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    assert _line(coord, "cast") is not None


async def test_ticked_it_stays_watched_and_counts_for_nothing(hass: HomeAssistant):
    _integration(hass, "cast", ["Basement Chromecast"])
    coord = await _house(hass, ["mobile_app"])
    await coord._sight_router_integrations()
    coord.set_recommendation_ack(True, line="offer:cast")
    line = _line(coord, "cast")
    assert line["acknowledged"]
    assert "cast" not in coord.excluded_integrations
    await coord._sight_router_integrations()
    assert _line(coord, "cast")["acknowledged"]


async def test_the_card_replaces_the_written_lines_that_named_it(hass: HomeAssistant):
    _integration(hass, "webostv", ["LG Lounge"])
    coord = await _house(hass, ["mobile_app"])
    coord._rebuild_registry_view()
    before = [e["text"] for e in coord.recommendation_lines()]
    assert any("webostv" in t or "LG webOS" in t for t in before), before
    await coord._sight_router_integrations()
    texts = [e["text"] for e in coord.recommendation_lines() if not e["key"].startswith("offer:")]
    assert not any("LG webOS" in t or "webostv" in t for t in texts)
    assert _line(coord, "webostv") is not None


async def test_a_house_written_by_0276_is_read_as_one_that_exists(hass: HomeAssistant, hass_storage):
    """The upgrade itself: the file says 0.27.6 wrote it, and the list was
    never saved, so the default it had stands."""
    from custom_components.device_sentinel.const import DATA_LAST_VERSION, STORAGE_KEY

    from .helpers import setup_entry

    _integration(hass, "alexa_media", ["Echo Kitchen"])
    hass_storage[STORAGE_KEY] = {"version": 1, "data": {DATA_LAST_VERSION: "0.27.6", DATA_SETUP_COUNT: 12}}
    coord = (await setup_entry(hass)).runtime_data
    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == list(DEFAULT_EXCLUDED_BEFORE_0277)
    assert "alexa_media" not in coord.excluded_integrations
    assert _line(coord, "alexa_media") is not None


async def test_a_new_install_keeps_alexa_and_cast_after_its_first_restart(hass: HomeAssistant, freezer):
    """The second start reads the new install's saved default, not the
    older one, so both stay excluded."""
    from .outage_helpers import restart

    _integration(hass, "alexa_media", ["Echo Kitchen"])
    coord = await setup_coordinator(hass)
    assert {"alexa_media", "cast"} <= coord.excluded_integrations
    coord = await restart(hass, freezer)
    assert {"alexa_media", "cast"} <= coord.excluded_integrations
    assert _line(coord, "alexa_media") is None


async def test_an_integration_with_no_devices_raises_no_card(hass: HomeAssistant):
    MockConfigEntry(domain="cast", title="cast").add_to_hass(hass)
    coord = await _house(hass, ["mobile_app"])
    await coord._sight_router_integrations()
    assert _line(coord, "cast") is None
