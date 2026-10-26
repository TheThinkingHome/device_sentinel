# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_restart_resume.py, Version: 0.27.5 (2026-10-26)

"""A Wi-Fi outage open across a restart (rules UP-04, UP-10, UP-11).

Ruled a bug by James, 25 October 2026 (Known Gap 31, the Wi-Fi half):
an outage open before a restart is resumed from when it went down.
Ruled 26 October 2026: the outage is stored while it stands and
resumed from that stored state alone, so it comes back exactly as it
stood: its backdated start, its fallen set, its worst count and what
its down announced. A file written by 0.27.4 holds none, and nothing
is resumed.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DATA_WIFI_OUTAGE,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    STORAGE_KEY,
    SYS_WIFI_DOWN,
    SYS_WIFI_RECOVERING,
    SYS_WIFI_UP,
    WIFI_KEY,
    WIFI_OUTAGE_SINCE,
)

import pytest

from custom_components.device_sentinel.const import STARTUP_GRACE_SECONDS
from tests.outage_helpers import restart, tick
from tests.test_wifi_outage import _declared, _fall, _heard, _house, _rise


def _now() -> float:
    return dt_util.utcnow().timestamp()


def _downs(coord):
    return [r for r in coord.data[DATA_SYSTEM_EVENTS] if r["kind"] == SYS_WIFI_DOWN]


def _recovering(coord):
    return [
        r for r in coord.data[DATA_SYSTEM_EVENTS]
        if r["kind"] == SYS_WIFI_RECOVERING
    ]


def _fail(coord, device_id, when):
    record = coord.data[DATA_DEVICES][device_id]
    record[DEV_FROZEN_CATEGORY] = "unavailable"
    record[DEV_FROZEN_SINCE] = when


async def _down_then_restart(hass, freezer):
    coord, trackers, devices, _untied = await _house(hass, 6)
    heard = _heard(hass)
    first = await _declared(hass, coord, trackers, freezer, count=3)
    since = coord.wifi_down_at
    for device in devices[:3]:
        _fail(coord, device.id, first + 30.0)
    assert coord.data[DATA_WIFI_OUTAGE][WIFI_OUTAGE_SINCE] == since
    coord = await restart(hass, freezer, down=120)
    return coord, trackers, devices, since, heard


async def _scan_down_then_restart(hass, freezer):
    """A chosen network the scan declared gone, before any tracker left."""
    coord, trackers, devices, _untied = await _house(hass, 6)
    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, "wifi_networks": ["Harbor-IoT"]},
    )
    await hass.async_block_till_done()
    coord = coord.entry.runtime_data
    coord._grace_until = 0.0
    heard = _heard(hass)
    since = _now() - 90
    coord._wifi_scan_declare(since, ["Harbor-IoT"])
    assert coord.wifi_down_at == since
    coord = await restart(hass, freezer, down=120)
    return coord, trackers, since, heard


async def test_the_outage_is_resumed_from_when_it_went_down(
    hass: HomeAssistant, freezer
):
    coord, _trackers, devices, since, _heard = await _down_then_restart(
        hass, freezer
    )
    # Taken back at setup, inside the startup grace.
    assert coord.wifi_down_at == since
    assert len(coord.wifi_fallen_set) == 3
    assert coord.upstream_down_since(devices[0].id) == (WIFI_KEY, since)


async def test_its_return_closes_the_pair_with_its_real_length(
    hass: HomeAssistant, freezer
):
    coord, trackers, _devices, since, heard = await _down_then_restart(
        hass, freezer
    )
    coord._grace_until = 0.0
    coord._sample_wifi(_now())
    assert coord.wifi_down_at is not None

    freezer.tick(timedelta(minutes=5))
    for tracker in trackers[:3]:
        await _rise(hass, tracker)
    now = _now()
    coord._sample_wifi(now)
    await hass.async_block_till_done()
    assert coord.wifi_down_at is None
    assert DATA_WIFI_OUTAGE not in coord.data

    assert [label for label, _data in heard] == ["down", "restored"]
    restored = heard[-1][1]
    assert restored["devices"] == 6
    assert abs(restored["for_seconds"] - (now - since)) < 2
    up = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r["kind"] == SYS_WIFI_UP]
    assert len(up) == 1 and abs(up[0]["duration"] - (now - since)) < 2


async def test_trackers_home_by_the_end_of_the_grace_close_it(
    hass: HomeAssistant, freezer
):
    """The stored fallen set came home while Home Assistant restarted:
    the first sample after the grace counts them back and closes it."""
    coord, trackers, _devices, _since, heard = await _down_then_restart(
        hass, freezer
    )
    for tracker in trackers[:3]:
        await _rise(hass, tracker)
    coord._sample_wifi(_now())
    assert coord.wifi_down_at is not None
    coord._grace_until = 0.0
    coord._sample_wifi(_now())
    await hass.async_block_till_done()
    assert coord.wifi_down_at is None
    assert [label for label, _data in heard] == ["down", "restored"]


async def test_an_outage_open_across_two_restarts_is_still_resumed(
    hass: HomeAssistant, freezer
):
    coord, trackers, _devices, _untied = await _house(hass, 6)
    heard = _heard(hass)
    await _declared(hass, coord, trackers, freezer, count=3)
    since = coord.wifi_down_at

    coord = await restart(hass, freezer, down=120)
    coord._grace_until = 0.0
    coord._sample_wifi(_now())
    assert coord.wifi_down_at == since

    coord = await restart(hass, freezer, down=120)
    assert coord.wifi_down_at == since
    coord = await restart(hass, freezer, down=120)
    assert coord.wifi_down_at == since

    coord._grace_until = 0.0
    coord._sample_wifi(_now())
    for tracker in trackers[:3]:
        await _rise(hass, tracker)
    coord._sample_wifi(_now())
    await hass.async_block_till_done()
    assert [label for label, _ in heard] == ["down", "restored"]


async def test_a_scan_house_ends_it_when_the_network_is_heard(
    hass: HomeAssistant, freezer
):
    """Nothing fell, so the resumed outage waits for the network, by
    its stored down mark, and ends when the scan hears it."""
    coord, _trackers, since, heard = await _scan_down_then_restart(
        hass, freezer
    )
    coord._wifi_scan_interface = "wlo1"
    coord._grace_until = 0.0
    coord._sample_wifi(_now())
    assert coord.wifi_down_at == since
    assert coord.wifi_scan_down_at == since

    coord._wifi_scan_restore(_now())
    await hass.async_block_till_done()
    assert coord.wifi_down_at is None
    assert [label for label, _data in heard] == ["down", "restored"]


async def test_a_chosen_network_with_no_adapter_lets_the_trackers_decide(
    hass: HomeAssistant, freezer
):
    """No adapter answered through the grace, so nothing will hear the
    network: with nothing fallen, the outage ends."""
    coord, _trackers, _since, heard = await _scan_down_then_restart(
        hass, freezer
    )
    coord._sample_wifi(_now())
    assert coord.wifi_down_at is not None
    coord._grace_until = 0.0
    coord._sample_wifi(_now())
    await hass.async_block_till_done()
    assert coord.wifi_down_at is None
    assert [label for label, _data in heard] == ["down", "restored"]


async def test_a_tracker_away_before_with_a_healthy_device_is_not_a_casualty(
    hass: HomeAssistant, freezer
):
    """A tied tracker reading away while its device works was away
    before the outage. It is not in the stored fallen set, so once the
    casualties are home the outage closes."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    await _fall(hass, trackers[5])
    freezer.tick(timedelta(hours=2))
    await _declared(hass, coord, trackers, freezer, count=3)
    assert trackers[5] not in coord.wifi_fallen_set

    coord = await restart(hass, freezer, down=120)
    for tracker in trackers[:3]:
        await _rise(hass, tracker)
    coord._grace_until = 0.0
    coord._sample_wifi(_now())
    for _ in range(3):
        freezer.tick(timedelta(seconds=60))
        coord._sample_wifi(_now())
    await hass.async_block_till_done()
    assert trackers[5] not in coord.wifi_fallen_set
    assert coord.wifi_down_at is None


