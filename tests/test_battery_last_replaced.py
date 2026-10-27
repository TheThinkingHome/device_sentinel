# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_battery_last_replaced.py, Version: 0.27.10 (2026-10-27)

"""Battery Last Replaced and a person's answer to a detected one
(rules BAT-06, BAT-07).

A battery device's page shows the day. A detected replacement waits on
a Confirm Battery Replacement card and a Brief line until someone
confirms it, cancels it or gives the right day, and the battery history
follows the answer. One entry per device in the answers file holds what
the row says, written by the latest event (rule STOR-20).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.answers_store import ANSWERS_STORE_KEY
from custom_components.device_sentinel.const import (
    CONF_TRIM_DEVICES,
    DATA_DEVICES,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_DAILY_PREVIOUS,
    DEV_BATTERY_REPLACED_AT,
    DEV_BATTERY_REPLACED_PENDING,
    DEV_BATTERY_VALUE,
    DEV_LAST_ACTIVITY,
    DEV_LOGNORMAL_DAYS,
)
from custom_components.device_sentinel.daily_dates import (
    FAMILY_BATTERY,
    FAMILY_BATTERY_PREVIOUS,
    dates_for,
    set_dates,
)

from tests.helpers import register_device, setup_entry


async def _house(hass: HomeAssistant, name: str = "Hall Motion"):
    device, (entity_id,) = register_device(hass, "hall", name=name)
    registry = er.async_get(hass)
    registry.async_update_entity(entity_id, original_device_class="battery")
    registry.async_update_entity(entity_id, unit_of_measurement="%")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_BATTERY_VALUE] = 97.0
    return entry, coord, device, record


def _fold(coord, record, device_id, levels, first: date):
    """One midnight a day from `first`, the device heard each day."""
    for i, level in enumerate(levels):
        day = first + timedelta(days=i)
        coord._folding_day = day
        record[DEV_LAST_ACTIVITY] = dt_util.start_of_local_day(day).timestamp() + 3600
        record[DEV_BATTERY_VALUE] = float(level)
        coord._roll_battery(record, device_id)
    coord._folding_day = None


def _start() -> date:
    return dt_util.now().date() - timedelta(days=10)


async def _detected(hass: HomeAssistant, count=33):
    """Four days falling, then a new cell: the rise on day 5, confirmed
    at the midnight after day 6."""
    entry, coord, device, record = await _house(hass)
    record[DEV_LOGNORMAL_DAYS] = count
    _fold(coord, record, device.id, [40, 39, 38, 37, 100, 100], _start())
    return entry, coord, device, record


def _rise_day() -> str:
    return (_start() + timedelta(days=4)).isoformat()


def _card(coord):
    return next((c for c in coord.device_recommendations() if c["kind"] == "battery_confirm"), None)


async def test_a_detected_replacement_waits_for_a_person(hass: HomeAssistant):
    """Used at once, and waiting on a card in Simple and a Brief line
    naming the device and the day (rule BAT-06)."""
    _entry, coord, device, record = await _detected(hass)
    assert record[DEV_BATTERY_DAILY_PREVIOUS] == [40.0, 39.0, 38.0, 37.0]
    assert record[DEV_LOGNORMAL_DAYS] == 0
    view = coord.battery_replacement_view(device.id)
    assert view["waiting"] is True and view["how"] == "detected" and view["day"] == _rise_day()
    assert view["words"]["row"] == "Battery Last Replaced"
    card = _card(coord)
    assert card is not None and card["simple"] is True and card["title"] == "Confirm Battery Replacement"
    assert "Hall Motion, detected" in card["brief"]
    assert "Hall Motion, detected" in "\n".join(coord._recommendations_section())


async def test_confirm_keeps_the_detected_day(hass: HomeAssistant, hass_storage):
    _entry, coord, device, _record = await _detected(hass)
    coord.battery_answer(device.id, "confirm")
    assert _card(coord) is None
    view = coord.battery_replacement_view(device.id)
    assert view == {**view, "day": _rise_day(), "how": "confirmed", "waiting": False}
    await coord.async_flush_answers()
    saved = hass_storage[ANSWERS_STORE_KEY]["data"]["battery"][device.id]
    assert saved["day"] == _rise_day() and saved["how"] == "confirmed" and saved["waiting"] is False


async def test_confirm_is_refused_when_nothing_waits(hass: HomeAssistant):
    """A card left open in a second browser cannot overwrite a day the
    person entered (rule BAT-07)."""
    _entry, coord, device, _record = await _detected(hass)
    given = (_start() + timedelta(days=3)).isoformat()
    coord.battery_answer(device.id, "date", given)
    with pytest.raises(ValueError):
        coord.battery_answer(device.id, "confirm")
    assert coord.battery_replacement_view(device.id)["day"] == given


async def test_cancel_joins_the_history_and_leaves_the_count(hass: HomeAssistant):
    """The cell was never changed, so its history is one again, and the
    freeze rule's day count stands as it is and regrows as after any
    detection (rule BAT-07)."""
    _entry, coord, device, record = await _detected(hass)
    record[DEV_LOGNORMAL_DAYS] = 2
    coord.battery_answer(device.id, "cancel")
    assert record[DEV_BATTERY_DAILY_PREVIOUS] == []
    assert record[DEV_BATTERY_DAILY] == [40.0, 39.0, 38.0, 37.0, 100.0, 100.0]
    assert record[DEV_LOGNORMAL_DAYS] == 2
    assert record[DEV_BATTERY_REPLACED_AT] is None
    assert _card(coord) is None
    view = coord.battery_replacement_view(device.id)
    assert view["day"] is None and view["words"]["none"] == "No battery replacement yet"


async def test_cancelling_a_second_detection_keeps_the_first(hass: HomeAssistant):
    """Cancel returns the row to the replacement before, not to none
    (rule BAT-07)."""
    _entry, coord, device, record = await _detected(hass)
    coord.battery_answer(device.id, "confirm")
    first = coord.battery_replacement_view(device.id)["day"]
    stamp = record[DEV_BATTERY_REPLACED_AT]
    _fold(coord, record, device.id, [99, 40, 100, 100], _start() + timedelta(days=6))
    assert coord.battery_replacement_view(device.id)["waiting"] is True
    coord.battery_answer(device.id, "cancel")
    view = coord.battery_replacement_view(device.id)
    assert view["day"] == first and view["how"] == "confirmed" and view["waiting"] is False
    assert record[DEV_BATTERY_REPLACED_AT] == stamp


async def test_a_day_given_splits_the_history_there(hass: HomeAssistant):
    """Change date: the entries on and after the day belong to the cell
    in the device, and the answer is the person's own (rule BAT-07)."""
    _entry, coord, device, record = await _house(hass)
    today = dt_util.now().date()
    days = [today - timedelta(days=6 - i) for i in range(6)]
    record[DEV_BATTERY_DAILY] = [60.0, 59.0, 58.0, 99.0, 98.0, 97.0]
    set_dates(record, FAMILY_BATTERY, days)
    coord.battery_answer(device.id, "date", days[3].isoformat())
    assert record[DEV_BATTERY_DAILY_PREVIOUS] == [60.0, 59.0, 58.0]
    assert record[DEV_BATTERY_DAILY] == [99.0, 98.0, 97.0]
    assert dates_for(record, FAMILY_BATTERY, 3, today) == days[3:]
    assert dates_for(record, FAMILY_BATTERY_PREVIOUS, 3, today) == days[:3]
    view = coord.battery_replacement_view(device.id)
    assert view["day"] == days[3].isoformat() and view["how"] == "entered"
    # A day older than anything kept gives the whole history to the cell.
    coord.battery_answer(device.id, "date", (today - timedelta(days=400)).isoformat())
    assert record[DEV_BATTERY_DAILY_PREVIOUS] == []
    assert len(record[DEV_BATTERY_DAILY]) == 6


