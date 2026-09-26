# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_escalation_and_limits.py, Version: 0.23.8 (2026-09-25)

"""A worse problem replacing a lesser one, and lines a person reads.

The reference rig's watering sensor moved from frozen to unavailable
at the nightly reboot, and the brief called it a recovery "revived by
a reboot" in the same second the device was declared gone. The push
engine already knew better and said nothing; the knowledge never
reached the record. Beside that, three limits: a push that named fifty
devices in 2,160 characters, a duration that could not be printed, and
a battery reading outside nothing-to-full drawn as a percentage.
"""

from __future__ import annotations


from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    BATTERY_READABLE_MAX,
    DATA_DEVICES,
    DATA_INCIDENTS,
    DEV_BATTERY_DAILY,
    DEV_BATTERY_VALUE,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    INC_CAUSE,
    INC_EVENT,
    INC_KIND,
    INC_SUPERSEDED,
    INCIDENT_RESOLVED,
    SUMMARY_NAMES,
    TODO_KIND_FROZEN,
)
from custom_components.device_sentinel.durations import long_span
from custom_components.device_sentinel.normalise import check_records
from custom_components.device_sentinel.records import _new_device_record

from .helpers import register_device, setup_coordinator

HOUR = 3600.0


def _arm(coordinator, device_id: str, category: str, since: float) -> dict:
    record = coordinator.data[DATA_DEVICES][device_id]
    record[DEV_DAILY_MAX] = [600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_FROZEN_CATEGORY] = category
    record[DEV_FROZEN_SINCE] = since
    return record


async def test_a_worse_problem_replacing_a_lesser_one_is_not_a_recovery(
    hass: HomeAssistant,
):
    device, _entities = register_device(hass, "e1", name="Watering Kit")
    coordinator = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    _arm(coordinator, device.id, FREEZE_CATEGORY_FROZEN, now - 31 * HOUR)
    coordinator._sync_problem_list()

    # The reboot: Zigbee2MQTT stops claiming it is online, and the
    # verdict moves from frozen to unavailable in one pass.
    _arm(coordinator, device.id, FREEZE_CATEGORY_UNAVAILABLE, now - 31 * HOUR)
    coordinator._sync_problem_list()

    closed = [
        row
        for row in coordinator.data[DATA_INCIDENTS]
        if row[INC_EVENT] == INCIDENT_RESOLVED and row[INC_KIND] == TODO_KIND_FROZEN
    ]
    assert closed, "the frozen incident was never closed"
    assert closed[-1][INC_SUPERSEDED] is True
    assert closed[-1][INC_CAUSE] is None, "nothing revived it"


async def test_a_real_recovery_still_reads_as_one(hass: HomeAssistant):
    device, entities = register_device(hass, "e2", name="Door Entryway")
    coordinator = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    _arm(coordinator, device.id, FREEZE_CATEGORY_FROZEN, now - 2 * HOUR)
    coordinator._sync_problem_list()
    coordinator.data[DATA_DEVICES][device.id][DEV_FROZEN_CATEGORY] = None
    coordinator._sync_problem_list()
    closed = [
        row
        for row in coordinator.data[DATA_INCIDENTS]
        if row[INC_EVENT] == INCIDENT_RESOLVED and row[INC_KIND] == TODO_KIND_FROZEN
    ]
    assert closed[-1][INC_SUPERSEDED] is False


async def test_a_push_names_the_worst_few_and_counts_the_rest(
    hass: HomeAssistant,
):
    """Fifty devices down made a message of 2,160 characters."""
    devices = [
        register_device(hass, f"e{index}", name=f"Sensor Number {index:02d} In The Back Room")[0]
        for index in range(50)
    ]
    coordinator = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    for index, device in enumerate(devices):
        # The last to fail is the most recent, so it leads.
        _arm(coordinator, device.id, FREEZE_CATEGORY_FROZEN, now - (50 - index) * 60)
    coordinator._sync_problem_list()
    payload = coordinator._family_payload(
        "freeze", "Sensor Number 49 In The Back Room stopped reporting", False
    )
    message = str(payload["message"])
    assert len(message) < 400, message
    assert "Sensor Number 49" in message
    summary = message.split("Summary: ", 1)[1]
    assert summary.count(" In The Back Room") == SUMMARY_NAMES, summary
    assert f"and {50 - SUMMARY_NAMES} more devices." in message


