# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_recommendations.py, Version: 0.22.0 (2026-09-18)

"""The brief's Recommendations section (ruling #458).

What a person could change about their own setup, worst first: a
message that goes nowhere, a family switched off in effect, what is
disabled, a router integration watched again, and noise. Each line
stands until its condition is gone, and the section is absent when
there is nothing to say.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    CONF_BATTERY_MUTED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_HIGH_PRIORITY_TARGETS,
    DATA_DEVICES,
    DATA_STORM_DAYS,
    DEV_BATTERY_VALUE,
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
    # Sighted and excluded at setup (ruling #420), then taken off the
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
    """No cap (ruling #461, amending #458). Nothing is dismissed, so a
    cap would hide every line below it for as long as those above it
    stood."""
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
    path = hass.config.path("www", "device_sentinel", "daily_brief.html")
    page = await hass.async_add_executor_job(
        lambda: open(path, encoding="utf-8").read()
    )
    assert "<h2>Recommendations</h2>" in page
    assert page.index("<h2>Recommendations</h2>") < page.index(
        "<h2>Last 24 Hours</h2>"
    )
    assert "notify.old_phone" in page


# ------------------------------------------------ the library (#459)
# The fourth fleet set its own exclusions to none and watches ping,
# spook and mobile_app, the first house that did not take its list
# from the reference system's.


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
