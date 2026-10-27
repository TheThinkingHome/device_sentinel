# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_recommendations.py, Version: 0.27.10 (2026-10-27)

"""The brief's Recommendations section and the device cards (rules
REC-02, REC-04, REC-10).

What a person could change about their own setup, worst first: a
message that goes nowhere, a family switched off in effect, what is
disabled, a router integration watched again, and noise. Each line
stands until its condition is gone, and the section is absent when
there is nothing to say.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    CONF_BATTERY_MUTED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_FREEZE_MUTED_DEVICES,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_MUTED_DEVICES,
    CONF_MUTED_INTEGRATIONS,
    CONF_MUTED_LABELS,
    DATA_DEVICES,
    DATA_STORM_DAYS,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    SLOW_REPORTER_SECONDS,
    STORM_DAY_COUNT,
    STORM_DAY_DATE,
    STORM_DAY_DOMAIN,
    STORM_DAY_INTERVAL,
)

from tests.helpers import register_device, setup_coordinator, setup_entry


def _noisy(domains: list[str]) -> list[dict]:
    rows = []
    for domain in domains:
        for days_ago in (1, 2):
            rows.append({
                STORM_DAY_DATE: (
                    dt_util.now().date() - timedelta(days=days_ago)
                ).isoformat(),
                STORM_DAY_DOMAIN: domain,
                STORM_DAY_COUNT: 500,
                STORM_DAY_INTERVAL: 20.0,
            })
    return rows


def _text(lines: list[str]) -> str:
    return "\n".join(lines)


async def test_nothing_to_say_is_no_section(hass: HomeAssistant):
    """A house with a working target and nothing else amiss."""
    async def _phone(call):
        return None

    hass.services.async_register("notify", "phone", _phone)
    coord = await setup_coordinator(
        hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]}
    )
    assert coord._recommendations_section() == []


async def test_a_target_that_no_longer_exists_is_named(hass: HomeAssistant):
    coord = await setup_coordinator(
        hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.old_phone"]}
    )
    text = _text(coord._recommendations_section())
    assert "notify.old_phone" in text
    assert "Notifications Recipient Not Valid: notify.old_phone no longer exists." in text


async def test_no_target_at_all_is_said(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    lines = coord._recommendation_items()
    assert any(line.startswith("Notifications Recipient Not Set:") for line in lines)


async def test_a_family_muted_for_every_device_is_said(hass: HomeAssistant):
    first, _ = register_device(hass, "b1", name="Door One")
    second, _ = register_device(hass, "b2", name="Door Two")
    coord = await setup_coordinator(
        hass, {CONF_BATTERY_MUTED_DEVICES: [first.id, second.id]}
    )
    for device in (first, second):
        coord.data[DATA_DEVICES][device.id][DEV_BATTERY_VALUE] = 80.0
    lines = coord._recommendation_items()
    assert any(
        line.startswith("All battery devices are muted or excluded for battery reporting:") and "all 2 of your battery devices are muted" in line
        for line in lines
    )


async def test_a_family_with_one_device_unmuted_is_not_said(hass: HomeAssistant):
    first, _ = register_device(hass, "b1", name="Door One")
    second, _ = register_device(hass, "b2", name="Door Two")
    coord = await setup_coordinator(
        hass, {CONF_BATTERY_MUTED_DEVICES: [first.id]}
    )
    for device in (first, second):
        coord.data[DATA_DEVICES][device.id][DEV_BATTERY_VALUE] = 80.0
    lines = coord._recommendation_items()
    assert not any(line.startswith("All battery devices") for line in lines)


async def test_a_router_integration_watched_again_is_measured(hass: HomeAssistant):
    registry = er.async_get(hass)
    for n in range(3):
        device, _ = register_device(hass, f"client{n}", name=f"Client {n}")
        registry.async_get_or_create(
            "device_tracker", "tplink_router", f"mac{n}", device_id=device.id
        )
    # Sighted and excluded at setup (rule MUTE-02), then taken off the
    # list by the person, which is the only way it is watched again.
    entry = await setup_entry(hass, {CONF_EXCLUDED_INTEGRATIONS: []})
    assert "tplink_router" in entry.runtime_data.excluded_integrations
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_EXCLUDED_INTEGRATIONS: []}
    )
    await hass.async_block_till_done()
    coord = entry.runtime_data
    assert "tplink_router" not in coord.excluded_integrations
    lines = coord._recommendation_items()
    router = [line for line in lines if "the tplink_router integration" in line]
    assert len(router) == 1
    assert "registered 3 virtual devices" in router[0]


async def test_a_router_integration_still_excluded_is_not_said(hass: HomeAssistant):
    registry = er.async_get(hass)
    device, _ = register_device(hass, "client", name="Client")
    registry.async_get_or_create(
        "device_tracker", "tplink_router", "mac", device_id=device.id
    )
    coord = await setup_coordinator(
        hass, {CONF_EXCLUDED_INTEGRATIONS: ["tplink_router"]}
    )
    lines = coord._recommendation_items()
    assert not any("the tplink_router integration" in line for line in lines)


async def test_the_worst_comes_first(hass: HomeAssistant):
    coord = await setup_coordinator(
        hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.old_phone"]}
    )
    coord.data[DATA_STORM_DAYS] = _noisy(["poller"])
    lines = coord._recommendation_items()
    missing = next(i for i, line in enumerate(lines) if "notify.old_phone" in line)
    noisy = next(i for i, line in enumerate(lines) if "the poller integration" in line)
    assert missing < noisy


async def test_every_line_shows(hass: HomeAssistant):
    """No cap. Nothing is dismissed, so a cap would hide every line below
    it for as long as those above it stood (rule REC-02)."""
    coord = await setup_coordinator(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.gone"]})
    coord.data[DATA_STORM_DAYS] = _noisy([f"poller{n}" for n in range(6)])
    lines = coord._recommendations_section()
    body = [
        line for line in lines
        if line and not line.startswith("## ") and not line.startswith("These are suggestions")
    ]
    assert len(body) == 7
    assert not any(line.startswith("And ") for line in body)
    assert "the poller5 integration" in body[-1]


async def test_the_written_brief_carries_the_section(hass: HomeAssistant):
    coord = await setup_coordinator(
        hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.old_phone"]}
    )
    await hass.async_add_executor_job(coord._write_reports, "manual")
    path = hass.config.path("device_sentinel", "daily_brief.html")
    page = await hass.async_add_executor_job(
        lambda: open(path, encoding="utf-8").read()
    )
    assert "<h2>Recommendations</h2>" in page
    assert page.index("<h2>Recommendations</h2>") < page.index(
        "<h2>Last 24 Hours</h2>"
    )
    assert "notify.old_phone" in page


# ------------------------------------------------ the library (rule REC-03)
# A house can set its own exclusions to none and watch ping, spook and
# mobile_app, so its list is not taken from the defaults.


def _watched_integration(hass, domain: str, uid: str):
    """A device owned by `domain`, watched like any other."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import device_registry as dr

    entry = MockConfigEntry(domain=domain, title=domain)
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(domain, uid)},
        name=f"{domain} {uid}",
    )
    er.async_get(hass).async_get_or_create(
        "binary_sensor", domain, uid, device_id=device.id,
        config_entry=entry,
    )
    return device


