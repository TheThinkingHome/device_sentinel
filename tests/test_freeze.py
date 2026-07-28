# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_freeze.py, Version: 0.10.2 (2026-07-28)

"""The freeze, unavailable, unknown, and never-reported detector.

The freeze margin follows the ruling-85 power curve shaped by the two
deltas and gated by the arming floor: a device is judged frozen when it
goes silent past its learned window, unavailable or unknown when all its
live entities read so, with the worst category winning a mix and one
fresh entity keeping the whole device alive. A device that has produced
nothing since well before now is flagged not-reported ahead of the other
categories, because it has no rhythm to miss, while a device still inside
its grace window is left alone. Detection is live: a verdict flips once,
clears the instant the device reports, is debounced for the unavailable
case, and survives a reboot because the window is measured from the
device's own stored last-activity clock. A freeze-excluded device is
watched but never given a verdict, every menu step carries a label so no
screen renders blank, and a pre-0.5.0 record missing the freeze fields
is judged without crashing the sweep. This file holds that detector.
"""

import json
import pathlib
from datetime import timedelta

import pytest

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_SAVED_AT,
    FREEZE_UNAVAILABLE_DEBOUNCE,
    CONF_FREEZE_DELTA_HIGH,
    CONF_FREEZE_DELTA_LOW,
    CONF_FREEZE_EXCLUDED_DEVICES,
    DEV_DAILY_MAX,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_NOT_REPORTED,
    FREEZE_CATEGORY_UNAVAILABLE,
    FREEZE_CATEGORY_UNKNOWN,
    FREEZE_NOT_REPORTED_SECONDS,
)
from custom_components.device_sentinel.coordinator import _new_device_record

from tests.helpers import register_device, setup_coordinator

DOMAIN = "device_sentinel"


def _armed_record(rhythm_seconds: float, last_activity: float):
    """A record with an established rhythm and a last-activity stamp.

    Enough daily maxima to be armed, all equal to the rhythm so the
    trimmed maximum is exactly that value.
    """
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_DAILY_MAX] = [rhythm_seconds] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = last_activity
    return record


def _never_reported_record(first_observed_iso: str):
    """Zero events, no activity, observed at the given time."""
    record = _new_device_record(first_observed_iso, None)
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_FIRST_OBSERVED] = first_observed_iso
    return record


def _pre_050_record(first_observed_iso):
    """A record as a pre-0.5.0 storage load leaves it: no freeze
    fields at all."""
    record = _new_device_record(first_observed_iso, None)
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    record[DEV_FIRST_OBSERVED] = first_observed_iso
    record.pop("frozen_category", None)
    record.pop("frozen_since", None)
    return record


# ==================================================================
# The margin curve.
# ==================================================================

async def test_margin_curve_hits_the_ruling_85_anchors(
    hass: HomeAssistant,
):
    """The default curve passes through its anchors: a 1-hour device
    gets a bit over a 2x window, and the grace is clamped to the
    deltas. The band moved at 0.6.7 with the delta-high default (6h
    to 8h, #102), which lifts the whole midrange."""
    coord = await setup_coordinator(hass)
    one_hour = 3600.0
    grace = coord._freeze_grace(one_hour)
    window = one_hour + grace
    # 1 hr -> ~2.35x window on the 0.6.7 defaults.
    assert 2.1 <= window / one_hour <= 2.6


