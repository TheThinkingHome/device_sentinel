# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_wifi_outage.py, Version: 0.20.6 (2026-09-05)

"""The Wi-Fi outage: the tie ladder, the burst, the hold, the claim.

Every number asserted here was measured on the reference fleet before
it was ruled: nine of seventeen watched trackers not_home inside
sixty seconds on a real outage, a worst ordinary burst of three that
the hold absorbed, and a tie coverage of thirteen of sixteen from the
two MAC rungs. The cases follow those shapes rather than inventing
new ones.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    EVENT_UPSTREAM_DOWN,
    EVENT_UPSTREAM_RESTORED,
    WIFI_BURST_FLOOR,
    WIFI_HOLD_SECONDS,
    WIFI_KEY,
)
from custom_components.device_sentinel.wifi import (
    normalize_mac,
    tracker_medium,
)

from tests.helpers import setup_coordinator


def _tracker(hass, uid: str, mac: str, state: str = "home"):
    """Register one router tracker with its own entity and no shared
    device, which is the separate-registry-device shape the reference
    fleet actually has."""
    entry = er.async_get(hass).async_get_or_create(
        "device_tracker", "tplink_router", uid
    )
    hass.states.async_set(
        entry.entity_id,
        state,
        {"source_type": "router", "mac": mac},
    )
    return entry.entity_id


def _wifi_device(hass, source, uid: str, name: str, mac: str | None,
                 identifier: str | None = None):
    """Register one watched Wi-Fi device, tied by MAC connection or
    by an identifier that embeds the full MAC, or by nothing."""
    connections = (
        {(dr.CONNECTION_NETWORK_MAC, mac)} if mac else set()
    )
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("wifi_hub", identifier or uid)},
        connections=connections,
        name=name,
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "wifi_hub", uid,
        device_id=device.id, config_entry=source,
    )
    return device


async def _house(hass, count: int = 4):
    """A hub with `count` Wi-Fi devices, each tied to a tracker by a
    normalized MAC, plus one device with no tracker at all."""
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    trackers, devices = [], []
    for index in range(count):
        mac = f"AA-BB-CC-00-00-{index:02X}"
        trackers.append(_tracker(hass, f"t{index}", mac))
        devices.append(
            _wifi_device(
                hass, source, f"d{index}", f"WiFi Device {index}",
                mac.lower().replace("-", ":"),
            )
        )
    untied = _wifi_device(hass, source, "lone", "No Tracker", None)
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    return coord, trackers, devices, untied


def _heard(hass):
    seen: list[tuple[str, dict]] = []
    hass.bus.async_listen(
        EVENT_UPSTREAM_DOWN,
        lambda e: seen.append(("down", dict(e.data))),
    )
    hass.bus.async_listen(
        EVENT_UPSTREAM_RESTORED,
        lambda e: seen.append(("restored", dict(e.data))),
    )
    return seen


async def _fall(hass, tracker: str):
    state = hass.states.get(tracker)
    hass.states.async_set(tracker, "not_home", dict(state.attributes))
    await hass.async_block_till_done()


async def _rise(hass, tracker: str):
    state = hass.states.get(tracker)
    hass.states.async_set(tracker, "home", dict(state.attributes))
    await hass.async_block_till_done()


# ---------------------------------------------------------- the ladder


def test_mac_normalization_is_one_canonical_form():
    """Dashes, colons, case and bare hex all reduce to one spelling,
    and anything that is not twelve hex characters reduces to
    nothing."""
    assert normalize_mac("AA-BB-CC-00-11-22") == "aabbcc001122"
    assert normalize_mac("aa:bb:cc:00:11:22") == "aabbcc001122"
    assert normalize_mac("aabbcc001122") == "aabbcc001122"
    assert normalize_mac("aabbcc0011") is None
    assert normalize_mac(None) is None
    assert normalize_mac(42) is None


async def test_the_mac_rung_ties_across_spellings(hass: HomeAssistant):
    """The router says dashes and upper case, the registry says colons
    and lower case, and the tie holds anyway."""
    coord, trackers, devices, untied = await _house(hass, 3)
    assert len(coord._wifi_ties) == 3
    for device, tracker in zip(devices, trackers):
        assert coord._wifi_ties[device.id] == tracker
    assert untied.id not in coord._wifi_ties
    assert coord.wifi_capable


async def test_the_identifier_rung_claims_the_nspanel_shape(
    hass: HomeAssistant,
):
    """A device whose identifier embeds the full twelve-hex MAC is
    tied, which is the shape the NSPanels actually have."""
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    tracker = _tracker(hass, "panel", "7C-88-99-B2-C8-2B")
    device = _wifi_device(
        hass, source, "panel_dev", "NSPanel Pro James", None,
        identifier="nspanelpro7c8899b2c82b",
    )
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    assert coord._wifi_ties.get(device.id) == tracker


async def test_a_matching_name_alone_ties_nothing(hass: HomeAssistant):
    """A device named exactly like its tracker but sharing no MAC is
    honestly unclaimed: people rename devices to be descriptive, and
    a wrong tie suppresses an innocent device's verdicts."""
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    _tracker(hass, "fp2", "54-EF-44-5E-83-4A")
    device = _wifi_device(
        hass, source, "fp2_dev", "Presence Guest", None
    )
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    assert device.id not in coord._wifi_ties
    assert not coord.wifi_capable


