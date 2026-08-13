"""Tests for ambiguous names and stale exclusion picks.

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_stale_picks.py, Version: 0.13.2 (2026-08-13)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

Two faults found on the reference system on the same morning, and
they share a cause: a device the reports name but a person cannot
find, and a pick the settings screen holds but cannot show. Both come
from a surface printing less than it knows.
"""

from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.config_flow import (
    _device_options,
    _surviving_picks,
)
from custom_components.device_sentinel.const import (
    CONF_EXCLUDED_DEVICES,
    DATA_DEVICES,
)

from .helpers import register_device, setup_coordinator


class _FakeRegistry:
    """A registry holding exactly the ids it is given."""

    def __init__(self, ids: set[str]) -> None:
        self._ids = ids

    def async_get(self, device_id: str) -> object | None:
        return object() if device_id in self._ids else None


class _NamedRegistry:
    """A registry whose devices carry names, for the orphan label."""

    class _Device:
        def __init__(self, name: str) -> None:
            self.name = name
            self.name_by_user = None

    def __init__(self, names: dict[str, str]) -> None:
        self._names = names

    def async_get(self, device_id: str) -> object | None:
        name = self._names.get(device_id)
        return self._Device(name) if name else None


def _row(device_id: str, name: str, integration: str) -> dict[str, Any]:
    return {
        "device_id": device_id,
        "name": name,
        "integration": integration,
        "labels": frozenset(),
    }


def _label(row: dict[str, Any]) -> str:
    return f"{row['name']} ({row['integration']})"


def test_a_pick_the_registry_still_holds_survives():
    """A device with a disabled battery entity leaves that screen's
    rows while staying in the registry. Disabling an entity for an
    afternoon must not cost the exclusion that goes with it."""
    registry = _FakeRegistry({"alive"})

    assert _surviving_picks(["alive"], set(), registry) == ["alive"]


def test_a_pick_the_registry_has_lost_is_pruned():
    """The one case where absence is proof rather than inference
    (ruling #45): the registry holds every device of every config
    entry, loaded or not, so an id it cannot find belongs to hardware
    that has been removed. Its name went with it, so keeping the pick
    could only ever show a raw id."""
    registry = _FakeRegistry(set())

    assert _surviving_picks(["deleted"], set(), registry) == []


def test_a_covered_pick_still_goes():
    """The ladder of ruling #45 is unchanged: a broader exclusion
    still erases the narrower pick it covers, whatever the registry
    says."""
    registry = _FakeRegistry({"alive"})

    assert _surviving_picks(["alive"], {"alive"}, registry) == []


def test_the_picker_offers_a_pick_its_rows_have_lost():
    """The bug this release fixes: a screen holding a value its own
    selector did not offer failed to save at all, so no exclusion of
    any kind could be changed while one such pick sat in the options.
    The device is named rather than shown as an id, because a name is
    what makes the choice possible."""
    rows = [_row("listed", "Door Entryway", "mqtt")]
    registry = _NamedRegistry({"orphan": "Motion Hall"})

    options = _device_options(
        rows, ["listed", "orphan"], set(), _label, registry
    )

    values = [option["value"] for option in options]
    labels = {option["value"]: option["label"] for option in options}
    assert values == ["listed", "orphan"]
    assert labels["orphan"] == "Motion Hall (not currently listed)"


def test_the_picker_does_not_offer_a_deleted_pick():
    """A pick the registry has lost is pruned on save, so offering it
    would put a raw id in front of a person for no purpose."""
    rows = [_row("listed", "Door Entryway", "mqtt")]
    registry = _NamedRegistry({})

    options = _device_options(rows, ["listed", "gone"], set(), _label, registry)

    assert [option["value"] for option in options] == ["listed"]


async def test_a_shared_name_carries_its_integration(hass: HomeAssistant):
    """Three registry devices called Bluetooth Proxy 2d8900 produced
    one report row nobody could act on. The integration is appended
    where a name is shared, and only there."""
    first, _ = register_device(hass, "amb1", "Shared Name")
    second, _ = register_device(hass, "amb2", "Shared Name")
    alone, _ = register_device(hass, "amb3", "Its Own Name")
    coord = await setup_coordinator(hass)

    integration = coord._watched[first.id]
    assert coord._display_names[first.id] == f"Shared Name ({integration})"
    assert coord._display_names[second.id] == f"Shared Name ({integration})"
    assert coord._display_names[alone.id] == "Its Own Name"


async def test_the_pickers_keep_the_plain_name(hass: HomeAssistant):
    """The exclusion screens print the integration in their own label,
    so a display name carrying it too would read twice."""
    device, _ = register_device(hass, "amb4", "Shared Name")
    register_device(hass, "amb5", "Shared Name")
    coord = await setup_coordinator(hass)

    row = next(
        row
        for row in coord.watched_device_rows
        if row["device_id"] == device.id
    )
    assert row["name"] == "Shared Name"


async def test_a_departing_device_with_a_pick_is_named_in_the_log(
    hass: HomeAssistant, caplog
):
    """The pick is pruned the next time its screen is saved, and by
    then only the id remains. This is the last moment the name
    exists."""
    device, _ = register_device(hass, "amb6", "Leaving Device")
    coord = await setup_coordinator(
        hass, {CONF_EXCLUDED_DEVICES: [device.id]}
    )
    assert device.id in coord.data[DATA_DEVICES]

    caplog.clear()
    coord._log_removed_exclusion(device.id)

    assert "Leaving Device" in caplog.text


async def test_a_departing_device_without_a_pick_is_silent(
    hass: HomeAssistant, caplog
):
    """Devices leave Home Assistant all the time. Only the ones
    carrying a setting that will be dropped are worth a line."""
    device, _ = register_device(hass, "amb7", "Ordinary Device")
    coord = await setup_coordinator(hass)

    caplog.clear()
    coord._log_removed_exclusion(device.id)

    assert "Ordinary Device" not in caplog.text
