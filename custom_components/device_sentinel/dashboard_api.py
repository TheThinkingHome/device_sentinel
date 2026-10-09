# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: dashboard_api.py, Version: 0.25.1 (2026-10-08)

"""The WebSocket commands behind the dashboard, admins only.

`device_sentinel/status` returns the header. `device_sentinel/action`
runs a top-row button through the same coordinator code the device
page's buttons call. `device_sentinel/subscribe_changes` pushes the
change marker whenever it moves, so the Refresh button can change
colour without the dashboard asking on a timer. Each tab's own data
command is added with its tab.
"""

from __future__ import annotations

from datetime import date
from collections.abc import Callable
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .device_actions import NameInUse
from .power_source import power_choices
from .report_brief import RECOMMENDATIONS_CLOSING
from .const import (
    DOMAIN,
    TODO_DEVICE_ID,
    TODO_KINDS,
    TODO_SORT_NAME,
    TODO_STATUS,
    TODO_SUMMARY,
    TODO_UID,
    MAINTENANCE_MINUTES_MAX,
    MAINTENANCE_MINUTES_MIN,
    MAINTENANCE_MINUTES_STEP,
    SET_ASIDE_MEANINGS,
    TODO_KIND_FAMILIES,
)

_REGISTERED = f"{DOMAIN}_dashboard_api"

ACTION_MAINTENANCE = "maintenance"
ACTION_ENABLE_SIGNALS = "enable_signals"
ACTION_ENABLE_LAST_SEEN = "enable_last_seen"
ACTION_ENABLE_BATTERY = "enable_battery"

# The top row's enable buttons, each the device page button's own call.
_ENABLE_CALLS = {
    ACTION_ENABLE_SIGNALS: "async_enable_signal_entities",
    ACTION_ENABLE_LAST_SEEN: "async_enable_last_seen_entities",
    ACTION_ENABLE_BATTERY: "async_enable_battery_entities",
}

_MINUTES = list(
    range(
        MAINTENANCE_MINUTES_MIN,
        MAINTENANCE_MINUTES_MAX + 1,
        MAINTENANCE_MINUTES_STEP,
    )
)


@callback
def async_register_dashboard_api(hass: HomeAssistant) -> None:
    """Register the commands once per Home Assistant run."""
    if hass.data.get(_REGISTERED):
        return
    hass.data[_REGISTERED] = True
    websocket_api.async_register_command(hass, ws_status)
    websocket_api.async_register_command(hass, ws_action)
    websocket_api.async_register_command(hass, ws_subscribe_changes)
    websocket_api.async_register_command(hass, ws_classification)
    websocket_api.async_register_command(hass, ws_problem_list)
    websocket_api.async_register_command(hass, ws_acknowledge)
    websocket_api.async_register_command(hass, ws_recommendations)
    websocket_api.async_register_command(hass, ws_integrations)
    websocket_api.async_register_command(hass, ws_integration)
    websocket_api.async_register_command(hass, ws_devices)
    websocket_api.async_register_command(hass, ws_device)
    websocket_api.async_register_command(hass, ws_use_trimmed_maximum)
    # The device page's actions (0.24.5).
    websocket_api.async_register_command(hass, ws_device_choices)
    websocket_api.async_register_command(hass, ws_device_rename)
    websocket_api.async_register_command(hass, ws_device_area)
    websocket_api.async_register_command(hass, ws_device_label)
    websocket_api.async_register_command(hass, ws_device_new_area)
    websocket_api.async_register_command(hass, ws_device_new_label)
    websocket_api.async_register_command(hass, ws_device_last_seen)
    websocket_api.async_register_command(hass, ws_device_mute)
    websocket_api.async_register_command(hass, ws_device_power)
    websocket_api.async_register_command(hass, ws_device_type)
    websocket_api.async_register_command(hass, ws_brief)
    websocket_api.async_register_command(hass, ws_battery_trends)
    websocket_api.async_register_command(hass, ws_signal_trends)


