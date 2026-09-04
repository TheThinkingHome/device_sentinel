# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_integration_outage_fleet_tim.py, Version: 0.20.1 (2026-09-04)

"""The integration outage, driven against the second fleet.

Not a unit test. Each case loads the fleet's own record into a live
coordinator, plants its devices across the integrations the fleet
actually runs, and puts them through the shapes a house produces.
The reference fleet's cases live in their own file; the split is by
fleet because every case pays that fleet's full registry build.

This fleet holds the case the whole feature was built for: a
controller integration with seventeen devices behind one entry,
which nothing on the reference fleet can produce.

Skips whole when the fleet files are absent, as every fleet case does.
"""

from __future__ import annotations

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    INTEGRATION_DOWN_DWELL_SECONDS,
)

from tests.conftest import FLEET_ABSENT
from tests.fleet_house import TIM, TIM_SHAPE, _fleet
from tests.test_upstream_events_fleet import _heard


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
async def test_a_controller_falls_on_the_second_fleet(
    hass: HomeAssistant,
):
    """The case this was built for, on the fleet that has it.

    Z-Wave and Matter reload their entry when the controller
    disconnects, which is the one shape the reference fleet cannot
    produce. Seventeen devices behind one entry.
    """
    coord, entries, behind, now = await _fleet(hass, TIM, TIM_SHAPE)
    seen = _heard(hass)

    entries["controller_hub"].mock_state(
        hass, ConfigEntryState.SETUP_RETRY
    )
    coord._sample_integrations(now + 1)
    coord._sample_integrations(
        now + INTEGRATION_DOWN_DWELL_SECONDS + 2
    )
    await hass.async_block_till_done()

    assert [word for word, _ in seen] == ["down"], seen
    assert seen[0][1]["devices"] == len(behind["controller_hub"])
    assert seen[0][1]["devices"] >= 15

    entries["controller_hub"].mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now + 900.0)
    await hass.async_block_till_done()

    assert [word for word, _ in seen] == ["down", "restored"]
    assert seen[1][1]["for_seconds"] > 800.0
    assert seen[1][1]["devices"] == seen[0][1]["devices"]
    for device, _ in behind["controller_hub"]:
        assert coord.upstream_down_since(device.id) is None


# ------------------------------------------------------------- at scale


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
async def test_every_integration_falls_at_once(hass: HomeAssistant):
    """Seven integrations down together on a 234 device fleet.

    One event each, naming its own devices, and no device is claimed
    by the wrong one.
    """
    coord, entries, behind, now = await _fleet(hass, TIM, TIM_SHAPE)
    seen = _heard(hass)

    for domain in TIM_SHAPE:
        entries[domain].mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    coord._sample_integrations(
        now + INTEGRATION_DOWN_DWELL_SECONDS + 2
    )
    await hass.async_block_till_done()

    said = {payload["name"]: payload for _word, payload in seen}
    assert set(said) == set(TIM_SHAPE), sorted(said)
    for domain, payload in said.items():
        assert payload["devices"] == len(behind[domain]), domain

    for domain, members in behind.items():
        if domain == "mqtt":
            continue
        for device, _ in members:
            found = coord.upstream_down_since(device.id)
            assert found is not None and found[0] == domain

    # And they all come back, each paired.
    for domain in TIM_SHAPE:
        entries[domain].mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now + 600.0)
    await hass.async_block_till_done()

    downs = [p["name"] for w, p in seen if w == "down"]
    backs = [p["name"] for w, p in seen if w == "restored"]
    assert sorted(downs) == sorted(backs)


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
async def test_an_upgrade_reloads_everything_and_says_nothing(
    hass: HomeAssistant,
):
    """Every entry dropped and back inside the dwell.

    This is what a Home Assistant upgrade looks like, and it is the
    reason the dwell exists. Without it an upgrade would announce an
    outage per integration on every fleet, every time.
    """
    coord, entries, behind, now = await _fleet(hass, TIM, TIM_SHAPE)
    seen = _heard(hass)

    for source in entries.values():
        source.mock_state(hass, ConfigEntryState.NOT_LOADED)
    coord._sample_integrations(now + 1)
    for source in entries.values():
        source.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    coord._sample_integrations(now + 5)
    for source in entries.values():
        source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(now + 11)
    await hass.async_block_till_done()

    assert seen == [], seen
    for _domain, members in behind.items():
        for device, _ in members:
            assert coord.upstream_down_since(device.id) is None
