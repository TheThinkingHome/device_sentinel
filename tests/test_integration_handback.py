# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_integration_handback.py, Version: 0.27.10 (2026-10-27)

"""An integration coming back gives its devices time to rejoin
(rules UP-08, UNAV-05).

A bridge gets that window and a recovering row, and so do Z-Wave and
Matter, but those stacks have no bridge reader: their devices are
carried by the integration rung, which must not drop the outage the
moment the entry loads again. A stick pull looks clean only when its
devices return before anyone looks.
"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    BRIDGE_HANDBACK_SECONDS,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    DATA_DEVICES,
    DATA_SYSTEM_EVENTS,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    EVENT_FAULT,
    EVENT_RECOVERED,
    INTEGRATION_DOWN_DWELL_SECONDS,
    SYS_INTEGRATION_UP,
    SYS_KIND,
    SYS_WORST,
    UPSTREAM_KIND,
)
from tests.helpers import record_events, setup_coordinator
from tests.outage_helpers import PIN, arm, past_grace, walk

HOUR = 3600.0


async def _outage_and_return(hass: HomeAssistant, domain: str, freezer):
    source = MockConfigEntry(domain=domain, title=f"{domain} hub")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    devices = []
    for index in range(2):
        device = registry.async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={(domain, f"node{index}")},
            name=f"Node {index}",
        )
        er.async_get(hass).async_get_or_create(
            "sensor", domain, f"node{index}",
            device_id=device.id, config_entry=source,
        )
        devices.append(device)
    coord = await setup_coordinator(hass)
    coord._grace_until = 0.0
    coord._rebuild_registry_view()
    for device in devices:
        coord._watched[device.id] = domain
        assert coord._stack_for_device(device.id) is None

    start = dt_util.utcnow().timestamp()
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(start)
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    coord._sample_integrations(start + 1)
    freezer.tick(INTEGRATION_DOWN_DWELL_SECONDS + 5)
    coord._sample_integrations(start + INTEGRATION_DOWN_DWELL_SECONDS + 5)
    for device in devices:
        record = coord.data[DATA_DEVICES].setdefault(device.id, {})
        record[DEV_FROZEN_CATEGORY] = "unavailable"
        record[DEV_FROZEN_SINCE] = start + 30
    coord._note_upstream_peaks()

    freezer.tick(240)
    back = start + INTEGRATION_DOWN_DWELL_SECONDS + 245
    source.mock_state(hass, ConfigEntryState.LOADED)
    coord._sample_integrations(back)
    return coord, source, devices, start


@pytest.fixture(autouse=True)
def _leave_entries_unloaded(hass):
    """A real domain's entry left loaded makes teardown import an
    integration this harness does not carry."""
    yield
    for entry in hass.config_entries.async_entries():
        if entry.domain in ("zwave_js", "matter"):
            entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


@pytest.mark.parametrize("domain", ["zwave_js", "matter"])
async def test_the_claim_survives_the_return(
    hass: HomeAssistant, domain, freezer
):
    coord, _source, devices, start = await _outage_and_return(
        hass, domain, freezer
    )
    found = coord.upstream_down_since(devices[0].id)
    assert found is not None, "the claim ended the moment the entry loaded"
    assert found[0] == domain
    assert abs(found[1] - (start + 1)) < 1.0


@pytest.mark.parametrize("domain", ["zwave_js", "matter"])
async def test_the_window_ends(hass: HomeAssistant, domain, freezer):
    coord, _source, devices, _start = await _outage_and_return(
        hass, domain, freezer
    )
    freezer.tick(BRIDGE_HANDBACK_SECONDS + 10)
    assert coord.upstream_down_since(devices[0].id) is None
    assert coord.upstream_recovering_at(domain) is None


async def test_the_row_says_the_integration_is_recovering(
    hass: HomeAssistant, freezer
):
    coord, _source, devices, start = await _outage_and_return(
        hass, "zwave_js", freezer
    )
    assert coord.upstream_recovering_at("zwave_js") is not None
    summary, body = coord._upstream_item_text(
        "zwave_js", {UPSTREAM_KIND: start + 1}, 2
    )
    assert summary == "Z-Wave is back: waiting for 2 devices to reconnect"
    assert "Z-Wave came back at" in body

    record = coord.data[DATA_DEVICES][devices[0].id]
    record[DEV_FROZEN_CATEGORY] = None
    record[DEV_FROZEN_SINCE] = None
    summary, _body = coord._upstream_item_text(
        "zwave_js", {UPSTREAM_KIND: start + 1}, 2
    )
    assert summary == (
        "Z-Wave recovering: 1 of the 2 devices that went down remains "
        "unavailable"
    )


async def test_the_return_records_the_worst_moment(
    hass: HomeAssistant, freezer
):
    coord, _source, _devices, _start = await _outage_and_return(
        hass, "zwave_js", freezer
    )
    row = [
        r for r in coord.data[DATA_SYSTEM_EVENTS]
        if r[SYS_KIND] == SYS_INTEGRATION_UP
    ][-1]
    assert row[SYS_WORST] == 2


# ----------------- an integration outage holds frozen devices


def _pair(hass, n=2, domain="shelly"):
    source = MockConfigEntry(domain=domain, title=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    reg = er.async_get(hass)
    out = []
    for i in range(n):
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id, identifiers={(domain, f"d{i}")}, name=f"Sensor d{i}")
        ids = {"main": reg.async_get_or_create("binary_sensor", domain, f"d{i}_main", device_id=device.id, config_entry=source).entity_id,
               "x0": reg.async_get_or_create("sensor", domain, f"d{i}_x0", device_id=device.id, config_entry=source,
                                             entity_category=EntityCategory.DIAGNOSTIC).entity_id}
        out.append((device, ids))
    return source, out


@pytest.mark.parametrize("dwell", ["real", "zero"])
@pytest.mark.parametrize("mode", ["none", "muteB", "muteBoth"])
async def test_integration_outage_holds_frozen(hass: HomeAssistant, freezer, mode, dwell, monkeypatch):
    if dwell == "zero":
        from custom_components.device_sentinel import interventions as iv
        monkeypatch.setattr(iv, "INTEGRATION_DOWN_DWELL_SECONDS", 0.0)
    freezer.move_to(PIN)
    source, devs = _pair(hass)
    for _, ids in devs:
        hass.states.async_set(ids["main"], "off")
        hass.states.async_set(ids["x0"], "87")
    muted = {"none": [], "muteB": [devs[1][0].id], "muteBoth": [d.id for d, _ in devs]}[mode]
    coord = await setup_coordinator(hass, {CONF_UNAVAILABLE_MUTED_DEVICES: muted} if muted else None)
    recs = [arm(coord, d.id) for d, _ in devs]
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    for _, ids in devs:
        hass.states.async_set(ids["main"], "on")
    await hass.async_block_till_done()
    await walk(hass, freezer, 6 * HOUR, step=600)
    cats = [r[DEV_FROZEN_CATEGORY] for r in recs]
    assert cats == ["frozen", "frozen"], cats
    heard = [r[DEV_LAST_ACTIVITY] for r in recs]
    back = record_events(hass, EVENT_RECOVERED)
    faults = record_events(hass, EVENT_FAULT)
    # The integration fails for ten minutes (a cloud outage, a reload
    # that retries): everything unavailable, then the cached values back.
    source.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    for _, ids in devs:
        for eid in ids.values():
            hass.states.async_set(eid, "unavailable")
    await hass.async_block_till_done()
    for k in range(10):
        await walk(hass, freezer, 60)
    source.mock_state(hass, ConfigEntryState.LOADED)
    for _, ids in devs:
        hass.states.async_set(ids["main"], "on")
        hass.states.async_set(ids["x0"], "87")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    info = dict(
        mode=mode, dwell=dwell,
        moved=[r[DEV_LAST_ACTIVITY] != h for r, h in zip(recs, heard)],
        cats=[r[DEV_FROZEN_CATEGORY] for r in recs],
        back=[(e.get("device_id") == devs[0][0].id and "A" or "B", e.get("kind"), e.get("kinds"), e.get("cause")) for e in back],
        faults=[(e.get("device_id") == devs[0][0].id and "A" or "B", e.get("kind") or e.get("category")) for e in faults],
        held=[coord.upstream_down_since(d.id) for d, _ in devs],
    )
    assert info["moved"] == [False, False], info
    assert info["cats"] == ["frozen", "frozen"], info
    assert not info["back"], info
