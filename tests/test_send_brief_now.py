# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_send_brief_now.py, Version: 0.30.2 (2026-11-22)

"""Send Brief from the dashboard's menu, and the event a sent brief fires
(rules BRIEF-18, DASH-20).

The menu's Send Brief sends the brief as its file holds it, the last 24
hours, titled with when it was sent, to the Daily Brief targets: at any
hour and whatever How Often says, since a person asked. It never closes
the day. Every brief sent, on its schedule or from the menu, fires
device_sentinel_brief_sent, never carrying the brief's text.
"""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.device_sentinel.const import (
    CONF_BRIEF_TARGETS,
    CONF_REMINDER_MODE,
    DATA_BRIEF_CLOSED_DAY,
    EVENT_BRIEF_SENT,
    REMINDER_MODE_NONE,
)

from tests.helpers import record_events, setup_entry

PHONE = "notify.mobile_app_pixel"
MAIL = "notify.house_mail"


def _services(hass: HomeAssistant) -> list[ServiceCall]:
    hass.data["notify_services"] = {
        "mobile_app": [SimpleNamespace(_service_name="mobile_app", registered_targets={"mobile_app_pixel": "x"})],
        "smtp": [SimpleNamespace(_service_name="house_mail", registered_targets={})],
    }
    calls: list[ServiceCall] = []

    async def _record(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("notify", "mobile_app_pixel", _record)
    hass.services.async_register("notify", "house_mail", _record)
    return calls


async def _house(hass, targets, **options):
    entry = await setup_entry(hass)
    calls = _services(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_BRIEF_TARGETS: targets, **options})
    await hass.async_block_till_done()
    return entry.runtime_data, calls


async def test_send_brief_goes_now_titled_with_the_last_24_hours(hass: HomeAssistant):
    coord, calls = await _house(hass, [MAIL], **{CONF_REMINDER_MODE: REMINDER_MODE_NONE})
    events = record_events(hass, EVENT_BRIEF_SENT)
    closed = coord.data.get(DATA_BRIEF_CLOSED_DAY)
    result = await coord.async_send_brief_now()
    await hass.async_block_till_done()
    assert result == {"sent": 1, "targets": 1}
    assert [call.service for call in calls] == ["house_mail"], "sent though How Often is Never"
    title = calls[0].data["title"]
    assert title.startswith("Device Sentinel Daily Brief, Last 24 Hours (") and title.endswith("M)"), "12-hour unless asked"
    assert coord.data.get(DATA_BRIEF_CLOSED_DAY) == closed, "the day is not closed"
    assert len(events) == 1
    event = events[0]
    assert event["on_demand"] is True and event["targets"] == 1 and event["sent"] == 1
    assert event["from"] < event["to"]
    assert "text" not in event and "message" not in event


async def test_with_no_target_nothing_is_sent_or_fired(hass: HomeAssistant):
    coord, calls = await _house(hass, [PHONE])
    events = record_events(hass, EVENT_BRIEF_SENT)
    assert coord.brief_targets_usable() == [], "a phone is never a brief target"
    assert coord.dashboard_status()["brief_targets"] == 0
    assert await coord.async_send_brief_now() == {"sent": 0, "targets": 0}
    await hass.async_block_till_done()
    assert calls == [] and events == []


async def test_the_scheduled_brief_fires_the_event_too(hass: HomeAssistant):
    coord, calls = await _house(hass, [MAIL])
    coord._brief_should_send = lambda: True
    coord.data[DATA_BRIEF_CLOSED_DAY] = None
    events = record_events(hass, EVENT_BRIEF_SENT)
    await coord._on_brief_time(None)
    await hass.async_block_till_done()
    assert [call.service for call in calls] == ["house_mail"]
    assert calls[0].data["title"] == "Device Sentinel Daily Brief"
    assert len(events) == 1 and events[0]["on_demand"] is False and events[0]["sent"] == 1
    assert events[0]["from"] < events[0]["to"]


def test_the_title_carries_the_date_and_the_persons_clock():
    from datetime import datetime

    from custom_components.device_sentinel.report_brief import brief_title_when

    afternoon = datetime(2026, 11, 22, 14, 20)
    assert brief_title_when(afternoon, True) == "22 Nov 2026, 2:20 PM"
    assert brief_title_when(afternoon, False) == "22 Nov 2026, 14:20"
    assert brief_title_when(datetime(2026, 1, 5, 0, 7), True) == "5 Jan 2026, 12:07 AM"
    assert brief_title_when(datetime(2026, 1, 5, 0, 7), False) == "5 Jan 2026, 00:07"
    assert brief_title_when(datetime(2026, 7, 1, 12, 0), True) == "1 Jul 2026, 12:00 PM"


async def test_send_brief_titles_with_the_clock_the_dashboard_asks_for(
    hass: HomeAssistant, hass_ws_client, freezer
):
    await hass.config.async_set_time_zone("America/Guayaquil")
    coord, calls = await _house(hass, [MAIL])
    client = await hass_ws_client(hass)
    freezer.move_to("2026-11-22T19:20:00+00:00")
    await client.send_json_auto_id({"type": "device_sentinel/action", "action": "send_brief", "hour12": False})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": "device_sentinel/action", "action": "send_brief"})
    assert (await client.receive_json())["success"]
    titles = [call.data["title"] for call in calls]
    assert titles == [
        "Device Sentinel Daily Brief, Last 24 Hours (22 Nov 2026, 14:20)",
        "Device Sentinel Daily Brief, Last 24 Hours (22 Nov 2026, 2:20 PM)",
    ]


async def test_the_menu_actions_are_for_admins(hass: HomeAssistant, hass_ws_client, hass_admin_user):
    coord, calls = await _house(hass, [MAIL])
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "device_sentinel/action", "action": "send_brief"})
    reply = await client.receive_json()
    assert reply["success"] and reply["result"] == {"sent": 1, "targets": 1}
    await client.send_json_auto_id({"type": "device_sentinel/action", "action": "regenerate_reports"})
    reply = await client.receive_json()
    assert reply["success"]
    hass_admin_user.groups = []
    await client.send_json_auto_id({"type": "device_sentinel/action", "action": "send_brief"})
    reply = await client.receive_json()
    assert not reply["success"] and reply["error"]["code"] == "unauthorized"


async def test_a_target_saved_as_text_is_one_target(hass: HomeAssistant):
    """A hand-edited file can hold the targets as one piece of text: it is
    one target, never one per letter (rule BRIEF-11)."""
    coord, calls = await _house(hass, MAIL)
    assert coord.brief_targets_usable() == [MAIL]
    assert await coord.async_send_brief_now() == {"sent": 1, "targets": 1}
    assert [call.service for call in calls] == ["house_mail"]
