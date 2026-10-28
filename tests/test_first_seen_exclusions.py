# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_first_seen_exclusions.py, Version: 0.27.10 (2026-10-27)

"""Music Assistant, the television integrations, Alexa Media Player and
Google Cast, excluded when first seen on a new install (rule MUTE-02).

A new install starts with them on its exclusion list, and in its first
run one seen is added once, as a router integration is; a person who
takes one off keeps it off. Each test here is a house in its first run
(setup count 1). A house that already exists gets a recommendation
instead: test_exclusion_recommendations.py. A media player for a
television can bring back a television excluded through its own
integration, and open an unavailable incident each time the television
is switched off.
"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    AUTO_EXCLUDED_INTEGRATIONS,
    CONF_EXCLUDED_INTEGRATIONS,
    DEFAULT_EXCLUDED_INTEGRATIONS,
)

from .helpers import setup_coordinator

SEVEN = (
    "music_assistant", "webostv", "androidtv", "androidtv_remote", "samsungtv", "apple_tv", "dlna_dmr",
    "alexa_media", "cast",
)


def test_the_nine_are_on_a_new_installs_list():
    assert AUTO_EXCLUDED_INTEGRATIONS == SEVEN
    assert set(SEVEN) <= set(DEFAULT_EXCLUDED_INTEGRATIONS)
    # What was there before stays.
    assert {"mobile_app", "fully_kiosk", "spook", "ping", "tplink_router", "unifi"} <= set(
        DEFAULT_EXCLUDED_INTEGRATIONS
    )


def _player(hass, domain="music_assistant", uid="kitchen"):
    """A Music Assistant player: a media player and a button, no address."""
    source = MockConfigEntry(domain=domain, title=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(domain, uid)}, name=f"Player {uid}"
    )
    registry = er.async_get(hass)
    registry.async_get_or_create("media_player", domain, f"{uid}_player", device_id=device.id, config_entry=source)
    registry.async_get_or_create("button", domain, f"{uid}_favourite", device_id=device.id, config_entry=source)
    return device


async def _existing_house(hass, saved):
    """A house in its first run with its own saved list, nothing seen."""
    coord = await setup_coordinator(hass)
    # As if the setup just run were an older release's: nothing seen,
    # nothing told.
    coord.data["routers_seen"] = []
    coord.data["system_events"] = []
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_EXCLUDED_INTEGRATIONS: list(saved)}
    )
    await hass.async_block_till_done()
    return coord


async def test_an_existing_house_gets_music_assistant_excluded_once(hass: HomeAssistant):
    """A saved list that lacks Music Assistant, on a house in its first run."""
    player = _player(hass)
    rig = ["fully_kiosk", "spook", "ping", "androidtv", "webostv", "mobile_app", "tplink_router"]
    coord = await _existing_house(hass, rig)
    coord._rebuild_registry_view()
    assert player.id in coord._watched

    await coord._sight_router_integrations()

    excluded = coord.entry.options[CONF_EXCLUDED_INTEGRATIONS]
    assert excluded == [*rig, "music_assistant"]
    assert "music_assistant" in coord.data["routers_seen"]
    # Set aside at once, with no registry change to rebuild it.
    assert player.id not in coord._watched


async def test_one_taken_off_the_list_stays_off(hass: HomeAssistant):
    _player(hass)
    coord = await _existing_house(hass, ["mobile_app"])
    await coord._sight_router_integrations()
    assert "music_assistant" in coord.entry.options[CONF_EXCLUDED_INTEGRATIONS]

    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_EXCLUDED_INTEGRATIONS: ["mobile_app"]}
    )
    await hass.async_block_till_done()
    await coord._sight_router_integrations()

    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app"]


@pytest.mark.parametrize("domain", SEVEN)
async def test_each_is_excluded_when_first_seen(hass: HomeAssistant, domain):
    _player(hass, domain, uid=f"{domain}_1")
    coord = await _existing_house(hass, ["mobile_app"])
    await coord._sight_router_integrations()
    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app", domain]


async def test_one_the_house_does_not_have_is_not_added(hass: HomeAssistant):
    """Nothing is written for an integration the house does not have:
    updating the options reloads the entry."""
    coord = await _existing_house(hass, ["mobile_app"])
    before = dict(coord.entry.options)
    await coord._sight_router_integrations()
    assert dict(coord.entry.options) == before


async def test_one_already_excluded_writes_nothing(hass: HomeAssistant):
    """A house that already excludes samsungtv, apple_tv and dlna_dmr."""
    for domain in ("samsungtv", "apple_tv", "dlna_dmr"):
        _player(hass, domain, uid=f"{domain}_tim")
    tim = ["fully_kiosk", "spook", "ping", "samsungtv", "apple_tv", "dlna_dmr", "unifi", "mobile_app"]
    coord = await _existing_house(hass, tim)
    before = dict(coord.entry.options)

    await coord._sight_router_integrations()

    assert dict(coord.entry.options) == before
    assert {"samsungtv", "apple_tv", "dlna_dmr"} <= set(coord.data["routers_seen"])


async def test_a_new_install_has_them_from_the_start(hass: HomeAssistant):
    """No saved list: the default is in force and nothing is written."""
    player = _player(hass)
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    assert "music_assistant" in coord.excluded_integrations
    assert player.id not in coord._watched


async def test_an_ignored_or_disabled_entry_is_not_seen(hass: HomeAssistant):
    """A discovered television a person clicked Ignore on is not one the
    house has."""
    from homeassistant.config_entries import SOURCE_IGNORE, ConfigEntryDisabler

    MockConfigEntry(domain="samsungtv", source=SOURCE_IGNORE).add_to_hass(hass)
    MockConfigEntry(domain="dlna_dmr", disabled_by=ConfigEntryDisabler.USER).add_to_hass(hass)
    coord = await _existing_house(hass, ["mobile_app"])
    await coord._sight_router_integrations()
    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app"]


async def test_each_one_added_is_told_in_the_brief(hass: HomeAssistant):
    """A person who watched it on purpose sees it was excluded."""
    from custom_components.device_sentinel.const import DATA_SYSTEM_EVENTS, SYS_FIRST_SEEN_EXCLUDED, SYS_KIND, SYS_SCOPE

    _player(hass)
    coord = await _existing_house(hass, ["mobile_app"])
    await coord._sight_router_integrations()

    rows = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_FIRST_SEEN_EXCLUDED]
    assert [r[SYS_SCOPE] for r in rows] == ["music_assistant"]
    assert coord._system_event_phrase(rows[0]).endswith("excluded when first seen")
    assert "excluded when first seen, at" in coord._system_event_sentence(rows[0])
    # Seen again, nothing more is told.
    await coord._sight_router_integrations()
    assert len([r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_FIRST_SEEN_EXCLUDED]) == 1


async def test_a_list_never_saved_is_told_too(hass: HomeAssistant):
    """A house that never submitted its Configure screen has the default,
    which already holds the nine: still told."""
    from custom_components.device_sentinel.const import DATA_SYSTEM_EVENTS, SYS_FIRST_SEEN_EXCLUDED, SYS_KIND, SYS_SCOPE

    _player(hass)
    coord = await setup_coordinator(hass)
    coord.data["routers_seen"] = []
    coord.data[DATA_SYSTEM_EVENTS] = []
    await coord._sight_router_integrations()

    assert CONF_EXCLUDED_INTEGRATIONS not in coord.entry.options
    rows = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_FIRST_SEEN_EXCLUDED]
    assert [r[SYS_SCOPE] for r in rows] == ["music_assistant"]


async def test_the_next_settings_change_does_not_name_the_list(hass: HomeAssistant):
    """The exclusion is written before the update listener exists; the
    snapshot a later change is compared with must hold it."""
    _player(hass)
    coord = await _existing_house(hass, ["mobile_app"])
    coord._options_seen = dict(coord.entry.options)
    await coord._sight_router_integrations()
    assert coord._options_seen[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app", "music_assistant"]


async def test_a_restart_across_midnight_keeps_the_history_until_the_next(hass: HomeAssistant, hass_storage):
    """Updated in the evening, restarted after midnight: the catch-up fold
    runs before the sighting, so the newly excluded player's record is
    kept until the next midnight, as the brief says. And nothing crashes."""
    import datetime

    from homeassistant.util import dt as dt_util

    from custom_components.device_sentinel.const import (
        DATA_DEVICES,
        DATA_EPISODES,
        DATA_FIRST_INSTALLED,
        DATA_SAVED_AT,
        DATA_STATS_EPOCH,
        DATA_TODO_ITEMS,
        DEV_DAILY_MAX,
        DEV_EVENT_COUNT,
        DEV_FIRST_OBSERVED,
        DEV_LAST_ACTIVITY,
        DEV_TODAY_MAX,
        STATS_EPOCH,
        STORAGE_KEY,
    )

    from .helpers import setup_entry

    player = _player(hass)
    yesterday = (
        dt_util.now().replace(hour=23, minute=59, second=0, microsecond=0) - datetime.timedelta(days=1)
    ).timestamp()
    hass_storage[STORAGE_KEY] = {"version": 1, "data": {
        DATA_DEVICES: {player.id: {
            DEV_LAST_ACTIVITY: yesterday - 60.0, DEV_TODAY_MAX: 4000.0, DEV_EVENT_COUNT: 100,
            DEV_FIRST_OBSERVED: "2026-07-11T00:00:00+00:00", DEV_DAILY_MAX: [3000.0] * 10,
        }},
        DATA_STATS_EPOCH: STATS_EPOCH, DATA_SAVED_AT: yesterday, DATA_EPISODES: [], DATA_TODO_ITEMS: [],
        DATA_FIRST_INSTALLED: "2026-07-11T00:00:00+00:00", "clean_stop": True,
    }}

    entry = await setup_entry(hass, {CONF_EXCLUDED_INTEGRATIONS: ["mobile_app"]})
    coord = entry.runtime_data

    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app", "music_assistant"]
    assert player.id not in coord._watched
    record = coord.data[DATA_DEVICES].get(player.id)
    assert record is not None, "the catch-up fold discarded the newly excluded device"
    # The missed day was folded while it was still watched.
    assert record[DEV_DAILY_MAX][-1] == 4000.0


async def test_one_added_while_running_is_excluded_within_the_debounce(hass: HomeAssistant):
    """A new LG TV integration on a house that rarely restarts is excluded
    when it appears, before a false alarm."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    from custom_components.device_sentinel.const import DATA_SYSTEM_EVENTS, SYS_FIRST_SEEN_EXCLUDED, SYS_KIND

    coord = await _existing_house(hass, ["mobile_app"])
    coord.data[DATA_SYSTEM_EVENTS] = []
    tv = _player(hass, "webostv", uid="lounge")
    for _ in range(3):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
        await hass.async_block_till_done()

    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app", "webostv"]
    assert tv.id not in coord._watched
    assert [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_FIRST_SEEN_EXCLUDED]
    # Its own write is not told as a settings change.
    assert not [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == "options_changed"]


