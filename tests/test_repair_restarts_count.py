# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_repair_restarts_count.py, Version: 0.27.16 (2026-10-31)

"""A re-pair restarts the 42-Day Log-Normal Percentile; a reconfigure or
a removal does not, since neither changes how a device reports (rule
FRZ-05). The same on ZHA and on Zigbee2MQTT."""

from __future__ import annotations

import json

from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel import stack_zha
from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    DEV_LOGNORMAL_DAYS,
    DEV_LOGNORMAL_REASON,
    DEV_TODAY_MAX,
    LOGNORMAL_RESTART_REPAIR,
    STACK_Z2M,
    STACK_ZHA,
    SYS_DETAIL,
    SYS_DEVICE_HANDLED,
    SYS_KIND,
)

from custom_components.device_sentinel.stack_z2m import Z2MBridgeReader

from tests.helpers import register_device, setup_coordinator


class _PairingOpen:
    pairing_open = True

    def pairing_active_within(self, grace, now):
        return True

    def async_stop(self):
        return None


async def _zha_device(hass, key):
    device, _ = register_device(hass, key, f"ZHA {key}")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._watched[device.id] = STACK_ZHA
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_LOGNORMAL_DAYS] = 20
    observer = stack_zha.make_join_observer(hass, coord._record_device_handled)
    return device, coord, record, observer


async def test_a_zha_re_pair_restarts_the_count(hass: HomeAssistant):
    device, _coord, record, observer = await _zha_device(hass, "rp")
    ieee = "aa:bb:cc:dd:ee:ff:00:03"
    observer._pairing_until = float("inf")
    observer._on_message({"type": "device_joined", "device_info": {"ieee": ieee}})
    observer._on_message({"type": "device_fully_initialized", "device_info": {
        "ieee": ieee, "device_reg_id": device.id, "pairing_status": "INITIALIZED"}})
    assert record[DEV_LOGNORMAL_DAYS] == 0


async def test_a_zha_reconfigure_keeps_the_count(hass: HomeAssistant):
    device, _coord, record, observer = await _zha_device(hass, "rc")
    ieee = "aa:bb:cc:dd:ee:ff:00:01"
    observer._on_message({"type": "raw_device_initialized", "ieee": ieee})
    observer._on_message({"type": "device_fully_initialized", "device_info": {
        "ieee": ieee, "device_reg_id": device.id, "pairing_status": "CONFIGURED"}})
    assert record[DEV_LOGNORMAL_DAYS] == 20


async def test_a_zha_removal_keeps_the_count(hass: HomeAssistant):
    device, _coord, record, observer = await _zha_device(hass, "rm")
    observer._on_message({"type": "device_removed", "device_info": {
        "ieee": "aa:bb:cc:dd:ee:ff:00:02", "device_reg_id": device.id}})
    assert record[DEV_LOGNORMAL_DAYS] == 20


async def test_a_zigbee2mqtt_re_pair_restarts_the_count(hass: HomeAssistant, monkeypatch):
    device, _ = register_device(hass, "zp", "Z2M Plug")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [60.0] * 14
    record[DEV_TODAY_MAX] = 60.0
    record[DEV_LOGNORMAL_DAYS] = 20
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 3600.0
    monkeypatch.setattr(type(coord), "_recovered_during_pairing", lambda self, d, n: True)
    coord._record_activity(device.id, coord.entry.entry_id)
    assert record[DEV_LOGNORMAL_DAYS] == 0


async def test_a_zha_remove_and_pair_again_restarts_the_count(hass: HomeAssistant):
    device, _coord, record, observer = await _zha_device(hass, "rr")
    ieee = "aa:bb:cc:dd:ee:ff:00:0a"
    observer._pairing_until = float("inf")
    observer._on_message({"type": "device_joined", "device_info": {"ieee": ieee}})
    observer._on_message({"type": "raw_device_initialized", "ieee": ieee})
    observer._on_message({"type": "device_fully_initialized", "device_info": {
        "ieee": ieee, "device_reg_id": device.id, "pairing_status": "INITIALIZED"}})
    assert record[DEV_LOGNORMAL_DAYS] == 0


