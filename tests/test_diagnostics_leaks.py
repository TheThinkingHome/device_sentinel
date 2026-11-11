# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_diagnostics_leaks.py, Version: 0.28.11 (2026-11-10)

"""Attacks that must fail: personal data and secrets reaching the diagnostics
download, which is often attached to a public GitHub issue.

Every test asserts the SAFE behaviour: a passing test means nothing
leaked.
"""

from __future__ import annotations

import json
import time

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    CONF_BRIEF_TARGETS,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    CONF_WIFI_NETWORKS,
)
from custom_components.device_sentinel.diagnostics import (
    _redact_addresses,
    async_get_config_entry_diagnostics,
)

from tests.helpers import register_device, setup_entry

OWN_SSID = "Lander Family 5G"
NEIGHBOUR_SSIDS = {"Smith Household", "Calle Bolivar 14-22", "NETGEAR-Neighbour"}


async def _download(hass: HomeAssistant, entry) -> str:
    return json.dumps(await async_get_config_entry_diagnostics(hass, entry), default=str)


async def test_the_wifi_names_the_house_watches_are_not_in_the_download(
    hass: HomeAssistant,
):
    """The Wi-Fi networks a person chose are stored in the options and
    shown by the Wi-Fi scan section. A network name often carries a
    family name or a street address. Safe: not in the download."""
    entry = await setup_entry(hass, {CONF_WIFI_NETWORKS: [OWN_SSID]})
    text = await _download(hass, entry)
    assert OWN_SSID not in text


async def test_the_neighbours_wifi_names_are_not_in_the_download(
    hass: HomeAssistant,
):
    """The Wi-Fi scan keeps every network name the host's radio hears,
    the neighbours' included, and the download lists them under
    wifi_scan.heard. A list of the names heard from one spot locates the
    house on public Wi-Fi maps. Safe: not in the download."""
    entry = await setup_entry(hass, {CONF_WIFI_NETWORKS: [OWN_SSID]})
    coord = entry.runtime_data
    coord._wifi_scan_interface = "wlan0"
    coord._wifi_heard = {OWN_SSID, *NEIGHBOUR_SSIDS}
    text = await _download(hass, entry)
    for ssid in NEIGHBOUR_SSIDS:
        assert ssid not in text, ssid


async def test_notify_targets_are_redacted(hass: HomeAssistant):
    """Targets named after an email address (expected to hold)."""
    entry = await setup_entry(
        hass,
        {
            CONF_HIGH_PRIORITY_TARGETS: ["notify.mobile_app_james_iphone"],
            CONF_NORMAL_PRIORITY_TARGETS: ["notify.james_lander_gmail_com"],
            CONF_BRIEF_TARGETS: ["notify.randy_example_org"],
        },
    )
    text = await _download(hass, entry)
    for leak in ("james_iphone", "james_lander_gmail_com", "randy_example_org"):
        assert leak not in text, leak


def test_credentials_in_a_web_address_are_redacted():
    """A device's own text or an attribute carrying a camera or router
    address with its user and password. Only the host's IPv4 is
    replaced today. Safe: the password never survives."""
    for raw in (
        "http://admin:hunter2@192.168.1.5:8123/",
        "rtsp://cam:hunter2@cam.lan/stream",
        "https://user:hunter2@myhouse.duckdns.org/",
    ):
        out = json.dumps(_redact_addresses({"x": raw}))
        assert "hunter2" not in out, out


def test_an_email_address_is_redacted():
    """An email address in any text the download carries (a device
    named for its owner's account, a cloud entry's title). Safe: gone."""
    out = json.dumps(_redact_addresses({"name": "Tado of james.lander@example.com"}))
    assert "james.lander@example.com" not in out, out


def test_every_private_and_link_local_address_is_redacted():
    """IPv4 and IPv6 home addresses in their usual spellings (expected
    to hold)."""
    for raw in (
        "192.168.1.5", "10.0.0.1/24", "172.20.1.5:8123", "169.254.3.4",
        "100.101.102.103", "fe80::1%eth0", "fd12:3456:789a::1",
        "::ffff:192.168.1.5", "http://[2001:db8::1]:8123/",
        "2001:0db8:0000:0000:0000:ff00:0042:8329",
    ):
        out = _redact_addresses({"x": raw})["x"]
        assert "IP-" in out, (raw, out)


def test_every_mac_spelling_is_redacted():
    """MACs with colons, dashes, dots and none (expected to hold)."""
    for raw in ("AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "aabb.ccdd.eeff", "aabbccddeeff"):
        out = _redact_addresses({"x": raw})["x"]
        assert "MAC-" in out and "DD:EE:FF" not in out.upper(), (raw, out)


def test_the_ipv6_redaction_is_not_quadratic():
    """The IPv6 candidate pattern's lookahead scans to the end of a run
    of hex digits and colons from every starting point, so the time
    grows with the square of a string's length: 100 kB takes seconds.
    Safe: 100 kB of hostile text is redacted in well under a second."""
    hostile = "a:" * 50_000 + "!"
    started = time.perf_counter()
    _redact_addresses({"name": hostile})
    assert time.perf_counter() - started < 1.0


async def test_a_long_device_name_does_not_stall_the_download(hass: HomeAssistant):
    """The redaction runs inside the async diagnostics handler, on Home
    Assistant's event loop. A device whose own name is a long run of
    hex digits and colons stalls the whole of Home Assistant while an
    administrator downloads diagnostics. Safe: the download of a house
    with one such device takes under two seconds."""
    register_device(hass, "hostile", name="1:" * 50_000)
    entry = await setup_entry(hass)
    started = time.perf_counter()
    await async_get_config_entry_diagnostics(hass, entry)
    assert time.perf_counter() - started < 2.0
