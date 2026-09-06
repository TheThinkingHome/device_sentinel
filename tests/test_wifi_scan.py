# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_scan.py, Version: 0.20.9 (2026-09-06)

"""WiFi detection read from the host's own radio.

Every number here was measured before it was ruled. A full night of
scans on a two satellite mesh, roughly two hundred sweeps at three
minute intervals: the near satellite was missing from one sweep, the
far one from fifty nine, and both from none at all. The one real
event was the nightly router reboot, thirty seconds, confirmed
independently by the host's own association dropping and returning.

That is why the rule is "any access point broadcasting the name"
rather than a signal threshold, and why the confirmation delay
defaults to sixty seconds.
"""

from __future__ import annotations

from typing import Any

import pytest

from homeassistant.core import Event, HomeAssistant, State
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    CONF_WIFI_CONFIRM_SECONDS,
    CONF_WIFI_NETWORKS,
)

from tests.helpers import setup_coordinator

IOT = "IKS_Rotarran-IoT"
HOUSE = "IKS_Rotarran"

# The two satellites of the reference mesh, near and far, with the
# signal figures the host actually read.
NEAR = {"mac": "5E:E9:31:5C:CE:3E", "ssid": IOT, "signal": 77,
        "frequency": 2422, "mode": "infrastructure"}
FAR = {"mac": "5E:E9:31:5C:CE:56", "ssid": IOT, "signal": 37,
       "frequency": 2422, "mode": "infrastructure"}
OTHER = {"mac": "5E:E9:31:2C:CE:3E", "ssid": HOUSE, "signal": 75,
         "frequency": 2422, "mode": "infrastructure"}


class FakeSupervisor:
    """The Supervisor, answering the two endpoints this reads.

    A fake rather than a mock: the shapes are copied from real
    captures, including that an interface carries no `wifi` block
    while it is disconnected.
    """

    def __init__(self, wireless: bool = True) -> None:
        self.points: list[dict[str, Any]] = [NEAR, FAR, OTHER]
        self.wireless = wireless
        self.fail = False
        self.scans = 0

    async def send_command(self, path: str, method: str = "get") -> dict:
        if self.fail:
            raise RuntimeError("supervisor is not answering")
        if path == "/network/info":
            rows = [
                {"interface": "enp2s0", "type": "ethernet",
                 "connected": True, "wifi": None},
            ]
            if self.wireless:
                rows.append({
                    "interface": "wlo1", "type": "wireless",
                    "connected": True,
                    "wifi": {"ssid": IOT, "signal": 77},
                })
            return {"data": {"interfaces": rows}}
        if path.endswith("/accesspoints"):
            self.scans += 1
            return {"data": {"accesspoints": list(self.points)}}
        raise AssertionError(f"unexpected path {path}")


@pytest.fixture(name="supervisor")
def supervisor_fixture(hass: HomeAssistant) -> FakeSupervisor:
    fake = FakeSupervisor()
    hass.data["hassio"] = fake
    return fake


async def _coord(hass, networks=(IOT,), confirm=60):
    return await setup_coordinator(hass, {
        CONF_WIFI_NETWORKS: list(networks),
        CONF_WIFI_CONFIRM_SECONDS: confirm,
    })


def _heard(coord):
    return coord.wifi_scan_diagnostics["heard"]


def _tie_four(coord) -> None:
    """Four watched devices tied to four router trackers."""
    coord._wifi_ties = {f"dev{i}": f"device_tracker.t{i}" for i in range(4)}
    coord._wifi_device_of = {v: k for k, v in coord._wifi_ties.items()}


def _tracker_left(hass, coord, index: int) -> None:
    """Drive one tracker from home to not_home through the listener.

    Through the listener rather than by setting the state it keeps,
    because the decision about which source may trigger lives there
    and a test that writes the state directly proves nothing about
    it.
    """
    entity_id = f"device_tracker.t{index}"
    attrs = {"source_type": "router", "connection": "IoT"}
    hass.states.async_set(entity_id, "home", attrs)
    coord._on_wifi_tracker_change(
        Event(
            "state_changed",
            {
                "entity_id": entity_id,
                "old_state": State(entity_id, "home", attrs),
                "new_state": State(entity_id, "not_home", attrs),
            },
        )
    )


# ------------------------------------------------------ what it hears


async def test_a_configured_house_hears_its_networks(
    hass: HomeAssistant, supervisor: FakeSupervisor
):
    """The first sweep finds the adapter and reads the radio."""
    coord = await _coord(hass)
    await coord.async_sweep_wifi()
    assert coord.wifi_scan_configured
    assert coord.wifi_scan_diagnostics["interface"] == "wlo1"
    assert set(_heard(coord)) == {IOT, HOUSE}
    assert coord.wifi_scan_down_at is None
    assert coord.wifi_missing_networks == []