@pytest.mark.parametrize("how", ["integration", "device_freeze", "device_unavailable", "device_everything", "excluded_device"])
async def test_a_choice_already_made_stands(hass: HomeAssistant, how):
    """A television the person already muted, or one of whose devices they
    muted or excluded, is left as they chose."""
    from custom_components.device_sentinel.const import (
        CONF_EXCLUDED_DEVICES,
        CONF_FREEZE_MUTED_DEVICES,
        CONF_MUTED_DEVICES,
        CONF_MUTED_INTEGRATIONS,
        CONF_UNAVAILABLE_MUTED_DEVICES,
    )

    tv = _player(hass, "webostv", uid="muted")
    choice = {
        "integration": {CONF_MUTED_INTEGRATIONS: ["webostv"]},
        "device_freeze": {CONF_FREEZE_MUTED_DEVICES: [tv.id]},
        "device_unavailable": {CONF_UNAVAILABLE_MUTED_DEVICES: [tv.id]},
        "device_everything": {CONF_MUTED_DEVICES: [tv.id]},
        "excluded_device": {CONF_EXCLUDED_DEVICES: [tv.id]},
    }[how]
    coord = await setup_coordinator(hass)
    coord.data["routers_seen"] = []
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_EXCLUDED_INTEGRATIONS: ["mobile_app"], **choice}
    )
    await hass.async_block_till_done()

    await coord._sight_router_integrations()

    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app"]
    # Seen all the same, so it is never new again.
    assert "webostv" in coord.data["routers_seen"]


