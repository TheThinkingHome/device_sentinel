# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_dead_node_rounds_6.py, Version: 0.26.5 (2026-10-16)

"""The sixth adversarial round on 0.26.5 (16 October 2026).

Finding 1: a device whose only readable entity is its node status
sensor, coming back live from dead, is recorded as speaking twice: once
by _settle_down's came_back path (round five) and once more by
_on_state_changed's own `if back:` call. The second call counts an extra
event and, with the clock moving between the two calls as it does in
production, overwrites _silence_began with the first call's stamp.

Finding 2: a non-dead saved outage start on a status-only device is
never cleared (_down_now is None and the round-five path only ends a
saved "dead"), so the node's next death is dated from it and skips the
debounce, the round-four bug by another route.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DEV_DOWN_SINCE,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    FREEZE_CATEGORY_UNAVAILABLE,
)

from .helpers import registry_settled, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, walk

DAY = 86400.0


async def _lonely(hass: HomeAssistant, freezer, node: int, switch_on: bool = False):
    """A Z-Wave device whose only enabled entity is its node status."""
    source = MockConfigEntry(domain="zwave_js")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("zwave_js", f"4191921521-{node}")},
        name=f"P{node} Z-Wave Lonely",
    )
    reg = er.async_get(hass)
    switch = reg.async_get_or_create(
        "switch", "zwave_js", f"4191921521.{node}-37-0-currentValue",
        device_id=device.id, config_entry=source,
        disabled_by=None if switch_on else er.RegistryEntryDisabler.USER,
    ).entity_id
    status = reg.async_get_or_create(
        "sensor", "zwave_js", f"4191921521.{node}.node_status",
        device_id=device.id, config_entry=source, original_name="Node status",
    ).entity_id
    if switch_on:
        hass.states.async_set(switch, "on")
    hass.states.async_set(status, "alive")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=3.05 * DAY)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    return coord, device, switch, status, record



# ------------------------------------------------------------- finding 1


async def test_r6_back_from_dead_is_recorded_once(
    hass: HomeAssistant, freezer
):
    freezer.move_to(PIN)
    coord, device, _switch, status, record = await _lonely(hass, freezer, 30)

    hass.states.async_set(status, "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE

    calls: list[str | None] = []
    original = coord._record_activity

    def counting(device_id, *args, **kwargs):
        if device_id == device.id:
            calls.append(args[1] if len(args) > 1 else kwargs.get("entity_id"))
        return original(device_id, *args, **kwargs)

    coord._record_activity = counting
    before = int(record[DEV_EVENT_COUNT])
    hass.states.async_set(status, "alive")
    await hass.async_block_till_done()

    assert len(calls) == 1, (
        "the node coming back was recorded as the device speaking more than once",
        calls,
    )
    assert int(record[DEV_EVENT_COUNT]) == before + 1, (
        "one return counted as two events",
        before,
        record[DEV_EVENT_COUNT],
    )


# ------------------------------------------------------------- finding 2


async def test_r6_stale_unavailable_start_does_not_date_the_next_death(
    hass: HomeAssistant, freezer
):
    """A switch dropped briefly, then was switched off by its owner,
    leaving the status sensor alone: the saved start of the drop must
    not date the node's death hours later."""
    freezer.move_to(PIN)
    coord, device, switch, status, record = await _lonely(hass, freezer, 31, switch_on=True)

    hass.states.async_set(switch, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 60)
    assert record.get(DEV_DOWN_SINCE) is not None
    # The owner switches the value entity off while it is unavailable.
    er.async_get(hass).async_update_entity(
        switch, disabled_by=er.RegistryEntryDisabler.USER
    )
    hass.states.async_remove(switch)
    await hass.async_block_till_done()
    await registry_settled(hass)
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None

    await walk(hass, freezer, 2 * 3600)
    death = dt_util.utcnow().timestamp()
    hass.states.async_set(status, "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    assert record[DEV_FROZEN_CATEGORY] is None, (
        "the death skipped its debounce on a stale saved start",
        record.get(DEV_FROZEN_SINCE),
    )
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert record[DEV_FROZEN_SINCE] >= death - 1, (
        "the death was dated from an outage that ended hours before",
        record[DEV_FROZEN_SINCE],
        death,
    )


async def test_r6_saved_start_from_0264_does_not_date_the_next_death(
    hass: HomeAssistant, freezer
):
    """The same through the upgrade: 0.26.4 read the status sensor as a
    reading and could save [moment, "unavailable"] for a status-only
    device; 0.26.5 never clears it."""
    freezer.move_to(PIN)
    coord, device, _switch, status, record = await _lonely(hass, freezer, 32)
    record[DEV_DOWN_SINCE] = [dt_util.utcnow().timestamp() - 6 * 3600, "unavailable"]

    await walk(hass, freezer, 3600)
    death = dt_util.utcnow().timestamp()
    hass.states.async_set(status, "dead")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    assert record[DEV_FROZEN_CATEGORY] is None, "the death skipped its debounce"
    await walk(hass, freezer, 15 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert record[DEV_FROZEN_SINCE] >= death - 1, (
        record[DEV_FROZEN_SINCE],
        death,
    )
