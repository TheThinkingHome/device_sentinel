# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_freeze_rules.py, Version: 0.24.0 (2026-10-02)

"""The freeze wait as the shorter of two rules (#542, amended in 0.24.0).

The Trimmed Maximum reads the last 14 days' longest gaps and sets the
longest aside. The Log-Normal Percentile reads up to 42 from a device's
28th day and sets aside days far above or below its usual. The wait in
use is the shorter. Each case here is one James ruled on, on 2 October
2026: two bad days at the end of steady weeks, a device that starts
reporting faster, the short days that blew up the shadow rule, a young
device, and the count since a reset. The histories are built, not
copied, so each shows one thing.
"""

from __future__ import annotations

import math

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    DEV_DAILY_MAX,
    DEV_FIRMWARE_HISTORY,
    DEV_LOGNORMAL_DAYS,
    RULE_LOGNORMAL,
    RULE_TRIMMED,
)
from custom_components.device_sentinel.model_groups import note_firmware
from custom_components.device_sentinel.records import _new_device_record
from custom_components.device_sentinel.rhythm_rules import (
    lognormal_days,
    lognormal_rhythm,
)
from tests.helpers import register_device, setup_coordinator

HOUR = 3600.0


def _steady(days: int, hours: float = 1.0) -> list[float]:
    """A steady device: its longest gap wobbles a little around `hours`."""
    return [hours * HOUR * (0.9 + 0.2 * ((i * 7) % 10) / 10) for i in range(days)]


def _record(daily: list[float], since=None) -> dict:
    record = _new_device_record("2026-08-01T00:00:00+00:00", None)
    record[DEV_DAILY_MAX] = list(daily)
    record[DEV_LOGNORMAL_DAYS] = since
    return record


# --------------------------------------------------------------- the formula


def test_no_log_normal_percentile_before_28_days():
    assert lognormal_rhythm(_steady(27), 27) is None
    assert lognormal_rhythm(_steady(28), 28) is not None


def test_short_days_no_longer_blow_up_the_wait():
    """The dragon light's pattern: ordinary days of 10 to 40 hours, with
    a few days whose longest gap was minutes. The shadow rule of 0.23.17,
    which set aside long days only, threw its wait past 900 hours; the
    rule clipped on both sides stays near the device's own long days."""
    daily = [h * HOUR for h in (16, 43, 12, 22, 21, 27, 15, 23, 30, 37, 10, 20, 25, 18)] * 3
    for i in (3, 17, 31):
        daily[i] = 0.05 * HOUR
    fit = lognormal_rhythm(daily, 42)
    assert fit is not None
    assert fit["rhythm"] < 60 * HOUR
    assert set(fit["set_aside"]) >= {3, 17, 31}


def test_days_read_count_bad_days_and_stop_at_42():
    daily = _steady(60)
    fit = lognormal_rhythm(daily, 42)
    assert fit["days"] == 42
    fit = lognormal_rhythm(daily[:37], 37)
    assert fit["days"] == 37


def test_hostile_values_are_not_read():
    daily = _steady(40)
    daily[5] = float("nan")
    daily[6] = -3.0
    daily[7] = True
    daily[8] = float("inf")
    fit = lognormal_rhythm(daily, 40)
    assert fit is not None and math.isfinite(fit["rhythm"])
    for bad in (-1, float("nan"), True, "x", None):
        assert lognormal_days(_record(_steady(40), bad)) == 40


def test_every_day_identical_is_not_a_division_by_zero():
    fit = lognormal_rhythm([HOUR] * 30, 30)
    assert fit is not None
    # The spread floor of 0.15 lifts the target a little above the day.
    assert HOUR < fit["rhythm"] < 1.3 * HOUR


def test_the_count_since_a_reset_limits_the_days_read():
    record = _record(_steady(40), 10)
    assert lognormal_days(record) == 10
    record[DEV_LOGNORMAL_DAYS] = None
    assert lognormal_days(record) == 40
    record[DEV_DAILY_MAX] = _steady(90)
    assert lognormal_days(record) == 42


# ------------------------------------------------------ the rule in use