async def test_a_phone_tracker_ties_to_nothing(hass: HomeAssistant):
    """A tracker whose MAC matches no watched device feeds nothing,
    which is how 17 of 44 curates itself without a list."""
    coord, trackers, _devices, _untied = await _house(hass, 3)
    phone = _tracker(hass, "phone", "12-34-56-78-9A-BC")
    coord._rebuild_registry_view()
    assert phone not in coord._wifi_device_of
    assert len(coord._wifi_ties) == 3


# ------------------------------------------------- trigger, hold, claim


async def test_the_measured_outage_shape_declares(
    hass: HomeAssistant, freezer
):
    """Three tied trackers inside the window, still gone at the end of
    the hold: declared, dated from the first fall, membership count on
    the event, confirmation field present."""
    coord, trackers, devices, _ = await _house(hass, 4)
    seen = _heard(hass)

    first_fall = dt_util.utcnow().timestamp()
    for tracker in trackers[:3]:
        await _fall(hass, tracker)
    assert coord._wifi_hold_since is not None

    # Inside the hold: nothing, whatever the tick asks.
    coord._sample_wifi(first_fall + WIFI_HOLD_SECONDS - 5)
    await hass.async_block_till_done()
    assert seen == []
    assert coord.wifi_down_at is None

    # Past it: declared.
    freezer.tick(timedelta(seconds=WIFI_HOLD_SECONDS + 5))
    coord._sample_wifi(dt_util.utcnow().timestamp())
    await hass.async_block_till_done()

    assert [word for word, _ in seen] == ["down"], seen
    payload = seen[0][1]
    assert payload["kind"] == WIFI_KEY
    assert payload["name"] == WIFI_KEY
    assert payload["devices"] == 4
    assert "confirmed" in payload
    assert abs(coord.wifi_down_at - first_fall) < 2.0


async def test_two_trackers_never_trigger(hass: HomeAssistant, freezer):
    """One below the floor, over many ticks. The quiet case."""
    coord, trackers, _devices, _ = await _house(hass, 4)
    seen = _heard(hass)
    for tracker in trackers[:WIFI_BURST_FLOOR - 1]:
        await _fall(hass, tracker)
    now = dt_util.utcnow().timestamp()
    for tick in range(10):
        coord._sample_wifi(now + tick * 60.0)
    await hass.async_block_till_done()
    assert seen == []
    assert coord._wifi_hold_since is None


