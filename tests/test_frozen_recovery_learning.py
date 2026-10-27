# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_frozen_recovery_learning.py, Version: 0.27.10 (2026-10-27)

"""What a frozen device's recovery teaches (rules FRZ-12, FRZ-19).

A gap that ends while a device stands frozen is learned whole when the
device ended the silence itself: the two freeze rules already set a
long day aside, so one outage cannot stretch the wait in use, and a
slow reporter learns the quiet spells it really has. A report that
follows a command to one of the device's own entities within
COMMANDED_RECOVERY_SECONDS is a commanded recovery: the verdict clears,
because the device answered, and the gap is discarded as a pairing
gap is, because a toggle says nothing about the device's rhythm. The
command is read from Home Assistant's own `call_service` event, so an
automation's command counts the same as a hand. A command on an
ordinary day, with no freeze standing, changes nothing; a taint still
outranks everything.
"""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.device_sentinel.const import (
    COMMANDED_RECOVERY_SECONDS,
    DATA_DEVICES,
    DATA_EPISODES,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    EP_LEARNED,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    LEARNED_COMMANDED,
    STARTUP_GRACE_SECONDS,
    TAINT_UNAVAILABLE,
)

from .helpers import register_device, setup_coordinator


def _armed(coord, device_id, rhythm):
    """Give a device a learned rhythm and a fresh clock."""
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_DAILY_MAX] = [rhythm] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()
    record[DEV_TODAY_MAX] = None
    return record


async def _recover_after(hass, coord, eid, record, silence, frozen=True):
    """Complete a gap of the given silence, frozen or not."""
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - silence
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN if frozen else None
    hass.states.async_set(eid, str(dt_util.utcnow().timestamp()))
    await hass.async_block_till_done()
    return record


def _command(hass, eid):
    """A service call naming the entity, as a device card or an automation makes."""
    hass.bus.async_fire(
        "call_service",
        {"domain": "switch", "service": "toggle", "service_data": {"entity_id": eid}},
    )


def _last_episode(coord, device_id):
    rows = [row for row in coord.data.get(DATA_EPISODES, []) if row.get("device_id") == device_id]
    return rows[-1] if rows else None


async def test_a_frozen_devices_own_recovery_is_learned_whole(hass: HomeAssistant, freezer):
    """A pulled battery's 74 minutes on a 10-minute device: the whole gap
    teaches the device, because nothing says a hand ended it (rule FRZ-12)."""
    device, eid = register_device(hass, "whole1", "Slow Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 615.0)

    await _recover_after(hass, coord, eid[0], record, 4446.0, frozen=True)

    assert record[DEV_TODAY_MAX] == 4446.0
    assert record[DEV_FROZEN_CATEGORY] is None, "the verdict clears when it speaks"
    episode = _last_episode(coord, device.id)
    assert episode is None or not str(episode[EP_LEARNED]).startswith("capped")
    assert not hasattr(coord, "_resurrection_cap"), "the cap is gone, not idle"


async def test_a_recovery_after_a_command_clears_and_teaches_nothing(hass: HomeAssistant, freezer):
    """Toggling a frozen device from its card clears the alarm and teaches
    nothing (rule FRZ-19). Driven through the real handlers, with the
    render tick opening the silence episode as the live system does, so
    the LEARNED cell is read as written."""
    freezer.move_to("2026-10-11 15:00:00+00:00")
    device, eid = register_device(hass, "cmd1", "Coop Light")
    coord = await setup_coordinator(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    _armed(coord, device.id, 3600.0)
    record = coord.data[DATA_DEVICES][device.id]
    hass.states.async_set(eid[0], "off")
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=12))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN, "the sweep judged it frozen"

    _command(hass, eid[0])
    await hass.async_block_till_done()
    assert device.id in coord._commanded_at
    freezer.tick(timedelta(seconds=2))
    hass.states.async_set(eid[0], "on")
    await hass.async_block_till_done()

    assert record[DEV_FROZEN_CATEGORY] is None, "the device answered, so it is reachable"
    assert record[DEV_TODAY_MAX] in (None, 0.0), "and its silence taught nothing"
    assert device.id not in coord._commanded_at, "the command is spent"
    episode = _last_episode(coord, device.id)
    assert episode is not None and episode[EP_LEARNED] == LEARNED_COMMANDED


async def test_a_command_outside_the_window_is_not_the_reply(hass: HomeAssistant, freezer):
    """A command long before the report is a different act; the report
    is the device's own and its gap is learned."""
    device, eid = register_device(hass, "cmd2", "Late Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 3600.0)
    _command(hass, eid[0])
    await hass.async_block_till_done()
    freezer.tick(COMMANDED_RECOVERY_SECONDS + 5)

    await _recover_after(hass, coord, eid[0], record, 12 * 3600.0, frozen=True)

    assert record[DEV_TODAY_MAX] == 12 * 3600.0


async def test_a_command_on_an_ordinary_day_changes_nothing(hass: HomeAssistant, freezer):
    """No freeze standing: a commanded report is a report like any other,
    and the command is not spent on it."""
    device, eid = register_device(hass, "cmd3", "Daytime Switch")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 3600.0)
    _command(hass, eid[0])
    await hass.async_block_till_done()

    await _recover_after(hass, coord, eid[0], record, 1800.0, frozen=False)

    assert record[DEV_TODAY_MAX] == 1800.0
    assert device.id in coord._commanded_at, "kept for a report that does clear a freeze"


