# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_cached_values_after_restart.py, Version: 0.29.2 (2026-11-15)

"""Integrations and models that report cached values after a restart
(rule WATCH-12).

Only a device with no last seen is in scope. One on the list of
integrations and models that report cached values is reported back only
when one of its values changes. Every other device is taken at its
word: a value arriving after a restart or a reload, even the same value
as before, is the device speaking.

The suite's made-up integration "test" is on the list (tests/conftest.py);
"plainhub" here is a made-up integration that is not.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import restart_values
from custom_components.device_sentinel.const import (
    CONF_CACHED_ADDED,
    CONF_CACHED_REMOVED,
    CONF_RETENTION_DAYS,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    DEV_TODAY_MAX,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
)
from custom_components.device_sentinel.restart_values import (
    CACHED_VALUE_INTEGRATIONS,
    CASE_CONFIRMED,
    CASE_FROZEN,
    CASE_LISTED,
    DATA_RESTART_VALUES,
    RESTART_MODE_CACHED,
    RESTART_MODE_LIVE,
    restarts_in,
)

from tests.helpers import record_events, setup_coordinator
from tests.outage_helpers import PIN, arm, entry_of, past_grace, rec, reload, restart, walk

LIVE = "plainhub"
LISTED = "test"


def device_on(hass, domain, uid, kinds=("media_player", "switch"), maker="Acme", model="One"):
    """A device on an integration, with a make and a model."""
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
    )
    eids = [
        er.async_get(hass).async_get_or_create(
            kind, domain, f"{uid}_{kind}", device_id=device.id, config_entry=source
        ).entity_id
        for kind in kinds
    ]
    return device, eids


VALUES = ("idle", "off")


async def _house(hass, freezer, *devices):
    """Each (domain, uid) as a device showing VALUES, on a ten-minute
    rhythm, past the startup grace."""
    freezer.move_to(PIN)
    made = []
    for spec in devices:
        device, eids = device_on(hass, *spec) if isinstance(spec, tuple) else device_on(hass, **spec)
        for eid, value in zip(eids, VALUES):
            hass.states.async_set(eid, value)
        made.append((device, eids))
    coord = await setup_coordinator(hass)
    for device, _eids in made:
        arm(coord, device.id, rhythm=600.0)
    await past_grace(hass, freezer)
    return coord, made


async def _go_unavailable(hass, freezer, coord, device, eids):
    for eid in eids:
        hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


def _same_values_back(hass, eids):
    def _write():
        for eid, value in zip(eids, VALUES):
            hass.states.async_set(eid, value)

    return _write


def _mine(events, device_id):
    return [e for e in events if e.get("device_id") == device_id]


# ------------------------------------------------- back, and the list


@pytest.mark.parametrize("how", ["restart", "restart, values already there", "reload", "integration reload"])
async def test_a_device_off_the_list_is_back_when_its_values_return(
    hass: HomeAssistant, freezer, how
):
    """A Sonos speaker stayed listed after it recovered: down across a Home
    Assistant restart, a Device Sentinel
    reload or its integration's reload, then back showing exactly the
    values it had. Not on the list, so it is taken at its word."""
    coord, [(device, eids)] = await _house(hass, freezer, (LIVE, "speaker"))
    back = record_events(hass, EVENT_RECOVERED)
    await _go_unavailable(hass, freezer, coord, device, eids)
    if how == "restart":
        coord = await restart(hass, freezer, before_setup=_same_values_back(hass, eids))
    elif how == "restart, values already there":
        # Its integration loaded first: the values stand before Device
        # Sentinel listens, and no event brings them.
        coord = await restart(
            hass, freezer, before_setup=_same_values_back(hass, eids), keep_states=True
        )
    elif how == "reload":
        coord = await reload(hass)
        _same_values_back(hass, eids)()
    else:
        registry = er.async_get(hass)
        for eid in eids:
            hass.states.async_remove(eid)
            registry.async_get(eid).write_unavailable_state(hass)
        await hass.async_block_till_done()
        _same_values_back(hass, eids)()
    await hass.async_block_till_done()
    await walk(hass, freezer, 3 * 60)
    if how != "restart, values already there":
        assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    assert not coord._on_watch.get(device.id)
    # A recovery inside the startup grace is announced as it closes, and
    # values that stood before Device Sentinel listened are judged then.
    await past_grace(hass, freezer)
    await walk(hass, freezer, 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    assert len(_mine(back, device.id)) == 1


async def test_a_device_on_the_list_waits_for_a_changed_value(hass: HomeAssistant, freezer):
    """The same return on an integration that reports cached values is
    not the device speaking; a changed value is."""
    coord, [(device, eids)] = await _house(hass, freezer, (LISTED, "plug"))
    back = record_events(hass, EVENT_RECOVERED)
    await _go_unavailable(hass, freezer, coord, device, eids)
    coord = await restart(hass, freezer, before_setup=_same_values_back(hass, eids))
    await walk(hass, freezer, 20 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert not _mine(back, device.id)
    hass.states.async_set(eids[0], "playing")
    await hass.async_block_till_done()
    await walk(hass, freezer, 2 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    assert len(_mine(back, device.id)) == 1


async def test_a_working_device_off_the_list_moves_its_clock_at_a_start(
    hass: HomeAssistant, freezer
):
    """A healthy device's first value after a start is the device
    speaking when it is off the list, and a value handed back when it is
    on it (rule UNAV-05)."""
    coord, [(live, live_eids), (listed, listed_eids)] = await _house(
        hass, freezer, (LIVE, "speaker"), (LISTED, "plug")
    )
    before = {d.id: rec(coord, d.id)[DEV_LAST_ACTIVITY] for d in (live, listed)}
    coord = await restart(hass, freezer)
    await hass.async_block_till_done()
    assert rec(coord, live.id)[DEV_LAST_ACTIVITY] > (before[live.id] or 0)
    assert rec(coord, listed.id)[DEV_LAST_ACTIVITY] == before[listed.id]


@pytest.mark.shipped_cached_list
async def test_the_shipped_list_and_what_is_never_on_it(hass: HomeAssistant, freezer):
    """The twenty-three on the list as it ships. ZHA and Z-Wave JS are
    judged by last seen whatever a person ticks, and MQTT is not ours to
    put on."""
    assert CACHED_VALUE_INTEGRATIONS == {
        "oralb", "mobile_app", "knx", "octopus_energy", "modbus", "lutron_caseta",
        "lightwave_smart", "unifi", "tado", "august", "yale", "ring", "blink",
        "withings", "tronity", "trmnl", "alarmdotcom",
        "rfxtrx", "enocean", "leaone", "okok_scale", "eufylife_ble", "acaia",
    }
    freezer.move_to(PIN)
    wave, wave_eids = device_on(hass, "zwave_js", "node", kinds=("light",))
    sonos, sonos_eids = device_on(hass, "sonos", "speaker", kinds=("switch",))
    lutron, lutron_eids = device_on(hass, "lutron_caseta", "dimmer", kinds=("light",))
    for eid in (*wave_eids, *sonos_eids, *lutron_eids):
        hass.states.async_set(eid, "on")
    coord = await setup_coordinator(
        hass, {CONF_CACHED_ADDED: ["zwave_js", "zha", "sonos"], CONF_CACHED_REMOVED: ["lutron_caseta"]}
    )
    listed = coord.cached_integrations()
    assert "zwave_js" not in listed and "zha" not in listed and "mqtt" not in listed
    assert "sonos" in listed and "lutron_caseta" not in listed and "tado" in listed
    assert not coord._restart_scope(wave.id) and coord.page_restart(wave.id) is None
    if sonos.id in coord._watched:
        assert coord._reports_cached(sonos.id)
    if lutron.id in coord._watched:
        assert not coord._reports_cached(lutron.id)


async def test_a_device_with_last_seen_is_never_in_scope(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    device, eids = device_on(hass, LISTED, "door", kinds=("binary_sensor", "sensor"))
    source = hass.config_entries.async_entries(LISTED)[0]
    seen = er.async_get(hass).async_get_or_create(
        "sensor", LISTED, "door_last_seen", device_id=device.id, config_entry=source,
        suggested_object_id="door_last_seen",
    ).entity_id
    hass.states.async_set(eids[0], "on")
    hass.states.async_set(seen, dt_util.utcnow().isoformat())
    coord = await setup_coordinator(hass)
    assert device.id in coord._last_seen_entity
    assert not coord._restart_scope(device.id)
    assert not coord._reports_cached(device.id)
    assert coord.page_restart(device.id) is None


# ------------------------------------------------------ a model's setting


async def test_a_model_set_to_live_overrides_its_integration(hass: HomeAssistant, freezer):
    """Set on one device's page, it covers every device of the model,
    and a device waiting on the list is released at once."""
    coord, [(first, first_eids), (second, second_eids)] = await _house(
        hass, freezer, (LISTED, "plug1"), (LISTED, "plug2")
    )
    back = record_events(hass, EVENT_RECOVERED)
    await _go_unavailable(hass, freezer, coord, first, first_eids)
    coord = await restart(hass, freezer, before_setup=_same_values_back(hass, first_eids))
    await walk(hass, freezer, 5 * 60)
    assert coord.restart_pending(first.id)
    coord.page_set_restart(second.id, RESTART_MODE_LIVE)
    await hass.async_block_till_done()
    await walk(hass, freezer, 2 * 60)
    assert not coord._reports_cached(first.id) and not coord._reports_cached(second.id)
    assert rec(coord, first.id)[DEV_FROZEN_CATEGORY] is None
    assert len(_mine(back, first.id)) == 1
    # Kept in the answers file across a restart.
    await coord.async_flush_answers()
    coord = await restart(hass, freezer)
    assert coord.page_restart(first.id)["mode"] == RESTART_MODE_LIVE
    coord.page_set_restart(first.id, None)
    assert coord._reports_cached(second.id)
    assert coord.page_restart(second.id)["mode"] is None


async def test_a_model_set_to_cached_overrides_its_integration(hass: HomeAssistant, freezer):
    coord, [(device, eids), (other, _other_eids)] = await _house(
        hass, freezer, (LIVE, "speaker"), (LIVE, "amp", ("media_player", "switch"), "Acme", "Two")
    )
    coord.page_set_restart(device.id, RESTART_MODE_CACHED)
    assert coord._reports_cached(device.id) and not coord._reports_cached(other.id)
    back = record_events(hass, EVENT_RECOVERED)
    await _go_unavailable(hass, freezer, coord, device, eids)
    await coord.async_flush_answers()
    coord = await restart(hass, freezer, before_setup=_same_values_back(hass, eids))
    await walk(hass, freezer, 20 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert not _mine(back, device.id)
    with pytest.raises(ValueError):
        coord.page_set_restart(device.id, "sometimes")


async def test_a_device_with_no_model_follows_its_integration(hass: HomeAssistant, freezer):
    coord, [(device, _eids)] = await _house(
        hass, freezer, {"domain": LIVE, "uid": "thing", "maker": None, "model": None}
    )
    page = coord.page_restart(device.id)
    assert page["can_set"] is False and page["mode"] is None
    with pytest.raises(ValueError):
        coord.page_set_restart(device.id, RESTART_MODE_CACHED)


# ----------------------------------------------- the settings list


async def test_the_persons_changes_are_kept_apart_from_ours(hass: HomeAssistant, freezer):
    """Unticking one of ours and ticking one of theirs changes the list
    at once: a device waiting on an unticked integration is released."""
    coord, [(device, eids)] = await _house(hass, freezer, (LISTED, "plug"))
    back = record_events(hass, EVENT_RECOVERED)
    await _go_unavailable(hass, freezer, coord, device, eids)
    coord = await restart(hass, freezer, before_setup=_same_values_back(hass, eids))
    await past_grace(hass, freezer)
    assert coord._on_watch.get(device.id)
    entry = entry_of(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_CACHED_REMOVED: [LISTED], CONF_CACHED_ADDED: [LIVE]}
    )
    await hass.async_block_till_done()
    await walk(hass, freezer, 2 * 60)
    assert LISTED not in coord.cached_integrations() and LIVE in coord.cached_integrations()
    assert "tado" in coord.cached_integrations()
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    assert len(_mine(back, device.id)) == 1


async def test_the_settings_rows_name_the_models_set(hass: HomeAssistant, freezer):
    coord, made = await _house(
        hass, freezer,
        (LIVE, "a", ("switch",), "Acme", "One"),
        (LIVE, "b", ("switch",), "Acme", "Two"),
        (LISTED, "c", ("switch",), "Bolt", "Plug"),
    )
    rows = {row["domain"]: row["label"] for row in coord.restart_settings_rows()}
    assert set(rows) == {LIVE, LISTED}
    assert "set on" not in rows[LIVE]
    coord.page_set_restart(made[0][0].id, RESTART_MODE_CACHED)
    coord.page_set_restart(made[2][0].id, RESTART_MODE_LIVE)
    rows = {row["domain"]: row["label"] for row in coord.restart_settings_rows()}
    assert rows[LIVE].endswith(". Acme One reports cached values, set on its device page.")
    assert rows[LISTED].endswith(". Bolt Plug reports live, set on its device page.")
    coord.page_set_restart(made[1][0].id, RESTART_MODE_CACHED)
    rows = {row["domain"]: row["label"] for row in coord.restart_settings_rows()}
    assert rows[LIVE].endswith(
        ". Acme One and Acme Two report cached values, set on their device pages."
    )


# ---------------------------------------- on the list: Back after a restart?


async def _waiting(hass, freezer, *specs):
    coord, made = await _house(hass, freezer, *specs)
    device, eids = made[0]
    await _go_unavailable(hass, freezer, coord, device, eids)
    coord = await restart(hass, freezer, before_setup=_same_values_back(hass, eids))
    await past_grace(hass, freezer)
    await walk(hass, freezer, 2 * 60)
    return coord, made


async def test_the_first_note_and_its_back(hass: HomeAssistant, freezer):
    """Still listed with its values back: the note, its count and two
    buttons. It's Back clears it as a recovery a person confirmed."""
    coord, [(device, _eids)] = await _waiting(hass, freezer, (LISTED, "plug"))
    back = record_events(hass, EVENT_RECOVERED)
    page = coord.page_restart(device.id)
    assert page["name"] == "After a restart" and page["listed"] and page["mode"] is None
    assert page["words"] == (
        "Test devices can report cached values after a restart, so this device is "
        "reported back only when one of its values changes."
    ) or "can report cached values after a restart" in page["words"]
    note = page["note"]
    assert note["name"] == "Back after a restart?"
    assert note["count"] == "This is the first time this has happened to this device."
    assert [b["label"] for b in note["buttons"]] == ["It's Back", "It's Back, This Model Reports Live"]
    assert len(coord._restart_cases(CASE_LISTED)) == 1
    # Counted once, however many minutes pass.
    await walk(hass, freezer, 5 * 60)
    assert len(coord._restart_cases(CASE_LISTED)) == 1

    coord.page_confirm_back(device.id, "James")
    await hass.async_block_till_done()
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    # Its row leaves the Problem List at the next check, where the
    # recovery is told.
    await walk(hass, freezer, 60)
    mine = _mine(back, device.id)
    assert len(mine) == 1
    assert mine[0]["resolved_by"] == "intervention"
    assert coord.confirming(device.id) is None
    assert len(coord._restart_cases(CASE_CONFIRMED)) == 1
    assert coord.page_restart(device.id)["note"] is None
    # Still on the list: nothing about the model changed.
    assert coord._reports_cached(device.id)
    await walk(hass, freezer, 3 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    with pytest.raises(ValueError):
        coord.page_confirm_back(device.id, "James")


async def test_its_back_this_model_reports_live(hass: HomeAssistant, freezer):
    coord, [(device, _eids), (other, _)] = await _waiting(
        hass, freezer, (LISTED, "plug1"), (LISTED, "plug2")
    )
    coord.page_confirm_back(device.id, None, live=True)
    await hass.async_block_till_done()
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    assert not coord._reports_cached(device.id) and not coord._reports_cached(other.id)
    assert coord.page_restart(other.id)["words"] == (
        "All Acme One devices will be reported back as their values return after a restart."
    )


async def test_the_confirmed_recovery_is_told_in_its_own_words(hass: HomeAssistant, freezer):
    """The push and the Daily Brief say who confirmed it."""
    coord, [(device, _eids)] = await _waiting(hass, freezer, (LISTED, "plug"))
    lines: list[str] = []

    class _Seen(list):
        def append(self, event):
            lines.append(event[1])
            super().append(event)

    coord._pending_events = _Seen(coord._pending_events)
    coord.page_confirm_back(device.id, "  James\x07  ")
    await hass.async_block_till_done()
    await walk(hass, freezer, 2 * 60)
    from custom_components.device_sentinel.const import INC_CAUSE, INC_EVENT, INCIDENT_RESOLVED

    resolved = [
        row for row in coord.incident_rows()
        if row.get(INC_EVENT) == INCIDENT_RESOLVED and row.get(INC_CAUSE)
    ][-1]
    said = coord._compose_event(resolved)
    assert said.startswith("At ") and "James confirmed Plug was working, after " in said
    assert said.endswith(" listed as down.")
    assert any(line.endswith(", Plug was confirmed working by James.") for line in lines), lines
    resolved_unnamed = {**resolved, INC_CAUSE: restart_values.confirmed_cause(None)}
    assert "Plug was confirmed working on the Device Sentinel dashboard, after " in (
        coord._compose_event(resolved_unnamed)
    )


async def test_a_frozen_device_on_the_list_is_confirmed_back(hass: HomeAssistant, freezer):
    """It's Back on a device listed frozen restarts its clock, so it is
    not listed again the next minute."""
    coord, [(device, eids)] = await _house(hass, freezer, (LISTED, "plug"))
    rec(coord, device.id)[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 4 * 3600
    await walk(hass, freezer, 2 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    coord = await restart(hass, freezer)
    await walk(hass, freezer, 5 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert coord.restart_pending(device.id)
    assert coord.page_restart(device.id)["note"]["name"] == "Back after a restart?"
    now = dt_util.utcnow().timestamp()
    longest = rec(coord, device.id)[DEV_TODAY_MAX]
    coord.page_confirm_back(device.id, "James")
    await hass.async_block_till_done()
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    assert rec(coord, device.id)[DEV_LAST_ACTIVITY] >= now
    # The hours up to the press are not learned as the device's rhythm.
    assert rec(coord, device.id)[DEV_TODAY_MAX] == longest
    await walk(hass, freezer, 5 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None


# ------------------------------- off the list: Frozen since a restart?


async def _returned_unchanged(hass, freezer, coord, device, eids):
    await _go_unavailable(hass, freezer, coord, device, eids)
    coord = await restart(hass, freezer, before_setup=_same_values_back(hass, eids))
    await walk(hass, freezer, 3 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    return coord


async def test_back_at_a_restart_then_frozen_unchanged_is_the_second_note(
    hass: HomeAssistant, freezer
):
    coord, [(device, eids)] = await _house(hass, freezer, (LIVE, "speaker"))
    coord = await _returned_unchanged(hass, freezer, coord, device, eids)
    assert device.id in coord.data[DATA_RESTART_VALUES]["returns"]
    assert coord.page_restart(device.id)["note"] is None
    # Silent past its rhythm, nothing changed: listed frozen.
    await walk(hass, freezer, 40 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    assert len(coord._restart_cases(CASE_FROZEN)) == 1
    note = coord.page_restart(device.id)["note"]
    assert note["name"] == "Frozen since a restart?"
    assert [b["label"] for b in note["buttons"]] == [
        "This Model Reports Cached Values After a Restart"
    ]
    assert note["buttons"][0]["under"] == (
        "All Acme One devices will be reported back only when one of their values "
        "changes after a restart."
    )
    coord.page_set_restart(device.id, RESTART_MODE_CACHED)
    assert coord._reports_cached(device.id)
    assert coord.page_restart(device.id)["note"] is None
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN


async def test_a_changed_value_after_the_return_ends_the_memory(hass: HomeAssistant, freezer):
    coord, [(device, eids)] = await _house(hass, freezer, (LIVE, "speaker"))
    coord = await _returned_unchanged(hass, freezer, coord, device, eids)
    hass.states.async_set(eids[0], "playing")
    await hass.async_block_till_done()
    assert device.id not in coord.data[DATA_RESTART_VALUES]["returns"]
    await walk(hass, freezer, 40 * 60)
    assert coord._restart_cases(CASE_FROZEN) == []
    assert coord.page_restart(device.id)["note"] is None


async def test_a_return_with_a_new_value_is_not_remembered(hass: HomeAssistant, freezer):
    coord, [(device, eids)] = await _house(hass, freezer, (LIVE, "speaker"))
    await _go_unavailable(hass, freezer, coord, device, eids)

    def _new_values():
        hass.states.async_set(eids[0], "playing")
        hass.states.async_set(eids[1], "off")

    coord = await restart(hass, freezer, before_setup=_new_values)
    await walk(hass, freezer, 3 * 60)
    assert rec(coord, device.id)[DEV_FROZEN_CATEGORY] is None
    assert device.id not in (coord.data.get(DATA_RESTART_VALUES) or {}).get("returns", {})


# -------------------------------------------------------- the two cards


def _case(coord, kind, device, at, arm_at):
    data = coord._restart_data()
    data["cases"].append([at, kind, device.id, coord._power_key(device.id), arm_at])


async def test_card_one_shows_at_two_presses(hass: HomeAssistant, freezer):
    coord, [(first, _), (second, _)] = await _house(
        hass, freezer, (LISTED, "plug1"), (LISTED, "plug2")
    )
    now = dt_util.utcnow().timestamp()
    _case(coord, CASE_CONFIRMED, first, now - 86400, now - 86400)
    assert coord.restart_recommendations() == []
    _case(coord, CASE_CONFIRMED, second, now, now)
    [row] = coord.restart_recommendations()
    assert row["card"] == RESTART_MODE_LIVE and row["button"] == "Set to Reports Live"
    assert row["text"].startswith("Acme One, 2 devices. 2 times since ")
    assert row["text"].endswith(
        "a Acme One was listed as down after a restart with its values back, and was "
        "marked back each time. If these devices are working when that happens, set "
        "the model to report live."
    )
    coord.page_set_restart(row["device_id"], RESTART_MODE_LIVE)
    assert coord.restart_recommendations() == []


async def test_card_two_needs_three_cases_on_two_restarts(hass: HomeAssistant, freezer):
    coord, [(first, _), (second, _)] = await _house(
        hass, freezer, (LIVE, "s1"), (LIVE, "s2")
    )
    now = dt_util.utcnow().timestamp()
    # Three devices' worth on one restart is one event, not three.
    for device in (first, second, first):
        _case(coord, CASE_FROZEN, device, now - 3600, now - 7200)
    assert restarts_in([now - 7200, now - 7200 + 30, now - 7100]) == 1
    assert coord.restart_recommendations() == []
    _case(coord, CASE_FROZEN, second, now, now - 600 - 1)
    [row] = coord.restart_recommendations()
    assert row["card"] == RESTART_MODE_CACHED and row["button"] == "Set to Reports Cached Values"
    assert "4 times since " in row["text"] and "then later listed frozen" in row["text"]
    coord.page_set_restart(row["device_id"], RESTART_MODE_CACHED)
    assert coord.restart_recommendations() == []


# ------------------------------------------------- the count and the record


async def test_the_count_names_the_device_and_its_model(hass: HomeAssistant, freezer):
    coord, [(first, _), (second, _)] = await _waiting(
        hass, freezer, (LISTED, "plug1"), (LISTED, "plug2")
    )
    now = dt_util.utcnow().timestamp()
    start = dt_util.as_local(dt_util.utc_from_timestamp(now - 12 * 86400))
    _case(coord, CASE_LISTED, first, now - 12 * 86400, now - 12 * 86400)
    _case(coord, CASE_LISTED, first, now - 5 * 86400, now - 5 * 86400)
    said = f"This has happened to this device 3 times since {start.strftime('%b')} {start.day}"
    assert coord._restart_count_words(first.id, CASE_LISTED) == f"{said}."
    for _ in range(5):
        _case(coord, CASE_LISTED, second, now - 86400, now - 86400)
    assert coord._restart_count_words(first.id, CASE_LISTED) == (
        f"{said}, and to other Acme One devices 5 times."
    )


async def test_cases_are_kept_as_long_as_history_and_survive_a_restart(
    hass: HomeAssistant, freezer
):
    coord, [(device, _eids)] = await _house(hass, freezer, (LIVE, "speaker"))
    now = dt_util.utcnow().timestamp()
    days = int(entry_of(hass).options.get(CONF_RETENTION_DAYS, 0)) or 90
    _case(coord, CASE_FROZEN, device, now - (days + 400) * 86400, now)
    _case(coord, CASE_FROZEN, device, now - 86400, now)
    coord.data[DATA_RESTART_VALUES]["cases"].append(["damaged"])
    coord._dirty = True
    coord._critical = True
    coord = await restart(hass, freezer)
    rows = coord.data[DATA_RESTART_VALUES]["cases"]
    assert len(rows) == 1 and rows[0][0] == now - 86400
    told = coord.restart_diagnostics()
    assert told["cases"][0]["kind"] == CASE_FROZEN and "integrations" in told
    freezer.tick(timedelta(days=1))