async def test_a_flap_clears_inside_the_hold(hass: HomeAssistant, freezer):
    """The 4 September wobble: three fall, all return before the hold
    ends, nothing is reported and the state is clean for next time."""
    coord, trackers, _devices, _ = await _house(hass, 4)
    seen = _heard(hass)
    for tracker in trackers[:3]:
        await _fall(hass, tracker)
    assert coord._wifi_hold_since is not None
    for tracker in trackers[:3]:
        await _rise(hass, tracker)

    freezer.tick(timedelta(seconds=WIFI_HOLD_SECONDS + 5))
    coord._sample_wifi(dt_util.utcnow().timestamp())
    await hass.async_block_till_done()
    assert seen == []
    assert coord.wifi_down_at is None
    assert coord._wifi_hold_since is None
    assert coord._wifi_burst == []


async def test_the_startup_grace_counts_nothing(hass: HomeAssistant):
    """Restored trackers flapping at boot are the outage's shape in
    miniature, and the grace is the only thing separating them."""
    coord, trackers, _devices, _ = await _house(hass, 4)
    seen = _heard(hass)
    coord._grace_until = dt_util.utcnow().timestamp() + 300.0
    for tracker in trackers[:3]:
        await _fall(hass, tracker)
    assert coord._wifi_hold_since is None
    assert coord._wifi_burst == []
    now = dt_util.utcnow().timestamp()
    coord._sample_wifi(now + 120.0)
    await hass.async_block_till_done()
    assert seen == []


async def test_a_router_reload_is_not_an_outage(hass: HomeAssistant):
    """Trackers going unavailable is the router integration failing,
    not stations leaving, and unavailable back to not_home carries no
    home before it, so neither shape feeds the burst."""
    coord, trackers, _devices, _ = await _house(hass, 4)
    for tracker in trackers[:3]:
        state = hass.states.get(tracker)
        hass.states.async_set(
            tracker, "unavailable", dict(state.attributes)
        )
    await hass.async_block_till_done()
    assert coord._wifi_hold_since is None
    for tracker in trackers[:3]:
        state = hass.states.get(tracker)
        hass.states.async_set(
            tracker, "not_home", dict(state.attributes)
        )
    await hass.async_block_till_done()
    assert coord._wifi_hold_since is None
    assert coord._wifi_burst == []


async def _declared(hass, coord, trackers, freezer, count=3):
    """Drive a declared outage and return the moment it began."""
    first = dt_util.utcnow().timestamp()
    for tracker in trackers[:count]:
        await _fall(hass, tracker)
    freezer.tick(timedelta(seconds=WIFI_HOLD_SECONDS + 5))
    coord._sample_wifi(dt_util.utcnow().timestamp())
    await hass.async_block_till_done()
    assert coord.wifi_down_at is not None
    return first


async def test_a_device_is_claimed_only_by_its_own_tracker(
    hass: HomeAssistant, freezer
):
    """During a declared outage: a tied device whose tracker is gone
    is claimed, a tied device whose tracker reads home is not, and a
    device with no tie never is."""
    coord, trackers, devices, untied = await _house(hass, 4)
    await _declared(hass, coord, trackers, freezer, count=3)

    for device in devices[:3]:
        found = coord.upstream_down_since(device.id)
        assert found is not None and found[0] == WIFI_KEY
    # The fourth tracker still reads home.
    assert coord.upstream_down_since(devices[3].id) is None
    assert coord.upstream_down_since(untied.id) is None


async def test_the_resolver_and_the_push_know_the_name(
    hass: HomeAssistant, freezer
):
    """The 0.20.2 lesson, applied before shipping instead of after:
    the row stamps and the push leaves once the outage settles."""
    coord, trackers, devices, _ = await _house(hass, 4)
    from custom_components.device_sentinel.const import (
        DATA_DEVICES,
        DEV_FROZEN_CATEGORY,
        DEV_FROZEN_SINCE,
    )
    first = await _declared(hass, coord, trackers, freezer, count=3)

    assert coord.upstream_down_since_for(WIFI_KEY) == coord.wifi_down_at

    # Verdicts land on the claimed devices, then the settle passes.
    for device in devices[:3]:
        record = coord.data[DATA_DEVICES][device.id]
        record[DEV_FROZEN_CATEGORY] = "unavailable"
        record[DEV_FROZEN_SINCE] = first + 90.0
    freezer.tick(timedelta(seconds=120))
    assert coord.suppressed_down_counts == {WIFI_KEY: 3}
    assert coord._upstream_messages() == [(WIFI_KEY, 3, False)]


