# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_bridge_pairing.py, Version: 0.10.10 (2026-07-30)

"""Coordinator stacks, the Z2M bridge, and the pairing override.

Which coordinator stacks a house runs is read from the registry, not
asked: ZHA, Z-Wave, and Matter by their domain, Z2M only by the presence
of its bridge device, never by the shared mqtt domain. The Z2M bridge
reader turns two retained MQTT topics into one state (running, binding,
down, or unknown), failing safe on a payload that will not parse or a
pairing flag from a bridge not known to be online. A recovery that lands
while the bridge is in binding is a pairing intervention, not a real
self-recovery, so its gap is set aside rather than learned, and it must
not widen the rhythm. Alongside pairing, the per-device taint debounce
(a floor plus a share of the freeze window) decides whether an
unavailable blip inside a silence is a hiccup to learn or downtime to
discard. This file holds the stack detection, the bridge reader, the
taint debounce, and the full-path pairing override.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_sentinel.bridge import Z2MBridgeReader
from custom_components.device_sentinel.const import (
    BRIDGE_BINDING,
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BRIDGE_UNKNOWN,
    DATA_DEVICES,
    DATA_EPISODES,
    DEFAULT_TAINT_FLOOR_MINUTES,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    DEV_TAINTED,
    DEV_TODAY_MAX,
    EP_LEARNED,
    EP_TAINT_SECONDS,
    FREEZE_ARMING_DAYS,
    STACK_MATTER,
    DATA_SYSTEM_EVENTS,
    STACK_Z2M,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
    SYS_KIND,
    SYS_PAIRING_CLOSED,
    SYS_PAIRING_OPEN,
    SYS_SCOPE,
    STACK_ZHA,
    STACK_ZWAVE,
    STARTUP_GRACE_SECONDS,
)

from tests.helpers import setup_coordinator

DOMAIN = "device_sentinel"

# Pinned at 01:00 UTC (the harness runs in UTC) so the multi-hour
# silences below never cross midnight, which would roll the live
# maximum into the daily series and empty the value being asserted.
_PIN = "2026-07-24T01:00:00+00:00"


def _register(hass, uid, name, domain="test"):
    """A device on the given integration domain carrying one sensor,
    returning (device, entity_id). The domain matters for pairing,
    which keys on the mqtt domain a Z2M device carries."""
    source = MockConfigEntry(domain=domain)
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(domain, uid)},
        name=name,
    )
    entity = er.async_get(hass).async_get_or_create(
        "sensor", domain, f"{uid}_0", device_id=device.id, config_entry=source
    )
    return device, entity.entity_id


def _device(hass, domain, uid, name, model=None, manufacturer=None):
    """A watched device owned by a config entry of the given domain,
    optionally with a model and manufacturer for the Z2M bridge tells."""
    source = MockConfigEntry(domain=domain)
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(domain, uid)},
        name=name,
        model=model,
        manufacturer=manufacturer,
    )
    er.async_get(hass).async_get_or_create(
        "sensor", domain, f"{uid}_0", device_id=device.id, config_entry=source
    )
    return device


async def _pinned_coordinator(hass, freezer):
    """A coordinator with the clock pinned to _PIN and the startup grace
    already elapsed, so a silence driven afterward is judged rather than
    swallowed as startup churn. The taint and pairing paths both need
    the grace closed and the wall clock held off midnight."""
    freezer.move_to(_PIN)
    coord = await setup_coordinator(hass)
    freezer.tick(timedelta(seconds=STARTUP_GRACE_SECONDS + 5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    return coord


def _arm(coord, device_id, basis_hours):
    """Give a device a learned rhythm so it has a freeze window. The
    debounce takes a share of that window, so an armed device is what
    exercises the share; an unarmed device gets the floor alone."""
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_DAILY_MAX] = [basis_hours * 3600.0] * (FREEZE_ARMING_DAYS + 2)


async def _silence(hass, freezer, eid, silent_hours, unavailable_seconds):
    """Drive a real silence: report, go quiet, blip unavailable, return.

    Every step goes through the state-change handlers so the debounce
    path is what decides the outcome.
    """
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=silent_hours * 3600.0))
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=unavailable_seconds))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()


def _learned_gap(record):
    """Return the largest gap the device has learned, live or rolled,
    robust to a midnight rollover moving the live maximum into the
    daily series."""
    candidates = list(record[DEV_DAILY_MAX])
    if record[DEV_TODAY_MAX] is not None:
        candidates.append(record[DEV_TODAY_MAX])
    return max(candidates) if candidates else None


def _msg(payload):
    """A stand-in for an MQTT ReceiveMessage carrying a payload."""
    return SimpleNamespace(payload=payload)


def _reader(hass):
    return Z2MBridgeReader(hass)


def _binding_reader(hass):
    """A bridge reader already in binding, as it would be with a pairing
    window open on the live system."""
    r = Z2MBridgeReader(hass)
    r._on_state(_msg("online"))
    r._on_info(_msg('{"permit_join": true, "permit_join_end": 1}'))
    return r


def _running_reader(hass):
    """A bridge reader running, no pairing open."""
    r = Z2MBridgeReader(hass)
    r._on_state(_msg("online"))
    r._on_info(_msg('{"permit_join": false}'))
    return r


async def _silence_and_recover(hass, freezer, eid, silent_hours):
    """Report, go quiet past basis, read unavailable, then recover on a
    real value, all through the real handlers. A render tick is fired
    during the silence so the episode-open scan runs, as the live
    system does on its 60-second tick."""
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=silent_hours * 3600.0))
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


# ==================================================================
# Coordinator stack auto-detection.
# ==================================================================

async def test_zha_and_zwave_and_matter_are_told_by_domain(
    hass: HomeAssistant,
):
    """A device on each domain marks its stack present."""
    _device(hass, "zha", "z1", "A Zigbee Light")
    _device(hass, "zwave_js", "w1", "A Z-Wave Switch")
    _device(hass, "matter", "m1", "A Matter Plug")
    coord = await setup_coordinator(hass)
    assert STACK_ZHA in coord._stacks
    assert STACK_ZWAVE in coord._stacks
    assert STACK_MATTER in coord._stacks
    # No Z2M: there is no bridge device.
    assert STACK_Z2M not in coord._stacks


async def test_mqtt_without_a_bridge_is_not_z2m(hass: HomeAssistant):
    """The case that matters. A house full of MQTT devices with no
    Zigbee2MQTT bridge must not report Z2M, because the mqtt domain
    alone cannot tell Z2M apart from any other MQTT device (#139)."""
    _device(hass, "mqtt", "q1", "Some MQTT Sensor")
    _device(hass, "mqtt", "q2", "Another MQTT Thing")
    coord = await setup_coordinator(hass)
    assert STACK_Z2M not in coord._stacks


async def test_the_z2m_bridge_name_marks_z2m_present(hass: HomeAssistant):
    """A bridge device whose name ends 'Zigbee2MQTT Bridge' marks Z2M
    present. This is the portable tell: it holds whatever coordinator
    hardware sits behind it (an SLZB, a Sonoff dongle, anything)."""
    _device(hass, "mqtt", "b1", "SLZB-06M Zigbee2MQTT Bridge")
    _device(hass, "mqtt", "q1", "A normal MQTT sensor")
    coord = await setup_coordinator(hass)
    assert STACK_Z2M in coord._stacks


async def test_the_z2m_bridge_model_marks_z2m_present(hass: HomeAssistant):
    """The backup tell: a device with model 'Bridge' under manufacturer
    'Zigbee2MQTT', for a bridge named something else entirely."""
    _device(
        hass,
        "mqtt",
        "b2",
        "Coordinator",
        model="Bridge",
        manufacturer="Zigbee2MQTT",
    )
    coord = await setup_coordinator(hass)
    assert STACK_Z2M in coord._stacks


async def test_a_house_with_nothing_has_no_stacks(hass: HomeAssistant):
    """No coordinator devices, no stacks. The detection reports only
    what is actually present."""
    _device(hass, "sun", "s1", "Sun")
    coord = await setup_coordinator(hass)
    assert coord._stacks == set()


async def test_stacks_reach_diagnostics(hass: HomeAssistant):
    """The whole visible surface of the phase: the detected stacks
    appear in the diagnostics classification block, sorted."""
    from custom_components.device_sentinel.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    _device(hass, "zha", "z1", "A Zigbee Light")
    _device(hass, "mqtt", "b1", "SLZB-06M Zigbee2MQTT Bridge")
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)
    stacks = result["classification"]["stacks"]
    assert STACK_ZHA in stacks
    assert STACK_Z2M in stacks
    assert stacks == sorted(stacks)


