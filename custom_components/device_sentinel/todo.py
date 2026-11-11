# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: todo.py, Version: 0.28.11 (2026-11-10)

"""Todo platform for the Device Sentinel integration.

One list, todo.device_sentinel_problem_list, holding every problem the detections
find: frozen, unavailable, unknown, and never-reported devices, low
and falling batteries, and railed signals. Three families, and any
wording written for a reader names all three.

The list also carries what is wrong above the devices. When a
coordinator, the broker, the Wi-Fi network or a whole integration goes
down, the devices behind it do not each take a line: one row names the
cause and counts them, reading like `Zigbee2MQTT down: 74 of 77 devices
unavailable` (rule UP-11), and it clears itself when the cause returns.
Two devices keep their own row through such an outage, the one already
broken before it began and the one still down after it clears, because
those are the two the outage does not explain. One item per device,
keyed by its registry id, so a device with two problems carries two
kinds on one line rather than appearing twice. The sync in the
coordinator owns the list: items appear the moment a detection fires,
follow the problems as they come and go, and are deleted the moment the
last one clears.

The acknowledgment lifecycle (rule LIST-03):

- Checking an item is the acknowledgment. It stays on the list,
  marked done, and nothing is sent about it while it sits checked:
  not a push, not the card, not the daily brief. Checking never
  means recovered.
- Recovery deletes the item, acknowledged or not. One symbol, one
  meaning, and the deletion is the automatic re-arm: the next
  failure is a new incident and a fresh item.
- Hand-deleting an item whose device is still down is the hard
  un-acknowledge: the next sync re-adds it and its fault fires on the
  bus again.

There is no add box: the list is maintained by detections alone, so
the create feature is not offered. Text edits do not stick either; the sync rewrites the
wording from the detections.

Order: open items alphabetical by the device's common name, then the
acknowledged block in the order the boxes were checked, oldest
first. Each item's due date is when its earliest problem began, so
the list shows age natively.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.components.homeassistant.const import DATA_EXPOSED_ENTITIES
from homeassistant.components.homeassistant.exposed_entities import (
    KNOWN_ASSISTANTS,
    async_expose_entity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DeviceSentinelConfigEntry
from .const import (
    ATTR_SENTINEL_TYPE,
    ATTR_SENTINEL_VERSION,
    DOMAIN,
    SENTINEL_TYPE_PROBLEM_LIST,
    TODO_DESCRIPTION,
    TODO_KINDS,
    TODO_STATUS,
    TODO_SUMMARY,
    TODO_UID,
)
from .coordinator import DeviceSentinelCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceSentinelConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Device Sentinel problem list."""
    async_add_entities([DeviceSentinelTodoList(entry.runtime_data)])


# Marked on the entity's own registry options once it has been hidden,
# so a person who later shows it to Assist keeps that choice.
_ASSIST_HIDDEN = "assist_hidden"


@callback
def hide_from_assistants_once(hass: HomeAssistant, entity_id: str) -> None:
    """Hide the Problem List from Assist and the voice assistants, once.

    Home Assistant shows a to-do list to Assist by default, and with it
    any conversation agent, an AI one included: one could read the
    house's problems, and mark an item done, which takes it off the
    card and out of the alerts (rule NOTE-08). So it is hidden the first
    time the list is set up on this release, and a person who wants
    Assist to see it turns that on under Settings, Voice assistants,
    Expose. Done once, never again, so that choice is kept (rule
    LIST-14). Where Home Assistant's exposure settings are not loaded,
    nothing is marked and it is tried at the next start.
    """
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is None or DATA_EXPOSED_ENTITIES not in hass.data:
        return
    own = dict(entry.options.get(DOMAIN) or {})
    if own.get(_ASSIST_HIDDEN):
        return
    for assistant in KNOWN_ASSISTANTS:
        async_expose_entity(hass, assistant, entity_id, False)
    own[_ASSIST_HIDDEN] = True
    registry.async_update_entity_options(entity_id, DOMAIN, own)


class DeviceSentinelTodoList(TodoListEntity):
    """The problem list, checkable, persistent, detection-fed."""

    _attr_has_entity_name = True
    # Named rather than inheriting the device name: an unnamed
    # entity renders as "Device Sentinel" on the device page, which
    # tells a user nothing about what the row holds.
    _attr_translation_key = "problem_list"
    _attr_icon = "mdi:clipboard-alert-outline"
    _attr_should_poll = False
    # No CREATE: the sync alone maintains the list, so the card shows
    # no add box and todo.add_item is rejected. No SET_DESCRIPTION:
    # the sync owns the wording, so offering the edit would only
    # invite text that reverts on the next pass. UPDATE stays for the
    # checkbox, DELETE for the hard un-acknowledge.
    _attr_supported_features = (
        TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, coordinator: DeviceSentinelCoordinator) -> None:
        """Initialize the problem list."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_problems"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Device Sentinel",
            manufacturer="The Thinking Home",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=coordinator.version,
        )
        self._attr_extra_state_attributes = {
            ATTR_SENTINEL_TYPE: SENTINEL_TYPE_PROBLEM_LIST,
            ATTR_SENTINEL_VERSION: coordinator.version,
        }

    async def async_added_to_hass(self) -> None:
        """Track coordinator refreshes so sync writes surface."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_refresh)
        )
        hide_from_assistants_once(self.hass, self.entity_id)

    def _handle_refresh(self) -> None:
        """Reflect the stored items."""
        self.async_write_ha_state()

    @staticmethod
    def _earliest_since(record: dict) -> datetime | None:
        """Return the item's due date: when its earliest problem
        began, local, so the card shows age natively. None when no
        kind carries a stamp, which cannot happen for a sync-built
        item but keeps a malformed record harmless."""
        stamps = [
            since
            for since in (record.get(TODO_KINDS) or {}).values()
            if since is not None
        ]
        if not stamps:
            return None
        return dt_util.as_local(dt_util.utc_from_timestamp(min(stamps)))

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the stored items, already in display order."""
        return [
            TodoItem(
                uid=record[TODO_UID],
                summary=record[TODO_SUMMARY],
                description=record.get(TODO_DESCRIPTION),
                due=self._earliest_since(record),
                status=(
                    TodoItemStatus.COMPLETED
                    if record[TODO_STATUS] == "completed"
                    else TodoItemStatus.NEEDS_ACTION
                ),
            )
            for record in self._coordinator.todo_items
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Apply a user edit, meaning the check that acknowledges.

        Checking an item marks it completed and it stays on the list;
        the coordinator stamps the check time, which orders the
        acknowledged block. Unchecking reopens it. Summary text sent
        along with the status is ignored on purpose: the sync owns
        the wording.
        """
        # A status Home Assistant did not send is not a status of
        # needs_action. The coordinator ignores a status of None;
        # folding None into needs_action here would defeat that guard,
        # and a caller that updates text alone would silently reopen
        # the item.
        status: str | None = None
        if item.status is not None:
            status = (
                "completed"
                if item.status == TodoItemStatus.COMPLETED
                else "needs_action"
            )
        await self._coordinator.async_todo_update(
            uid=item.uid,
            status=status,
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items a user removed by hand."""
        await self._coordinator.async_todo_delete(uids)