@pytest.mark.parametrize("router", ["unifi", "fritz"])
async def test_a_router_on_a_list_never_saved_is_excluded_and_told(hass: HomeAssistant, router):
    """One the default holds is told; one it lacks, such as a FRITZ!Box,
    is added and told."""
    from custom_components.device_sentinel.const import DATA_SYSTEM_EVENTS, SYS_FIRST_SEEN_EXCLUDED, SYS_KIND, SYS_SCOPE

    _player(hass, router, uid="ap")
    coord = await setup_coordinator(hass)
    coord.data["routers_seen"] = []
    coord.data[DATA_SYSTEM_EVENTS] = []
    coord._first_seen_exclusions_present = lambda: {router}
    await coord._sight_router_integrations()

    rows = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r[SYS_KIND] == SYS_FIRST_SEEN_EXCLUDED]
    assert [r[SYS_SCOPE] for r in rows] == [router]
    assert router in coord.excluded_integrations
    if router == "fritz":
        assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == [*DEFAULT_EXCLUDED_INTEGRATIONS, "fritz"]
    else:
        assert CONF_EXCLUDED_INTEGRATIONS not in coord.entry.options


@pytest.mark.parametrize("damaged", ["webostv", {"a": 1}])
async def test_a_damaged_list_does_not_stop_the_start(hass: HomeAssistant, damaged):
    """A list hand-edited into something else is read as empty. (A number
    there fails elsewhere first.)"""
    _player(hass)
    coord = await _existing_house(hass, [])
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_EXCLUDED_INTEGRATIONS: damaged}
    )
    await hass.async_block_till_done()
    coord.data["routers_seen"] = []

    await coord._sight_router_integrations()

    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["music_assistant"]


