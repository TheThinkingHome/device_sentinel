"""What a stranger gets: an empty install, driven end to end.

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_fresh_install.py, Version: 0.13.8 (2026-08-13)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

Every other suite starts from a record the tests build. This one
starts from nothing: no storage, no history, no options, the state a
person is in the first time they press Add Integration. It walks the
first minutes, the first readings, and the first midnight, and asks
at each step whether what a person sees is true.
"""

import os

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel.const import (
    ATTR_AWAITING_BATTERY,
    DATA_DEVICES,
    DEV_SIGNAL_DAILY_P5,
    REPORT_DIR,
    REPORT_WWW_DIR,
)

from .helpers import register_device, setup_coordinator


async def test_a_fresh_install_writes_its_reports_at_once(
    hass: HomeAssistant,
):
    """The files exist from the first boot, so a dashboard card
    pointed at them is never a broken link, and a person who installs
    and immediately looks finds a page rather than a 404."""
    register_device(hass, "fi1", "First Device")
    coord = await setup_coordinator(hass)

    await hass.async_add_executor_job(coord._write_reports, "setup")

    reports = hass.config.path(REPORT_DIR)
    www = hass.config.path(REPORT_WWW_DIR)
    for name in ("device_telemetry.md", "classification.md"):
        assert os.path.exists(os.path.join(reports, name)), name
    for name in ("daily_brief.html", "battery_report.html"):
        assert os.path.exists(os.path.join(www, name)), name


async def test_a_fresh_install_claims_nothing_it_has_not_learned(
    hass: HomeAssistant,
):
    """The first minutes are the ones most likely to lie: no rhythm,
    no floor, no history, and every sensor still has to say something
    true. Nothing is frozen, nothing is weak, and the Data sensors
    say zero rather than implying a depth they do not have.
    """
    register_device(hass, "fi2", "Quiet Device")
    coord = await setup_coordinator(hass)

    depth = coord.recording_depth
    assert depth["freeze"]["complete_days"] == 0
    assert depth["battery"]["complete_days"] == 0
    assert depth["signal"]["complete_days"] == 0
    assert coord.frozen_devices_list == []
    assert coord.signal_weak_list == []
    assert coord.battery_low_list == []


async def test_the_first_readings_do_not_produce_a_verdict(
    hass: HomeAssistant,
):
    """Arming takes seven days (ruling #172 and the freeze arming
    window), so a device that reports on day one is observed and not
    judged. A verdict here would be the worst kind: a stranger's
    first impression of the integration is a false alarm.
    """
    device, (entity_id,) = register_device(hass, "fi3", "Talkative Device")
    coord = await setup_coordinator(hass)

    for minute in range(10):
        hass.states.async_set(entity_id, str(minute))
        await hass.async_block_till_done()

    record = coord.data[DATA_DEVICES][device.id]
    assert record["event_count"] >= 10
    assert coord.frozen_devices_list == []
    assert coord.learning_buckets["established"] == 0


async def test_the_first_midnight_records_a_day(hass: HomeAssistant):
    """The fold is where an empty install becomes a recording one.
    One day of history, in every series that had something to say,
    and the Data sensors move off zero the moment it lands.
    """
    device, (entity_id,) = register_device(hass, "fi4", "Folding Device")
    coord = await setup_coordinator(hass)
    record = coord.data[DATA_DEVICES][device.id]
    coord._feed_signal(record, 140.0, 0.0)
    coord._feed_signal(record, 132.0, 600.0)

    # The whole midnight job, not one of its parts: a fresh
    # install has to come out of the fold with exactly one day.
    await coord._on_midnight(None)

    assert len(record[DEV_SIGNAL_DAILY_P5]) == 1
    assert coord.recording_depth["signal"]["complete_days"] == 1


async def test_a_fresh_install_offers_what_it_can_enable(
    hass: HomeAssistant,
):
    """The first useful thing a person does is press Enable Battery,
    so the count behind that button has to be right on a system that
    has never run before."""
    await setup_coordinator(hass)

    status = hass.states.get("sensor.device_sentinel_status")

    assert status is not None
    assert status.state in ("watching", "learning", "problem")
    assert status.attributes[ATTR_AWAITING_BATTERY] == 0


async def test_an_empty_house_is_not_an_error(hass: HomeAssistant):
    """No devices at all: a new Home Assistant, or one where every
    device is a service entry. Everything still sets up and says
    nothing rather than dividing by a fleet of zero.
    """
    coord = await setup_coordinator(hass)

    assert coord.watched_count == 0
    assert coord.recording_depth["freeze"]["device_days"] == 0
    await hass.async_add_executor_job(coord._write_reports, "setup")
    text = open(
        os.path.join(hass.config.path(REPORT_DIR), "classification.md")
    ).read()
    assert "Watching 0 of" in text
