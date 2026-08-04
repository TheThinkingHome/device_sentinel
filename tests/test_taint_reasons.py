# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_taint_reasons.py, Version: 0.11.6 (2026-08-04)

"""Why a gap went unlearned, and the record saying so (#164).

A taint suppresses learning for one completed gap. It used to be a
bare true or false, so the one line that turned it into words could
name only the commonest cause and every excluded gap read
"unavailable" whatever the device had done. This file pins the four
behaviours that replace it: the reason is the state the device was
actually in, a stored boolean is carried forward as the only reason
it could have meant, the widest cause wins when an intervention
outranks the symptom, and the promotion is resolved at the episode
rather than at the report because the storm behind a reconnect has
released long before the devices behind it come back.
"""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    DATA_EPISODES,
    DEV_TAINTED,
    EPISODE_ENDED_REBOOT,
    EPISODE_ENDED_RECONNECT,
    EPISODE_ENDED_RESUMED,
    EP_ENDED,
    EP_LEARNED,
    LEARNED_PAIRING,
    TAINT_BRIDGE_DOWN,
    TAINT_UNAVAILABLE,
    TAINT_UNKNOWN,
)
from custom_components.device_sentinel.coordinator import (
    DeviceSentinelCoordinator,
)
from custom_components.device_sentinel.journal import _promoted_learned

from .helpers import setup_coordinator


def _plain_device(hass: HomeAssistant, uid: str, name: str):
    """One device with one sensor entity, no last-contact entity."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    entry = er.async_get(hass).async_get_or_create(
        "sensor", "test", uid, device_id=device.id, config_entry=source
    )
    return device, entry.entity_id


# ------------------------------------------- the reason on the record

def _armed_and_silent(coord, device_id, seconds_silent):
    """Give a device an hourly rhythm and a silence past its basis."""
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = (
        dt_util.utcnow().timestamp() - seconds_silent
    )


async def test_taint_records_unavailable_as_its_reason(
    hass: HomeAssistant, freezer
):
    """A device that sat in unavailable is excluded under that word.

    Driven through the real state path rather than by setting the
    field, because the taint is set and spent inside one event
    handler and is never observable from outside it. The episode is
    where it becomes readable, which is the surface that matters.
    """
    device, eid = _plain_device(hass, "unavail", "Unavail")
    coord = await setup_coordinator(hass)
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 7200.0)
    coord._judge_all_devices()
    assert len(coord.data[DATA_EPISODES]) == 1

    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=7200))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    assert coord.data[DATA_EPISODES][0][EP_LEARNED] == (
        f"no ({TAINT_UNAVAILABLE})"
    )


async def test_taint_records_unknown_as_its_reason(
    hass: HomeAssistant, freezer
):
    """A device that sat in unknown does not report unavailable.

    This is the case the old boolean could never tell, because the
    state was captured and then spent on a log line.
    """
    device, eid = _plain_device(hass, "unk", "Unk")
    coord = await setup_coordinator(hass)
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 7200.0)
    coord._judge_all_devices()

    hass.states.async_set(eid, "unknown")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=7200))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    learned = coord.data[DATA_EPISODES][0][EP_LEARNED]
    assert learned == f"no ({TAINT_UNKNOWN})"
    assert learned != f"no ({TAINT_UNAVAILABLE})"


async def test_promotion_survives_a_lag_longer_than_the_storm(
    hass: HomeAssistant, freezer
):
    """The reconnect is named however late the device comes back.

    This is the whole reason the promotion is resolved at the episode.
    The storm that names a reconnect releases after five seconds; on
    the development fleet the tainted devices behind one outage
    reported with lags from zero seconds to fifty minutes, so deciding
    at the report would have caught two of fifty-six.
    """
    device, eid = _plain_device(hass, "laggy", "Laggy")
    coord = await setup_coordinator(hass)
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 7200.0)
    coord._judge_all_devices()

    # The bridge comes back and stamps the episode. The storm behind
    # it releases five seconds later; this device does not.
    coord._stamp_intervention(
        EPISODE_ENDED_RECONNECT, dt_util.utcnow().timestamp()
    )
    assert coord.data[DATA_EPISODES][0][EP_ENDED] == EPISODE_ENDED_RECONNECT

    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=7200))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    assert coord.data[DATA_EPISODES][0][EP_LEARNED] == (
        f"no ({TAINT_BRIDGE_DOWN})"
    )


# --------------------------------------------- carrying storage forward

def test_stored_boolean_becomes_unavailable():
    """A true from before this version meant unavailable and only that."""
    devices = {
        "a": {DEV_TAINTED: True},
        "b": {DEV_TAINTED: False},
        "c": {DEV_TAINTED: TAINT_BRIDGE_DOWN},
        "d": {},
    }
    converted = DeviceSentinelCoordinator._coerce_taint_reasons(devices)

    assert converted == 1
    assert devices["a"][DEV_TAINTED] == TAINT_UNAVAILABLE
    # False stays false: falsy is how every caller asks the question.
    assert devices["b"][DEV_TAINTED] is False
    # A reason already stored is not overwritten.
    assert devices["c"][DEV_TAINTED] == TAINT_BRIDGE_DOWN
    # A record without the key is left alone rather than gaining one.
    assert DEV_TAINTED not in devices["d"]


def test_carrying_forward_is_idempotent():
    """A second load converts nothing, so the log stays quiet."""
    devices = {"a": {DEV_TAINTED: True}}
    DeviceSentinelCoordinator._coerce_taint_reasons(devices)

    assert DeviceSentinelCoordinator._coerce_taint_reasons(devices) == 0


# ------------------------------------------------- the widest cause wins

def test_bridge_reconnect_outranks_the_symptom():
    """A device felled by its bridge says so, not unavailable."""
    assert (
        _promoted_learned(
            EPISODE_ENDED_RECONNECT, f"no ({TAINT_UNAVAILABLE})"
        )
        == f"no ({TAINT_BRIDGE_DOWN})"
    )
    assert (
        _promoted_learned(EPISODE_ENDED_RECONNECT, f"no ({TAINT_UNKNOWN})")
        == f"no ({TAINT_BRIDGE_DOWN})"
    )


def test_a_reboot_does_not_promote():
    """A reboot is an intervention but not a reason a gap is unlearned."""
    assert (
        _promoted_learned(EPISODE_ENDED_REBOOT, f"no ({TAINT_UNAVAILABLE})")
        == f"no ({TAINT_UNAVAILABLE})"
    )


def test_a_learned_gap_and_a_pairing_discard_pass_through():
    """Only a taint label is ever replaced."""
    assert _promoted_learned(EPISODE_ENDED_RECONNECT, "yes") == "yes"
    assert (
        _promoted_learned(EPISODE_ENDED_RECONNECT, LEARNED_PAIRING)
        == LEARNED_PAIRING
    )
    assert _promoted_learned(EPISODE_ENDED_RECONNECT, None) is None
    assert _promoted_learned(None, f"no ({TAINT_UNAVAILABLE})") == (
        f"no ({TAINT_UNAVAILABLE})"
    )
    assert (
        _promoted_learned(EPISODE_ENDED_RESUMED, f"no ({TAINT_UNAVAILABLE})")
        == f"no ({TAINT_UNAVAILABLE})"
    )
