# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_dead_node_rounds_7.py, Version: 0.26.5 (2026-10-16)

"""Seventh adversarial round on 0.26.5 (16 October 2026).

Finding 1: _status_only reads every entity in _own_entities from the
entity registry and treats one the registry no longer knows as switched
off. A value entity renamed while its device is unavailable is missing
from the registry under its old id until the debounced rebuild runs (up
to REGISTRY_REBUILD_COOLDOWN_SECONDS), and its old state is gone, so
_down_now reads None and _status_only reads True. Round six's new
branch in _settle_down then ends the saved non-dead outage start (and
may taint), though the device is still unavailable under its new id.
After the rebuild the outage starts again at a later moment. Before
round six a None reading ended nothing, which is what the docstring of
_settle_down promises ("a rename or a removal cannot" lose the start).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.const import DEV_DOWN_SINCE, DEV_TAINTED

from .outage_helpers import PIN, walk
from .test_dead_node_rounds_6 import _lonely


async def test_a7_rename_inside_rebuild_cooldown_keeps_outage_start(
    hass: HomeAssistant, freezer, monkeypatch
):
    freezer.move_to(PIN)
    coord, device, switch, status, record = await _lonely(
        hass, freezer, 70, switch_on=True
    )

    hass.states.async_set(switch, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    saved = record.get(DEV_DOWN_SINCE)
    assert saved is not None and saved[1] != "dead"
    tainted_before = record.get(DEV_TAINTED)

    # A rebuild ran inside the last cooldown, so this one waits.
    monkeypatch.setattr(
        coord._registry_debouncer, "async_schedule_call", lambda: None
    )
    new_id = "switch.p70_renamed"
    er.async_get(hass).async_update_entity(switch, new_entity_id=new_id)
    hass.states.async_remove(switch)
    hass.states.async_set(new_id, "unavailable")
    await hass.async_block_till_done()

    # The minute sweep, or any status sensor write, inside the window.
    coord._settle_down(device.id, None)

    assert record.get(DEV_DOWN_SINCE) == saved, (
        "a rename inside the rebuild cooldown ended an outage the device "
        "is still in",
        record.get(DEV_DOWN_SINCE),
        saved,
    )
    assert record.get(DEV_TAINTED) == tainted_before

    # The rebuild catches up: the start is still the original one.
    monkeypatch.undo()
    coord._rebuild_and_notify()
    coord._settle_down(device.id, None)
    assert record.get(DEV_DOWN_SINCE) == saved