async def test_the_worst_leads_the_push(hass: HomeAssistant):
    """Severity first, and the battery beneath it is still counted."""
    down, _entities = register_device(hass, "w1", name="Door Master")
    coordinator = await setup_coordinator(hass)
    now = dt_util.utcnow().timestamp()
    _arm(coordinator, down.id, FREEZE_CATEGORY_UNAVAILABLE, now - 60)
    coordinator._sync_problem_list()
    summary = coordinator._family_summary("freeze")
    assert summary.startswith("Door Master unavailable")


async def test_a_duration_that_is_not_a_number_reads_as_unknown():
    assert long_span(float("inf")) == "?"
    assert long_span(float("nan")) in ("?", "0 days")
    assert long_span(62 * 86400) == "8 and a half weeks"


async def test_a_battery_outside_a_percentage_is_not_drawn_as_one(
    hass: HomeAssistant,
):
    device, _entities = register_device(hass, "b1", name="Odd Cell")
    coordinator = await setup_coordinator(hass)
    record = coordinator.data[DATA_DEVICES][device.id]
    for level, readable in (
        (-5.0, False),
        (0.0, True),
        (50.0, True),
        (BATTERY_READABLE_MAX, True),
        (186.0, False),
    ):
        record[DEV_BATTERY_VALUE] = level
        record[DEV_BATTERY_DAILY] = [level] * 5
        page = coordinator.dashboard_device(device.id)
        assert page["battery"]["readable"] is readable, level


def test_a_negative_gap_is_refused_at_the_boundary():
    """A negative today_max folded into the day's series at midnight
    and had the whole record refused on the next load."""
    record = _new_device_record("2026-09-23T00:00:00+00:00", 1.0)
    record["today_max"] = -50.0
    faults = check_records({"a" * 32: record})
    assert faults and faults[0][1] == "today_max"

    record["today_max"] = 50.0
    assert not check_records({"a" * 32: record})


async def test_a_house_with_no_lutron_says_nothing(hass: HomeAssistant):
    from custom_components.device_sentinel.study_lutron import lutron_study

    assert await lutron_study(hass) == {}


async def test_a_house_with_no_zwave_or_matter_says_nothing(
    hass: HomeAssistant,
):
    from custom_components.device_sentinel.study_stacks import (
        matter_study,
        zwave_study,
    )

    assert zwave_study(hass) == {}
    assert await matter_study(hass) == {}


async def test_a_zwave_network_is_read_defensively(hass: HomeAssistant):
    """A fake driver in the shape the library gives, plus one node
    whose attributes are missing entirely, which is what a version
    change looks like from here."""
    from types import SimpleNamespace

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.device_sentinel.study_stacks import (
        ZWAVE_DOMAIN,
        zwave_study,
    )

    alive = SimpleNamespace(
        node_id=2, status="alive", ready=True, is_controller_node=False,
        is_listening=True, is_frequent_listening=False, is_routing=True,
        statistics=SimpleNamespace(rtt=31.0, rssi=-58, commands_tx=100),
    )
    asleep = SimpleNamespace(
        node_id=3, status="asleep", ready=True, is_controller_node=False,
        is_listening=False, is_frequent_listening=True, is_routing=False,
        statistics=None,
    )
    bare = SimpleNamespace(node_id=4)
    entry = MockConfigEntry(domain=ZWAVE_DOMAIN, title="Z-Wave JS")
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(
        client=SimpleNamespace(
            driver=SimpleNamespace(
                controller=SimpleNamespace(
                    nodes={2: alive, 3: asleep, 4: bare},
                    statistics=SimpleNamespace(messages_tx=900, can=2),
                )
            )
        )
    )
    found = zwave_study(hass)["networks"][0]
    assert found["nodes"] == 3
    assert found["by_status"] == {"alive": 1, "asleep": 1, "None": 1}
    assert found["controller_statistics"] == {"messages_tx": 900, "can": 2}
    rows = {row["node_id"]: row for row in found["node_rows"]}
    assert rows[2]["statistics"]["rssi"] == -58
    assert rows[3]["frequent_listening"] is True
    assert rows[4]["status"] is None and rows[4]["statistics"] == {}