async def test_a_tracker_away_before_whose_device_failed_then_is_not_claimed(
    hass: HomeAssistant, freezer
):
    coord, trackers, devices, _untied = await _house(hass, 6)
    await _fall(hass, trackers[5])
    began = _now()
    _fail(coord, devices[5].id, began)
    freezer.tick(timedelta(hours=2))
    await _declared(hass, coord, trackers, freezer, count=3)
    assert coord.upstream_down_since(devices[5].id) is None

    coord = await restart(hass, freezer, down=120)
    _fail(coord, devices[5].id, began)
    coord._grace_until = 0.0
    coord._sample_wifi(_now())
    assert trackers[5] not in coord.wifi_fallen_set
    assert coord.upstream_down_since(devices[5].id) is None


async def test_a_lookback_casualty_stays_claimed_and_the_start_holds(
    hass: HomeAssistant, freezer
):
    """A tied device whose failure began three minutes before the first
    tracker left belongs to the outage, which is dated from it (UP-15).
    After a restart it is still claimed, and the start has not moved
    (UP-11, LIST-13)."""
    coord, trackers, devices, _untied = await _house(hass, 6)
    began = _now() - 180.0
    _fail(coord, devices[0].id, began)
    await _declared(hass, coord, trackers, freezer, count=3)
    before = coord.upstream_down_since_for(WIFI_KEY)
    assert before == began
    assert coord.upstream_down_since(devices[0].id) == (WIFI_KEY, began)
    down = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r["kind"] == SYS_WIFI_DOWN]
    assert down[-1]["when"] == began

    coord = await restart(hass, freezer, down=120)
    _fail(coord, devices[0].id, began)
    coord._grace_until = 0.0
    coord._sample_wifi(_now())
    assert coord.wifi_down_at is not None
    assert coord.upstream_down_since_for(WIFI_KEY) == before
    assert coord.upstream_down_since(devices[0].id) == (WIFI_KEY, began)