async def test_two_bad_days_hand_the_wait_to_the_log_normal_percentile(
    hass: HomeAssistant,
):
    coord = await setup_coordinator(hass)
    daily = _steady(38) + [6 * HOUR, 5.5 * HOUR]
    found = coord._freeze_rhythm(_record(daily))
    assert found["rule"] == RULE_LOGNORMAL
    assert found["trimmed"] > 5 * HOUR
    assert found["rhythm"] < 1.5 * HOUR
    assert coord.rule_label(found) == "40-Day Log-Normal Percentile"
    window = coord._freeze_window(_record(daily))
    assert window == pytest.approx(found["rhythm"] + coord._freeze_grace(found["rhythm"]))


async def test_a_device_reporting_faster_keeps_the_trimmed_maximum(
    hass: HomeAssistant,
):
    """Six-hour gaps for four weeks, then one-hour gaps for two: the
    Trimmed Maximum has forgotten the slow weeks, the Log-Normal
    Percentile has not, so the shorter is the Trimmed Maximum."""
    coord = await setup_coordinator(hass)
    daily = _steady(28, 6.0) + _steady(14, 1.0)
    found = coord._freeze_rhythm(_record(daily))
    assert found["rule"] == RULE_TRIMMED
    assert found["rhythm"] < 1.5 * HOUR
    assert coord.rule_label(found) == "14-Day Trimmed Maximum"


async def test_a_young_device_names_the_days_it_has(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    found = coord._freeze_rhythm(_record(_steady(9)))
    assert found["lognormal"] is None
    assert coord.rule_label(found) == "9-Day Trimmed Maximum"
    assert coord._freeze_rhythm(_record(_steady(3))) is None


async def test_a_reset_device_waits_28_new_days(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    daily = _steady(38) + [6 * HOUR, 5.5 * HOUR]
    found = coord._freeze_rhythm(_record(daily, 27))
    assert found["lognormal"] is None and found["rule"] == RULE_TRIMMED
    found = coord._freeze_rhythm(_record(daily, 28))
    assert found["rule"] == RULE_LOGNORMAL
    assert coord.rule_label(found) == "28-Day Log-Normal Percentile"


# ----------------------------------------------------------- the resets


def test_a_new_firmware_resets_the_count_and_the_first_sighting_does_not():
    record = _record(_steady(40))
    assert note_firmware(record, "1.0", 1_790_000_000.0)
    assert record[DEV_LOGNORMAL_DAYS] is None
    assert not note_firmware(record, "1.0", 1_790_000_100.0)
    assert record[DEV_LOGNORMAL_DAYS] is None
    assert note_firmware(record, "1.1", 1_790_000_200.0)
    assert record[DEV_LOGNORMAL_DAYS] == 0
    assert record[DEV_FIRMWARE_HISTORY][-1][0] == "1.1"


async def test_a_battery_replacement_resets_the_count(hass: HomeAssistant):
    coord = await setup_coordinator(hass)
    record = _record(_steady(40))
    record["battery_daily_value"] = [40.0, 39.0, 38.0]
    record["battery_value"] = 100.0
    coord._roll_battery(record)
    coord._roll_battery(record)
    assert record[DEV_LOGNORMAL_DAYS] == 0


async def test_a_re_pair_resets_the_count(hass: HomeAssistant):
    device, _entities = register_device(hass, "rp0", "Re-paired Device")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_LOGNORMAL_DAYS] = None
    coord._record_device_handled(device.id, "device_joined")
    assert record[DEV_LOGNORMAL_DAYS] == 0


async def test_the_fold_counts_days_and_lets_go_at_42(hass: HomeAssistant):
    device, _entities = register_device(hass, "fd0", "Folded Device")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = _steady(10)
    record[DEV_LOGNORMAL_DAYS] = 5
    record["today_max"] = HOUR
    await coord._on_midnight(None)
    assert record[DEV_LOGNORMAL_DAYS] == 6
    record[DEV_LOGNORMAL_DAYS] = 41
    record["today_max"] = HOUR
    await coord._on_midnight(None)
    assert record[DEV_LOGNORMAL_DAYS] is None
    record["today_max"] = HOUR
    await coord._on_midnight(None)
    assert record[DEV_LOGNORMAL_DAYS] is None


# ------------------------------------------- three slow days, and the button


def test_three_slow_days_are_a_new_habit_and_two_are_bad_days():
    from custom_components.device_sentinel.rhythm_rules import slowed_down
    base = _steady(40, 1.0)
    assert not slowed_down(base + [6 * HOUR, 6.5 * HOUR], 42)
    assert slowed_down(base + [6 * HOUR, 6.5 * HOUR, 5.5 * HOUR], 42)


def test_short_days_are_not_a_slowdown():
    from custom_components.device_sentinel.rhythm_rules import slowed_down
    base = _steady(40, 1.0)
    assert not slowed_down(base + [0.01 * HOUR] * 3, 42)


async def test_the_fold_resets_after_three_slow_days(hass: HomeAssistant):
    device, _entities = register_device(hass, "sl0", "Slowed Device")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = _steady(40, 1.0) + [6 * HOUR, 6.5 * HOUR]
    record[DEV_LOGNORMAL_DAYS] = None
    record["today_max"] = 5.5 * HOUR
    await coord._on_midnight(None)
    assert record[DEV_LOGNORMAL_DAYS] == 0
    found = coord._freeze_rhythm(record)
    assert found["rule"] == RULE_TRIMMED and found["lognormal"] is None


async def test_the_button_sets_the_trimmed_maximum(hass: HomeAssistant, hass_ws_client):
    device, _entities = register_device(hass, "bt0", "Button Device")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = _steady(38) + [6 * HOUR, 5.5 * HOUR]
    record[DEV_LOGNORMAL_DAYS] = None
    assert coord._freeze_rhythm(record)["rule"] == RULE_LOGNORMAL
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "device_sentinel/use_trimmed_maximum", "device_id": device.id})
    reply = await client.receive_json()
    assert reply["success"], reply
    assert record[DEV_LOGNORMAL_DAYS] == 0
    assert coord._freeze_rhythm(record)["rule"] == RULE_TRIMMED
    await client.send_json({"id": 2, "type": "device_sentinel/use_trimmed_maximum", "device_id": "no-such"})
    reply = await client.receive_json()
    assert reply["error"]["code"] == "not_found"