async def test_a_watched_library_integration_is_advised(hass: HomeAssistant):
    for n in range(5):
        _watched_integration(hass, "ping", f"host{n}")
    _watched_integration(hass, "mobile_app", "phone")
    _watched_integration(hass, "spook", "tools")
    coord = await setup_coordinator(hass, {CONF_EXCLUDED_INTEGRATIONS: []})
    items = coord._recommendation_items()
    alerts = [line for line in items if line.startswith("Some integrations create false alerts:")]
    assert len(alerts) == 1
    assert "integrations to stop false alarms" in alerts[0]
    tools = [line for line in items if line.startswith("Some integrations own no devices")]
    assert len(tools) == 1
    assert "spook (1 device) is watched" in tools[0]
    assert tools[0].endswith("Exclude it in the Exclusions and Muting settings screen.")


async def test_an_excluded_library_integration_is_not_advised(hass: HomeAssistant):
    _watched_integration(hass, "ping", "host")
    coord = await setup_coordinator(hass, {CONF_EXCLUDED_INTEGRATIONS: ["ping"]})
    assert not any(
        line.startswith("Some integrations")
        for line in coord._recommendation_items()
    )


async def test_the_library_is_data(hass: HomeAssistant):
    """Categories live in one table, not in prose."""
    from custom_components.device_sentinel.const import (
        LIBRARY_FALSE_ALERTS,
        LIBRARY_NO_DEVICES,
        RECOMMENDATION_LIBRARY,
    )

    domains = [d for group in RECOMMENDATION_LIBRARY.values() for d in group]
    assert "ping" in RECOMMENDATION_LIBRARY[LIBRARY_FALSE_ALERTS]
    assert "webostv" in RECOMMENDATION_LIBRARY[LIBRARY_FALSE_ALERTS]
    assert RECOMMENDATION_LIBRARY[LIBRARY_NO_DEVICES] == ("spook",)
    assert len(domains) == len(set(domains))