async def test_margin_clamps_to_the_two_deltas(hass: HomeAssistant):
    """A very fast rhythm floors at delta-low, a very slow one ceils
    at delta-high, whatever the curve would otherwise give."""
    coord = await setup_coordinator(
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
    tight = await setup_coordinator(
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


# ==================================================================
# The arming gate.
# ==================================================================

async def test_unarmed_device_has_no_freeze_window(hass: HomeAssistant):
    """A device with too few learned days has no window, so it is
    never called frozen (unavailable-only until armed, #27)."""
    coord = await setup_coordinator(hass)
    record = _new_device_record("2026-07-11T00:00:00+00:00", None)
    record[DEV_DAILY_MAX] = [60.0] * (FREEZE_ARMING_DAYS - 1)
    assert coord._freeze_window(record) is None


async def test_armed_device_has_a_window(hass: HomeAssistant):
    """Enough learned days gives a window of rhythm plus grace."""
    coord = await setup_coordinator(hass)
    record = _armed_record(3600.0, 0.0)
    window = coord._freeze_window(record)
    assert window is not None
    assert window > 3600.0  # rhythm plus some grace


# ==================================================================
# Freeze fires.
# ==================================================================

async def test_armed_silent_device_is_judged_frozen(hass: HomeAssistant):
    """An armed device silent past its window, with a live entity
    holding a stale value, is frozen."""
    device, entities = register_device(hass, "frz1", entity_count=1)
    coord = await setup_coordinator(hass)
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
    device, entities = register_device(hass, "frz2", entity_count=1)
    coord = await setup_coordinator(hass)
    hass.states.async_set(entities[0], "21.5")
    now = 1_000_000.0
    # last activity only 10 s ago: well inside any window.
    record = _armed_record(3600.0, now - 10)
    coord.data["devices"][device.id] = record
    assert coord._device_down_category(device.id, record, now) is None


# ==================================================================
# Unavailable and unknown.
# ==================================================================

async def test_all_entities_unavailable_is_unavailable(hass: HomeAssistant):
    """When every live entity reads unavailable, the device is
    unavailable, no arming needed."""
    device, entities = register_device(hass, "un1", entity_count=2)
    coord = await setup_coordinator(hass)
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
    device, entities = register_device(hass, "un2", entity_count=2)
    coord = await setup_coordinator(hass)
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
    device, entities = register_device(hass, "mix1", entity_count=8)
    coord = await setup_coordinator(hass)
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
    device, entities = register_device(hass, "mix2", entity_count=8)
    coord = await setup_coordinator(hass)
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


# ==================================================================
# Verdict flip and debounce.
# ==================================================================

async def test_verdict_flips_once_and_clears_on_report(
    hass: HomeAssistant,
):
    """A frozen verdict is stored on the flip and cleared the instant
    the device reports (live recovery)."""
    device, entities = register_device(hass, "flip1", entity_count=1)
    coord = await setup_coordinator(hass)
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
    device, entities = register_device(hass, "deb1", entity_count=1)
    coord = await setup_coordinator(hass)
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


# ==================================================================
# Reboot survival.
# ==================================================================

async def test_verdict_survives_reboot_from_stored_clock(
    hass: HomeAssistant,
):
    """A device frozen before a restart is still frozen after: the
    window is measured from the stored last-activity clock, which the
    reboot does not reset, not from Home Assistant's last_reported."""
    device, entities = register_device(hass, "reboot1", entity_count=1)
    coord = await setup_coordinator(hass)
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


# ==================================================================
# The frozen list and report.
# ==================================================================

async def test_frozen_list_and_report_show_the_device(
    hass: HomeAssistant,
):
    """A frozen device appears in the sensor list and the telemetry
    report's down section."""
    device, entities = register_device(hass, "rep1", entity_count=1)
    coord = await setup_coordinator(hass)
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
    coord = await setup_coordinator(hass)
    lines = coord._reporting_lines()
    text = "\n".join(lines)
    assert "Reporting Devices (0)" in text
    assert "nothing is frozen" in text


# ==================================================================
# The never-reported verdict, the freeze exclude, the menu labels.
# ==================================================================

async def test_silent_since_install_is_not_reported(hass: HomeAssistant):
    """A device with zero events, first seen well past the grace
    window, is flagged not_reported."""
    device, _ = register_device(hass, "nr1")
    coord = await setup_coordinator(hass)
    # Observed 3 days ago, still nothing.
    record = _never_reported_record("2026-07-08T00:00:00+00:00")
    coord.data["devices"][device.id] = record
    now = 1_784_600_000.0  # well past 3 days after 2026-07-08
    assert (
        coord._device_down_category(device.id, record, now)
        == FREEZE_CATEGORY_NOT_REPORTED
    )


async def test_recently_added_silent_device_is_not_flagged(
    hass: HomeAssistant,
):
    """A device added moments ago with no events yet is not flagged:
    it may simply be slow to first report, inside the grace window."""
    device, _ = register_device(hass, "nr2")
    coord = await setup_coordinator(hass)
    # Observed only an hour before now.
    import datetime

    now = 1_784_600_000.0
    observed = datetime.datetime.fromtimestamp(
        now - 3600, tz=datetime.timezone.utc
    ).isoformat()
    record = _never_reported_record(observed)
    coord.data["devices"][device.id] = record
    assert coord._device_down_category(device.id, record, now) is None


async def test_a_device_that_reported_once_is_not_not_reported(
    hass: HomeAssistant,
):
    """One event ever means the not_reported path never applies, even
    if the device later goes silent: that is a freeze, not a
    never-started."""
    device, _ = register_device(hass, "nr3")
    coord = await setup_coordinator(hass)
    record = _never_reported_record("2026-07-08T00:00:00+00:00")
    record[DEV_EVENT_COUNT] = 1
    record[DEV_LAST_ACTIVITY] = 1_784_000_000.0
    coord.data["devices"][device.id] = record
    now = 1_784_600_000.0
    # Not not_reported; it has an event. (It is not armed either, so
    # not frozen; the point is it never takes the not_reported branch.)
    assert (
        coord._device_down_category(device.id, record, now)
        != FREEZE_CATEGORY_NOT_REPORTED
    )


async def test_freeze_exclude_suppresses_every_verdict(hass: HomeAssistant):
    """A freeze-excluded device is watched but never given a verdict,
    even one it would otherwise earn."""
    device, _ = register_device(hass, "fx1")
    coord = await setup_coordinator(hass, {CONF_FREEZE_EXCLUDED_DEVICES: []})
    record = _never_reported_record("2026-07-08T00:00:00+00:00")
    coord.data["devices"][device.id] = record
    now = 1_784_600_000.0
    # Without the exclude it would be not_reported.
    assert (
        coord._device_down_category(device.id, record, now)
        == FREEZE_CATEGORY_NOT_REPORTED
    )
    # Add the device to the freeze exclude and it goes quiet.
    hass.config_entries.async_update_entry(
        coord.entry,
        options={CONF_FREEZE_EXCLUDED_DEVICES: [device.id]},
    )
    assert coord._device_down_category(device.id, record, now) is None


def test_every_menu_step_has_a_label():
    """Every step in the options menu has a label in both string
    files, so no screen renders blank. This is the guard for the
    0.5.0 miss where freeze had a step but no menu label."""
    base = pathlib.Path("custom_components/device_sentinel")
    for fn in ("strings.json", "translations/en.json"):
        data = json.loads((base / fn).read_text())
        init = data["options"]["step"]["init"]
        labels = init["menu_options"]
        # Every step that appears as a menu option (minus init itself)
        # must have a non-empty label.
        steps = set(data["options"]["step"]) - {"init"}
        for step in steps:
            assert step in labels, f"{fn}: {step} has no menu label"
            assert labels[step].strip(), f"{fn}: {step} label is blank"


def test_grace_window_is_48_hours():
    """The not-reported grace is 48 hours, clearing once-a-day
    devices that will have reported twice by then."""
    assert FREEZE_NOT_REPORTED_SECONDS == 48 * 3600


# ==================================================================
# Judgment survives a pre-0.5.0 record.
# ==================================================================

async def test_old_record_judges_without_crashing(hass: HomeAssistant):
    """A pre-0.5.0 record with no freeze fields is judged, not
    crashed on, and an old zero-event ghost gets its verdict."""
    device, _ = register_device(hass, "ghost", "Front Security")
    coord = await setup_coordinator(hass)
    record = _pre_050_record("2026-07-11T01:17:48.811715+00:00")
    coord.data["devices"][device.id] = record
    # The whole sweep runs without raising, and the ghost, well past
    # the 48-hour grace, is flagged not_reported.
    coord._judge_all_devices()
    assert record["frozen_category"] == FREEZE_CATEGORY_NOT_REPORTED


async def test_every_old_record_in_the_sweep_is_judged(hass: HomeAssistant):
    """Two pre-0.5.0 ghosts, both missing the freeze fields, are both
    judged in one sweep. Before the fix the first killed the tick and
    the second was never reached; both must now be flagged."""
    first, _ = register_device(hass, "first", "First Ghost")
    second, _ = register_device(hass, "second", "Second Ghost")
    coord = await setup_coordinator(hass)
    first_record = _pre_050_record("2026-07-11T01:17:48.811715+00:00")
    second_record = _pre_050_record("2026-07-11T01:17:48.811715+00:00")
    coord.data["devices"][first.id] = first_record
    coord.data["devices"][second.id] = second_record
    coord._judge_all_devices()
    assert first_record["frozen_category"] == FREEZE_CATEGORY_NOT_REPORTED
    assert second_record["frozen_category"] == FREEZE_CATEGORY_NOT_REPORTED


# ==================================================================
# A pending down-stamp must not outlive the blip that set it.
# ==================================================================

def _contact_device(hass, uid):
    """A device that publishes its own last-contact entity."""
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=uid,
    )
    reg = er.async_get(hass)
    plain = reg.async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    seen = reg.async_get_or_create(
        "sensor", "test", f"{uid}_last_seen",
        device_id=device.id, config_entry=source,
        suggested_object_id=f"{uid}_last_seen",
    )
    return device, plain.entity_id, seen.entity_id


async def _blip_and_republish(hass, coord, device, eid, seen, heard, freezer):
    """Take a device down briefly, then bring it back by republishing.

    The republish returns the same last-contact stamp, so the contact
    clock does not advance and the return is not a report (#124).
    """
    record = coord.data[DATA_DEVICES][device.id]
    freezer.tick(timedelta(seconds=30))
    hass.states.async_set(seen, STATE_UNAVAILABLE)
    hass.states.async_set(eid, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    coord._apply_freeze_verdict(
        device.id, record, dt_util.utcnow().timestamp()
    )
    freezer.tick(timedelta(seconds=20))
    hass.states.async_set(seen, heard)
    hass.states.async_set(eid, "on")
    await hass.async_block_till_done()
    coord._apply_freeze_verdict(
        device.id, record, dt_util.utcnow().timestamp()
    )
    return record


async def test_a_pending_stamp_clears_when_the_device_reads_healthy(
    hass: HomeAssistant, freezer
):
    """A blip stamps a down-since before any verdict is published. If
    the device comes back by republishing a retained value, the clock
    does not advance, so the report path never runs and nothing there
    clears the stamp. It has to clear here instead, or it outlives the
    blip that set it."""
    device, eid, seen = _contact_device(hass, "pend1")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    heard = dt_util.utcnow().isoformat()
    hass.states.async_set(seen, heard)
    hass.states.async_set(eid, "on")
    await hass.async_block_till_done()

    record = await _blip_and_republish(
        hass, coord, device, eid, seen, heard, freezer
    )
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record[DEV_FROZEN_SINCE] is None


async def test_a_later_outage_still_serves_its_full_debounce(
    hass: HomeAssistant, freezer
):
    """The consequence a person would notice. A stale stamp makes the
    next outage look hours old, so it publishes at once instead of
    waiting out the debounce, and the brief reports a device that just
    went down as having been down all along."""
    device, eid, seen = _contact_device(hass, "pend2")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    heard = dt_util.utcnow().isoformat()
    hass.states.async_set(seen, heard)
    hass.states.async_set(eid, "on")
    await hass.async_block_till_done()

    record = await _blip_and_republish(
        hass, coord, device, eid, seen, heard, freezer
    )

    # Two hours later it goes down for real.
    freezer.tick(timedelta(hours=2))
    hass.states.async_set(seen, STATE_UNAVAILABLE)
    hass.states.async_set(eid, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    now = dt_util.utcnow().timestamp()
    assert coord._apply_freeze_verdict(device.id, record, now) is False
    # The stamp dates from this outage, not from the old blip.
    assert now - record[DEV_FROZEN_SINCE] < FREEZE_UNAVAILABLE_DEBOUNCE

    # It publishes only once the debounce has actually elapsed.
    freezer.tick(timedelta(seconds=FREEZE_UNAVAILABLE_DEBOUNCE + 5))
    assert (
        coord._apply_freeze_verdict(
            device.id, record, dt_util.utcnow().timestamp()
        )
        is True
    )
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


async def test_a_published_verdict_keeps_its_since_while_still_down(
    hass: HomeAssistant, freezer
):
    """The guard on the clearing above. Once a verdict is published,
    every later sweep sees the same category and returns early. The
    down-since has to survive those passes: it is what the problem
    list, the brief and the reports count from, so clearing it would
    reset a device's outage to zero on the next tick."""
    device, eid, seen = _contact_device(hass, "held1")
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    hass.states.async_set(seen, dt_util.utcnow().isoformat())
    hass.states.async_set(eid, "on")
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][device.id]

    # Down, stamped, then published once the debounce elapses.
    hass.states.async_set(seen, STATE_UNAVAILABLE)
    hass.states.async_set(eid, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    coord._apply_freeze_verdict(
        device.id, record, dt_util.utcnow().timestamp()
    )
    freezer.tick(timedelta(seconds=FREEZE_UNAVAILABLE_DEBOUNCE + 5))
    assert (
        coord._apply_freeze_verdict(
            device.id, record, dt_util.utcnow().timestamp()
        )
        is True
    )
    published_since = record[DEV_FROZEN_SINCE]
    assert published_since is not None

    # Still down an hour later: the sweep returns early and the stamp
    # is untouched, so the reported age keeps growing.
    freezer.tick(timedelta(hours=1))
    assert (
        coord._apply_freeze_verdict(
            device.id, record, dt_util.utcnow().timestamp()
        )
        is False
    )
    assert record[DEV_FROZEN_SINCE] == published_since
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


# ==================================================================
# #160: silence is judged on what was watched, not the wall clock.
# ==================================================================

def _freeze_window_of(coord, record):
    """The device's own window, for asserting the wall clock lies."""
    return coord._freeze_window(record)


async def test_an_outage_is_not_counted_against_a_device(
    hass: HomeAssistant, freezer
):
    """The fault a six-minute power cut exposed. A device that kept
    reporting to its bridge throughout was blamed for the silence the
    system could not hear, and the fastest reporters crossed their
    windows first, purely by arithmetic."""
    device, entities = register_device(hass, "dt1", entity_count=1)
    coord = await setup_coordinator(hass)
    # Settle the entity first: setting a state re-arms the
    # device's clock, which would overwrite the stamp under test.
    hass.states.async_set(entities[0], "21.5")
    await hass.async_block_till_done()
    now = dt_util.utcnow().timestamp()
    record = _armed_record(rhythm_seconds=120.0, last_activity=now - 30.0)
    coord.data[DATA_DEVICES][device.id] = record

    # The system was last listening 30 s after this device reported,
    # then nothing heard anything for twenty minutes.
    coord._last_alive = now
    coord._downtime = 1200.0
    later = now + 1200.0

    # Wall clock says 20.5 minutes of silence, far past its window.
    assert (later - record[DEV_LAST_ACTIVITY]) > _freeze_window_of(coord, record)
    # Observed silence is the 30 s before the stop, and no verdict.
    assert coord._observed_silence(record, later) == 30.0
    assert coord._device_down_category(device.id, record, later) is None


async def test_a_device_already_silent_is_still_caught_at_once(
    hass: HomeAssistant, freezer
):
    """The credit is an offset, not an amnesty. A device that had
    already gone quiet before the stop carries that silence into the
    sum, so a genuinely dead device is caught the instant the system
    returns rather than being given the outage as cover."""
    device, entities = register_device(hass, "dt2", entity_count=1)
    coord = await setup_coordinator(hass)
    # Settle the entity first: setting a state re-arms the
    # device's clock, which would overwrite the stamp under test.
    hass.states.async_set(entities[0], "21.5")
    await hass.async_block_till_done()
    now = dt_util.utcnow().timestamp()
    # Silent for two hours before the stop, window two minutes.
    record = _armed_record(rhythm_seconds=120.0, last_activity=now - 7200.0)
    coord.data[DATA_DEVICES][device.id] = record

    coord._last_alive = now
    coord._downtime = 1200.0
    later = now + 1200.0

    assert coord._observed_silence(record, later) == 7200.0
    assert (
        coord._device_down_category(device.id, record, later)
        == FREEZE_CATEGORY_FROZEN
    )


async def test_the_credit_lapses_once_the_device_reports(
    hass: HomeAssistant, freezer
):
    """A clock that postdates the outage needs no allowance, so the
    device is judged normally from its next report onward and a
    freeze arriving after the restart is caught on time."""
    device, entities = register_device(hass, "dt3", entity_count=1)
    coord = await setup_coordinator(hass)
    # Settle the entity first: setting a state re-arms the
    # device's clock, which would overwrite the stamp under test.
    hass.states.async_set(entities[0], "21.5")
    await hass.async_block_till_done()
    now = dt_util.utcnow().timestamp()
    record = _armed_record(rhythm_seconds=120.0, last_activity=now - 30.0)
    coord.data[DATA_DEVICES][device.id] = record
    coord._last_alive = now
    coord._downtime = 1200.0

    # It reports after the restart, so its clock is newer than the
    # last moment anything was listening.
    record[DEV_LAST_ACTIVITY] = now + 1200.0
    window = _freeze_window_of(coord, record)
    later = now + 1200.0 + window + 60.0
    # No credit: the whole span since it reported is counted, so a
    # freeze that begins after the restart is caught on time.
    # approx: a few hundred seconds added to a 1.7-billion-second
    # timestamp loses the last digit to float precision.
    assert coord._observed_silence(record, later) == pytest.approx(
        window + 60.0
    )
    assert (
        coord._device_down_category(device.id, record, later)
        == FREEZE_CATEGORY_FROZEN
    )


async def test_downtime_is_read_from_the_newer_file_stamp(
    hass: HomeAssistant, hass_storage
):
    """Both files carry the time they were written, and the newer is
    the last moment anything was observed. After a clean stop that is
    exact; after a crash it is early, which credits too much rather
    than too little."""
    coord = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    coord._note_downtime(
        {DATA_SAVED_AT: now - 3600.0}, {DATA_SAVED_AT: now - 600.0}
    )
    assert coord._last_alive == now - 600.0
    assert 590.0 < coord._downtime < 610.0


async def test_an_unstamped_pair_credits_nothing(
    hass: HomeAssistant, hass_storage
):
    """Files written before the stamp existed cannot date the outage,
    so nothing is credited and judgment is exactly as it was."""
    coord = await setup_coordinator(hass)
    coord._note_downtime({}, {})
    assert coord._last_alive is None
    assert coord._downtime == 0.0
