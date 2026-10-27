# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_config_screens.py, Version: 0.27.10 (2026-10-27)

"""What the configuration screens promise a person reading them (rules
CFG-01, CFG-02, CFG-05).

A large house runs hundreds of devices across a hundred integrations,
and a picker of three hundred names in whatever order the coordinator
built them is not a list anybody reads, so the choosers are sorted.

Sorting is asserted at the source rather than trusted to the
selector's own flag, because the flag is a request to a frontend and
these tests run without one.
"""

from __future__ import annotations

import json
import pathlib

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.config_flow import _device_options
from custom_components.device_sentinel.const import (
    CONF_BATTERY_MUTED_DEVICES,
    CONF_BATTERY_MUTED_INTEGRATIONS,
    CONF_BATTERY_MUTED_LABELS,
    CONF_MUTED_DEVICES,
    CONF_MUTED_INTEGRATIONS,
    CONF_MUTED_LABELS,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_LOW_THRESHOLD,
)

from .helpers import register_device, setup_entry


def _labels(options) -> list[str]:
    return [option["label"] for option in options]


async def test_the_device_picker_is_sorted_by_name(hass: HomeAssistant):
    """Row order is the coordinator's; the picker's order is the
    reader's."""
    rows = [
        {"device_id": "d1", "name": "Zigbee Plug"},
        {"device_id": "d2", "name": "Attic Sensor"},
        {"device_id": "d3", "name": "motion hall"},
        {"device_id": "d4", "name": "Basement Leak"},
    ]
    await setup_entry(hass)

    options = _device_options(
        rows, [], set(), lambda row: row["name"], dr.async_get(hass)
    )

    assert _labels(options) == [
        "Attic Sensor",
        "Basement Leak",
        "motion hall",
        "Zigbee Plug",
    ]


async def test_the_sort_ignores_case(hass: HomeAssistant):
    """A lowercase name belongs among its neighbours, not after the
    alphabet."""
    rows = [
        {"device_id": "d1", "name": "alpha"},
        {"device_id": "d2", "name": "Beta"},
        {"device_id": "d3", "name": "gamma"},
    ]
    await setup_entry(hass)

    options = _device_options(
        rows, [], set(), lambda row: row["name"], dr.async_get(hass)
    )

    assert _labels(options) == ["alpha", "Beta", "gamma"]


async def test_a_pick_added_back_is_sorted_in_with_the_rest(
    hass: HomeAssistant,
):
    """A held pick whose row has gone is offered back, and it takes
    its place in the order rather than being appended at the end."""
    device, _ = register_device(hass, "held", "Aardvark Sensor")
    await setup_entry(hass)
    rows = [
        {"device_id": "d1", "name": "Middle Device"},
        {"device_id": "d2", "name": "Zebra Device"},
    ]

    options = _device_options(
        rows, [device.id], set(), lambda row: row["name"], dr.async_get(hass)
    )

    assert _labels(options)[0].startswith("Aardvark Sensor")
    assert len(options) == 3


async def test_the_menu_is_called_configuration(hass: HomeAssistant):
    """The menu behind the gear icon is Configuration, as every other
    integration's is, because half these screens are exclusion lists
    rather than tuning (rule CFG-01).
    """
    package = pathlib.Path(
        __import__(
            "custom_components.device_sentinel.const", fromlist=["const"]
        ).__file__
    ).parent
    for source in (
        package / "strings.json",
        package / "translations" / "en.json",
    ):
        strings = json.loads(source.read_text())
        assert (
            strings["options"]["step"]["init"]["title"]
            == "Device Sentinel Configuration"
        )
        assert "Tuning" not in source.read_text()


async def test_a_section_saves_and_returns_to_the_menu(
    hass: HomeAssistant,
):
    """Submitting a section writes it and shows the menu again.

    Creating the entry would write the options and end the flow in one
    call, closing the dialog and dropping the person back in Home
    Assistant halfway through six screens (rule CFG-01).
    """
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "battery"}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_LOW_THRESHOLD: 33,
            "battery_muting": {
                CONF_BATTERY_MUTED_INTEGRATIONS: [],
                CONF_BATTERY_MUTED_LABELS: [],
                CONF_BATTERY_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_LOW_THRESHOLD] == 33