async def test_a_day_given_stands_however_old(hass: HomeAssistant):
    """A day entered long before the detected one is the row's day:
    the latest event wins, nothing is compared (rule BAT-07)."""
    _entry, coord, device, _record = await _detected(hass)
    given = (dt_util.now().date() - timedelta(days=200)).isoformat()
    coord.battery_answer(device.id, "date", given)
    view = coord.battery_replacement_view(device.id)
    assert view["day"] == given and view["how"] == "entered" and view["waiting"] is False
    assert _card(coord) is None


async def test_a_day_given_while_a_rise_waits_ends_it(hass: HomeAssistant):
    """A day given the morning after a cell is swapped, its rise still
    waiting for a second night: the next midnight confirms nothing over
    the person's answer and the run does not stop (rule BAT-06)."""
    _entry, coord, device, record = await _house(hass)
    record[DEV_LOGNORMAL_DAYS] = 20
    _fold(coord, record, device.id, [40, 39, 38, 100], _start())
    assert record[DEV_BATTERY_REPLACED_PENDING] is not None
    given = (_start() + timedelta(days=3)).isoformat()
    coord.battery_answer(device.id, "date", given)
    assert record[DEV_BATTERY_REPLACED_PENDING] is None
    _fold(coord, record, device.id, [100], _start() + timedelta(days=4))
    assert _card(coord) is None
    assert record[DEV_LOGNORMAL_DAYS] == 20
    assert coord.battery_replacement_view(device.id)["day"] == given


