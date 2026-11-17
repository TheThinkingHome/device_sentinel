# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_names.py, Version: 0.29.5 (2026-11-17)

"""The diagnostics download names nothing of the house (rule STOR-21).

A download is often attached to a public issue. Each device, area,
label, Wi-Fi network and router tracker is shown by a numbered
stand-in that keeps its number in every download, and the name part of
each entity id by its device's. The key back to the names is written
to the reports folder, never into the download.

The house test seats each test house, plants a name on every device,
area, label and entity, and reads the whole download for any of them.
Pointed at the private archive (DEVICE_SENTINEL_FLEET_DIR), where each
house holds a real download, it seats the real names instead.
"""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_EPISODES,
    DATA_INCIDENTS,
    DATA_TODO_ITEMS,
    REPORT_DIR,
)
from custom_components.device_sentinel.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.device_sentinel.stand_ins import (
    KEY_FILE,
    STAND_INS_KEY,
    StandInBook,
)

from tests.conftest import fleet_data, fleet_path
from tests.helpers import register_device, setup_entry

PLANT = "Pqz"


def _text(download) -> str:
    return json.dumps(download, ensure_ascii=False)


async def _download(hass: HomeAssistant, entry):
    return await async_get_config_entry_diagnostics(hass, entry)


def _key(hass: HomeAssistant) -> str:
    return Path(hass.config.path(REPORT_DIR, KEY_FILE)).read_text(encoding="utf-8")


# --------------------------------------------------------- a small house


async def _small_house(hass: HomeAssistant):
    areas = ar.async_get(hass)
    labels = lr.async_get(hass)
    terrace = areas.async_create("Terrace")
    spare = labels.async_create("Spare Parts")
    door, _ = register_device(hass, "door", "Terrace Door")
    lamp, _ = register_device(hass, "lamp", "Lamp Of Janet")
    twin, _ = register_device(hass, "twin", "Terrace Door")
    devices = dr.async_get(hass)
    devices.async_update_device(door.id, area_id=terrace.id, labels={spare.label_id})
    devices.async_update_device(twin.id, area_id=terrace.id)
    entry = await setup_entry(hass, {"muted_labels": [spare.label_id]})
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    return entry, coord, door, lamp, twin, terrace, spare


async def test_names_are_numbers_and_the_key_tells_them_back(hass: HomeAssistant):
    entry, coord, door, lamp, twin, terrace, spare = await _small_house(hass)
    # A row that kept an older name, as an incident does after a rename.
    coord.data[DATA_INCIDENTS] = [
        {"device_id": lamp.id, "name": "Janet's Old Lamp", "kind": "frozen", "event": "opened", "when": 1.0},
    ]
    coord.data[DATA_TODO_ITEMS] = [
        {"uid": "u1", "device_id": door.id, "summary": "Terrace Door: battery 10%",
         "description": "Lamp Of Janet and Terrace Door share a Wi-Fi channel.", "status": "needs_action",
         "sort_name": "Terrace Door"},
    ]
    download = await _download(hass, entry)
    text = _text(download)
    for name in ("Terrace", "Janet", "Spare Parts", "spare_parts", "terrace_door", "lamp_of_janet"):
        assert name not in text, name
    rows = download["devices"]
    word = {device_id: row["name"] for device_id, row in rows.items()}
    assert sorted(word.values()) == ["Device 1", "Device 2", "Device 3"]
    # Devices sharing an area, and sharing a name, still show it.
    assert rows[door.id]["area"] == rows[twin.id]["area"] == "Area 1"
    assert rows[door.id]["shares_name_with"] == [word[twin.id]]
    assert rows[lamp.id]["shares_name_with"] == []
    # The row keeps its device's number whatever name it recorded.
    assert download["incidents"][0]["name"] == word[lamp.id]
    item = download["todo_items"][0]
    assert item["summary"] == f"{word[door.id]}: battery 10%"
    assert item["description"] == (
        f"{word[lamp.id]} and {word[door.id]} share a Wi-Fi channel."
    )
    assert download["entry_options"]["muted_labels"] == ["Label 1"]
    # The entity id keeps what it reads, and loses whose it is.
    ids = {row["entity_id"] for row in rows[door.id]["all_entities"]}
    assert ids == {f"sensor.{word[door.id].lower().replace(' ', '_')}"}
    # The key, beside the reports, tells each number back, and only the
    # person can read it.
    key = _key(hass)
    assert f"| {word[lamp.id]} | Lamp Of Janet |" in key
    assert "| Area 1 | Terrace |" in key
    assert "| Label 1 | Spare Parts |" in key
    mode = stat.S_IMODE(os.stat(hass.config.path(REPORT_DIR, KEY_FILE)).st_mode)
    assert mode == 0o600


