# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_maintenance.py, Version: 0.12.12 (2026-08-07)

"""Maintenance mode and the surfaces that shipped beside it.

The window (rulings #225 and #238): one button declares a person at work on
the hardware, and any device that recovers while the declaration
stands is attributed to their hands rather than learned. Both edges
are recorded as system events, the end is a timestamp sensor a
dashboard can count down from, and pairing keeps precedence where
both windows are open because it names the stack where maintenance
names only the person.

Beside it: the awaiting-enable counts on Status (ruling #237), so a
dashboard shows each enable button only while a press would do
something; the availability attribute on the Z2M bridge sensor
(ruling #236), reported and never written; and the battery intervention
sentence (ruling #235), because a convicted battery device cannot be
reached by radio and the push should say what fixes it.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    ATTR_AWAITING_BATTERY,
    ATTR_AWAITING_LAST_SEEN,
    ATTR_AWAITING_SIGNAL,
    CONF_MAINTENANCE_MINUTES,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_LAST_ACTIVITY,
    DEV_TODAY_MAX,
    SYS_DETAIL,
    SYS_DURATION,
    SYS_KIND,
    SYS_MAINTENANCE_CLOSED,
    SYS_MAINTENANCE_OPEN,
)

from tests.helpers import register_device, setup_coordinator, setup_entry


def _event_kinds(coord) -> list[str]:
    """Return the recorded system event kinds, oldest first."""
    return [row[SYS_KIND] for row in coord.data.get(DATA_SYSTEM_EVENTS, [])]


def _maintenance_rows(coord) -> list[dict]:
    """Return only the maintenance rows from the system events."""
    return [
        row
        for row in coord.data.get(DATA_SYSTEM_EVENTS, [])
        if row[SYS_KIND]
        in (SYS_MAINTENANCE_OPEN, SYS_MAINTENANCE_CLOSED)
    ]


async def test_the_button_opens_and_a_second_press_closes_early(
    hass: HomeAssistant,
):
    """One button, two meanings, both edges recorded (ruling #238)."""
    coord = await setup_coordinator(hass)
    assert coord.maintenance_until is None

    result = await coord.async_toggle_maintenance()
    assert result == {"maintenance": "opened", "minutes": 10}
    until = coord.maintenance_until
    assert until is not None
    now = dt_util.utcnow().timestamp()
    # The default window is ten minutes from the press.
    assert 590 <= until - now <= 610

    result = await coord.async_toggle_maintenance()
    assert result == {"maintenance": "closed"}
    assert coord.maintenance_until is None

    rows = _maintenance_rows(coord)
    assert [row[SYS_KIND] for row in rows] == [
        SYS_MAINTENANCE_OPEN,
        SYS_MAINTENANCE_CLOSED,
    ]
    assert rows[0][SYS_DETAIL] == "10 minute window"
    assert rows[1][SYS_DETAIL] == "ended by hand"
    # The closing row carries how long the declaration actually stood.
    assert rows[1][SYS_DURATION] is not None
    assert rows[1][SYS_DURATION] < 60


async def test_the_window_length_is_the_option_clamped_to_its_band(
    hass: HomeAssistant,
):
    """The slider rules the window, and a wild value is clamped."""
    coord = await setup_coordinator(
        hass, options={CONF_MAINTENANCE_MINUTES: 30}
    )
    assert coord.maintenance_minutes == 30
    result = await coord.async_toggle_maintenance()
    assert result == {"maintenance": "opened", "minutes": 30}
    await coord.async_toggle_maintenance()

    # Out-of-band and broken values fall to the band edge or default,
    # so no option can produce a nonsensical window. Each is its own
    # setup, because a config entry's options are read-only from here.
    wide = await setup_coordinator(
        hass, options={CONF_MAINTENANCE_MINUTES: 500}
    )
    assert wide.maintenance_minutes == 60
    zero = await setup_coordinator(
        hass, options={CONF_MAINTENANCE_MINUTES: 0}
    )
    assert zero.maintenance_minutes == 5
    broken = await setup_coordinator(
        hass, options={CONF_MAINTENANCE_MINUTES: "wild"}
    )
    assert broken.maintenance_minutes == 10


async def test_an_expired_window_closes_at_its_declared_end(
    hass: HomeAssistant,
):
    """Expiry is lazy but stamped at the end, not at the noticing."""
    coord = await setup_coordinator(hass)
    await coord.async_toggle_maintenance()
    declared_end = coord.maintenance_until
    # Rewind the window so it has already lapsed, then let the lazy
    # check notice, the way the render tick would a minute later.
    coord._maintenance_until = declared_end - 700.0
    coord._maintenance_opened_at = declared_end - 1300.0
    now = dt_util.utcnow().timestamp()
    coord._expire_maintenance(now)

    assert coord.maintenance_until is None
    rows = _maintenance_rows(coord)
    assert rows[-1][SYS_KIND] == SYS_MAINTENANCE_CLOSED
    assert rows[-1][SYS_DETAIL] == "expired"
    # Stamped at the declared end the window actually had.
    assert rows[-1]["when"] == declared_end - 700.0
    assert rows[-1][SYS_DURATION] == 600.0


async def test_a_recovery_during_maintenance_is_not_learned(
    hass: HomeAssistant,
):
    """The discard (rulings #225 and #238): the gap never reaches the rhythm.

    The same device, the same gap, twice: without a window the gap
    becomes the day's maximum, with one it is discarded and the
    maximum it briefly wrote is retracted (ruling #166).
    """
    device, _ = register_device(hass, "maint1", name="Maint One")
    coord = await setup_coordinator(hass)

    # First contact stamps the clock; a rewind then manufactures a
    # 600 second silence for the next contact to complete.
    coord._record_activity(device.id, None)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_LAST_ACTIVITY] = record[DEV_LAST_ACTIVITY] - 600.0
    coord._record_activity(device.id, None)
    assert record[DEV_TODAY_MAX] is not None
    assert record[DEV_TODAY_MAX] >= 600.0

    # Again, inside a declared window: discarded, and the retraction
    # pulls the larger gap back out of the day.
    record[DEV_LAST_ACTIVITY] = record[DEV_LAST_ACTIVITY] - 900.0
    await coord.async_toggle_maintenance()
    coord._record_activity(device.id, None)
    assert record[DEV_TODAY_MAX] is None


