# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_odd_identifiers.py, Version: 0.23.13 (2026-09-27)

"""An identifier of any length never stops Device Sentinel (issue #16).

Home Assistant types a device identifier as a pair, a domain and a
value, and stores whatever an integration registers. hOn 0.8.4
registers three parts, its domain, the appliance's MAC and its type,
and reading every identifier as a pair left Device Sentinel 0.22.28 in
setup_error in any house with a Haier appliance, and failed the
diagnostics download whenever Extended Diagnostics had anything ticked.
Reported by BeardedTinker with a traceback and a working patch. Fixed
first on the Latest line as 0.22.29, and here in the fourth place the
0.23 line has, the Extended Diagnostics node mapping.
"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel import diagnostics
from custom_components.device_sentinel.const import CONF_STUDY_HARDWARE, DOMAIN, STUDIABLE
from custom_components.device_sentinel.device_fields import identifier_values
from custom_components.device_sentinel.stack_z2m import device_key

from .helpers import setup_entry
from .test_wifi_outage import _tracker

ODD = [
    ("hon", "a4cf12b3c4d5", "washing_machine"),
    ("four", "a", "b", "c"),
    ("lonely",),
    ("numbers", 12345, 6.5),
]


def _device(hass, domain, identifier, name, uid):
    source = MockConfigEntry(domain=domain, title=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={identifier}, name=name,
    )
    entity = er.async_get(hass).async_get_or_create(
        "sensor", domain, uid, device_id=device.id, config_entry=source,
    )
    hass.states.async_set(entity.entity_id, "idle")
    return device


def _found(tree, key):
    """The first value under `key` anywhere in the download."""
    if isinstance(tree, dict):
        if key in tree:
            return tree[key]
        for value in tree.values():
            found = _found(value, key)
            if found is not None:
                return found
    return None


def test_identifiers_are_read_at_any_length():
    class _Device:
        identifiers = {("hon", "mac", "type"), ("pair", "value"), ("lonely",), (), "not a tuple"}

    read = sorted(identifier_values(_Device()))
    assert read == [("hon", ("mac", "type")), ("lonely", ()), ("pair", ("value",))]


async def test_a_haier_appliance_does_not_stop_setup(hass: HomeAssistant):
    """The reported case: hOn's three-part identifier."""
    _device(hass, "hon", ODD[0], "Haier washer", "washer")
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED


@pytest.mark.parametrize("studied", [False, True], ids=["plain", "extended"])
async def test_every_odd_shape_sets_up_ticks_and_downloads(hass: HomeAssistant, studied):
    for index, identifier in enumerate(ODD):
        _device(hass, f"odd{index}", identifier, f"Odd {index}", f"odd{index}")
    options = {CONF_STUDY_HARDWARE: [STUDIABLE["matter"]]} if studied else {}
    entry = await setup_entry(hass, options)
    assert entry.state is ConfigEntryState.LOADED
    coord = entry.runtime_data
    await coord._on_render_tick(None)
    await hass.async_block_till_done()
    report = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    assert report
    if studied:
        watched = _found(report, "watched_devices")
        told = {row["name"]: row["identifiers"] for row in watched}
        # Every part kept (issue #16); the MAC in the middle is the
        # appliance's own, so the download carries its stand-in
        # rather than the address itself (0.23.19).
        assert told["Odd 0"] == ["A4:CF:12:MAC-01:washing_machine"]


async def test_a_mac_in_a_third_part_still_ties_the_device(hass: HomeAssistant):
    """The Wi-Fi tie searches every part after the domain, as the
    reporter's patch did."""
    tracker = _tracker(hass, "washer-tracker", "A4:CF:12:B3:C4:D5")
    device = _device(hass, "hon", ("hon", "haier", "a4cf12b3c4d5"), "Haier washer", "washer")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    assert coord._wifi_ties.get(device.id) == tracker


def test_a_zigbee2mqtt_device_is_named_at_any_length():
    class _Device:
        identifiers = {("mqtt", "zigbee2mqtt_0x282c02bfffeafa5b", "extra")}

    assert device_key(_Device()) == "0x282c02bfffeafa5b"


async def test_one_unreadable_device_never_stops_setup(hass: HomeAssistant, monkeypatch, caplog):
    """Whatever else another integration's registry entry holds: the
    device is still watched, named once, and setup goes on."""
    device = _device(hass, "strange", ("strange", "x"), "Strange device", "strange")
    from custom_components.device_sentinel import coordinator as module

    real = module.detect_stack

    def _refuses(domain, dev):
        if dev.id == device.id:
            raise RuntimeError("an entry nobody expected")
        return real(domain, dev)

    monkeypatch.setattr(module, "detect_stack", _refuses)
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    coord = entry.runtime_data
    assert device.id in coord._watched
    coord._rebuild_registry_view()
    warned = [r for r in caplog.records if "could not read part of Strange device" in r.getMessage()]
    assert len(warned) == 1


async def test_the_entry_is_named_in_the_loaded_state(hass: HomeAssistant):
    """The reporter's success check: loaded, not setup_error."""
    _device(hass, "hon", ODD[0], "Haier washer", "washer")
    await setup_entry(hass)
    assert hass.config_entries.async_entries(DOMAIN)[0].state is ConfigEntryState.LOADED


async def test_a_node_is_mapped_whatever_its_identifier_length(hass: HomeAssistant):
    """The Extended Diagnostics node mapping (0.23.8), the fourth place."""
    from custom_components.device_sentinel.study_stacks import node_devices

    source = MockConfigEntry(domain="zwave_js", title="Z-Wave")
    source.add_to_hass(hass)
    plain = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("zwave_js", "3967862535-5")}, name="Plain",
    )
    longer = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("zwave_js", "3967862535-7", "extra")}, name="Longer",
    )
    dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("zwave_js",)}, name="Bare",
    )
    found = node_devices(hass, source, "zwave_js")
    assert found.get("5") == plain.id and found.get("7") == longer.id
