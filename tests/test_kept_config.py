# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.

"""Removing the integration can keep settings, but not learned data (STOR-24)."""

from pathlib import Path

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.storage import Store

from custom_components.device_sentinel.const import (
    CONF_KEEP_CONFIG_ON_REMOVAL,
    CONF_REPEAT_FLOOR,
    CONF_RETENTION_DAYS,
    CONF_TRIM_DEVICES,
    CONF_TRIM_INTEGRATIONS,
    DEFAULT_RETENTION_DAYS,
    DOMAIN,
    STORAGE_KEY,
)
from custom_components.device_sentinel.kept_config import KEPT_CONFIG_KEY
from tests.helpers import setup_entry


async def _add(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def test_opt_in_keeps_settings_on_disk_but_not_history(hass: HomeAssistant, real_disk):
    entry = await setup_entry(hass, {CONF_REPEAT_FLOOR: 3})
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    form = await hass.config_entries.options.async_configure(
        menu["flow_id"], {"next_step_id": "advanced"}
    )
    assert form["type"] is FlowResultType.FORM
    keep = next(key for key in form["data_schema"].schema if key == CONF_KEEP_CONFIG_ON_REMOVAL)
    assert keep.default() is False
    await hass.config_entries.options.async_configure(
        menu["flow_id"], form["data_schema"]({CONF_KEEP_CONFIG_ON_REMOVAL: True})
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_KEEP_CONFIG_ON_REMOVAL] is True

    folder = Path(real_disk)
    backup = folder / KEPT_CONFIG_KEY
    assert not backup.exists()
    # Unload for a reload is not removal; storage is written, not discarded.
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert (folder / STORAGE_KEY).exists()
    assert not backup.exists()

    assert await hass.config_entries.async_remove(entry.entry_id) == {"require_restart": False}
    assert backup.exists()
    assert not (folder / STORAGE_KEY).exists()

    new_entry = await _add(hass)
    assert new_entry.entry_id != entry.entry_id
    assert new_entry.options[CONF_REPEAT_FLOOR] == 3
    assert new_entry.options[CONF_KEEP_CONFIG_ON_REMOVAL] is True

    hass.config_entries.async_update_entry(
        new_entry, options={**new_entry.options, CONF_KEEP_CONFIG_ON_REMOVAL: False}
    )
    await hass.async_block_till_done()
    await hass.config_entries.async_remove(new_entry.entry_id)
    assert not backup.exists()
    assert CONF_REPEAT_FLOOR not in (await _add(hass)).options


async def test_saved_options_migrate_without_replaying_trim(hass: HomeAssistant, real_disk):
    await Store(hass, 1, KEPT_CONFIG_KEY).async_save({
        "minor_version": 7,
        "options": {
            CONF_RETENTION_DAYS: 30,
            CONF_TRIM_DEVICES: ["device"],
            CONF_TRIM_INTEGRATIONS: ["mqtt"],
        },
    })

    entry = await _add(hass)
    assert entry.options[CONF_RETENTION_DAYS] == DEFAULT_RETENTION_DAYS
    assert CONF_TRIM_DEVICES not in entry.options
    assert CONF_TRIM_INTEGRATIONS not in entry.options


async def test_malformed_kept_options_do_not_block_setup(hass: HomeAssistant, real_disk):
    await Store(hass, 1, KEPT_CONFIG_KEY).async_save({"minor_version": 8, "options": []})

    assert not (await _add(hass)).options