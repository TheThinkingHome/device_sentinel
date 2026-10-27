# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_low_battery_clear.py, Version: 0.27.10 (2026-10-27)

"""A low battery clears only above the threshold plus 3, and says when it
crossed (rule BAT-03): 18 percent at the default 15 still reads low, and
the brief and the push read "battery crossed the threshold on Oct 24.
Its current level is 17%."
"""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_LOW_THRESHOLD,
    DATA_DEVICES,
    DEV_BATTERY_LOW,
    DEV_BATTERY_SINCE,
    DEV_BATTERY_VALUE,
)

from .helpers import setup_coordinator
from .test_battery import _battery_device


async def _low(hass, uid):
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    device, eids = _battery_device(hass, source, uid)
    coord = await setup_coordinator(hass, {CONF_LOW_THRESHOLD: 15})
    coord._grace_until = 0.0
    hass.states.async_set(eids["pct"], "15")
    await hass.async_block_till_done()
    record = coord.data[DATA_DEVICES][device.id]
    assert record[DEV_BATTERY_LOW] is True
    return coord, device, eids, record


async def test_17_and_18_still_read_low(hass: HomeAssistant):
    coord, _device, eids, record = await _low(hass, 3)
    for level in ("17", "18"):
        hass.states.async_set(eids["pct"], level)
        await hass.async_block_till_done()
        assert record[DEV_BATTERY_LOW] is True, level


async def test_above_18_it_clears(hass: HomeAssistant):
    coord, _device, eids, record = await _low(hass, 4)
    hass.states.async_set(eids["pct"], "19")
    await hass.async_block_till_done()
    assert record[DEV_BATTERY_LOW] is False


async def test_the_words_say_when_it_crossed_and_where_it_stands(hass: HomeAssistant):
    coord, device, _eids, record = await _low(hass, 5)
    record[DEV_BATTERY_SINCE] = "2026-10-24T15:00:00+00:00"
    record[DEV_BATTERY_VALUE] = 17.0
    said = coord._battery_phrase(device.id, False)
    assert said == "battery crossed the threshold on Oct 24. Its current level is 17%"
    assert "fell" not in said


async def test_back_above_the_line_no_number_is_given(hass: HomeAssistant):
    coord, device, _eids, record = await _low(hass, 6)
    record[DEV_BATTERY_VALUE] = 40.0
    assert coord._battery_phrase(device.id, False) == "battery read low, since recovered"


async def test_a_row_of_history_is_told_by_its_own_time(hass: HomeAssistant):
    """The brief's sentence puts the row's time before the current level,
    and a table row keeps its own crossing day, not the device's latest.
    """
    from custom_components.device_sentinel.const import DATA_INCIDENTS, INC_KIND, TODO_KIND_LOW_BATTERY

    coord, _device, _eids, record = await _low(hass, 7)
    row = [r for r in coord.data[DATA_INCIDENTS] if r.get(INC_KIND) == TODO_KIND_LOW_BATTERY][-1]
    record[DEV_BATTERY_SINCE] = "2026-10-24T15:00:00+00:00"
    record[DEV_BATTERY_VALUE] = 17.0
    sentence = coord._compose_event(row)
    assert "battery crossed the threshold at " in sentence
    assert sentence.endswith("Its current level is 17%.") or sentence.endswith("Its current level is 17%"), sentence
    # The table's cell names the row's own day, not the latest crossing.
    assert "Oct 24" not in coord._brief_phrase(row)