# ==================================================================
# The Z2M bridge reader.
# ==================================================================

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


# ==================================================================
# The grace-share taint debounce.
# ==================================================================

async def test_button_james_long_self_recovery_is_learned(
    hass: HomeAssistant, freezer
):
    """The lost-data case, now fixed. A 9h self-recovery on a device
    with a ~6.3h basis, its unavailable blip a few seconds, is
    learned: the debounce (floor + share) is far longer than the
    blip, so no taint is set and the real gap reaches the maximum."""
    device, eid = _register(hass, "bj", "Button James Night Table")
    coord = await _pinned_coordinator(hass, freezer)
    _arm(coord, device.id, 6.3)
    rec = coord.data[DATA_DEVICES][device.id]

    await _silence(hass, freezer, eid, silent_hours=9.0, unavailable_seconds=8)

    assert rec[DEV_TAINTED] is False
    learned = _learned_gap(rec)
    assert learned is not None and learned >= 8 * 3600
    # No episode was tainted: the gap is honest, not excluded.
    assert all(
        ep.get(EP_TAINT_SECONDS) is None
        for ep in coord.data.get(DATA_EPISODES, [])
    )


async def test_door_master_real_outage_stays_discarded(
    hass: HomeAssistant, freezer
):
    """The false-flag case, still correct. A device with a ~3.7h
    basis, unavailable well past its debounce before it returns, has
    that gap discarded: the taint fires and the completed gap is
    excluded from learning."""
    device, eid = _register(hass, "dm", "Door Master")
    coord = await _pinned_coordinator(hass, freezer)
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()
    _arm(coord, device.id, 3.7)
    rec = coord.data[DATA_DEVICES][device.id]

    # Go unavailable long enough to taint (past floor + share), then
    # come back on the device's own report. The taint is set on the
    # recovering transition and consumed by the completing stamp.
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=90 * 60))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    # The gap that spanned the outage is discarded: the live maximum
    # never took it.
    assert rec[DEV_TODAY_MAX] is None or rec[DEV_TODAY_MAX] < 90 * 60
    assert rec[DEV_TAINTED] is False  # consumed by the recovery


