# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_cached_value_models.py, Version: 0.29.2 (2026-11-15)

"""Device Sentinel's own list of makes and models that report cached
values after a restart, the settings list's choices, and a settings
entry edited by hand (rule WATCH-12).

A model on the list, in an integration that otherwise reports live,
waits for a changed value after a restart; a person's setting on a
device page comes first. The settings list offers only integrations
with a device the list can apply to.
"""

from __future__ import annotations

import json

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_CACHED_ADDED,
    CONF_CACHED_REMOVED,
    DEV_FROZEN_CATEGORY,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_UNAVAILABLE,
)
from custom_components.device_sentinel.power_source import model_key
from custom_components.device_sentinel.restart_values import (
    CACHED_VALUE_MODEL_NAMES,
    CACHED_VALUE_MODELS,
    CASE_CONFIRMED,
    RESTART_MODE_CACHED,
    RESTART_MODE_LIVE,
    stored_domains,
)

from tests.helpers import record_events, setup_coordinator
from tests.outage_helpers import PIN, arm, entry_of, past_grace, rec, restart, walk

VALUES = ("on", "21.5")
HT = ("Shelly", "Shelly H&T", "SHHT-1")
PLUG = ("Shelly", "Shelly Plus Plug S", "SNPL-00112EU")


def _device(hass, domain, uid, maker, model, model_id="", kinds=("binary_sensor", "sensor")):
    sources = hass.config_entries.async_entries(domain)
    if sources:
        source = sources[0]
    else:
        source = MockConfigEntry(domain=domain, title=domain.title())
        source.add_to_hass(hass)
        source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(domain, uid)},
        name=uid.title(),
        manufacturer=maker,
        model=model,
        model_id=model_id or None,
    )
    eids = [
        er.async_get(hass).async_get_or_create(
            kind, domain, f"{uid}_{kind}", device_id=device.id, config_entry=source
        ).entity_id
        for kind in kinds
    ]
    return device, eids


async def _house(hass, freezer, *specs, options=None):
    freezer.move_to(PIN)
    made = []
    for spec in specs:
        device, eids = _device(hass, *spec)
        for eid, value in zip(eids, VALUES):
            hass.states.async_set(eid, value)
        made.append((device, eids))
    coord = await setup_coordinator(hass, options or {})
    for device, _eids in made:
        arm(coord, device.id, rhythm=600.0)
    await past_grace(hass, freezer)
    return coord, made


def _same_values_back(hass, eids):
    def _write():
        for eid, value in zip(eids, VALUES):
            hass.states.async_set(eid, value)
    return _write


async def _down(hass, freezer, coord, device, eids):
    for eid in eids:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


def _mine(events, device_id):
    return [e for e in events if e.get("device_id") == device_id]


# ------------------------------------------------------- the list itself


def test_the_list_holds_the_thirty_six_models_as_their_integrations_name_them():
    """Manufacturer, model and model ID as each integration writes them,
    so each matches the key a device page sets."""
    assert len(CACHED_VALUE_MODEL_NAMES) == 36
    assert len(CACHED_VALUE_MODELS) == 36
    assert model_key(*HT) in CACHED_VALUE_MODELS
    assert model_key("Govee", "H5123", None) in CACHED_VALUE_MODELS
    assert model_key("Linptech", "ES3", None) in CACHED_VALUE_MODELS
    # Left off: they keep a connection, or can run from USB.
    for names in (
        ("Shelly", "Shelly Motion", "SHMOS-01"),
        ("Shelly", "Shelly Valve", "SHTRV-01"),
        ("Shelly", "Shelly Button1", "SHBTN-1"),
        PLUG,
    ):
        assert model_key(*names) not in CACHED_VALUE_MODELS
    makers = {json.loads(key)[0] for key in CACHED_VALUE_MODELS}
    assert makers == {"Shelly", "Govee", "Xiaomi", "Linptech"}


# ---------------------------------------------- a listed model, at a restart


