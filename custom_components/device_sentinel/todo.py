# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: todo.py, Version: 0.6.0 (2026-07-21)

"""Todo platform for the Device Sentinel integration.

One list, todo.device_sentinel, holding every problem the detections
find: frozen, unavailable, unknown, and never-reported devices, low
batteries, and signal problems. One item per device, keyed by its
registry id, so a device with two problems carries two kinds on one
line rather than appearing twice. The sync in the coordinator owns
the list: items appear the moment a detection fires, follow the
problems as they come and go, and are deleted the moment the last
one clears.

The acknowledgment lifecycle, carried from Sentinel Notify:

- Checking an item is the acknowledgment. It stays on the list,
  marked done, and Step 8 will send nothing about it while it sits
  checked. Checking never means recovered.
- Recovery deletes the item, acknowledged or not. One symbol, one
  meaning, and the deletion is the automatic re-arm: the next
  failure is a new incident and a fresh item.
- Hand-deleting an item whose device is still down is the hard
  un-acknowledge: the next sync re-adds and re-announces it.

There is no add box: the list is maintained by detections alone, so
the create feature is not offered and hand-typed items are gone
(anything stored without a device id was purged at the 0.6.0
upgrade). Text edits do not stick either; the sync rewrites the
wording from the detections.

Order: open items alphabetical by the device's common name, then the
acknowledged block in the order the boxes were checked, oldest
first. Each item's due date is when its earliest problem began, so
the list shows age natively.
"""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
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


class DeviceSentinelTodoList(TodoListEntity):
    """The problem list, checkable, persistent, detection-fed."""

    _attr_has_entity_name = True
    # Named rather than inheriting the device name: an unnamed
    # entity renders as "Device Sentinel" on the device page, which
    # tells a user nothing about what the row holds.
    _attr_name = "Problem List"
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

    def _handle_refresh(self) -> None:
        """Reflect the stored items."""
        self.async_write_ha_state()

    @staticmethod
    def _earliest_since(record: dict) -> object:
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
        await self._coordinator.async_todo_update(
            uid=item.uid,
            status=(
                "completed"
                if item.status == TodoItemStatus.COMPLETED
                else "needs_action"
            ),
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items a user removed by hand."""
        await self._coordinator.async_todo_delete(uids)