async def test_a_fast_device_keeps_the_floor_against_a_two_second_blip(
    hass: HomeAssistant, freezer
):
    """The reason the floor exists. A device with a tiny window would
    get a near-zero debounce from a pure share, so a two-second mesh
    blip would taint it. The floor holds: two seconds is far under
    the ten-minute floor, so the gap is learned."""
    device, eid = _register(hass, "f1", "Fast Sensor")
    coord = await _pinned_coordinator(hass, freezer)
    _arm(coord, device.id, 0.02)  # ~72 s basis, a very fast device
    rec = coord.data[DATA_DEVICES][device.id]

    await _silence(
        hass, freezer, eid, silent_hours=0.5, unavailable_seconds=2
    )

    assert rec[DEV_TAINTED] is False
    learned = _learned_gap(rec)
    assert learned is not None and learned >= 0.5 * 3600 - 5


async def test_the_recorder_writes_the_tainting_duration(
    hass: HomeAssistant, freezer
):
    """Step 4's recorder, proven. When a taint discards a gap, the
    unavailable duration lands on the episode as taint_seconds, so
    the rig can measure the real spread rather than a guess."""
    device, eid = _register(hass, "rec", "Recorder Sensor")
    coord = await _pinned_coordinator(hass, freezer)
    hass.states.async_set(eid, "1")
    await hass.async_block_till_done()

    # Arm the device and backdate its last contact past its basis so
    # the silence scan opens an episode for it.
    coord._grace_until = 0.0
    _arm(coord, device.id, 3.7)
    rec_record = coord.data[DATA_DEVICES][device.id]
    rec_record[DEV_LAST_ACTIVITY] = (
        dt_util.utcnow().timestamp() - 6 * 3600.0
    )
    coord._judge_all_devices()
    assert coord.data.get(DATA_EPISODES), "no episode opened"

    # Now taint it with a long unavailable and recover on its own.
    hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=60 * 60))
    hass.states.async_set(eid, "2")
    await hass.async_block_till_done()

    tainted = [
        ep
        for ep in coord.data.get(DATA_EPISODES, [])
        if ep.get(EP_TAINT_SECONDS) is not None
    ]
    assert tainted, "no episode recorded a tainting duration"
    assert tainted[0][EP_TAINT_SECONDS] == pytest.approx(60 * 60, abs=5)