# ------------------------------------------- Wi-Fi coverage absent
# A machine with a wireless adapter and no network named for it, and
# no router ties to see an outage another way, detects no Wi-Fi outage
# at all, and nothing says so.


async def _with_adapter(hass, monkeypatch, interfaces, options=None):
    from custom_components.device_sentinel import wifi as wifi_module

    async def _found(_hass):
        return interfaces

    monkeypatch.setattr(wifi_module, "wireless_interfaces", _found)
    coord = await setup_coordinator(hass, options)
    await coord.async_check_unused_adapter()
    return coord


def _wifi_lines(coord):
    return [
        line for line in coord._recommendation_items()
        if line.startswith("Wi-Fi network not set")
    ]


async def test_an_unused_adapter_is_named(hass: HomeAssistant, monkeypatch):
    coord = await _with_adapter(hass, monkeypatch, [{"interface": "wlan0"}])
    lines = _wifi_lines(coord)
    assert len(lines) == 1
    assert "wlan0" in lines[0]


async def test_a_chosen_network_is_coverage(hass: HomeAssistant, monkeypatch):
    from custom_components.device_sentinel.const import CONF_WIFI_NETWORKS

    coord = await _with_adapter(
        hass, monkeypatch, [{"interface": "wlan0"}],
        {CONF_WIFI_NETWORKS: ["Home"]},
    )
    assert _wifi_lines(coord) == []


async def test_router_ties_are_coverage(hass: HomeAssistant, monkeypatch):
    coord = await _with_adapter(hass, monkeypatch, [{"interface": "wlan0"}])
    coord._wifi_ties = {"device_tracker.phone": "device"}
    assert _wifi_lines(coord) == []


async def test_no_adapter_says_nothing(hass: HomeAssistant, monkeypatch):
    coord = await _with_adapter(hass, monkeypatch, [])
    assert _wifi_lines(coord) == []


# ---------------------------------------- Zigbee2MQTT availability


class _Reader:
    def __init__(self, enabled):
        self.availability_enabled = enabled

    def async_stop(self):
        return None