async def test_on_a_list_never_saved_a_choice_made_is_kept(hass: HomeAssistant):
    """A house that never saved its list, watching its LG TV with one of
    its devices muted for freeze: the new default does not overrule that."""
    from custom_components.device_sentinel.const import CONF_FREEZE_MUTED_DEVICES

    tv = _player(hass, "webostv", uid="kept")
    coord = await setup_coordinator(hass)
    coord.data["routers_seen"] = []
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_FREEZE_MUTED_DEVICES: [tv.id]}
    )
    await hass.async_block_till_done()
    await coord._sight_router_integrations()

    listed = coord.entry.options[CONF_EXCLUDED_INTEGRATIONS]
    assert "webostv" not in listed
    assert listed == [n for n in DEFAULT_EXCLUDED_INTEGRATIONS if n != "webostv"]
    coord._rebuild_registry_view()
    assert tv.id in coord._watched


async def test_a_change_made_while_a_sighting_saves_is_not_written_over(hass: HomeAssistant):
    """The list is read and written with no wait between, so a person's
    change made while the file saves stands."""
    _player(hass)
    coord = await _existing_house(hass, ["mobile_app"])
    real_save = coord._save_now
    changed = []

    async def save_and_change():
        coord._save_now = real_save
        if not changed:
            changed.append(True)
            hass.config_entries.async_update_entry(
                coord.entry,
                options={**coord.entry.options, CONF_EXCLUDED_INTEGRATIONS: [
                    *coord.entry.options[CONF_EXCLUDED_INTEGRATIONS], "ping"]},
            )
        await real_save()

    coord._save_now = save_and_change
    await coord._sight_router_integrations()
    await hass.async_block_till_done()

    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app", "music_assistant", "ping"]


async def test_a_sighting_after_the_stop_saves_nothing(hass: HomeAssistant):
    """A stopped coordinator is left alone."""
    _player(hass)
    coord = await _existing_house(hass, ["mobile_app"])
    coord._stopped = True
    before = dict(coord.entry.options)
    await coord._sight_router_integrations()
    assert dict(coord.entry.options) == before
    coord._stopped = False


@pytest.mark.parametrize("how", ["everything", "label"])
async def test_on_a_list_never_saved_a_full_or_label_mute_is_kept(hass: HomeAssistant, how):
    """The TV a house muted for everything, or through a label, is set
    aside by the new default before the sighting, so the choice is read
    from the settings and the registry, not from what is watched."""
    from homeassistant.helpers import label_registry as lr

    from custom_components.device_sentinel.const import CONF_MUTED_DEVICES, CONF_UNAVAILABLE_MUTED_LABELS

    tv = _player(hass, "samsungtv", uid="lounge")
    if how == "label":
        label = lr.async_get(hass).async_create("Television")
        dr.async_get(hass).async_update_device(tv.id, labels={label.label_id})
        choice = {CONF_UNAVAILABLE_MUTED_LABELS: [label.label_id]}
    else:
        choice = {CONF_MUTED_DEVICES: [tv.id]}
    coord = await setup_coordinator(hass)
    coord.data["routers_seen"] = []
    hass.config_entries.async_update_entry(coord.entry, options={**coord.entry.options, **choice})
    await hass.async_block_till_done()

    await coord._sight_router_integrations()

    assert "samsungtv" not in coord.entry.options[CONF_EXCLUDED_INTEGRATIONS]


async def test_a_router_is_excluded_whatever_was_muted(hass: HomeAssistant):
    """Routers are excluded when first seen, whatever the person muted
    (rule MUTE-02)."""
    from custom_components.device_sentinel.const import CONF_MUTED_INTEGRATIONS

    _player(hass, "fritz", uid="box")
    coord = await setup_coordinator(hass)
    coord.data["routers_seen"] = []
    hass.config_entries.async_update_entry(
        coord.entry, options={**coord.entry.options, CONF_EXCLUDED_INTEGRATIONS: ["mobile_app"],
                              CONF_MUTED_INTEGRATIONS: ["fritz"]}
    )
    await hass.async_block_till_done()
    coord._first_seen_exclusions_present = lambda: {"fritz"}

    await coord._sight_router_integrations()

    assert coord.entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["mobile_app", "fritz"]