async def test_the_broker_still_outranks_the_network(
    hass: HomeAssistant, freezer
):
    """Order is broker, then bridge, then wifi, then integration."""
    coord, trackers, devices, _ = await _house(hass, 4)
    await _declared(hass, coord, trackers, freezer, count=3)
    assert coord.upstream_down_since(devices[0].id)[0] == WIFI_KEY
    coord._broker_down_at = dt_util.utcnow().timestamp()
    found = coord.upstream_down_since(devices[0].id)
    assert found is not None and found[0] != WIFI_KEY


async def test_wifi_outranks_the_integration_rung(
    hass: HomeAssistant, freezer
):
    """A device claimed by its tracker is claimed by the surest
    witness, even while its config entry also reads down."""
    coord, trackers, devices, _ = await _house(hass, 4)
    await _declared(hass, coord, trackers, freezer, count=3)

    called: list[str] = []
    original = coord.integration_down_since

    def _spy(device_id):
        called.append(device_id)
        return original(device_id)

    coord.integration_down_since = _spy
    found = coord.upstream_down_since(devices[0].id)
    assert found is not None and found[0] == WIFI_KEY
    assert called == []


async def test_recovery_pairs_and_releases_the_claims(
    hass: HomeAssistant, freezer
):
    """Below the floor the outage closes: the restored half fires with
    the same membership, and every claim drops."""
    coord, trackers, devices, _ = await _house(hass, 4)
    seen = _heard(hass)
    await _declared(hass, coord, trackers, freezer, count=3)

    for tracker in trackers[:2]:
        await _rise(hass, tracker)
    freezer.tick(timedelta(seconds=30))
    coord._sample_wifi(dt_util.utcnow().timestamp())
    await hass.async_block_till_done()

    assert [word for word, _ in seen] == ["down", "restored"], seen
    assert seen[1][1]["devices"] == seen[0][1]["devices"] == 4
    assert seen[1][1]["for_seconds"] > 0.0
    assert coord.wifi_down_at is None
    for device in devices:
        assert coord.upstream_down_since(device.id) is None


async def test_a_house_with_no_ties_pays_nothing(hass: HomeAssistant):
    """The absent-capability case: no ties, no subscription, no
    sensor, and the sampler is a no-op."""
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    assert not coord.wifi_capable
    assert coord._wifi_unsub is None
    coord._sample_wifi(dt_util.utcnow().timestamp())
    assert coord.wifi_down_at is None


# ------------------------------------------------- the real boot order


async def test_the_real_boot_order_heals_itself(hass: HomeAssistant):
    """Found on the reference fleet the hour 0.20.3 deployed. At boot
    the tracker registry entries exist and their states do not,
    because the router integration has not polled; the ladder tied
    nothing and the create-once sensor check read the house as
    incapable forever. The retry gate holds while ties are empty and
    any tracker is stateless, and the tick heals it."""
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    device = _wifi_device(
        hass, source, "boot0", "WiFi Device Boot",
        "aa:bb:cc:00:00:00",
    )
    tracker = er.async_get(hass).async_get_or_create(
        "device_tracker", "tplink_router", "boot_t0"
    )
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()

    assert coord._wifi_ties == {}
    assert not coord.wifi_capable
    assert coord._wifi_retry_pending

    # The router polls; the state appears; the next tick ties.
    hass.states.async_set(
        tracker.entity_id, "home",
        {"source_type": "router", "mac": "AA-BB-CC-00-00-00"},
    )
    await hass.async_block_till_done()
    coord._sample_wifi(dt_util.utcnow().timestamp())

    assert coord._wifi_ties.get(device.id) == tracker.entity_id
    assert coord.wifi_capable
    assert not coord._wifi_retry_pending


