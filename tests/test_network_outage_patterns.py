# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_network_outage_patterns.py, Version: 0.28.7 (2026-11-09)

"""A network that goes down at the same time again and again (rule DASH-18).

The pattern is told in one sentence, shown as a recommendation and over
the outages it covers. A person can mark it expected: its outages stay
listed, marked expected, and stop being counted. An outage at another
time, one that runs well past its usual length or does not end, is not
expected, and a pattern that stops for 14 days is forgotten.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_EXPECTED_OUTAGES,
    SYS_BRIDGE_DOWN,
    SYS_BRIDGE_UP,
)
from tests.helpers import setup_coordinator

TZ = "America/Guayaquil"


@pytest.fixture
async def _guayaquil(hass: HomeAssistant, freezer):
    await hass.config.async_set_time_zone(TZ)
    # Nov 9, 2026, 9:00 AM in Guayaquil.
    freezer.move_to("2026-11-09T14:00:00+00:00")


def _local(day: int, hour: int, minute: int, month: int = 11) -> float:
    return datetime(2026, month, day, hour, minute, tzinfo=dt_util.get_time_zone(TZ)).timestamp()


def _zha(hass):
    entry = MockConfigEntry(domain="zha", title="ZHA")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("zha", "00:11")}, name="Office Motion"
    )
    er.async_get(hass).async_get_or_create("sensor", "zha", "00:11-x", device_id=device.id, config_entry=entry)
    return device


def _outage(coordinator, start: float, length: float | None, scope: str = "zha") -> None:
    coordinator._record_system_event(SYS_BRIDGE_DOWN, scope=scope, when=start)
    if length is not None:
        coordinator._record_system_event(SYS_BRIDGE_UP, scope=scope, when=start + length, duration=length, devices=12)


async def _house(hass, nights=((10, 29), (10, 30), (10, 31), (11, 1), (11, 2), (11, 3)), length=240.0):
    _zha(hass)
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    for month, day in nights:
        _outage(coordinator, _local(day, 3, 40, month), length)
    return coordinator


@pytest.mark.usefixtures("_guayaquil")
async def test_six_nights_in_a_row_make_one_sentence(hass: HomeAssistant):
    coordinator = await _house(hass)
    page = coordinator.dashboard_network("zha")
    assert len(page["patterns"]) == 1
    pattern = page["patterns"][0]
    assert pattern["sentence"] == "Down 6 nights in a row at 3:40 AM, Oct 29 to Nov 3."
    assert pattern["question"].startswith("Is this expected? ")
    assert pattern["usual"] == 240.0
    # The recommendation and the outage list share the one sentence.
    assert [c["sentence"] for c in page["cards"]] == [pattern["sentence"]]
    assert sorted(pattern["outages"]) == list(range(6))
    # The logbook opens the newest night, ten minutes either side.
    book = page["cards"][0]["logbook"]
    assert dt_util.parse_datetime(book["start"]).timestamp() == _local(3, 3, 30)
    assert dt_util.parse_datetime(book["end"]).timestamp() == _local(3, 3, 54)


@pytest.mark.usefixtures("_guayaquil")
async def test_two_nights_are_not_a_pattern(hass: HomeAssistant):
    coordinator = await _house(hass, nights=((11, 2), (11, 3)))
    page = coordinator.dashboard_network("zha")
    assert page["patterns"] == [] and page["cards"] == []


@pytest.mark.usefixtures("_guayaquil")
async def test_two_outages_one_night_count_one_night(hass: HomeAssistant):
    """Guard: three outages on two nights are not three nights."""
    coordinator = await _house(hass, nights=((11, 2), (11, 3)))
    _outage(coordinator, _local(3, 3, 50), 120.0)
    assert coordinator.dashboard_network("zha")["patterns"] == []


@pytest.mark.usefixtures("_guayaquil")
async def test_nights_apart_say_times(hass: HomeAssistant):
    coordinator = await _house(hass, nights=((10, 20), (10, 27), (11, 3)))
    sentence = coordinator.dashboard_network("zha")["patterns"][0]["sentence"]
    assert sentence == "Down 3 times at about 3:40 AM in the last 30 days, most recently Nov 3."


@pytest.mark.usefixtures("_guayaquil")
async def test_a_pattern_across_midnight_is_one(hass: HomeAssistant):
    """11:55 PM and 12:05 AM are ten minutes apart."""
    _zha(hass)
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    _outage(coordinator, _local(1, 23, 55), 60.0)
    _outage(coordinator, _local(3, 0, 5), 60.0)
    _outage(coordinator, _local(4, 23, 58), 60.0)
    patterns = coordinator.dashboard_network("zha")["patterns"]
    assert len(patterns) == 1 and patterns[0]["times"] == 3


@pytest.mark.usefixtures("_guayaquil")
async def test_daytime_outages_say_days(hass: HomeAssistant):
    coordinator = await _house(hass, nights=())
    for day in (1, 2, 3):
        _outage(coordinator, _local(day, 14, 0), 60.0)
    assert "3 days in a row at 2:00 PM" in coordinator.dashboard_network("zha")["patterns"][0]["sentence"]


@pytest.mark.usefixtures("_guayaquil")
async def test_marked_expected_its_outages_stay_listed_but_uncounted(hass: HomeAssistant):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    page = coordinator.dashboard_network("zha")
    assert page["cards"] == []
    assert all(o["expected"] for o in page["outages"])
    assert page["patterns"][0]["expected"] is True
    row = coordinator.dashboard_networks()[0]
    assert row["outages"] == 0 and row["expected"] == 6
    listed = coordinator.expected_list()
    assert [(r["network"], r["time"], r["usual"]) for r in listed] == [("zha", "3:40 AM", "4 minutes")]


@pytest.mark.usefixtures("_guayaquil")
async def test_the_next_night_of_the_pattern_is_expected(hass: HomeAssistant, freezer):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    _outage(coordinator, _local(10, 3, 47), 300.0)
    freezer.move_to("2026-11-10T14:00:00+00:00")
    page = coordinator.dashboard_network("zha")
    assert page["outages"][0]["expected"] is True
    assert page["cards"] == []


@pytest.mark.usefixtures("_guayaquil")
async def test_an_outage_at_another_time_is_not_expected(hass: HomeAssistant, freezer):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    _outage(coordinator, _local(10, 4, 10), 240.0)
    freezer.move_to("2026-11-10T14:00:00+00:00")
    page = coordinator.dashboard_network("zha")
    assert page["outages"][0]["expected"] is False
    assert coordinator.dashboard_networks()[0]["outages"] == 1


@pytest.mark.usefixtures("_guayaquil")
async def test_an_outage_twice_as_long_is_told(hass: HomeAssistant, freezer):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    _outage(coordinator, _local(10, 3, 40), 3600.0)
    freezer.move_to("2026-11-10T14:00:00+00:00")
    page = coordinator.dashboard_network("zha")
    assert page["outages"][0]["expected"] is False
    longer = [c for c in page["cards"] if c["kind"] == "longer"]
    assert len(longer) == 1
    assert longer[0]["sentence"] == "The outage you expect at 3:40 AM ran 60 minutes on Nov 10, against its usual 4 minutes."


@pytest.mark.usefixtures("_guayaquil")
async def test_an_expected_outage_that_does_not_end_is_told(hass: HomeAssistant, freezer):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    _outage(coordinator, _local(10, 3, 40), None)
    freezer.move_to("2026-11-10T09:00:00+00:00")  # 4:00 AM, 20 minutes in
    page = coordinator.dashboard_network("zha")
    assert page["outages"][0]["open"] is True, page["outages"][0]
    assert page["outages"][0]["expected"] is False
    assert any(c["sentence"].startswith("The outage you expect at 3:40 AM has not ended since 3:40 AM")
               for c in page["cards"] if c["kind"] == "longer")
    assert page["up"]["back_since"] is None


@pytest.mark.usefixtures("_guayaquil")
async def test_an_expected_outage_still_within_its_length_is_expected(hass: HomeAssistant):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    row = coordinator.expected_for("zha")[0]
    outage = {"went_down": dt_util.utc_from_timestamp(_local(10, 3, 40)).isoformat(), "duration": None, "open": True}
    assert coordinator._outage_fits(row, outage, _local(10, 3, 44)) is True
    assert coordinator._outage_fits(row, outage, _local(10, 4, 40)) is False


@pytest.mark.usefixtures("_guayaquil")
async def test_a_pattern_quiet_for_14_days_is_forgotten(hass: HomeAssistant, freezer):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    freezer.move_to("2026-11-23T14:00:00+00:00")
    coordinator.dashboard_network("zha")
    assert coordinator.expected_for("zha")
    freezer.move_to("2026-11-24T14:00:00+00:00")
    coordinator.dashboard_network("zha")
    assert coordinator.expected_for("zha") == []
    assert coordinator.data[DATA_EXPECTED_OUTAGES] == []


@pytest.mark.usefixtures("_guayaquil")
async def test_stop_expecting_brings_the_card_back(hass: HomeAssistant):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    coordinator.set_outage_expected("zha", 225, False)
    assert coordinator.expected_for("zha") == []
    assert len(coordinator.dashboard_network("zha")["cards"]) == 1


@pytest.mark.usefixtures("_guayaquil")
async def test_only_a_real_pattern_can_be_expected(hass: HomeAssistant):
    coordinator = await _house(hass)
    with pytest.raises(ValueError):
        coordinator.set_outage_expected("zha", 600, True)
    with pytest.raises(ValueError):
        coordinator.set_outage_expected("matter", 220, True)
    with pytest.raises(ValueError):
        coordinator.set_outage_expected("zha", 1440, True)
    assert coordinator.expected_for("zha") == []


@pytest.mark.usefixtures("_guayaquil")
async def test_a_damaged_row_is_read_as_nothing(hass: HomeAssistant):
    coordinator = await _house(hass)
    coordinator.data[DATA_EXPECTED_OUTAGES] = [
        "x", {"network": "zha"}, {"network": "zha", "minute": True, "set_at": 1.0},
        {"network": "zha", "minute": 220, "set_at": "soon"}, {"network": 4, "minute": 220, "set_at": 1.0},
    ]
    page = coordinator.dashboard_network("zha")
    assert len(page["cards"]) == 1
    assert coordinator.expected_list() == []


@pytest.mark.usefixtures("_guayaquil")
async def test_the_command_marks_and_unmarks(hass: HomeAssistant, hass_ws_client):
    coordinator = await _house(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "device_sentinel/network_expected", "key": "zha", "minute": 220, "on": True})
    reply = await client.receive_json()
    assert reply["success"], reply
    await client.send_json_auto_id({"type": "device_sentinel/integrations"})
    reply = await client.receive_json()
    assert [r["time"] for r in reply["result"]["expected"]] == ["3:40 AM"]
    await client.send_json_auto_id({"type": "device_sentinel/network_expected", "key": "zha", "minute": 9999, "on": True})
    reply = await client.receive_json()
    assert not reply["success"]
    await client.send_json_auto_id({"type": "device_sentinel/network_expected", "key": "zha", "minute": 220, "on": False})
    reply = await client.receive_json()
    assert reply["success"] and coordinator.expected_for("zha") == []


async def test_the_command_is_for_administrators(hass: HomeAssistant, hass_ws_client, hass_read_only_access_token):
    await setup_coordinator(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": "device_sentinel/network_expected", "key": "zha", "minute": 220, "on": True})
    reply = await client.receive_json()
    assert reply["error"]["code"] == "unauthorized"


@pytest.mark.usefixtures("_guayaquil")
async def test_the_brief_says_an_expected_return_was_expected(hass: HomeAssistant):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    # Marked before the night told, so its length is judged.
    coordinator.data[DATA_EXPECTED_OUTAGES][0]["set_at"] = _local(1, 0, 0)
    row = {"kind": SYS_BRIDGE_UP, "scope": "zha", "when": _local(3, 3, 44), "duration": 240.0, "devices": 12}
    assert coordinator._system_event_sentence(row).endswith(" It was expected.")
    assert coordinator._system_event_phrase(row).endswith(", as expected")
    other = {**row, "when": _local(3, 9, 44)}
    assert "expected" not in coordinator._system_event_sentence(other)
    longer = {**row, "duration": 7200.0, "when": _local(3, 5, 40)}
    assert "expected" not in coordinator._system_event_sentence(longer)


def test_a_damaged_expected_row_is_found_by_the_storage_check():
    from custom_components.device_sentinel.normalise import check_storage, damaged_rows

    good = {"network": "zha", "minute": 220, "length": 240.0, "set_at": 1793000000.0}
    unknown = {"network": "zha", "minute": 220, "length": None, "set_at": 1793000000.0}
    bad = {"network": "zha", "minute": "3:40", "length": 240.0, "set_at": 1793000000.0}
    data = {DATA_EXPECTED_OUTAGES: [good, unknown, bad]}
    assert damaged_rows(data) == {DATA_EXPECTED_OUTAGES: [2]}
    assert any(fault[0].startswith(DATA_EXPECTED_OUTAGES) for fault in check_storage(data))


@pytest.mark.usefixtures("_guayaquil")
async def test_expected_outages_are_kept_in_storage_and_diagnostics(hass: HomeAssistant):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    saved = coordinator._data_to_save()
    assert saved[DATA_EXPECTED_OUTAGES][0]["minute"] == 220
    from custom_components.device_sentinel.diagnostics import async_get_config_entry_diagnostics

    found = await async_get_config_entry_diagnostics(hass, coordinator.entry)
    text = repr(found)
    assert "expected_outages" in text


@pytest.mark.usefixtures("_guayaquil")
async def test_a_network_that_drops_at_random_has_no_pattern(hass: HomeAssistant):
    """Three outages in one half hour among thirty at random times is
    chance, not a schedule."""
    coordinator = await _house(hass, nights=())
    times = [(d, (d * 197) % 1440) for d in range(1, 31)]
    for index, (day, minute) in enumerate(times):
        month, mday = (10, day + 9) if day <= 22 else (11, day - 22)
        _outage(coordinator, _local(mday, minute // 60, minute % 60, month), 60.0)
    for mday in (5, 6, 7):
        _outage(coordinator, _local(mday, 14, 2), 60.0)
    assert coordinator.dashboard_network("zha")["patterns"] == []


@pytest.mark.usefixtures("_guayaquil")
async def test_a_pattern_keeps_only_outages_near_its_time(hass: HomeAssistant):
    """3:00, 3:01, 3:15 and 3:30: the 3:30 is not part of a 3:08 pattern,
    so marking it expected clears the card."""
    coordinator = await _house(hass, nights=())
    for day, minute in ((1, 0), (2, 1), (3, 15), (4, 30)):
        _outage(coordinator, _local(day, 3, minute), 120.0)
    pattern = coordinator.dashboard_network("zha")["patterns"][0]
    assert pattern["times"] == 3
    coordinator.set_outage_expected("zha", pattern["minute"], True)
    assert coordinator.dashboard_network("zha")["cards"] == []


@pytest.mark.usefixtures("_guayaquil")
async def test_either_side_of_midnight_is_one_night(hass: HomeAssistant):
    coordinator = await _house(hass, nights=())
    _outage(coordinator, _local(2, 23, 58), 60.0)
    _outage(coordinator, _local(3, 0, 3), 60.0)
    _outage(coordinator, _local(3, 23, 59), 60.0)
    assert coordinator.dashboard_network("zha")["patterns"] == []
    _outage(coordinator, _local(5, 0, 1), 60.0)
    pattern = coordinator.dashboard_network("zha")["patterns"][0]
    assert pattern["times"] == 3
    assert pattern["sentence"] == "Down 3 nights in a row at 12:00 AM, Nov 3 to Nov 5."


@pytest.mark.usefixtures("_guayaquil")
async def test_a_long_run_is_told_once_and_marking_again_never_hides_it(hass: HomeAssistant, freezer):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    first = coordinator.expected_for("zha")[0]["set_at"]
    _outage(coordinator, _local(10, 3, 40), 3600.0)
    freezer.move_to("2026-11-10T14:00:00+00:00")
    page = coordinator.dashboard_network("zha")
    assert [c["kind"] for c in page["cards"]] == ["longer"]
    assert page["patterns"][0]["expected"] is True
    coordinator.set_outage_expected("zha", 220, True)
    assert coordinator.expected_for("zha")[0]["set_at"] == first
    page = coordinator.dashboard_network("zha")
    assert page["outages"][0]["expected"] is False
    assert [c["kind"] for c in page["cards"]] == ["longer"]


@pytest.mark.usefixtures("_guayaquil")
async def test_the_midnight_fold_forgets_without_a_page_opened(hass: HomeAssistant, freezer):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    freezer.move_to("2026-11-24T05:00:00+00:00")
    await coordinator._on_midnight(None)
    assert coordinator.expected_for("zha") == []
    row = {"kind": SYS_BRIDGE_UP, "scope": "zha", "when": _local(24, 3, 46), "duration": 240.0}
    assert "expected" not in coordinator._system_event_sentence(row)


@pytest.mark.usefixtures("_guayaquil")
async def test_in_short_says_an_expected_bridge_outage_was_expected(hass: HomeAssistant):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    coordinator.data[DATA_EXPECTED_OUTAGES][0]["set_at"] = _local(1, 0, 0)
    rows = [{"kind": SYS_BRIDGE_UP, "scope": "zha", "when": _local(3, 3, 45), "duration": 300.0}]
    said = coordinator._quiet_run_sentences(rows)
    assert said and said[-1].endswith(" It was expected."), said
    rows = [{"kind": SYS_BRIDGE_UP, "scope": "zha", "when": _local(3, 9, 50), "duration": 600.0}]
    assert not any("expected" in s for s in coordinator._quiet_run_sentences(rows))


@pytest.mark.usefixtures("_guayaquil")
async def test_stop_expecting_works_for_a_network_since_removed(hass: HomeAssistant):
    coordinator = await _house(hass)
    coordinator.data[DATA_EXPECTED_OUTAGES] = [{"network": "z2m", "minute": 220, "length": 240.0, "set_at": _local(8, 0, 0)}]
    coordinator.set_outage_expected("z2m", 220, False)
    assert coordinator.data[DATA_EXPECTED_OUTAGES] == []


@pytest.mark.usefixtures("_guayaquil")
async def test_the_logbook_words_are_in_the_houses_time(hass: HomeAssistant):
    coordinator = await _house(hass)
    book = coordinator.dashboard_network("zha")["cards"][0]["logbook"]
    assert book["words"] == "Nov 3, 3:30 AM to 3:54 AM"
    across = coordinator._logbook(_local(3, 23, 55), _local(4, 0, 10))
    assert across["words"] == "Nov 3, 11:55 PM to Nov 4, 12:10 AM"


@pytest.mark.usefixtures("_guayaquil")
async def test_a_long_failure_inside_the_pattern_is_never_expected(hass: HomeAssistant):
    """Three 4-minute restarts and one 8-hour failure at the same time:
    marking the pattern expected leaves the failure an outage."""
    coordinator = await _house(hass, nights=((11, 1), (11, 2), (11, 3)))
    _outage(coordinator, _local(4, 3, 40), 8 * 3600.0)
    coordinator.set_outage_expected("zha", 220, True)
    page = coordinator.dashboard_network("zha")
    failure = next(o for o in page["outages"] if o["duration"] == 8 * 3600.0)
    assert failure["expected"] is False
    assert coordinator.dashboard_networks()[0]["outages"] == 1
    assert page["cards"] == []


@pytest.mark.usefixtures("_guayaquil")
async def test_stop_then_yes_never_hides_a_long_run_since(hass: HomeAssistant, freezer):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    _outage(coordinator, _local(10, 3, 40), 3 * 3600.0)
    freezer.move_to("2026-11-10T14:00:00+00:00")
    coordinator.set_outage_expected("zha", 220, False)
    coordinator.set_outage_expected("zha", 220, True)
    page = coordinator.dashboard_network("zha")
    assert page["outages"][0]["expected"] is False
    assert coordinator.dashboard_networks()[0]["outages"] == 1


@pytest.mark.usefixtures("_guayaquil")
async def test_a_pattern_with_no_recorded_length_cannot_be_expected(hass: HomeAssistant):
    coordinator = await _house(hass, nights=())
    for day in (1, 2, 3):
        coordinator._record_system_event(SYS_BRIDGE_DOWN, scope="zha", when=_local(day, 3, 40))
        coordinator._record_system_event(SYS_BRIDGE_UP, scope="zha", when=_local(day, 3, 44), devices=12)
    page = coordinator.dashboard_network("zha")
    assert page["patterns"] and page["patterns"][0]["usual"] is None
    with pytest.raises(ValueError):
        coordinator.set_outage_expected("zha", 220, True)
    coordinator.data[DATA_EXPECTED_OUTAGES] = [{"network": "zha", "minute": 220, "length": None, "set_at": _local(8, 0, 0)}]
    assert not any(o["expected"] for o in coordinator.dashboard_network("zha")["outages"])


@pytest.mark.usefixtures("_guayaquil")
async def test_in_short_tells_the_unexpected_outage_over_a_longer_expected_one(hass: HomeAssistant):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    coordinator.data[DATA_EXPECTED_OUTAGES][0]["set_at"] = _local(1, 0, 0)
    rows = [{"kind": SYS_BRIDGE_UP, "scope": "zha", "when": _local(3, 3, 46), "duration": 360.0},
            {"kind": SYS_BRIDGE_UP, "scope": "zha", "when": _local(3, 14, 5), "duration": 300.0}]
    said = coordinator._quiet_run_sentences(rows)
    assert len(said) == 1 and "expected" not in said[0] and "2:00 PM" in said[0], said


@pytest.mark.usefixtures("_guayaquil")
async def test_a_removed_integration_is_never_called_expected(hass: HomeAssistant):
    from custom_components.device_sentinel.const import SYS_INTEGRATION_UP
    from custom_components.device_sentinel.outage_detail import REMOVED, make_detail

    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    coordinator.data[DATA_EXPECTED_OUTAGES][0]["set_at"] = _local(1, 0, 0)
    row = {"kind": SYS_INTEGRATION_UP, "scope": "zha", "when": _local(3, 3, 44), "duration": 240.0,
           "detail": make_detail("entry", None, REMOVED)}
    assert coordinator.system_row_expected(row) is False


@pytest.mark.usefixtures("_guayaquil")
async def test_the_networks_tab_shows_the_last_outage_not_expected(hass: HomeAssistant, freezer):
    coordinator = await _house(hass)
    _outage(coordinator, _local(5, 14, 0), 300.0)
    coordinator.set_outage_expected("zha", 220, True)
    _outage(coordinator, _local(10, 3, 41), 240.0)
    freezer.move_to("2026-11-10T14:00:00+00:00")
    row = coordinator.dashboard_networks()[0]
    assert row["last_outage"]["expected"] is False
    assert dt_util.parse_datetime(row["last_outage"]["went_down"]).timestamp() == _local(5, 14, 0)


@pytest.mark.usefixtures("_guayaquil")
async def test_only_expected_outages_show_the_newest_marked(hass: HomeAssistant):
    coordinator = await _house(hass)
    coordinator.set_outage_expected("zha", 220, True)
    row = coordinator.dashboard_networks()[0]
    assert row["last_outage"]["expected"] is True


@pytest.mark.usefixtures("_guayaquil")
async def test_zigbee2mqtts_expected_time_never_covers_the_broker(hass: HomeAssistant):
    from custom_components.device_sentinel.const import SYS_BROKER_UP

    coordinator = await _house(hass)
    coordinator.data[DATA_EXPECTED_OUTAGES] = [{"network": "z2m", "minute": 180, "length": 60.0, "set_at": _local(1, 0, 0)}]
    row = {"kind": SYS_BROKER_UP, "scope": "mqtt", "when": _local(3, 3, 6), "duration": 90.0}
    assert coordinator.system_row_expected(row) is False


@pytest.mark.usefixtures("_guayaquil")
async def test_a_second_time_is_tried_when_the_first_has_too_small_a_share(hass: HomeAssistant):
    """Five days at 1:00 AM, one outage each, and twelve outages over
    three days at 9:00 PM, among eleven more at other times: 9:00 PM is
    a third of all outages, 1:00 AM is not."""
    coordinator = await _house(hass, nights=())
    for day in (1, 2, 3, 4, 5):
        _outage(coordinator, _local(day, 1, 0), 60.0)
    for day in (1, 2, 3):
        for minute in (0, 2, 4, 6):
            _outage(coordinator, _local(day, 21, minute), 30.0)
    for index, hour in enumerate((5, 7, 9, 11, 13, 15, 17, 19, 23, 3, 10)):
        _outage(coordinator, _local(6 + index % 3, hour, 30), 60.0)
    patterns = coordinator.dashboard_network("zha")["patterns"]
    assert [p["minute"] // 60 for p in patterns] == [21], patterns


@pytest.mark.usefixtures("_guayaquil")
async def test_a_stored_row_with_no_usual_length_marks_nothing(hass: HomeAssistant):
    coordinator = await _house(hass)
    coordinator.data[DATA_EXPECTED_OUTAGES] = [{"network": "zha", "minute": 220, "length": None, "set_at": _local(1, 0, 0)}]
    page = coordinator.dashboard_network("zha")
    assert page["patterns"][0]["expected"] is False
    assert [c["kind"] for c in page["cards"]] == ["pattern"]


@pytest.mark.usefixtures("_guayaquil")
async def test_zigbee2mqtts_expected_time_never_covers_a_broker_outage_on_its_page(hass: HomeAssistant, freezer):
    from custom_components.device_sentinel.const import SYS_BROKER_DOWN, SYS_BROKER_UP

    entry = MockConfigEntry(domain="mqtt", title="MQTT")
    entry.add_to_hass(hass)
    plug = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("mqtt", "zigbee2mqtt_0x00aa")}, name="Plug")
    er.async_get(hass).async_get_or_create("sensor", "mqtt", "0x00aa_lqi", device_id=plug.id, config_entry=entry)
    coordinator = await setup_coordinator(hass)
    coordinator._rebuild_registry_view()
    for day in (1, 2, 3):
        _outage(coordinator, _local(day, 3, 40), 240.0, scope="z2m")
    if "z2m" not in coordinator.network_keys():
        pytest.skip("this harness has no Zigbee2MQTT network")
    coordinator.set_outage_expected("z2m", 220, True)
    coordinator._record_system_event(SYS_BROKER_DOWN, scope="mqtt", when=_local(8, 3, 50))
    coordinator._record_system_event(SYS_BROKER_UP, scope="mqtt", when=_local(8, 3, 52), duration=120.0)
    page = coordinator.dashboard_network("z2m")
    broker = next(o for o in page["outages"] if o.get("source") == "mqtt")
    assert broker["expected"] is False
    assert not any(c["kind"] == "longer" for c in page["cards"])
    assert len(page["patterns"]) == 1 and len(page["patterns"][0]["outages"]) == 3


@pytest.mark.usefixtures("_guayaquil")
async def test_running_since_is_left_out_while_the_network_is_down(hass: HomeAssistant):
    coordinator = await _house(hass)
    up = coordinator._network_up("zha", {"state": "down", "words": "Controller Jammed"}, coordinator.network_outages("zha", 30))
    assert up["back_since"] is None
    up = coordinator._network_up("zha", {"state": "ok"}, coordinator.network_outages("zha", 30))
    assert up["back_since"] is not None


def test_a_length_of_one_second_is_one_second():
    from custom_components.device_sentinel.network_extras import _span

    assert _span(1.2) == "1 second" and _span(30) == "30 seconds"
