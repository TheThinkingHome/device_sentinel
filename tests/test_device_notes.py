# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_device_notes.py, Version: 0.29.5 (2026-11-17)

"""A person's own note on a device (rule DEV-19).

One line of the person's words on the device page, empty until written.
It is kept in the answers file with the other answers (rule STOR-20),
so it outlives a restart and a Data Trim (rule CFG-10), and goes with
the device's record. The log says the note changed and where, never its
words; the download says only that a note exists (rule STOR-21).
"""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.answers_store import ANSWERS_STORE_KEY
from custom_components.device_sentinel.const import (
    CONF_TRIM_DEVICES,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    SYS_DETAIL,
    SYS_DEVICE_ID,
    SYS_DEVICE_PAGE,
    SYS_KIND,
)
from custom_components.device_sentinel.device_notes import NOTE_MAX_CHARACTERS
from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics

from .helpers import register_device, setup_entry

NOTE = "Previously the terrace door sensor in the guest room"

_ids = iter(range(1, 10_000))


async def _ws(client, **payload):
    await client.send_json({"id": next(_ids), **payload})
    return await client.receive_json()


async def _house(hass: HomeAssistant, hass_ws_client):
    device, _entities = register_device(hass, "nt0", "Door Terrace")
    entry = await setup_entry(hass)
    client = await hass_ws_client(hass)
    return entry, entry.runtime_data, client, device


def _page_rows(coord, device_id):
    return [row for row in coord.data.get(DATA_SYSTEM_EVENTS) or []
            if row[SYS_KIND] == SYS_DEVICE_PAGE and row.get(SYS_DEVICE_ID) == device_id]


async def test_a_device_starts_with_no_note(hass: HomeAssistant, hass_ws_client):
    _entry, coord, client, device = await _house(hass, hass_ws_client)
    page = await _ws(client, type="device_sentinel/device", device_id=device.id)
    assert page["success"]
    assert page["result"]["identity"]["note"] is None
    assert "notes" not in coord._answers_payload()


async def test_a_note_is_written_shown_and_logged_without_its_words(hass: HomeAssistant, hass_ws_client):
    _entry, coord, client, device = await _house(hass, hass_ws_client)
    reply = await _ws(client, type="device_sentinel/device_note", device_id=device.id, note=f"  {NOTE}  ")
    assert reply["success"], reply
    page = await _ws(client, type="device_sentinel/device", device_id=device.id)
    assert page["result"]["identity"]["note"] == NOTE
    assert coord._answers_payload()["notes"][device.id]["text"] == NOTE
    rows = _page_rows(coord, device.id)
    assert [row[SYS_DETAIL] for row in rows] == ["note added, from its device page"]
    assert NOTE not in json.dumps(coord.data[DATA_SYSTEM_EVENTS])


