# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v095_pairing_fullpath.py, Version: 0.9.5 (2026-07-25)

"""0.9.5 full-path test: a real gap through the coordinator, judged.

The helper tests prove the pieces; this proves the join. A device
goes silent, reads unavailable, and then recovers while its Z2M bridge
is in binding. The whole recovery runs through the real state-change
handlers, so the pairing override is what decides the outcome, exactly
as it will on the live system. This is the software half of the proof
James reasoned out: both hardware halves (the bridge entering binding,
the device coming back) are already confirmed on the fleet, so proving
the code that joins them here means the whole path is trustworthy even
though the live coincidence is hard to stage.

The contrast test matters as much: the same silence and recovery with
the bridge NOT in binding is learned normally, so the override changes
only the pairing case and nothing else.
"""

from datetime import timedelta
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.bridge import Z2MBridgeReader
from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_EPISODES,
    DEV_DAILY_MAX,
    EP_LEARNED,
    FREEZE_ARMING_DAYS,
    STACK_Z2M,
    STARTUP_GRACE_SECONDS,
)

DOMAIN = "device_sentinel"
_PIN = "2026-07-24T01:00:00+00:00"


def _register_mqtt(hass, uid, name):
    """Register a device on the mqtt integration, which is the domain a
    Z2M device carries and the pairing check keys on."""
    source = MockConfigEntry(domain="mqtt")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("mqtt", uid)},
        name=name,
    )
    entity = er.async_get(hass).async_get_or_create(
        "sensor", "mqtt", f"{uid}_0", device_id=device.id, config_entry=source
    )
    return device, entity.entity_id


async def _coordinator(hass, freezer):
    freezer.move_to(_PIN)
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    return coord


def _arm(coord, device_id, basis_hours):
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_DAILY_MAX] = [basis_hours * 3600.0] * (FREEZE_ARMING_DAYS + 2)


def _binding_reader(hass):
    """A bridge reader already in binding, as it would be with a pairing
    window open on the live system."""
    r = Z2MBridgeReader(hass)
    r._on_state(SimpleNamespace(payload="online"))
    r._on_info(
        SimpleNamespace(
            payload='{"permit_join": true, "permit_join_end": 1}'
        )
    )
    return r


def _running_reader(hass):
    """A bridge reader running, no pairing open."""
    r = Z2MBridgeReader(hass)
    r._on_state(SimpleNamespace(payload="online"))
    r._on_info(SimpleNamespace(payload='{"permit_join": false}'))
    return r


async def _silence_and_recover(hass, freezer, eid, silent_hours):
    """Report, go quiet past basis, read unavailable, then recover on a
    real value, all through the real handlers. A render tick is fired
    during the silence so the episode-open scan runs, which is what the
    live system does on its 60-second tick."""
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=silent_hours * 3600.0))
    # The tick that opens the silence episode, as on the live system.
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=30))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()


def _last_episode(coord, device_id):
    for ep in reversed(coord.data.get(DATA_EPISODES) or []):
        if ep.get("device_id") == device_id:
            return ep
    return None


async def test_recovery_during_binding_is_discarded_as_pairing(
    hass: HomeAssistant, freezer
):
    """The full path. An mqtt device recovers while its bridge is in
    binding, and its completed gap is set aside as a pairing
    intervention, marked no (pairing), not learned."""
    device, eid = _register_mqtt(hass, "pair1", "Switch Under Test")
    coord = await _coordinator(hass, freezer)
    coord._bridge_readers[STACK_Z2M] = _binding_reader(hass)
    _arm(coord, device.id, basis_hours=1.0)

    await _silence_and_recover(hass, freezer, eid, silent_hours=3.0)

    ep = _last_episode(coord, device.id)
    assert ep is not None
    assert ep[EP_LEARNED] == "no (pairing)"


async def test_same_recovery_without_binding_is_learned(
    hass: HomeAssistant, freezer
):
    """The contrast. The identical silence and recovery with the bridge
    merely running is learned normally, so the override touches only the
    pairing case."""
    device, eid = _register_mqtt(hass, "pair2", "Switch Not Pairing")
    coord = await _coordinator(hass, freezer)
    coord._bridge_readers[STACK_Z2M] = _running_reader(hass)
    _arm(coord, device.id, basis_hours=1.0)

    await _silence_and_recover(hass, freezer, eid, silent_hours=3.0)

    ep = _last_episode(coord, device.id)
    assert ep is not None
    # A 3h self-recovery on a 1h basis, brief unavailable: learned.
    assert ep[EP_LEARNED] == "yes"


async def test_pairing_gap_does_not_widen_the_rhythm(
    hass: HomeAssistant, freezer
):
    """A discarded pairing gap must not become the learned maximum. The
    device's rhythm after a pairing-discarded 3h gap is still its armed
    1h basis, not 3h."""
    device, eid = _register_mqtt(hass, "pair3", "Switch Rhythm Guard")
    coord = await _coordinator(hass, freezer)
    coord._bridge_readers[STACK_Z2M] = _binding_reader(hass)
    _arm(coord, device.id, basis_hours=1.0)

    await _silence_and_recover(hass, freezer, eid, silent_hours=3.0)

    record = coord.data[DATA_DEVICES][device.id]
    today = record.get("today_max")
    # The 3h (10800s) pairing gap was retracted, so today_max is not it.
    assert today is None or today < 3.0 * 3600.0
