# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_www_retired.py, Version: 0.23.5 (2026-09-25)

"""The www folder retired (#470, built as 0.23.5).

Home Assistant serves config/www at /local to anyone who asks, signed
in or not, and the files Device Sentinel wrote there named devices,
battery levels and outage times. The owner ruled on 23 and 25
September 2026: the battery and signal reports and the brief's dated
copies go, the current brief moves to config/device_sentinel/, and the
whole www/device_sentinel folder is deleted, whatever else is in it.
Links in Reports stays, and the brief's links use only the address it
names.

The tests that are not guards fail on 0.23.4, which serves the folder
and keeps writing into it.
"""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.device_sentinel import _retire_www_folder
from custom_components.device_sentinel.const import (
    CONF_REPORT_LINKS,
    REPORT_BRIEF_HTML,
    REPORT_DIR,
    REPORT_LINKS_INTERNAL,
    REPORT_WWW_DIR,
)

from .helpers import register_device, setup_coordinator, setup_entry

OLD_BRIEF = "<html>the brief from 0.23.4</html>"


def _plant(hass: HomeAssistant) -> str:
    """Lay out www/device_sentinel as 0.23.4 left it, plus a file of
    the person's own and a subfolder."""
    folder = hass.config.path(REPORT_WWW_DIR)
    os.makedirs(os.path.join(folder, "mine"), exist_ok=True)
    files = {
        REPORT_BRIEF_HTML: OLD_BRIEF,
        "daily_brief_2026-09-24.html": "dated",
        "battery_report.html": "battery",
        "battery_report_2026-09-24.html": "battery dated",
        "signal_report.html": "signal",
        "signal_report_2026-09-24.html": "signal dated",
        "my_notes.txt": "a person's own file",
        os.path.join("mine", "card.png"): "an image",
    }
    for name, text in files.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
            handle.write(text)
    return folder


def _moved(hass: HomeAssistant) -> str:
    return os.path.join(hass.config.path(REPORT_DIR), REPORT_BRIEF_HTML)


async def test_the_brief_moves_and_the_whole_folder_goes(hass: HomeAssistant):
    folder = _plant(hass)
    done = await hass.async_add_executor_job(_retire_www_folder, hass)

    assert not os.path.exists(folder)
    with open(_moved(hass), encoding="utf-8") as handle:
        assert handle.read() == OLD_BRIEF
    assert "8 file(s)" in done
    assert "after moving the current brief" in done


async def test_a_brief_already_in_its_new_home_is_kept(hass: HomeAssistant):
    """Guard: the newer file wins; the old one is not copied over it."""
    folder = _plant(hass)
    os.makedirs(hass.config.path(REPORT_DIR), exist_ok=True)
    with open(_moved(hass), "w", encoding="utf-8") as handle:
        handle.write("already here")

    done = await hass.async_add_executor_job(_retire_www_folder, hass)

    assert not os.path.exists(folder)
    with open(_moved(hass), encoding="utf-8") as handle:
        assert handle.read() == "already here"
    assert "after moving" not in done


async def test_a_house_with_no_folder_is_left_alone(hass: HomeAssistant):
    """Guard: every start after the first finds nothing to do."""
    assert await hass.async_add_executor_job(_retire_www_folder, hass) is None
    assert not os.path.exists(_moved(hass))


async def test_the_first_start_retires_the_folder(hass: HomeAssistant):
    """End to end through setup, and nothing is written under www
    afterwards, the brief included."""
    folder = _plant(hass)
    coord = await setup_coordinator(hass)
    await hass.async_add_executor_job(coord._write_reports, "manual")

    assert not os.path.exists(folder)
    assert os.path.isfile(_moved(hass))
    assert not os.path.exists(hass.config.path("www", "device_sentinel"))


async def test_a_folder_that_cannot_be_deleted_does_not_stop_the_start(
    hass: HomeAssistant, caplog
):
    folder = _plant(hass)

    def _refuse(*_args, **_kwargs):
        raise OSError("read-only")

    caplog.set_level(logging.WARNING, logger="custom_components.device_sentinel")
    with patch("custom_components.device_sentinel.shutil.rmtree", _refuse):
        entry = await setup_entry(hass)

    assert entry.runtime_data is not None
    assert os.path.isdir(folder)
    assert "could not delete www/device_sentinel" in caplog.text


async def test_internal_never_reaches_for_the_external_address(
    hass: HomeAssistant,
):
    """The owner, 25 September 2026: the setting names the address,
    and nothing goes above it. With Internal chosen and no internal
    address typed in, Home Assistant still knows the machine's own
    address on the house network and that is what links; the external
    address set beside it is never used."""
    device, _ = register_device(hass, "lnk1", name="Motion Laundry")
    coord = await setup_coordinator(hass)
    hass.config.internal_url = None
    hass.config.external_url = "https://house.example.com"
    hass.config_entries.async_update_entry(
        coord.entry,
        options={**coord.entry.options, CONF_REPORT_LINKS: REPORT_LINKS_INTERNAL},
    )
    await hass.async_block_till_done()

    link = coord._report_link(f"/device-sentinel/device/{device.id}")
    assert link is not None and "house.example.com" not in link
    assert "house.example.com" not in coord._device_cell(device.id, "Motion Laundry")
