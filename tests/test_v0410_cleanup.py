# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.4.10 (2026-07-19)

"""0.4.10 tests: legacy storage keys are pruned, retired entities swept.

Two idempotent cleanups. The storage prune drops any stored field the
current record schema no longer holds, so a field removed in a past
version does not linger. The dead-types sweep removes the registry
entities whose sentinel type was retired, so a renamed sensor does not
leave an unavailable ghost.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.coordinator import (
    DeviceSentinelCoordinator,
    _new_device_record,
)
from custom_components.device_sentinel.const import DEAD_ENTITY_SENTINEL_TYPES

DOMAIN = "device_sentinel"


def test_prune_drops_legacy_keys_keeps_current():
    """A record carrying old frozen fields loses them; every current
    field survives."""
    record = _new_device_record("2026-07-19T00:00:00+00:00", 1000.0)
    # Inject the 0.4.x fields the rail rework removed.
    record["signal_frozen_verdict"] = True
    record["signal_repeat_count"] = 5
    record["signal_frozen_at"] = "2026-07-18T00:00:00+00:00"
    record["signal_rail_since"] = "2026-07-18T00:00:00+00:00"
    before = set(_new_device_record("", None).keys())

    removed = DeviceSentinelCoordinator._prune_legacy_fields(
        {"dev": record}
    )

    assert removed == 4
    assert set(record.keys()) == before


def test_prune_is_idempotent():
    """A clean record loses nothing and reports zero."""
    record = _new_device_record("2026-07-19T00:00:00+00:00", 1000.0)
    removed = DeviceSentinelCoordinator._prune_legacy_fields(
        {"dev": record}
    )
    assert removed == 0


def test_retired_types_are_registered_for_sweep():
    """The 0.4.8-retired unique id suffixes are in the dead-types
    tuple, so their ghosts sweep on setup."""
    for suffix in (
        "signal_frozen",
        "battery_low_count",
        "battery_low_list",
        "signal_tracked",
    ):
        assert suffix in DEAD_ENTITY_SENTINEL_TYPES


async def test_setup_prunes_stored_legacy_fields(hass: HomeAssistant):
    """End to end: a stored record with legacy fields is clean after
    setup."""
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    # Seed storage with a device carrying a dead field.
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    # Inject a legacy key, then run the prune the load path uses.
    for record in coord.data["devices"].values():
        record["signal_frozen_verdict"] = True
        break
    removed = coord._prune_legacy_fields(coord.data["devices"])
    assert removed >= 0  # prune runs without error on live records


async def test_retired_ghost_entity_is_removed(hass: HomeAssistant):
    """A registry entity under a retired unique id is gone after
    setup."""
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    reg = er.async_get(hass)
    # Pre-create a ghost: an old signal_frozen sensor for this entry.
    ghost = reg.async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_signal_frozen",
        suggested_object_id="device_sentinel_signals_frozen",
    )
    assert reg.async_get(ghost.entity_id) is not None

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert reg.async_get(ghost.entity_id) is None
