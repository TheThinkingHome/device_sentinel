# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_stack_capture.py, Version: 0.23.3 (2026-09-24)

"""What Extended Diagnostics captures from Z-Wave and Matter.

The second fleet's first capture, 24 September, wrote Z-Wave node
states as 1, 3 and 4 where the file promised asleep, dead and alive;
wrote the word "datetime" for each node's last seen; and left every
Matter line's detail empty, with no network and no last contact. These
tests build nodes in the shapes the libraries give. The ones that are
not guards fail on 0.23.2.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.study_stacks import (
    MATTER_DOMAIN,
    ZWAVE_DOMAIN,
    matter_study,
    probe_rows,
    zwave_study,
)

SEEN = datetime(2026, 9, 24, 19, 9, tzinfo=UTC)


class _NodeStatus(enum.IntEnum):
    """The shape Z-Wave JS's library gives a node's state in."""

    UNKNOWN = 0
    ASLEEP = 1
    AWAKE = 2
    DEAD = 3
    ALIVE = 4


def _zwave(hass, nodes):
    entry = MockConfigEntry(domain=ZWAVE_DOMAIN, title="Z-Wave JS")
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(client=SimpleNamespace(driver=SimpleNamespace(
        controller=SimpleNamespace(nodes=nodes, statistics=None))))


def _matter(hass, nodes):
    entry = MockConfigEntry(domain=MATTER_DOMAIN, title="Matter")
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(adapter=SimpleNamespace(
        matter_client=SimpleNamespace(get_nodes=lambda: nodes)))


async def test_zwave_states_are_words(hass: HomeAssistant):
    _zwave(hass, {
        5: SimpleNamespace(node_id=5, status=1, statistics=None),
        6: SimpleNamespace(node_id=6, status=3, statistics=None),
        7: SimpleNamespace(node_id=7, status=_NodeStatus.ALIVE, statistics=None),
    })
    rows = {row["node"]: row["now"] for row in probe_rows(hass, {ZWAVE_DOMAIN})}
    assert rows == {"5": "asleep", "6": "dead", "7": "alive"}
    found = zwave_study(hass)["networks"][0]
    assert found["by_status"] == {"asleep": 1, "dead": 1, "alive": 1}


async def test_zwave_last_seen_is_a_time(hass: HomeAssistant):
    _zwave(hass, {9: SimpleNamespace(
        node_id=9, status=4, statistics=SimpleNamespace(last_seen=SEEN, rssi=-61))})
    (row,) = probe_rows(hass, {ZWAVE_DOMAIN})
    assert "last_seen 2026-09-24T19:09:00+00:00" in row["detail"]
    assert "datetime" not in row["detail"]


async def test_matter_network_from_the_feature_map(hass: HomeAssistant):
    thread = SimpleNamespace(node_id=19, available=False,
        node_data=SimpleNamespace(attributes={"0/49/65532": 2, "0/40/1": "TUO"}))
    wifi = SimpleNamespace(node_id=20, available=True,
        node_data=SimpleNamespace(attributes={"0/49/65532": 1}))
    _matter(hass, [thread, wifi])
    rows = {row["node"]: row["detail"] for row in probe_rows(hass, {MATTER_DOMAIN})}
    assert rows["19"] == "network thread"
    assert rows["20"] == "network wifi"


async def test_matter_network_from_its_diagnostics_cluster(hass: HomeAssistant):
    node = SimpleNamespace(node_id=21, available=True,
        node_data=SimpleNamespace(attributes={"0/53/0": 11, "0/53/1": 3}))
    _matter(hass, [node])
    (row,) = probe_rows(hass, {MATTER_DOMAIN})
    assert row["detail"] == "network thread"


async def test_matter_last_contact_names_its_source(hass: HomeAssistant):
    node = SimpleNamespace(node_id=22, available=True,
        node_data=SimpleNamespace(attributes={"0/49/65532": 2}, last_interview=SEEN))
    _matter(hass, [node])
    (row,) = probe_rows(hass, {MATTER_DOMAIN})
    assert row["detail"] == "network thread, last_interview 2026-09-24T19:09:00+00:00"
    study = await matter_study(hass)
    first = study["fabrics"][0]["node_rows"][0]
    assert first["network"] == "thread" and first["seen_as"] == "last_interview"


async def test_a_bare_matter_node_says_nothing_rather_than_guessing(
    hass: HomeAssistant,
):
    """Guard: no attributes, no network claimed."""
    _matter(hass, [SimpleNamespace(node_id=23, available=True)])
    (row,) = probe_rows(hass, {MATTER_DOMAIN})
    assert row["detail"] == ""