async def test_z2m_availability_off_is_said(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord._bridge_readers = {"z2m": _Reader(False)}
    assert any(
        line.startswith("Zigbee2MQTT availability is disabled:")
        for line in coord._recommendation_items()
    )


async def test_z2m_availability_on_or_unknown_says_nothing(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    for state in (True, None):
        coord._bridge_readers = {"z2m": _Reader(state)}
        assert not any(
            "Zigbee2MQTT availability" in line
            for line in coord._recommendation_items()
        )


# ------------------------------------- a links address no longer held


async def test_a_links_address_that_is_gone_is_said(hass: HomeAssistant):
    from custom_components.device_sentinel.const import (
        CONF_REPORT_LINKS,
        REPORT_LINKS_EXTERNAL,
    )

    await hass.config.async_update(external_url=None)
    coord = await setup_coordinator(hass, {CONF_REPORT_LINKS: REPORT_LINKS_EXTERNAL})
    lines = [
        line for line in coord._recommendation_items()
        if line.startswith("Your Home Assistant External URL")
    ]
    assert len(lines) == 1
    assert "links with your external URL" in lines[0]


async def test_a_links_address_that_is_held_says_nothing(hass: HomeAssistant):
    from custom_components.device_sentinel.const import (
        CONF_REPORT_LINKS,
        REPORT_LINKS_EXTERNAL,
    )

    await hass.config.async_update(external_url="https://example.org")
    coord = await setup_coordinator(hass, {CONF_REPORT_LINKS: REPORT_LINKS_EXTERNAL})
    assert not any(
        line.startswith("Your Home Assistant")
        for line in coord._recommendation_items()
    )


async def test_a_single_muted_device_is_it_not_them(hass: HomeAssistant):
    only, _ = register_device(hass, "b1", name="Only Door")
    coord = await setup_coordinator(hass, {CONF_BATTERY_MUTED_DEVICES: [only.id]})
    coord.data[DATA_DEVICES][only.id][DEV_BATTERY_VALUE] = 80.0
    line = next(
        line for line in coord._recommendation_items()
        if line.startswith("All battery devices")
    )
    assert "your only battery device is muted" in line
    assert "unmute or unexclude it on" in line
    assert "unexclude them" not in line


# ------------------------------------------ recommendations about devices


async def _house_for_cards(hass: HomeAssistant):
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr

    kitchen = ar.async_get(hass).async_create("Kitchen")
    known, _ = register_device(hass, "rc1", "Door Kitchen")
    dr.async_get(hass).async_update_device(
        known.id, manufacturer="Aqara", model="Door and window sensor", model_id="MCCGQ11LM",
        hw_version="2", area_id=kitchen.id,
    )
    unknown, _ = register_device(hass, "rc2", "Mystery Sensor")
    twin_a, _ = register_device(hass, "rc3", "Hall Light")
    twin_b, _ = register_device(hass, "rc4", "hall light")
    for device in (twin_a, twin_b):
        dr.async_get(hass).async_update_device(device.id, area_id=kitchen.id)
    coord = await setup_coordinator(hass)
    off = er.RegistryEntryDisabler.INTEGRATION
    found = dr.async_get(hass).async_get(unknown.id)
    entry_id = getattr(found, "config_entry_id", None) or next(iter(found.config_entries))
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "rc2_ls", device_id=unknown.id,
        config_entry=hass.config_entries.async_get_entry(entry_id),
        original_name="Last seen", disabled_by=off,
    )
    coord._rebuild_registry_view()
    return coord, known, unknown, twin_a, twin_b


async def test_each_card_lists_its_devices(hass: HomeAssistant):
    coord, known, unknown, twin_a, twin_b = await _house_for_cards(hass)
    cards = {card["kind"]: card for card in coord.device_recommendations()}
    ids = {kind: [row["device_id"] for row in card["devices"]] for kind, card in cards.items()}
    assert known.id not in ids["power"], "the library knows the Aqara sensor"
    assert unknown.id in ids["power"] and twin_a.id in ids["power"]
    assert ids["last_seen"] == [unknown.id]
    assert ids["area"] == [unknown.id]
    assert set(ids["names"]) == {twin_a.id, twin_b.id}, "names compared without regard to capitals"
    # The two type cards come last; none of these devices has a type.
    assert [card["kind"] for card in coord.device_recommendations()] == ["power", "last_seen", "area", "names", "type"]
    assert cards["last_seen"]["body"].startswith("1 device has a Last Seen sensor")
    names = [row["name"] for row in cards["power"]["devices"]]
    assert names == sorted(names, key=str.casefold)


async def test_a_card_leaves_when_its_condition_does(hass: HomeAssistant, hass_ws_client):
    coord, known, unknown, twin_a, twin_b = await _house_for_cards(hass)
    client = await hass_ws_client(hass)
    for i, device in enumerate((unknown, twin_a, twin_b)):
        await client.send_json({"id": 10 + i, "type": "device_sentinel/device_power", "device_id": device.id,
                                "choice": "USB Powered"})
        assert (await client.receive_json())["success"]
    assert "power" not in {card["kind"] for card in coord.device_recommendations()}


async def test_the_tab_carries_the_cards_and_the_power_choices(hass: HomeAssistant, hass_ws_client):
    coord, *_ = await _house_for_cards(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "device_sentinel/recommendations"})
    reply = await client.receive_json()
    assert reply["success"], reply
    result = reply["result"]
    assert [card["kind"] for card in result["devices"]] == ["power", "last_seen", "area", "names", "type"]
    assert "PoE Powered" in result["power"]["choices"] and result["power"]["quantity"] == [1, 8]
    assert not any("Power Not Set" in line for line in result["lines"]), "the cards are not repeated as lines"