async def test_a_house_with_no_adapter_does_nothing(
    hass: HomeAssistant, supervisor: FakeSupervisor
):
    """Most systems are in this state, and the router ties keep their
    own trigger there (#391)."""
    supervisor.wireless = False
    coord = await _coord(hass)
    await coord.async_sweep_wifi()
    assert not coord.wifi_scan_configured
    assert supervisor.scans == 0
    assert coord.wifi_scan_down_at is None


async def test_no_supervisor_is_absent_rather_than_broken(
    hass: HomeAssistant
):
    """A Core or Container install has no Supervisor at all."""
    coord = await _coord(hass)
    await coord.async_sweep_wifi()
    assert not coord.wifi_scan_configured
    assert coord.wifi_scan_down_at is None


async def test_choosing_nothing_costs_nothing(
    hass: HomeAssistant, supervisor: FakeSupervisor
):
    """No network chosen means the sweep returns on its first line."""
    coord = await _coord(hass, networks=())
    await coord.async_sweep_wifi()
    assert supervisor.scans == 0
    assert not coord.wifi_scan_configured


# ------------------------------------------------- any means up (#392)


async def test_one_satellite_is_enough(
    hass: HomeAssistant, supervisor: FakeSupervisor
):
    """The far satellite was missing from fifty nine sweeps of two
    hundred and it never mattered, because the near one was there.

    The rule is not a signal threshold: a weak reading means the host
    is far from that access point, not that the access point is
    failing.
    """
    coord = await _coord(hass)
    supervisor.points = [NEAR, OTHER]
    await coord.async_sweep_wifi()
    assert coord.wifi_scan_down_at is None
    assert coord.wifi_scan_diagnostics["gone_at"] is None

    # And the other way round: only the far one, at signal 37.
    supervisor.points = [FAR, OTHER]
    await coord.async_sweep_wifi()
    assert coord.wifi_scan_down_at is None


async def test_every_satellite_gone_starts_the_hold(
    hass: HomeAssistant, supervisor: FakeSupervisor
):
    """Nothing is reported until the delay passes."""
    coord = await _coord(hass)
    await coord.async_sweep_wifi()
    supervisor.points = [OTHER]
    await coord.async_sweep_wifi()
    assert coord.wifi_scan_down_at is None
    assert coord.wifi_scan_diagnostics["gone_at"] is not None
    assert coord.wifi_missing_networks == [IOT]


async def test_the_outage_is_dated_from_when_it_went(
    hass: HomeAssistant, supervisor: FakeSupervisor, freezer
):
    """Not from when the delay expired, so the reported length is the
    real one."""
    coord = await _coord(hass)
    await coord.async_sweep_wifi()

    supervisor.points = [OTHER]
    await coord.async_sweep_wifi()
    gone_at = coord.wifi_scan_diagnostics["gone_at"]

    from datetime import timedelta

    freezer.tick(timedelta(seconds=65))
    await coord.async_sweep_wifi()
    assert coord.wifi_scan_down_at is not None
    assert abs(coord.wifi_scan_down_at - gone_at) < 1.0


async def test_the_nightly_reboot_is_absorbed(
    hass: HomeAssistant, supervisor: FakeSupervisor, freezer
):
    """The one real event a full night contained: the router rebooted
    and the near satellite was missing from a single sweep, thirty
    seconds. A sixty second delay covers it twice over."""
    coord = await _coord(hass)
    await coord.async_sweep_wifi()

    from datetime import timedelta

    supervisor.points = [OTHER]
    await coord.async_sweep_wifi()
    freezer.tick(timedelta(seconds=30))
    supervisor.points = [NEAR, FAR, OTHER]
    await coord.async_sweep_wifi()

    assert coord.wifi_scan_down_at is None
    assert coord.wifi_scan_diagnostics["gone_at"] is None


async def test_the_delay_holds_across_repeated_sweeps(
    hass: HomeAssistant, supervisor: FakeSupervisor, freezer
):
    """Missing across several sweeps, but for less than the delay.

    Found by a control run: removing the confirmation delay entirely
    left every other test in this file green, because a network that
    goes missing sets its clock on the first sweep and can only be
    declared on a later one, and the reboot case recovers before that
    second sweep arrives. So nothing here was actually testing the
    delay; it was testing that two sweeps are needed.

    The reference fleet sweeps every sixty seconds and the delay
    defaults to sixty, so this shape happens whenever a sweep lands
    early in the window.
    """
    from datetime import timedelta

    coord = await _coord(hass)
    await coord.async_sweep_wifi()

    supervisor.points = [OTHER]
    for _ in range(4):
        await coord.async_sweep_wifi()
        freezer.tick(timedelta(seconds=10))
        assert coord.wifi_scan_down_at is None, (
            "declared before the delay had passed"
        )

    # Now past it.
    freezer.tick(timedelta(seconds=30))
    await coord.async_sweep_wifi()
    assert coord.wifi_scan_down_at is not None