async def test_two_sections_in_one_visit_both_stick(hass: HomeAssistant):
    """The point of returning to the menu.

    A person crossing three screens in one sitting keeps all three,
    and each is written at the moment it is submitted rather than
    held until some later confirmation.
    """
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "battery"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_LOW_THRESHOLD: 22,
            "battery_muting": {
                CONF_BATTERY_MUTED_INTEGRATIONS: [],
                CONF_BATTERY_MUTED_LABELS: [],
                CONF_BATTERY_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_LOW_THRESHOLD] == 22

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "exclude": {
                CONF_EXCLUDED_INTEGRATIONS: ["ping"],
            },
            "muting": {
                CONF_MUTED_INTEGRATIONS: [],
                CONF_MUTED_LABELS: [],
                CONF_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["ping"]
    assert entry.options[CONF_LOW_THRESHOLD] == 22


async def test_the_menu_says_a_section_saves_on_submit(
    hass: HomeAssistant,
):
    """A person who submits and then closes the dialog has to be
    able to know their work was kept.

    Home Assistant labels the button Submit and gives us no say in
    it, so the menu's own description carries the promise instead.
    """
    package = pathlib.Path(
        __import__(
            "custom_components.device_sentinel.const", fromlist=["const"]
        ).__file__
    ).parent
    for source in (
        package / "strings.json",
        package / "translations" / "en.json",
    ):
        described = json.loads(source.read_text())["options"]["step"]["init"][
            "description"
        ]
        assert "saves when you submit it" in described
        assert "keeps everything you have already submitted" in described


async def test_the_excludes_live_in_a_section_and_store_flat(
    hass: HomeAssistant,
):
    """The section draws the screen; the keys stay flat (rule CFG-02).

    A Home Assistant section renders its name, then its description,
    then its fields, so the heading and its explanation sit above the
    pickers. Each screen keeps its plain settings loose at the top and
    moves its exclude ladder into a section, as Advanced does for Data
    Trim.

    Storage does not change. Every reader of these options, and every
    entry already on disk, knows them by their flat names, so a save
    unwraps the section before storing.
    """
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "battery"}
    )

    top = result["data_schema"].schema
    assert any(str(key) == "battery_muting" for key in top)
    assert not any("excluded" in str(key) for key in top)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_LOW_THRESHOLD: 25,
            "battery_muting": {
                CONF_BATTERY_MUTED_INTEGRATIONS: ["mqtt"],
                CONF_BATTERY_MUTED_LABELS: [],
                CONF_BATTERY_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_BATTERY_MUTED_INTEGRATIONS] == ["mqtt"]
    assert "battery_muting" not in entry.options


async def test_every_sectioned_screen_keeps_its_settings_loose(
    hass: HomeAssistant,
):
    """Sections hold only the mutes; the settings stay loose.

    What a person came for stays at the top, and the mutes sit below it
    under their own headings, because a screen that swept its settings
    into a section would bury them. Freeze and Unavailable Detection has
    two sections, one per mute (rules CFG-02, MUTE-06).
    """
    entry = await setup_entry(hass)
    expected = {
        "battery": (("battery_muting",), 2),
        "signal": (("signal_muting",), 4),
        "freeze": (("freeze_muting", "unavailable_muting"), 2),
        "exclusions": (("muting",), 1),
    }
    for step, (section_keys, loose_count) in expected.items():
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": step}
        )
        keys = [str(key) for key in result["data_schema"].schema]
        for section_key in section_keys:
            assert section_key in keys, step
        assert len(keys) == loose_count + len(section_keys), (step, keys)


async def test_each_section_carries_a_heading_and_an_explanation(
    hass: HomeAssistant,
):
    """Each section carries a heading and an explanation, because a
    section with neither would move the fields without moving the words
    (rule CFG-02).
    """
    package = pathlib.Path(
        __import__(
            "custom_components.device_sentinel.const", fromlist=["const"]
        ).__file__
    ).parent
    for source in (
        package / "strings.json",
        package / "translations" / "en.json",
    ):
        steps = json.loads(source.read_text())["options"]["step"]
        for step, key in (
            ("battery", "battery_muting"),
            ("signal", "signal_muting"),
            ("freeze", "freeze_muting"),
            ("exclusions", "muting"),
        ):
            block = steps[step]["sections"][key]
            assert block["name"], (step, "name")
            assert len(block["description"]) > 40, (step, "description")
            assert len(block["data"]) == 3, (step, "fields")
            assert len(block["data_description"]) == 3, (step, "help")


async def test_the_ignore_list_has_its_own_section(hass: HomeAssistant):
    """Both halves of Global Exclusions carry a heading (rule CFG-02).

    A loose field renders its label above the input and its help below
    it, which would leave the ignore list explained underneath its
    chooser while the exclude ladder beside it has its explanation
    above. This screen has no plain settings, only two groups of lists
    that need different explanations, so it has two sections and
    nothing loose.
    """
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "exclusions"}
    )

    assert [str(key) for key in result["data_schema"].schema] == [
        "exclude",
        "muting",
    ]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "exclude": {CONF_EXCLUDED_INTEGRATIONS: ["ping"]},
            "muting": {
                CONF_MUTED_INTEGRATIONS: [],
                CONF_MUTED_LABELS: [],
                CONF_MUTED_DEVICES: [],
            },
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.MENU
    assert entry.options[CONF_EXCLUDED_INTEGRATIONS] == ["ping"]
    assert "ignore" not in entry.options


async def test_both_halves_carry_a_heading_and_an_explanation(
    hass: HomeAssistant,
):
    """The whole point of giving ignore a section of its own."""
    package = pathlib.Path(
        __import__(
            "custom_components.device_sentinel.const", fromlist=["const"]
        ).__file__
    ).parent
    for source in (
        package / "strings.json",
        package / "translations" / "en.json",
    ):
        step = json.loads(source.read_text())["options"]["step"]["exclusions"]
        assert not step["data"], "nothing loose on this screen"
        # Devices sit with the integrations in one section (rule MUTE-03).
        assert step["sections"]["exclude"]["name"] == "Integrations and Devices to Exclude"
        assert (
            step["sections"]["muting"]["name"] == "Global Muting"
        )
        for key in ("exclude", "muting"):
            assert len(step["sections"][key]["description"]) > 60, key


async def test_maintenance_window_sits_above_the_data_trim_section(hass: HomeAssistant):
    """Rule CFG-02: plain settings first, sections below. The form draws
    its fields in the schema's order."""
    from custom_components.device_sentinel.const import CONF_MAINTENANCE_MINUTES

    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "advanced"}
    )
    names = [str(key) for key in result["data_schema"].schema]
    assert names[-1] == "data_trim"
    assert names.index(CONF_MAINTENANCE_MINUTES) < names.index("data_trim")