async def test_a_day_entered_before_the_new_level_stands(hass: HomeAssistant):
    """The person gives the day the evening they swap the cell; the
    device reports the new level later and the rise is confirmed two
    nights on. That is the same replacement: no card, and the row keeps
    the person's day (rule BAT-07)."""
    _entry, coord, device, record = await _house(hass)
    _fold(coord, record, device.id, [40, 39, 38], _start())
    given = (_start() + timedelta(days=2)).isoformat()
    coord.battery_answer(device.id, "date", given)
    _fold(coord, record, device.id, [38, 100, 100], _start() + timedelta(days=3))
    assert record[DEV_BATTERY_REPLACED_AT] is not None
    assert _card(coord) is None
    view = coord.battery_replacement_view(device.id)
    assert view["day"] == given and view["how"] == "entered"


async def test_a_confirmed_day_does_not_move_after_the_history_days(hass: HomeAssistant):
    """Once stored, the day is never worked out again, so a cell that
    outlasts the History days keeps its day (rule BAT-07)."""
    _entry, coord, device, record = await _detected(hass)
    coord.battery_answer(device.id, "confirm")
    record[DEV_BATTERY_DAILY] = [90.0] * coord.retention_days
    assert coord.battery_replacement_view(device.id)["day"] == _rise_day()


async def test_a_replacement_detected_before_0_26_7_counts_as_confirmed(hass: HomeAssistant):
    """No card at the upgrade; the day is the new cell's first kept day,
    stored once at the start (rule BAT-07)."""
    _entry, coord, device, record = await _house(hass)
    today = dt_util.now().date()
    days = [today - timedelta(days=4 - i) for i in range(4)]
    record[DEV_BATTERY_DAILY] = [99.0, 99.0, 98.5, 98.5]
    set_dates(record, FAMILY_BATTERY, days)
    record[DEV_BATTERY_REPLACED_AT] = dt_util.as_utc(
        dt_util.start_of_local_day(days[0] + timedelta(days=2)) + timedelta(minutes=5)
    ).isoformat()
    assert _card(coord) is None
    view = coord.battery_replacement_view(device.id)
    assert view["day"] == days[0].isoformat() and view["how"] == "confirmed" and view["waiting"] is False
    coord._settle_battery_entries()
    assert coord._battery_answers()[device.id]["day"] == days[0].isoformat()


