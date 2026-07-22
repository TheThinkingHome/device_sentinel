# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v071_settings.py, Version: 0.7.1 (2026-07-22)

"""0.7.1 tests: the reorganized settings and the brief wording.

One screen for notifications and the daily brief, in three sections
that flatten to the same stored keys as before; a new Advanced
screen whose sliders feed live coordinator properties; and the two
brief wording fixes ruled from the first live file.
"""

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_BRIEF_TARGETS,
    CONF_COALESCE_MINUTES,
    CONF_EPISODE_SHARE,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_NORMAL_PRIORITY_TARGETS,
    CONF_PERSISTENT_ENABLED,
    CONF_QUIET_ENABLED,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_REMINDER_MODE,
    CONF_REMINDER_TIME,
    CONF_SETTLE_SHARE,
    DEFAULT_EPISODE_SHARE_PCT,
    DEFAULT_SETTLE_SHARE_PCT,
    DEV_EVENT_COUNT,
    DEV_FIRST_OBSERVED,
    DEV_LAST_ACTIVITY,
)

DOMAIN = "device_sentinel"


async def _setup(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_sections_flatten_to_the_same_stored_keys(
    hass: HomeAssistant,
):
    """The screen gained sections; the storage did not. Options keep
    their original flat keys so nothing downstream migrates."""
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "notifications"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "instant": {
                CONF_HIGH_PRIORITY_TARGETS: [],
                CONF_NORMAL_PRIORITY_TARGETS: [],
                CONF_PERSISTENT_ENABLED: True,
            },
            "quiet": {
                CONF_QUIET_ENABLED: True,
                CONF_QUIET_START: "22:00:00",
                CONF_QUIET_END: "07:00:00",
            },
            "brief": {
                CONF_REMINDER_MODE: "daily",
                CONF_REMINDER_TIME: "07:00:00",
                CONF_BRIEF_TARGETS: ["notify.smtp_home"],
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_QUIET_ENABLED] is True
    assert entry.options[CONF_REMINDER_TIME] == "07:00:00"
    assert entry.options[CONF_BRIEF_TARGETS] == ["notify.smtp_home"]
    assert "instant" not in entry.options  # flattened, not nested


async def test_advanced_stores_and_coordinator_reads_live(
    hass: HomeAssistant,
):
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "advanced"}
    )
    assert result["step_id"] == "advanced"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SETTLE_SHARE: 50,
            CONF_EPISODE_SHARE: 30,
            CONF_COALESCE_MINUTES: 5,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    coord = entry.runtime_data
    assert coord.episode_share == 0.30
    assert coord.coalesce_seconds == 300


async def test_advanced_defaults_match_the_shipped_constants(
    hass: HomeAssistant,
):
    """An untouched install behaves exactly as 0.7.0 did."""
    entry = await _setup(hass)
    coord = entry.runtime_data
    assert DEFAULT_SETTLE_SHARE_PCT == 30
    assert coord.episode_share == DEFAULT_EPISODE_SHARE_PCT / 100.0
    assert coord.coalesce_seconds == 900


async def test_episode_share_is_clamped(hass: HomeAssistant):
    entry = await _setup(hass, {CONF_EPISODE_SHARE: 500})
    assert entry.runtime_data.episode_share == 0.90


async def test_brief_says_discovered_for_never_reported(
    hass: HomeAssistant,
):
    """#118: the SINCE cell for a never-reported device is when it
    was discovered in the registry, and says so."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", "nr1")},
        name="Silent From Birth",
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "nr1_0",
        device_id=device.id, config_entry=source,
    )
    entry = await _setup(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_EVENT_COUNT] = 0
    record[DEV_LAST_ACTIVITY] = None
    # Discovered three days ago: past the 48-hour patience for a
    # device that has never spoken.
    from datetime import timedelta

    record[DEV_FIRST_OBSERVED] = (
        dt_util.utcnow() - timedelta(days=3)
    ).isoformat()
    coord._grace_until = 0.0
    coord._judge_all_devices()
    coord._sync_problem_list()
    await hass.async_add_executor_job(coord._write_reports, "test")
    stamp = dt_util.now().strftime("%Y-%m-%d")
    with open(
        hass.config.path("device_sentinel", f"daily_brief_{stamp}.md"),
        encoding="utf-8",
    ) as handle:
        text = handle.read()
    assert "discovered" in text
    assert "Silent From Birth" in text


async def test_counts_line_reads_naturally(hass: HomeAssistant):
    """#117 rider: '2 devices need attention, one of them
    acknowledged.' rather than clipped fragments."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from custom_components.device_sentinel.const import (
        DEV_DAILY_MAX,
        DEV_FROZEN_CATEGORY,
        DEV_FROZEN_SINCE,
        FREEZE_ARMING_DAYS,
        FREEZE_CATEGORY_FROZEN,
    )

    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    names = ["Counts One", "Counts Two"]
    devices = []
    for i, name in enumerate(names):
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id,
            identifiers={("test", f"c{i}")},
            name=name,
        )
        er.async_get(hass).async_get_or_create(
            "sensor", "test", f"c{i}_0",
            device_id=device.id, config_entry=source,
        )
        devices.append(device)
    entry = await _setup(hass)
    coord = entry.runtime_data
    since = dt_util.utcnow().timestamp() - 3600
    for device in devices:
        record = coord.data["devices"][device.id]
        record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
        record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
        record[DEV_FROZEN_SINCE] = since
    coord._sync_problem_list()
    uid = coord.todo_items[0]["uid"]
    await coord.async_todo_update(uid=uid, status="completed")
    await hass.async_add_executor_job(coord._write_reports, "test")
    stamp = dt_util.now().strftime("%Y-%m-%d")
    with open(
        hass.config.path("device_sentinel", f"daily_brief_{stamp}.md"),
        encoding="utf-8",
    ) as handle:
        text = handle.read()
    assert "2 devices need attention, one of them acknowledged." in text
