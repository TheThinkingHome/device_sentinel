# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_addresses.py, Version: 0.28.11 (2026-11-10)

"""Each Wi-Fi device's address and access point, and an address two
devices hold at once (rule UP-19).

A router tracker carries the address it gave the device as `ip`, and
UniFi carries the access point as `ap_mac`. Each change is kept with
when it happened. Two devices that hold one address at once for 10
minutes are a network fault: either can look like it has stopped
working. They are flagged on the Recommendations tab and by a Repair
card that can only be acknowledged, and the card goes away by itself
once each device has its own address.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_ADDRESS_CHANGES,
    DOMAIN,
    REPAIR_SHARED_ADDRESS,
    SHARED_ADDRESS_SECONDS,
)
from custom_components.device_sentinel.diagnostics import _redact_addresses
from custom_components.device_sentinel.normalise import check_storage

from tests.test_wifi_outage import _house


def _give(hass, tracker: str, ip: str | None, ap: str | None = None, state: str = "home"):
    attributes = dict(hass.states.get(tracker).attributes)
    attributes.pop("ip", None)
    attributes.pop("ap_mac", None)
    if ip is not None:
        attributes["ip"] = ip
    if ap is not None:
        attributes["ap_mac"] = ap
    hass.states.async_set(tracker, state, attributes)


def _rows(coord, device_id):
    return [r for r in coord.data.get(DATA_ADDRESS_CHANGES) or [] if r["device_id"] == device_id]


def _card(coord):
    return next((c for c in coord.device_recommendations() if c["kind"] == "shared_address"), None)


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, REPAIR_SHARED_ADDRESS)


async def test_an_address_and_access_point_are_kept_with_each_change(hass: HomeAssistant):
    coord, trackers, devices, _untied = await _house(hass, 2)
    now = dt_util.utcnow().timestamp()
    _give(hass, trackers[0], "192.168.1.40", "aa:bb:cc:11:22:33")
    coord._sample_addresses(now)
    coord._sample_addresses(now + 60)  # nothing changed, nothing kept
    assert len(_rows(coord, devices[0].id)) == 1
    _give(hass, trackers[0], "192.168.1.40", "aa:bb:cc:44:55:66")
    coord._sample_addresses(now + 120)
    rows = _rows(coord, devices[0].id)
    assert [r["ap"] for r in rows] == ["aa:bb:cc:11:22:33", "aa:bb:cc:44:55:66"]
    found = coord.address_of(devices[0].id)
    assert found["ip"] == "192.168.1.40" and found["ap"] == "aa:bb:cc:44:55:66"
    # The address has not changed since the first reading; the access point has.
    assert abs(dt_util.parse_datetime(found["ip_since"]).timestamp() - now) < 1
    assert abs(dt_util.parse_datetime(found["ap_since"]).timestamp() - (now + 120)) < 1
    assert found["shared"] is False
    # A tracker that says nothing gives no row and no page rows.
    assert coord.address_of(devices[1].id) is None


async def test_the_device_page_carries_the_address(hass: HomeAssistant):
    coord, trackers, devices, _untied = await _house(hass, 1)
    _give(hass, trackers[0], "192.168.1.41")
    coord._sample_addresses(dt_util.utcnow().timestamp())
    page = coord.dashboard_device(devices[0].id)
    assert page["identity"]["address"]["ip"] == "192.168.1.41"
    assert page["identity"]["address"]["ap"] is None


async def test_two_devices_on_one_address_are_flagged_after_ten_minutes(hass: HomeAssistant):
    coord, trackers, devices, _untied = await _house(hass, 3)
    now = dt_util.utcnow().timestamp()
    _give(hass, trackers[0], "192.168.1.50")
    _give(hass, trackers[1], "192.168.1.50")
    _give(hass, trackers[2], "192.168.1.51")
    coord._sample_addresses(now)
    coord._sample_addresses(now + SHARED_ADDRESS_SECONDS - 60)
    assert coord.shared_addresses() == {} and _issue(hass) is None and _card(coord) is None
    coord._sample_addresses(now + SHARED_ADDRESS_SECONDS + 1)
    assert coord.shared_addresses() == {"192.168.1.50": sorted([devices[0].id, devices[1].id])}
    issue = _issue(hass)
    assert issue is not None and not issue.is_fixable
    assert issue.severity == ir.IssueSeverity.WARNING
    assert "WiFi Device 0" in issue.translation_placeholders["detail"]
    card = _card(coord)
    assert {row["device_id"] for row in card["devices"]} == {devices[0].id, devices[1].id}
    assert all(row["detail"] == "192.168.1.50" for row in card["devices"])
    assert coord.address_of(devices[0].id)["shared"] is True
    assert coord.address_of(devices[2].id)["shared"] is False


async def test_the_flag_goes_away_by_itself_once_each_has_its_own(hass: HomeAssistant):
    coord, trackers, _devices, _untied = await _house(hass, 2)
    now = dt_util.utcnow().timestamp()
    _give(hass, trackers[0], "192.168.1.60")
    _give(hass, trackers[1], "192.168.1.60")
    coord._sample_addresses(now)
    coord._sample_addresses(now + SHARED_ADDRESS_SECONDS + 1)
    assert _issue(hass) is not None
    _give(hass, trackers[1], "192.168.1.61")
    coord._sample_addresses(now + SHARED_ADDRESS_SECONDS + 61)
    assert coord.shared_addresses() == {} and _issue(hass) is None and _card(coord) is None


async def test_a_tracker_away_keeps_a_stale_address_and_is_not_flagged(hass: HomeAssistant):
    """A device that left keeps its last address as an attribute; the
    router has already given it to someone else."""
    coord, trackers, _devices, _untied = await _house(hass, 2)
    now = dt_util.utcnow().timestamp()
    _give(hass, trackers[0], "192.168.1.70")
    _give(hass, trackers[1], "192.168.1.70", state="not_home")
    coord._sample_addresses(now)
    coord._sample_addresses(now + SHARED_ADDRESS_SECONDS + 1)
    assert coord.shared_addresses() == {} and _issue(hass) is None


async def test_a_break_in_the_share_starts_the_ten_minutes_again(hass: HomeAssistant):
    coord, trackers, _devices, _untied = await _house(hass, 2)
    now = dt_util.utcnow().timestamp()
    _give(hass, trackers[0], "192.168.1.80")
    _give(hass, trackers[1], "192.168.1.80")
    coord._sample_addresses(now)
    _give(hass, trackers[1], "192.168.1.81")
    coord._sample_addresses(now + 300)
    _give(hass, trackers[1], "192.168.1.80")
    coord._sample_addresses(now + 360)
    coord._sample_addresses(now + SHARED_ADDRESS_SECONDS + 1)
    assert coord.shared_addresses() == {}
    coord._sample_addresses(now + 360 + SHARED_ADDRESS_SECONDS)
    assert "192.168.1.80" in coord.shared_addresses()


async def test_one_tracker_tied_to_two_devices_is_not_a_share(hass: HomeAssistant):
    """One piece of hardware shown as two devices holds one address
    through one tracker: nothing is wrong."""
    coord, trackers, devices, _untied = await _house(hass, 2)
    coord._wifi_ties[devices[1].id] = trackers[0]
    now = dt_util.utcnow().timestamp()
    _give(hass, trackers[0], "192.168.1.90")
    coord._sample_addresses(now)
    coord._sample_addresses(now + SHARED_ADDRESS_SECONDS + 1)
    assert coord.shared_addresses() == {}


async def test_one_device_seen_by_two_routers_is_not_a_share(hass: HomeAssistant):
    """Two trackers, from two router integrations, carrying one MAC are
    one piece of hardware."""
    coord, trackers, devices, _untied = await _house(hass, 2)
    attributes = dict(hass.states.get(trackers[0]).attributes)
    hass.states.async_set(trackers[1], "home", {**attributes, "ip": "192.168.1.95"})
    _give(hass, trackers[0], "192.168.1.95")
    now = dt_util.utcnow().timestamp()
    coord._sample_addresses(now)
    coord._sample_addresses(now + SHARED_ADDRESS_SECONDS + 1)
    assert coord.shared_addresses() == {}


async def test_address_rows_are_held_to_the_history_length(hass: HomeAssistant):
    coord, _trackers, devices, _untied = await _house(hass, 1)
    now = dt_util.utcnow().timestamp()
    rows = coord.data.setdefault(DATA_ADDRESS_CHANGES, [])
    old = now - (coord.retention_days + 2) * 86400
    rows.append({"device_id": devices[0].id, "when": old - 10, "ip": "10.0.0.1", "ap": None})
    rows.append({"device_id": devices[0].id, "when": old, "ip": "10.0.0.2", "ap": None})
    rows.append({"device_id": "gone", "when": old, "ip": "10.0.0.3", "ap": None})
    coord._address_now = None
    coord._trim_house_tables(now)
    # Each device keeps its latest row, however old, so its page still
    # shows the address it has now.
    kept = coord.data[DATA_ADDRESS_CHANGES]
    assert {(r["device_id"], r["ip"]) for r in kept} == {(devices[0].id, "10.0.0.2"), ("gone", "10.0.0.3")}
    assert coord.address_of(devices[0].id)["ip"] == "10.0.0.2"


async def test_a_device_moving_between_access_points_keeps_its_newest_rows(hass: HomeAssistant):
    """A mesh device that moves every minute all day (rule UP-19)."""
    from custom_components.device_sentinel.const import ADDRESS_ROWS_PER_DEVICE

    coord, trackers, devices, _untied = await _house(hass, 1)
    now = dt_util.utcnow().timestamp()
    for minute in range(24 * 60):
        _give(hass, trackers[0], "192.168.1.40", "aa:bb:cc:00:00:0%d" % (minute % 2))
        coord._sample_addresses(now + 60 * minute)
    rows = _rows(coord, devices[0].id)
    assert len(rows) == ADDRESS_ROWS_PER_DEVICE
    assert rows[-1]["when"] == now + 60 * (24 * 60 - 1)
    assert coord.address_of(devices[0].id)["ap"] == "aa:bb:cc:00:00:01"


async def test_an_attribute_too_long_to_be_an_address_is_not_kept(hass: HomeAssistant):
    coord, trackers, devices, _untied = await _house(hass, 1)
    _give(hass, trackers[0], "x" * 5000, "y" * 5000)
    coord._sample_addresses(dt_util.utcnow().timestamp())
    assert _rows(coord, devices[0].id) == []


def test_a_damaged_address_row_is_found_by_the_shape_check():
    good = {"device_id": "a", "when": 1_790_000_000.0, "ip": "192.168.1.2", "ap": None}
    assert check_storage({"address_changes": [good]}) == []
    assert check_storage({"address_changes": [dict(good, when="noon")]})


def test_the_diagnostics_download_replaces_the_addresses():
    payload = {"address_changes": [{"device_id": "a", "when": 1.0, "ip": "192.168.1.2",
                                    "ap": "aa:bb:cc:11:22:33"}],
               "shared_addresses": {"192.168.1.2": ["a", "b"]}}
    text = repr(_redact_addresses(payload))
    assert "192.168.1.2" not in text
    assert "11:22:33" not in text


async def test_the_card_shows_names_as_text_never_as_markdown(hass: HomeAssistant):
    """A repair card is shown as Markdown: a name like a picture would
    load it from elsewhere (rule CODE-10)."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.device_sentinel.repairs import async_evaluate_shared_addresses

    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    async_evaluate_shared_addresses(
        hass, entry, {"IP-01": ["![x](https://evil.example/p.png)", "Lamp"]}
    )
    detail = _issue(hass).translation_placeholders["detail"]
    assert "![x](" not in detail and "\\!\\[x\\]" in detail, detail