def _coordinator(hass: HomeAssistant) -> Any | None:
    """The running coordinator, or None when Device Sentinel is not loaded."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return getattr(entry, "runtime_data", None)
    return None


def _not_loaded(connection: websocket_api.ActiveConnection, msg_id: int) -> None:
    connection.send_error(msg_id, "not_loaded", "Device Sentinel is not loaded")


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "device_sentinel/status"})
@callback
def ws_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the header: each part the house has, and maintenance."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    connection.send_result(msg["id"], coordinator.dashboard_status())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/action",
        vol.Required("action"): vol.In(
            [ACTION_MAINTENANCE, *_ENABLE_CALLS]
        ),
        vol.Optional("minutes"): vol.In(_MINUTES),
    }
)
@websocket_api.async_response
async def ws_action(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run one top-row button.

    Maintenance takes an optional length, chosen per press within the
    same bounds as the setting; without one it uses the setting, which
    stays the default. It opens the window, or closes an open one.
    """
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    action = msg["action"]
    if action == ACTION_MAINTENANCE:
        result = await coordinator.async_toggle_maintenance(msg.get("minutes"))
    else:
        result = await getattr(coordinator, _ENABLE_CALLS[action])()
    connection.send_result(msg["id"], result if isinstance(result, dict) else {})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "device_sentinel/subscribe_changes"}
)
@callback
def ws_subscribe_changes(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Push the change marker now and whenever it moves."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return

    @callback
    def _forward(marker: int) -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], {"marker": marker})
        )

    connection.subscriptions[msg["id"]] = coordinator.async_subscribe_changes(
        _forward
    )
    connection.send_result(msg["id"])
    _forward(coordinator.change_marker)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "device_sentinel/classification"})
@callback
def ws_classification(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the Classification tab: every device's standing, and totals.

    The rows come from the same builder as classification.md, so the
    tab and the file can never disagree.
    """
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    rows = coordinator.classification_rows()
    connection.send_result(
        msg["id"],
        {
            "rows": rows,
            "watched": sum(1 for row in rows if row["watched"]),
            "set_aside": sum(1 for row in rows if not row["watched"]),
            "deviceless": coordinator.deviceless_count,
            # The key under the table, the same words as the report's.
            "set_aside_meanings": [list(pair) for pair in SET_ASIDE_MEANINGS],
            "muted_entities": [
                {"entity_id": entity_id, "reason": reason}
                for entity_id, reason in sorted(coordinator._muted_entities.items())
            ],
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "device_sentinel/problem_list"})
@callback
def ws_problem_list(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the Problem List tab: every to-do item, acknowledged too.

    Read from the to-do items themselves, in their own order, which is
    worst first with the acknowledged block after it. The brief's Now
    table leaves acknowledged items out; the to-do list shows them,
    and this tab is the to-do list.
    """
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    rows = []
    for item in coordinator.todo_items:
        name = item.get(TODO_SORT_NAME) or ""
        summary = item[TODO_SUMMARY]
        problem = summary[len(name) + 2:] if summary.startswith(f"{name}: ") else summary
        kinds = item[TODO_KINDS]
        since = min((v for v in kinds.values() if isinstance(v, (int, float))), default=None)
        rows.append({
            "uid": item[TODO_UID],
            "device_id": item[TODO_DEVICE_ID],
            "name": name,
            "integration": coordinator._watched.get(item[TODO_DEVICE_ID], ""),
            # Its name as shown, Zigbee2MQTT for a Zigbee2MQTT device
            # (0.24.11); the domain above still opens its page.
            "integration_name": coordinator._integration_name_of(item[TODO_DEVICE_ID]),
            "problem": problem,
            "since": dt_util.utc_from_timestamp(since).isoformat() if since is not None else None,
            "acknowledged": item.get(TODO_STATUS) == "completed",
            # The mute beside each problem (0.24.5): the one that
            # matches it, by the kinds' families.
            "mutes": [
                mute for family, mute in (("down", "freeze"), ("battery", "battery"), ("signal", "signal"))
                if any(TODO_KIND_FAMILIES.get(kind) == family for kind in kinds)
            ],
            # What powers it, beside a battery problem (0.24.7).
            "power": (
                coordinator.power_text(item[TODO_DEVICE_ID])
                if any(TODO_KIND_FAMILIES.get(kind) == "battery" for kind in kinds)
                else None
            ),
        })
    connection.send_result(msg["id"], {"rows": rows})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/acknowledge",
        vol.Required("uid"): str,
        vol.Required("acknowledged"): bool,
    }
)
@websocket_api.async_response
async def ws_acknowledge(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Acknowledge a problem, or take the acknowledgment back.

    The to-do list's own path, so a tick here is the same act as a tick
    there: same record, same silence, same entry on the timeline.
    """
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    if not any(item[TODO_UID] == msg["uid"] for item in coordinator.todo_items):
        connection.send_error(msg["id"], "not_found", "That problem has already cleared")
        return
    await coordinator.async_todo_update(
        uid=msg["uid"],
        status="completed" if msg["acknowledged"] else "needs_action",
    )
    connection.send_result(msg["id"], {})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "device_sentinel/recommendations"})
@websocket_api.async_response
async def ws_recommendations(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the Recommendations tab: the brief's own lines and closing.

    The wireless adapter is asked about first, as the brief does before
    it is written, because the Supervisor answers only on the loop.
    """
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    await coordinator.async_check_unused_adapter()
    connection.send_result(
        msg["id"],
        {
            "lines": coordinator._recommendation_items(),
            "closing": RECOMMENDATIONS_CLOSING,
            # Recommendations about single devices, each with its list,
            # and the Power choices to set them from the list (0.24.9).
            "devices": coordinator.device_recommendations(),
            "power": power_choices(),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "device_sentinel/integrations"})
@callback
def ws_integrations(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the Integrations tab: one row per integration with a device."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    connection.send_result(msg["id"], {"rows": coordinator.dashboard_integrations()})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "device_sentinel/integration", vol.Required("domain"): str}
)
@callback
def ws_integration(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one integration's page."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    page = coordinator.dashboard_integration(msg["domain"])
    if page is None:
        connection.send_error(msg["id"], "not_found", "No device belongs to that integration")
        return
    connection.send_result(msg["id"], page)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "device_sentinel/devices"})
