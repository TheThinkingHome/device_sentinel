"""Times and dates follow the owner account's Localization choices (rule GEN-11).

# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
# File: test_clock.py, Version: 0.30.4 (2026-11-23)
# Copyright (C) 2026 James Lander
# SPDX-License-Identifier: GPL-3.0-or-later

Home Assistant keeps each account's language, time format and date
format on the server. What Device Sentinel writes for everyone, the
brief, the pushes, the Problem List and the reports, follows the owner
account's choices, and follows them again the moment the owner changes
them. "As my language has it" and "as this browser has it" fall back to
the language, and so does a house with no choice saved.
"""

from datetime import datetime

import pytest
from homeassistant.components.frontend.storage import async_user_store
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel import clock, network_extras

from .helpers import setup_coordinator

MOMENT = datetime(2026, 11, 23, 17, 34, 7)


class _Store:
    def __init__(self, **choices):
        self.data = {"language": choices}


@pytest.fixture(autouse=True)
def _english_after():
    yield
    clock.bind(None, "en")


def test_no_choice_reads_as_english_has_it():
    clock.bind(None, "en")
    assert clock.time_text(MOMENT) == "5:34 PM"
    assert clock.day_time_text(MOMENT) == "Nov 23, 5:34 PM"
    assert clock.report_text(MOMENT) == "November 23, 2026 at 5:34 PM"


def test_24_hours_and_day_first_as_chosen():
    clock.bind(_Store(language="en", time_format="24", date_format="DMY"), "en")
    assert clock.time_text(MOMENT) == "17:34"
    assert clock.time_text(MOMENT, seconds=True) == "17:34:07"
    assert clock.time_text(datetime(2026, 11, 23, 5, 4)) == "05:04"
    assert clock.day_time_text(MOMENT) == "23 Nov, 17:34"
    assert clock.report_text(MOMENT) == "23 November 2026 at 17:34"


def test_year_first_and_12_hours_as_chosen():
    clock.bind(_Store(language="de", time_format="12", date_format="YMD"), "de")
    assert clock.time_text(MOMENT) == "5:34 PM"
    assert clock.day_text(MOMENT, year=True) == "2026 Nov 23"


def test_as_the_language_has_it():
    clock.bind(_Store(language="de", time_format="language", date_format="language"), "en")
    assert clock.time_text(MOMENT) == "17:34"
    assert clock.day_text(MOMENT) == "23 Nov"
    clock.bind(_Store(language="en-GB", time_format="language", date_format="language"), "en")
    assert clock.time_text(MOMENT) == "17:34"
    assert clock.day_text(MOMENT) == "23 Nov"
    clock.bind(_Store(language="en-CA", time_format="language", date_format="language"), "en")
    assert clock.day_text(MOMENT, year=True) == "2026 Nov 23"


def test_as_the_browser_has_it_falls_back_to_the_language():
    clock.bind(_Store(language="fr", time_format="system", date_format="system"), "en")
    assert clock.time_text(MOMENT) == "17:34"
    assert clock.day_text(MOMENT) == "23 Nov"


def test_a_time_of_day_from_minutes_follows_too():
    clock.bind(_Store(time_format="24"), "en")
    assert network_extras._clock(220) == "03:40"
    clock.bind(None, "en")
    assert network_extras._clock(220) == "3:40 AM"


async def test_the_owner_choices_are_read_and_followed_as_they_change(hass: HomeAssistant, hass_owner_user):
    store = await async_user_store(hass, hass_owner_user.id)
    await store.async_set_item("language", {"language": "en", "time_format": "24", "date_format": "DMY"})
    await setup_coordinator(hass)
    assert clock.time_text(MOMENT) == "17:34"
    assert clock.day_text(MOMENT) == "23 Nov"
    await store.async_set_item("language", {"language": "en", "time_format": "12", "date_format": "MDY"})
    assert clock.time_text(MOMENT) == "5:34 PM"
    assert clock.day_text(MOMENT) == "Nov 23"


async def test_no_owner_choice_saved_reads_as_the_language(hass: HomeAssistant, hass_owner_user):
    await setup_coordinator(hass)
    assert clock.time_text(MOMENT) == "5:34 PM"
