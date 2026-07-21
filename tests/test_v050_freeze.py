# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v050_freeze.py, Version: 0.6.2 (2026-07-21)

"""0.5.0 tests: the freeze, unavailable, and unknown detector.

The margin follows the ruling-85 power curve shaped by the two
deltas, gated by the arming floor (#27). A device is judged frozen
when it goes silent past its window, unavailable or unknown when all
its live entities read so, with the worst category winning a mix.
Detection is live: the verdict clears the instant the device reports,
and a stored verdict survives a reboot rebuilt from the device's own
last-activity clock.
"""

import pytest

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_FREEZE_DELTA_HIGH,
    CONF_FREEZE_DELTA_LOW,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_UNKNOWN,
)
from custom_components.device_sentinel.coordinator import _new_device_record

DOMAIN = "device_sentinel"


def _register_device(hass, uid: str, entity_count: int = 1):
    """Create a real registry device with N entities."""
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=f"Freeze {uid}",
    )
    entities = []
    for n in range(entity_count):
        ent = er.async_get(hass).async_get_or_create(
            "sensor",
            "test",
            f"{uid}_{n}",
            device_id=device.id,
            config_entry=source,
        )
        entities.append(ent.entity_id)
    return device, entities


async def _coordinator(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Device Sentinel",
        data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _armed_record(rhythm_seconds: float, last_activity: float):
    """A record with an established rhythm and a last-activity stamp.

    Enough daily maxima to be armed, all equal to the rhythm so the
    trimmed maximum is exactly that value.
    """
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_DAILY_MAX] = [rhythm_seconds] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = last_activity
    return record


# --------------------------------------------------------------- margin


async def test_margin_curve_hits_the_ruling_85_anchors(
    hass: HomeAssistant,
):
    """The default curve passes through its anchors: a 1-hour device
    gets about a 2x window, and the grace is clamped to the deltas."""
    coord = await _coordinator(hass)
    one_hour = 3600.0
    grace = coord._freeze_grace(one_hour)
    window = one_hour + grace
    # 1 hr -> ~2x window (grace near 1 hr).
    assert 1.9 <= window / one_hour <= 2.3


async def test_margin_clamps_to_the_two_deltas(hass: HomeAssistant):
    """A very fast rhythm floors at delta-low, a very slow one ceils
    at delta-high, whatever the curve would otherwise give."""
    coord = await _coordinator(
        hass, {CONF_FREEZE_DELTA_LOW: 3, CONF_FREEZE_DELTA_HIGH: 6}
    )
    # 1-second rhythm: curve would give less than the floor.
    assert coord._freeze_grace(1.0) == pytest.approx(3 * 60, abs=1)
    # 48-hour rhythm: curve would give more than the ceiling.
    assert coord._freeze_grace(48 * 3600) == pytest.approx(6 * 3600, abs=1)


async def test_deltas_reshape_the_curve_not_just_the_ends(
    hass: HomeAssistant,
):
    """Moving the deltas changes the grace for a mid-fleet device, not
    only the extremes: the whole curve re-fits."""
    tight = await _coordinator(
        hass, {CONF_FREEZE_DELTA_LOW: 1, CONF_FREEZE_DELTA_HIGH: 4}
    )
    tight_grace = tight._freeze_grace(3600.0)
    # New entry for a looser setting (separate coordinator).
    loose_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Loose",
        data={},
        options={CONF_FREEZE_DELTA_LOW: 5, CONF_FREEZE_DELTA_HIGH: 8},
    )
    loose_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(loose_entry.entry_id)
    await hass.async_block_till_done()
    loose_grace = loose_entry.runtime_data._freeze_grace(3600.0)
    # A 1-hour device is neither delta; it sits mid-curve, so a looser
    # setting gives it more grace than a tighter one.
    assert loose_grace > tight_grace


# ----------------------------------------------------------- arming gate


async def test_unarmed_device_has_no_freeze_window(hass: HomeAssistant):
    """A device with too few learned days has no window, so it is
    never called frozen (unavailable-only until armed, #27)."""
    coord = await _coordinator(hass)
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_DAILY_MAX] = [60.0] * (FREEZE_ARMING_DAYS - 1)
    assert coord._freeze_window(record) is None


