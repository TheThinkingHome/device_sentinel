# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_integration_outage_fleet_james.py, Version: 0.20.1 (2026-09-04)

"""The integration outage, driven against the reference fleet.

Not a unit test. Each case loads the fleet's own record into a live
coordinator, plants its devices across the integrations the fleet
actually runs, and puts them through the shapes a house produces.
The second fleet's cases live in their own file; the split is by
fleet because every case pays that fleet's full registry build.

Two questions are asked throughout. Does the new rung report the
integration where nothing else can, and does it leave alone
everything that worked before it existed.

Skips whole when the fleet files are absent, as every fleet case does.
"""

from __future__ import annotations

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    INTEGRATION_DOWN_DWELL_SECONDS,
)

from tests.conftest import FLEET_ABSENT
from tests.fleet_house import JAMES, JAMES_SHAPE, _fleet
from tests.test_upstream_events_fleet import _heard, _stub


# ------------------------------------------------------- one at a time


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
async def test_one_integration_falls_on_the_reference_fleet(
    hass: HomeAssistant,
):
    """The blinds hub goes, and its six devices are reported as it."""
    coord, entries, behind, now = await _fleet(hass, JAMES, JAMES_SHAPE)
    seen = _heard(hass)

    entries["blinds_hub"].mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    coord._sample_integrations(
        now + INTEGRATION_DOWN_DWELL_SECONDS + 2
    )
    await hass.async_block_till_done()

    assert [word for word, _ in seen] == ["down"], seen
    assert seen[0][1]["kind"] == "integration"
    assert seen[0][1]["name"] == "blinds_hub"
    assert seen[0][1]["devices"] == len(behind["blinds_hub"])

    for device, _ in behind["blinds_hub"]:
        found = coord.upstream_down_since(device.id)
        assert found is not None and found[0] == "blinds_hub"

    # Nobody else is touched.
    for domain, members in behind.items():
        if domain == "blinds_hub":
            continue
        for device, _ in members:
            assert coord.upstream_down_since(device.id) is None


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
async def test_an_integration_that_will_not_settle(
    hass: HomeAssistant,
):
    """Twenty cycles, each one past the dwell.

    Every failure is answered, and the count never drifts.
    """
    coord, entries, behind, now = await _fleet(hass, JAMES, JAMES_SHAPE)
    seen = _heard(hass)
    source = entries["camera_hub"]

    clock = now
    for _cycle in range(20):
        source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
        clock += 1
        coord._sample_integrations(clock)
        clock += INTEGRATION_DOWN_DWELL_SECONDS + 1
        coord._sample_integrations(clock)
        source.mock_state(hass, ConfigEntryState.LOADED)
        clock += INTEGRATION_DOWN_DWELL_SECONDS + 1
        coord._sample_integrations(clock)
    await hass.async_block_till_done()

    words = [word for word, _ in seen]
    assert words == ["down", "restored"] * 20, len(words)
    counts = {payload["devices"] for _w, payload in seen}
    assert counts == {len(behind["camera_hub"])}, counts


# ------------------------------------------- nothing else has changed


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
async def test_the_zigbee_stack_still_answers_for_itself(
    hass: HomeAssistant,
):
    """A bridge outage is a bridge outage, exactly as before.

    The Zigbee devices carry the bulk of both fleets. If the new rung
    reached them, every bridge outage would be reported twice or
    reported wrongly, so this is the regression that matters most.
    """
    coord, entries, behind, now = await _fleet(hass, JAMES, JAMES_SHAPE)
    seen = _heard(hass)

    # The Zigbee entry falls too, which must change nothing: the
    # bridge answers for those devices and the rung must not.
    entries["mqtt"].mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    coord._sample_integrations(
        now + INTEGRATION_DOWN_DWELL_SECONDS + 2
    )
    await hass.async_block_till_done()
    assert seen == [], seen
    for device, _ in behind["mqtt"]:
        assert coord.upstream_down_since(device.id) is None

    # Now the bridge itself goes, which is the old path.
    coord._bridge_readers["z2m"] = _stub(BRIDGE_DOWN)
    coord._sample_bridges()
    await hass.async_block_till_done()

    assert [word for word, _ in seen] == ["down"], seen
    assert seen[0][1]["kind"] == "bridge"
    assert seen[0][1]["name"] == "z2m"
    for device, _ in behind["mqtt"]:
        found = coord.upstream_down_since(device.id)
        assert found is not None and found[0] == "z2m"

    coord._bridge_readers["z2m"] = _stub(BRIDGE_RUNNING)
    coord._sample_bridges()
    await hass.async_block_till_done()
    assert [word for word, _ in seen] == ["down", "restored"]


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
async def test_the_broker_still_outranks_everything(
    hass: HomeAssistant,
):
    """Order is broker, then bridge, then integration (ruling #264)."""
    coord, entries, behind, now = await _fleet(hass, JAMES, JAMES_SHAPE)

    entries["blinds_hub"].mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(now + 1)
    coord._sample_integrations(
        now + INTEGRATION_DOWN_DWELL_SECONDS + 2
    )
    device = behind["blinds_hub"][0][0]
    assert coord.upstream_down_since(device.id)[0] == "blinds_hub"

    coord._broker_down_at = now
    for domain, members in behind.items():
        for member, _ in members:
            found = coord.upstream_down_since(member.id)
            assert found is not None
            assert found[0] != domain or domain == "mqtt", domain


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
async def test_a_healthy_fleet_says_nothing_at_all(
    hass: HomeAssistant,
):
    """Every entry loaded, every bridge up, over many samples.

    The quiet case, which is the one a person lives in. A detector
    that speaks here is worse than one that never speaks at all.
    """
    coord, _entries, behind, now = await _fleet(
        hass, JAMES, JAMES_SHAPE
    )
    seen = _heard(hass)

    for tick in range(60):
        coord._sample_integrations(now + tick * 30.0)
        coord._sample_bridges()
    await hass.async_block_till_done()

    assert seen == [], seen
    for _domain, members in behind.items():
        for device, _ in members:
            assert coord.upstream_down_since(device.id) is None
