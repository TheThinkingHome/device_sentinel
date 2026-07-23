# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v075_honest_reports.py, Version: 0.7.5 (2026-07-23)

"""0.7.5 tests: four ways the reports were telling small lies.

A shared duration suffix that only joined correctly with one of the
four wordings. Acknowledged problems still being reported to the
person who acknowledged them. A Zigbee reconnect taking credit for
reviving a HomeKit accessory it cannot reach. And a brief renaming
itself at midnight, so one window produced two files.
"""

import glob
import os

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_EPISODES,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    EPISODE_ENDED_RECONNECT,
    EP_AT,
    EP_BASIS,
    EP_DEVICE_ID,
    EP_ENDED,
    EP_LAG,
    EP_LEARNED,
    EP_NAME,
    EP_SINCE,
    EP_WINDOW,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
)

DOMAIN = "device_sentinel"


def _register(hass, uid, name, source=None):
    if source is None:
        source = MockConfigEntry(domain="test", title=f"Source {uid}")
        source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    ent = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    return device, ent.entity_id, source


async def _coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _fault(coord, device_id, category, hours=4.0):
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = category
    record[DEV_FROZEN_SINCE] = (
        dt_util.utcnow().timestamp() - hours * 3600.0
    )


def _open_episode(coord, device_id, name):
    coord.data[DATA_EPISODES].append(
        {
            EP_DEVICE_ID: device_id,
            EP_NAME: name,
            EP_SINCE: dt_util.utcnow().timestamp() - 7200.0,
            EP_BASIS: 3600.0,
            EP_WINDOW: 7200.0,
            EP_ENDED: None,
            EP_AT: None,
            EP_LAG: None,
            EP_LEARNED: None,
        }
    )


# ------------------------------------------------------- the grammar

async def test_present_perfect_kinds_take_for_not_ago(
    hass: HomeAssistant,
):
    """"has been unavailable 4.0h ago" reached a live brief. Three of
    the four wordings are present perfect and need "for"."""
    device, entity_id, _ = _register(hass, "g1", "Grammar Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "on")
    _fault(coord, device.id, FREEZE_CATEGORY_UNAVAILABLE)
    coord._sync_problem_list()
    line = coord._compose_device_line(device.id)
    assert line == "Grammar Sensor has been unavailable for 4.0h."
    assert "ago" not in line


async def test_past_tense_kind_still_takes_ago(hass: HomeAssistant):
    device, entity_id, _ = _register(hass, "g2", "Past Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "on")
    _fault(coord, device.id, FREEZE_CATEGORY_FROZEN)
    coord._sync_problem_list()
    assert coord._compose_device_line(device.id) == (
        "Past Sensor stopped reporting 4.0h ago."
    )


# ------------------------------------------- acknowledgment (#123)

async def test_acknowledged_device_leaves_the_whole_brief(
    hass: HomeAssistant, read_brief
):
    """Standing state and history alike, while it stays acknowledged."""
    device, entity_id, _ = _register(hass, "a1", "Quiet Please")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "on")
    _fault(coord, device.id, FREEZE_CATEGORY_FROZEN)
    coord._sync_problem_list()          # opens an incident
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    await hass.async_add_executor_job(coord._write_reports, "test")

    text = read_brief(hass)
    assert "Quiet Please" not in text
    assert "Nothing needs attention." in text
    assert "Nothing happened." in text


async def test_recovery_of_an_acknowledged_device_is_news(
    hass: HomeAssistant, read_brief
):
    """#114 with #123: acknowledgment ends at recovery, because the
    item is deleted, so the recovery is reported."""
    device, entity_id, _ = _register(hass, "a2", "Came Back")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "on")
    _fault(coord, device.id, FREEZE_CATEGORY_FROZEN)
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")

    record = coord.data["devices"][device.id]
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    coord._sync_problem_list()          # deletes the item
    await hass.async_add_executor_job(coord._write_reports, "test")

    text = read_brief(hass)
    assert "Came Back" in text
    assert "recovered" in text


# ------------------------------------- intervention attribution

async def test_a_storm_only_stamps_its_own_integration(
    hass: HomeAssistant,
):
    """A Zigbee reconnect cannot revive a HomeKit accessory, and
    crediting it with one put a false cause in a live brief."""
    zigbee, _, zigbee_entry = _register(hass, "z1", "Zigbee Thing")
    homekit, _, _ = _register(hass, "h1", "HomeKit Thing")
    coord = await _coordinator(hass)
    _open_episode(coord, zigbee.id, "Zigbee Thing")
    _open_episode(coord, homekit.id, "HomeKit Thing")

    coord._stamp_intervention(
        EPISODE_ENDED_RECONNECT,
        dt_util.utcnow().timestamp(),
        entry_id=zigbee_entry.entry_id,
    )
    by_name = {
        row[EP_NAME]: row[EP_ENDED] for row in coord.data[DATA_EPISODES]
    }
    assert by_name["Zigbee Thing"] == EPISODE_ENDED_RECONNECT
    assert by_name["HomeKit Thing"] is None


async def test_a_restart_stamps_everything(hass: HomeAssistant):
    """No entry_id means the whole system, which is what a restart is."""
    first, _, _ = _register(hass, "r1", "One")
    second, _, _ = _register(hass, "r2", "Two")
    coord = await _coordinator(hass)
    _open_episode(coord, first.id, "One")
    _open_episode(coord, second.id, "Two")

    coord._stamp_intervention(
        EPISODE_ENDED_RECONNECT, dt_util.utcnow().timestamp()
    )
    assert all(
        row[EP_ENDED] == EPISODE_ENDED_RECONNECT
        for row in coord.data[DATA_EPISODES]
    )


# ------------------------------------------------ one window, one file

async def test_one_window_writes_one_file(hass: HomeAssistant):
    """Naming by the moment of writing renamed the in-progress brief
    at midnight, so a single window left two overlapping files."""
    coord = await _coordinator(hass)
    for _ in range(3):
        await hass.async_add_executor_job(coord._write_reports, "test")
    written = glob.glob(
        hass.config.path("device_sentinel", "daily_brief_*.md")
    )
    assert len(written) == 1


async def test_the_file_is_named_for_the_window_start(
    hass: HomeAssistant,
):
    coord = await _coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "test")
    start = coord._brief_window_start(dt_util.utcnow().timestamp())
    expected = dt_util.as_local(
        dt_util.utc_from_timestamp(start)
    ).strftime("daily_brief_%Y-%m-%d.md")
    written = glob.glob(
        hass.config.path("device_sentinel", "daily_brief_*.md")
    )
    assert os.path.basename(written[0]) == expected
