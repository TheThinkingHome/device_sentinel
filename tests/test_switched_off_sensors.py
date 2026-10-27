# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_switched_off_sensors.py, Version: 0.27.10 (2026-10-27)

"""Switched-off sensors: found per device, turned on per device (rules
REC-05, DASH-09).

No button entity turns sensors on, because any user, automation or
script could press it and turn on other integrations' entities on
every watched device, including ones a person had switched off. A
sensor is switched on one device and one kind at a time, by an
administrator, from the device's page or its Recommendations card, and
the retired-entity sweep removes the three old registry entries.

Only a device's own entities count as switched off, never one another
integration added (rule WATCH-02), and a device is listed only when
none of its own entities of that kind is on. Who switched them off is
kept, because a person's own choice is listed already acknowledged
(rule REC-07).
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_SYSTEM_EVENTS,
    DOMAIN,
    SYS_DETAIL,
)

from tests.helpers import setup_entry


def _device(hass: HomeAssistant, uid: str, name: str | None = None):
    """A loaded source integration and one of its devices."""
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name or uid,
    )
    return source, device


def _entity(
    hass: HomeAssistant, source, device, uid: str, object_id: str,
    *, platform: str = "test", disabled_by=None, device_class=None, unit=None,
):
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "sensor", platform, uid,
        suggested_object_id=object_id,
        device_id=device.id,
        config_entry=source if platform == "test" else None,
        disabled_by=disabled_by,
        original_device_class=device_class,
        unit_of_measurement=unit,
    )
    return entry.entity_id


INTEGRATION = er.RegistryEntryDisabler.INTEGRATION
USER = er.RegistryEntryDisabler.USER


async def test_the_three_enable_buttons_are_gone(hass: HomeAssistant):
    """Only Regenerate Reports and Maintenance Mode are button entities;
    nothing a script can press turns on another integration's entity
    (rule DASH-09)."""
    await setup_entry(hass)
    buttons = sorted(
        state.entity_id for state in hass.states.async_all("button")
        if state.entity_id.startswith("button.device_sentinel")
    )
    assert buttons == [
        "button.device_sentinel_maintenance_mode",
        "button.device_sentinel_regenerate_reports",
    ]


async def test_an_upgrade_removes_the_three_registry_entries(hass: HomeAssistant):
    """An older install holds the three entries in its registry; the
    retired-entity sweep removes them at setup and leaves the two
    buttons that stay (rule STOR-19)."""
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", options={})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = [
        registry.async_get_or_create(
            "button", DOMAIN, f"{entry.entry_id}_{key}", config_entry=entry,
        ).entity_id
        for key in (
            "enable_signal_entities",
            "enable_last_seen_entities",
            "enable_battery_entities",
        )
    ]
    kept = registry.async_get_or_create(
        "button", DOMAIN, f"{entry.entry_id}_regenerate_reports", config_entry=entry,
    ).entity_id
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for entity_id in old:
        assert registry.async_get(entity_id) is None, entity_id
    assert registry.async_get(kept) is not None


async def test_switched_off_reads_who_switched_it_off(hass: HomeAssistant):
    """The integration's default reads "other"; a person's own choice
    reads "user", so its card row starts acknowledged (rule REC-07)."""
    source, by_default = _device(hass, "by_default")
    _entity(hass, source, by_default, "bd_ls", "by_default_last_seen", disabled_by=INTEGRATION)
    source2, by_hand = _device(hass, "by_hand")
    _entity(hass, source2, by_hand, "bh_ls", "by_hand_last_seen", disabled_by=USER)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    assert coord.switched_off(by_default.id, "last_seen") == "other"
    assert coord.switched_off(by_hand.id, "last_seen") == "user"
    assert coord.switched_off_devices("last_seen") == {
        by_default.id: "other", by_hand.id: "user",
    }


async def test_another_integrations_entity_never_lists_a_device(hass: HomeAssistant):
    """A battery sensor Battery Notes adds to a device is not the
    device's own (rule WATCH-02): switched off, it lists nothing, and a
    turn-on leaves it alone (rule REC-05)."""
    source, device = _device(hass, "noted")
    _entity(hass, source, device, "noted_temp", "noted_temperature")
    foreign = _entity(
        hass, source, device, "noted_bn", "noted_battery_plus",
        platform="battery_notes", disabled_by=INTEGRATION,
        device_class="battery", unit="%",
    )
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    assert coord.switched_off(device.id, "battery") is None
    assert coord.page_turn_on(device.id, "battery") == 0
    assert er.async_get(hass).async_get(foreign).disabled_by is INTEGRATION


async def test_one_entity_of_the_kind_on_is_enough(hass: HomeAssistant):
    """A ZHA-shaped device with its RSSI on and its LQI off has a
    signal, so it is not listed (rule REC-05)."""
    source, device = _device(hass, "zha_like")
    _entity(hass, source, device, "zl_rssi", "zha_like_rssi", device_class="signal_strength", unit="dBm")
    _entity(hass, source, device, "zl_lqi", "zha_like_lqi", disabled_by=INTEGRATION)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    assert coord.switched_off(device.id, "signal") is None


@pytest.mark.parametrize(
    "kind,object_id,device_class,unit",
    [
        ("last_seen", "plug_last_seen", None, None),
        ("battery", "plug_battery", "battery", "%"),
        ("signal", "plug_linkquality", None, None),
    ],
)
async def test_a_turn_on_reaches_one_device_and_one_kind(
    hass: HomeAssistant, kind, object_id, device_class, unit
):
    """One device, one kind. Another device's switched-off entity of the
    same kind, and this device's other kinds, stay off, and the brief
    carries one row on the device's line (rule DASH-09)."""
    source, device = _device(hass, "plug", name="Hall Plug")
    target = _entity(
        hass, source, device, f"p_{kind}", object_id,
        disabled_by=INTEGRATION, device_class=device_class, unit=unit,
    )
    other_kind = _entity(
        hass, source, device, "p_other",
        "plug_last_seen" if kind != "last_seen" else "plug_linkquality",
        disabled_by=INTEGRATION,
    )
    source2, neighbour = _device(hass, "neighbour")
    theirs = _entity(
        hass, source2, neighbour, f"n_{kind}", f"neighbour_{object_id}",
        disabled_by=INTEGRATION, device_class=device_class, unit=unit,
    )
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    registry = er.async_get(hass)
    assert coord.page_turn_on(device.id, kind) == 1
    assert registry.async_get(target).disabled_by is None
    assert registry.async_get(other_kind).disabled_by is INTEGRATION
    assert registry.async_get(theirs).disabled_by is INTEGRATION
    rows = [
        row for row in coord.data.get(DATA_SYSTEM_EVENTS) or []
        if "turned on, from its device page" in str(row.get(SYS_DETAIL))
    ]
    assert len(rows) == 1
    # A second press finds nothing left and records nothing.
    assert coord.page_turn_on(device.id, kind) == 0


async def test_a_turn_on_refuses_an_unknown_kind(hass: HomeAssistant):
    source, device = _device(hass, "odd")
    _entity(hass, source, device, "odd_t", "odd_temperature")
    entry = await setup_entry(hass)
    with pytest.raises(ValueError):
        entry.runtime_data.page_turn_on(device.id, "everything")


async def test_the_status_sensor_keeps_no_awaiting_counts(hass: HomeAssistant):
    """The status sensor keeps no awaiting-enable attributes
    (rule CFG-07)."""
    source, device = _device(hass, "await")
    _entity(hass, source, device, "aw_ls", "await_last_seen", disabled_by=INTEGRATION)
    await setup_entry(hass)
    status = hass.states.get("sensor.device_sentinel_status")
    assert not any(key.endswith("_awaiting_enable") for key in status.attributes)