async def test_a_detection_by_0_26_6_after_a_downgrade_is_dated_once(hass: HomeAssistant):
    """A stamp no entry carries, written by an older release, replaces an
    older answer with the new cell's first day (rule STOR-19)."""
    _entry, coord, device, record = await _house(hass)
    old = (dt_util.now().date() - timedelta(days=90)).isoformat()
    coord._battery_answers()[device.id] = {"day": old, "how": "confirmed", "stamp": "2026-07-01T05:00:00+00:00",
                                            "waiting": False, "history": []}
    today = dt_util.now().date()
    days = [today - timedelta(days=3 - i) for i in range(3)]
    record[DEV_BATTERY_DAILY] = [100.0, 100.0, 99.5]
    set_dates(record, FAMILY_BATTERY, days)
    record[DEV_BATTERY_REPLACED_AT] = dt_util.utcnow().isoformat()
    view = coord.battery_replacement_view(device.id)
    assert view["day"] == days[0].isoformat() and view["how"] == "confirmed"


async def test_a_wired_device_never_waits_on_the_card(hass: HomeAssistant):
    """A device answered as wired that still reports a rising level is
    not listed, because there is no row to answer it from (rule BAT-07)."""
    _entry, coord, device, _record = await _detected(hass)
    coord.page_set_power(device.id, "Mains Powered", None)
    assert _card(coord) is None
    assert coord.battery_replacement_view(device.id) is None


async def test_a_future_day_and_nonsense_are_refused(hass: HomeAssistant):
    _entry, coord, device, _record = await _house(hass)
    with pytest.raises(ValueError):
        coord.battery_answer(device.id, "date", (dt_util.now().date() + timedelta(days=2)).isoformat())
    with pytest.raises(ValueError):
        coord.battery_answer(device.id, "date", "soon")
    with pytest.raises(ValueError):
        coord.battery_answer(device.id, "cancel")


async def test_a_rechargeable_cell_reads_charged(hass: HomeAssistant):
    _entry, coord, device, _record = await _detected(hass)
    coord.page_set_power(device.id, "Rechargeable", 1)
    words = coord.battery_replacement_view(device.id)["words"]
    assert words["row"] == "Battery Last Charged" and words["card"] == "Confirm Battery Charge"
    assert _card(coord)["title"] == "Confirm Battery Charge"


async def test_entries_survive_a_restart_and_a_bad_one_is_dropped(hass: HomeAssistant, hass_storage):
    entry, coord, device, _record = await _house(hass)
    given = date(2026, 10, 1).isoformat()
    coord.battery_answer(device.id, "date", given)
    await coord.async_flush_answers()
    data = hass_storage[ANSWERS_STORE_KEY]["data"]
    data["battery"]["someone"] = {"day": "never", "how": "confirmed"}
    data["battery"]["another"] = {"day": "2026-10-01", "how": "detected", "waiting": "yes", "history": [{"day": "x"}]}
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    answers = coord._battery_answers()
    assert answers[device.id]["day"] == given and answers[device.id]["how"] == "entered"
    assert "someone" not in answers
    # Malformed, and with no device behind it: dropped at the start.
    assert "another" not in answers


async def test_the_ws_command_is_admin_only(
    hass: HomeAssistant, hass_ws_client, hass_read_only_access_token
):
    _entry, _coord, device, _record = await _detected(hass)
    reader = await hass_ws_client(hass, hass_read_only_access_token)
    await reader.send_json({"id": 1, "type": "device_sentinel/device_battery", "device_id": device.id, "action": "confirm"})
    assert not (await reader.receive_json())["success"]
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "device_sentinel/device_battery", "device_id": device.id, "action": "confirm"})
    assert (await client.receive_json())["success"]


async def test_two_cancels_go_back_through_the_history(hass: HomeAssistant):
    """A confirmed replacement, then two false rises left unanswered:
    two Cancels come back to the confirmed one (rule BAT-07)."""
    _entry, coord, device, record = await _detected(hass)
    coord.battery_answer(device.id, "confirm")
    first = coord.battery_replacement_view(device.id)["day"]
    _fold(coord, record, device.id, [99, 40, 100, 100], _start() + timedelta(days=6))
    _fold(coord, record, device.id, [99, 40, 100, 100], _start() + timedelta(days=10))
    coord.battery_answer(device.id, "cancel")
    assert coord.battery_replacement_view(device.id)["waiting"] is True
    coord.battery_answer(device.id, "cancel")
    view = coord.battery_replacement_view(device.id)
    assert view["day"] == first and view["how"] == "confirmed" and view["waiting"] is False