async def test_a_device_keeps_its_number_and_a_number_is_never_given_twice(hass: HomeAssistant, hass_storage):
    entry, coord, door, lamp, twin, terrace, spare = await _small_house(hass)
    first = (await _download(hass, entry))["devices"]
    # Removed from Home Assistant, and a new device added.
    dr.async_get(hass).async_remove_device(twin.id)
    coord.data[DATA_DEVICES].pop(twin.id, None)
    plug, _ = register_device(hass, "plug", "Garden Plug")
    coord._rebuild_registry_view()
    second = (await _download(hass, entry))["devices"]
    assert second[door.id]["name"] == first[door.id]["name"]
    assert second[lamp.id]["name"] == first[lamp.id]["name"]
    assert second[plug.id]["name"] == "Device 4"
    # The table is kept between starts, in its own file.
    stored = hass_storage[STAND_INS_KEY]
    assert stored["data"]["next"]["device"] == 5
    # The removed device's number stays its own.
    assert stored["data"]["device"][twin.id]["n"] == int(first[twin.id]["name"].split()[1])


def test_a_book_never_gives_a_number_below_one_it_gave():
    book = StandInBook({"device": {"a": {"n": 7}, "b": {"n": "x"}}, "next": {"device": 3}})
    assert book.word("device", "a") == "Device 7"
    assert book.word("device", "c") == "Device 8"
    assert book.word("device", "b") == "Device 9"
    assert StandInBook("not a table").word("label", "x") == "Label 1"


async def test_networks_and_trackers_keep_their_numbers(hass: HomeAssistant):
    from custom_components.device_sentinel.diagnostics import _redact_addresses

    book = StandInBook()
    first = _redact_addresses({"ssid": "Smith Home", "t": "device_tracker.janes_iphone is away"}, (), book)
    later = _redact_addresses({"t": "device_tracker.bobs_phone; device_tracker.janes_iphone", "ssid": "Smith Home"}, (), book)
    assert first == {"ssid": "SSID-01", "t": "device_tracker.tracker_01 is away"}
    assert later == {"t": "device_tracker.tracker_02; device_tracker.tracker_01", "ssid": "SSID-01"}


async def test_a_device_named_for_its_model_keeps_its_model(hass: HomeAssistant):
    device, _ = register_device(hass, "printer", "HL-L2370DW")
    dr.async_get(hass).async_update_device(device.id, manufacturer="Brother", model="HL-L2370DW")
    entry = await setup_entry(hass)
    entry.runtime_data._rebuild_registry_view()
    row = (await _download(hass, entry))["devices"][device.id]
    assert row["name"] == "Device 1"
    assert row["model"] == "HL-L2370DW"
    assert row["manufacturer"] == "Brother"


async def test_a_short_name_is_hidden_where_it_stands_and_never_in_a_sentence(hass: HomeAssistant):
    device, _ = register_device(hass, "hundred", "100")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    coord.data[DATA_TODO_ITEMS] = [
        {"uid": "u", "device_id": device.id, "summary": "battery 100%", "sort_name": "100"},
    ]
    item = (await _download(hass, entry))["todo_items"][0]
    assert item["sort_name"] == "Device 1"
    assert item["summary"] == "battery 100%"


async def test_a_name_inside_a_longer_word_is_left(hass: HomeAssistant):
    device, _ = register_device(hass, "den", "Den")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    coord.data[DATA_EPISODES] = [{"device_id": "other", "name": "Garden plug", "since": 1.0}]
    coord.data[DATA_TODO_ITEMS] = [
        {"uid": "u", "summary": "Garden plug next to the Den: unavailable"},
    ]
    download = await _download(hass, entry)
    assert download["todo_items"][0]["summary"] == f"Device 2 next to the {download['devices'][device.id]['name']}: unavailable"


# ------------------------------------------------------ the test houses

HOUSES = ("reference", "second", "third", "fourth", "fifth", "sixth")
_ALIAS = re.compile(r"\bDevice (\d+)\b")


def _house_files(house: str) -> tuple[Path | None, Path | None]:
    folder = fleet_path(house)
    if not folder.is_dir():
        return None, None
    downloads = sorted(folder.glob("*config_entry*.json"))
    storage = next(
        (folder / name for name in ("device_sentinel_storage.json", "device_sentinel.storage")
         if (folder / name).exists()),
        None,
    )
    return (downloads[0] if downloads else None), storage


def _rows_with_names(data, found: set[str]) -> None:
    if isinstance(data, dict):
        if isinstance(data.get("device_id"), str):
            for key in ("name", "sort_name", "removed_name"):
                if isinstance(data.get(key), str):
                    found.add(data[key])
        for value in data.values():
            _rows_with_names(value, found)
    elif isinstance(data, list):
        for value in data:
            _rows_with_names(value, found)


