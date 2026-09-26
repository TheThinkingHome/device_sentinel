# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_stack_readers.py, Version: 0.23.9 (2026-09-26)

"""The Z-Wave and Matter readers in shadow (0.23.8).

The stack probe names each node's device (#478), sets Device
Sentinel's own view of that device beside the stack's, says whether
they agree, and records the coordinators. Nothing acts on either side.
The fakes follow the shapes read on 25 September 2026 in the code Home
Assistant 2026.9.2 ships and the libraries it pins
(Project__Stack_Readers.md).

The tests that are not guards fail on 0.23.7, which names no device,
writes nothing when a Z-Wave plug is unplugged, and records neither
coordinator.
"""

from __future__ import annotations

import os
from datetime import timedelta
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_STUDY_HARDWARE,
    DATA_DEVICES,
    DATA_STACK_PROBE,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    PROBE_AGREES,
    PROBE_DETAIL,
    PROBE_DEVICE_ID,
    PROBE_NOW,
    PROBE_SENTINEL,
    PROBE_WAS,
    REPORT_DIR,
    REPORT_STACK_PROBE,
)
from custom_components.device_sentinel.study_stacks import (
    MATTER_DOMAIN,
    ZWAVE_DOMAIN,
    coordinator_rows,
    probe_rows,
)

from .helpers import probe_lines, setup_coordinator

HOME = 3947620411
FABRIC = 0x2A6F1C3D4E5B6A79


def _entry(hass, domain):
    entry = MockConfigEntry(domain=domain, title=domain)
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    return entry


def _device(hass, entry, domain, ident, name):
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(domain, ident)}, name=name,
    )
    er.async_get(hass).async_get_or_create(
        "sensor", domain, f"{ident}-reading", device_id=device.id, config_entry=entry,
    )
    return device


def _zwave(hass, nodes, *, connected=True, driver=True, status=0):
    entry = _entry(hass, ZWAVE_DOMAIN)
    controller = SimpleNamespace(home_id=HOME, nodes=nodes, status=status, statistics=None)
    client = SimpleNamespace(
        connected=connected,
        driver=SimpleNamespace(controller=controller) if driver else None,
    )
    entry.runtime_data = SimpleNamespace(client=client)
    return entry, client


def _matter(hass, nodes, *, connected=True):
    entry = _entry(hass, MATTER_DOMAIN)
    client = SimpleNamespace(
        get_nodes=lambda: nodes, connection=SimpleNamespace(connected=connected),
    )
    entry.runtime_data = SimpleNamespace(adapter=SimpleNamespace(matter_client=client))
    return entry, client


def _plug(node_id, status=4, seen=None):
    return SimpleNamespace(
        node_id=node_id, status=status, is_listening=True, is_controller_node=False,
        last_seen=seen, statistics=None,
    )


async def _studied(hass):
    return await setup_coordinator(hass, {CONF_STUDY_HARDWARE: ["Z-Wave", "Matter"]})


def _lines(coord, node):
    return probe_lines(coord, node)


async def test_each_node_names_its_device(hass: HomeAssistant):
    """#478, through the identifiers Home Assistant registers."""
    zentry, _client = _zwave(hass, {10: _plug(10)})
    p03 = _device(hass, zentry, ZWAVE_DOMAIN, f"{HOME}-10", "P03 Z-Wave Smart plug")
    mentry, _client = _matter(hass, [SimpleNamespace(node_id=22, available=True, node_data=SimpleNamespace(attributes={}))])
    b09 = _device(hass, mentry, MATTER_DOMAIN, f"deviceid_{FABRIC:016X}-{22:016X}-MatterNodeDevice", "B09 Matter button")
    rows = {(row["stack"], row["node"]): row["device_id"] for row in probe_rows(hass, {ZWAVE_DOMAIN, MATTER_DOMAIN})}
    assert rows[(ZWAVE_DOMAIN, "10")] == p03.id
    assert rows[(MATTER_DOMAIN, "22")] == b09.id