async def test_the_brief_says_re_paired(hass: HomeAssistant):
    device, coord, _record, observer = await _zha_device(hass, "rpb")
    ieee = "aa:bb:cc:dd:ee:ff:00:09"
    observer._pairing_until = float("inf")
    observer._on_message({"type": "device_joined", "device_info": {"ieee": ieee}})
    observer._on_message({"type": "device_fully_initialized", "device_info": {
        "ieee": ieee, "device_reg_id": device.id, "pairing_status": "INITIALIZED"}})
    rows = [r for r in coord.data["system_events"] if r.get(SYS_KIND) == SYS_DEVICE_HANDLED]
    assert rows[-1][SYS_DETAIL].endswith(" re-pair")
    assert coord._system_event_phrase(rows[-1]) == "re-paired by hand"


async def test_devices_reporting_while_another_is_paired_keep_their_count(hass: HomeAssistant):
    devices = [register_device(hass, f"zz{k}", f"Z2M {k}")[0] for k in ("a", "b", "c")]
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._bridge_readers[STACK_Z2M] = _PairingOpen()
    counts = []
    for device in devices:
        coord._watched[device.id] = "mqtt"
        record = coord.data[DATA_DEVICES][device.id]
        record[DEV_DAILY_MAX] = [60.0] * 40
        record[DEV_TODAY_MAX] = 60.0
        record[DEV_LOGNORMAL_DAYS] = 35
        record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 60.0
        coord._record_activity(device.id, coord.entry.entry_id)
        counts.append(record[DEV_LOGNORMAL_DAYS])
    del coord._bridge_readers[STACK_Z2M]
    assert counts == [35, 35, 35]


class _PairingClosed(_PairingOpen):
    pairing_open = False

    def pairing_active_within(self, grace, now):
        return False


async def _removed_and_back(hass, monkeypatch, reader):
    """A device removed from Home Assistant and added again with its old
    id, its coordinator's pairing open or closed as the reader says."""
    from custom_components.device_sentinel import coordinator as module
    from tests.helpers import registry_settled
    from tests.test_removed_hold import Hardware

    monkeypatch.setattr(module, "reader_for_domain", lambda readers, domain: reader)
    hw = Hardware(hass, "zr1", "Z2M Removed")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = coord.data[DATA_DEVICES][hw.device_id]
    record[DEV_DAILY_MAX] = [3600.0] * 40
    record[DEV_LOGNORMAL_DAYS] = 35
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - 2 * 86400.0
    hw.remove()
    await registry_settled(hass)
    hw.add()
    await registry_settled(hass)
    return coord, coord.data[DATA_DEVICES][hw.device_id]


async def test_a_device_removed_and_added_again_while_pairing_restarts_the_count(
    hass: HomeAssistant, monkeypatch
):
    """The usual Zigbee2MQTT re-pair: removed, then paired again. Decided on
    its return, since its first report may come after pairing closes, or
    carry a Last Seen older than its return.
    """
    _coord, record = await _removed_and_back(hass, monkeypatch, _PairingOpen())
    assert record[DEV_LOGNORMAL_DAYS] == 0


async def test_a_device_removed_and_added_again_with_pairing_closed_keeps_the_count(
    hass: HomeAssistant, monkeypatch
):
    _coord, record = await _removed_and_back(hass, monkeypatch, _PairingClosed())
    assert record[DEV_LOGNORMAL_DAYS] == 35


# On Zigbee2MQTT, only the device that joined while
# pairing was open has its count restarted, never another device that
# came back during the same window (rule FRZ-05).


def _msg(payload):
    return SimpleNamespace(payload=payload)


def _z2m(hass, key, ieee):
    """A device in the registry, to be known by a Zigbee2MQTT address."""
    device, _ = register_device(hass, key, f"Z2M {key}")
    return SimpleNamespace(id=device.id, ieee=ieee)