async def test_a_house_of_phone_trackers_stops_looking(
    hass: HomeAssistant,
):
    """Phone trackers with states and no router: after one look the
    gate closes and the tick pays one boolean forever."""
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    _wifi_device(hass, source, "p0", "Some Device", None)
    phone = er.async_get(hass).async_get_or_create(
        "device_tracker", "mobile_app", "phone0"
    )
    hass.states.async_set(phone.entity_id, "home", {"source_type": "gps"})
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()

    assert not coord._wifi_retry_pending
    calls = []
    original = coord._rebuild_wifi_ties
    coord._rebuild_wifi_ties = lambda: calls.append(1) or original()
    coord._sample_wifi(dt_util.utcnow().timestamp())
    assert calls == []


async def test_the_sensor_arrives_when_the_capability_does(
    hass: HomeAssistant,
):
    """The platform sets up before the router polls, and the sensor
    still appears, once, on the first refresh with a tie."""
    from custom_components.device_sentinel import sensor as sensor_mod

    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    device = _wifi_device(
        hass, source, "late0", "WiFi Device Late",
        "aa:bb:cc:00:00:01",
    )
    tracker = er.async_get(hass).async_get_or_create(
        "device_tracker", "tplink_router", "late_t0"
    )
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()

    added: list = []

    class _Entry:
        runtime_data = coord

    await sensor_mod.async_setup_entry(
        hass, _Entry(), lambda ents, **kw: added.extend(ents)
    )
    names = [type(e).__name__ for e in added]
    assert "DeviceSentinelWifiSensor" not in names

    hass.states.async_set(
        tracker.entity_id, "home",
        {"source_type": "router", "mac": "AA-BB-CC-00-00-01"},
    )
    await hass.async_block_till_done()
    coord._sample_wifi(dt_util.utcnow().timestamp())
    assert coord._wifi_ties.get(device.id) == tracker.entity_id
    coord._notify()
    names = [type(e).__name__ for e in added]
    assert names.count("DeviceSentinelWifiSensor") == 1
    coord._notify()
    names = [type(e).__name__ for e in added]
    assert names.count("DeviceSentinelWifiSensor") == 1


async def test_diagnostics_carry_the_tie_table(hass: HomeAssistant):
    """The section that would have answered the live question without
    a template: tie count, the table, the retry gate, the outage."""
    coord, trackers, devices, _ = await _house(hass, 2)
    view = coord.wifi_diagnostics
    assert view["ties"] == 2
    assert view["retry_pending"] is False
    assert view["down_since"] is None
    assert set(view["tied"]) == {d.id for d in devices}


# --------------------------------------------------- wired and wireless


def test_the_medium_reader_knows_both_published_markers():
    """Read from source: TP-Link publishes `connection`, Fritz
    `connection_type`, and no integration publishes a positive wifi
    marker. Unifi and Fritz publish an SSID only when wireless."""
    assert tracker_medium({"connection": "wired"}) == "wired"
    assert tracker_medium({"connection_type": "LAN"}) == "wired"
    # TP-Link's wireless value is the network's own name, never
    # "wifi", which is why this is an exclusion and not an allow list.
    assert tracker_medium({"connection": "IoT"}) == "unknown"
    assert tracker_medium({"essid": "Home"}) == "wireless"
    assert tracker_medium({"ssid": "Home"}) == "wireless"
    # Wired wins, because it is the marker the ladder acts on.
    assert tracker_medium({"connection": "wired", "ssid": "Home"}) == "wired"
    # A house that publishes nothing keeps every tie it had.
    assert tracker_medium({}) == "unknown"
    assert tracker_medium(None) == "unknown"


