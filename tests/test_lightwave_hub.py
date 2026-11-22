# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_lightwave_hub.py, Version: 0.30.2 (2026-11-22)

"""A Lightwave hub judged by its Cloud Link sensor (rule STACK-17).

The layout of a Lightwave Smart house with Cloud Link, as a tester's files show
it: the hub is a service device carrying Cloud Link; each radio device
("<name> Device", with its Connected sensor) is registered via the hub;
each light or socket via its radio device. When the hub's network cable
was pulled, Cloud Link read off 2 minutes 23 seconds later and every
Connected sensor read unavailable; nothing was listed in the 13 minutes
it lasted. Here the same hub is one row, its devices wait for it, and
they keep their own judgment while it is up.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
)

from .helpers import record_events, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, walk

DOMAIN = "lightwave_smart"
HOUR = 3600.0


def _house(hass, cloud=True):
    source = MockConfigEntry(domain=DOMAIN)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    devices = dr.async_get(hass)
    reg = er.async_get(hass)
    hub = devices.async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(DOMAIN, "hub-fs")},
        name="LinkPlus", model="L2", entry_type=dr.DeviceEntryType.SERVICE,
    )
    radio = devices.async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(DOMAIN, "dev-1")}, name="Power Monitor Device", model="L40MK2",
    )
    radio = devices.async_update_device(radio.id, via_device_id=hub.id)
    socket = devices.async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(DOMAIN, "fs-1")}, name="Power Monitor", model="L40MK2",
    )
    socket = devices.async_update_device(socket.id, via_device_id=radio.id)
    ids = {}
    if cloud:
        ids["cloud"] = reg.async_get_or_create(
            "binary_sensor", DOMAIN, "hub-fs_cloudLink", device_id=hub.id, config_entry=source,
            entity_category=EntityCategory.DIAGNOSTIC,
        ).entity_id
    ids["dawn"] = reg.async_get_or_create(
        "sensor", DOMAIN, "hub-fs_dawnTime", device_id=hub.id, config_entry=source,
        entity_category=EntityCategory.DIAGNOSTIC,
    ).entity_id
    ids["link"] = reg.async_get_or_create(
        "binary_sensor", DOMAIN, "dev-1_connectivity", device_id=radio.id, config_entry=source,
        entity_category=EntityCategory.DIAGNOSTIC,
    ).entity_id
    ids["update"] = reg.async_get_or_create(
        "update", DOMAIN, "dev-1_firmware", device_id=radio.id, config_entry=source,
        entity_category=EntityCategory.DIAGNOSTIC,
    ).entity_id
    ids["power"] = reg.async_get_or_create(
        "sensor", DOMAIN, "fs-1_power", device_id=socket.id, config_entry=source,
    ).entity_id
    return hub, radio, socket, ids


async def _ready(hass, freezer, cloud=True, options=None):
    freezer.move_to(PIN)
    hub, radio, socket, ids = _house(hass, cloud=cloud)
    for key, value in (("cloud", "on"), ("dawn", "2026-10-11T12:32:00+00:00"), ("link", "on"),
                       ("update", "off"), ("power", "12.0")):
        if key in ids:
            hass.states.async_set(ids[key], value)
    coord = await setup_coordinator(hass, options(hub) if options else None)
    records = {"socket": arm(coord, socket.id, rhythm=HOUR), "radio": arm(coord, radio.id, rhythm=HOUR)}
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    hass.states.async_set(ids["power"], "13.0")
    await hass.async_block_till_done()
    return coord, {"hub": hub, "radio": radio, "socket": socket}, ids, records


def _item(coord, device_id):
    return next((i for i in coord.todo_items if i["device_id"] == device_id), None)


async def test_the_service_hub_is_watched_and_holds_its_devices(hass: HomeAssistant, freezer):
    coord, dev, _ids, _records = await _ready(hass, freezer)
    hub = dev["hub"].id
    assert hub in coord._watched, "a service device carrying Cloud Link is watched"
    assert coord.is_hub(hub)
    assert coord.hub_of(dev["radio"].id) == hub and coord.hub_of(dev["socket"].id) == hub
    assert not coord.judged_by_hub(dev["socket"].id), "its devices keep their own judgment"


async def test_cloud_link_off_is_one_row_and_its_devices_wait(hass: HomeAssistant, freezer):
    """Cloud Link off on two minute checks: the hub is down, dated from the
    first; nothing behind it is listed, however long it lasts."""
    coord, dev, ids, records = await _ready(hass, freezer)
    faults = record_events(hass, EVENT_FAULT)
    recoveries = record_events(hass, EVENT_RECOVERED)
    lost_at = dt_util.utcnow().timestamp()
    hass.states.async_set(ids["cloud"], "off")
    for key in ("link",):
        hass.states.async_set(ids[key], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 61)
    assert _item(coord, dev["hub"].id) is None, "one reading is not an outage"
    await walk(hass, freezer, 4 * HOUR, step=600)
    item = _item(coord, dev["hub"].id)
    assert item is not None and "Hub down, 2 devices that it controls" in item["summary"]
    since = coord.data[DATA_DEVICES][dev["hub"].id][DEV_FROZEN_SINCE]
    assert lost_at <= since <= lost_at + 62
    for name in ("radio", "socket"):
        assert _item(coord, dev[name].id) is None, name
        assert records[name][DEV_FROZEN_CATEGORY] is None, f"{name} waited for its hub"
    assert [f["device_id"] for f in faults] == [dev["hub"].id]

    hass.states.async_set(ids["cloud"], "on")
    hass.states.async_set(ids["link"], "on")
    hass.states.async_set(ids["power"], "14.0")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    assert _item(coord, dev["hub"].id) is None
    assert [r["device_id"] for r in recoveries] == [dev["hub"].id]


async def test_cloud_link_unavailable_says_nothing(hass: HomeAssistant, freezer):
    """Unreadable is no opinion: the hub is not down, and a socket silent
    past its rhythm, its own sensor unreadable too, is frozen as ever."""
    coord, dev, ids, records = await _ready(hass, freezer)
    hass.states.async_set(ids["cloud"], "unavailable")
    hass.states.async_set(ids["link"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert _item(coord, dev["hub"].id) is None
    assert records["socket"][DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN


async def test_a_connected_sensor_off_is_listed_at_once(hass: HomeAssistant, freezer):
    """Lightwave waits about 30 minutes before Connected reads off, so no
    three-minute wait follows: listed at the next minute check, dated
    from the change, as a Lutron hub's lost connection is."""
    coord, dev, ids, records = await _ready(hass, freezer)
    went = dt_util.utcnow().timestamp()
    hass.states.async_set(ids["link"], "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 61)
    for name in ("radio", "socket"):
        assert records[name][DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, name
        assert went - 1 <= records[name][DEV_FROZEN_SINCE] <= went + 1, name


async def test_a_house_without_cloud_link_keeps_the_hub_set_aside(hass: HomeAssistant, freezer):
    """A Lightwave hub with no Cloud Link, so the service hub is set aside
    as any service, and its devices are judged as before."""
    coord, dev, _ids, _records = await _ready(hass, freezer, cloud=False)
    assert dev["hub"].id not in coord._watched
    assert not coord.is_hub(dev["hub"].id) and coord.hub_of(dev["socket"].id) is None


async def test_the_hub_is_a_network(hass: HomeAssistant, freezer):
    coord, dev, _ids, _records = await _ready(hass, freezer)
    assert any(key.endswith(dev["hub"].id) for key in coord.network_keys())


async def test_the_download_names_each_device_set_aside_and_why(hass: HomeAssistant, freezer):
    """The question this hub raised, answered from the file alone."""
    from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics

    coord, dev, _ids, _records = await _ready(hass, freezer, cloud=False)
    data = await async_get_config_entry_diagnostics(hass, coord.entry)
    rows = data["set_aside_devices"]
    hub = next(row for row in rows if row["device_id"] == dev["hub"].id)
    assert hub["reason"] == "service" and hub["integration"] == DOMAIN and hub["model"] == "L2"
    assert data["classification"]["set_aside"] == len(rows)


async def test_a_set_aside_name_is_hidden_when_names_are_not_shared(hass: HomeAssistant, freezer):
    import json

    from custom_components.device_sentinel.const import CONF_SHARE_NAMES
    from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics

    coord, dev, _ids, _records = await _ready(hass, freezer, cloud=False)
    hass.config_entries.async_update_entry(coord.entry, options={**coord.entry.options, CONF_SHARE_NAMES: False})
    await hass.async_block_till_done()
    data = await async_get_config_entry_diagnostics(hass, coord.entry)
    hub = next(row for row in data["set_aside_devices"] if row["device_id"] == dev["hub"].id)
    assert hub["name"].startswith("Device ") and "LinkPlus" not in json.dumps(data)


async def test_cloud_link_switched_off_is_a_card_to_turn_it_on(hass: HomeAssistant, freezer):
    """A hub whose Cloud Link a person switched off has no word to give:
    it is listed on the Cloud Link Switched Off card, in Simple too, and
    Turn On switches it back on (rules STACK-17, REC-05)."""
    coord, dev, ids, _records = await _ready(hass, freezer)
    hub = dev["hub"].id
    assert coord.device_recommendations() == [] or all(
        card["kind"] != "hub_link_off" for card in coord.device_recommendations())
    er.async_get(hass).async_update_entity(ids["cloud"], disabled_by=er.RegistryEntryDisabler.USER)
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    assert hub in coord._watched and coord.is_hub(hub)
    assert coord._hub_connected(hub) is None, "a switched-off Cloud Link says nothing"
    card = next(card for card in coord.device_recommendations() if card["kind"] == "hub_link_off")
    assert card["title"] == "Cloud Link Switched Off" and card["simple"] is True
    assert [row["device_id"] for row in card["devices"]] == [hub] and card["devices"][0]["by_user"]
    assert coord.page_turn_on(hub, "hub_link") == 1
    assert er.async_get(hass).async_get(ids["cloud"]).disabled_by is None


async def test_a_muted_hub_mutes_its_outage_and_not_its_devices(hass: HomeAssistant, freezer):
    """Muting a Lightwave hub silences the hub going down, with its
    devices waiting behind it, and nothing of their own: a socket the hub
    cannot reach is still listed (rule STACK-17)."""
    from custom_components.device_sentinel.const import CONF_UNAVAILABLE_MUTED_DEVICES

    coord, dev, ids, records = await _ready(
        hass, freezer, options=lambda hub: {CONF_UNAVAILABLE_MUTED_DEVICES: [hub.id]})
    faults = record_events(hass, EVENT_FAULT)
    assert not coord._unavailable_muted(dev["socket"].id), "the hub's mute is not its devices'"
    hass.states.async_set(ids["link"], "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 61)
    assert _item(coord, dev["socket"].id) is not None, "a socket the hub cannot reach is listed"
    hass.states.async_set(ids["link"], "on")
    hass.states.async_set(ids["power"], "14.0")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    hass.states.async_set(ids["cloud"], "off")
    hass.states.async_set(ids["link"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 4 * HOUR, step=600)
    assert _item(coord, dev["hub"].id) is None, "the muted hub going down is silent"
    assert _item(coord, dev["socket"].id) is None and _item(coord, dev["radio"].id) is None
    assert dev["hub"].id not in [f["device_id"] for f in faults]


async def test_its_devices_pages_keep_their_own_words(hass: HomeAssistant, freezer):
    """A Lightwave device is judged on its own while its hub is up, so its
    page and its Devices row do not say "Judged by its hub". While the
    hub is down, the page says so."""
    coord, dev, ids, _records = await _ready(hass, freezer)
    for name in ("radio", "socket"):
        page = coord.dashboard_device(dev[name].id)
        assert page is not None and "judged_by" in page["status"], name
        assert (page["status"]["judged_by"] or {}).get("how") != "hub", name
        assert page["hub"] is None, f"{name}: no hub line while the hub is up"
    rows = {row["device_id"]: row for row in coord.dashboard_devices()}
    assert "judged_by" in rows[dev["socket"].id]
    assert (rows[dev["socket"].id]["judged_by"] or {}).get("how") != "hub"
    hass.states.async_set(ids["cloud"], "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 4 * HOUR, step=600)
    hub = coord.dashboard_device(dev["socket"].id)["hub"]
    assert hub is not None and hub["up"] is False
