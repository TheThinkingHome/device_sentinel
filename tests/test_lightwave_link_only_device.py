# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_lightwave_link_only_device.py, Version: 0.30.11 (2026-11-27)

"""A Lightwave device left with nothing that reports but its Connected sensor (rule STACK-16).

Lightwave Smart 5.5 moves a radio device's reporting entity to its light or
socket, so the radio device ("<name> Device") keeps only its Connected sensor
and its firmware notice. While that sensor reads on, the hub reaches the
device: it is never called stopped reporting, and one already listed by its
clock alone leaves the Problem List once the sensor
reads on, whether it came on after off, after unavailable, or read on all
along. Not inside the startup grace. A Z-Wave node with only its node status
keeps the clock rule.
"""

from __future__ import annotations

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.device_sentinel.const import (
    CONF_HIGH_PRIORITY_TARGETS,
    DATA_DEVICES,
    DEV_FROZEN_CATEGORY,
    DEV_LAST_ACTIVITY,
    DEV_TODAY_MAX,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_FROZEN,
)

from .helpers import record_events, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, walk
from .test_lightwave_connectivity import HOUR, _house
from .test_zwave_dead_node import DAY, _zwave

DOMAIN = "lightwave_smart"


def _listed_as_before(monkeypatch, coord):
    """The old verdict: the Connected sensor not read for a device with
    nothing else, so the clock alone lists it while the sensor reads on."""
    monkeypatch.setattr(type(coord), "_link_up", lambda self, device_id: False)


