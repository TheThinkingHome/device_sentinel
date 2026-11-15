# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_poller_note.py, Version: 0.29.0 (2026-11-14)

"""A polling integration's note sits on its own row and page.

What Device Sentinel can and cannot see through an integration that
updates all its devices at once recommends nothing, so it is not on the
Recommendations tab: it is a note under the integration's name on the
Integrations tab and on the integration's own page (rule UP-18).
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_STORM_DAYS,
    STORM_DAY_COUNT,
    STORM_DAY_DATE,
    STORM_DAY_DOMAIN,
    STORM_DAY_INTERVAL,
)

from tests.helpers import register_device, setup_coordinator


def _poller_days(domain: str) -> list[dict]:
    return [
        {
            STORM_DAY_DATE: (dt_util.now().date() - timedelta(days=days_ago)).isoformat(),
            STORM_DAY_DOMAIN: domain,
            STORM_DAY_COUNT: 300,
            STORM_DAY_INTERVAL: 300.0,
        }
        for days_ago in (1, 2)
    ]


async def test_the_note_is_on_the_row_and_the_page_not_the_tab(hass: HomeAssistant):
    register_device(hass, "thermostat", name="Hall Thermostat")
    coord = await setup_coordinator(hass)
    coord.data[DATA_STORM_DAYS] = _poller_days("test")

    row = next(r for r in coord.dashboard_integrations() if r["domain"] == "test")
    assert row["note"].endswith("but not when one of its devices fails.")
    assert "every 5 minutes" in row["note"]
    # A note, so no exclusion is recommended beside it (rule UP-18).
    assert row["recommended"] is None

    page = coord.dashboard_integration("test")
    assert page["note"] == row["note"]

    assert not any(
        "updates all its devices at once" in line
        for line in coord._recommendation_items()
    )


async def test_an_ordinary_integration_has_no_note(hass: HomeAssistant):
    register_device(hass, "plug", name="Desk Plug")
    coord = await setup_coordinator(hass)
    row = next(r for r in coord.dashboard_integrations() if r["domain"] == "test")
    assert row["note"] is None
    assert coord.dashboard_integration("test")["note"] is None
