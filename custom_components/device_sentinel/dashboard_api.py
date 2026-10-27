# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: dashboard_api.py, Version: 0.27.10 (2026-10-27)

"""The WebSocket commands behind the dashboard, admins only.

`device_sentinel/status` returns the header. `device_sentinel/action`
runs a top-row button through the same coordinator code the device
page's buttons call. `device_sentinel/subscribe_changes` pushes the
change marker whenever it moves, so the Refresh button can change
colour without the dashboard asking on a timer. Each tab's own data
command is added with its tab.

The status reply and every change marker also carry `panel`, the hash
of the dashboard file Home Assistant serves this run, so a tab
left open across an update knows it is out of date (rule DASH-14).
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

from .device_actions import MUTE_SOURCES_SAID, NameInUse
from .device_type import TYPE_CHOICES, TYPE_OTHER
from .power_source import power_choices
from .report_brief import RECOMMENDATIONS_CLOSING
from .const import (
    DATA_PANEL_FILE,
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
    TODO_KIND_FROZEN,
    TODO_KIND_NEVER_REPORTED,
)

_REGISTERED = f"{DOMAIN}_dashboard_api"

# Where a sensor turn-on, a power answer or a type can be pressed: its
# device page or its Recommendations card (rule BRIEF-07).
ACT_SOURCES = ["device_page", "recommendations"]


def mutes_for_kinds(kinds: Any) -> list[str]:
    """The mutes offered beside a Problem List item, one per kind it has.

    A silence is the freeze mute's; a device gone, or dropping out, the
    unavailable mute's; then battery and signal (rule MUTE-06).
    """
    silence = (TODO_KIND_FROZEN, TODO_KIND_NEVER_REPORTED)
    wanted = (
        ("freeze", lambda k: k in silence),
        ("unavailable", lambda k: TODO_KIND_FAMILIES.get(k) == "down" and k not in silence),
        ("battery", lambda k: TODO_KIND_FAMILIES.get(k) == "battery"),
        ("signal", lambda k: TODO_KIND_FAMILIES.get(k) == "signal"),
    )
    return [mute for mute, test in wanted if any(test(kind) for kind in kinds)]

ACTION_MAINTENANCE = "maintenance"
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
    # The device page's actions (rule DASH-09).
    websocket_api.async_register_command(hass, ws_device_choices)
    websocket_api.async_register_command(hass, ws_device_rename)
    websocket_api.async_register_command(hass, ws_device_area)
    websocket_api.async_register_command(hass, ws_device_label)
    websocket_api.async_register_command(hass, ws_device_new_area)
    websocket_api.async_register_command(hass, ws_device_new_label)
    websocket_api.async_register_command(hass, ws_device_turn_on)
    websocket_api.async_register_command(hass, ws_device_label_mute)
    websocket_api.async_register_command(hass, ws_recommendation_ack)
    websocket_api.async_register_command(hass, ws_device_battery)
    websocket_api.async_register_command(hass, ws_device_mute)
    websocket_api.async_register_command(hass, ws_device_exclude)
    websocket_api.async_register_command(hass, ws_integration_exclude)
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
    connection.send_result(
        msg["id"], {**coordinator.dashboard_status(), "panel": hass.data.get(DATA_PANEL_FILE)}
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/action",
        vol.Required("action"): vol.In(
            [ACTION_MAINTENANCE]
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
    result = await coordinator.async_toggle_maintenance(msg.get("minutes"))
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
    """Push the change marker now and whenever it moves, with the
    dashboard file served (rule DASH-14). Home Assistant's frontend subscribes
    again when it reconnects after a restart, so the first marker after
    an update reaches an open tab without anyone pressing Refresh."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return

    @callback
    def _forward(marker: int) -> None:
        connection.send_message(
            websocket_api.event_message(
                msg["id"], {"marker": marker, "panel": hass.data.get(DATA_PANEL_FILE)}
            )
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
            # (rule GEN-07); the domain above still opens its page.
            "integration_name": coordinator._integration_name_of(item[TODO_DEVICE_ID]),
            "problem": problem,
            "since": dt_util.utc_from_timestamp(since).isoformat() if since is not None else None,
            "acknowledged": item.get(TODO_STATUS) == "completed",
            # So the tab can say "discovered" with the time, in the
            # brief's word for a device that never reported (rule LIST-10).
            "never_reported": TODO_KIND_NEVER_REPORTED in kinds,
            # The mute beside each problem: the one that matches it. A
            # silence is the freeze mute's, a device gone or dropping out
            # the unavailable mute's (rule MUTE-09).
            "mutes": mutes_for_kinds(kinds),
            # What powers it, beside a battery problem.
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
            # Each written line with its key, whether Simple shows it,
            # and whether it is acknowledged (rules REC-09, REC-07).
            "lines": coordinator.recommendation_lines(),
            "closing": RECOMMENDATIONS_CLOSING,
            # Recommendations about single devices, each with its list,
            # and the Power choices to set them from the list.
            "devices": coordinator.device_recommendations(),
            "power": power_choices(),
            # The Type choices, to set a type from the list.
            "types": {"choices": list(TYPE_CHOICES), "other": TYPE_OTHER},
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
    """Return the Devices tab: every watched device, and the devices on
    the exclusion lists for its Excluded list (rule DASH-12)."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    connection.send_result(msg["id"], {
        "rows": coordinator.dashboard_devices(),
        "excluded": coordinator.dashboard_excluded_devices(),
    })


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
    count again, as a firmware update does (rule FRZ-05). Admin only, as
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
    """Run one device-page act and answer the page (rule DASH-10).

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
        vol.Optional("source", default="device_page"): vol.In(ACT_SOURCES),
    }
)
@callback
def ws_device_power(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Set what powers a device, or clear the owner's entry,
    recorded with where it was pressed (rule BRIEF-07)."""
    def act(c: Any) -> dict[str, Any]:
        c.page_from(msg["source"], lambda: c.page_set_power(
            msg["device_id"], msg.get("choice"), msg.get("quantity"), msg.get("other")
        ))
        # Battery Notes' form for a battery type set here, wherever it
        # was set from, the Recommendations tab too (rule DEV-09).
        return {"report_url": c.power_report_url(msg["device_id"]) if msg.get("choice") else None}

    _page_act(hass, connection, msg, act)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/device_type",
        vol.Required("device_id"): str,
        vol.Optional("choice"): vol.Any(str, None),
        vol.Optional("other"): vol.Any(str, None),
        vol.Optional("source", default="device_page"): vol.In(ACT_SOURCES),
    }
)
@callback
def ws_device_type(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Set what a device is, or go back to what its entities say,
    recorded with where it was pressed (rule BRIEF-07)."""
    _page_act(
        hass, connection, msg,
        lambda c: c.page_from(
            msg["source"],
            lambda: c.page_set_type(msg["device_id"], msg.get("choice"), msg.get("other")),
        ),
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
        vol.Required("type"): "device_sentinel/device_label_mute",
        vol.Required("device_id"): str,
        vol.Required("kind"): vol.In(["everything", "freeze", "unavailable", "battery", "signal"]),
        vol.Exclusive("label_id", "label"): str,
        vol.Exclusive("name", "label"): str,
    }
)
@callback
def ws_device_label_mute(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Mute by label from the device page (rule MUTE-09)."""
    if "label_id" not in msg and "name" not in msg:
        connection.send_error(msg["id"], "invalid_format", "A label or a new label's name is needed")
        return
    _page_act(
        hass, connection, msg,
        lambda c: c.page_label_mute(
            msg["device_id"], msg["kind"], label_id=msg.get("label_id"), name=msg.get("name")
        ),
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
    """Make an area and move a device into it."""
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
    """Make a label and put it on a device."""
    _page_act(hass, connection, msg, lambda c: c.page_new_label(msg["device_id"], msg["name"]))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/device_battery",
        vol.Required("device_id"): str,
        vol.Required("action"): vol.In(["confirm", "cancel", "date"]),
        vol.Optional("day"): str,
    }
)
@callback
def ws_device_battery(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Confirm, cancel, or set the day of a battery replacement (rule BAT-07)."""
    _page_act(
        hass, connection, msg,
        lambda c: c.battery_answer(msg["device_id"], msg["action"], msg.get("day")),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/recommendation_ack",
        vol.Required("on"): bool,
        vol.Exclusive("line", "which"): str,
        vol.Exclusive("kind", "which"): str,
        vol.Optional("device_id"): str,
    }
)
@callback
def ws_recommendation_ack(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Tick or untick one device on one card, or one written line (rule REC-07)."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    try:
        coordinator.set_recommendation_ack(
            msg["on"], kind=msg.get("kind"), device_id=msg.get("device_id"), line=msg.get("line"),
        )
    except ValueError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    connection.send_result(msg["id"], {})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/device_turn_on",
        vol.Required("device_id"): str,
        vol.Required("kind"): vol.In(["last_seen", "node_status", "battery", "signal", "voltage"]),
        vol.Optional("source", default="device_page"): vol.In(ACT_SOURCES),
    }
)
@callback
def ws_device_turn_on(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Switch on one device's own entities of one kind (rule REC-05).

    Admin only, one device and one kind: the only way left to switch on
    another integration's entity since the Enable buttons went. Recorded
    with where it was pressed, its device page or a Recommendations
    card (rule BRIEF-07).
    """
    _page_act(
        hass, connection, msg,
        lambda c: c.page_from(
            msg["source"],
            lambda: {"enabled": c.page_turn_on(msg["device_id"], msg["kind"])},
        ),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/device_mute",
        vol.Required("device_id"): str,
        vol.Required("kind"): vol.In(["everything", "freeze", "unavailable", "battery", "signal"]),
        vol.Required("on"): bool,
        # Where the press was made, for the brief's line (rule BRIEF-07).
        vol.Optional("source", default="device_page"): vol.In(list(MUTE_SOURCES_SAID)),
    }
)
@callback
def ws_device_mute(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Set or lift one kind of mute on a device, as Settings does."""
    _page_act(
        hass, connection, msg,
        lambda c: c.page_set_mute(msg["device_id"], msg["kind"], msg["on"], msg["source"]),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/device_exclude",
        vol.Required("device_id"): str,
        vol.Required("on"): bool,
        # Where it was pressed, for the brief's row (rule BRIEF-07).
        vol.Optional("source", default="device_page"): vol.In(["device_page", "devices_tab"]),
    }
)
@callback
def ws_device_exclude(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Exclude one device, or take it back, as Settings does (rule MUTE-03)."""
    _page_act(
        hass, connection, msg,
        lambda c: c.page_set_excluded(msg["device_id"], msg["on"], msg["source"]),
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "device_sentinel/integration_exclude",
        vol.Required("domain"): str,
        vol.Required("on"): bool,
    }
)
@callback
def ws_integration_exclude(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Exclude an integration, or take it back, from its page (rule MUTE-03).

    Only an integration that owns a device has a page that offers it."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_loaded(connection, msg["id"])
        return
    if coordinator.dashboard_integration(msg["domain"]) is None:
        connection.send_error(msg["id"], "not_found", "No device belongs to that integration")
        return
    try:
        coordinator.page_set_integration_excluded(msg["domain"], msg["on"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "refused", str(err) or "Home Assistant refused the change")
        return
    connection.send_result(msg["id"], {})


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

    Built in the executor, as the reports are, because the tab judges
    every stored day of every device, about 100 ms, and on the event
    loop all of Home Assistant would wait while it did (rule CODE-06).
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