async def test_pairing_takes_precedence_over_maintenance(
    hass: HomeAssistant,
):
    """Where both windows are open, the stack's signal wins (ruling #238).

    Observable as the absence of the maintenance retraction path
    taking a different branch: the discard happens either way, so the
    proof is the pairing branch running first, which this drives by
    making the pairing check answer yes and asserting the gap is
    still discarded (the maintenance branch is an elif and cannot
    run).
    """
    device, _ = register_device(hass, "maint2", name="Maint Two")
    coord = await setup_coordinator(hass)
    coord._recovered_during_pairing = lambda *_args: True

    coord._record_activity(device.id, None)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_LAST_ACTIVITY] = record[DEV_LAST_ACTIVITY] - 600.0
    await coord.async_toggle_maintenance()
    coord._record_activity(device.id, None)
    # Discarded by pairing: the retraction ran there, and the window
    # is still open with nothing double-counted.
    assert record[DEV_TODAY_MAX] is None
    assert coord.maintenance_until is not None


async def test_without_any_window_the_gap_is_learned(hass: HomeAssistant):
    """The control: no window, no pairing, the gap reaches the day."""
    device, _ = register_device(hass, "maint3", name="Maint Three")
    coord = await setup_coordinator(hass)
    coord._record_activity(device.id, None)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_LAST_ACTIVITY] = record[DEV_LAST_ACTIVITY] - 600.0
    coord._record_activity(device.id, None)
    assert record[DEV_TODAY_MAX] is not None


async def test_the_timer_sensor_is_a_timestamp_or_unknown(
    hass: HomeAssistant,
):
    """The dashboard surface (ruling #238): a time while open, unknown
    while closed, flipped without waiting for a tick."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    state = hass.states.get("sensor.device_sentinel_maintenance_ends")
    assert state is not None
    assert state.state == "unknown"

    await coord.async_toggle_maintenance()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.device_sentinel_maintenance_ends")
    assert state.state not in ("unknown", "unavailable")

    await coord.async_toggle_maintenance()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.device_sentinel_maintenance_ends")
    assert state.state == "unknown"


async def test_the_button_entity_exists_and_presses(hass: HomeAssistant):
    """The fifth button reaches the toggle."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.device_sentinel_maintenance_mode"},
        blocking=True,
    )
    assert coord.maintenance_until is not None