async def test_an_unplugged_plug_that_stays_alive_is_still_recorded(hass: HomeAssistant):
    """Research finding 4: Tim Plas's P03 read alive three days after it
    was last heard. The line comes from last seen passing the device's
    window, and Device Sentinel's frozen verdict agrees with it."""
    now = dt_util.utcnow()
    zentry, _client = _zwave(hass, {10: _plug(10, 4, now - timedelta(days=3))})
    p03 = _device(hass, zentry, ZWAVE_DOMAIN, f"{HOME}-10", "P03 Z-Wave Smart plug")
    coord = await _studied(hass)
    record = coord.data[DATA_DEVICES][p03.id]
    record[DEV_DAILY_MAX] = [600.0] * 14
    record[DEV_LAST_ACTIVITY] = (now - timedelta(days=3)).timestamp()
    record[DEV_FROZEN_CATEGORY] = "frozen"
    coord.probe_tick(now.timestamp())
    (line,) = _lines(coord, "10")
    assert line[PROBE_DEVICE_ID] == "P03 Z-Wave Smart plug"
    assert line[PROBE_NOW] == "alive, not heard within its window"
    assert line[PROBE_SENTINEL] == "frozen"
    assert line[PROBE_AGREES] == "yes"
    assert "last heard 3 days ago" in line[PROBE_DETAIL]


async def test_a_line_when_only_device_sentinel_changes(hass: HomeAssistant):
    """The stack's side unchanged, Device Sentinel's changing: a line,
    and it says the two disagree."""
    now = dt_util.utcnow()
    zentry, _client = _zwave(hass, {10: _plug(10, 4, now)})
    p03 = _device(hass, zentry, ZWAVE_DOMAIN, f"{HOME}-10", "P03 Z-Wave Smart plug")
    coord = await _studied(hass)
    record = coord.data[DATA_DEVICES][p03.id]
    record[DEV_DAILY_MAX] = [600.0] * 14
    record[DEV_LAST_ACTIVITY] = now.timestamp()
    coord.probe_tick(now.timestamp())
    coord.probe_tick(now.timestamp() + 60)
    assert len(_lines(coord, "10")) == 1, "nothing changed, nothing written"
    record[DEV_FROZEN_CATEGORY] = "frozen"
    coord.probe_tick(now.timestamp() + 120)
    last = _lines(coord, "10")[-1]
    assert (last[PROBE_NOW], last[PROBE_SENTINEL], last[PROBE_AGREES]) == ("alive", "frozen", "no")


async def test_the_controller_has_lines_of_its_own(hass: HomeAssistant):
    """A stick pulled or a server restarted is on record with its time."""
    _entry_, client = _zwave(hass, {})
    coord = await _studied(hass)
    coord.probe_tick(1000.0)
    client.driver = None
    coord.probe_tick(1060.0)
    client.connected = False
    coord.probe_tick(1120.0)
    lines = [(row[PROBE_WAS], row[PROBE_NOW]) for row in _lines(coord, "controller")]
    assert lines == [("", "ready"), ("ready", "no driver"), ("no driver", "disconnected")]


async def test_the_controller_says_when_it_is_unresponsive(hass: HomeAssistant):
    _zwave(hass, {}, status=1)
    assert [row["now"] for row in coordinator_rows(hass, {ZWAVE_DOMAIN})] == ["unresponsive"]


async def test_the_matter_server_connection_is_recorded(hass: HomeAssistant):
    _entry_, client = _matter(hass, [])
    coord = await _studied(hass)
    coord.probe_tick(1000.0)
    client.connection.connected = False
    coord.probe_tick(1060.0)
    assert [row[PROBE_NOW] for row in _lines(coord, "server")] == ["connected", "disconnected"]


