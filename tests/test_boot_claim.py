# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_boot_claim.py, Version: 0.22.0 (2026-09-18)

"""A restart during an outage lists nothing on its own (#447).

Staged on the reference rig on 17 September: the MQTT broker was
stopped, Home Assistant restarted, and the problem list came up
holding 75 individual rows, one for every Zigbee device, each
"unavailable since 3:21 PM". A minute later the first tick replaced
all 75 with the single Zigbee2MQTT row. The probe recorded both
moments to the second.

The cause is the order at setup: every device is judged and the
problem list written before the bridge readers start and before the
remembered outage is restored, so at that moment no device can be
matched to its bridge and nothing claims it. Present in every release
back to the feature, not new in 0.21.12, and it needs devices already
down behind a bridge across a restart to show at all.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_SEEN_SINCE,
    BRIDGE_SEEN_STATE,
    DATA_BRIDGE_SEEN,
    DATA_DEVICES,
    DATA_TODO_ITEMS,
    DATA_SAVED_AT,
    DEV_EVENT_COUNT,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    STACK_Z2M,
    STATS_EPOCH,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)
from tests.helpers import setup_entry


def _unavailable(hass, entity_ids) -> None:
    """What a stopped broker leaves behind: every entity restored
    unavailable."""
    for entity_id in entity_ids:
        hass.states.async_set(entity_id, "unavailable")


def _house(hass) -> list[str]:
    """A Zigbee2MQTT house: the bridge device is the tell, and four
    devices behind it."""
    source = MockConfigEntry(domain="mqtt", title="MQTT")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    made = []
    entity_ids = []
    for uid, name in (
        ("bridge", "SLZB-06M Zigbee2MQTT Bridge"),
        ("d1", "Door Master"),
        ("d2", "Motion Hall"),
        ("d3", "Leak Kitchen Sink"),
        ("d4", "Switch Kitchen"),
    ):
        device = registry.async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("mqtt", uid)},
            name=name,
        )
        entity = entities.async_get_or_create(
            "sensor", "mqtt", f"{uid}_0",
            device_id=device.id, config_entry=source,
        )
        entity_ids.append(entity.entity_id)
        if uid != "bridge":
            made.append(device.id)
    _unavailable(hass, entity_ids)
    return made


def _plant(hass_storage, device_ids: list[str], down_at: float) -> None:
    """Storage as the restart found it: the bridge down since 3:21,
    and every device behind it judged unavailable."""
    devices = {}
    for device_id in device_ids:
        devices[device_id] = {
            DEV_FROZEN_CATEGORY: "unavailable",
            DEV_FROZEN_SINCE: down_at,
        }
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            DATA_DEVICES: devices,
            DATA_BRIDGE_SEEN: {
                STACK_Z2M: {
                    BRIDGE_SEEN_STATE: BRIDGE_DOWN,
                    BRIDGE_SEEN_SINCE: down_at,
                }
            },
            DATA_TODO_ITEMS: [],
            DATA_SAVED_AT: down_at + 60,
            # A file this version wrote, so the load runs no upgrade
            # and the verdicts it holds are read as they stand.
            "last_version": "0.21.13",
            "stats_epoch": STATS_EPOCH,
            "first_installed": "2026-07-11T00:08:21.626003+00:00",
            "setup_count": 400,
        },
    }
    # The hot clocks, which is where a device's last contact lives.
    # Without them every device reads as one that has never reported,
    # and the judgment at boot clears the verdict this stages.
    hass_storage[STORAGE_CLOCKS_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_CLOCKS_KEY,
        "data": {
            "clocks": {
                device_id: {
                    DEV_LAST_ACTIVITY: down_at - 600,
                    DEV_EVENT_COUNT: 400,
                }
                for device_id in device_ids
            },
            DATA_SAVED_AT: down_at + 60,
        },
    }


@pytest.fixture
def _quiet_mqtt(hass):
    """The reader subscribes if MQTT is there and reports unknown if
    it is not, which is the state a stopped broker leaves."""
    yield


async def test_a_restart_inside_a_bridge_outage_lists_nothing(
    hass: HomeAssistant, hass_storage, _quiet_mqtt
):
    down_at = dt_util.utcnow().timestamp() - 1800
    device_ids = _house(hass)
    _plant(hass_storage, device_ids, down_at)

    entry = await setup_entry(hass)
    coord = entry.runtime_data

    listed = {
        item.get("device_id") for item in coord.data[DATA_TODO_ITEMS]
    }
    assert not listed & set(device_ids), (
        "the list came up holding a row for every device behind the "
        "bridge, before anything could claim them"
    )


async def test_the_bridge_claims_them_from_the_first_write(
    hass: HomeAssistant, hass_storage, _quiet_mqtt
):
    """The claim exists at the moment the list is first written, not a
    tick later."""
    down_at = dt_util.utcnow().timestamp() - 1800
    device_ids = _house(hass)
    _plant(hass_storage, device_ids, down_at)

    entry = await setup_entry(hass)
    coord = entry.runtime_data

    assert coord._bridge_down_at.get(STACK_Z2M) == down_at
    for device_id in device_ids:
        found = coord.upstream_down_since(device_id)
        assert found is not None and found[0] == STACK_Z2M


async def test_a_device_broken_on_its_own_still_reaches_the_list(
    hass: HomeAssistant, hass_storage, _quiet_mqtt
):
    """The fix must not silence a device nothing explains.

    Its own integration is running and says nothing about it, so no
    hold applies (ruling #449 waits only on an upstream that reads
    down or failed to set up) and the row stands at once."""
    down_at = dt_util.utcnow().timestamp() - 1800
    device_ids = _house(hass)
    source = MockConfigEntry(domain="brother", title="Printer")
    source.add_to_hass(hass)
    alone = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("brother", "p1")},
        name="HL-L2370DW",
    )
    printer = er.async_get(hass).async_get_or_create(
        "sensor", "brother", "p1_0",
        device_id=alone.id, config_entry=source,
    )
    _unavailable(hass, [printer.entity_id])
    _plant(hass_storage, device_ids + [alone.id], down_at)

    entry = await setup_entry(hass)
    coord = entry.runtime_data

    listed = {
        item.get("device_id") for item in coord.data[DATA_TODO_ITEMS]
    }
    assert alone.id in listed
    assert not listed & set(device_ids), (
        "the bridge still speaks for its own"
    )


async def test_a_failing_integration_is_one_row_not_many(
    hass: HomeAssistant, hass_storage, _quiet_mqtt
):
    """Ruling #449 holds them through the grace; #445 then reports the
    integration itself, so the devices behind it are never listed one
    by one."""
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.device_sentinel.const import (
        INTEGRATION_DOWN_DWELL_SECONDS,
    )

    down_at = dt_util.utcnow().timestamp() - 1800
    source = MockConfigEntry(domain="controller_hub", title="Hub")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    made = []
    for index in range(3):
        device = registry.async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("controller_hub", f"n{index}")},
            name=f"Node {index}",
        )
        entity = entities.async_get_or_create(
            "sensor", "controller_hub", f"n{index}_0",
            device_id=device.id, config_entry=source,
        )
        hass.states.async_set(entity.entity_id, "unavailable")
        made.append(device.id)
    _plant(hass_storage, made, down_at)
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    listed = {
        item.get("device_id") for item in coord.data[DATA_TODO_ITEMS]
    }
    assert not listed & set(made)

    coord._grace_until = 0.0
    now = dt_util.utcnow().timestamp()
    coord._sample_integrations(now + INTEGRATION_DOWN_DWELL_SECONDS + 1)
    coord._sync_problem_list()
    await hass.async_block_till_done()
    summaries = [
        item.get("summary") for item in coord.data[DATA_TODO_ITEMS]
    ]
    listed = {
        item.get("device_id") for item in coord.data[DATA_TODO_ITEMS]
    }
    assert not listed & set(made), summaries
    assert any("controller_hub down" in text for text in summaries)
    source.mock_state(hass, ConfigEntryState.NOT_LOADED)


async def test_a_silent_broker_owns_its_devices_after_the_grace(
    hass: HomeAssistant, hass_storage, _quiet_mqtt
):
    """Rulings #449 and #451, the case staged on the reference rig on
    17 September: Mosquitto stopped, Home Assistant restarted. It
    loaded the MQTT entry a second later, so no integration outage
    was owed, and the broker reader reads unknown until it first hears
    the broker, so nothing else in the house would have spoken for
    these devices.

    Inside the grace they wait. Once the grace is over, a broker the
    house has heard before and that has said nothing all run is down
    from the start of the run, and the devices roll into its one row.
    """
    from custom_components.device_sentinel.const import (
        BRIDGE_SEEN_STATE,
        BROKER_LABEL,
        BROKER_RUNNING,
        BROKER_UNKNOWN,
        DATA_BROKER_SEEN,
        SYS_BROKER_DOWN,
        DATA_SYSTEM_EVENTS,
        SYS_KIND,
    )

    class _Silent:
        """A reader that has heard nothing since this run began."""

        state = BROKER_UNKNOWN
        loaded = False
        started_at = None
        stopped_at = None

        def regressed_since(self, _known):
            return False

        def async_stop(self):
            return None

    down_at = dt_util.utcnow().timestamp() - 1800
    device_ids = _house(hass)
    _plant(hass_storage, device_ids, down_at)
    # The broker was running when the last run ended, which is the
    # evidence that this broker publishes at all.
    hass_storage[STORAGE_KEY]["data"][DATA_BROKER_SEEN] = {
        BRIDGE_SEEN_STATE: BROKER_RUNNING
    }
    # Nothing remembered about the bridge: this is the case ruling
    # #447 does not cover.
    hass_storage[STORAGE_KEY]["data"].pop(DATA_BRIDGE_SEEN)

    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._broker_reader = _Silent()

    coord._sync_problem_list()
    await hass.async_block_till_done()
    listed = {
        item.get("device_id") for item in coord.data[DATA_TODO_ITEMS]
    }
    assert not listed & set(device_ids), "they were listed inside the grace"

    coord._grace_until = 0.0
    coord._sample_bridges()
    coord._sync_problem_list()
    await hass.async_block_till_done()

    kinds = [row[SYS_KIND] for row in coord.data[DATA_SYSTEM_EVENTS]]
    assert kinds.count(SYS_BROKER_DOWN) == 1
    assert coord._broker_down_at == coord._started_at
    for device_id in device_ids:
        found = coord.upstream_down_since(device_id)
        assert found is not None and found[0] == BROKER_LABEL
    listed = {
        item.get("device_id") for item in coord.data[DATA_TODO_ITEMS]
    }
    assert not listed & set(device_ids)
    summaries = [
        item.get("summary") for item in coord.data[DATA_TODO_ITEMS]
    ]
    assert any("MQTT broker down" in text for text in summaries), summaries