async def test_the_stack_probe_writes_a_line_when_a_node_changes(
    hass: HomeAssistant,
):
    """A snapshot shows a healthy network whenever it is taken. The
    interesting events are rare, so they are recorded as they happen."""
    from types import SimpleNamespace

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.device_sentinel.const import (
        CONF_STUDY_HARDWARE,
        DATA_STACK_PROBE,
        REPORT_STACK_PROBE,
        STUDIABLE,
    )
    from custom_components.device_sentinel.study_stacks import ZWAVE_DOMAIN

    node = SimpleNamespace(
        node_id=7, status="alive", ready=True, is_controller_node=False,
        is_listening=False, is_frequent_listening=False, is_routing=False,
        statistics=SimpleNamespace(rtt=42.0, rssi=-70),
    )
    source = MockConfigEntry(domain=ZWAVE_DOMAIN, title="Z-Wave JS")
    source.add_to_hass(hass)
    source.runtime_data = SimpleNamespace(
        client=SimpleNamespace(
            driver=SimpleNamespace(
                controller=SimpleNamespace(nodes={7: node}, statistics=None)
            )
        )
    )
    coordinator = await setup_coordinator(
        hass, {CONF_STUDY_HARDWARE: [STUDIABLE[ZWAVE_DOMAIN]]}
    )
    now = dt_util.utcnow().timestamp()

    def node_lines():
        # Since 0.23.8 the controller has a line of its own; this test
        # is about the node's.
        return [row for row in coordinator.data[DATA_STACK_PROBE] if row["node"] == "7"]

    coordinator.probe_tick(now)
    assert len(node_lines()) == 1, "the first reading"

    coordinator.probe_tick(now + 30)
    assert len(node_lines()) == 1, "nothing changed"

    node.status = "dead"
    coordinator.probe_tick(now + 60)
    rows = node_lines()
    assert len(rows) == 2
    assert rows[-1]["was"] == "alive" and rows[-1]["now"] == "dead"
    assert "rssi -70" in rows[-1]["detail"]

    await hass.async_add_executor_job(coordinator._write_reports, "test")
    text = open(
        hass.config.path("device_sentinel", REPORT_STACK_PROBE),
        encoding="utf-8",
    ).read()
    # The DEVICE column (0.23.8) sits between NODE and WAS; this node
    # has no device in the registry.
    assert "| zwave_js | 7 |  | alive | dead |" in text
    assert "Stack Probe" in text


async def test_the_stack_probe_stays_quiet_when_nothing_is_studied(
    hass: HomeAssistant,
):
    from custom_components.device_sentinel.const import (
        DATA_STACK_PROBE,
        REPORT_STACK_PROBE,
    )

    coordinator = await setup_coordinator(hass)
    coordinator.probe_tick(dt_util.utcnow().timestamp())
    assert not coordinator.data.get(DATA_STACK_PROBE)
    await hass.async_add_executor_job(coordinator._write_reports, "test")
    from pathlib import Path

    assert not Path(
        hass.config.path("device_sentinel", REPORT_STACK_PROBE)
    ).exists()