async def test_an_away_matter_node_and_an_unavailable_device_agree(hass: HomeAssistant):
    node = SimpleNamespace(node_id=19, available=False, node_data=SimpleNamespace(attributes={"0/49/65532": 1, "0/54/4": -71}))
    mentry, _client = _matter(hass, [node])
    plug = _device(hass, mentry, MATTER_DOMAIN, f"deviceid_{FABRIC:016X}-{19:016X}-MatterNodeDevice", "P22 Tapo plug")
    coord = await _studied(hass)
    record = coord.data[DATA_DEVICES][plug.id]
    record[DEV_LAST_ACTIVITY] = 1.0
    record[DEV_FROZEN_CATEGORY] = "unavailable"
    coord.probe_tick(1000.0)
    (line,) = _lines(coord, "19")
    assert (line[PROBE_NOW], line[PROBE_SENTINEL], line[PROBE_AGREES]) == ("away", "unavailable", "yes")
    assert "wifi rssi -71" in line[PROBE_DETAIL]


async def test_matter_wifi_nodes_are_named_when_wifi_goes_down(hass: HomeAssistant):
    """#412's exception, observed: which Matter Wi-Fi nodes went away
    with Device Sentinel's Wi-Fi outage and which did not."""
    away = SimpleNamespace(node_id=19, available=False, node_data=SimpleNamespace(attributes={"0/49/65532": 1}))
    up = SimpleNamespace(node_id=20, available=True, node_data=SimpleNamespace(attributes={"0/49/65532": 1}))
    thread = SimpleNamespace(node_id=22, available=False, node_data=SimpleNamespace(attributes={"0/49/65532": 2}))
    mentry, _client = _matter(hass, [away, up, thread])
    _device(hass, mentry, MATTER_DOMAIN, f"deviceid_{FABRIC:016X}-{19:016X}-MatterNodeDevice", "P22 Tapo plug")
    coord = await _studied(hass)
    coord.probe_tick(1000.0)
    coord._wifi_down_at = 1050.0
    coord.probe_tick(1060.0)
    (line,) = _lines(coord, "wifi")
    assert line[PROBE_NOW] == "wifi down"
    assert line[PROBE_DETAIL] == "away: P22 Tapo plug; available: node 20"


async def test_whether_each_status_sensor_is_on(hass: HomeAssistant):
    """Research finding 5: the node status sensor's change counts as the
    device speaking, so the probe says where it is on."""
    zentry, _client = _zwave(hass, {10: _plug(10), 11: _plug(11), 12: _plug(12)})
    registry = er.async_get(hass)
    registry.async_get_or_create("sensor", ZWAVE_DOMAIN, f"{HOME}.10.node_status", config_entry=zentry)
    registry.async_get_or_create("sensor", ZWAVE_DOMAIN, f"{HOME}.11.node_status", config_entry=zentry,
                                 disabled_by=er.RegistryEntryDisabler.USER)
    details = {row["node"]: row["detail"] for row in probe_rows(hass, {ZWAVE_DOMAIN})}
    assert "status sensor on" in details["10"]
    assert "status sensor off" in details["11"]
    assert "status sensor absent" in details["12"]


async def test_the_day_counts_what_agreed(hass: HomeAssistant):
    now = dt_util.utcnow()
    zentry, _client = _zwave(hass, {10: _plug(10, 4, now - timedelta(days=3)), 11: _plug(11, 4, now)})
    stale = _device(hass, zentry, ZWAVE_DOMAIN, f"{HOME}-10", "P03 plug")
    fresh = _device(hass, zentry, ZWAVE_DOMAIN, f"{HOME}-11", "P04 plug")
    coord = await _studied(hass)
    for device, frozen in ((stale, False), (fresh, False)):
        record = coord.data[DATA_DEVICES][device.id]
        record[DEV_DAILY_MAX] = [600.0] * 14
        record[DEV_LAST_ACTIVITY] = now.timestamp()
        if frozen:
            record[DEV_FROZEN_CATEGORY] = "frozen"
    coord.probe_fold(now.timestamp())
    day = next(row for row in probe_lines(coord) if row[PROBE_NOW] == "day")
    assert day[PROBE_AGREES] == "1 agree, 1 do not"


