# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v093_stacks.py, Version: 0.9.3 (2026-07-25)

"""0.9.3 tests: coordinator stack auto-detection (#143, #144).

Which coordinator stacks a house runs is read from the registry, not
asked. ZHA, Z-Wave, and Matter are told by their integration domain.
Z2M is told by the presence of its bridge device, never by the mqtt
domain it shares with every other MQTT thing, which is the case that
matters most to prove: a house full of mqtt devices with no Z2M
bridge must not report Z2M.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    STACK_MATTER,
    STACK_Z2M,
    STACK_ZHA,
    STACK_ZWAVE,
)

DOMAIN = "device_sentinel"


def _device(hass, domain, uid, name, model=None, manufacturer=None):
    """Create a device owned by a config entry of the given domain,
    with an entity so it is watched, returning nothing."""
    source = MockConfigEntry(domain=domain)
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(domain, uid)},
        name=name,
        model=model,
        manufacturer=manufacturer,
    )
    er.async_get(hass).async_get_or_create(
        "sensor", domain, f"{uid}_0", device_id=device.id, config_entry=source
    )
    return device


async def _coordinator(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_zha_and_zwave_and_matter_are_told_by_domain(
    hass: HomeAssistant,
):
    """A device on each domain marks its stack present."""
    _device(hass, "zha", "z1", "A Zigbee Light")
    _device(hass, "zwave_js", "w1", "A Z-Wave Switch")
    _device(hass, "matter", "m1", "A Matter Plug")
    coord = await _coordinator(hass)
    assert STACK_ZHA in coord._stacks
    assert STACK_ZWAVE in coord._stacks
    assert STACK_MATTER in coord._stacks
    # No Z2M: there is no bridge device.
    assert STACK_Z2M not in coord._stacks


async def test_mqtt_without_a_bridge_is_not_z2m(hass: HomeAssistant):
    """The case that matters. A house full of MQTT devices with no
    Zigbee2MQTT bridge must not report Z2M, because the mqtt domain
    alone cannot tell Z2M apart from any other MQTT device (#139)."""
    _device(hass, "mqtt", "q1", "Some MQTT Sensor")
    _device(hass, "mqtt", "q2", "Another MQTT Thing")
    coord = await _coordinator(hass)
    assert STACK_Z2M not in coord._stacks


async def test_the_z2m_bridge_name_marks_z2m_present(hass: HomeAssistant):
    """A bridge device whose name ends 'Zigbee2MQTT Bridge' marks Z2M
    present. This is the portable tell: it holds whatever coordinator
    hardware sits behind it (an SLZB, a Sonoff dongle, anything)."""
    _device(hass, "mqtt", "b1", "SLZB-06M Zigbee2MQTT Bridge")
    _device(hass, "mqtt", "q1", "A normal MQTT sensor")
    coord = await _coordinator(hass)
    assert STACK_Z2M in coord._stacks


async def test_the_z2m_bridge_model_marks_z2m_present(hass: HomeAssistant):
    """The backup tell: a device with model 'Bridge' under manufacturer
    'Zigbee2MQTT', for a bridge named something else entirely."""
    _device(
        hass,
        "mqtt",
        "b2",
        "Coordinator",
        model="Bridge",
        manufacturer="Zigbee2MQTT",
    )
    coord = await _coordinator(hass)
    assert STACK_Z2M in coord._stacks


async def test_a_house_with_nothing_has_no_stacks(hass: HomeAssistant):
    """No coordinator devices, no stacks. The detection reports only
    what is actually present."""
    _device(hass, "sun", "s1", "Sun")
    coord = await _coordinator(hass)
    assert coord._stacks == set()


async def test_stacks_reach_diagnostics(hass: HomeAssistant):
    """The whole visible surface of the phase: the detected stacks
    appear in the diagnostics classification block, sorted."""
    from custom_components.device_sentinel.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    _device(hass, "zha", "z1", "A Zigbee Light")
    _device(hass, "mqtt", "b1", "SLZB-06M Zigbee2MQTT Bridge")
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)
    stacks = result["classification"]["stacks"]
    assert STACK_ZHA in stacks
    assert STACK_Z2M in stacks
    assert stacks == sorted(stacks)