async def test_the_emailed_brief_carries_one_line_each_with_its_link(hass: HomeAssistant):
    from custom_components.device_sentinel.const import CONF_REPORT_LINKS, REPORT_LINKS_EXTERNAL

    coord, *_ = await _house_for_cards(hass)
    text = _text(coord._recommendations_section())
    # Each title counts the rows not ticked, as on the tab (rule REC-08).
    active = {card["title"]: card["active"] for card in coord.device_recommendations()}
    for title in ("Power Not Set", "Last Seen Sensor Switched Off", "No Area Assigned", "Devices Sharing A Name"):
        assert active[title] > 0, title
        assert f"{title} ({active[title]}): " in text, title
    assert "from the Recommendations tab" in text
    hass.config.external_url = "https://home.example.org"
    hass.config_entries.async_update_entry(coord.entry, options={**coord.entry.options,
                                                                  CONF_REPORT_LINKS: REPORT_LINKS_EXTERNAL})
    coord._recommendations_section()
    links = coord._brief_rec_links
    assert links and all(url.startswith("https://home.example.org/device-sentinel/recommendations?open=")
                         for url in links.values()), links


async def test_only_the_recommendation_lines_carry_a_link(hass: HomeAssistant):
    from custom_components.device_sentinel.const import CONF_REPORT_LINKS, REPORT_LINKS_EXTERNAL

    coord, known, unknown, *_ = await _house_for_cards(hass)
    hass.config.external_url = "https://home.example.org"
    hass.config_entries.async_update_entry(coord.entry, options={**coord.entry.options,
                                                                  CONF_REPORT_LINKS: REPORT_LINKS_EXTERNAL})
    section = coord._recommendations_section()
    # A line someone else wrote that reads like a link is only text.
    page = coord._render_brief_html("\n".join(
        ["# Device Sentinel Daily Brief", "", '<a href="https://evil.example">x</a>', ""] + section))
    assert page.count(">Open the list</a>") == 4
    assert 'href="https://evil.example"' not in page
    assert "&lt;a href=" in page


# ==================================================================
# Slow Reporting Devices (rule REC-06).
# ==================================================================

def _wait_of(coord, device_id, rhythm_seconds):
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_DAILY_MAX] = [rhythm_seconds] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()
    return coord._freeze_window(record)


def _slow_card(coord):
    return next((c for c in coord.device_recommendations() if c["kind"] == "slow"), None)


async def test_a_device_whose_wait_is_over_the_line_is_offered_a_freeze_mute(hass: HomeAssistant):
    """The card lists it in its own words, and it is not in the emailed
    brief (rule REC-06)."""
    slow, _ = register_device(hass, "slow1", "Guest Lamp")
    quick, _ = register_device(hass, "slow2", "Hall Motion")
    coord = await setup_coordinator(hass)
    assert _wait_of(coord, slow.id, 40 * 3600.0) > SLOW_REPORTER_SECONDS
    assert _wait_of(coord, quick.id, 600.0) < SLOW_REPORTER_SECONDS

    card = _slow_card(coord)
    assert card is not None and card["title"] == "Slow Reporting Devices"
    assert [row["name"] for row in card["devices"]] == ["Guest Lamp"]
    assert card["body"].startswith("These devices go quiet for long periods.")
    assert "its battery runs low." in card["body"]
    assert "brief" not in card, "a slow device is not a fault, so it stays out of the brief"
    assert not any("Slow Reporting" in line for line in coord._recommendations_section())


async def test_the_line_is_the_wait_in_use_not_the_rhythm(hass: HomeAssistant):
    """A rhythm just under the line whose grace carries the wait over it
    is listed: the card reads what the freeze judgment reads."""
    device, _ = register_device(hass, "slow3", "Porch Button")
    coord = await setup_coordinator(hass)
    rhythm = SLOW_REPORTER_SECONDS - 1800.0
    wait = _wait_of(coord, device.id, rhythm)
    assert wait > SLOW_REPORTER_SECONDS > rhythm
    assert [row["name"] for row in _slow_card(coord)["devices"]] == ["Porch Button"]


