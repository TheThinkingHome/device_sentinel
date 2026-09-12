# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_naming.py, Version: 0.20.18 (2026-09-12)

"""A device with no registry name is never shown as its id (ruling #402)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.naming import display_name

HEX32 = re.compile(r"^[0-9a-f]{32}$")
DEVICE_ID = "deca7fbaee8d0f62f473fbc7ad5675f9"
MAC = "78:6c:84:24:b8:af"


@dataclass
class Dev:
    name: str | None = None
    name_by_user: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    connections: set = field(default_factory=set)


def _mac():
    return {(dr.CONNECTION_NETWORK_MAC, MAC)}


def test_the_person_s_name_wins():
    dev = Dev(name="unifi thing", name_by_user="Hall AP", manufacturer="Ubiquiti",
              model="UAP-AC-Pro", connections=_mac())
    assert display_name(dev, "unifi", DEVICE_ID) == "Hall AP"


def test_then_the_integration_s_name():
    dev = Dev(name="Living Room", manufacturer="Ubiquiti", model="UAP", connections=_mac())
    assert display_name(dev, "unifi", DEVICE_ID) == "Living Room"


def test_make_model_and_mac_when_nameless():
    """The second fleet's case: UniFi registers unknown clients with no name."""
    dev = Dev(manufacturer="Ubiquiti", model="UAP-AC-Pro", connections=_mac())
    assert display_name(dev, "unifi", DEVICE_ID) == f"Ubiquiti UAP-AC-Pro {MAC}"


def test_integration_and_mac_when_no_make_or_model():
    dev = Dev(connections=_mac())
    assert display_name(dev, "unifi", DEVICE_ID) == f"unifi {MAC}"


def test_integration_and_id_tail_as_the_last_resort():
    dev = Dev()
    assert display_name(dev, "unifi", DEVICE_ID) == "unifi-ad5675f9"


def test_no_registry_entry_at_all():
    assert display_name(None, "mqtt", DEVICE_ID) == "mqtt-ad5675f9"
    assert display_name(None, None, DEVICE_ID) == "Unknown-ad5675f9"


def test_a_known_stack_uses_its_display_name():
    dev = Dev(connections=_mac())
    assert display_name(dev, "z2m", DEVICE_ID) == f"Zigbee2MQTT {MAC}"


def test_blank_and_whitespace_names_are_not_names():
    dev = Dev(name="   ", name_by_user="", manufacturer="A", model="B", connections=_mac())
    assert display_name(dev, "unifi", DEVICE_ID) == f"A B {MAC}"


def test_partial_make_or_model_falls_to_the_mac_rung():
    dev = Dev(manufacturer="Ubiquiti", connections=_mac())
    assert display_name(dev, "unifi", DEVICE_ID) == f"unifi {MAC}"


def test_never_a_bare_hash():
    """Every rung, and none of them is the id."""
    for dev in (
        Dev(), Dev(connections=_mac()), Dev(manufacturer="A", model="B"),
        Dev(manufacturer="A", model="B", connections=_mac()), None,
    ):
        assert not HEX32.match(display_name(dev, "unifi", DEVICE_ID))
