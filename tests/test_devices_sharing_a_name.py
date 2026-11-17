# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_devices_sharing_a_name.py, Version: 0.29.5 (2026-11-17)

"""Devices of one name are told apart by their areas (rule REC-04).

Home Assistant 2026.11 asks people to name each device for what it is
and let the area tell devices of one name apart: three TIMMERFLOTTE
sensors in three rooms is the expected way. Devices Sharing A Name and
the rename warning list a device only when another of its name is in
the same area, or when it has no area to tell it apart.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.device_actions import NameInUse
from custom_components.device_sentinel.naming import cannot_be_told_apart, devices_sharing_a_name

from .helpers import setup_entry

SOURCE = "guntamatic"
NAME = "TIMMERFLOTTE temp/hmd sensor"


# ------------------------------------------------------------- the rule


@pytest.mark.parametrize(
    ("a", "b", "apart"),
    [
        ((NAME, "Kitchen"), (NAME, "Office"), True),
        ((NAME, "Kitchen"), (NAME.upper(), "kitchen"), False),
        ((NAME, None), (NAME, "Office"), False),
        ((NAME, "Kitchen"), (NAME, None), True),
        ((NAME, None), (NAME, None), False),
        ((NAME, "Kitchen"), ("Other sensor", "Kitchen"), True),
        (("", None), ("", None), True),
    ],
)
def test_two_devices_are_told_apart_by_name_or_area(a, b, apart):
    """The second one's area tells it apart only when the first has one
    too; a device with no area is told apart by its name alone."""
    assert cannot_be_told_apart(*a, *b) is (not apart)


def test_three_sensors_in_three_rooms_are_not_listed():
    shown = {"a": (NAME, "Kitchen"), "b": (NAME, "Office"), "c": (NAME, "Bedroom")}
    assert devices_sharing_a_name(shown) == []


def test_two_in_one_room_are_listed_and_the_third_is_not():
    shown = {"a": (NAME, "Kitchen"), "b": (NAME, "Kitchen"), "c": (NAME, "Office")}
    assert sorted(devices_sharing_a_name(shown)) == ["a", "b"]


def test_one_with_no_area_is_listed_and_the_one_in_a_room_is_not():
    """The one with no area has nothing beside its name; the other reads
    with its room (rule NOTE-13)."""
    shown = {"a": (NAME, "Kitchen"), "b": (NAME, None)}
    assert devices_sharing_a_name(shown) == ["b"]


def test_two_that_read_the_same_in_a_notification_are_listed():
    """A name ending in a bracket is printed without its area, so two in
    two rooms read the same on the phone and are listed (rule NOTE-13)."""
    shown = {"a": ("Thermostat (Z-Wave)", "Kitchen"), "b": ("Thermostat (Z-Wave)", "Hall")}
    assert sorted(devices_sharing_a_name(shown)) == ["a", "b"]


def test_a_short_area_inside_a_longer_name_does_not_hide_it():
    shown = {"a": ("Garden plug", "Den"), "b": ("Garden plug", "Garden")}
    assert devices_sharing_a_name(shown) == []


def test_a_name_alone_is_never_listed():
    assert devices_sharing_a_name({"a": (NAME, None)}) == []


# ------------------------------------------------- on a running house


def _sensor(hass: HomeAssistant, source, uid: str, name: str, area_id: str | None):
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(SOURCE, uid)},
        name=name, manufacturer="IKEA of Sweden", model="TIMMERFLOTTE",
    )
    if area_id:
        registry.async_update_device(device.id, area_id=area_id)
    er.async_get(hass).async_get_or_create(
        "sensor", SOURCE, f"{uid}_temperature", device_id=device.id, config_entry=source,
    )
    return device.id


def _house(hass: HomeAssistant, rooms: list[str | None]):
    source = MockConfigEntry(domain=SOURCE, title="Sensors")
    source.add_to_hass(hass)
    areas = ar.async_get(hass)
    made: dict[str, str] = {}
    ids = []
    for i, room in enumerate(rooms):
        area_id = None
        if room:
            if room not in made:
                made[room] = areas.async_create(room).id
            area_id = made[room]
        ids.append(_sensor(hass, source, f"s{i}", NAME, area_id))
    return ids


def _card(coordinator):
    return next((c for c in coordinator.device_recommendations() if c["kind"] == "names"), None)


async def test_sensors_in_their_own_rooms_raise_no_card(hass: HomeAssistant, hass_storage):
    """Three sensors of one name, each in its own room."""
    _house(hass, ["Kitchen", "Office", "Bedroom"])
    entry = await setup_entry(hass)
    assert _card(entry.runtime_data) is None


async def test_two_in_one_room_raise_the_card(hass: HomeAssistant, hass_storage):
    ids = _house(hass, ["Kitchen", "Kitchen", "Office"])
    entry = await setup_entry(hass)
    card = _card(entry.runtime_data)
    assert card is not None
    assert sorted(row["device_id"] for row in card["devices"]) == sorted(ids[:2])
    assert card["body"].startswith("2 devices have the same name as another device in the same area")


async def test_one_without_an_area_is_listed_with_its_area_not_set(hass: HomeAssistant, hass_storage):
    ids = _house(hass, ["Kitchen", None])
    entry = await setup_entry(hass)
    card = _card(entry.runtime_data)
    assert [row["device_id"] for row in card["devices"]] == [ids[1]]
    assert card["devices"][0]["area"] is None
    assert "set the area where it reads Not Set" in card["body"]
    assert card["body"].startswith("1 device has the same name")
    assert "tell it apart" in card["body"]


# ------------------------------------------------------ the rename warning


async def test_renaming_to_a_name_used_in_another_room_is_not_held(hass: HomeAssistant, hass_storage):
    source = MockConfigEntry(domain=SOURCE, title="Sensors")
    source.add_to_hass(hass)
    areas = ar.async_get(hass)
    kitchen, office = areas.async_create("Kitchen").id, areas.async_create("Office").id
    _sensor(hass, source, "a", NAME, kitchen)
    other = _sensor(hass, source, "b", "Sensor B", office)
    entry = await setup_entry(hass)
    entry.runtime_data.page_rename(other, NAME)
    assert dr.async_get(hass).async_get(other).name_by_user == NAME


async def test_renaming_to_a_name_used_in_the_same_room_is_held(hass: HomeAssistant, hass_storage):
    source = MockConfigEntry(domain=SOURCE, title="Sensors")
    source.add_to_hass(hass)
    kitchen = ar.async_get(hass).async_create("Kitchen").id
    _sensor(hass, source, "a", NAME, kitchen)
    other = _sensor(hass, source, "b", "Sensor B", kitchen)
    entry = await setup_entry(hass)
    with pytest.raises(NameInUse) as held:
        entry.runtime_data.page_rename(other, NAME.lower())
    assert held.value.area == "Kitchen"


async def test_renaming_beside_a_device_with_no_area_is_held(hass: HomeAssistant, hass_storage):
    """The one with no area could no longer be told apart, so the rename
    asks first, either way round."""
    source = MockConfigEntry(domain=SOURCE, title="Sensors")
    source.add_to_hass(hass)
    kitchen = ar.async_get(hass).async_create("Kitchen").id
    _sensor(hass, source, "a", NAME, None)
    other = _sensor(hass, source, "b", "Sensor B", kitchen)
    entry = await setup_entry(hass)
    with pytest.raises(NameInUse) as held:
        entry.runtime_data.page_rename(other, NAME)
    assert held.value.area is None


# ------------------------------------------------------ the move warning


async def test_moving_into_a_room_with_a_device_of_the_same_name_is_held(hass: HomeAssistant, hass_storage):
    """A move is checked as a rename is: into a room where a device of the
    same name already is, it asks first (rules REC-04, DASH-10)."""
    source = MockConfigEntry(domain=SOURCE, title="Sensors")
    source.add_to_hass(hass)
    areas = ar.async_get(hass)
    kitchen, office = areas.async_create("Kitchen").id, areas.async_create("Office").id
    _sensor(hass, source, "a", NAME, kitchen)
    other = _sensor(hass, source, "b", NAME, office)
    entry = await setup_entry(hass)
    with pytest.raises(NameInUse) as held:
        entry.runtime_data.page_set_area(other, kitchen)
    assert held.value.area == "Kitchen"
    assert dr.async_get(hass).async_get(other).area_id == office
    entry.runtime_data.page_set_area(other, kitchen, confirm=True)
    assert dr.async_get(hass).async_get(other).area_id == kitchen


async def test_moving_into_a_room_of_its_own_is_not_held(hass: HomeAssistant, hass_storage):
    source = MockConfigEntry(domain=SOURCE, title="Sensors")
    source.add_to_hass(hass)
    areas = ar.async_get(hass)
    kitchen, office, bedroom = (areas.async_create(r).id for r in ("Kitchen", "Office", "Bedroom"))
    _sensor(hass, source, "a", NAME, kitchen)
    other = _sensor(hass, source, "b", NAME, office)
    entry = await setup_entry(hass)
    entry.runtime_data.page_set_area(other, bedroom)
    assert dr.async_get(hass).async_get(other).area_id == bedroom


async def test_taking_away_the_area_beside_a_device_of_the_same_name_is_held(hass: HomeAssistant, hass_storage):
    """With no area it could no longer be told apart from the one in the
    Kitchen."""
    source = MockConfigEntry(domain=SOURCE, title="Sensors")
    source.add_to_hass(hass)
    areas = ar.async_get(hass)
    kitchen, office = areas.async_create("Kitchen").id, areas.async_create("Office").id
    _sensor(hass, source, "a", NAME, kitchen)
    other = _sensor(hass, source, "b", NAME, office)
    entry = await setup_entry(hass)
    with pytest.raises(NameInUse):
        entry.runtime_data.page_set_area(other, None)
    assert dr.async_get(hass).async_get(other).area_id == office


async def test_a_new_area_named_as_a_room_with_the_same_name_is_held_and_makes_nothing(hass: HomeAssistant, hass_storage):
    source = MockConfigEntry(domain=SOURCE, title="Sensors")
    source.add_to_hass(hass)
    areas = ar.async_get(hass)
    kitchen, office = areas.async_create("Kitchen").id, areas.async_create("Office").id
    _sensor(hass, source, "a", NAME, kitchen)
    other = _sensor(hass, source, "b", NAME, office)
    entry = await setup_entry(hass)
    with pytest.raises(NameInUse):
        entry.runtime_data.page_new_area(other, "kitchen")
    count = len(areas.async_list_areas())
    entry.runtime_data.page_new_area(other, "Pantry")
    assert len(areas.async_list_areas()) == count + 1
    assert dr.async_get(hass).async_get(other).area_id == areas.async_get_area_by_name("Pantry").id


async def test_the_page_asks_and_moves_on_a_yes(hass: HomeAssistant, hass_storage, hass_ws_client):
    source = MockConfigEntry(domain=SOURCE, title="Sensors")
    source.add_to_hass(hass)
    areas = ar.async_get(hass)
    kitchen, office = areas.async_create("Kitchen").id, areas.async_create("Office").id
    _sensor(hass, source, "a", NAME, kitchen)
    other = _sensor(hass, source, "b", NAME, office)
    await setup_entry(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "device_sentinel/device_area", "device_id": other, "area_id": kitchen})
    reply = await client.receive_json()
    assert not reply["success"] and reply["error"]["code"] == "name_in_use"
    assert reply["error"]["message"] == f"Another device is already named {NAME} (in the Kitchen)."
    await client.send_json({"id": 2, "type": "device_sentinel/device_area", "device_id": other, "area_id": kitchen, "confirm": True})
    assert (await client.receive_json())["success"]
    assert dr.async_get(hass).async_get(other).area_id == kitchen