async def test_a_device_already_muted_for_freeze_leaves_the_card(hass: HomeAssistant):
    device, _ = register_device(hass, "slow4", "Muted Lamp")
    coord = await setup_coordinator(hass, {CONF_FREEZE_MUTED_DEVICES: [device.id]})
    _wait_of(coord, device.id, 40 * 3600.0)
    assert _slow_card(coord) is None


async def test_an_unarmed_device_has_no_wait_and_no_card(hass: HomeAssistant):
    device, _ = register_device(hass, "slow5", "New Device")
    coord = await setup_coordinator(hass)
    coord.data[DATA_DEVICES][device.id][DEV_DAILY_MAX] = [40 * 3600.0] * 2
    assert _slow_card(coord) is None


async def test_a_device_muted_for_everything_leaves_the_card(hass: HomeAssistant):
    """Mute everything already stops every freeze verdict, so the card has
    nothing to offer it, whether the mute names the device, a label or the
    integration (rule REC-06)."""
    label = lr.async_get(hass).async_create("Ignore")
    by_device, _ = register_device(hass, "slow6", "Muted Device")
    by_label, _ = register_device(hass, "slow7", "Labelled Device")
    dr.async_get(hass).async_update_device(by_label.id, labels={label.label_id})
    coord = await setup_coordinator(
        hass, {CONF_MUTED_DEVICES: [by_device.id], CONF_MUTED_LABELS: [label.label_id]}
    )
    for device in (by_device, by_label):
        _wait_of(coord, device.id, 40 * 3600.0)
    assert _slow_card(coord) is None


async def test_an_integration_muted_for_everything_leaves_the_card(hass: HomeAssistant):
    device, _ = register_device(hass, "slow8", "Integration Device")
    coord = await setup_coordinator(hass, {CONF_MUTED_INTEGRATIONS: ["test"]})
    _wait_of(coord, device.id, 40 * 3600.0)
    assert _slow_card(coord) is None


def _esphome_slow_device(hass, uid, deep_sleep, available=True):
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    class _Info:
        has_deep_sleep = deep_sleep

    class _Runtime:
        device_info = _Info()

    _Runtime.available = available
    source = MockConfigEntry(domain="esphome")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    source.runtime_data = _Runtime()
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("esphome", uid)}, name=f"Device {uid}"
    )
    ids = [
        er.async_get(hass).async_get_or_create(
            "sensor", "esphome", f"{uid}_{n}", device_id=device.id, config_entry=source
        ).entity_id
        for n in ("t", "fw")
    ]
    return device, ids


async def test_the_card_leaves_off_only_the_devices_judgment_leaves_off(hass: HomeAssistant):
    """An awake ESPHome device is off the card while its connection is up,
    even with one entity unavailable; with a frozen verdict standing, or
    for a deep-sleep device, the freeze rule can judge it, so the card
    offers the mute. A dropped device is judged unavailable, never
    frozen, so it stays off too (rules REC-06, STACK-07)."""
    from custom_components.device_sentinel.const import DEV_FROZEN_CATEGORY, FREEZE_CATEGORY_FROZEN

    connected, (c_t, c_fw) = _esphome_slow_device(hass, "conn", False)
    partial, (p_t, p_fw) = _esphome_slow_device(hass, "part", False)
    standing, (s_t, s_fw) = _esphome_slow_device(hass, "stand", False)
    sleeper, (z_t, z_fw) = _esphome_slow_device(hass, "sleep", True)
    dropped, _ = _esphome_slow_device(hass, "drop", False, available=False)
    coord = await setup_coordinator(hass)
    for eid in (c_t, c_fw, p_t, s_t, s_fw, z_t, z_fw):
        hass.states.async_set(eid, "21.5")
    hass.states.async_set(p_fw, "unavailable")
    for device in (connected, partial, standing, sleeper, dropped):
        _wait_of(coord, device.id, 40 * 3600.0)
    coord.data[DATA_DEVICES][standing.id][DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    assert [row["name"] for row in _slow_card(coord)["devices"]] == ["Device sleep", "Device stand"]
