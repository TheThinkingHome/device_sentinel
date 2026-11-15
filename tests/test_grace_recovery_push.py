# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_grace_recovery_push.py, Version: 0.29.0 (2026-11-14)

"""A recovery inside the startup grace still reaches the phone afterwards.

NOTE-03: each family's push replaces its last message on the phone, and
"a recovery sends its family's push again, so a summary never claims a
problem that has cleared". Inside the startup grace nothing is pushed,
and the recovery of a device that reports in the grace is dropped, not
held: only its bus event is held (WATCH-10). The phone keeps the last
Device push, "... stopped reporting. Summary: <device> frozen", until
some other device in the family next changes, which may be days.

The common way in: a device froze, the phone was told, and the person
restarted Home Assistant to fix it. The device reports in the first
minutes and is fine, but the phone still says it is frozen.

Asserts the correct behaviour: after the grace closes, a push in the
device's family is sent that no longer claims the problem.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    DATA_DEVICES,
    DATA_TODO_ITEMS,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    STARTUP_GRACE_SECONDS,
)

from tests.helpers import setup_entry


def _device(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("test", uid)}, name=name
    )
    ent = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0", device_id=device.id, config_entry=source
    )
    return device, ent.entity_id


async def test_a_recovery_inside_the_grace_corrects_the_phone(
    hass: HomeAssistant, freezer
):
    device, eid = _device(hass, "gr1", "Fixed By Restart")
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]})
    coord = entry.runtime_data
    coord._grace_until = 0.0
    calls: list[dict] = []

    async def handler(call):
        calls.append(dict(call.data))

    hass.services.async_register("notify", "phone", handler)
    hass.states.async_set(eid, "21.5")
    await hass.async_block_till_done()

    # A learned hourly device, silent three hours: frozen, and pushed
    # once its 18-minute hold is over (NOTE-06).
    gap = 3600.0
    now = dt_util.utcnow().timestamp()
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [gap] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = now - 3 * gap
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = now - gap
    coord._sync_problem_list()
    await hass.async_block_till_done()
    for _ in range(20):
        freezer.tick(timedelta(minutes=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    told = [c for c in calls if "Fixed By Restart" in str(c.get("message"))]
    assert told, "precondition: the fault reached the phone"
    if not any(
        item.get("device_id") == device.id for item in coord.data[DATA_TODO_ITEMS]
    ):
        raise AssertionError("precondition: the device is listed")
    before = len(calls)

    # The person restarts; the device reports a minute into the grace.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    freezer.tick(timedelta(seconds=60))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    hass.states.async_set(eid, "22.0")
    await hass.async_block_till_done()
    # Past the grace and any parking minute.
    for _ in range(int(STARTUP_GRACE_SECONDS // 60) + 5):
        freezer.tick(timedelta(minutes=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    assert not any(
        item.get("device_id") == device.id for item in coord.data[DATA_TODO_ITEMS]
    ), "precondition: the device left the list"
    after = calls[before:]
    assert after, (
        "no push after the grace: the phone's last Device message still "
        "says the device is frozen"
    )
    assert "Fixed By Restart frozen" not in str(after[-1].get("message"))