async def test_a_radio_device_left_with_only_its_link_is_never_called_frozen(
    hass: HomeAssistant, freezer
):
    coord, dev, ids, records = await _house(hass, freezer)
    er.async_get(hass).async_remove(ids["led"])  # the 5.5 move
    await hass.async_block_till_done()
    await walk(hass, freezer, 8 * HOUR, step=600)
    assert records["radio"][DEV_FROZEN_CATEGORY] is None, "its hub reaches it"
    # Off still takes it down.
    hass.states.async_set(ids["link"], "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 15 * 60)
    assert records["radio"][DEV_FROZEN_CATEGORY] is not None


async def test_one_listed_while_its_link_read_on_all_along_clears(
    hass: HomeAssistant, freezer, monkeypatch
):
    """Listed while Connected, nothing changing since."""
    coord, dev, ids, records = await _house(hass, freezer)
    er.async_get(hass).async_remove(ids["led"])
    await hass.async_block_till_done()
    recoveries = record_events(hass, EVENT_RECOVERED)
    with monkeypatch.context() as patch:
        _listed_as_before(patch, coord)
        await walk(hass, freezer, 8 * HOUR, step=600)
        assert records["radio"][DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN, "precondition"
    # Now the sensor still reads on, and nothing has changed.
    before = records["radio"][DEV_TODAY_MAX]
    await walk(hass, freezer, 120)
    assert records["radio"][DEV_FROZEN_CATEGORY] is None
    assert records["radio"][DEV_TODAY_MAX] == before, "the silence is not learned as a gap"
    assert [e for e in recoveries if e.get("device_id") == dev["radio"].id], "closed as a recovery"


async def test_short_unavailable_spells_then_connected_clear_it(
    hass: HomeAssistant, freezer, monkeypatch
):
    """Ten-second unavailable spells at restarts and while sensors are
    enabled, then Connected again."""
    coord, dev, ids, records = await _house(hass, freezer)
    er.async_get(hass).async_remove(ids["led"])
    await hass.async_block_till_done()
    with monkeypatch.context() as patch:
        _listed_as_before(patch, coord)
        await walk(hass, freezer, 8 * HOUR, step=600)
    hass.states.async_set(ids["link"], "unavailable")
    await hass.async_block_till_done()
    assert records["radio"][DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    for _ in range(3):
        hass.states.async_set(ids["link"], "unavailable")
        await hass.async_block_till_done()
        await walk(hass, freezer, 10, step=10)
        hass.states.async_set(ids["link"], "on")
        await hass.async_block_till_done()
        await walk(hass, freezer, 30, step=30)
    await walk(hass, freezer, 120)
    assert records["radio"][DEV_FROZEN_CATEGORY] is None


async def test_unavailable_alone_clears_nothing(hass: HomeAssistant, freezer, monkeypatch):
    coord, dev, ids, records = await _house(hass, freezer)
    er.async_get(hass).async_remove(ids["led"])
    await hass.async_block_till_done()
    with monkeypatch.context() as patch:
        _listed_as_before(patch, coord)
        await walk(hass, freezer, 8 * HOUR, step=600)
    hass.states.async_set(ids["link"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    assert records["radio"][DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN


async def test_a_dimmer_listed_while_its_link_said_nothing_clears_when_it_reads_on(
    hass: HomeAssistant, freezer
):
    """A light that still reports, listed frozen while its link was
    unavailable: its link reading on again is its hub hearing it."""
    coord, dev, ids, records = await _house(hass, freezer)
    hass.states.async_set(ids["link"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 8 * HOUR, step=600)
    assert records["light"][DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN, "precondition"
    hass.states.async_set(ids["link"], "on")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    assert records["light"][DEV_FROZEN_CATEGORY] is None


async def test_not_cleared_inside_the_startup_grace(hass: HomeAssistant, freezer, monkeypatch):
    """A restored "on" at a restart is not the hub hearing the device until
    the grace closes (rule WATCH-10)."""
    coord, dev, ids, records = await _house(hass, freezer)
    er.async_get(hass).async_remove(ids["led"])
    await hass.async_block_till_done()
    with monkeypatch.context() as patch:
        _listed_as_before(patch, coord)
        await walk(hass, freezer, 8 * HOUR, step=600)
    coord._grace_until = dt_util.utcnow().timestamp() + 600
    await walk(hass, freezer, 5 * 60)
    assert records["radio"][DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN, "held inside the grace"
    await walk(hass, freezer, 7 * 60)
    assert records["radio"][DEV_FROZEN_CATEGORY] is None


async def test_forty_listed_radio_devices_clear_with_one_push(
    hass: HomeAssistant, freezer, monkeypatch
):
    """Forty listed together clear together, and the phone hears it once."""
    freezer.move_to(PIN)
    source = MockConfigEntry(domain=DOMAIN)
    source.add_to_hass(hass)
    devices = dr.async_get(hass)
    reg = er.async_get(hass)
    hub = devices.async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(DOMAIN, "hub-fs")}, name="LinkPlus", model="L2",
    )
    radios, links, leds = [], [], []
    for i in range(40):
        radio = devices.async_get_or_create(
            config_entry_id=source.entry_id, identifiers={(DOMAIN, f"dev-{i}")},
            name=f"Switch {i} Device", model="L42",
        )
        radio = devices.async_update_device(radio.id, via_device_id=hub.id)
        leds.append(reg.async_get_or_create(
            "light", DOMAIN, f"fs-{i}_rgbColor", device_id=radio.id, config_entry=source,
            entity_category=EntityCategory.CONFIG,
        ).entity_id)
        reg.async_get_or_create(
            "update", DOMAIN, f"dev-{i}_firmware", device_id=radio.id, config_entry=source,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        links.append(reg.async_get_or_create(
            "binary_sensor", DOMAIN, f"dev-{i}_connectivity", device_id=radio.id, config_entry=source,
            entity_category=EntityCategory.DIAGNOSTIC,
        ).entity_id)
        radios.append(radio)
    for entity_id in links + leds:
        hass.states.async_set(entity_id, "on")
    phone = async_mock_service(hass, "notify", "phone")
    coord = await setup_coordinator(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.phone"]})
    for radio in radios:
        arm(coord, radio.id, rhythm=2 * HOUR)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    for entity_id in leds:
        hass.states.async_set(entity_id, "off")  # each heard once
    await hass.async_block_till_done()
    for entity_id in leds:
        reg.async_remove(entity_id)  # the 5.5 move
    await hass.async_block_till_done()
    with monkeypatch.context() as patch:
        _listed_as_before(patch, coord)
        await walk(hass, freezer, 8 * HOUR, step=600)
        records = [coord.data[DATA_DEVICES][radio.id] for radio in radios]
        assert all(r[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN for r in records), "precondition"
    phone.clear()
    await walk(hass, freezer, 120)
    assert all(r[DEV_FROZEN_CATEGORY] is None for r in records)
    assert len(phone) == 1, [c.data.get("message") for c in phone]


async def test_a_z_wave_node_with_only_its_status_keeps_the_clock_rule(hass: HomeAssistant, freezer):
    """Alive but silent past its window: still frozen (rules WATCH-04, STACK-05)."""
    freezer.move_to(PIN)
    source, device, ids = _zwave(hass, last_seen=False)
    reg = er.async_get(hass)
    for key in ("switch", "rssi"):
        reg.async_remove(ids[key])
    hass.states.async_set(ids["status"], "alive")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id, rhythm=3.05 * DAY)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    record[DEV_LAST_ACTIVITY] = dt_util.utcnow().timestamp()  # last heard now
    await walk(hass, freezer, 8 * DAY, step=3600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