async def test_the_start_moved_back_after_declaring_moves_its_row(
    hass: HomeAssistant, freezer
):
    """A verdict that lands after the declaration moves the start back,
    and the down row and the stored start move with it."""
    coord, trackers, devices, _untied = await _house(hass, 6)
    first = await _declared(hass, coord, trackers, freezer, count=3)
    _fail(coord, devices[0].id, first - 120.0)
    coord._wifi_backdate()
    assert coord.wifi_down_at == first - 120.0
    down = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r["kind"] == SYS_WIFI_DOWN]
    assert down[-1]["when"] == first - 120.0
    assert coord.data[DATA_WIFI_OUTAGE][WIFI_OUTAGE_SINCE] == first - 120.0


async def test_a_backdate_while_recovering_still_moves_the_down_row(
    hass: HomeAssistant, freezer
):
    """The recovering row is written after the down row; a later
    backdate re-dates the down row all the same."""
    coord, trackers, devices, _untied = await _house(hass, 6)
    first = await _declared(hass, coord, trackers, freezer, count=3)
    for tracker in trackers[:2]:
        await _rise(hass, tracker)
    coord._sample_wifi(_now())
    kinds = [r["kind"] for r in coord.data[DATA_SYSTEM_EVENTS]]
    assert SYS_WIFI_RECOVERING in kinds
    _fail(coord, devices[2].id, first - 120.0)
    coord._wifi_backdate()
    assert coord.wifi_down_at == first - 120.0
    assert coord.data[DATA_WIFI_OUTAGE][WIFI_OUTAGE_SINCE] == first - 120.0
    down = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r["kind"] == SYS_WIFI_DOWN]
    assert down[-1]["when"] == first - 120.0


async def test_a_down_row_an_older_release_left_open_keeps_its_date(
    hass: HomeAssistant, freezer, hass_storage
):
    """0.27.4 restarted mid-outage and left its down row open. The next
    outage is dated back at its declaration, before its own row exists,
    and the older row keeps its date."""
    coord, trackers, devices, _untied = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    old_when = _downs(coord)[-1]["when"]

    def written_by_0_27_4():
        hass_storage[STORAGE_KEY]["data"].pop(DATA_WIFI_OUTAGE, None)

    coord = await restart(hass, freezer, down=120, before_setup=written_by_0_27_4)
    coord._grace_until = 0.0
    coord._sample_wifi(_now())
    assert coord.wifi_down_at is None
    for tracker in trackers[:3]:
        await _rise(hass, tracker)
    freezer.tick(timedelta(days=2))

    _fail(coord, devices[0].id, _now() - 120.0)
    first = await _declared(hass, coord, trackers, freezer, count=3)
    assert coord.wifi_down_at < first
    downs = _downs(coord)
    assert len(downs) == 2
    assert downs[0]["when"] == old_when
    assert downs[1]["when"] == coord.wifi_down_at


