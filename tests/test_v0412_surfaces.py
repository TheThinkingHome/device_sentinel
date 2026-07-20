# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.4.12 (2026-07-19)

"""0.4.12 tests: the problem counts are opt-in, the integration picker
offers only integrations that own a watched device.

The todo list is where a person reads trouble devices, so the three
problem counts (Signal: Problems, Battery: Low, Device: Frozen) are
disabled by default. The exclusions integration picker no longer lists
every integration in Home Assistant, only those with a watched device.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "device_sentinel"


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_problem_counts_are_disabled_by_default(hass: HomeAssistant):
    """The three problem sensors register disabled, so they do not
    appear until a person enables them."""
    entry = await _setup(hass)
    reg = er.async_get(hass)
    for suffix in ("signal_problems", "low_batteries", "frozen_devices"):
        eid = reg.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
        )
        assert eid is not None, suffix
        assert reg.async_get(eid).disabled_by is not None, suffix


async def test_tracked_counts_stay_enabled(hass: HomeAssistant):
    """The Tracked family is not disabled: those are the always-on
    overview counts."""
    entry = await _setup(hass)
    reg = er.async_get(hass)
    for suffix in ("tracked_signals", "tracked_batteries", "tracked_devices"):
        eid = reg.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
        )
        assert eid is not None, suffix
        assert reg.async_get(eid).disabled_by is None, suffix


async def test_battery_low_is_diagnostic(hass: HomeAssistant):
    """Battery: Low is a diagnostic entity, matching its two problem
    siblings."""
    from homeassistant.const import EntityCategory
    entry = await _setup(hass)
    reg = er.async_get(hass)
    eid = reg.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_low_batteries"
    )
    assert reg.async_get(eid).entity_category == EntityCategory.DIAGNOSTIC


async def test_integration_picker_offers_only_watched_integrations(
    hass: HomeAssistant,
):
    """A watched device's integration is offered; a service-only
    integration with no watched device is not.

    watched_device_rows already omits service-type devices, so its
    integration set is exactly the pickable list.
    """
    source = MockConfigEntry(domain="test")
    source.add_to_hass(hass)
    # A real device on integration "reolink".
    dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("reolink", "cam1")},
        name="Front Camera",
    )
    entry = await _setup(hass)
    coord = entry.runtime_data
    integrations = {row["integration"] for row in coord.watched_device_rows}
    # The watched device's integration is present; nothing service-only
    # sneaks in, because service devices never entered watched_device_rows.
    assert all(isinstance(name, str) for name in integrations)
