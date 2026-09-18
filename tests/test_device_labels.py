# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_device_labels.py, Version: 0.21.14 (2026-09-18)

"""A device's name in an HTML report: its area, and a link to it.

Issue #13, from fetzerch: on a large house the reports name a device
that means nothing on its own. Every one of his temperature sensors
is called "Temperature & Humidity", and finding the one that is
reported means going and looking. The name now carries its area in
square brackets and links to the device page, and the link is
absolute with the external URL preferred (ruling #183), so it works
from outside the house as well as in it.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

from custom_components.device_sentinel.const import (
    CONF_REPORT_LINKS,
    REPORT_LINKS_EXTERNAL,
    REPORT_LINKS_INTERNAL,
)
from tests.helpers import register_device, setup_coordinator


async def _linking(hass, coord, choice):
    """Turn links on, as a person does on the notifications screen."""
    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, CONF_REPORT_LINKS: choice},
    )
    await hass.async_block_till_done()


def _in_area(hass, device, area_name: str) -> None:
    area = ar.async_get(hass).async_get_or_create(area_name)
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)


async def test_the_name_carries_its_area(hass: HomeAssistant):
    device, _ = register_device(hass, "lab1", name="Temperature & Humidity")
    _in_area(hass, device, "Kitchen")
    coord = await setup_coordinator(hass)
    await _linking(hass, coord, REPORT_LINKS_INTERNAL)

    label = coord._device_cell(device.id, "Temperature & Humidity")
    assert "Temperature &amp; Humidity</a> [Kitchen]" in label


async def test_the_name_links_to_the_device_page(hass: HomeAssistant):
    device, _ = register_device(hass, "lab2", name="Motion Laundry")
    coord = await setup_coordinator(hass)
    await _linking(hass, coord, REPORT_LINKS_INTERNAL)

    label = coord._device_cell(device.id, "Motion Laundry")
    assert f'href="http://10.10.10.10:8123/config/devices/device/{device.id}"' in label
    assert ">Motion Laundry</a>" in label


async def test_a_device_with_no_area_says_none(hass: HomeAssistant):
    device, _ = register_device(hass, "lab3", name="HL-L2370DW")
    coord = await setup_coordinator(hass)
    await _linking(hass, coord, REPORT_LINKS_INTERNAL)

    label = coord._device_cell(device.id, "HL-L2370DW")
    assert label.endswith(">HL-L2370DW</a> [None]")


async def test_a_name_that_already_ends_in_a_bracket_is_left_alone(
    hass: HomeAssistant,
):
    """"Soil Moisture (Monstera) [Greenhouse]" reads as two
    afterthoughts. The name is already doing the work."""
    device, _ = register_device(hass, "lab4", name="Soil Moisture (Monstera)")
    _in_area(hass, device, "Greenhouse")
    coord = await setup_coordinator(hass)
    await _linking(hass, coord, REPORT_LINKS_INTERNAL)

    label = coord._device_cell(device.id, "Soil Moisture (Monstera)")
    assert "Greenhouse" not in label


async def test_a_row_that_belongs_to_no_device_is_plain(
    hass: HomeAssistant,
):
    """The system rows in the brief's own table."""
    coord = await setup_coordinator(hass)
    assert coord._device_cell(None, "The system") == "The system"


async def test_a_name_is_escaped_inside_the_link(hass: HomeAssistant):
    device, _ = register_device(hass, "lab5", name='Sensor "A" & <b>')
    coord = await setup_coordinator(hass)
    await _linking(hass, coord, REPORT_LINKS_INTERNAL)

    label = coord._device_cell(device.id, 'Sensor "A" & <b>')
    assert "<b>" not in label.replace("<b>", "", 0).split(">Sensor")[0]
    assert "&lt;b&gt;" in label
    assert "&amp;" in label


# ------------------------------------------------- the address setting


async def test_nothing_is_linked_until_a_person_says_so(
    hass: HomeAssistant,
):
    """A report is a file that gets shared. The house's address goes
    into one only when its owner chooses which address to use."""
    device, _ = register_device(hass, "lab6", name="Motion Laundry")
    _in_area(hass, device, "Laundry")
    coord = await setup_coordinator(hass)

    label = coord._device_cell(device.id, "Motion Laundry")
    assert label == "Motion Laundry [Laundry]"
    assert coord._report_link("/config/devices/device/x") is None


