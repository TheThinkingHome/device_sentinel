"""Tests for what the reports say about set-aside devices and dwell.

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_report_columns.py, Version: 0.13.6 (2026-08-13)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

Ruling #257 recorded why each device was set aside and the
classification file printed a tick regardless, so a disabled device
and a service device still read identically: the reason existed in
the data and never reached the page. The dwell chart had the same
shape of gap, recording the day's percentiles since 0.12.19 and
showing neither.
"""

import os

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DEV_SIGNAL_DAILY_MEAN,
    DEV_SIGNAL_DAILY_MIN,
    DEV_SIGNAL_DAILY_P5,
    DEV_SIGNAL_DAILY_P50,
    DEV_SIGNAL_DAILY_SD,
    DEV_SIGNAL_DWELL_DAILY,
    DEV_SIGNAL_VALUE,
    REPORT_WWW_DIR,
    SET_ASIDE_DISABLED,
    SET_ASIDE_NO_ENTITIES,
    SET_ASIDE_SERVICE,
)

from .helpers import register_device, setup_coordinator


def _classification(hass) -> str:
    path = hass.config.path("device_sentinel/classification.md")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _dwell_page(hass) -> str:
    path = os.path.join(
        hass.config.path(REPORT_WWW_DIR), "signal_dwell.html"
    )
    with open(path, encoding="utf-8") as handle:
        return handle.read()


async def test_each_reason_is_named_in_the_classification(
    hass: HomeAssistant,
):
    """Three ways to be set aside, three words. A column that can only
    say yes tells a person nothing about which one they are looking
    at, which is what sent one device hunting through diagnostics."""
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "svc")},
        name="Service One",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    disabled = registry.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "off")},
        name="Disabled One",
        disabled_by=dr.DeviceEntryDisabler.USER,
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "off_0",
        device_id=disabled.id, config_entry=source,
    )
    registry.async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "bare")},
        name="Bare One",
    )
    coord = await setup_coordinator(hass)
    # Past the startup window, where the no-entities rule is held
    # because an integration may still be loading (ruling #260).
    coord._grace_until = 0.0
    coord._rebuild_registry_view()

    await hass.async_add_executor_job(coord._write_reports, "manual")
    text = _classification(hass)

    rows = {
        line.split("|")[1].strip(): line
        for line in text.splitlines()
        if line.startswith("| ")
    }
    assert SET_ASIDE_SERVICE in rows["Service One"]
    assert SET_ASIDE_DISABLED in rows["Disabled One"]
    assert SET_ASIDE_NO_ENTITIES in rows["Bare One"]


async def test_the_header_names_all_three_causes(hass: HomeAssistant):
    """The sentence called every set-aside device a service device,
    which stopped being true the moment disabled devices joined
    them."""
    coord = await setup_coordinator(hass)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    text = _classification(hass)

    assert "service devices, disabled devices, and devices with no" in text
    assert "no hardware to watch" not in text


async def test_the_dwell_table_carries_the_percentiles(
    hass: HomeAssistant,
):
    """Recorded since 0.12.19 and shown nowhere. The order runs from
    the device's own baseline upward: floor, now, P5, median, then
    the mean and its spread."""
    device, _ = register_device(hass, "rc1", "Dwelling Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_VALUE] = 96.0
    record[DEV_SIGNAL_DAILY_MIN] = [80.0] * 14
    record[DEV_SIGNAL_DWELL_DAILY] = [42.0]
    record[DEV_SIGNAL_DAILY_MEAN] = [104.0]
    record[DEV_SIGNAL_DAILY_SD] = [8.0]
    record[DEV_SIGNAL_DAILY_P5] = [86.0]
    record[DEV_SIGNAL_DAILY_P50] = [101.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _dwell_page(hass)

    assert "<th>P5</th><th>Median</th>" in page
    assert "<td>86</td><td>101</td>" in page


async def test_a_device_with_no_percentiles_reads_from_tonight(
    hass: HomeAssistant,
):
    """Every device on the first day after a change to what is
    recorded, so the page says so rather than printing a blank."""
    device, _ = register_device(hass, "rc2", "Fresh Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_VALUE] = 96.0
    record[DEV_SIGNAL_DAILY_MIN] = [80.0] * 14
    record[DEV_SIGNAL_DWELL_DAILY] = [42.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _dwell_page(hass)

    assert "from tonight" in page


async def test_the_legend_explains_every_column(hass: HomeAssistant):
    """A table of eleven columns that names none of them is a puzzle.
    Each heading is explained where the table is, not on the wiki."""
    device, _ = register_device(hass, "rc3", "Legend Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    record[DEV_SIGNAL_VALUE] = 96.0
    record[DEV_SIGNAL_DAILY_MIN] = [80.0] * 14
    record[DEV_SIGNAL_DWELL_DAILY] = [42.0]

    await hass.async_add_executor_job(coord._write_reports, "manual")
    page = _dwell_page(hass)

    for heading in (
        "<b>Dwell</b>",
        "<b>Prior Day</b>",
        "<b>Days Over Red</b>",
        "<b>Floor</b>",
        "<b>Now</b>",
        "<b>P5</b>",
        "<b>Median</b>",
    ):
        assert heading in page