async def test_status_counts_what_each_enable_button_would_do(
    hass: HomeAssistant,
):
    """The awaiting-enable counts (ruling #237): exact, no lists, and
    user-disabled entities are in no count because the buttons leave
    them alone."""
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "await1")},
        name="Await One",
    )
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "sensor", "test", "aw_ls",
        suggested_object_id="await_last_seen",
        device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    ent_reg.async_get_or_create(
        "sensor", "test", "aw_lq",
        suggested_object_id="await_linkquality",
        device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    entry = await setup_entry(hass)
    coord = entry.runtime_data

    counts = coord.awaiting_enable_counts()
    assert counts == {"signal": 0, "last_seen": 1, "battery": 0}

    status = hass.states.get("sensor.device_sentinel_status")
    assert status.attributes[ATTR_AWAITING_LAST_SEEN] == 1
    assert status.attributes[ATTR_AWAITING_SIGNAL] == 0
    assert status.attributes[ATTR_AWAITING_BATTERY] == 0

    # Pressing the button empties its count: the attribute and the
    # press read the same registry through the same filter.
    await coord.async_enable_last_seen_entities()
    assert coord.awaiting_enable_counts()["last_seen"] == 0


async def test_the_battery_conviction_carries_the_intervention_line(
    hass: HomeAssistant,
):
    """A convicted battery device says what fixes it (ruling #235): a
    person at the device. A mains device says nothing extra, and a
    recovery never carries it."""
    device, _ = register_device(hass, "batt1", name="Batt One")
    coord = await setup_coordinator(hass)
    coord._notification_delay = lambda _device_id: 0.0

    sentence = "This is a battery device."

    # Mains: no elected battery entity, no line.
    coord._collect_event("frozen", "Batt One", False, device.id)
    assert coord._pending_events
    assert sentence not in coord._pending_events[-1][1]

    # Battery: the elected entity is the classification.
    coord._battery_entity[device.id] = ("sensor.batt_one_battery", False)
    coord._collect_event("frozen", "Batt One", False, device.id)
    line = coord._pending_events[-1][1]
    assert sentence in line
    assert "needs a person at the device" in line

    # A recovery is good news and carries no intervention ask.
    coord._collect_event("frozen", "Batt One", True, device.id)
    assert sentence not in coord._pending_events[-1][1]

    # The tap-open description says the same thing (ruling #235).
    _summary, description = coord._problem_item_text(
        "Batt One", {"frozen": None}, None, device_id=device.id
    )
    assert sentence in description
    _summary, description = coord._problem_item_text(
        "Batt One", {"battery": None}, 12, device_id=device.id
    )
    assert sentence not in description


async def test_the_bridge_sensor_reports_availability(hass: HomeAssistant):
    """The availability attribute (ruling #236): read from the reader,
    written by nobody."""

    class _Reader:
        permit_join_end = None
        base_topic = "zigbee2mqtt"
        last_heard = None
        availability_enabled = True

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    from custom_components.device_sentinel.sensor import (
        DeviceSentinelBridgeSensor,
    )

    sensor = DeviceSentinelBridgeSensor(coord, "zigbee2mqtt")
    original = coord._bridge_readers
    coord._bridge_readers = {"zigbee2mqtt": _Reader()}
    attrs = sensor.extra_state_attributes
    assert attrs["availability_enabled"] is True

    class _Bare:
        permit_join_end = None
        base_topic = "zigbee2mqtt"
        last_heard = None

    coord._bridge_readers = {"zigbee2mqtt": _Bare()}
    attrs = sensor.extra_state_attributes
    assert "availability_enabled" not in attrs

    # The real readers come back before teardown stops them.
    coord._bridge_readers = original


async def test_a_restart_closes_the_window_the_stop_interrupted(
    hass: HomeAssistant,
):
    """The events log pairs every edge: a window open at the stop gets
    its closing row at the next setup, detail "ended by restart", no
    duration because how long it truly stood cannot be known."""
    from tests.helpers import setup_entry

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    await coord.async_toggle_maintenance()
    assert coord.maintenance_until is not None
    # The stop, mid-window: unload persists, the window dies with the
    # process, and the open row stays behind in storage.
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    assert coord.maintenance_until is None
    rows = _maintenance_rows(coord)
    assert [row[SYS_KIND] for row in rows] == [
        SYS_MAINTENANCE_OPEN,
        SYS_MAINTENANCE_CLOSED,
    ]
    assert rows[-1][SYS_DETAIL] == "ended by restart"
    assert rows[-1][SYS_DURATION] is None

    # A cleanly closed pair is left alone: no second close appears at
    # the next restart.
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    assert len(_maintenance_rows(coord)) == 2
