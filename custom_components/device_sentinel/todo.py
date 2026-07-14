"""Todo platform for the Device Sentinel integration.

One list, todo.device_sentinel, holding every problem the integration
finds: low batteries, frozen devices, unavailable entities, weak
signals. The type lives on each item rather than in separate lists,
so a novice has one place to look and loses nothing.

The acknowledgment lifecycle, carried from Sentinel Notify:

- Checking an item is the acknowledgment. It stays on the list,
  marked done, and goes quiet. Checking never means recovered.
- Recovery deletes the item. One symbol, one meaning.
- An acknowledged item that recovers and fails again re-arms
  naturally: the recovery deleted it, the new failure adds it fresh.
- Items the integration did not create are never touched, so a
  user's own additions to this list survive every refresh.

This is the backbone. Nothing populates the list yet: the engine that
adds on detection and deletes on recovery arrives with Step 5. The
list is real, checkable, persistent, and empty until then.

Order is alphabetical by the device or entity common name, enforced
on every write, because a readable list beats one ordered by age.
The integration owns the order, so user reordering does not stick:
this is a system-maintained problem list, not a personal one.
"""

from __future__ import annotations

import uuid
from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DeviceSentinelConfigEntry
from .const import (
    ATTR_SENTINEL_TYPE,
    ATTR_SENTINEL_VERSION,
    DOMAIN,
    SENTINEL_TYPE_PROBLEM_LIST,
    TODO_DESCRIPTION,
    TODO_KIND,
    TODO_OURS,
    TODO_SORT_NAME,
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
    """The problem list, checkable and persistent."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:clipboard-alert-outline"
    _attr_should_poll = False
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
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
        """Track coordinator refreshes so engine writes surface."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_refresh)
        )

    def _handle_refresh(self) -> None:
        """Reflect the stored items."""
        self.async_write_ha_state()

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the stored items, already alphabetical."""
        return [
            TodoItem(
                uid=record[TODO_UID],
                summary=record[TODO_SUMMARY],
                description=record.get(TODO_DESCRIPTION),
                status=(
                    TodoItemStatus.COMPLETED
                    if record[TODO_STATUS] == "completed"
                    else TodoItemStatus.NEEDS_ACTION
                ),
            )
            for record in self._coordinator.todo_items
        ]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item a user typed into the list.

        User additions are foreign items: they are marked as not ours
        so the engine never deletes or rewrites them.
        """
        await self._coordinator.async_todo_add(
            summary=item.summary or "",
            description=item.description,
            sort_name=item.summary or "",
            kind=None,
            ours=False,
            uid=item.uid or uuid.uuid4().hex,
        )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Apply a user edit, including the check that acknowledges.

        Checking an item marks it completed and it stays on the list.
        The engine reads that status as the acknowledgment and goes
        quiet about it; only a recovery removes it.
        """
        await self._coordinator.async_todo_update(
            uid=item.uid,
            summary=item.summary,
            description=item.description,
            status=(
                "completed"
                if item.status == TodoItemStatus.COMPLETED
                else "needs_action"
            ),
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items a user removed by hand."""
        await self._coordinator.async_todo_delete(uids)
