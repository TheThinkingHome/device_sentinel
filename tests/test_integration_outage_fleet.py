# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_integration_outage_fleet.py, Version: 0.20.1 (2026-09-04)

"""The integration outage, driven against both reference fleets.

Not a unit test. Each case loads a real fleet's own record into a
live coordinator, plants its devices across the integrations that
fleet actually runs, and then puts them through the shapes a house
produces: one integration falling, several at once, an upgrade that
reloads everything, and a Zigbee stack that must answer for itself.

Two questions are asked throughout. Does the new rung report the
integration where nothing else can, and does it leave alone
everything that worked before it existed.

Skips whole when the fleet files are absent, as every fleet case does.
"""

from __future__ import annotations

import glob
import json

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    DATA_DEVICES,
    INTEGRATION_DOWN_DWELL_SECONDS,
)

from tests.conftest import FLEET_ABSENT, fleet_path
from tests.helpers import setup_coordinator
from tests.test_upstream_events_fleet import _heard, _stub

JAMES = fleet_path("james", "device_sentinel.storage")
TIM = fleet_path("tim", "device_sentinel_storage.json")

# The integrations each reference fleet runs that have no reader
# watching them, taken from its own classification. Stand-in domain
# names, because Home Assistant tries to load and unload a real one
# around the test and leaves the loop holding work at teardown.
JAMES_SHAPE = {
    "blinds_hub": 6,
    "camera_hub": 4,
    "presence_hub": 3,
    "node_hub": 3,
    "coordinator_hub": 2,
    "printer_hub": 1,
    "relay_hub": 1,
}
TIM_SHAPE = {
    "router_hub": 41,
    "node_hub": 34,
    "controller_hub": 17,
    "button_hub": 14,
    "server_hub": 12,
    "storage_hub": 4,
    "sensor_hub": 4,
}


def _records(path):
    """Return a fleet's real device records."""
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    data = loaded.get("data", loaded)
    return data.get("devices") or {}


def _names(path):
    """Return the device names from the diagnostics beside the fleet."""
    found = glob.glob(str(path.parent / "config_entry*.json"))
    if not found:
        return {}
    with open(found[0], encoding="utf-8") as handle:
        dump = json.load(handle)
    return {
        device_id: (record or {}).get("name") or device_id
        for device_id, record in (
            (dump.get("data") or {}).get("devices") or {}
        ).items()
    }


def _house(hass, path, shape):
    """Build a house shaped like the fleet, and carry its records.

    Every device gets one of the fleet's real records, so the
    statistics under the judgment are real even though the wiring is
    reconstructed. Any record left over after the shape is filled
    goes onto the Zigbee bridge's stack, which is where most of both
    fleets actually lives.
    """
    records = list(_records(path).items())
    names = _names(path)
    entries: dict[str, MockConfigEntry] = {}
    behind: dict[str, list] = {}
    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    index = 0

    for domain, count in shape.items():
        source = MockConfigEntry(domain=domain, title=f"{domain} hub")
        source.add_to_hass(hass)
        entries[domain] = source
        behind[domain] = []
        for _ in range(count):
            if index >= len(records):
                break
            device_id, _record = records[index]
            device = registry.async_get_or_create(
                config_entry_id=source.entry_id,
                identifiers={(domain, f"d{index}")},
                name=names.get(device_id) or device_id,
            )
            entities.async_get_or_create(
                "sensor", domain, f"d{index}",
                device_id=device.id, config_entry=source,
            )
            behind[domain].append((device, device_id))
            index += 1

    # The rest on Zigbee, with a bridge, which is the shape both
    # fleets really have.
    zigbee = MockConfigEntry(domain="mqtt", title="Zigbee")
    zigbee.add_to_hass(hass)
    entries["mqtt"] = zigbee
    bridge = registry.async_get_or_create(
        config_entry_id=zigbee.entry_id,
        identifiers={("mqtt", "z2m_bridge")},
        name="SLZB-06M Zigbee2MQTT Bridge",
    )
    entities.async_get_or_create(
        "sensor", "mqtt", "z2m_bridge_0",
        device_id=bridge.id, config_entry=zigbee,
    )
    behind["mqtt"] = []
    while index < len(records):
        device_id, _record = records[index]
        uid = f"zigbee2mqtt_0x{index:016x}"
        device = registry.async_get_or_create(
            config_entry_id=zigbee.entry_id,
            identifiers={("mqtt", uid)},
            name=names.get(device_id) or device_id,
        )
        entities.async_get_or_create(
            "sensor", "mqtt", uid,
            device_id=device.id, config_entry=zigbee,
        )
        behind["mqtt"].append((device, device_id))
        index += 1
    return entries, behind


async def _fleet(hass, path, shape):
    """Load a fleet into a coordinator past its grace, entries up."""
    entries, behind = _house(hass, path, shape)
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()

    records = _records(path)
    for _domain, members in behind.items():
        for device, device_id in members:
            record = records.get(device_id)
            if isinstance(record, dict):
                coord.data[DATA_DEVICES][device.id] = dict(record)

    now = dt_util.utcnow().timestamp()
    for source in entries.values():
        source.mock_state(hass, ConfigEntryState.LOADED)
    coord._bridge_readers["z2m"] = _stub(BRIDGE_RUNNING)
    coord._bridge_seen["z2m"] = BRIDGE_RUNNING
    # Seen up, which is what a real house does before anything falls.
    coord._sample_integrations(now)
    return coord, entries, behind, now


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