async def test_a_wired_tracker_is_never_tied(hass: HomeAssistant):
    """The reference fleet's four PoE cameras and its printer tied
    themselves in on 0.20.4: MAC matching says nothing about medium,
    and a switch reboot could then have declared a Wi-Fi outage. The
    worst wired cluster measured was five inside sixty seconds,
    above the floor."""
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    camera = _wifi_device(
        hass, source, "cam0", "Camera Living Room",
        "ec:71:db:98:ad:44",
    )
    blind = _wifi_device(
        hass, source, "blind0", "Master City Blinds",
        "bc:ff:4d:28:3b:9b",
    )
    wired = er.async_get(hass).async_get_or_create(
        "device_tracker", "tplink_router", "cam_t0"
    )
    hass.states.async_set(
        wired.entity_id, "home",
        {
            "source_type": "router", "mac": "EC-71-DB-98-AD-44",
            "connection": "wired", "band": None,
        },
    )
    wireless = er.async_get(hass).async_get_or_create(
        "device_tracker", "tplink_router", "blind_t0"
    )
    hass.states.async_set(
        wireless.entity_id, "home",
        {
            "source_type": "router", "mac": "BC-FF-4D-28-3B-9B",
            "connection": "IoT", "band": "2G",
        },
    )
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()

    assert camera.id not in coord._wifi_ties
    assert coord._wifi_ties.get(blind.id) == wireless.entity_id
    assert coord._wifi_wired_skipped == [wired.entity_id]
    assert coord._wifi_medium_census.get("wired") == 1


async def test_a_wired_tracker_cannot_reach_the_floor(hass: HomeAssistant):
    """Three wired trackers leaving together says nothing, because
    none of them was ever tied."""
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    trackers = []
    for index in range(3):
        mac = f"EC-71-DB-00-00-{index:02X}"
        _wifi_device(
            hass, source, f"w{index}", f"Wired Device {index}",
            mac.lower().replace("-", ":"),
        )
        entry = er.async_get(hass).async_get_or_create(
            "device_tracker", "tplink_router", f"w_t{index}"
        )
        hass.states.async_set(
            entry.entity_id, "home",
            {
                "source_type": "router", "mac": mac,
                "connection": "wired",
            },
        )
        trackers.append(entry.entity_id)
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    seen = _heard(hass)

    assert coord._wifi_ties == {}
    assert not coord.wifi_capable
    for tracker in trackers:
        state = hass.states.get(tracker)
        hass.states.async_set(
            tracker, "not_home", dict(state.attributes)
        )
    await hass.async_block_till_done()
    assert coord._wifi_hold_since is None
    coord._sample_wifi(dt_util.utcnow().timestamp())
    await hass.async_block_till_done()
    assert seen == []


async def test_fritz_spelling_is_excluded_too(hass: HomeAssistant):
    """Fritz publishes connection_type LAN, read from its own
    CONNECTION_TYPE_LAN constant."""
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    device = _wifi_device(
        hass, source, "fz0", "Fritz Wired Device", "aa:bb:cc:dd:ee:ff"
    )
    entry = er.async_get(hass).async_get_or_create(
        "device_tracker", "fritz", "fz_t0"
    )
    hass.states.async_set(
        entry.entity_id, "home",
        {
            "source_type": "router", "mac": "AA-BB-CC-DD-EE-FF",
            "connection_type": "LAN",
        },
    )
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    assert device.id not in coord._wifi_ties


async def test_the_census_reaches_the_diagnostics(hass: HomeAssistant):
    """What was tied, what was skipped for being wired, and how the
    house's trackers divide by medium, all visible in a download."""
    coord, _trackers, _devices, _ = await _house(hass, 2)
    view = coord.wifi_diagnostics
    assert view["ties"] == 2
    assert "medium_census" in view
    assert view["wired_skipped"] == []


# ------------------------------------------- a tie must survive an outage