async def test_a_non_admin_cannot_press_it(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    device, _entities = register_device(hass, "bt1", "Guarded Device")
    coord = await setup_coordinator(hass)
    coord.data["devices"][device.id][DEV_LOGNORMAL_DAYS] = None
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json({"id": 1, "type": "device_sentinel/use_trimmed_maximum", "device_id": device.id})
    reply = await client.receive_json()
    assert reply["error"]["code"] == "unauthorized"
    assert coord.data["devices"][device.id][DEV_LOGNORMAL_DAYS] is None


# ------------------------------------------------------ the kept wait


async def test_the_wait_is_kept_and_replaced_when_its_inputs_change(hass: HomeAssistant, monkeypatch):
    device, _e = register_device(hass, "km0", "Kept Device")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = _steady(38) + [6 * HOUR, 5.5 * HOUR]
    record[DEV_LOGNORMAL_DAYS] = None
    calls = []
    real = coord._compute_freeze_rhythm
    monkeypatch.setattr(coord, "_compute_freeze_rhythm", lambda r: calls.append(1) or real(r))
    first = coord._freeze_window(record)
    for _ in range(50):
        assert coord._freeze_window(record) == first
    assert len(calls) == 1, "asked again with nothing changed: read from memory"
    # A reset changes the count: worked out again.
    coord.use_trimmed_maximum(device.id)
    assert coord._freeze_window(record) > first and len(calls) == 2
    # The fold appends a day: worked out again.
    record["today_max"] = HOUR
    await coord._on_midnight(None)
    coord._freeze_window(record)
    assert len(calls) == 3
    # A new list in place of the old (a load, a wipe): worked out again.
    record[DEV_DAILY_MAX] = list(record[DEV_DAILY_MAX])
    coord._freeze_window(record)
    assert len(calls) == 4


async def test_a_settings_change_replaces_the_kept_wait(hass: HomeAssistant):
    from custom_components.device_sentinel.const import CONF_FREEZE_DELTA_HIGH
    device, _e = register_device(hass, "km1", "Settings Device")
    coord = await setup_coordinator(hass)
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = _steady(40, 6.0)
    before = coord._freeze_window(record)
    hass.config_entries.async_update_entry(coord.entry, options={**coord.entry.options, CONF_FREEZE_DELTA_HIGH: 2})
    await hass.async_block_till_done()
    assert coord._freeze_window(record) != before