async def test_a_restart_while_recovering_writes_one_recovering_row(
    hass: HomeAssistant, freezer
):
    """On a house with trackers only, the recovery under way at the
    restart stays under way: its row reads recovering through the grace
    and its recovering row is written once."""
    coord, trackers, _devices, _untied = await _house(hass, 10)
    await _declared(hass, coord, trackers, freezer, count=5)
    for tracker in trackers[:2]:
        await _rise(hass, tracker)
    coord._sample_wifi(_now())
    began = coord.wifi_recovering_at
    assert began is not None
    assert len(_recovering(coord)) == 1

    coord = await restart(hass, freezer, down=120)
    assert coord.wifi_recovering_at == began
    coord._grace_until = 0.0
    coord._sample_wifi(_now())
    assert coord.wifi_down_at is not None
    assert len(_recovering(coord)) == 1


async def test_the_worst_seen_before_the_restart_is_kept(
    hass: HomeAssistant, freezer
):
    """The most devices it had down carries across, and its up row and
    the Daily Brief tell it by that (UP-11)."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)
    coord._note_upstream_peaks()
    assert coord.suppressed_down_counts.get(WIFI_KEY) == 3

    coord = await restart(hass, freezer, down=120)
    for tracker in trackers[:3]:
        await _rise(hass, tracker)
    coord._grace_until = 0.0
    coord._sample_wifi(_now())
    await hass.async_block_till_done()
    assert coord.wifi_down_at is None
    up = [r for r in coord.data[DATA_SYSTEM_EVENTS] if r["kind"] == SYS_WIFI_UP]
    assert len(up) == 1
    assert up[0].get("worst") == 3


async def test_a_0_27_4_file_resumes_nothing(
    hass: HomeAssistant, freezer, hass_storage
):
    """0.27.4 stored no Wi-Fi outage. A down row it left open is not
    resumed at the upgrade, whatever the row says."""
    coord, trackers, _devices, untied = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)

    def written_by_0_27_4():
        hass_storage[STORAGE_KEY]["data"].pop(DATA_WIFI_OUTAGE, None)

    coord = await restart(hass, freezer, down=120, before_setup=written_by_0_27_4)
    coord._grace_until = 0.0
    coord._sample_wifi(_now())
    assert coord.wifi_down_at is None
    _fail(coord, untied.id, _now())
    assert coord.upstream_down_since(untied.id) is None


async def test_a_damaged_stored_outage_is_dropped_and_resumes_nothing(
    hass: HomeAssistant, freezer, hass_storage
):
    coord, trackers, _devices, _untied = await _house(hass, 6)
    await _declared(hass, coord, trackers, freezer, count=3)

    def damaged():
        hass_storage[STORAGE_KEY]["data"][DATA_WIFI_OUTAGE] = {
            WIFI_OUTAGE_SINCE: "yesterday",
        }
        # With no last-good copy to restore from, the damage is
        # repaired where it is found (rule STOR-09).
        copy = Path(hass.config.path(".storage/device_sentinel.storage.last-good"))
        copy.unlink(missing_ok=True)

    coord = await restart(hass, freezer, down=120, before_setup=damaged)
    assert coord.wifi_down_at is None
    assert DATA_WIFI_OUTAGE not in coord.data


async def test_a_closed_outage_is_not_resumed(hass: HomeAssistant, freezer):
    coord, trackers, _devices, _untied = await _house(hass, 4)
    await _declared(hass, coord, trackers, freezer, count=3)
    for tracker in trackers[:3]:
        await _rise(hass, tracker)
    coord._sample_wifi(_now())
    assert coord.wifi_down_at is None
    assert DATA_WIFI_OUTAGE not in coord.data
    coord = await restart(hass, freezer, down=60)
    coord._sample_wifi(_now())
    assert coord.wifi_down_at is None


async def test_nothing_fallen_heard_inside_the_grace_has_no_recovering_phase(
    hass: HomeAssistant, freezer
):
    """A resumed outage with an empty fallen set ends when the network
    is heard, inside the startup grace too, with no recovering row
    (rule UP-16). Until 0.27.5 it waited for the grace, wrote a
    recovering row and the Problem List read recovering meanwhile."""
    coord, _trackers, _since, heard = await _scan_down_then_restart(
        hass, freezer
    )
    assert coord._in_startup_grace()
    assert not coord.wifi_fallen_set
    coord._wifi_scan_interface = "wlo1"
    coord._wifi_scan_restore(_now())
    await hass.async_block_till_done()
    assert _recovering(coord) == []
    assert coord.wifi_recovering_at is None
    assert coord.wifi_down_at is None
    assert [label for label, _ in heard][-1] == "restored"


@pytest.mark.parametrize("placeholder", [False, True])
async def test_a_router_answering_after_the_grace_closes_the_outage(
    hass: HomeAssistant, freezer, placeholder
):
    """A resumed outage whose router integration answers only after the
    five-minute grace, with every fallen tracker already home. The
    returns arrive before any tie can hear them, so the fallen trackers
    are read again when the ties form (rule UP-16). Until 0.27.5 they
    were read once at the grace's end, against absent states, and the
    outage never closed. With `placeholder`, the trackers read Home
    Assistant's "unavailable" placeholder until the router answers."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    attrs = {t: dict(hass.states.get(t).attributes) for t in trackers}
    await _declared(hass, coord, trackers, freezer, count=3)
    registry = er.async_get(hass)

    def router_not_loaded():
        for tracker in trackers:
            hass.states.async_remove(tracker)
            if placeholder:
                registry.async_get(tracker).write_unavailable_state(hass)

    coord = await restart(hass, freezer, down=120, before_setup=router_not_loaded)
    assert coord.wifi_down_at is not None
    await tick(hass, freezer, step=STARTUP_GRACE_SECONDS + 5)
    await tick(hass, freezer, step=60, n=2)
    assert not coord._in_startup_grace()
    assert not coord._wifi_ties
    for tracker in trackers:
        hass.states.async_set(tracker, "home", attrs[tracker])
    await hass.async_block_till_done()
    await tick(hass, freezer, step=60, n=3)
    assert coord._wifi_ties
    assert coord.wifi_down_at is None, (
        f"returned {coord.wifi_returned_count} of {len(coord.wifi_fallen_set)}"
    )


