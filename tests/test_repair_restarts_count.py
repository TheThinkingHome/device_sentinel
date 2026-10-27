# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_repair_restarts_count.py, Version: 0.27.9 (2026-10-27)

"""A re-pair restarts the 42-Day Log-Normal Percentile; a reconfigure or
a removal does not, since neither changes how a device reports (rule
FRZ-05). The same on ZHA and on Zigbee2MQTT."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel import stack_zha
from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    DEV_LOGNORMAL_DAYS,
    DEV_TODAY_MAX,
    STACK_Z2M,
    STACK_ZHA,
    SYS_DETAIL,
    SYS_DEVICE_HANDLED,
    SYS_KIND,
)

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
    """The usual Zigbee2MQTT re-pair: removed, then paired again. Decided
    on its return, since its first report may come after pairing closes,
    or carry a Last Seen older than its return (0.27.9 rounds 2 and 3)."""
    _coord, record = await _removed_and_back(hass, monkeypatch, _PairingOpen())
    assert record[DEV_LOGNORMAL_DAYS] == 0


async def test_a_device_removed_and_added_again_with_pairing_closed_keeps_the_count(
    hass: HomeAssistant, monkeypatch
):
    _coord, record = await _removed_and_back(hass, monkeypatch, _PairingClosed())
    assert record[DEV_LOGNORMAL_DAYS] == 35
