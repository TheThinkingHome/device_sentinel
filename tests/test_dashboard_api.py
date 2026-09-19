# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_dashboard_api.py, Version: 0.22.1 (2026-09-19)

"""The dashboard's data layer: status, actions and the change marker.

The dashboard reads the same coordinator facts the entities read, so
the two can never disagree. Its actions call the same code the device
page's buttons call. The marker moves when something a person would
want to see arrives, and the dashboard subscribes to it rather than
asking on a timer.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEFAULT_MAINTENANCE_MINUTES,
    SYS_RESTART,
)

from tests.helpers import setup_coordinator


class _Reader:
    def __init__(self, state):
        self.state = state

    def async_stop(self):
        return None


async def _call(client, **message):
    await client.send_json_auto_id(message)
    return await client.receive_json()


async def test_status_names_only_what_the_house_has(hass: HomeAssistant, hass_ws_client):
    await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/status")
    assert reply["success"], reply
    result = reply["result"]
    assert result["parts"] == []
    assert result["maintenance"] == {
        "open": False,
        "until": None,
        "default_minutes": DEFAULT_MAINTENANCE_MINUTES,
    }
    assert isinstance(result["marker"], int)


async def test_status_reads_what_the_sensors_read(hass: HomeAssistant, hass_ws_client):
    coord = await setup_coordinator(hass)
    coord._bridge_readers = {"zha": _Reader("running"), "z2m": _Reader("down")}
    coord._broker_reader = _Reader("running")
    MockConfigEntry(domain="mqtt").add_to_hass(hass)
    client = await hass_ws_client(hass)
    parts = (await _call(client, type="device_sentinel/status"))["result"]["parts"]
    assert parts == [
        {"key": "z2m", "name": "Bridge: Zigbee2MQTT", "state": "down"},
        {"key": "zha", "name": "Bridge: ZHA", "state": "running"},
        {"key": "mqtt", "name": "Broker: MQTT", "state": "running"},
    ]


async def test_maintenance_opens_for_the_minutes_chosen(hass: HomeAssistant, hass_ws_client):
    coord = await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/action", action="maintenance", minutes=30)
    assert reply["success"], reply
    status = (await _call(client, type="device_sentinel/status"))["result"]
    assert status["maintenance"]["open"] is True
    opened = coord._maintenance_opened_at
    assert round(coord._maintenance_until - opened) == 30 * 60
    await _call(client, type="device_sentinel/action", action="maintenance")
    status = (await _call(client, type="device_sentinel/status"))["result"]
    assert status["maintenance"]["open"] is False


async def test_maintenance_without_minutes_uses_the_setting(hass: HomeAssistant, hass_ws_client):
    coord = await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    await _call(client, type="device_sentinel/action", action="maintenance")
    assert round(coord._maintenance_until - coord._maintenance_opened_at) == (
        DEFAULT_MAINTENANCE_MINUTES * 60
    )


async def test_minutes_outside_the_steps_are_refused(hass: HomeAssistant, hass_ws_client):
    await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    for minutes in (7, 0, 90):
        reply = await _call(
            client, type="device_sentinel/action", action="maintenance", minutes=minutes
        )
        assert not reply["success"], minutes


async def test_the_enable_actions_call_the_buttons_code(hass: HomeAssistant, hass_ws_client, monkeypatch):
    coord = await setup_coordinator(hass)
    called = []
    for name in (
        "async_enable_signal_entities",
        "async_enable_last_seen_entities",
        "async_enable_battery_entities",
    ):
        async def _spy(_name=name):
            called.append(_name)
            return {}

        monkeypatch.setattr(coord, name, _spy)
    client = await hass_ws_client(hass)
    for action in ("enable_signals", "enable_last_seen", "enable_battery"):
        assert (await _call(client, type="device_sentinel/action", action=action))["success"]
    assert called == [
        "async_enable_signal_entities",
        "async_enable_last_seen_entities",
        "async_enable_battery_entities",
    ]


async def test_an_unknown_action_is_refused(hass: HomeAssistant, hass_ws_client):
    await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/action", action="reboot")
    assert not reply["success"]


async def test_a_non_admin_is_refused(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    await setup_coordinator(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    reply = await _call(client, type="device_sentinel/status")
    assert not reply["success"]
    assert reply["error"]["code"] == "unauthorized"


async def test_the_marker_moves_on_a_system_event_and_is_pushed(hass: HomeAssistant, hass_ws_client):
    coord = await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/subscribe_changes")
    assert reply["success"]
    first = await client.receive_json()
    start = first["event"]["marker"]
    coord._record_system_event(SYS_RESTART)
    pushed = await client.receive_json()
    assert pushed["event"]["marker"] > start


async def test_the_marker_moves_at_midnight(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    before = coord.change_marker
    await coord._on_midnight(None)
    assert coord.change_marker > before


async def test_the_marker_moves_when_a_problem_opens_and_closes(hass: HomeAssistant):
    from homeassistant.util import dt as dt_util

    from custom_components.device_sentinel.const import (
        DEV_DAILY_MAX,
        DEV_FROZEN_CATEGORY,
        DEV_FROZEN_SINCE,
        FREEZE_ARMING_DAYS,
        FREEZE_CATEGORY_FROZEN,
    )
    from tests.helpers import register_device

    device, (entity_id,) = register_device(hass, "door", name="Door")
    coord = await setup_coordinator(hass)
    hass.states.async_set(entity_id, "on")
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 3600
    before = coord.change_marker
    coord._sync_problem_list()
    opened = coord.change_marker
    assert opened > before
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    coord._sync_problem_list()
    assert coord.change_marker > opened


async def test_an_unchanged_problem_list_leaves_the_marker(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    coord._sync_problem_list()
    before = coord.change_marker
    coord._sync_problem_list()
    assert coord.change_marker == before


async def test_nothing_loaded_is_an_error_not_a_crash(hass: HomeAssistant, hass_ws_client):
    from custom_components.device_sentinel.dashboard_api import async_register_dashboard_api

    async_register_dashboard_api(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/status")
    assert not reply["success"]
    assert reply["error"]["code"] == "not_loaded"


# ------------------------------------------------ the Classification tab


async def test_classification_is_the_files_rows(hass: HomeAssistant, hass_ws_client):
    """One builder feeds the file and the dashboard, so they cannot drift."""
    from tests.helpers import register_device

    register_device(hass, "a", name="Alpha Door")
    register_device(hass, "b", name="Bravo Plug")
    coord = await setup_coordinator(hass)
    client = await hass_ws_client(hass)
    reply = await _call(client, type="device_sentinel/classification")
    assert reply["success"], reply
    result = reply["result"]
    assert result["rows"] == coord.classification_rows()
    names = [row["name"] for row in result["rows"]]
    assert names == sorted(names, key=str.lower)
    watched = [row for row in result["rows"] if row["watched"]]
    assert {row["name"] for row in watched} >= {"Alpha Door", "Bravo Plug"}
    assert all(row["device_id"] for row in result["rows"])
    assert result["watched"] == len(watched)
    assert result["watched"] + result["set_aside"] == len(result["rows"])
    assert set(result) >= {"rows", "watched", "set_aside", "deviceless", "muted_entities"}


async def test_classification_names_the_mute_and_the_reason_set_aside(hass: HomeAssistant, hass_ws_client):
    from tests.helpers import register_device

    device, _ = register_device(hass, "m", name="Muted Panel")
    coord = await setup_coordinator(hass)
    coord._muted_devices = {device.id: "device"}
    coord._set_aside = {"x": ("Old Tracker", "tplink_router", "excluded")}
    client = await hass_ws_client(hass)
    rows = (await _call(client, type="device_sentinel/classification"))["result"]["rows"]
    muted = next(row for row in rows if row["name"] == "Muted Panel")
    assert muted["muted"] == "Global (device)"
    aside = next(row for row in rows if row["name"] == "Old Tracker")
    assert aside == {
        "device_id": "x", "name": "Old Tracker", "integration": "tplink_router",
        "watched": False, "muted": "", "set_aside": "excluded", "copies": 1,
    }