async def test_a_router_answering_after_the_grace_keeps_trackers_still_away(
    hass: HomeAssistant, freezer
):
    """The same late router, with the fallen trackers still away: read
    when the ties form, they stay away and the outage stays open."""
    coord, trackers, _devices, _untied = await _house(hass, 6)
    attrs = {t: dict(hass.states.get(t).attributes) for t in trackers}
    await _declared(hass, coord, trackers, freezer, count=3)
    fallen = sorted(coord.wifi_fallen_set)
    assert len(fallen) == 3

    def router_not_loaded():
        for tracker in trackers:
            hass.states.async_remove(tracker)

    coord = await restart(hass, freezer, down=120, before_setup=router_not_loaded)
    await tick(hass, freezer, step=STARTUP_GRACE_SECONDS + 5)
    await tick(hass, freezer, step=60, n=2)
    for tracker in trackers:
        state = "not_home" if tracker in fallen else "home"
        hass.states.async_set(tracker, state, attrs[tracker])
    await hass.async_block_till_done()
    await tick(hass, freezer, step=60, n=3)
    assert coord._wifi_ties
    assert coord.wifi_down_at is not None
    assert coord.wifi_returned_count == 0
    # And one coming home afterwards is heard as a return.
    hass.states.async_set(fallen[0], "home", attrs[fallen[0]])
    await hass.async_block_till_done()
    assert coord.wifi_returned_count == 1


@pytest.mark.xfail(
    strict=True,
    reason="Rare, documented and not fixed in 0.27.5: a fallen tracker "
    "going unavailable inside the grace is counted as a return.",
)
async def test_a_tracker_unavailable_inside_the_grace_is_not_a_return(
    hass: HomeAssistant, freezer
):
    """The router integration reports its trackers unavailable for a
    moment after a restart, then not_home again: nothing came back."""
    coord, trackers, _devices, _since, heard = await _down_then_restart(
        hass, freezer
    )
    assert coord._in_startup_grace()
    # The ties form on the first minute check, inside the grace.
    await tick(hass, freezer, step=61)
    assert coord._wifi_ties and coord._in_startup_grace()
    for tracker in trackers[:3]:
        attributes = dict(hass.states.get(tracker).attributes)
        hass.states.async_set(tracker, "unavailable", attributes)
        await hass.async_block_till_done()
        hass.states.async_set(tracker, "not_home", attributes)
        await hass.async_block_till_done()
    coord._grace_until = 0.0
    for _ in range(3):
        freezer.tick(timedelta(seconds=60))
        coord._sample_wifi(_now())
    await hass.async_block_till_done()
    assert coord.wifi_down_at is not None
    assert [label for label, _ in heard] == ["down"]
