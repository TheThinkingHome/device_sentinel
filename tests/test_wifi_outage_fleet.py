# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_outage_fleet.py, Version: 0.20.3 (2026-09-04)

"""The Wi-Fi outage, driven against both reference fleets.

The reference fleet gets the measured 3 September shape: thirteen
tied devices (the two MAC rungs' real coverage), nine trackers gone
inside the window, and the outage declared while every config entry
stays loaded, which is exactly the case the integration rung is
blind to. The second fleet has no router trackers at all, which is
the absent-capability case: no ties, no subscription, no sensor, no
cost, and 234 devices judged exactly as before.

Skips whole when the fleet files are absent, as every fleet case does.
"""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.const import (
    WIFI_HOLD_SECONDS,
    WIFI_KEY,
)

from tests.conftest import FLEET_ABSENT
from tests.fleet_house import JAMES, JAMES_SHAPE, TIM, TIM_SHAPE, _fleet
from tests.test_upstream_events_fleet import _heard


def _give_tracker(hass, device, index: int) -> str:
    """Give one fleet device a MAC connection and a router tracker
    carrying the same MAC in the router's own spelling."""
    mac = f"aa:bb:cc:dd:{index // 256:02x}:{index % 256:02x}"
    dr.async_get(hass).async_update_device(
        device.id,
        merge_connections={(dr.CONNECTION_NETWORK_MAC, mac)},
    )
    entry = er.async_get(hass).async_get_or_create(
        "device_tracker", "tplink_router", f"wt{index}"
    )
    hass.states.async_set(
        entry.entity_id,
        "home",
        {"source_type": "router", "mac": mac.upper().replace(":", "-")},
    )
    return entry.entity_id


@pytest.mark.skipif(not JAMES.exists(), reason=FLEET_ABSENT)
async def test_the_measured_outage_on_the_reference_fleet(
    hass: HomeAssistant,
):
    """Thirteen tied, nine gone, entries all loaded: one Wi-Fi event
    carrying the membership, the claims on exactly the fallen nine,
    the Zigbee stack untouched, and the integration rung silent."""
    coord, entries, behind, now = await _fleet(hass, JAMES, JAMES_SHAPE)

    # Thirteen ties across the no-reader domains, the fleet's real
    # coverage from the two MAC rungs.
    tied = []
    for domain in (
        "blinds_hub", "presence_hub", "node_hub", "relay_hub",
        "camera_hub",
    ):
        for device, _record in behind[domain]:
            if len(tied) >= 13:
                break
            tied.append((device, _give_tracker(hass, device, len(tied))))
    coord._rebuild_registry_view()
    assert len(coord._wifi_ties) == 13
    seen = _heard(hass)

    for _device, tracker in tied[:9]:
        state = hass.states.get(tracker)
        hass.states.async_set(
            tracker, "not_home", dict(state.attributes)
        )
    await hass.async_block_till_done()

    hold_since = coord._wifi_hold_since
    assert hold_since is not None
    coord._sample_wifi(hold_since + WIFI_HOLD_SECONDS + 5)
    await hass.async_block_till_done()

    assert [word for word, _ in seen] == ["down"], seen
    payload = seen[0][1]
    assert payload["kind"] == WIFI_KEY
    assert payload["devices"] == 13
    assert "confirmed" in payload

    # The claims follow the fallen trackers and nothing else.
    for device, _tracker in tied[:9]:
        found = coord.upstream_down_since(device.id)
        assert found is not None and found[0] == WIFI_KEY
    for device, _tracker in tied[9:]:
        assert coord.upstream_down_since(device.id) is None
    for device, _record in behind["mqtt"][:20]:
        assert coord.upstream_down_since(device.id) is None

    # Recovery pairs once the floor is no longer met.
    for _device, tracker in tied[:8]:
        state = hass.states.get(tracker)
        hass.states.async_set(tracker, "home", dict(state.attributes))
    await hass.async_block_till_done()
    coord._sample_wifi(hold_since + WIFI_HOLD_SECONDS + 120)
    await hass.async_block_till_done()
    assert [word for word, _ in seen] == ["down", "restored"]
    assert seen[1][1]["devices"] == 13


@pytest.mark.skipif(not TIM.exists(), reason=FLEET_ABSENT)
async def test_the_second_fleet_pays_nothing(hass: HomeAssistant):
    """No router trackers anywhere: the capability does not exist for
    this house and must cost it nothing. No ties, no subscription,
    and a day of ticks says nothing on the bus."""
    coord, _entries, behind, now = await _fleet(hass, TIM, TIM_SHAPE)
    seen = _heard(hass)

    assert not coord.wifi_capable
    assert coord._wifi_unsub is None
    for tick in range(60):
        coord._sample_wifi(now + tick * 60.0)
    await hass.async_block_till_done()
    assert seen == []
    assert coord.wifi_down_at is None
    for _domain, members in behind.items():
        for device, _record in members[:5]:
            assert coord.upstream_down_since(device.id) is None
