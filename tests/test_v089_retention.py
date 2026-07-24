# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v089_retention.py, Version: 0.8.9 (2026-07-24)

"""0.8.9 tests: how much is kept, and what is judged.

Reporting gaps join the long series, and how long every series is
kept becomes the user's choice. The rule that makes both safe is
that no verdict depends on either: the freeze rhythm and the signal
floor are computed from the most recent fourteen days whatever is
stored, so a Pi keeping thirty days detects exactly what a fast
machine keeping a year detects.
"""

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
    CONF_COALESCE_MINUTES,
    CONF_EPISODE_SHARE,
    CONF_RETENTION_DAYS,
    CONF_SETTLE_SHARE,
    DAILY_MAX_KEEP,
    DEFAULT_RETENTION_DAYS,
    DEV_DAILY_MAX,
    DEV_TODAY_MAX,
    RETENTION_DAYS_MAX,
    RETENTION_DAYS_MIN,
    RETENTION_DAYS_STEP,
)

DOMAIN = "device_sentinel"


def _register(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    return device


async def _entry(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Device Sentinel", data={},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# --------------------------------------- judgment ignores retention

async def test_the_rhythm_reads_only_the_judgment_window(
    hass: HomeAssistant,
):
    """The hazard this release had to avoid. The trimmed maximum of
    ninety days is higher than of fourteen, because more days mean
    more chances at a long gap, so reading the whole series would
    quietly widen every freeze window on the fleet."""
    device = _register(hass, "j1", "Judged Sensor")
    entry = await _entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]

    fortnight = [600.0 + n for n in range(DAILY_MAX_KEEP)]
    record[DEV_DAILY_MAX] = list(fortnight)
    with_a_fortnight = coord._freeze_window(record)

    # The same fortnight, preceded by far longer gaps months ago.
    record[DEV_DAILY_MAX] = [50000.0] * 60 + list(fortnight)
    with_a_season = coord._freeze_window(record)

    assert with_a_season == with_a_fortnight


async def test_the_rhythm_is_the_same_at_every_setting(
    hass: HomeAssistant,
):
    """A Pi keeping thirty days detects what a fast machine keeping a
    year detects."""
    device = _register(hass, "j2", "Same Sensor")
    series = [50000.0] * 60 + [600.0 + n for n in range(DAILY_MAX_KEEP)]
    seen = set()
    for days in (RETENTION_DAYS_MIN, DEFAULT_RETENTION_DAYS,
                 RETENTION_DAYS_MAX):
        entry = await _entry(hass, {CONF_RETENTION_DAYS: days})
        coord = entry.runtime_data
        record = coord.data["devices"][device.id]
        record[DEV_DAILY_MAX] = list(series)
        seen.add(coord._freeze_window(record))
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    assert len(seen) == 1


async def test_the_report_cell_still_shows_a_fortnight(
    hass: HomeAssistant,
):
    device = _register(hass, "j3", "Cell Sensor")
    entry = await _entry(hass)
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [600.0 + n for n in range(120)]
    assert len(coord._format_maxima_cell(record[DEV_DAILY_MAX]).split(", ")) == (
        DAILY_MAX_KEEP
    )


# ------------------------------------------------- how much is kept

async def test_gaps_are_kept_for_the_chosen_length(
    hass: HomeAssistant,
):
    """Reporting gaps join the long series, so three months of them
    can eventually be used to question the fourteen-day window."""
    device = _register(hass, "k1", "Kept Sensor")
    entry = await _entry(hass, {CONF_RETENTION_DAYS: 30})
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [float(n) for n in range(200)]
    record[DEV_TODAY_MAX] = 999.0
    await coord._on_midnight(None)
    assert len(record[DEV_DAILY_MAX]) == 30
    assert record[DEV_DAILY_MAX][-1] == 999.0


async def test_the_setting_is_clamped_to_its_band(
    hass: HomeAssistant,
):
    """The floor of thirty is what makes the slider safe: no choice
    can starve a fourteen-day judgment window."""
    for asked, expected in (
        (5, RETENTION_DAYS_MIN),
        (900, RETENTION_DAYS_MAX),
        (60, 60),
    ):
        entry = await _entry(hass, {CONF_RETENTION_DAYS: asked})
        assert entry.runtime_data.retention_days == expected
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_reducing_the_setting_waits_for_midnight(
    hass: HomeAssistant,
):
    """A settings dialog should not destroy three months of history
    the instant a slider moves; the trim happens where every other
    trim happens."""
    device = _register(hass, "k2", "Patient Sensor")
    entry = await _entry(hass, {CONF_RETENTION_DAYS: 90})
    coord = entry.runtime_data
    record = coord.data["devices"][device.id]
    record[DEV_DAILY_MAX] = [float(n) for n in range(90)]

    hass.config_entries.async_update_entry(
        entry, options={CONF_RETENTION_DAYS: 30}
    )
    await coord.async_options_updated()
    assert len(record[DEV_DAILY_MAX]) == 90     # untouched for now

    record[DEV_TODAY_MAX] = 1.0
    await coord._on_midnight(None)
    assert len(record[DEV_DAILY_MAX]) == 30     # trimmed at the roll


async def test_the_slider_reaches_the_advanced_screen(
    hass: HomeAssistant,
):
    entry = await _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "advanced"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SETTLE_SHARE: 30,
            CONF_EPISODE_SHARE: 50,
            CONF_COALESCE_MINUTES: 15,
            CONF_RETENTION_DAYS: 180,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_RETENTION_DAYS] == 180
    assert entry.runtime_data.retention_days == 180
    assert RETENTION_DAYS_STEP == 30


async def test_the_report_states_the_retention_in_force(
    hass: HomeAssistant,
):
    """The tunables line said "keep 14 days" after retention became a
    setting, telling a reader it kept a fortnight while keeping three
    months (0.8.10)."""
    _register(hass, "t1", "Tunable Sensor")
    entry = await _entry(hass, {CONF_RETENTION_DAYS: 180})
    coord = entry.runtime_data
    await hass.async_add_executor_job(coord._write_reports, "test")
    with open(
        hass.config.path("device_sentinel/diagnostics/device_telemetry.md"),
        encoding="utf-8",
    ) as handle:
        text = handle.read()
    assert f"judge on {DAILY_MAX_KEEP} days, keep 180 days." in text
