# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_options_migration.py, Version: 0.16.18 (2026-08-22)

"""The options migration, entry shape by entry shape (ruling #316).

What a person loses if this is wrong is their whole muting list, and
they find out at the next brief, when every device they had silenced
arrives at once with nothing to explain it. So the shapes are tested
separately rather than as one happy path: an entry that never had a
picker touched, an entry carrying all twelve lists, an entry that has
already been migrated, an entry holding only some of the twelve, and
the jump the public will make from the release they are actually on.

The real fleet's options are read from the diagnostics file when it
is present rather than hand-written here, because a hand-written
entry holds what the author expects and the file holds what the
integration actually wrote.
"""

from __future__ import annotations

import json
import pathlib

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DATA_DEVICES,
    DATA_LAST_VERSION,
    DATA_SYSTEM_EVENTS,
    DEAD_OPTION_KEYS,
    DOMAIN,
    IGNORE_KEY_RENAMES,
    MUTING_KEY_RENAMES,
    OPTION_KEY_RENAMES,
    OPTIONS_MINOR_VERSION,
    STORAGE_KEY,
    SYS_DETAIL,
    SYS_DEVICES,
    SYS_DURATION,
    SYS_KIND,
    SYS_OPTIONS_CHANGED,
    SYS_RESTART,
    SYS_SCOPE,
    SYS_TRIMMED,
    SYS_WHEN,
)
from tests.helpers import setup_coordinator

# The spellings a 0.16.3 entry carries, which is the release the
# public sits on and therefore the one the single jump starts from.
PUBLIC_RELEASE_OPTIONS = {
    "excluded_integrations": ["tplink_router", "ping"],
    "excluded_labels": ["no_watch"],
    "excluded_devices": ["dev_global_1", "dev_global_2"],
    "battery_excluded_integrations": ["mobile_app"],
    "battery_excluded_labels": [],
    "battery_excluded_devices": ["dev_batt_1"],
    "signal_excluded_integrations": [],
    "signal_excluded_labels": ["mains"],
    "signal_excluded_devices": ["dev_sig_1"],
    "freeze_excluded_integrations": ["ping"],
    "freeze_excluded_labels": [],
    "freeze_excluded_devices": ["dev_frz_1"],
    "ignored_integrations": ["mobile_app"],
    "low_threshold": 20,
    # Retired at #311, never swept, so a real entry still carries it.
    "signal_margin": 5,
    "signal_red_threshold": 10,
    "signal_sensitivity": 0,
}


