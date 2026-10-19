# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_never_the_device.py, Version: 0.26.7 (2026-10-19)

"""What is never the device speaking.

A firmware notice and a command button are Home Assistant's, never the
device reporting: their writes move no clock and end no verdict. A
device with nothing switched on but those is set aside, in words true
of it, and its integration reads "Nothing switched on to read"; a
device with everything switched off and nothing on stays watched for
the prompt (ruling #369). The Hue bridge's Zigbee connectivity sensor
is the bridge's word, never the light reporting (James, 17 and 18
October 2026). Found by the adversarial rounds of 0.26.6.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_FREEZE_MUTED_DEVICES,
    CONF_UNAVAILABLE_MUTED_DEVICES,
    DATA_DEVICES,
    DEV_DOWN_SINCE,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    EVENT_FAULT,
    EVENT_RECOVERED,
    FREEZE_CATEGORY_FROZEN,
    FREEZE_CATEGORY_UNAVAILABLE,
    SET_ASIDE_MEANINGS,
)

from .helpers import record_events, setup_coordinator
from .outage_helpers import PIN, arm, past_grace, walk
from .test_freeze_unavailable_split import _mine, _ready, _sensor

HOUR = 3600.0


# -------------------------------- firmware notices and command buttons


# 2. A firmware notice (update entity, not a main entity) changing while the
# device is judged unavailable on its main entity: the notice is the
# coordinator's, not the device speaking.
async def test_2_update_entity_change_is_not_a_recovery(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(
        hass, freezer, "r10d",
        extras=(("sensor", EntityCategory.DIAGNOSTIC), ("update", None)),
    )
    hass.states.async_set(ids["x1"], "off")
    await hass.async_block_till_done()
    back = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(ids["main"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    hass.states.async_set(ids["x1"], "on")
    await hass.async_block_till_done()
    await walk(hass, freezer, 5 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, record[DEV_FROZEN_CATEGORY]
    assert not _mine(back, device.id), "recovered on a firmware notice"


DIAG = ("sensor", EntityCategory.DIAGNOSTIC)


# A. Rule 9: an update entity's same-value write (state_reported, as a
# coordinator refresh writes it) moves the device's clock.
async def test_a_update_same_value_write_does_not_move_clock(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r11a", extras=(DIAG, ("update", None)))
    hass.states.async_set(ids["x1"], "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    before = record[DEV_LAST_ACTIVITY]
    hass.states.async_set(ids["x1"], "off")  # same value: state_reported
    await hass.async_block_till_done()
    assert record[DEV_LAST_ACTIVITY] == before, "update entity write moved the clock"


# A2. The same write ends a standing frozen verdict, with a recovery.
async def test_a2_update_same_value_write_does_not_end_freeze(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r11b", extras=(DIAG, ("update", None)))
    hass.states.async_set(ids["x1"], "off")
    await hass.async_block_till_done()
    for _ in range(int(12 * HOUR // 600)):
        if record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN:
            break
        await walk(hass, freezer, 600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    back = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(ids["x1"], "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 3 * 60)
    assert not _mine(back, device.id), ("recovered on a firmware notice", record[DEV_FROZEN_CATEGORY])
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN, record[DEV_FROZEN_CATEGORY]


# B. Rule 9: a device with no main entity (update + diagnostic only), down;
# the update entity comes back while the diagnostic stays unavailable.
async def test_b_no_main_update_back_does_not_end_unavailable(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _ready(hass, freezer, "r11c", main="update", extras=(DIAG,))
    assert not coord._main_entities.get(device.id)
    hass.states.async_set(ids["main"], "unavailable")
    hass.states.async_set(ids["x0"], "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, (coord._live_entity_states(device.id), record[DEV_FROZEN_SINCE], record.get("down_since"), coord._grace_until - dt_util.utcnow().timestamp())
    back = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(ids["main"], "off")
    await hass.async_block_till_done()
    await walk(hass, freezer, 5 * 60)
    assert not _mine(back, device.id), ("recovered on a firmware notice", record[DEV_FROZEN_CATEGORY])
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, record[DEV_FROZEN_CATEGORY]


async def test_5_a_command_button_press_is_not_a_report(hass: HomeAssistant, freezer):
    from .test_freeze_unavailable_split import _ready
    from custom_components.device_sentinel.const import FREEZE_CATEGORY_FROZEN
    coord, device, ids, record = await _ready(hass, freezer, "r12p", extras=(("button", None),))
    await walk(hass, freezer, 6 * HOUR, step=600)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN
    back = record_events(hass, EVENT_RECOVERED)
    hass.states.async_set(ids["x0"], dt_util.utcnow().isoformat())
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_FROZEN, "pressed in Home Assistant, not the device"
    assert not [e for e in back if e.get("device_id") == device.id]


# ---------------------- set aside: nothing switched on that can report


# 1. Rule 9: a device whose only entity is a firmware notice has nothing
# that could ever report, as one with no entity at all (#257, #369). In
# 0.26.5 the update entity's writes were its reports.
async def test_1_update_only_device_is_not_never_reported(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    _source, device, ids = _sensor(hass, "r12u", main="update", extras=())
    hass.states.async_set(ids["main"], "off")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    for _ in range(int(50 * HOUR // 1800)):
        # Coordinator refreshes rewrite the notice; it is never the device.
        hass.states.async_set(ids["main"], "off", force_update=True)
        await hass.async_block_till_done()
        await walk(hass, freezer, 1800, step=600)
    # Set aside as a device with no entities is (James, 17 October 2026).
    assert device.id not in coord._watched
    assert not [i for i in coord.todo_items if i["device_id"] == device.id]


async def test_6_a_device_with_only_a_command_button_is_set_aside(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    _source, device, ids = _sensor(hass, "r12b", main="button", extras=())
    hass.states.async_set(ids["main"], "unknown")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    assert device.id not in coord._watched


def _device(hass, uid, entities):
    source = MockConfigEntry(domain="broadlink", title="broadlink")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("broadlink", uid)}, name=f"Light {uid}")
    reg = er.async_get(hass)
    for index, (domain, enabled) in enumerate(entities):
        reg.async_get_or_create(
            domain, "broadlink", f"{uid}_{index}", device_id=device.id, config_entry=source,
            disabled_by=None if enabled else er.RegistryEntryDisabler.USER)
    return device


async def test_buttons_on_and_the_light_switched_off_is_set_aside(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    device = _device(hass, "ir1", [("button", True)] * 7 + [("light", False), ("remote", False)])
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    assert device.id not in coord._watched


async def test_a_firmware_notice_on_and_the_sensor_switched_off_is_set_aside(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    device = _device(hass, "ir2", [("update", True), ("sensor", False)])
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    assert device.id not in coord._watched


async def test_everything_switched_off_stays_watched_for_the_prompt(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    device = _device(hass, "ir3", [("light", False), ("sensor", False)])
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    assert device.id in coord._watched


async def test_a_button_beside_a_light_switched_on_stays_watched(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    device = _device(hass, "ir4", [("button", True), ("light", True)])
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    assert device.id in coord._watched


# E. The words shown for the reason a device switched-off-sensor plus
# firmware-notice device is set aside must be true of it.
async def test_e_set_aside_words_are_true(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    source = MockConfigEntry(domain="broadlink", title="broadlink")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("broadlink", "r14e")}, name="Light r14e")
    reg = er.async_get(hass)
    reg.async_get_or_create("update", "broadlink", "r14e_0", device_id=device.id, config_entry=source)
    reg.async_get_or_create("sensor", "broadlink", "r14e_1", device_id=device.id, config_entry=source,
                            disabled_by=er.RegistryEntryDisabler.USER)
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    reason = coord._set_aside[device.id][2]
    assert reason == "nothing switched on that can report"
    assert dict(SET_ASIDE_MEANINGS)[reason] == (
        "Switch on one of its other entities and Device Sentinel watches it."
    )


# F. The Integrations tab's standing for an integration whose only device
# is set aside this way: "service", whose meaning is "Its devices report
# themselves as services".
async def test_f_integration_standing_is_not_service(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    source = MockConfigEntry(domain="broadlink", title="broadlink")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("broadlink", "r14f")}, name="Light r14f")
    reg = er.async_get(hass)
    for index in range(4):
        reg.async_get_or_create("button", "broadlink", f"r14f_b{index}", device_id=device.id, config_entry=source)
    reg.async_get_or_create("light", "broadlink", "r14f_l", device_id=device.id, config_entry=source,
                            disabled_by=er.RegistryEntryDisabler.USER)
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    rows = {row["domain"]: row for row in coord.dashboard_integrations()}
    assert rows["broadlink"]["standing"] == "notices_only"


def _loaded(hass, domain):
    source = MockConfigEntry(domain=domain, title=domain)
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    return source


# 2. Rule 9's last sentence: a device with everything switched off and
# nothing on stays watched (#369). One whose only entity is a switched-off
# firmware notice is set aside as having no entities.
async def test_r15_2_only_a_switched_off_notice_is_set_aside_truthfully(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    source = _loaded(hass, "broadlink")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("broadlink", "r15b")}, name="Light r15b")
    er.async_get(hass).async_get_or_create(
        "update", "broadlink", "r15b_0", device_id=device.id, config_entry=source,
        disabled_by=er.RegistryEntryDisabler.USER)
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    # Set aside, with words true of it (James, 17 October 2026).
    assert device.id not in coord._watched
    reason = coord._set_aside[device.id][2]
    assert reason == "no entities"
    assert dict(SET_ASIDE_MEANINGS)[reason].startswith(
        "It has no entities of its own that can report"
    )


# 4. An integration whose set-aside devices are one notices-only and one
# with no entities reads "Service only" ("Its devices report themselves as
# services"), true of neither.
async def test_r15_4_mixed_set_aside_integration_standing(hass: HomeAssistant, freezer):
    freezer.move_to(PIN)
    source = _loaded(hass, "broadlink")
    reg = dr.async_get(hass)
    light = reg.async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("broadlink", "r15d1")}, name="Light r15d")
    reg.async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("broadlink", "r15d2")}, name="Bare r15d")
    er.async_get(hass).async_get_or_create(
        "button", "broadlink", "r15d_b", device_id=light.id, config_entry=source)
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    rows = {row["domain"]: row for row in coord.dashboard_integrations()}
    reasons = sorted(r for _n, d, r in coord._set_aside.values() if d == "broadlink")
    assert rows["broadlink"]["standing"] == "notices_only", (rows["broadlink"]["standing"], reasons)


# 4. Rule 9: an integration whose only device has no entities at all, no
# notice and no button, reads "Nothing switched on to read", whose meaning
# says its devices have firmware notices or command buttons switched on.
async def test_r17_4_bare_integration_standing_words(hass: HomeAssistant, freezer):
    from custom_components.device_sentinel.const import STANDING_MEANINGS

    freezer.move_to(PIN)
    source = MockConfigEntry(domain="bare", title="bare")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("bare", "r17d")}, name="Bare r17d")
    coord = await setup_coordinator(hass)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    rows = {row["domain"]: row for row in coord.dashboard_integrations()}
    standing = rows["bare"]["standing"]
    meaning = dict(STANDING_MEANINGS).get("Nothing switched on to read")
    # Its words fit a device with no entities too (James, 17 October 2026).
    assert standing == "notices_only"
    assert meaning == "Its devices have nothing switched on that can report."


# ------------ the Hue bridge's word is the bridge's, never the light's


async def test_r19_2_the_hue_bridge_word_is_not_the_light_reporting(hass: HomeAssistant, freezer):
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from .helpers import setup_coordinator
    from .outage_helpers import PIN, arm, past_grace

    freezer.move_to(PIN)
    source = MockConfigEntry(domain="hue", title="hue")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("hue", "r19h")}, name="Hue light r19h")
    reg = er.async_get(hass)
    light = reg.async_get_or_create("light", "hue", "r19h_l", device_id=device.id, config_entry=source).entity_id
    word = reg.async_get_or_create(
        "sensor", "hue", "r19h_z", device_id=device.id, config_entry=source,
        entity_category=EntityCategory.DIAGNOSTIC, translation_key="zigbee_connectivity").entity_id
    hass.states.async_set(light, "on")
    hass.states.async_set(word, "connected")
    coord = await setup_coordinator(hass)
    record = arm(coord, device.id)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    hass.states.async_set(light, "off")
    await hass.async_block_till_done()
    faults = record_events(hass, EVENT_FAULT)
    hass.states.async_set(light, "unavailable")
    freezer.tick(timedelta(milliseconds=5))
    hass.states.async_set(word, "connectivity_issue")
    await hass.async_block_till_done()
    await walk(hass, freezer, 30 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert _mine(faults, device.id)


async def _hue(hass, freezer, uid, kind="light", options=None):
    freezer.move_to(PIN)
    source = MockConfigEntry(domain="hue", title="hue")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("hue", uid)}, name=f"Hue {uid}")
    reg = er.async_get(hass)
    ids = {}
    if kind == "light":
        ids["main"] = reg.async_get_or_create(
            "light", "hue", f"{uid}_l", device_id=device.id, config_entry=source).entity_id
        hass.states.async_set(ids["main"], "on")
    else:
        ids["main"] = reg.async_get_or_create(
            "event", "hue", f"{uid}_e", device_id=device.id, config_entry=source).entity_id
        ids["battery"] = reg.async_get_or_create(
            "sensor", "hue", f"{uid}_b", device_id=device.id, config_entry=source,
            entity_category=EntityCategory.DIAGNOSTIC, original_device_class="battery",
            unit_of_measurement="%").entity_id
        hass.states.async_set(ids["main"], "unknown")
        hass.states.async_set(ids["battery"], "80", {"device_class": "battery", "unit_of_measurement": "%"})
    ids["word"] = reg.async_get_or_create(
        "sensor", "hue", f"{uid}_z", device_id=device.id, config_entry=source,
        entity_category=EntityCategory.DIAGNOSTIC, translation_key="zigbee_connectivity").entity_id
    hass.states.async_set(ids["word"], "connected")
    if options is not None:
        options = {k: [device.id] if v == "SELF" else v for k, v in options.items()}
    coord = await setup_coordinator(hass, options)
    record = arm(coord, device.id)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    if kind == "light":
        hass.states.async_set(ids["main"], "off")
    else:
        hass.states.async_set(ids["battery"], "79", {"device_class": "battery", "unit_of_measurement": "%"})
    await hass.async_block_till_done()
    return coord, device, ids, record


async def _lose(hass, freezer, ids):
    for key in ("main", "battery"):
        if key in ids:
            hass.states.async_set(ids[key], "unavailable")
    freezer.tick(timedelta(milliseconds=5))
    hass.states.async_set(ids["word"], "connectivity_issue")
    await hass.async_block_till_done()


# 1. A Hue light lost and found: the bridge's word first, then the light.
# Down while only the word is back; recovered when the light speaks; the
# saved outage start held until then.
async def test_r20_1_hue_light_back_through_the_light(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _hue(hass, freezer, "r20a")
    faults, back = record_events(hass, EVENT_FAULT), record_events(hass, EVENT_RECOVERED)
    await _lose(hass, freezer, ids)
    await walk(hass, freezer, 30 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert record.get(DEV_DOWN_SINCE) is not None
    assert len(_mine(faults, device.id)) == 1
    hass.states.async_set(ids["word"], "connected")
    await hass.async_block_till_done()
    await walk(hass, freezer, 10 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, "the bridge's word ended the outage"
    assert record.get(DEV_DOWN_SINCE) is not None, "the bridge's word cleared the saved start"
    assert not _mine(back, device.id)
    hass.states.async_set(ids["main"], "on")
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert record.get(DEV_DOWN_SINCE) is None
    assert len(_mine(back, device.id)) == 1


# 2. Rule 1 on a Hue light: freeze-muted, still reported unavailable.
async def test_r20_2_freeze_muted_hue_light_reported(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _hue(hass, freezer, "r20b", options={CONF_FREEZE_MUTED_DEVICES: "SELF"})
    faults = record_events(hass, EVENT_FAULT)
    await _lose(hass, freezer, ids)
    await walk(hass, freezer, 30 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert len(_mine(faults, device.id)) == 1


# 3. The bridge rewriting its word with the same value while the light is
# gone keeps nothing alive.
async def test_r20_3_same_value_word_keeps_nothing_alive(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _hue(hass, freezer, "r20c")
    await _lose(hass, freezer, ids)
    for _ in range(5):
        await walk(hass, freezer, 5 * 60)
        hass.states.async_set(ids["word"], "connectivity_issue", force_update=True)
        await hass.async_block_till_done()
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


# 4. A Hue dimmer: buttons at rest, a battery, the bridge's word. The
# bridge loses it: unavailable. Back through its battery: recovered.
async def test_r20_4_hue_dimmer_down_and_back(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _hue(hass, freezer, "r20d", kind="dimmer")
    faults, back = record_events(hass, EVENT_FAULT), record_events(hass, EVENT_RECOVERED)
    await _lose(hass, freezer, ids)
    await walk(hass, freezer, 30 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    hass.states.async_set(ids["word"], "connected")
    hass.states.async_set(ids["main"], "unknown")
    await hass.async_block_till_done()
    await walk(hass, freezer, 5 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE, "came back on buttons at rest"
    hass.states.async_set(ids["battery"], "78", {"device_class": "battery", "unit_of_measurement": "%"})
    await hass.async_block_till_done()
    await walk(hass, freezer, 120)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert len(_mine(faults, device.id)) == 1
    assert len(_mine(back, device.id)) == 1


# 5. No Z-Wave status row on a Hue device's page, and the word is not
# counted as a Z-Wave status awaiting enable.
async def test_r20_5_hue_page_has_no_node_status(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _hue(hass, freezer, "r20e")
    assert coord._node_status_view(device.id) is None
    assert device.id not in coord._node_status_entity
    assert coord.switched_off_devices("node_status") == {}


# 6. Unavailable mute on a Hue light: no verdict while down; lifted while
# still down, listed again from the outage start, and pushed.
async def test_r20_6_unavailable_mute_lifted_on_hue(hass: HomeAssistant, freezer):
    coord, device, ids, record = await _hue(hass, freezer, "r20f", options={CONF_UNAVAILABLE_MUTED_DEVICES: "SELF"})
    faults = record_events(hass, EVENT_FAULT)
    await _lose(hass, freezer, ids)
    lost = record.get(DEV_DOWN_SINCE)
    await walk(hass, freezer, 30 * 60)
    assert record[DEV_FROZEN_CATEGORY] is None
    assert not _mine(faults, device.id)
    coord.page_set_mute(device.id, "unavailable", False)
    await hass.async_block_till_done()
    await walk(hass, freezer, 5 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    assert lost is not None and abs(record["frozen_since"] - lost[0]) < 120, (record["frozen_since"], lost)
    assert len(_mine(faults, device.id)) == 1


# 7. Restart while a Hue light is down, the word holding a value: still
# unavailable after the restart (the word holds no device up).
async def test_r20_7_restart_while_hue_light_down(hass: HomeAssistant, freezer):
    from .outage_helpers import restart
    coord, device, ids, record = await _hue(hass, freezer, "r20g")
    await _lose(hass, freezer, ids)
    await walk(hass, freezer, 30 * 60)
    assert record[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE
    coord = await restart(hass, freezer)
    await walk(hass, freezer, 30 * 60)
    rec2 = coord.data[DATA_DEVICES][device.id]
    assert rec2[DEV_FROZEN_CATEGORY] == FREEZE_CATEGORY_UNAVAILABLE


# 5. A Hue light whose light entity is switched off and whose bridge word
# is switched on: not set aside (rule 9 names only notices and buttons),
# so it must be judged. Silent for days, then the bridge loses it.
async def test_r21_5_hue_word_only_device_is_judged_or_set_aside(hass: HomeAssistant, freezer):
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.const import EntityCategory
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from .helpers import setup_coordinator
    from .outage_helpers import PIN, arm, past_grace
    freezer.move_to(PIN)
    source = MockConfigEntry(domain="hue", title="hue")
    source.add_to_hass(hass)
    source.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("hue", "r21e")}, name="Hue r21e")
    reg = er.async_get(hass)
    reg.async_get_or_create("light", "hue", "r21e_l", device_id=device.id, config_entry=source,
                            disabled_by=er.RegistryEntryDisabler.USER)
    word = reg.async_get_or_create(
        "sensor", "hue", "r21e_z", device_id=device.id, config_entry=source,
        entity_category=EntityCategory.DIAGNOSTIC, translation_key="zigbee_connectivity").entity_id
    hass.states.async_set(word, "connected")
    coord = await setup_coordinator(hass, None)
    if device.id in coord._set_aside:
        return
    record = arm(coord, device.id)
    await hass.async_block_till_done()
    await past_grace(hass, freezer)
    seen = set()
    for _ in range(48):
        await walk(hass, freezer, HOUR, step=600)
        seen.add(record.get(DEV_FROZEN_CATEGORY))
    hass.states.async_set(word, "unavailable")
    await hass.async_block_till_done()
    await walk(hass, freezer, HOUR, step=300)
    seen.add(record.get(DEV_FROZEN_CATEGORY))
    assert seen != {None}, ("watched, never set aside, never judged in two days and an unavailable word",
                            device.id in coord._watched, coord._live_entity_states(device.id))