@callback
def ws_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the Devices tab: every watched device."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    connection.send_result(msg["id"], {"rows": coordinator.dashboard_devices()})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "device_sentinel/device", vol.Required("device_id"): str}
)
@callback
def ws_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one device's page. The page asks again every minute."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    page = coordinator.dashboard_device(msg["device_id"])
    if page is None:
        connection.send_error(msg["id"], "not_found", "Device Sentinel has no record of that device")
        return
    connection.send_result(msg["id"], page)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/use_trimmed_maximum",
        vol.Required("device_id"): str,
    }
)
@callback
def ws_use_trimmed_maximum(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """The device page's button: start a device's Log-Normal Percentile
    count again, as a firmware update does (0.24.0). Admin only, as
    every act on the dashboard is."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    if not coordinator.use_trimmed_maximum(msg["device_id"]):
        connection.send_error(msg["id"], "not_found", "Device Sentinel has no record of that device")
        return
    connection.send_result(msg["id"], {})


def _page_act(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    act: Callable[[Any], Any],
) -> None:
    """Run one device-page act and answer the page (0.24.5).

    An unknown device answers not_found; a name another device shows
    answers name_in_use with the sentence the page shows; anything Home
    Assistant refuses answers refused with its own reason, which the
    page shows under the row, keeping the row's old value.
    """
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    try:
        result = act(coordinator)
    except KeyError:
        connection.send_error(msg["id"], "not_found", "Device Sentinel has no record of that device")
        return
    except NameInUse as clash:
        where = f" (in the {clash.area})" if clash.area else ""
        connection.send_error(
            msg["id"], "name_in_use", f"Another device is already named {clash.name}{where}."
        )
        return
    except (HomeAssistantError, ValueError) as err:
        connection.send_error(msg["id"], "refused", str(err) or "Home Assistant refused the change")
        return
    connection.send_result(msg["id"], result if isinstance(result, dict) else {})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "device_sentinel/device_choices"})
@callback
def ws_device_choices(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The areas and labels a picker offers, each label with its meaning."""
    _page_act(hass, connection, msg, lambda c: c.page_choices())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/device_rename",
        vol.Required("device_id"): str,
        vol.Optional("name"): vol.Any(str, None),
        vol.Optional("confirm", default=False): bool,
    }
)
@callback
def ws_device_rename(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Rename a device; an empty name resets it to the integration's."""
    _page_act(
        hass, connection, msg,
        lambda c: c.page_rename(msg["device_id"], msg.get("name"), msg["confirm"]),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/device_power",
        vol.Required("device_id"): str,
        vol.Optional("choice"): vol.Any(str, None),
        vol.Optional("quantity"): vol.Any(int, None),
        vol.Optional("other"): vol.Any(str, None),
    }
)
@callback
def ws_device_power(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Set what powers a device, or clear the owner's entry (0.24.7)."""
    _page_act(
        hass, connection, msg,
        lambda c: c.page_set_power(
            msg["device_id"], msg.get("choice"), msg.get("quantity"), msg.get("other")
        ),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/device_type",
        vol.Required("device_id"): str,
        vol.Optional("choice"): vol.Any(str, None),
        vol.Optional("other"): vol.Any(str, None),
    }
)
@callback
def ws_device_type(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Set what a device is, or go back to what its entities say (0.25.1)."""
    _page_act(
        hass, connection, msg,
        lambda c: c.page_set_type(msg["device_id"], msg.get("choice"), msg.get("other")),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/device_area",
        vol.Required("device_id"): str,
        vol.Optional("area_id"): vol.Any(str, None),
    }
)
@callback
def ws_device_area(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Move a device to an area, or to none."""
    _page_act(hass, connection, msg, lambda c: c.page_set_area(msg["device_id"], msg.get("area_id")))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/device_label",
        vol.Required("device_id"): str,
        vol.Required("label_id"): str,
        vol.Required("add"): bool,
    }
)
@callback
def ws_device_label(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Put a label on a device or take it off; never deletes the label."""
    _page_act(
        hass, connection, msg,
        lambda c: c.page_label(msg["device_id"], msg["label_id"], msg["add"]),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/device_new_area",
        vol.Required("device_id"): str,
        vol.Required("name"): str,
    }
)
@callback
def ws_device_new_area(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Make an area and move a device into it (0.25.0)."""
    _page_act(hass, connection, msg, lambda c: c.page_new_area(msg["device_id"], msg["name"]))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/device_new_label",
        vol.Required("device_id"): str,
        vol.Required("name"): str,
    }
)
@callback
def ws_device_new_label(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Make a label and put it on a device (0.25.0)."""
    _page_act(hass, connection, msg, lambda c: c.page_new_label(msg["device_id"], msg["name"]))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "device_sentinel/device_last_seen", vol.Required("device_id"): str}
)
@callback
def ws_device_last_seen(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Switch on one device's Last Seen entity."""
    _page_act(
        hass, connection, msg,
        lambda c: {"enabled": c.page_enable_last_seen(msg["device_id"])},
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/device_mute",
        vol.Required("device_id"): str,
        vol.Required("kind"): vol.In(["everything", "freeze", "battery", "signal"]),
        vol.Required("on"): bool,
    }
)
@callback
def ws_device_mute(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Set or lift one kind of mute on a device, as Settings does."""
    _page_act(
        hass, connection, msg,
        lambda c: c.page_set_mute(msg["device_id"], msg["kind"], msg["on"]),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "device_sentinel/brief", vol.Optional("day"): str}
)
@callback
def ws_brief(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one day of the brief. Without a day, today."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    asked = msg.get("day")
    if asked is None:
        day = dt_util.now().date()
    else:
        try:
            day = date.fromisoformat(asked)
        except ValueError:
            connection.send_error(msg["id"], "not_found", "That is not a day")
            return
    page = coordinator.dashboard_brief(day)
    if page is None:
        connection.send_error(msg["id"], "not_found", "That day is no longer kept")
        return
    connection.send_result(msg["id"], page)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "device_sentinel/battery_trends"})
@callback
def ws_battery_trends(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the Battery Trends tab."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    connection.send_result(msg["id"], coordinator.battery_trends())


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "device_sentinel/signal_trends"})
@websocket_api.async_response
async def ws_signal_trends(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the Signal Trends tab.

    Built in the executor, as the reports are (0.22.20). The tab judges
    every stored day of every device, about 100 ms on the fleets held,
    and on the event loop all of Home Assistant waited while it did.
    It reads the same records the report writer reads from the
    executor, and its list of watched records is a copy taken when it
    starts.
    """
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    page = await hass.async_add_executor_job(coordinator.signal_trends)
    connection.send_result(msg["id"], page)