async def _seat(hass: HomeAssistant, house: str):
    """The house onto a Home Assistant, under its own names or planted
    ones. Returns the entry and the names that must not appear."""
    download_path, storage_path = _house_files(house)
    if download_path is None:
        pytest.skip("house absent")
    download = json.loads(download_path.read_text(encoding="utf-8"))
    download = download.get("data", download)
    real = "incidents" in download
    data = fleet_data(storage_path) if storage_path is not None else {}
    if not data.get("devices"):
        data = {
            **{k: v for k, v in download.items() if isinstance(v, list)},
            "devices": {i: row.get("statistics") or {} for i, row in download["devices"].items()},
        }
    names = {i: row.get("name") for i, row in download["devices"].items() if isinstance(row, dict)}
    text = json.dumps(data, ensure_ascii=False)
    if not real:
        # The anonymized houses read "Device 160": each becomes a name of
        # its own that cannot be taken for a stand-in.
        text = _ALIAS.sub(lambda m: f"{PLANT} Lamp {m.group(1)}", text)
        names = {i: _ALIAS.sub(lambda m: f"{PLANT} Lamp {m.group(1)}", n or "") for i, n in names.items()}
    source = MockConfigEntry(domain="test", title="")
    source.add_to_hass(hass)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    areas = ar.async_get(hass)
    labels = lr.async_get(hass)
    live: dict[str, str] = {}
    for n, (old_id, name) in enumerate(sorted(names.items())):
        row = download["devices"][old_id]
        device = devices.async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("test", old_id)},
            name=name or None,
            manufacturer=row.get("manufacturer"),
            model=row.get("model"),
        )
        live[old_id] = device.id
        if real:
            for entity in row.get("all_entities") or []:
                domain, _, object_id = entity["entity_id"].partition(".")
                entities.async_get_or_create(
                    domain, "test", entity["entity_id"], suggested_object_id=object_id,
                    device_id=device.id, config_entry=source,
                )
            area = row.get("area")
        else:
            slug = slugify(name)
            for domain, suffix in (("sensor", "battery"), ("binary_sensor", "contact")):
                entities.async_get_or_create(
                    domain, "test", f"{old_id}{suffix}", suggested_object_id=f"{slug}_{suffix}",
                    device_id=device.id, config_entry=source,
                )
            entities.async_get_or_create(
                "sensor", "test", f"{old_id}other", suggested_object_id=f"{PLANT.lower()} other {n}",
                device_id=device.id, config_entry=source,
            )
            area = f"{PLANT} Room {n % 5}"
        if isinstance(area, str) and area:
            place = areas.async_get_area_by_name(area) or areas.async_create(area)
            devices.async_update_device(device.id, area_id=place.id)
    for old_id, new_id in live.items():
        text = text.replace(old_id, new_id)
    data = json.loads(text)
    options = dict(download.get("entry_options") or {})
    for key in [k for k in options if k.endswith("_labels")]:
        made = []
        for label_id in options[key] or []:
            label = labels.async_get_label(label_id) or labels.async_create(
                label_id.replace("_", " ") if real else f"{PLANT} Tag {label_id}"
            )
            made.append(label.label_id)
        options[key] = made
    if not real:
        tag = labels.async_create(f"{PLANT} Tag")
        options["muted_labels"] = [tag.label_id]
    options = {k: v for k, v in options.items() if not isinstance(v, str) or "REDACTED" not in v}
    entry = await setup_entry(hass, options)
    coord = entry.runtime_data
    for old_id, record in (data.get("devices") or {}).items():
        if isinstance(record, dict):
            coord.data[DATA_DEVICES][old_id] = dict(record)
    for key in ("system_events", "incidents", "silence_episodes", "todo_items", "todo_journal",
                "short_drops", "short_drop_days", "address_changes", "signal_stress", "storm_days"):
        if isinstance(data.get(key), list):
            coord.data[key] = data[key]
    coord._rebuild_registry_view()
    hidden: set[str] = set(n for n in names.values() if n)
    _rows_with_names(data, hidden)
    hidden |= {a.name for a in areas.async_list_areas()}
    hidden |= {lab.name for lab in labels.async_list_labels()}
    return entry, hidden, real


def _kept_words(download) -> set[str]:
    """What a device is, kept on purpose: a name equal to one is no leak."""
    kept: set[str] = set()

    def every(value):
        if isinstance(value, str):
            kept.add(value)
        elif isinstance(value, dict):
            for inner in value.values():
                every(inner)
        elif isinstance(value, list):
            for inner in value:
                every(inner)

    def walk(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                if key in ("manufacturer", "model", "model_id", "maker", "model_name", "sw_version", "hw_version") and isinstance(inner, str):
                    kept.add(inner)
                # What a device is and what powers it: a device named
                # "Fan" whose type reads "Fan".
                if key in ("type", "power"):
                    every(inner)
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)

    walk(download)
    return kept