async def test_the_area_survives_the_setting_being_off(
    hass: HomeAssistant,
):
    """The area is a name, not an address, so it is never withheld."""
    device, _ = register_device(hass, "lab7", name="Temperature & Humidity")
    _in_area(hass, device, "Kitchen")
    coord = await setup_coordinator(hass)

    assert coord._device_cell(device.id, "Temperature & Humidity") == (
        "Temperature &amp; Humidity [Kitchen]"
    )


async def test_each_choice_uses_its_own_address(hass: HomeAssistant):
    device, _ = register_device(hass, "lab8", name="Motion Laundry")
    coord = await setup_coordinator(hass)
    hass.config.internal_url = "http://10.10.10.10:8123"
    hass.config.external_url = "https://house.example.com"

    await _linking(hass, coord, REPORT_LINKS_INTERNAL)
    assert coord._report_link("/x") == "http://10.10.10.10:8123/x"

    await _linking(hass, coord, REPORT_LINKS_EXTERNAL)
    assert coord._report_link("/x") == "https://house.example.com/x"
    assert "https://house.example.com" in coord._device_cell(
        device.id, "Motion Laundry"
    )


async def test_a_choice_that_home_assistant_cannot_serve_links_nothing(
    hass: HomeAssistant,
):
    """External chosen on a house that has no external address: a dead
    link helps nobody, so the name prints plain."""
    device, _ = register_device(hass, "lab9", name="Motion Laundry")
    coord = await setup_coordinator(hass)
    hass.config.internal_url = "http://10.10.10.10:8123"
    hass.config.external_url = None

    await _linking(hass, coord, REPORT_LINKS_EXTERNAL)
    assert coord._report_link("/x") is None
    assert coord._device_cell(device.id, "Motion Laundry") == (
        "Motion Laundry [None]"
    )


# ------------------------------------------------- inside the reports


async def test_the_brief_tables_carry_the_area_and_the_link(
    hass: HomeAssistant, freezer
):
    """The tables are composed as Markdown, which has lost the device
    by the time the page is rendered, so the pairing is kept for the
    render. The Markdown itself stays plain, because a notification
    carries that text."""
    from custom_components.device_sentinel.const import (
        DATA_DEVICES,
        DEV_FROZEN_CATEGORY,
        DEV_FROZEN_SINCE,
    )
    from homeassistant.util import dt as dt_util

    device, _ = register_device(hass, "brief1", name="Motion Laundry")
    _in_area(hass, device, "Laundry")
    coord = await setup_coordinator(hass)
    await _linking(hass, coord, REPORT_LINKS_INTERNAL)
    hass.config.internal_url = "http://10.10.10.10:8123"

    record = coord.data[DATA_DEVICES].setdefault(device.id, {})
    record[DEV_FROZEN_CATEGORY] = "unavailable"
    record[DEV_FROZEN_SINCE] = dt_util.utcnow().timestamp() - 600
    coord._sync_problem_list()
    await hass.async_block_till_done()
    await hass.async_add_executor_job(coord._write_reports, "manual")

    page = coord.hass.config.path("www/device_sentinel/daily_brief.html")
    with open(page, encoding="utf-8") as handle:
        html = handle.read()
    assert f"/config/devices/device/{device.id}" in html
    assert ">Motion Laundry</a> [Laundry]" in html


async def test_a_name_two_devices_share_is_not_linked(
    hass: HomeAssistant, freezer
):
    """An ambiguous link is worse than none: on the reference rig,
    "Dining Shades" is two registry devices."""
    first, _ = register_device(hass, "twin1", name="Dining Shades")
    second, _ = register_device(hass, "twin2", name="Dining Shades")
    coord = await setup_coordinator(hass)
    await _linking(hass, coord, REPORT_LINKS_INTERNAL)

    coord._brief_devices = {}
    coord._note_brief_device(first.id, "Dining Shades")
    coord._note_brief_device(second.id, "Dining Shades")
    assert coord._brief_devices["Dining Shades"] is None
    assert coord._brief_cells("| Dining Shades |") == ["Dining Shades"]
