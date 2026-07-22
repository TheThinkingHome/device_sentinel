# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v067_episodes.py, Version: 0.6.7 (2026-07-22)

"""0.6.7 tests: silence episodes and the widened delta-high range.

An episode opens when a device passes its own basis, closes as
resumed when it speaks for itself, and is stamped by an intervention
when a reboot or a bridge reconnect truncates it. The lag column,
filled at the first genuine report after an intervention, is what
separates a wedge from a device that was merely quiet.
"""

from datetime import timedelta

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_EPISODES,
    DEFAULT_FREEZE_DELTA_HIGH_HR,
    DEV_DAILY_MAX,
    DEV_LAST_ACTIVITY,
    EPISODE_ENDED_REBOOT,
    EPISODE_ENDED_RESUMED,
    EP_ENDED,
    EP_LAG,
    EP_LEARNED,
    EP_NAME,
    FREEZE_ARMING_DAYS,
    FREEZE_DELTA_HIGH_HR_MAX,
    FREEZE_DELTA_HIGH_HR_MIN,
)

DOMAIN = "device_sentinel"


def _register(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
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
    return device, ent.entity_id


async def _coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _armed_and_silent(coord, device_id, hours_silent):
    """Give a device an hourly rhythm and a silence past its basis.

    Startup grace is closed first: these tests are about a running
    system, and a stamp inside grace is correctly excluded from
    learning, which would mask what the episode columns are proving.
    """
    coord._grace_until = 0.0
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = (
        dt_util.utcnow().timestamp() - hours_silent * 3600.0
    )


def _episodes(coord):
    return coord.data[DATA_EPISODES]


async def test_delta_high_range_widened(hass: HomeAssistant):
    """#102: the asymmetric 2-to-8 range becomes 4 to 12, default 8."""
    assert FREEZE_DELTA_HIGH_HR_MIN == 4
    assert FREEZE_DELTA_HIGH_HR_MAX == 12
    assert DEFAULT_FREEZE_DELTA_HIGH_HR == 8


async def test_quiet_device_never_opens_an_episode(hass: HomeAssistant):
    """The filter that keeps the file readable: a device inside its
    rhythm produces no row."""
    device, entity_id = _register(hass, "q1", "Quiet Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 0.5)  # half its basis
    coord._judge_all_devices()
    assert _episodes(coord) == []


async def test_episode_opens_past_basis_and_resumes(
    hass: HomeAssistant,
):
    """Past its rhythm opens a row; speaking for itself closes it as
    resumed, with the gap learned."""
    device, entity_id = _register(hass, "r1", "Resuming Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 2.0)
    coord._judge_all_devices()
    assert len(_episodes(coord)) == 1
    assert _episodes(coord)[0][EP_ENDED] is None
    assert _episodes(coord)[0][EP_NAME] == "Resuming Sensor"

    coord._record_activity(device.id, None, entity_id, "2")
    episode = _episodes(coord)[0]
    assert episode[EP_ENDED] == EPISODE_ENDED_RESUMED
    assert episode[EP_LEARNED] == "yes"
    assert episode[EP_LAG] is None  # nothing to measure against


async def test_reboot_truncates_and_lag_fills_later(
    hass: HomeAssistant, freezer
):
    """A restart stamps the open episode; the lag arrives with the
    device's first genuine report, which is the wedge discriminator."""
    device, entity_id = _register(hass, "i1", "Levered Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 3.0)
    coord._judge_all_devices()

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    episode = _episodes(coord)[0]
    assert episode[EP_ENDED] == EPISODE_ENDED_REBOOT
    assert episode[EP_LAG] is None  # still awaiting the resume

    freezer.tick(timedelta(seconds=90))
    coord._record_activity(device.id, None, entity_id, "2")
    episode = _episodes(coord)[0]
    assert 80 <= episode[EP_LAG] <= 100
    assert episode[EP_ENDED] == EPISODE_ENDED_REBOOT  # unchanged


async def test_second_silence_is_a_new_row(hass: HomeAssistant):
    """One row per occurrence, so a nightly wedge reads as a pattern."""
    device, entity_id = _register(hass, "s2", "Repeating Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 2.0)
    coord._judge_all_devices()
    coord._record_activity(device.id, None, entity_id, "2")
    _armed_and_silent(coord, device.id, 2.0)
    coord._judge_all_devices()
    assert len(_episodes(coord)) == 2


async def test_report_written_and_readable(hass: HomeAssistant):
    """The file exists, names the device, and shows the columns."""
    device, entity_id = _register(hass, "w1", "Written Sensor")
    coord = await _coordinator(hass)
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 2.0)
    coord._judge_all_devices()
    await hass.async_add_executor_job(coord._write_reports, "test")
    path = hass.config.path("device_sentinel", "silence_episodes.md")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert "silence episodes" in text
    assert "Written Sensor" in text
    assert "| SILENT SINCE | DEVICE |" in text
    assert "open" in text


async def test_empty_report_says_so(hass: HomeAssistant):
    coord = await _coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "test")
    path = hass.config.path("device_sentinel", "silence_episodes.md")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert "No device has been silent past its own rhythm" in text


async def test_episodes_reach_diagnostics(hass: HomeAssistant):
    from custom_components.device_sentinel.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    device, entity_id = _register(hass, "d1", "Diag Sensor")
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    hass.states.async_set(entity_id, "1")
    await hass.async_block_till_done()
    _armed_and_silent(coord, device.id, 2.0)
    coord._judge_all_devices()
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert "silence_episodes" in diag
    assert diag["silence_episodes"][0][EP_NAME] == "Diag Sensor"