@pytest.mark.parametrize("house", HOUSES)
async def test_a_house_download_names_nothing_of_the_house(hass: HomeAssistant, house: str):
    entry, hidden, real = await _seat(hass, house)
    download = await _download(hass, entry)
    text = _text(download)
    if not real:
        assert PLANT not in text and PLANT.lower() not in text
        return
    kept = _kept_words(download)
    leaks = sorted(
        name for name in hidden
        if len(name) >= 3 and any(ch.isalpha() for ch in name) and name not in kept
        and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text)
    )
    assert leaks == []
    slugs = {slugify(name) for name in hidden if len(slugify(name)) >= 4 and name not in kept}
    ids = set(re.findall(r"\b[a-z_]+\.([a-z0-9_]+)\b", text))
    assert not [i for i in ids for s in slugs if re.search(rf"(?:^|_){s}(?:_|$)", i)]


async def test_a_device_page_act_hides_a_name_since_changed_and_an_area_since_deleted(hass: HomeAssistant):
    from custom_components.device_sentinel.const import DATA_SYSTEM_EVENTS, SYS_DEVICE_PAGE

    entry, coord, door, lamp, twin, terrace, spare = await _small_house(hass)
    events = [
        ("renamed Janet's Desk Lamp, from its device page", "renamed {own}, from its device page"),
        ("moved to Janet's Room, a new area, from the Devices tab", "moved to Area 1, a new area, from the Devices tab"),
        ("moved to Terrace, from its device page", "moved to Area 2, from its device page"),
        ("label Spare Parts added, from its device page", "label Label 1 added, from its device page"),
        ("label Old Kit removed, from its device page", "label Label 2 removed, from its device page"),
        ("set to its parent's area, Terrace, from its device page", "set to its parent's area, Area 2, from its device page"),
        ("note added, from its device page", "note added, from its device page"),
        ("freeze muted by label Old Kit, on 3 devices, from its device page",
         "freeze muted by label Label 2, on 3 devices, from its device page"),
    ]
    coord.data[DATA_SYSTEM_EVENTS] = [
        {"when": 1.0, "kind": SYS_DEVICE_PAGE, "scope": "system", "detail": said, "device_id": lamp.id}
        for said, _ in events
    ]
    download = await _download(hass, entry)
    own = download["devices"][lamp.id]["name"]
    rows = [row["detail"] for row in download["system_events"] if row.get("kind") == SYS_DEVICE_PAGE]
    assert rows == [shown.format(own=own) for _, shown in events]
    key = _key(hass)
    # Numbered as the download first needs them.
    assert "| Area 1 | Janet's Room |" in key
    assert "| Area 2 | Terrace |" in key
    assert "| Label 2 | Old Kit |" in key


async def test_a_label_named_like_a_word_is_never_taken_from_a_sentence(hass: HomeAssistant):
    """A label is said only where a device page records it: "Battery" as
    a label leaves "Battery 10% since ..." as it is."""
    battery = lr.async_get(hass).async_create("Battery")
    device, _ = register_device(hass, "door", "Front Door")
    entry = await setup_entry(hass, {"battery_muted_labels": [battery.label_id]})
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    coord.data[DATA_TODO_ITEMS] = [
        {"uid": "u", "device_id": device.id, "summary": "Front Door: battery 10%",
         "description": "Battery 10% since October 26, 2026 at 9:48 AM."},
    ]
    download = await _download(hass, entry)
    assert download["todo_items"][0]["description"] == "Battery 10% since October 26, 2026 at 9:48 AM."
    assert download["entry_options"]["battery_muted_labels"] == ["Label 1"]


async def test_a_long_name_is_hidden_where_a_sentence_cuts_it(hass: HomeAssistant):
    """A name past 60 characters is said cut, ending "…", on the Problem
    List and in the brief; the cut form is hidden too (rule DEV-03)."""
    from custom_components.device_sentinel.naming import fitted_name

    long_name = "Hallway motion sensor by the stairs to the basement, left of the door"
    device, _ = register_device(hass, "long", long_name)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    cut = fitted_name(long_name)
    assert cut != long_name and cut.endswith("…")
    coord.data[DATA_TODO_ITEMS] = [{"uid": "u", "summary": f"{cut}: unavailable"}]
    download = await _download(hass, entry)
    assert download["todo_items"][0]["summary"] == f"{download['devices'][device.id]['name']}: unavailable"
    assert "Hallway motion" not in _text(download)