async def test_recovery_closes_the_outage(
    hass: HomeAssistant, supervisor: FakeSupervisor, freezer
):
    coord = await _coord(hass)
    await coord.async_sweep_wifi()
    from datetime import timedelta

    supervisor.points = [OTHER]
    await coord.async_sweep_wifi()
    freezer.tick(timedelta(seconds=65))
    await coord.async_sweep_wifi()
    assert coord.wifi_scan_down_at is not None

    supervisor.points = [NEAR, OTHER]
    await coord.async_sweep_wifi()
    assert coord.wifi_scan_down_at is None
    assert coord.wifi_missing_networks == []


# --------------------------------------------------------- two networks


async def test_any_chosen_network_missing_is_an_outage(
    hass: HomeAssistant, supervisor: FakeSupervisor, freezer
):
    """Ruled, and the reason is a limitation stated plainly on the
    settings screen: Device Sentinel cannot tell which network a
    device is on, so it cannot tell whose devices are affected."""
    coord = await _coord(hass, networks=(IOT, HOUSE))
    await coord.async_sweep_wifi()
    from datetime import timedelta

    supervisor.points = [NEAR, FAR]
    await coord.async_sweep_wifi()
    freezer.tick(timedelta(seconds=65))
    await coord.async_sweep_wifi()
    assert coord.wifi_scan_down_at is not None
    assert coord.wifi_missing_networks == [HOUSE]


# ------------------------------------------------------- not answering


async def test_a_silent_supervisor_is_not_an_outage(
    hass: HomeAssistant, supervisor: FakeSupervisor, freezer
):
    """An unanswered question is not a missing network.

    Home Assistant shutting down stops the Supervisor answering, and
    treating that as an outage would declare one on every restart.
    """
    coord = await _coord(hass)
    await coord.async_sweep_wifi()
    from datetime import timedelta

    supervisor.fail = True
    for _ in range(5):
        freezer.tick(timedelta(seconds=65))
        await coord.async_sweep_wifi()
    assert coord.wifi_scan_down_at is None
    assert coord.wifi_scan_diagnostics["gone_at"] is None


async def test_a_chosen_network_that_is_never_heard_is_named(
    hass: HomeAssistant, supervisor: FakeSupervisor
):
    """A network renamed at the router and one that is down look the
    same from a picker, so the status sensor names it and the
    settings screen keeps it selected."""
    coord = await _coord(hass, networks=("Typo-Network",))
    await coord.async_sweep_wifi()
    assert coord.wifi_missing_networks == ["Typo-Network"]


# ------------------------------------------- which source triggers (#391)


async def test_the_scan_triggers_and_the_ties_stand_down(
    hass: HomeAssistant, supervisor: FakeSupervisor, freezer
):
    """Where the scan is configured it is primary, and the router
    ties no longer declare an outage of their own. They confirm and
    they count, which is what turns twenty individual reports into
    one line naming a cause.
    """
    from datetime import timedelta

    from custom_components.device_sentinel.const import (
        WIFI_BURST_FLOOR,
        WIFI_HOLD_SECONDS,
    )

    coord = await _coord(hass)
    await coord.async_sweep_wifi()
    assert coord.wifi_scan_configured

    # Enough tracker movement to have triggered before this ruling,
    # driven through the listener that owns the decision rather than
    # by setting the state it produces.
    coord._grace_until = 0.0
    _tie_four(coord)
    for index in range(WIFI_BURST_FLOOR + 1):
        _tracker_left(hass, coord, index)
    assert coord._wifi_hold_since is None, "the ties started a hold"
    coord._sample_wifi(dt_util.utcnow().timestamp() + WIFI_HOLD_SECONDS + 5)
    assert coord._wifi_down_at is None

    # The scan declares it, and the ties supply the count.
    supervisor.points = [OTHER]
    await coord.async_sweep_wifi()
    freezer.tick(timedelta(seconds=65))
    await coord.async_sweep_wifi()
    assert coord._wifi_down_at is not None
    assert coord.wifi_confirmation()["tied"] == 4
    assert coord.wifi_confirmation()["away"] == WIFI_BURST_FLOOR + 1


async def test_the_ties_still_trigger_without_a_scan(
    hass: HomeAssistant, supervisor: FakeSupervisor
):
    """A house with a supported router and no wireless adapter keeps
    exactly the detection it had before any of this existed. Most
    people are in that position."""
    from custom_components.device_sentinel.const import (
        WIFI_BURST_FLOOR,
        WIFI_HOLD_SECONDS,
    )

    supervisor.wireless = False
    coord = await _coord(hass)
    await coord.async_sweep_wifi()
    assert not coord.wifi_scan_configured

    coord._grace_until = 0.0
    _tie_four(coord)
    for index in range(WIFI_BURST_FLOOR):
        _tracker_left(hass, coord, index)
    assert coord._wifi_hold_since is not None, "the ties did not trigger"
    coord._sample_wifi(
        coord._wifi_hold_since + WIFI_HOLD_SECONDS + 5
    )
    assert coord._wifi_down_at is not None