async def test_an_unarmed_device_uses_the_floor(
    hass: HomeAssistant, freezer
):
    """A device with no learned window falls back to the floor alone:
    with nothing learned there is no grace to take a share of. A
    five-minute unavailable is under the ten-minute floor and is
    learned; the same on an armed device is well within its window
    too, so the floor is the operative rule here."""
    device, eid = _register(hass, "u1", "Unarmed Sensor")
    coord = await _pinned_coordinator(hass, freezer)
    rec = coord.data[DATA_DEVICES][device.id]
    # Not armed: no DEV_DAILY_MAX, so _freeze_window is None.
    assert len(rec[DEV_DAILY_MAX]) < FREEZE_ARMING_DAYS

    await _silence(
        hass,
        freezer,
        eid,
        silent_hours=0.5,
        unavailable_seconds=DEFAULT_TAINT_FLOOR_MINUTES * 60 - 120,
    )

    # Five minutes < the ten-minute floor, so no taint: learned.
    assert rec[DEV_TAINTED] is False
    learned = _learned_gap(rec)
    assert learned is not None and learned >= 0.5 * 3600 - 5


# ==================================================================
# The full-path pairing override.
# ==================================================================

async def test_recovery_during_binding_is_discarded_as_pairing(
    hass: HomeAssistant, freezer
):
    """The full path. An mqtt device recovers while its bridge is in
    binding, and its completed gap is set aside as a pairing
    intervention, marked no (pairing), not learned."""
    device, eid = _register(hass, "pair1", "Switch Under Test", domain="mqtt")
    coord = await _pinned_coordinator(hass, freezer)
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
    device, eid = _register(hass, "pair2", "Switch Not Pairing", domain="mqtt")
    coord = await _pinned_coordinator(hass, freezer)
    coord._bridge_readers[STACK_Z2M] = _running_reader(hass)
    _arm(coord, device.id, basis_hours=1.0)

    await _silence_and_recover(hass, freezer, eid, silent_hours=3.0)

    ep = _last_episode(coord, device.id)
    assert ep is not None
    # A 3h self-recovery on a 1h basis, brief unavailable: learned,
    # and since 0.10.10 learned under the resurrection cap (#166),
    # because the device stood convicted when it spoke. The contrast
    # with the pairing case holds: a pairing gap is discarded whole,
    # this one still teaches, bounded.
    assert ep[EP_LEARNED].startswith("capped (3.0h -> ")


async def test_pairing_gap_does_not_widen_the_rhythm(
    hass: HomeAssistant, freezer
):
    """A discarded pairing gap must not become the learned maximum. The
    device's rhythm after a pairing-discarded 3h gap is still its armed
    1h basis, not 3h."""
    device, eid = _register(hass, "pair3", "Switch Rhythm Guard", domain="mqtt")
    coord = await _pinned_coordinator(hass, freezer)
    coord._bridge_readers[STACK_Z2M] = _binding_reader(hass)
    _arm(coord, device.id, basis_hours=1.0)

    await _silence_and_recover(hass, freezer, eid, silent_hours=3.0)

    record = coord.data[DATA_DEVICES][device.id]
    today = record.get("today_max")
    # The 3h (10800s) pairing gap was retracted, so today_max is not it.
    assert today is None or today < 3.0 * 3600.0


