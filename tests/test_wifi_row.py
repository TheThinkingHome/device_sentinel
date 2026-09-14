# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_row.py, Version: 0.21.3 (2026-09-14)

"""The row a Wi-Fi outage writes. Rulings #411 to #414.

Written before the change, and every case here fails against 0.21.1.

The fault the second fleet reported: a staged outage took down
forty-odd devices and the problem list showed every one of them
individually with no cause. The row builder, its wording and its
suppression all existed and worked for Zigbee2MQTT and ZHA. Only the
claim's lifetime was wrong.

A device is claimed while its own tracker reads not_home. Trackers
lead and verdicts trail: the trackers were home 76 seconds after the
peak, while the entities behind them were still going unavailable on
their own timers, 41 seconds to four minutes on the measured
3 September outage. So the casualties reached the problem list after
the claim that would have gathered them had expired.

#411 An outage claims every device that failed inside it, for the
     life of the outage, rather than only while that device's own
     tracker is away.
#412 Except a device a radio stack owns. Zigbee, Z-Wave and Matter
     hardware has its own bridge rung and its own medium. Ownership
     is asked of the bridge rather than the integration domain,
     because Z2M devices arrive through MQTT discovery and carry the
     mqtt domain, which would claim every MQTT device in the house.
#413 A wired device is counted among an outage's casualties even
     though a wired tracker is never counted toward declaring one.
     Declaring wants precision; attributing wants coverage.
#414 The outage names the network it belongs to.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    UPSTREAM_KIND,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    WIFI_KEY,
)

from tests.test_wifi_outage import _declared, _house, _rise, _wifi_device


def _judge(coord, devices, when: float) -> None:
    """Land an unavailable verdict, as the detector would once the
    entities have been unavailable long enough."""
    for device in devices:
        record = coord.data[DATA_DEVICES][device.id]
        record[DEV_FROZEN_CATEGORY] = "unavailable"
        record[DEV_FROZEN_SINCE] = when


# ------------------------------------------------------------- #411


async def test_the_claim_outlives_the_tracker_coming_home(
    hass: HomeAssistant, freezer
):
    """The defect. Ten fall, the trackers come home a minute into the
    recovery, and the verdicts land after that. Every one of them is
    still a casualty of the outage."""
    coord, trackers, devices, _untied = await _house(hass, 14)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)

    for tracker in trackers[:7]:
        await _rise(hass, tracker)
    await hass.async_block_till_done()
    assert coord.wifi_down_at is not None

    _judge(coord, devices[:7], first + 90.0)
    freezer.tick(timedelta(seconds=120))

    for device in devices[:7]:
        found = coord.upstream_down_since(device.id)
        assert found is not None and found[0] == WIFI_KEY, device.id


async def test_the_row_is_written_rather_than_each_device(
    hass: HomeAssistant, freezer
):
    """One row naming the outage, and the casualties counted rather
    than listed. This is what the second fleet did not get.

    Ten fell and seven have been judged down so far. The row counts
    ten: the devices the outage took, not the verdicts that have
    caught up. Asserted the other way round until the staged outage
    of 14 September showed what that reads like on a screen, where
    the row crawled from 1 to 10 over thirteen minutes while the
    network had been down the whole time.
    """
    coord, trackers, devices, _untied = await _house(hass, 14)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)

    for tracker in trackers[:7]:
        await _rise(hass, tracker)
    _judge(coord, devices[:7], first + 90.0)
    freezer.tick(timedelta(seconds=120))

    assert coord.suppressed_down_counts == {WIFI_KEY: 10}


async def test_a_device_whose_tracker_stayed_home_is_still_claimed(
    hass: HomeAssistant, freezer
):
    """A tracker reading home is not evidence the device is well.

    Written the other way round first, on the reasoning that a router
    still listing a device proves it could reach it. That is a weak
    signal read as a strong one: the router may be holding a stale
    entry, the device may be asleep, or it may be frozen for its own
    reason. Nothing is known from it, so the window claims it like
    anything else that failed inside the outage.

    The cost is small because the claim ends with the outage (#426).
    A device that really is broken on its own becomes its own row
    minutes later. The cost of the opposite is a row nobody can
    explain sitting beside the outage row, which is the fault this
    release exists to fix.
    """
    coord, trackers, devices, _untied = await _house(hass, 14)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)

    _judge(coord, devices[12:13], first + 90.0)
    freezer.tick(timedelta(seconds=120))

    found = coord.upstream_down_since(devices[12].id)
    assert found is not None and found[0] == WIFI_KEY


async def test_a_device_that_failed_before_the_outage_is_not_claimed(
    hass: HomeAssistant, freezer
):
    """The control that survives. The window is the outage, so a
    device already down when it began is not a casualty of it."""
    coord, trackers, devices, _untied = await _house(hass, 14)

    _judge(coord, devices[12:13], 1.0)
    await _declared(hass, coord, trackers[:10], freezer, count=10)
    freezer.tick(timedelta(seconds=120))

    assert coord.upstream_down_since(devices[12].id) is None


async def test_the_claim_ends_with_the_outage(
    hass: HomeAssistant, freezer
):
    """For the life of the outage and no longer (#426). Once it
    closes, whatever is still down is its own problem."""
    coord, trackers, devices, _untied = await _house(hass, 10)
    first = await _declared(hass, coord, trackers, freezer, count=10)

    for tracker in trackers:
        await _rise(hass, tracker)
    _judge(coord, devices[:4], first + 90.0)
    for step in range(3):
        coord._sample_wifi(first + 120.0 + step * 60.0)
        await hass.async_block_till_done()
    assert coord.wifi_down_at is None

    for device in devices[:4]:
        assert coord.upstream_down_since(device.id) is None


# ------------------------------------------------------------- #412


async def test_a_radio_device_is_not_claimed(
    hass: HomeAssistant, freezer
):
    """A Zigbee sensor that died during the outage has its own bridge
    rung and its own medium, so the network does not explain it."""
    coord, trackers, devices, untied = await _house(hass, 14)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)

    radio = untied
    coord._watched[radio.id] = "mqtt"
    coord._radio_owned.add(radio.id)
    _judge(coord, [radio], first + 90.0)
    freezer.tick(timedelta(seconds=120))

    assert coord.upstream_down_since(radio.id) is None


async def test_ownership_is_asked_of_the_bridge_not_the_domain(
    hass: HomeAssistant, freezer
):
    """An MQTT device the Z2M bridge does not know is not Zigbee's.

    The reference fleet's two NSPanel Pros are MQTT and Wi-Fi: they
    publish their own discovery and carry no Z2M identifier. A test
    on the domain would claim every MQTT device in that house as
    Zigbee's, which is right for almost all of it and wrong for them.
    """
    coord, trackers, devices, untied = await _house(hass, 14)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)

    panel = _wifi_device(
        hass, coord.entry, "nspanel", "NSPanel Pro James", None
    )
    coord._watched[panel.id] = "mqtt"
    # No Z2M identifier, so the bridge does not own it.
    assert panel.id not in coord._radio_owned
    _judge(coord, [panel], first + 90.0)
    freezer.tick(timedelta(seconds=120))

    found = coord.upstream_down_since(panel.id)
    assert found is not None and found[0] == WIFI_KEY


# ------------------------------------------------------------- #413


async def test_a_wired_device_is_counted_among_the_casualties(
    hass: HomeAssistant, freezer
):
    """Deliberately the opposite of #388, which keeps a wired tracker
    out of the count that declares an outage. Declaring wants
    precision; attributing wants coverage."""
    coord, trackers, devices, _untied = await _house(hass, 14)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)

    wired = devices[11]
    coord._wifi_wired_skipped.append(trackers[11])
    _judge(coord, [wired], first + 90.0)
    freezer.tick(timedelta(seconds=120))

    found = coord.upstream_down_since(wired.id)
    assert found is not None and found[0] == WIFI_KEY


# ------------------------------------------------------------- #414


async def test_the_row_names_the_network(hass: HomeAssistant, freezer):
    """The person reads the row, not the tie table."""
    coord, trackers, devices, _untied = await _house(hass, 14)
    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, "wifi_networks": ["IKS_Rotarran-IoT"]},
    )
    await hass.async_block_till_done()
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)
    _judge(coord, devices[:7], first + 90.0)
    freezer.tick(timedelta(seconds=120))

    summary, description = coord._upstream_item_text(
        WIFI_KEY, {UPSTREAM_KIND: first}, 7
    )
    assert summary == "WiFi network unavailable: 7 of 14 devices down"
    assert "'IKS_Rotarran-IoT' WiFi network became unavailable" in description
    assert "7 of its 14 managed devices" in description


async def test_the_wording_without_a_network(hass: HomeAssistant, freezer):
    """A house with none configured still gets a sentence."""
    coord, trackers, devices, _untied = await _house(hass, 14)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)
    _judge(coord, devices[:7], first + 90.0)
    freezer.tick(timedelta(seconds=120))

    _summary, description = coord._upstream_item_text(
        WIFI_KEY, {UPSTREAM_KIND: first}, 7
    )
    assert description.startswith(
        "Home Assistant's WiFi network became unavailable"
    )


async def test_the_wording_with_two_networks(hass: HomeAssistant, freezer):
    """Both are named. Unmeasured: no fleet has two configured."""
    coord, trackers, devices, _untied = await _house(hass, 14)
    hass.config_entries.async_update_entry(
        coord.entry,
        options={
            **coord.entry.options,
            "wifi_networks": ["IKS_Rotarran-IoT", "IKS_Rotarran"],
        },
    )
    await hass.async_block_till_done()
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)
    _judge(coord, devices[:7], first + 90.0)
    freezer.tick(timedelta(seconds=120))

    _summary, description = coord._upstream_item_text(
        WIFI_KEY, {UPSTREAM_KIND: first}, 7
    )
    assert (
        "The 'IKS_Rotarran-IoT' and 'IKS_Rotarran' WiFi networks became "
        "unavailable" in description
    )
    # "its" has no referent with two named.
    assert "of their 14 managed devices" in description
    assert " of its " not in description


# ------------------------------------------ the other instrumentation


async def test_the_sensor_publishes_the_recovery(
    hass: HomeAssistant, freezer
):
    """The probe can only record what the integration publishes.

    Today the Wi-Fi sensor publishes three fields and none of them is
    the recovery, so a staged outage shows the declare and the clear
    with nothing in between, which is exactly where the settle is
    decided.
    """
    coord, trackers, _devices, _untied = await _house(hass, 14)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)

    published = coord.wifi_attributes
    assert published["fallen"] == 10
    assert published["returned"] == 0
    assert published["announced"] is False
    assert published["threshold"] == 3
    assert published["recovery_needed"] == 4

    for tracker in trackers[:6]:
        await _rise(hass, tracker)
    coord._sample_wifi(first + 120.0)
    await hass.async_block_till_done()

    published = coord.wifi_attributes
    assert published["returned"] == 6
    assert published["announced"] is True
    assert published["quiet_ticks"] == 0


# ------------------------------------- the staged outage of 14 September


async def test_the_fallen_set_holds_every_tracker_that_is_away(
    hass: HomeAssistant, freezer
):
    """Found by a staged outage on hardware, not by this suite.

    The trackers do not fall in one instant. On 14 September they
    fell across several minutes, and the burst window is pruned to
    sixty seconds on every fall, so the outage's start time kept
    moving forward. The fallen set was seeded from the trackers whose
    fall time was at or after that start, and by the time the
    threshold was reached the start had moved past all of them: the
    set was empty at declaration with eleven trackers away.

    Every case in this file until now landed its falls in the same
    instant, so the prune never moved and the defect could not
    appear.
    """
    coord, trackers, _devices, _untied = await _house(hass, 12)
    coord._grace_until = 0.0

    # Five fall, then a gap longer than the burst window, then five
    # more. The shape of a real outage rather than a test's.
    for tracker in trackers[:5]:
        state = hass.states.get(tracker)
        hass.states.async_set(tracker, "not_home", dict(state.attributes))
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=90))
    for tracker in trackers[5:10]:
        state = hass.states.get(tracker)
        hass.states.async_set(tracker, "not_home", dict(state.attributes))
    await hass.async_block_till_done()

    assert coord._wifi_hold_since is not None
    coord._sample_wifi(coord._wifi_hold_since + 65.0)
    await hass.async_block_till_done()

    assert coord.wifi_down_at is not None
    assert len(coord.wifi_fallen_set) == 10, coord.wifi_fallen_set


async def test_the_count_is_the_devices_the_outage_took(
    hass: HomeAssistant, freezer
):
    """The row counts devices the outage took, not devices Home
    Assistant has finished marking down.

    On 14 September the row read 1 of 12 four minutes in, then 3, then
    4, then 10 at thirteen minutes, because it was counting freeze
    verdicts landing one at a time. The network was down and ten
    devices were on it from the first minute.
    """
    coord, trackers, _devices, _untied = await _house(hass, 12)
    first = await _declared(hass, coord, trackers[:10], freezer, count=10)

    # Not one verdict has landed yet.
    assert coord.suppressed_down_counts == {WIFI_KEY: 10}
    summary, _body = coord._upstream_item_text(
        WIFI_KEY, {UPSTREAM_KIND: first}, 10
    )
    assert summary == "WiFi network unavailable: 10 of 12 devices down"


async def test_the_scan_route_builds_a_fallen_set_too(
    hass: HomeAssistant, freezer
):
    """The route nothing covered, found by hardware.

    A house that can hear its own radio declares from the scan (#391)
    and the tie burst is switched off entirely. 0.21.1 built the
    fallen set in the tie route alone, so on the reference system,
    which has a network configured, there was never a fallen set at
    all: the sensor published `fallen=0` with eleven trackers away,
    the claim had nothing to work from, and the recovery closed on
    two returns against a threshold of one.

    Neither fleet file configures a network and no constructed house
    did either, which is why two fleet replays and a full gate all
    passed over it.
    """
    coord, trackers, _devices, _untied = await _house(hass, 12)
    coord._grace_until = 0.0
    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, "wifi_networks": ["IKS_Rotarran-IoT"]},
    )
    await hass.async_block_till_done()

    for tracker in trackers[:10]:
        state = hass.states.get(tracker)
        hass.states.async_set(tracker, "not_home", dict(state.attributes))
    await hass.async_block_till_done()

    since = dt_util.utcnow().timestamp()
    coord.on_wifi_scan_down(since, ["IKS_Rotarran-IoT"])
    await hass.async_block_till_done()

    assert coord.wifi_down_at is not None
    assert len(coord.wifi_fallen_set) == 10
    assert coord.wifi_casualties == 10
    assert coord.suppressed_down_counts == {WIFI_KEY: 10}
    assert coord.wifi_attributes["fallen"] == 10