def _armed(coord, device, silent_for):
    """Watched on Zigbee2MQTT by its address, its record armed, last
    heard silent_for seconds ago."""
    coord._watched[device.id] = "mqtt"
    coord._stack_keys[device.id] = (STACK_Z2M, device.ieee)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_DAILY_MAX] = [600.0] * 40
    record[DEV_TODAY_MAX] = 600.0
    record[DEV_LOGNORMAL_DAYS] = 35
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp() - silent_for
    return record


def _live_reader(coord, opened_live=True):
    """A reader subscribed before the window opened (opened_live), or
    one that found the window already open when it subscribed."""
    reader = Z2MBridgeReader(coord.hass)
    reader.set_join_recorder(coord._record_repaired)
    reader._joins_live = True
    reader._on_state(_msg("online"))
    if opened_live:
        reader._on_info(_msg('{"permit_join": false}'))
    reader._on_info(_msg('{"permit_join": true, "permit_join_end": 1}'))
    coord._bridge_readers[STACK_Z2M] = reader
    return reader


def _event(kind, ieee, status=None):
    data = {"ieee_address": ieee, "friendly_name": ieee}
    if status:
        data["status"] = status
    return _msg(json.dumps({"type": kind, "data": data}))


async def test_only_the_device_that_joined_starts_its_count_again(hass: HomeAssistant):
    """Window Dining Room Left re-paired while Window Dining Room Right
    came back on its own during the same window: only the
    left one starts again, and the page can say why."""
    left = _z2m(hass, "left", "0x00000000000000a1")
    right = _z2m(hass, "right", "0x00000000000000a2")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    left_rec = _armed(coord, left, 7200.0)
    right_rec = _armed(coord, right, 7200.0)
    reader = _live_reader(coord)
    reader._on_event(_event("device_leave", "0x00000000000000a1"))
    reader._on_event(_event("device_joined", "0x00000000000000a1"))
    reader._on_event(_event("device_announce", "0x00000000000000a2"))
    coord._record_activity(left.id, coord.entry.entry_id)
    coord._record_activity(right.id, coord.entry.entry_id)
    del coord._bridge_readers[STACK_Z2M]
    assert left_rec[DEV_LOGNORMAL_DAYS] == 0
    assert left_rec[DEV_LOGNORMAL_REASON] == LOGNORMAL_RESTART_REPAIR
    assert right_rec[DEV_LOGNORMAL_DAYS] == 35
    assert right_rec[DEV_LOGNORMAL_REASON] is None


async def test_an_interview_started_while_pairing_counts_as_a_re_pair(hass: HomeAssistant):
    device = _z2m(hass, "iv", "0x00000000000000b1")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = _armed(coord, device, 60.0)
    reader = _live_reader(coord)
    reader._on_event(_event("device_interview", "0x00000000000000b1", "successful"))
    assert record[DEV_LOGNORMAL_DAYS] == 35
    reader._on_event(_event("device_interview", "0x00000000000000b1", "started"))
    del coord._bridge_readers[STACK_Z2M]
    assert record[DEV_LOGNORMAL_DAYS] == 0


async def test_a_join_or_interview_with_pairing_closed_keeps_the_count(hass: HomeAssistant):
    """An interview asked for by hand from Zigbee2MQTT, with no window
    open, changes nothing about how the device reports."""
    device = _z2m(hass, "cl", "0x00000000000000c1")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = _armed(coord, device, 60.0)
    reader = Z2MBridgeReader(hass)
    reader.set_join_recorder(coord._record_repaired)
    reader._joins_live = True
    reader._on_state(_msg("online"))
    reader._on_info(_msg('{"permit_join": false}'))
    reader._on_event(_event("device_interview", "0x00000000000000c1", "started"))
    reader._on_event(_event("device_joined", "0x00000000000000c1"))
    assert record[DEV_LOGNORMAL_DAYS] == 35