async def _migrated(
    hass: HomeAssistant, options: dict, minor_version: int = 1
) -> MockConfigEntry:
    """Set an entry up at a given minor version and return it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Device Sentinel",
        data={},
        options=options,
        version=1,
        minor_version=minor_version,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_the_twelve_lists_arrive_under_their_muting_names(
    hass: HomeAssistant,
):
    """Every list, its exact contents, and no old name left behind."""
    entry = await _migrated(hass, dict(PUBLIC_RELEASE_OPTIONS))

    for old, new in MUTING_KEY_RENAMES.items():
        assert entry.options[new] == PUBLIC_RELEASE_OPTIONS[old], new
        if old in IGNORE_KEY_RENAMES.values():
            # The one name the next step takes up again, so its
            # absence would be wrong rather than right.
            continue
        assert old not in entry.options, old
    assert entry.minor_version == OPTIONS_MINOR_VERSION


async def test_settings_that_are_not_muting_are_untouched(
    hass: HomeAssistant,
):
    """The migration moves twelve keys and reads none of the rest.

    The ignore list is the one to watch: step 3 takes the word step 2
    vacated, so the two must run in order and the chain is what makes
    that true for the person who arrives at both in one load.
    """
    entry = await _migrated(hass, dict(PUBLIC_RELEASE_OPTIONS))

    assert entry.options["excluded_integrations"] == ["mobile_app"]
    assert "ignored_integrations" not in entry.options
    assert entry.options["muted_integrations"] == ["tplink_router", "ping"]
    assert entry.options["low_threshold"] == 20


async def test_the_retired_signal_keys_are_swept(hass: HomeAssistant):
    """#311 turned four settings into constants and left the keys.

    They have sat in every stored entry since, reading in diagnostics
    as live settings, which is the rot ruling #49 exists to stop.
    """
    entry = await _migrated(hass, dict(PUBLIC_RELEASE_OPTIONS))

    for key in ("signal_margin", "signal_red_threshold", "signal_sensitivity"):
        assert key in DEAD_OPTION_KEYS
        assert key not in entry.options


async def test_an_untouched_install_gains_no_keys(hass: HomeAssistant):
    """A missing key produces nothing, not an empty list.

    A person who never opened a picker should not come out of the
    upgrade owning twelve settings they never made.
    """
    entry = await _migrated(hass, {"low_threshold": 15})

    for new in MUTING_KEY_RENAMES.values():
        assert new not in entry.options, new
    assert entry.options == {"low_threshold": 15}
    assert entry.minor_version == OPTIONS_MINOR_VERSION


async def test_a_half_filled_entry_moves_only_what_it_holds(
    hass: HomeAssistant,
):
    """Most real entries carry two or three of the twelve."""
    entry = await _migrated(
        hass,
        {
            "excluded_integrations": ["ping"],
            "freeze_excluded_devices": [],
            "low_threshold": 20,
        },
    )

    assert entry.options["muted_integrations"] == ["ping"]
    assert entry.options["freeze_muted_devices"] == []
    assert "muted_devices" not in entry.options
    assert "battery_muted_labels" not in entry.options


async def test_running_it_twice_changes_nothing(hass: HomeAssistant):
    """An entry already at the current version is left alone.

    Home Assistant will not call the migration again, but the guard
    inside it is what makes that true rather than assumed, and a
    reload must not double-apply anything.
    """
    entry = await _migrated(hass, dict(PUBLIC_RELEASE_OPTIONS))
    after_first = dict(entry.options)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert dict(entry.options) == after_first
    assert entry.minor_version == OPTIONS_MINOR_VERSION


async def test_an_already_muted_entry_is_not_disturbed(
    hass: HomeAssistant,
):
    """A fresh install writes muting names from the start."""
    fresh = {
        "muted_integrations": ["ping"],
        "muted_devices": ["dev_1"],
    }
    entry = await _migrated(
        hass, dict(fresh), minor_version=OPTIONS_MINOR_VERSION
    )

    assert entry.options["muted_integrations"] == ["ping"]
    assert entry.options["muted_devices"] == ["dev_1"]


async def test_the_public_jump_from_the_current_release(
    hass: HomeAssistant,
):
    """0.16.3 is what the public runs, and it arrives in one load.

    The author and the beta tester take the steps one at a time, so
    this path is the one nobody exercises by hand before it reaches
    a stranger's system.
    """
    entry = await _migrated(hass, dict(PUBLIC_RELEASE_OPTIONS), minor_version=1)

    assert entry.minor_version == OPTIONS_MINOR_VERSION
    assert entry.options["muted_devices"] == ["dev_global_1", "dev_global_2"]
    assert entry.options["signal_muted_labels"] == ["mains"]
    assert entry.options["excluded_integrations"] == ["mobile_app"]
    assert not [
        key
        for key in entry.options
        if "excluded" in key and key != "excluded_integrations"
    ]


async def test_the_reference_fleet_s_own_entry_survives(
    hass: HomeAssistant,
):
    """The real options, read from a diagnostics download.

    A hand-written entry holds what the author expects. This one
    holds what the integration actually wrote on a live system, which
    is the difference that has caught two releases already.
    """
    uploads = pathlib.Path("/mnt/user-data/uploads")
    files = sorted(uploads.glob("config_entry-device_sentinel-*.json"))
    if not files:
        return
    stored = json.loads(files[0].read_text(encoding="utf-8"))
    options = dict(stored["data"]["entry_options"])
    # The muting lists as the live system holds them, before the move.
    # Only names that are retired outright. `excluded_integrations`
    # is a source in step 2 and the target of step 3, so on a file
    # already migrated it is the live ignore list rather than an old
    # muting key, and reading it as one would assert the opposite of
    # the truth. Same rule the source guard uses.
    retired = set(OPTION_KEY_RENAMES) - set(OPTION_KEY_RENAMES.values())
    before = {
        old: list(options[old]) for old in retired if old in options
    }
    if not before:
        return

    entry = await _migrated(hass, options)

    for old, kept in before.items():
        assert entry.options[OPTION_KEY_RENAMES[old]] == kept, old
        assert old not in entry.options


async def test_a_brief_covering_the_upgrade_still_names_its_settings(
    hass: HomeAssistant, hass_storage
):
    """Stored settings-changed rows carry option keys, so they move.

    The brief turns each recorded key into the label a person read on
    the screen (ruling #314). Rename the keys and leave the history
    alone and every brief covering a day before the upgrade prints
    `excluded_devices` at a person for as long as the row is kept.
    """
    now = dt_util.utcnow().timestamp()
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "key": STORAGE_KEY,
        "data": {
            DATA_DEVICES: {},
            DATA_LAST_VERSION: "0.16.17",
            DATA_SYSTEM_EVENTS: [
                {
                    SYS_WHEN: now - 3600.0,
                    SYS_KIND: SYS_OPTIONS_CHANGED,
                    SYS_SCOPE: "system",
                    SYS_DURATION: None,
                    # The row as 0.16.17 would have written it: the
                    # muting keys in their exclude spellings and the
                    # ignore list under its own name.
                    SYS_DETAIL: (
                        "excluded_devices, battery_excluded_labels, "
                        "ignored_integrations"
                    ),
                    SYS_DEVICES: None,
                },
                {
                    SYS_WHEN: now - 1800.0,
                    SYS_KIND: SYS_RESTART,
                    SYS_SCOPE: "system",
                    SYS_DURATION: 28.0,
                    SYS_DETAIL: None,
                    SYS_DEVICES: None,
                },
                {
                    # A trim's detail is a comma-joined list of names
                    # under the same field. No real device is named
                    # after an option key, so this row is contrived:
                    # what it pins is the rule rather than a case
                    # seen in the wild. The pass is named, not a
                    # sweep, and a sweep over every kind would
                    # rewrite whatever it recognized anywhere.
                    SYS_WHEN: now - 900.0,
                    SYS_KIND: SYS_TRIMMED,
                    SYS_SCOPE: "system",
                    SYS_DURATION: None,
                    SYS_DETAIL: "excluded_devices",
                    SYS_DEVICES: 1,
                },
            ],
        },
    }
    coordinator = await setup_coordinator(hass)

    events = coordinator.data[DATA_SYSTEM_EVENTS]
    assert events[0][SYS_DETAIL] == (
        "muted_devices, battery_muted_labels, excluded_integrations"
    )
    # The neighbouring kinds carry counts and names under the same
    # field, so a sweep rather than a named pass would ruin them.
    assert events[1][SYS_DETAIL] is None
    assert events[2][SYS_DETAIL] == "excluded_devices"


async def test_a_key_it_does_not_know_passes_through(
    hass: HomeAssistant, hass_storage
):
    """A row written by a later version survives a downgrade."""
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "key": STORAGE_KEY,
        "data": {
            DATA_DEVICES: {},
            DATA_LAST_VERSION: "0.16.17",
            DATA_SYSTEM_EVENTS: [
                {
                    SYS_WHEN: dt_util.utcnow().timestamp() - 60.0,
                    SYS_KIND: SYS_OPTIONS_CHANGED,
                    SYS_SCOPE: "system",
                    SYS_DURATION: None,
                    SYS_DETAIL: "something_from_the_future",
                    SYS_DEVICES: None,
                }
            ],
        },
    }
    coordinator = await setup_coordinator(hass)

    events = coordinator.data[DATA_SYSTEM_EVENTS]
    assert events[0][SYS_DETAIL] == "something_from_the_future"


async def test_a_row_written_after_the_rename_is_left_alone(
    hass: HomeAssistant, hass_storage
):
    """`excluded_integrations` means two different settings.

    It was the muting key until 0.16.18 moved it and is the ignore key
    since 0.16.19 moved into the word it vacated. Read without a date,
    a row written by today's release would be rewritten by tomorrow's
    load into a setting its author never touched, and the brief would
    name the wrong screen field at a person. The storage file's own
    version stamp is what tells the two apart.
    """
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "key": STORAGE_KEY,
        "data": {
            DATA_DEVICES: {},
            DATA_LAST_VERSION: "0.16.19",
            DATA_SYSTEM_EVENTS: [
                {
                    SYS_WHEN: dt_util.utcnow().timestamp() - 60.0,
                    SYS_KIND: SYS_OPTIONS_CHANGED,
                    SYS_SCOPE: "system",
                    SYS_DURATION: None,
                    SYS_DETAIL: "excluded_integrations",
                    SYS_DEVICES: None,
                }
            ],
        },
    }
    coordinator = await setup_coordinator(hass)

    events = coordinator.data[DATA_SYSTEM_EVENTS]
    assert events[0][SYS_DETAIL] == "excluded_integrations"
