"""Tests for what the reports say about set-aside devices.

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
    REPORT_WWW_DIR,
    SET_ASIDE_DISABLED,
    SET_ASIDE_NO_ENTITIES,
    SET_ASIDE_SERVICE,
)

from .helpers import setup_coordinator


def _classification(hass) -> str:
    path = hass.config.path("device_sentinel/classification.md")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _signal_page(hass) -> str:
    path = os.path.join(
        hass.config.path(REPORT_WWW_DIR), "signal_report.html"
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


async def test_the_header_names_every_cause(hass: HomeAssistant):
    """The sentence called every set-aside device a service device,
    which stopped being true the moment disabled devices joined them,
    and again when a person could ignore a whole integration."""
    coord = await setup_coordinator(hass)

    await hass.async_add_executor_job(coord._write_reports, "manual")
    text = _classification(hass)

    assert "service devices, disabled devices, devices with no" in text
    assert "integrations you asked to ignore" in text
    assert "no hardware to watch" not in text


