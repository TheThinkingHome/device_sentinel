# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_www_serving.py, Version: 0.10.21 (2026-08-03)

"""Serving the www folder on the boot that creates it (ruling #186).

Found by the deep analysis of 2026-08-03, the day the integration
acquired outside users, and checked against Home Assistant's own
source rather than assumed: the frontend registers /local only where
config/www already exists as a directory when it sets up, and it
checks that once. Device Sentinel creates www/device_sentinel later,
so on a system that never had a www folder the first boot after
installing leaves the daily brief and the dwell chart on disk at
addresses that return nothing.

It never showed on the author's system, which has had a www folder
for years, which is exactly why it needed finding by machine rather
than by use.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.device_sentinel.const import (
    REPORT_WWW_DIR,
    REPORT_WWW_PARENT,
    REPORT_WWW_URL,
)

from .helpers import setup_coordinator


async def test_the_folder_is_served_when_no_www_existed(
    hass: HomeAssistant, tmp_path,
):
    """The fault as found: no www folder, so no /local this boot.

    The integration registers its own folder rather than leaving the
    links dead until somebody restarts a second time for reasons
    nothing explained.
    """
    # A config directory of this test's own. The shared one
    # already holds a www folder from every other test that
    # writes a report, which is the one condition this file
    # exists to vary.
    hass.config.config_dir = str(tmp_path)
    await async_setup_component(hass, "http", {})
    parent = hass.config.path(REPORT_WWW_PARENT)
    assert not os.path.isdir(parent)

    calls: list = []

    async def _capture(configs):
        calls.extend(configs)

    with patch.object(
        hass.http, "async_register_static_paths", _capture
    ):
        await setup_coordinator(hass)

    assert len(calls) == 1
    assert calls[0].url_path == REPORT_WWW_URL
    assert calls[0].path == hass.config.path(REPORT_WWW_DIR)
    # The folder is made before it is registered, since a static
    # resource over a missing directory is not a resource.
    assert os.path.isdir(hass.config.path(REPORT_WWW_DIR))


async def test_nothing_is_registered_when_www_already_existed(
    hass: HomeAssistant, tmp_path,
):
    """Where the parent was there, the frontend has /local covered.

    A second overlapping route would be a route nobody needs, so the
    test is deliberately for the parent rather than for our own
    folder.
    """
    # A config directory of this test's own. The shared one
    # already holds a www folder from every other test that
    # writes a report, which is the one condition this file
    # exists to vary.
    hass.config.config_dir = str(tmp_path)
    await async_setup_component(hass, "http", {})
    os.makedirs(hass.config.path(REPORT_WWW_PARENT), exist_ok=True)

    calls: list = []

    async def _capture(configs):
        calls.extend(configs)

    with patch.object(
        hass.http, "async_register_static_paths", _capture
    ):
        await setup_coordinator(hass)

    assert calls == []


async def test_a_failed_registration_does_not_stop_setup(
    hass: HomeAssistant, tmp_path,
):
    """A link that cannot be served is a worse brief, not a broken
    integration, and the files are on disk either way."""

    # A config directory of this test's own. The shared one
    # already holds a www folder from every other test that
    # writes a report, which is the one condition this file
    # exists to vary.
    hass.config.config_dir = str(tmp_path)
    await async_setup_component(hass, "http", {})

    async def _boom(configs):
        raise RuntimeError("no router today")

    with patch.object(hass.http, "async_register_static_paths", _boom):
        coord = await setup_coordinator(hass)

    assert coord is not None
    await hass.async_add_executor_job(coord._write_reports, "manual")
    assert os.path.isfile(
        os.path.join(
            hass.config.path(REPORT_WWW_DIR), "daily_brief.html"
        )
    )