async def test_a_note_is_changed_and_cleared(hass: HomeAssistant, hass_ws_client):
    _entry, coord, client, device = await _house(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_note", device_id=device.id, note=NOTE)
    await _ws(client, type="device_sentinel/device_note", device_id=device.id, note="Put in service on 10/10/2025")
    assert coord.device_note(device.id) == "Put in service on 10/10/2025"
    # The same words again change nothing and write no row.
    await _ws(client, type="device_sentinel/device_note", device_id=device.id, note="Put in service on 10/10/2025")
    await _ws(client, type="device_sentinel/device_note", device_id=device.id, note="")
    assert coord.device_note(device.id) is None
    assert "notes" not in coord._answers_payload()
    assert [row[SYS_DETAIL] for row in _page_rows(coord, device.id)] == [
        "note added, from its device page", "note changed, from its device page", "note cleared, from its device page"]


@pytest.mark.parametrize(
    "text", ["two\nlines", "a hidden​mark", "x" * (NOTE_MAX_CHARACTERS + 1)],
    ids=["line break", "hidden character", "too long"],
)
async def test_a_note_that_is_not_one_line_of_words_is_refused(hass: HomeAssistant, hass_ws_client, text):
    _entry, coord, client, device = await _house(hass, hass_ws_client)
    reply = await _ws(client, type="device_sentinel/device_note", device_id=device.id, note=text)
    assert not reply["success"] and reply["error"]["code"] == "refused"
    assert coord.device_note(device.id) is None


async def test_accents_and_the_longest_note_are_kept(hass: HomeAssistant, hass_ws_client):
    _entry, coord, client, device = await _house(hass, hass_ws_client)
    start = "Sensor del baño, puesto el 10/10/2025 🔋 "
    text = start + "x" * (NOTE_MAX_CHARACTERS - len(start))
    assert len(text) == NOTE_MAX_CHARACTERS
    reply = await _ws(client, type="device_sentinel/device_note", device_id=device.id, note=text)
    assert reply["success"], reply
    assert coord.device_note(device.id) == text


async def test_an_unknown_device_and_a_reader_are_refused(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    _entry, _coord, client, device = await _house(hass, hass_ws_client)
    reply = await _ws(client, type="device_sentinel/device_note", device_id="nope", note=NOTE)
    assert reply["error"]["code"] == "not_found"
    reader = await hass_ws_client(hass, hass_read_only_access_token)
    reply = await _ws(reader, type="device_sentinel/device_note", device_id=device.id, note=NOTE)
    assert not reply["success"] and reply["error"]["code"] == "unauthorized"


async def test_a_note_outlives_a_restart_and_a_bad_one_is_dropped(hass: HomeAssistant, hass_ws_client, hass_storage):
    entry, coord, client, device = await _house(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_note", device_id=device.id, note=NOTE)
    await coord.async_flush_answers()
    data = hass_storage[ANSWERS_STORE_KEY]["data"]
    assert data["notes"][device.id]["text"] == NOTE
    data["notes"]["broken"] = {"text": 7}
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    assert coord.device_note(device.id) == NOTE
    assert coord.device_note("broken") is None


async def test_a_data_trim_keeps_the_note(hass: HomeAssistant, hass_ws_client):
    """A trim lets a device with bad data start over; the person's own
    words about it are an answer, and answers stay (rule CFG-10)."""
    entry, coord, client, device = await _house(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_note", device_id=device.id, note=NOTE)
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_TRIM_DEVICES: [device.id]})
    await hass.async_block_till_done()
    assert coord.device_note(device.id) == NOTE


async def test_a_note_stays_while_its_device_is_in_home_assistant(hass: HomeAssistant, hass_ws_client):
    """Excluded, a device keeps no record, and keeps its note; gone from
    Home Assistant with no record held, it loses it (rule DEV-19)."""
    _entry, coord, client, device = await _house(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_note", device_id=device.id, note=NOTE)
    del coord.data[DATA_DEVICES][device.id]
    coord._settle_notes()
    assert coord.device_note(device.id) == NOTE
    dr.async_get(hass).async_remove_device(device.id)
    coord.data[DATA_DEVICES].pop(device.id, None)
    coord._settle_notes()
    assert coord.device_note(device.id) is None


async def test_the_download_says_a_note_exists_and_never_its_words(hass: HomeAssistant, hass_ws_client):
    entry, coord, client, device = await _house(hass, hass_ws_client)
    await _ws(client, type="device_sentinel/device_note", device_id=device.id, note=NOTE)
    out = await async_get_config_entry_diagnostics(hass, entry)
    assert out["devices"][device.id]["has_note"] is True
    assert out["answers"]["notes"] == 1
    assert NOTE not in json.dumps(out, default=str)
    assert "guest room" not in json.dumps(out, default=str).lower()


async def test_a_note_edited_into_the_file_is_held_to_what_the_pencil_accepts(hass: HomeAssistant, hass_ws_client):
    """A note too long, or holding a hidden character, is dropped and
    counted, as any malformed answer is (rule STOR-20)."""
    _entry, coord, _client, device = await _house(hass, hass_ws_client)
    dropped = coord._notes_read({
        device.id: {"text": "x" * 501, "set": "2026-11-17T08:00:00+00:00"},
        "other": {"text": "line one\nline two", "set": "2026-11-17T08:00:00+00:00"},
        "fine": {"text": "Put in service on 10 October 2025", "set": "2026-11-17T08:00:00+00:00"},
    })
    assert dropped == 2
    assert coord.device_note(device.id) is None
    assert coord.device_note("fine") == "Put in service on 10 October 2025"
