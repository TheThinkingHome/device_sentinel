# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_storage_failures.py, Version: 0.17.4 (2026-08-24)

"""A storage file Home Assistant cannot read (ruling #327).

The person who most needs a plain explanation is the person whose
file just broke. Setup used to let the exception escape, so they got
a stack trace and a config entry whose error named no cause.

The two files are answered differently on purpose. The main file is
the record, so setup stops and says so, permanently rather than on a
retry loop, because a corrupt file does not become readable on the
next attempt. The clocks file is the small companion, so an
unreadable one costs a few minutes of live counters and the start
continues.

The banked Restore flow will read the last-good copy beside the file
when it ships; until then an explanation is what a person gets.
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


async def _entry_with_failing_load(hass: HomeAssistant, error: Exception):
    """Set up the integration with our own store raising on load.

    Only this integration's key fails: patching every Store would
    break Home Assistant's own registries and prove nothing about
    this guard.
    """
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
    """A file that will not parse stops setup with a sentence.

    Before this, the exception escaped `async_setup_entry` and Home
    Assistant showed a traceback with no cause a person could act on.
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

    Losing it costs one interval of live counters, so the start
    continues on the clocks held in the main file and says so, rather
    than refusing to run (ruling #327).
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
    at all, and that path is unchanged."""
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.data["devices"] == {}
