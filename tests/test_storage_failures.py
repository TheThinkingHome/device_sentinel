# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_storage_failures.py, Version: 0.27.10 (2026-10-27)

"""A storage file Home Assistant cannot read (rules STOR-08, STOR-10).

The person who most needs a plain explanation is the person whose file
just broke, so setup never lets the exception escape as a stack trace
and an error that names no cause.

The two files are answered differently on purpose. The main file is
the record, so with no last-good copy to restore, setup stops and says
so, permanently rather than on a retry loop, because a corrupt file
does not become readable on the next attempt. The clocks file is the
small companion, so an unreadable one restarts the device clocks,
keeps everything learned, and the start continues.
"""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    DOMAIN,
    STORAGE_CLOCKS_KEY,
    STORAGE_KEY,
)

from tests.helpers import setup_entry


def _clear_storage(hass: HomeAssistant) -> None:
    """Start from a directory with no last-good copy in it.

    The harness config directory is a fixed folder inside the
    installed package, shared by every test in the session and left
    on disk between runs, so a copy another test wrote would let the
    restore succeed and the refusal these tests describe would never
    happen.
    """
    import os

    directory = hass.config.path(".storage")
    if not os.path.exists(directory):
        return
    for name in os.listdir(directory):
        if name.startswith("device_sentinel"):
            os.remove(os.path.join(directory, name))


async def _entry_with_failing_load(hass: HomeAssistant, error: Exception):
    """Set up the integration with Device Sentinel's own store raising on load.

    Only this integration's key fails: patching every Store would
    break Home Assistant's own registries and prove nothing about
    this guard.
    """
    _clear_storage(hass)
    real_load = Store.async_load

    async def _selective(self, *args, **kwargs):
        if self.key == STORAGE_KEY:
            raise error
        return await real_load(self, *args, **kwargs)

    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={}, options={}
    )
    entry.add_to_hass(hass)
    with patch.object(Store, "async_load", _selective):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_an_unreadable_storage_file_states_the_fault(
    hass: HomeAssistant, caplog
) -> None:
    """A file that will not parse, with no copy to restore, stops setup
    with a sentence, not a traceback with no cause a person could act
    on (rule STOR-08).
    """
    entry = await _entry_with_failing_load(
        hass, HomeAssistantError("expecting value: line 1 column 1")
    )
    assert entry.state is ConfigEntryState.SETUP_ERROR
    # The log names the file and says nothing was changed.
    assert STORAGE_KEY in caplog.text
    assert "will not start" in caplog.text
    assert "Nothing has been changed" in caplog.text


async def test_an_unreadable_storage_file_does_not_retry(
    hass: HomeAssistant
) -> None:
    """ConfigEntryError rather than ConfigEntryNotReady.

    A corrupt file does not become readable on the next attempt, so a
    retry loop would only repeat the same failure every few minutes
    and bury the one line that explains it.
    """
    entry = await _entry_with_failing_load(
        hass, ValueError("Expecting ',' delimiter")
    )
    assert entry.state is ConfigEntryState.SETUP_ERROR
    # SETUP_RETRY is what ConfigEntryNotReady would have produced.
    assert entry.state is not ConfigEntryState.SETUP_RETRY


async def test_an_unreadable_clocks_file_is_survivable(
    hass: HomeAssistant, hass_storage, caplog
) -> None:
    """The small companion is not the record.

    Losing it restarts each device's clock and loses nothing learned, so
    the start continues and says so, rather than refusing to run
    (rule STOR-10).
    """
    real_load = None

    async def _selective(self, *args, **kwargs):
        if self.key == STORAGE_CLOCKS_KEY:
            raise HomeAssistantError("clocks file is not JSON")
        return await real_load(self, *args, **kwargs)

    real_load = Store.async_load
    with patch.object(Store, "async_load", _selective):
        entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert STORAGE_CLOCKS_KEY in caplog.text
    assert "Nothing learned is lost" in caplog.text


async def test_a_missing_storage_file_is_still_a_fresh_install(
    hass: HomeAssistant
) -> None:
    """The guard catches faults, not absence. A first run has no file
    at all and starts as a fresh install."""
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.data["devices"] == {}