async def test_an_entry_goes_with_its_device(hass: HomeAssistant):
    """An excluded device's record goes at the fold; its entry goes at
    the next start or midnight, as power and type answers do
    (rule STOR-20)."""
    _entry, coord, device, _record = await _detected(hass)
    del coord.data[DATA_DEVICES][device.id]
    coord._settle_battery_entries()
    assert device.id not in coord._battery_answers()


async def test_a_main_file_older_than_the_entry_shows_no_card(hass: HomeAssistant):
    """The main file restored from a copy made before the detection: the
    record knows no replacement, so nothing waits and the replacement
    before stands (rule STOR-20)."""
    _entry, coord, device, record = await _detected(hass)
    record[DEV_BATTERY_REPLACED_AT] = None
    assert _card(coord) is None
    assert coord.battery_replacement_view(device.id)["day"] is None
    with pytest.raises(ValueError):
        coord.battery_answer(device.id, "cancel")


async def test_nothing_is_taken_while_stopping(hass: HomeAssistant):
    """A click as Home Assistant stops would reach the answers file and
    not the main file, so nothing is taken (rule STOR-20)."""
    _entry, coord, device, _record = await _detected(hass)
    coord._stopped = True
    try:
        with pytest.raises(ValueError):
            coord.battery_answer(device.id, "cancel")
    finally:
        coord._stopped = False


async def test_an_old_detection_whose_cell_outlasts_the_history_reads_the_old_cells_end(hass: HomeAssistant):
    """The new cell's first entry trimmed away: the day after the old
    cell's last dated entry, not the confirming stamp minus a day
    (rule BAT-07)."""
    _entry, coord, device, record = await _house(hass)
    keep = coord.retention_days
    today = dt_util.now().date()
    new_days = [today - timedelta(days=keep - i) for i in range(keep)]
    record[DEV_BATTERY_DAILY] = [90.0] * keep
    set_dates(record, FAMILY_BATTERY, new_days)
    old_last = new_days[0] - timedelta(days=20)
    record[DEV_BATTERY_DAILY_PREVIOUS] = [20.0, 19.0]
    set_dates(record, FAMILY_BATTERY_PREVIOUS, [old_last - timedelta(days=1), old_last])
    record[DEV_BATTERY_REPLACED_AT] = dt_util.as_utc(
        dt_util.start_of_local_day(old_last + timedelta(days=3))
    ).isoformat()
    assert coord.battery_replacement_view(device.id)["day"] == (old_last + timedelta(days=1)).isoformat()


async def test_a_day_entered_before_the_new_level_keeps_the_old_cells_history(hass: HomeAssistant):
    """The person's day set the old cell's history aside; the rise
    confirmed after it is the same replacement and adds to that history
    rather than replacing it (rule BAT-08)."""
    _entry, coord, device, record = await _house(hass)
    _fold(coord, record, device.id, [40, 39, 38], _start())
    coord.battery_answer(device.id, "date", (_start() + timedelta(days=3)).isoformat())
    assert record[DEV_BATTERY_DAILY_PREVIOUS] == [40.0, 39.0, 38.0]
    _fold(coord, record, device.id, [37, 100, 100], _start() + timedelta(days=3))
    assert record[DEV_BATTERY_DAILY_PREVIOUS] == [40.0, 39.0, 38.0, 37.0]
    previous_days = dates_for(record, FAMILY_BATTERY_PREVIOUS, 4, dt_util.now().date())
    assert previous_days == [_start() + timedelta(days=i) for i in range(4)]


async def test_a_trimmed_device_starts_with_no_replacement(hass: HomeAssistant):
    """A trim deletes the device's history; its entry goes with it, so a
    fresh record reads no replacement, not an earlier one (rule CFG-10)."""
    _entry, coord, device, record = await _detected(hass)
    coord.battery_answer(device.id, "confirm")
    await coord._apply_trim_selection({**coord.entry.options, CONF_TRIM_DEVICES: [device.id]})
    await hass.async_block_till_done()
    assert device.id not in coord._battery_answers()
