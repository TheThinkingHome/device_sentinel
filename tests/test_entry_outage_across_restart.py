# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_entry_outage_across_restart.py, Version: 0.27.10 (2026-10-27)

"""An integration entry outage standing across a restart (rules UP-09,
UP-10, UP-11).

The same promises a bridge or broker outage keeps: a down pushed before
the restart is not pushed again, and its over push still follows; a down
never told on the bus is told once after the next grace, and only a told
down is owed its restored; the worst count so far survives. Each mark is
kept with the entry's outage and saved at once, and a damaged mark is
dropped without an exception.
"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIDGE_HANDBACK_SECONDS,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    INTEGRATION_DOWN_DWELL_SECONDS,
    SYS_INTEGRATION_UP,
    SYS_KIND,
    SYS_WORST,
    UPSTREAM_SETTLE_SECONDS,
)
from custom_components.device_sentinel.interventions import DATA_INTEGRATION_SEEN
from custom_components.device_sentinel.normalise import check_storage

from tests.helpers import record_events, setup_coordinator
from tests.outage_helpers import past_grace, restart, walk
from tests.test_upstream_push_across_restart import _record_pushes
from tests.test_wifi_push_phases import _owed

DOMAIN = "lutron_caseta"


def _hub(hass: HomeAssistant, devices: int = 2):
    """One config entry carrying several devices, as a hub does."""
    source = MockConfigEntry(domain=DOMAIN, title="Hub")
    source.add_to_hass(hass)
    made = []
    for index in range(devices):
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={(DOMAIN, f"node{index}")},
            name=f"Node {index}",
        )
        er.async_get(hass).async_get_or_create(
            "sensor", DOMAIN, f"node{index}",
            device_id=device.id, config_entry=source,
        )
        made.append(device)
    return source, made


def _watch(coord, devices):
    coord._rebuild_registry_view()
    for device in devices:
        coord._watched[device.id] = DOMAIN


def _key(source):
    return f"{DOMAIN}|{source.entry_id}"


def _seen(coord, source):
    return (coord.data.get(DATA_INTEGRATION_SEEN) or {}).get(_key(source))


def _down(coord, devices, when):
    for device in devices:
        record = coord.data[DATA_DEVICES].setdefault(device.id, {})
        record[DEV_FROZEN_CATEGORY] = "unavailable"
        record[DEV_FROZEN_SINCE] = when


async def _goes_down(hass, freezer, source, devices):
    """Loaded, then down past the dwell, outside the grace: told."""
    coord = await setup_coordinator(hass)
    await past_grace(hass, freezer)
    _watch(coord, devices)
    now = dt_util.utcnow().timestamp()
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now)
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert source.entry_id in coord._integration_told
    _down(coord, devices, now + 30)
    coord._note_upstream_peaks()
    return coord


async def _pushed_down(hass, freezer, source, devices):
    coord = await _goes_down(hass, freezer, source, devices)
    seen = _seen(coord, source)
    assert seen is not None and seen["told"] is True and seen["devices"] == 2
    assert seen["worst"] == 2
    freezer.tick(UPSTREAM_SETTLE_SECONDS + 5)
    coord._critical = False
    assert _owed(coord) == [(DOMAIN, False)]
    assert _owed(coord) == []
    assert _seen(coord, source)["pushed"] is True
    assert coord._critical, "the push mark is saved at once"
    return coord


async def test_entry_down_is_not_pushed_again_after_a_restart(
    hass: HomeAssistant, freezer
):
    source, devices = _hub(hass)
    await _pushed_down(hass, freezer, source, devices)
    coord = await restart(hass, freezer, down=120)
    _watch(coord, devices)
    sent: list = []
    _record_pushes(coord, sent)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 180)
    assert coord.upstream_down_since_for(DOMAIN) is not None  # resumed
    assert sent == []
    # Over: its over push follows, once and silent, and the record goes.
    source.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, BRIDGE_HANDBACK_SECONDS + 240)
    assert sent == [(DOMAIN, True, False)]
    assert _seen(coord, source) is None
    # The worst count stored before the restart is the one it ends with.
    (up,) = [
        row for row in coord.data[DATA_SYSTEM_EVENTS]
        if row[SYS_KIND] == SYS_INTEGRATION_UP
    ]
    assert up[SYS_WORST] == 2


async def test_entry_back_inside_the_hand_back_still_pushes_over(
    hass: HomeAssistant, freezer
):
    """Back before the restart with its over push still owed: it goes
    after the next grace, once and silent."""
    source, devices = _hub(hass)
    coord = await _pushed_down(hass, freezer, source, devices)
    source.mock_state(hass, ConfigEntryState.LOADED)
    freezer.tick(240)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert source.entry_id not in coord._integration_told
    assert _seen(coord, source)["pushed"] is True  # kept until the over push
    coord = await restart(hass, freezer, down=60)
    _watch(coord, devices)
    sent: list = []
    _record_pushes(coord, sent)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 240)
    assert sent == [(DOMAIN, True, False)]
    assert _seen(coord, source) is None


async def test_entry_down_never_told_is_told_after_the_next_grace(
    hass: HomeAssistant, freezer
):
    source, devices = _hub(hass)
    coord = await setup_coordinator(hass)
    _watch(coord, devices)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    assert coord._in_startup_grace()
    now = dt_util.utcnow().timestamp()
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now)
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert source.entry_id in coord._integration_told  # held, not told
    assert _seen(coord, source)["told"] is False
    coord = await restart(hass, freezer, down=30)  # inside the grace
    _watch(coord, devices)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert _key(source) not in coord._upstream_owed
    await past_grace(hass, freezer)
    await walk(hass, freezer, 120)
    await hass.async_block_till_done()
    assert len(downs) == 1 and list(ups) == []
    assert _seen(coord, source)["told"] is True
    source.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, 120)
    await hass.async_block_till_done()
    assert len(downs) == 1 and len(ups) == 1


async def test_entry_down_never_told_and_back_inside_the_grace_says_nothing(
    hass: HomeAssistant, freezer
):
    source, devices = _hub(hass)
    coord = await setup_coordinator(hass)
    _watch(coord, devices)
    downs = record_events(hass, "device_sentinel_upstream_down")
    ups = record_events(hass, "device_sentinel_upstream_restored")
    now = dt_util.utcnow().timestamp()
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now)
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    coord = await restart(hass, freezer, down=30)
    _watch(coord, devices)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    source.mock_state(hass, ConfigEntryState.LOADED)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(dt_util.utcnow().timestamp())  # back in the grace
    await past_grace(hass, freezer)
    await walk(hass, freezer, 240)
    await hass.async_block_till_done()
    assert list(downs) == [] and list(ups) == []


@pytest.mark.parametrize(
    "damaged",
    [
        "not a record",
        {"told": "no", "pushed": 1, "devices": -3, "worst": "x"},
        {"told": None, "pushed": [True], "devices": True, "worst": 10**13},
    ],
)
async def test_damaged_entry_marks_are_dropped(
    hass: HomeAssistant, freezer, hass_storage, damaged
):
    """Anything but a flag or a count is dropped without an exception, and
    the outage is taken as told, as one remembered before the marks
    existed (rule STOR-07).

    The damage is written into the stored file after the stop and before
    the start. Written into memory before the stop, it would race the old
    run: a minute tick landing after the settle sends the real down push,
    which marks pushed over the damaged value, so the test would pass or
    fail by the wall clock."""
    from custom_components.device_sentinel.const import STORAGE_KEY

    source, devices = _hub(hass)
    await _goes_down(hass, freezer, source, devices)

    def _damage() -> None:
        hass_storage[STORAGE_KEY]["data"][DATA_INTEGRATION_SEEN] = {
            _key(source): damaged
        }

    coord = await restart(hass, freezer, down=60, before_setup=_damage)
    _watch(coord, devices)
    coord._sample_integrations(dt_util.utcnow().timestamp())
    assert _key(source) in coord._upstream_owed
    assert _key(source) not in coord._upstream_held
    assert DOMAIN not in coord._upstream_announced
    kept = _seen(coord, source)
    assert kept is None or not any(
        field in kept for field in ("told", "pushed", "devices", "worst")
    )


async def test_entry_marks_have_a_shape(hass: HomeAssistant, freezer):
    """The stored marks pass the shape check, and a store that is not a
    mapping is caught by it (rule STOR-05)."""
    source, devices = _hub(hass)
    coord = await _pushed_down(hass, freezer, source, devices)
    assert check_storage({DATA_INTEGRATION_SEEN: coord.data[DATA_INTEGRATION_SEEN]}) == []
    assert check_storage({DATA_INTEGRATION_SEEN: ["a list"]})


async def test_entry_over_push_not_repeated_after_a_later_power_cut(
    hass: HomeAssistant, freezer
):
    """The record cleared after the over push reaches the file at once,
    so a power cut later brings no second over push (rule UP-09)."""
    from tests.test_upstream_push_across_restart import _power_cut

    source, devices = _hub(hass)
    coord = await _pushed_down(hass, freezer, source, devices)
    sent: list = []
    _record_pushes(coord, sent)
    source.mock_state(hass, ConfigEntryState.LOADED)
    await walk(hass, freezer, BRIDGE_HANDBACK_SECONDS + 240)
    assert sent == [(DOMAIN, True, False)]
    assert _seen(coord, source) is None
    await walk(hass, freezer, 1800)
    coord = await _power_cut(hass, freezer)
    _watch(coord, devices)
    again: list = []
    _record_pushes(coord, again)
    await past_grace(hass, freezer)
    await walk(hass, freezer, 240)
    assert again == []
