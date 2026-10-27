# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_recommendation_acknowledgement.py, Version: 0.27.10 (2026-10-27)

"""The switched-off cards and acknowledging a recommendation (rules
REC-05, REC-07).

Beside Last Seen Sensor Switched Off sit Battery, Signal, and Z-Wave
Status as its own card. Every row, and every written recommendation,
carries a tick a person can set and take back, kept in the answers file
and forgotten when its device leaves the card or its line goes. A
sensor a person switched off themselves starts ticked. What is ticked
leaves the count and the emailed Brief (rules REC-08, REC-10); Simple's
cards and lines are marked (rule REC-09).
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel.answers_store import ANSWERS_STORE_KEY
from custom_components.device_sentinel.const import CONF_HIGH_PRIORITY_TARGETS

from tests.helpers import register_device, setup_entry

INTEGRATION = er.RegistryEntryDisabler.INTEGRATION
USER = er.RegistryEntryDisabler.USER


def _battery_off(hass: HomeAssistant, uid: str, name: str, by=INTEGRATION):
    device, (entity_id,) = register_device(hass, uid, name=name)
    registry = er.async_get(hass)
    registry.async_update_entity(
        entity_id, original_device_class="battery", disabled_by=by,
    )
    registry.async_update_entity(entity_id, unit_of_measurement="%")
    return device, entity_id


def _card(coord, kind: str):
    return next((c for c in coord.device_recommendations() if c["kind"] == kind), None)


async def test_the_battery_card_lists_its_devices_and_is_in_simple(hass: HomeAssistant):
    """The Battery Sensor Switched Off card, shown in Simple; Signal
    Sensor Switched Off is shown in Simple too (rules REC-05, REC-09)."""
    device, _ = _battery_off(hass, "hall", "Hall Motion")
    sig, (sig_entity,) = register_device(hass, "sig", name="Shed Plug")
    er.async_get(hass).async_update_entity(
        sig_entity, original_device_class="signal_strength", disabled_by=INTEGRATION,
    )
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    card = _card(coord, "battery_off")
    assert card is not None and card["title"] == "Battery Sensor Switched Off"
    assert [row["device_id"] for row in card["devices"]] == [device.id]
    assert card["simple"] is True and card["active"] == 1
    assert "Turn them on from the Recommendations tab." in card["brief"]
    signal = _card(coord, "signal_off")
    assert signal is not None and signal["simple"] is True
    assert [row["device_id"] for row in signal["devices"]] == [sig.id]


async def test_a_tick_leaves_the_count_and_the_brief_and_can_be_taken_back(hass: HomeAssistant):
    """Ticked, the row stays listed and leaves the count and the emailed
    Brief; unticked, it counts again (rule REC-07)."""
    device, _ = _battery_off(hass, "hall", "Hall Motion")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    coord.set_recommendation_ack(True, kind="battery_off", device_id=device.id)
    card = _card(coord, "battery_off")
    assert card["devices"][0]["acknowledged"] is True and card["active"] == 0
    assert card["brief"] is None
    assert "Battery Sensor Switched Off" not in "\n".join(coord._recommendations_section())
    coord.set_recommendation_ack(False, kind="battery_off", device_id=device.id)
    card = _card(coord, "battery_off")
    assert card["active"] == 1
    assert "Battery Sensor Switched Off" in "\n".join(coord._recommendations_section())


async def test_the_brief_line_counts_what_is_not_ticked(hass: HomeAssistant):
    """The emailed Brief's line carries the same number as the card's
    title, the rows not ticked, and leaves with the last (rule REC-10)."""
    first, _ = _battery_off(hass, "a", "Alpha")
    second, _ = _battery_off(hass, "b", "Bravo")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    assert "Battery Sensor Switched Off (2): " in "\n".join(coord._recommendations_section())
    coord.set_recommendation_ack(True, kind="battery_off", device_id=first.id)
    section = "\n".join(coord._recommendations_section())
    assert "Battery Sensor Switched Off (1): " in section
    coord.set_recommendation_ack(True, kind="battery_off", device_id=second.id)
    assert "Battery Sensor Switched Off" not in "\n".join(coord._recommendations_section())


async def test_a_new_device_on_a_ticked_card_is_active_on_its_own(hass: HomeAssistant):
    """Three ticked, a fourth joins, the count is one (rule REC-08)."""
    first, _ = _battery_off(hass, "a", "Alpha")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    coord.set_recommendation_ack(True, kind="battery_off", device_id=first.id)
    second, _ = _battery_off(hass, "b", "Bravo")
    coord._rebuild_registry_view()
    card = _card(coord, "battery_off")
    ticks = {row["device_id"]: row["acknowledged"] for row in card["devices"]}
    assert ticks == {first.id: True, second.id: False}
    assert card["active"] == 1


async def test_a_tick_is_forgotten_when_its_device_leaves_the_card(hass: HomeAssistant):
    """Switched on, the device leaves the card and its tick goes; off
    again, it is active again (rule REC-07)."""
    device, entity_id = _battery_off(hass, "hall", "Hall Motion")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    coord.set_recommendation_ack(True, kind="battery_off", device_id=device.id)
    registry = er.async_get(hass)
    registry.async_update_entity(entity_id, disabled_by=None)
    coord._rebuild_registry_view()
    assert _card(coord, "battery_off") is None
    # Forgotten at the midnight run, the one place ticks are forgotten.
    assert coord._acks()["devices"]["battery_off"] == {device.id: True}
    coord.prune_recommendation_acks()
    assert "battery_off" not in coord._acks()["devices"]
    registry.async_update_entity(entity_id, disabled_by=INTEGRATION)
    coord._rebuild_registry_view()
    assert _card(coord, "battery_off")["devices"][0]["acknowledged"] is False


async def test_a_sensor_its_person_switched_off_starts_ticked(hass: HomeAssistant):
    """Shown, so the person sees Device Sentinel would like it on, and
    not counted; unticking counts it (rule REC-07)."""
    device, _ = _battery_off(hass, "hall", "Hall Motion", by=USER)
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    card = _card(coord, "battery_off")
    assert card["devices"][0]["acknowledged"] is True and card["devices"][0]["by_user"] is True
    assert card["active"] == 0
    coord.set_recommendation_ack(False, kind="battery_off", device_id=device.id)
    assert _card(coord, "battery_off")["active"] == 1


async def test_a_written_line_is_ticked_by_its_key(hass: HomeAssistant):
    """A line naming no device is ticked too, and leaves the emailed
    Brief; Simple shows the target lines (rules REC-07, REC-09)."""
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.old_phone"]})
    coord = entry.runtime_data
    lines = coord.recommendation_lines()
    gone = next(line for line in lines if line["key"] == "target:notify.old_phone")
    assert gone["simple"] is True and gone["acknowledged"] is False
    coord.set_recommendation_ack(True, line="target:notify.old_phone")
    assert next(line for line in coord.recommendation_lines() if line["key"] == gone["key"])["acknowledged"]
    assert "notify.old_phone" not in "\n".join(coord._recommendations_section())
    with pytest.raises(ValueError):
        coord.set_recommendation_ack(True, line="no_such_line")


async def test_ticks_survive_a_restart_in_the_answers_file(hass: HomeAssistant, hass_storage):
    """Kept with the other answers a person gives (rule STOR-20)."""
    device, _ = _battery_off(hass, "hall", "Hall Motion")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    coord.set_recommendation_ack(True, kind="battery_off", device_id=device.id)
    await coord.async_flush_answers()
    saved = hass_storage[ANSWERS_STORE_KEY]["data"]
    assert saved["acknowledged"]["devices"]["battery_off"] == {device.id: True}
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    assert _card(coord, "battery_off")["devices"][0]["acknowledged"] is True


async def test_damaged_ticks_are_dropped_not_fatal(hass: HomeAssistant, hass_storage):
    """A tick that is not true or false is dropped and the start goes on
    (rule STOR-05)."""
    hass_storage[ANSWERS_STORE_KEY] = {
        "version": 1, "key": ANSWERS_STORE_KEY,
        "data": {"power": {}, "types": {}, "acknowledged": {"devices": {"battery_off": {"x": "yes"}}, "lines": []}},
    }
    entry = await setup_entry(hass)
    assert entry.runtime_data._acks() == {"devices": {}, "lines": {}}


async def test_the_ws_command_ticks_and_refuses_a_stale_row(hass: HomeAssistant, hass_ws_client):
    device, _ = _battery_off(hass, "hall", "Hall Motion")
    entry = await setup_entry(hass)
    entry.runtime_data._rebuild_registry_view()
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "device_sentinel/recommendation_ack",
                            "kind": "battery_off", "device_id": device.id, "on": True})
    assert (await client.receive_json())["success"]
    await client.send_json({"id": 2, "type": "device_sentinel/recommendation_ack",
                            "kind": "battery_off", "device_id": "gone", "on": True})
    reply = await client.receive_json()
    assert not reply["success"] and reply["error"]["code"] == "not_found"


async def test_a_line_missing_at_a_start_keeps_its_tick(hass: HomeAssistant, hass_storage):
    """A line can be absent at a start, before a reader has heard, or
    while the Supervisor does not answer. Reading never forgets a tick,
    a start keeps it, and only the midnight run forgets a line that is
    gone then (rule REC-07)."""
    entry = await setup_entry(hass, {CONF_HIGH_PRIORITY_TARGETS: ["notify.old_phone"]})
    coord = entry.runtime_data
    coord.set_recommendation_ack(True, line="target:notify.old_phone")
    entries = coord._recommendation_entries
    coord._recommendation_entries = lambda: [e for e in entries() if e["key"] != "target:notify.old_phone"]
    coord.recommendation_lines()
    coord._recommendations_section()
    assert coord._acks()["lines"] == {"target:notify.old_phone": True}
    await coord.async_flush_answers()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    assert coord._acks()["lines"] == {"target:notify.old_phone": True}
    entries = coord._recommendation_entries
    coord._recommendation_entries = lambda: [e for e in entries() if e["key"] != "target:notify.old_phone"]
    coord.prune_recommendation_acks()
    assert coord._acks()["lines"] == {}


async def test_only_a_real_midnight_forgets(hass: HomeAssistant):
    """The catch-up fold a start runs forgets nothing; a real midnight
    does (rule REC-07)."""
    device, entity_id = _battery_off(hass, "hall", "Hall Motion")
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._rebuild_registry_view()
    coord.set_recommendation_ack(True, kind="battery_off", device_id=device.id)
    er.async_get(hass).async_update_entity(entity_id, disabled_by=None)
    coord._rebuild_registry_view()
    await coord._on_midnight(None)
    assert coord._acks()["devices"] == {"battery_off": {device.id: True}}
    await coord._on_midnight(object())
    assert coord._acks()["devices"] == {}


async def test_the_report_writer_only_reads_the_ticks(hass: HomeAssistant):
    """The report is written off Home Assistant's own thread; it reads
    the ticks and never changes them (rule CODE-06)."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    coord._recommendation_acks = {"devices": {"battery_off": {"gone-device": True}}, "lines": {"gone": True}}
    await hass.async_add_executor_job(coord._recommendations_section)
    await hass.async_block_till_done()
    assert coord._recommendation_acks == {"devices": {"battery_off": {"gone-device": True}}, "lines": {"gone": True}}