async def test_armed_device_has_a_window(hass: HomeAssistant):
    """Enough learned days gives a window of rhythm plus grace."""
    coord = await _coordinator(hass)
    record = _armed_record(3600.0, 0.0)
    window = coord._freeze_window(record)
    assert window is not None
    assert window > 3600.0  # rhythm plus some grace


# ---------------------------------------------------------- freeze fire


async def test_armed_silent_device_is_judged_frozen(hass: HomeAssistant):
    """An armed device silent past its window, with a live entity
    holding a stale value, is frozen."""
    device, entities = _register_device(hass, "frz1", entity_count=1)
    coord = await _coordinator(hass)
    # A stale-but-present value.
    hass.states.async_set(entities[0], "21.5")
    now = 1_000_000.0
    window = coord._freeze_grace(3600.0) + 3600.0
    record = _armed_record(3600.0, now - window - 10)
    coord.data["devices"][device.id] = record
    category = coord._device_down_category(device.id, record, now)
    assert category == FREEZE_CATEGORY_FROZEN


async def test_fresh_entity_keeps_a_device_alive(hass: HomeAssistant):
    """A device whose clock says frozen but whose activity is recent
    is not frozen: a report inside the window means alive."""
    device, entities = _register_device(hass, "frz2", entity_count=1)
    coord = await _coordinator(hass)
    hass.states.async_set(entities[0], "21.5")
    now = 1_000_000.0
    # last activity only 10 s ago: well inside any window.
    record = _armed_record(3600.0, now - 10)
    coord.data["devices"][device.id] = record
    assert coord._device_down_category(device.id, record, now) is None


# --------------------------------------------- unavailable and unknown


async def test_all_entities_unavailable_is_unavailable(hass: HomeAssistant):
    """When every live entity reads unavailable, the device is
    unavailable, no arming needed."""
    device, entities = _register_device(hass, "un1", entity_count=2)
    coord = await _coordinator(hass)
    for e in entities:
        hass.states.async_set(e, STATE_UNAVAILABLE)
    now = 1_000_000.0
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_LAST_ACTIVITY] = now - 10
    coord.data["devices"][device.id] = record
    assert (
        coord._device_down_category(device.id, record, now)
        == FREEZE_CATEGORY_UNAVAILABLE
    )


async def test_all_entities_unknown_is_unknown(hass: HomeAssistant):
    """When every live entity reads unknown, the device is unknown."""
    device, entities = _register_device(hass, "un2", entity_count=2)
    coord = await _coordinator(hass)
    for e in entities:
        hass.states.async_set(e, STATE_UNKNOWN)
    now = 1_000_000.0
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_LAST_ACTIVITY] = now - 10
    coord.data["devices"][device.id] = record
    assert (
        coord._device_down_category(device.id, record, now)
        == FREEZE_CATEGORY_UNKNOWN
    )


async def test_mixed_down_state_worst_category_wins(hass: HomeAssistant):
    """Six unavailable and two unknown resolves to unavailable: the
    most definite category dominates a mixed device."""
    device, entities = _register_device(hass, "mix1", entity_count=8)
    coord = await _coordinator(hass)
    for e in entities[:6]:
        hass.states.async_set(e, STATE_UNAVAILABLE)
    for e in entities[6:]:
        hass.states.async_set(e, STATE_UNKNOWN)
    now = 1_000_000.0
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_LAST_ACTIVITY] = now - 10
    coord.data["devices"][device.id] = record
    assert (
        coord._device_down_category(device.id, record, now)
        == FREEZE_CATEGORY_UNAVAILABLE
    )


async def test_one_fresh_entity_beats_seven_unavailable(hass: HomeAssistant):
    """If one live entity still reports a real value, the device is
    alive however many siblings are unavailable."""
    device, entities = _register_device(hass, "mix2", entity_count=8)
    coord = await _coordinator(hass)
    for e in entities[:7]:
        hass.states.async_set(e, STATE_UNAVAILABLE)
    hass.states.async_set(entities[7], "42")  # one real value
    now = 1_000_000.0
    # not armed and recent activity: only the all-bad path could flag,
    # and it does not, because one entity is good.
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_LAST_ACTIVITY] = now - 10
    coord.data["devices"][device.id] = record
    assert coord._device_down_category(device.id, record, now) is None