async def test_a_command_to_another_device_is_not_this_ones(hass: HomeAssistant, freezer):
    device, eid = register_device(hass, "cmd4", "Quiet Device")
    other, other_eid = register_device(hass, "cmd5", "Busy Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 3600.0)
    _command(hass, other_eid[0])
    await hass.async_block_till_done()

    await _recover_after(hass, coord, eid[0], record, 12 * 3600.0, frozen=True)

    assert record[DEV_TODAY_MAX] == 12 * 3600.0
    assert other.id in coord._commanded_at and device.id not in coord._commanded_at


async def test_a_command_naming_a_list_of_entities_is_read(hass: HomeAssistant, freezer):
    """Home Assistant passes several targets as a list; a target that is
    not a string, or not watched, is ignored rather than failing the handler."""
    device, eid = register_device(hass, "cmd6", "Listed Device")
    coord = await setup_coordinator(hass)
    hass.bus.async_fire(
        "call_service",
        {"domain": "light", "service": "turn_on",
         "service_data": {"entity_id": ["light.nobody", 7, eid[0]]}},
    )
    hass.bus.async_fire("call_service", {"domain": "light", "service": "turn_on", "service_data": {"entity_id": 7}})
    hass.bus.async_fire("call_service", {"domain": "light", "service": "turn_on", "service_data": "nonsense"})
    hass.bus.async_fire("call_service", {"domain": "light", "service": "turn_on"})
    await hass.async_block_till_done()
    assert device.id in coord._commanded_at


async def test_taint_outranks_a_commanded_recovery(hass: HomeAssistant, freezer):
    """An attributed outage is discarded as a taint, whatever followed it."""
    device, eid = register_device(hass, "cmd7", "Tainted Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 3600.0)
    record[DEV_TAINTED] = TAINT_UNAVAILABLE
    _command(hass, eid[0])
    await hass.async_block_till_done()

    await _recover_after(hass, coord, eid[0], record, 12 * 3600.0, frozen=True)

    assert record[DEV_TODAY_MAX] is None
    assert record[DEV_TAINTED] is False
    episode = _last_episode(coord, device.id)
    assert episode is None or episode[EP_LEARNED] != LEARNED_COMMANDED


async def test_unconvicted_life_is_untouched(hass: HomeAssistant, freezer):
    """A device that was never frozen learns its gap as it always did."""
    device, eid = register_device(hass, "cmd8", "Ordinary Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 615.0)
    await _recover_after(hass, coord, eid[0], record, 1200.0, frozen=False)
    assert record[DEV_TODAY_MAX] == 1200.0


async def test_a_clock_set_back_does_not_stretch_the_window(hass: HomeAssistant, freezer):
    """A command stamped before the system clock was set back two hours is
    no reply to a report an hour later on the new clock (rule FRZ-21)."""
    freezer.move_to("2026-10-11 15:00:00+00:00")
    device, eid = register_device(hass, "cmd9", "Clock Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 3600.0)
    _command(hass, eid[0])
    await hass.async_block_till_done()
    freezer.move_to("2026-10-11 14:00:00+00:00")
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    assert coord._recovered_after_command(device.id, record, dt_util.utcnow().timestamp()) is False


async def test_a_command_in_any_shape_home_assistant_accepts_is_read(hass: HomeAssistant):
    """Home Assistant accepts one string of comma-separated ids and any
    letter case; the event carries the call as written (rule FRZ-19)."""
    device, eid = register_device(hass, "cmd10", "Comma Device")
    other, other_eid = register_device(hass, "cmd11", "Case Device")
    coord = await setup_coordinator(hass)
    _command(hass, f"switch.somebody_else, {eid[0]}")
    _command(hass, other_eid[0].upper())
    await hass.async_block_till_done()
    assert device.id in coord._commanded_at and other.id in coord._commanded_at


async def test_a_clock_step_moves_the_command_with_it(hass: HomeAssistant, freezer):
    """A reply three real seconds after a command is its reply, whatever
    the clock did between: the command moves with the other moments
    (rule FRZ-21)."""
    freezer.move_to("2026-10-11 15:00:00+00:00")
    device, eid = register_device(hass, "cmd12", "Step Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 3600.0)
    _command(hass, eid[0])
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=2, seconds=3))
    coord._shift_moments(7200.0)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    assert coord._recovered_after_command(device.id, record, dt_util.utcnow().timestamp()) is True


async def test_a_discarded_gap_gives_the_day_back_its_earlier_longest(hass: HomeAssistant, freezer):
    """A 90-minute quiet spell this morning, then a 12-hour freeze ended
    by a toggle: the toggle's gap is discarded and today's longest goes
    back to the 90 minutes, rather than to nothing (rule FRZ-15)."""
    freezer.move_to("2026-10-11 15:00:00+00:00")
    device, eid = register_device(hass, "cmd13", "Morning Device")
    coord = await setup_coordinator(hass)
    record = _armed(coord, device.id, 3600.0)
    record[DEV_TODAY_MAX] = 5400.0
    _command(hass, eid[0])
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=2))
    await _recover_after(hass, coord, eid[0], record, 12 * 3600.0, frozen=True)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_TODAY_MAX] == 5400.0


def test_the_undo_leaves_a_larger_gap_alone():
    """Only the gap just learned is pulled back; a longer one from
    earlier in the day was never replaced, so it stays (rule FRZ-15)."""
    from custom_components.device_sentinel.detect_freeze import FreezeMixin

    record = {DEV_TODAY_MAX: 9000.0}
    FreezeMixin._retract_today_max(record, 1200.0, 9000.0)
    assert record[DEV_TODAY_MAX] == 9000.0
    record = {DEV_TODAY_MAX: 1200.0}
    FreezeMixin._retract_today_max(record, 1200.0, None)
    assert record[DEV_TODAY_MAX] is None