async def test_the_file_names_devices_and_reads_old_lines(hass: HomeAssistant):
    """Lines stored before 0.23.9 move into the file once, oldest
    first, and storage lets them go; a line written before 0.23.8 has
    no Device Sentinel column and still renders."""
    zentry, _client = _zwave(hass, {10: _plug(10)})
    p03 = _device(hass, zentry, ZWAVE_DOMAIN, f"{HOME}-10", "P03 Z-Wave Smart plug")
    coord = await _studied(hass)
    coord.data[DATA_STACK_PROBE] = [
        {"when": 900.0, "stack": "zwave_js", "node": "6", "device_id": "", "was": "", "now": "dead", "detail": ""},
    ]
    coord.probe_tick(1000.0)
    await hass.async_block_till_done()
    assert coord.data[DATA_STACK_PROBE] == []
    coord.probe_tick(1060.0)
    await hass.async_block_till_done()
    with open(os.path.join(hass.config.path(REPORT_DIR), REPORT_STACK_PROBE), encoding="utf-8") as handle:
        page = handle.read()
    assert "| WHEN | STACK | NODE | DEVICE | WAS | NOW | SENTINEL | AGREES | DETAIL |" in page
    assert "| P03 Z-Wave Smart plug |" in page
    assert "| zwave_js | 6 |  |  | dead |" in page
    assert page.index("| zwave_js | 6 |") < page.index("| P03 Z-Wave Smart plug |"), "oldest first"
    assert p03.id not in page


async def test_the_file_rolls_over_at_its_cap(hass: HomeAssistant, monkeypatch):
    """At the cap the file becomes .1, older ones move up to .3, and
    the oldest is dropped (0.23.9)."""
    from custom_components.device_sentinel import report_maintainer

    monkeypatch.setattr(report_maintainer, "PROBE_FILE_MAX_BYTES", 4000)
    coord = await setup_coordinator(hass)
    base = os.path.join(hass.config.path(REPORT_DIR), REPORT_STACK_PROBE)
    for batch in range(14):
        lines = [f"| line {batch}-{i} |" + "x" * 80 for i in range(10)]
        await hass.async_add_executor_job(coord._probe_write_lines, lines)
    names = sorted(os.path.basename(p) for p in os.listdir(os.path.dirname(base)) if p.startswith(REPORT_STACK_PROBE))
    assert names == [REPORT_STACK_PROBE, f"{REPORT_STACK_PROBE}.1", f"{REPORT_STACK_PROBE}.2", f"{REPORT_STACK_PROBE}.3"]
    with open(base, encoding="utf-8") as handle:
        newest = handle.read()
    assert newest.startswith("# Device Sentinel") and "line 13-9" in newest
    assert all(os.path.getsize(f"{base}.{index}") <= 4000 for index in (1, 2, 3))
    with open(f"{base}.3", encoding="utf-8") as handle:
        assert "line 0-0" not in handle.read(), "the oldest file is dropped"

async def test_the_flapping_description_keeps_its_capitals(hass: HomeAssistant, freezer):
    """Tim Plas's list read "since september 25, 2026 at 2:04 pm":
    str.capitalize() lowered everything after the first letter."""
    from custom_components.device_sentinel.const import TODO_DESCRIPTION

    from .test_flapping import _drop, _item, _shed

    freezer.move_to("2026-09-25T19:04:00+00:00")
    coord, device, entity_id, _phone = await _shed(hass, freezer)
    for _ in range(4):
        await _drop(hass, coord, freezer, entity_id)
    description = _item(coord, device.id)[TODO_DESCRIPTION]
    assert description.startswith("Flapping, dropped out 4 times since September 25, 2026 at ")
    assert " PM." in description or " AM." in description, description
    assert "september" not in description