async def test_a_tie_survives_the_outage_it_exists_to_detect(
    hass: HomeAssistant,
):
    """Found on the reference fleet during the first live Wi-Fi test.

    An outage left seven wireless trackers reading wired while they
    were away, the ladder ran in that moment and skipped them, and
    nothing looked at them again: the tie set fell from twelve to six
    and was still six ten minutes after every attribute had recovered.
    A second outage would have been judged on half a fleet, and a
    third on fewer, each time silently.

    A medium is judged only while a tracker is home. An away tracker
    keeps what it was last judged to be, which is the #221 principle:
    a live reading confirms or doubts a classification, it does not
    decide one.
    """
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    device = _wifi_device(
        hass, source, "sv0", "Voice Assistant", "20:f8:3b:09:97:53"
    )
    tracker = er.async_get(hass).async_get_or_create(
        "device_tracker", "tplink_router", "sv_t0"
    )
    home_attrs = {"source_type": "router", "mac": "20-F8-3B-09-97-53",
                  "connection": "IoT", "band": "2G"}
    hass.states.async_set(tracker.entity_id, "home", home_attrs)
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    assert coord._wifi_ties.get(device.id) == tracker.entity_id

    # Away, and the router re-reports it without its network
    # attributes, which is what the live fleet actually did.
    hass.states.async_set(
        tracker.entity_id, "not_home",
        {"source_type": "router", "mac": "20-F8-3B-09-97-53",
         "connection": "wired", "band": None},
    )
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    assert coord._wifi_ties.get(device.id) == tracker.entity_id
    assert coord._wifi_wired_skipped == []

    hass.states.async_set(tracker.entity_id, "home", home_attrs)
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    assert coord._wifi_ties.get(device.id) == tracker.entity_id


async def test_a_skipped_tracker_rejoins_when_it_reads_wireless(
    hass: HomeAssistant,
):
    """The safety net, swept on the tick.

    However a tie is lost, it comes back on its own once the tracker
    is home and no longer reads wired. Without this the only way back
    from a wrong exclusion was a restart.
    """
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    device = _wifi_device(
        hass, source, "rj0", "Rejoining Device", "aa:bb:cc:11:22:33"
    )
    tracker = er.async_get(hass).async_get_or_create(
        "device_tracker", "tplink_router", "rj_t0"
    )
    # Home and genuinely wired at first, so it is properly skipped.
    hass.states.async_set(
        tracker.entity_id, "home",
        {"source_type": "router", "mac": "AA-BB-CC-11-22-33",
         "connection": "wired"},
    )
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    assert device.id not in coord._wifi_ties
    assert coord._wifi_wired_skipped == [tracker.entity_id]

    # Moved to Wi-Fi. The tick notices without being told.
    hass.states.async_set(
        tracker.entity_id, "home",
        {"source_type": "router", "mac": "AA-BB-CC-11-22-33",
         "connection": "IoT", "band": "2G"},
    )
    await hass.async_block_till_done()
    coord._sample_wifi(dt_util.utcnow().timestamp())
    assert coord._wifi_ties.get(device.id) == tracker.entity_id
    assert coord._wifi_wired_skipped == []


async def test_an_away_wired_tracker_stays_skipped(hass: HomeAssistant):
    """The reverse must also hold: remembering the medium must not
    quietly re-admit a wired device just because it went away."""
    source = MockConfigEntry(domain="wifi_hub", title="wifi hub")
    source.add_to_hass(hass)
    device = _wifi_device(
        hass, source, "aw0", "Wired Camera", "ec:71:db:98:ad:44"
    )
    tracker = er.async_get(hass).async_get_or_create(
        "device_tracker", "tplink_router", "aw_t0"
    )
    hass.states.async_set(
        tracker.entity_id, "home",
        {"source_type": "router", "mac": "EC-71-DB-98-AD-44",
         "connection": "wired"},
    )
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    assert device.id not in coord._wifi_ties

    # The switch reboots and the camera goes away, losing its marker.
    hass.states.async_set(
        tracker.entity_id, "not_home",
        {"source_type": "router", "mac": "EC-71-DB-98-AD-44"},
    )
    await hass.async_block_till_done()
    coord._rebuild_registry_view()
    assert device.id not in coord._wifi_ties, "a wired device was re-admitted"