async def test_a_window_open_before_the_start_falls_back_to_the_silence(hass: HomeAssistant):
    """bridge/event is not retained, so a window already open when Device
    Sentinel subscribed has joins it never heard: a device silent past
    its window that comes back during it is taken as re-paired, as
    before."""
    device = _z2m(hass, "fb", "0x00000000000000d1")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = _armed(coord, device, 7200.0)
    reader = _live_reader(coord, opened_live=False)
    assert reader.joins_seen() is False
    coord._record_activity(device.id, coord.entry.entry_id)
    del coord._bridge_readers[STACK_Z2M]
    assert record[DEV_LOGNORMAL_DAYS] == 0


async def test_a_join_for_a_device_home_assistant_does_not_know_is_ignored(hass: HomeAssistant):
    """A new device has no count to restart, and a malformed event
    breaks nothing."""
    device = _z2m(hass, "nw", "0x00000000000000e1")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = _armed(coord, device, 60.0)
    reader = _live_reader(coord)
    reader._on_event(_event("device_joined", "0x00000000000000ff"))
    reader._on_event(_msg("not json"))
    reader._on_event(_msg('{"type": "device_joined", "data": "x"}'))
    reader._on_event(_msg('{"type": "device_joined", "data": {"ieee_address": 7}}'))
    del coord._bridge_readers[STACK_Z2M]
    assert record[DEV_LOGNORMAL_DAYS] == 35


async def test_a_window_replayed_after_a_broker_reconnect_falls_back_to_the_silence(
    hass: HomeAssistant,
):
    """Home Assistant's MQTT client re-subscribes after losing the broker,
    and the bridge's state comes back retained. A window that opened
    while it was cut off had joins nobody heard, so it is judged by the
    silence, as before."""
    device = _z2m(hass, "rc", "0x00000000000000f1")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = _armed(coord, device, 7200.0)
    reader = Z2MBridgeReader(hass)
    reader.set_join_recorder(coord._record_repaired)
    reader._joins_live = True
    reader._on_state(_msg("online"))
    reader._on_info(_msg('{"permit_join": false}'))
    replay = SimpleNamespace(payload='{"permit_join": true, "permit_join_end": 1}', retain=True)
    reader._on_info(replay)
    assert reader.joins_seen() is False
    coord._bridge_readers[STACK_Z2M] = reader
    coord._record_activity(device.id, coord.entry.entry_id)
    del coord._bridge_readers[STACK_Z2M]
    assert record[DEV_LOGNORMAL_DAYS] == 0


async def test_a_device_set_aside_for_a_moment_while_it_rejoins_still_restarts(
    hass: HomeAssistant,
):
    """A re-pair by its button sends device_leave first, and its entities
    can be gone for a moment when the join arrives. It is still the
    device that was re-paired."""
    device = _z2m(hass, "sa", "0x00000000000000f2")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = _armed(coord, device, 60.0)
    coord._watched.pop(device.id, None)
    reader = _live_reader(coord)
    reader._on_event(_event("device_joined", "0x00000000000000f2"))
    del coord._bridge_readers[STACK_Z2M]
    assert record[DEV_LOGNORMAL_DAYS] == 0
    assert record[DEV_LOGNORMAL_REASON] == LOGNORMAL_RESTART_REPAIR


async def test_a_window_open_across_a_broker_reconnect_falls_back_to_the_silence(
    hass: HomeAssistant,
):
    """A window heard opening live, then the client loses the broker and
    reconnects while it is still open: joins in between were never
    heard, so the window is judged by the silence again."""
    device = _z2m(hass, "ra", "0x00000000000000f3")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    record = _armed(coord, device, 7200.0)
    reader = _live_reader(coord)
    assert reader.joins_seen() is True
    reader._on_info(SimpleNamespace(payload='{"permit_join": true, "permit_join_end": 1}', retain=True))
    assert reader.joins_seen() is False
    coord._record_activity(device.id, coord.entry.entry_id)
    del coord._bridge_readers[STACK_Z2M]
    assert record[DEV_LOGNORMAL_DAYS] == 0