async def test_a_listed_model_waits_for_a_changed_value(hass: HomeAssistant, freezer):
    """Shelly reports live, but its first-generation H&T sleeps and is
    shown with its restored values: down across a restart and back with
    the same values, it stays listed until one changes. A Shelly plug
    beside it is taken at its word."""
    coord, [(ht, ht_eids), (plug, plug_eids)] = await _house(
        hass, freezer, ("shelly", "ht", *HT), ("shelly", "plug", *PLUG)
    )
    assert "shelly" not in coord.cached_integrations()
    assert coord._reports_cached(ht.id) and not coord._reports_cached(plug.id)
    back = record_events(hass, EVENT_RECOVERED)
    await _down(hass, freezer, coord, ht, ht_eids)
    await _down(hass, freezer, coord, plug, plug_eids)

    def _both():
        _same_values_back(hass, ht_eids)()
        _same_values_back(hass, plug_eids)()

    coord = await restart(hass, freezer, before_setup=_both)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 5 * 60)
    assert rec(coord, ht.id)[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert rec(coord, plug.id)[DEV_FROZEN_CATEGORY] is None
    assert not _mine(back, ht.id) and len(_mine(back, plug.id)) == 1
    hass.states.async_set(ht_eids[1], "22.0")
    await hass.async_block_till_done()
    await walk(hass, freezer, 2 * 60)
    assert rec(coord, ht.id)[DEV_FROZEN_CATEGORY] is None
    assert len(_mine(back, ht.id)) == 1


async def test_the_device_page_names_the_listed_model(hass: HomeAssistant, freezer):
    coord, [(ht, _e), (plug, _f)] = await _house(
        hass, freezer, ("shelly", "ht", *HT), ("shelly", "plug", *PLUG)
    )
    page = coord.page_restart(ht.id)
    assert page["mode"] is None and page["can_set"] is True
    assert page["same_label"] == "Device Sentinel's Setting"
    assert page["words"].startswith("Device Sentinel lists ")
    assert "only when one of its values changes" in page["words"]
    other = coord.page_restart(plug.id)
    assert other["same_label"].casefold() == "same as shelly"
    assert "report live" in other["words"]


async def test_a_persons_setting_comes_first_and_same_goes_back(hass: HomeAssistant, freezer):
    coord, [(ht, ht_eids)] = await _house(hass, freezer, ("shelly", "ht", *HT))
    coord.page_set_restart(ht.id, RESTART_MODE_LIVE)
    assert not coord._reports_cached(ht.id)
    back = record_events(hass, EVENT_RECOVERED)
    await _down(hass, freezer, coord, ht, ht_eids)
    await coord.async_flush_answers()
    coord = await restart(hass, freezer, before_setup=_same_values_back(hass, ht_eids))
    await past_grace(hass, freezer)
    await walk(hass, freezer, 3 * 60)
    assert rec(coord, ht.id)[DEV_FROZEN_CATEGORY] is None
    assert len(_mine(back, ht.id)) == 1
    coord.page_set_restart(ht.id, None)
    assert coord._reports_cached(ht.id)
    assert coord.page_restart(ht.id)["mode"] is None


async def test_a_listed_model_can_be_offered_to_report_live(hass: HomeAssistant, freezer):
    """Two It's Back presses on a listed model bring the Models That May
    Report Live card, as for a listed integration."""
    coord, [(ht, _eids)] = await _house(hass, freezer, ("shelly", "ht", *HT))
    for _ in range(2):
        coord._restart_case(CASE_CONFIRMED, ht.id, dt_util.utcnow().timestamp())
    cards = coord.restart_recommendations()
    assert [card["card"] for card in cards] == [RESTART_MODE_LIVE]
    coord.page_set_restart(ht.id, RESTART_MODE_LIVE)
    assert coord.restart_recommendations() == []


async def test_a_listed_model_is_never_offered_to_report_cached(hass: HomeAssistant, freezer):
    coord, [(ht, _eids)] = await _house(hass, freezer, ("shelly", "ht", *HT))
    for minutes in (0, 0, 60 * 24):
        coord._restart_case(
            "frozen", ht.id, dt_util.utcnow().timestamp() + minutes * 60
        )
    assert coord.restart_recommendations() == []
    assert coord.page_restart(ht.id)["mode"] != RESTART_MODE_CACHED


# --------------------------------------------------- the settings list


async def test_only_integrations_the_list_can_apply_to_are_offered(hass: HomeAssistant, freezer):
    """An integration whose watched devices all have a Last Seen is not
    offered: ticking it would change nothing. One added by the person is
    kept on the screen, so it can be unticked."""
    freezer.move_to(PIN)
    door, door_eids = _device(hass, "zigbee", "door", "Aqara", "Door")
    source = hass.config_entries.async_entries("zigbee")[0]
    seen = er.async_get(hass).async_get_or_create(
        "sensor", "zigbee", "door_last_seen", device_id=door.id, config_entry=source,
        suggested_object_id="door_last_seen",
    ).entity_id
    blind, blind_eids = _device(hass, "blinds", "blind", "Acme", "Blind")
    for eid in (*door_eids, *blind_eids):
        hass.states.async_set(eid, "on")
    hass.states.async_set(seen, dt_util.utcnow().isoformat())
    coord = await setup_coordinator(hass, {CONF_CACHED_ADDED: ["faraway"]})
    assert door.id in coord._watched and blind.id in coord._watched
    offered = {row["domain"] for row in coord.restart_settings_rows()}
    assert "zigbee" not in offered
    assert "blinds" in offered and "faraway" in offered


# ------------------------------------------ a settings entry edited by hand


@pytest.mark.parametrize(
    "bad", [5, "tado", {"tado": True}, None, ["tado", 7, None]]
)
async def test_a_hand_edited_entry_does_not_stop_the_list_being_read(
    hass: HomeAssistant, freezer, bad
):
    """The added and removed lists must be lists of names. Anything else
    reads as no change, and the list, the settings screen and the
    diagnostics still work."""
    coord, [(ht, _eids)] = await _house(
        hass, freezer, ("blinds", "blind", "Acme", "Blind"),
        options={
            CONF_CACHED_ADDED: bad,
            CONF_CACHED_REMOVED: [] if isinstance(bad, list) else bad,
        },
    )
    listed = coord.cached_integrations()
    assert "tado" in listed and "a" not in listed and "t" not in listed
    assert coord.restart_settings_rows()
    assert coord.restart_diagnostics()["integrations"]
    if isinstance(bad, list):
        assert stored_domains({CONF_CACHED_ADDED: bad}, CONF_CACHED_ADDED) == {"tado"}
    else:
        assert stored_domains({CONF_CACHED_ADDED: bad}, CONF_CACHED_ADDED) == set()
    entry = entry_of(hass)
    assert entry.options[CONF_CACHED_ADDED] == bad
