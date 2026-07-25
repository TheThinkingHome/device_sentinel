# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v095_pairing.py, Version: 0.9.5 (2026-07-25)

"""0.9.5 tests: a recovery during pairing is discarded, not learned.

When a Z2M device recovers while a pairing window is open, or within a
short grace after it closed, that recovery is a hand re-pair and its
gap must be set aside so it never widens the learned rhythm (#145).
These tests prove the reader's grace check and the coordinator override
that acts on it, including the fail-safe: no reader, or a device that is
not Z2M, leaves the ordinary taint decision untouched (#147).
"""

from types import SimpleNamespace

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.bridge import Z2MBridgeReader
from custom_components.device_sentinel.const import (
    PAIRING_GRACE_SECONDS_DEFAULT,
)


def _msg(payload):
    return SimpleNamespace(payload=payload)


async def test_grace_true_while_pairing_open(hass: HomeAssistant):
    """Pairing open now counts, regardless of grace."""
    r = Z2MBridgeReader(hass)
    r._on_state(_msg("online"))
    r._on_info(_msg('{"permit_join": true, "permit_join_end": 1}'))
    assert r.pairing_active_within(PAIRING_GRACE_SECONDS_DEFAULT, 10_000.0)


async def test_grace_true_just_after_close(hass: HomeAssistant):
    """A window that closed a moment ago still counts within grace, for
    a device that reports just after pairing ends."""
    r = Z2MBridgeReader(hass)
    r._on_state(_msg("online"))
    r._on_info(_msg('{"permit_join": true}'))
    r._on_info(_msg('{"permit_join": false}'))  # closes now
    closed = r._pairing_closed_at
    assert closed is not None
    # 30s after close, inside a 120s grace
    assert r.pairing_active_within(120.0, closed + 30.0)


async def test_grace_false_well_after_close(hass: HomeAssistant):
    """Long after the window closed, a recovery is not pairing-caused
    and falls back to the ordinary decision."""
    r = Z2MBridgeReader(hass)
    r._on_state(_msg("online"))
    r._on_info(_msg('{"permit_join": true}'))
    r._on_info(_msg('{"permit_join": false}'))
    closed = r._pairing_closed_at
    assert not r.pairing_active_within(120.0, closed + 600.0)


async def test_grace_false_when_never_paired(hass: HomeAssistant):
    """A bridge that has only ever been running never reports pairing
    active, so an ordinary recovery is never mistaken for a re-pair."""
    r = Z2MBridgeReader(hass)
    r._on_state(_msg("online"))
    r._on_info(_msg('{"permit_join": false}'))
    assert not r.pairing_active_within(120.0, 10_000.0)


async def test_override_discards_gap_during_pairing(hass: HomeAssistant):
    """The coordinator override: a Z2M device that recovers while its
    bridge is pairing has its gap discarded as a pairing intervention,
    not learned. Checked directly on the helper so the seam is proven
    without driving a full gap through the event bus."""
    from custom_components.device_sentinel.coordinator import (
        DeviceSentinelCoordinator,
    )

    # A minimal stand-in coordinator carrying just what the helper reads.
    reader = Z2MBridgeReader(hass)
    reader._on_state(_msg("online"))
    reader._on_info(_msg('{"permit_join": true, "permit_join_end": 1}'))

    coord = DeviceSentinelCoordinator.__new__(DeviceSentinelCoordinator)
    coord._bridge_readers = {"z2m": reader}
    coord._watched = {"dev_mqtt": "mqtt", "dev_zha": "zha"}

    # An mqtt (Z2M) device recovering during pairing is pairing-caused.
    assert coord._recovered_during_pairing("dev_mqtt", 10_000.0) is True
    # A non-mqtt device is not a Z2M pairing candidate.
    assert coord._recovered_during_pairing("dev_zha", 10_000.0) is False


async def test_override_falls_back_with_no_reader(hass: HomeAssistant):
    """The fail-safe: with no bridge reader, the pairing check returns
    False and the ordinary taint decision stands (#147)."""
    from custom_components.device_sentinel.coordinator import (
        DeviceSentinelCoordinator,
    )

    coord = DeviceSentinelCoordinator.__new__(DeviceSentinelCoordinator)
    coord._bridge_readers = {}
    coord._watched = {"dev_mqtt": "mqtt"}
    assert coord._recovered_during_pairing("dev_mqtt", 10_000.0) is False


async def test_retract_today_max_pulls_back_the_pairing_gap(
    hass: HomeAssistant,
):
    """A pairing gap that was the day's largest is retracted, so it
    never widens the learned rhythm; an unrelated larger max is kept."""
    from custom_components.device_sentinel.coordinator import (
        DeviceSentinelCoordinator,
    )
    from custom_components.device_sentinel.const import DEV_TODAY_MAX

    rec = {DEV_TODAY_MAX: 500.0}
    DeviceSentinelCoordinator._retract_today_max(rec, 500.0)
    assert rec[DEV_TODAY_MAX] is None

    rec2 = {DEV_TODAY_MAX: 900.0}
    DeviceSentinelCoordinator._retract_today_max(rec2, 500.0)
    assert rec2[DEV_TODAY_MAX] == 900.0  # unrelated larger max untouched