def _kinds(coord, kind):
    return [
        row
        for row in coord.data.get(DATA_SYSTEM_EVENTS, [])
        if row[SYS_KIND] == kind
    ]


async def test_the_bridge_going_down_and_back_is_recorded(
    hass: HomeAssistant, freezer
):
    """One line above fifty device rows, saying why they happened.

    Nothing else polls the reader: its state is read on demand by the
    sensors and the pairing check, so a bridge could go away and come
    back leaving no trace anywhere but in the devices it silenced.
    """
    coord = await setup_coordinator(hass)
    reader = _running_reader(hass)
    coord._bridge_readers[STACK_Z2M] = reader
    await coord._on_render_tick(None)          # the first, steady reading

    reader._on_state(_msg("offline"))
    await coord._on_render_tick(None)
    down = _kinds(coord, SYS_BRIDGE_DOWN)
    assert len(down) == 1
    assert down[0][SYS_SCOPE] == STACK_Z2M

    freezer.tick(360)
    reader._on_state(_msg("online"))
    await coord._on_render_tick(None)
    up = _kinds(coord, SYS_BRIDGE_UP)
    assert len(up) == 1
    assert up[0]["duration"] >= 300, "the outage lost its span"


async def test_a_steady_bridge_records_nothing(
    hass: HomeAssistant, freezer
):
    """Only transitions. A reader sampled every minute all day would
    otherwise fill the record with the news that nothing changed."""
    coord = await setup_coordinator(hass)
    coord._bridge_readers[STACK_Z2M] = _running_reader(hass)
    for _ in range(4):
        await coord._on_render_tick(None)
    assert _kinds(coord, SYS_BRIDGE_DOWN) == []
    assert _kinds(coord, SYS_BRIDGE_UP) == []


class _Stub:
    """A reader whose state can be set, to drive the sampler alone.

    It carries async_stop because the coordinator's shutdown calls it
    on every reader, and a stub without it fails the unload, leaves
    the render tick uncancelled, and turns a passing test into a
    teardown error.
    """

    def __init__(self, state, pairing=False):
        self.state = state
        self.pairing_open = pairing

    def async_stop(self):
        return None


async def test_a_blip_to_unknown_does_not_lose_the_recovery(
    hass: HomeAssistant, freezer
):
    """Unknown is not a state the bridge is in, it is the absence of
    news, and treating it as one costs the recovery.

    A bridge that is down, briefly unheard, and then back would
    otherwise leave the down recorded and the return not, because the
    sampler would have forgotten it was ever down. The outage would
    read as permanent for as long as the record is kept.
    """
    coord = await setup_coordinator(hass)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    await coord._on_render_tick(None)

    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_DOWN)
    await coord._on_render_tick(None)
    assert len(_kinds(coord, SYS_BRIDGE_DOWN)) == 1

    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_UNKNOWN)
    await coord._on_render_tick(None)

    freezer.tick(120)
    coord._bridge_readers[STACK_Z2M] = _Stub(BRIDGE_RUNNING)
    await coord._on_render_tick(None)

    up = _kinds(coord, SYS_BRIDGE_UP)
    assert len(up) == 1, "the return was lost across the blip"
    assert up[0]["duration"] >= 60


async def test_a_pairing_window_is_recorded_with_its_span(
    hass: HomeAssistant, freezer
):
    """Pairing already discards gaps (#150); this says when and for
    how long, so a discarded gap has a visible reason."""
    coord = await setup_coordinator(hass)
    reader = _running_reader(hass)
    coord._bridge_readers[STACK_Z2M] = reader
    await coord._on_render_tick(None)

    reader._on_info(_msg('{"permit_join": true, "permit_join_end": 1}'))
    await coord._on_render_tick(None)
    assert len(_kinds(coord, SYS_PAIRING_OPEN)) == 1

    freezer.tick(120)
    reader._on_info(_msg('{"permit_join": false}'))
    await coord._on_render_tick(None)
    closed = _kinds(coord, SYS_PAIRING_CLOSED)
    assert len(closed) == 1
    assert closed[0]["duration"] >= 60