# ------------------------------------------------------ verdict + flip


async def test_verdict_flips_once_and_clears_on_report(
    hass: HomeAssistant,
):
    """A frozen verdict is stored on the flip and cleared the instant
    the device reports (live recovery)."""
    device, entities = _register_device(hass, "flip1", entity_count=1)
    coord = await _coordinator(hass)
    hass.states.async_set(entities[0], "21.5")
    now = 2_000_000.0
    window = coord._freeze_grace(3600.0) + 3600.0
    record = _armed_record(3600.0, now - window - 10)
    coord.data["devices"][device.id] = record

    # First judgment flips to frozen.
    assert coord._apply_freeze_verdict(device.id, record, now) is True
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    # Second judgment, unchanged, does not flip again.
    assert coord._apply_freeze_verdict(device.id, record, now) is False

    # A report clears it at once.
    coord._clear_freeze_verdict(device.id, record)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_FROZEN_SINCE] is None


async def test_unavailable_verdict_is_debounced(hass: HomeAssistant):
    """An unavailable device is not published on the first judgment;
    it must stay down past the debounce first, so a quick flip settles
    before it is reported."""
    device, entities = _register_device(hass, "deb1", entity_count=1)
    coord = await _coordinator(hass)
    hass.states.async_set(entities[0], STATE_UNAVAILABLE)
    now = 3_000_000.0
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_LAST_ACTIVITY] = now - 10
    coord.data["devices"][device.id] = record

    # First pass stamps the down-since but does not publish.
    assert coord._apply_freeze_verdict(device.id, record, now) is False
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_FROZEN_SINCE] == now

    # After the debounce elapses, it publishes.
    later = now + 200
    assert coord._apply_freeze_verdict(device.id, record, later) is True
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


# -------------------------------------------------- reboot survival


async def test_verdict_survives_reboot_from_stored_clock(
    hass: HomeAssistant,
):
    """A device frozen before a restart is still frozen after: the
    window is measured from the stored last-activity clock, which the
    reboot does not reset, not from Home Assistant's last_reported."""
    device, entities = _register_device(hass, "reboot1", entity_count=1)
    coord = await _coordinator(hass)
    hass.states.async_set(entities[0], "21.5")
    now = 4_000_000.0
    window = coord._freeze_grace(3600.0) + 3600.0
    # last activity is well past the window: this device was already
    # deep in a freeze before the (simulated) reboot.
    record = _armed_record(3600.0, now - window - 5000)
    coord.data["devices"][device.id] = record
    # A fresh judgment after "restart" still sees it frozen, because
    # the stored clock carries the real silence.
    assert (
        coord._device_down_category(device.id, record, now)
        == FREEZE_CATEGORY_FROZEN
    )


# ------------------------------------------------------- report + list


async def test_frozen_list_and_report_show_the_device(
    hass: HomeAssistant,
):
    """A frozen device appears in the sensor list and the telemetry
    report's down section."""
    device, entities = _register_device(hass, "rep1", entity_count=1)
    coord = await _coordinator(hass)
    hass.states.async_set(entities[0], "21.5")
    now = 5_000_000.0
    window = coord._freeze_grace(3600.0) + 3600.0
    record = _armed_record(3600.0, now - window - 10)
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = now - 600
    coord.data["devices"][device.id] = record

    rows = coord.frozen_devices_list
    assert any(r["device_id"] == device.id for r in rows)
    assert coord.frozen_devices_count >= 1

    lines = coord._reporting_lines()
    text = "\n".join(lines)
    assert "Reporting Devices" in text
    assert FREEZE_CATEGORY_FROZEN in text


async def test_empty_report_says_all_clear(hass: HomeAssistant):
    """With nothing down, the report's section is an all-clear line,
    not a blank."""
    coord = await _coordinator(hass)
    lines = coord._reporting_lines()
    text = "\n".join(lines)
    assert "Reporting Devices (0)" in text
    assert "nothing is frozen" in text
