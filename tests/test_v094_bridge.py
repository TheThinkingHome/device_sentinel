# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v094_bridge.py, Version: 0.9.4 (2026-07-25)

"""0.9.4 tests: the Z2M bridge reader and the per-stack bridge sensor.

The reader turns two retained MQTT topics into one readable state:
running, binding, down, or unknown. These tests drive its callbacks
with synthetic payloads, no broker needed, and prove the state machine
sorts every case, including the ones that must fail safe: a payload
that will not parse, an open pairing flag on a bridge not known to be
online, and nothing heard at all. The sensor tests prove it is one per
stack and disabled by default, so a house sees the bridge sensors only
when it enables the one it wants.
"""

from types import SimpleNamespace

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.bridge import Z2MBridgeReader
from custom_components.device_sentinel.const import (
    BRIDGE_BINDING,
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BRIDGE_UNKNOWN,
)


def _msg(payload):
    """A stand-in for an MQTT ReceiveMessage carrying a payload."""
    return SimpleNamespace(payload=payload)


def _reader(hass):
    return Z2MBridgeReader(hass)


async def test_nothing_heard_reads_unknown(hass: HomeAssistant):
    """Before any message, the bridge state is unknown, not down: we
    genuinely do not know yet, and unknown is the honest word."""
    r = _reader(hass)
    assert r.state == BRIDGE_UNKNOWN
    assert r.pairing_open is False


async def test_online_and_closed_reads_running(hass: HomeAssistant):
    r = _reader(hass)
    r._on_state(_msg("online"))
    r._on_info(_msg('{"permit_join": false}'))
    assert r.state == BRIDGE_RUNNING
    assert r.pairing_open is False


async def test_online_and_pairing_reads_binding(hass: HomeAssistant):
    """The case the whole feature exists to see: online with a pairing
    window open reads binding, and the window end is surfaced."""
    r = _reader(hass)
    r._on_state(_msg("online"))
    r._on_info(
        _msg('{"permit_join": true, "permit_join_end": 1784800000}')
    )
    assert r.state == BRIDGE_BINDING
    assert r.pairing_open is True
    assert r.permit_join_end == "1784800000"


async def test_offline_reads_down(hass: HomeAssistant):
    r = _reader(hass)
    r._on_state(_msg("offline"))
    assert r.state == BRIDGE_DOWN
    assert r.pairing_open is False


async def test_pairing_open_but_not_online_is_not_binding(
    hass: HomeAssistant,
):
    """A guard that matters. If info says permit_join but the bridge
    has never confirmed it is online, the state is down, not binding:
    pairing is only meaningful on a bridge we know is up, so a stale
    info payload cannot fake a binding window."""
    r = _reader(hass)
    r._on_info(_msg('{"permit_join": true}'))
    assert r.state == BRIDGE_DOWN
    assert r.pairing_open is False


async def test_permit_join_end_absent_outside_binding(hass: HomeAssistant):
    """The window end is reported only while binding, so a reader that
    is running never leaks a stale end time."""
    r = _reader(hass)
    r._on_state(_msg("online"))
    r._on_info(_msg('{"permit_join": false}'))
    assert r.permit_join_end is None


async def test_malformed_info_does_not_raise_or_flip(hass: HomeAssistant):
    """A payload that will not parse leaves the prior state untouched
    rather than raising or dropping to a wrong state. This is the
    fail-safe the detector rests on."""
    r = _reader(hass)
    r._on_state(_msg("online"))
    r._on_info(_msg('{"permit_join": true, "permit_join_end": 1784800000}'))
    assert r.state == BRIDGE_BINDING
    # garbage arrives; state must not change
    r._on_info(_msg("not json at all {["))
    assert r.state == BRIDGE_BINDING


async def test_state_as_json_object_is_read(hass: HomeAssistant):
    """bridge/state is sometimes a bare string, sometimes a JSON object
    with a state field. Both must read as online."""
    r = _reader(hass)
    r._on_state(_msg('{"state": "online"}'))
    r._on_info(_msg('{"permit_join": false}'))
    assert r.state == BRIDGE_RUNNING


async def test_bytes_payload_is_decoded(hass: HomeAssistant):
    """MQTT payloads can be bytes; the reader decodes them."""
    r = _reader(hass)
    r._on_state(_msg(b"online"))
    r._on_info(_msg(b'{"permit_join": true, "permit_join_end": 1}'))
    assert r.state == BRIDGE_BINDING


async def test_bridge_sensor_is_created_per_stack_and_disabled(
    hass: HomeAssistant,
):
    """A house with a Z2M bridge gets one bridge sensor, and it is
    disabled by default so it stays off until the user enables it."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    # A Z2M bridge device so stack detection reports z2m.
    src = MockConfigEntry(domain="mqtt")
    src.add_to_hass(hass)
    bridge = dr.async_get(hass).async_get_or_create(
        config_entry_id=src.entry_id,
        identifiers={("mqtt", "z2m_bridge")},
        name="SLZB-06M Zigbee2MQTT Bridge",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "mqtt", "z2m_bridge_0", device_id=bridge.id, config_entry=src
    )

    entry = MockConfigEntry(domain="device_sentinel", title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    reg = er.async_get(hass)
    bridge_entities = [
        e for e in reg.entities.values()
        if e.platform == "device_sentinel" and "bridge" in (e.unique_id or "")
    ]
    assert len(bridge_entities) == 1
    assert bridge_entities[0].disabled_by is not None  # disabled by default
    assert "z2m" in bridge_entities[0].unique_id
