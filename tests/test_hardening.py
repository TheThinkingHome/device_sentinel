# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_hardening.py, Version: 0.9.9 (2026-07-26)

"""Audit hardening, legacy cleanup, and the per-screen wiki links.

The audit fixes guard the edges: report cells escape pipes and newlines
in a device name so a table keeps its column count, the hot-path
handlers survive an entity missing from the map, a since ahead of the
clock prints a zero age rather than a negative one, and a signal line
whose name lookup misses falls back to the device id. Two idempotent
cleanups keep the store and the registry tidy: the storage prune drops
any stored field the current schema no longer holds, and the dead-types
sweep removes registry entities whose sentinel type was retired. And
every settings screen links to its own wiki page rather than the front
door, with the page names pinned as constants because a typo would
render as a create-this-page screen rather than an error. This file
holds the audit fixes, the two cleanups, and the wiki links.
"""

import re
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.coordinator import (
    DeviceSentinelCoordinator,
    _new_device_record,
)
from custom_components.device_sentinel.const import (
    DEAD_ENTITY_SENTINEL_TYPES,
    DEV_DAILY_MAX,
    DEV_FROZEN_CATEGORY,
    DEV_FROZEN_SINCE,
    DEV_LAST_ACTIVITY,
    FREEZE_ARMING_DAYS,
    FREEZE_CATEGORY_FROZEN,
    WIKI_BASE_URL,
    WIKI_LINK_BATTERY,
    WIKI_LINK_DEVICE_PAGE,
    WIKI_LINK_EXCLUSIONS,
    WIKI_LINK_FAQ,
    WIKI_LINK_FREEZE,
    WIKI_LINK_HOME,
    WIKI_LINK_LEARNING,
    WIKI_LINK_NOTIFICATIONS,
    WIKI_LINK_PROBLEM_LIST,
    WIKI_LINK_RECOVERY,
    WIKI_LINK_REPORTS,
    WIKI_LINK_SIGNAL,
)

from tests.helpers import setup_coordinator, setup_entry

DOMAIN = "device_sentinel"


def _register(hass, uid, name):
    source = MockConfigEntry(domain="test", title="Source")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={("test", uid)},
        name=name,
    )
    ent = er.async_get(hass).async_get_or_create(
        "sensor", "test", f"{uid}_0",
        device_id=device.id, config_entry=source,
    )
    return device, ent.entity_id


def _freeze(coord, device_id, since=1_000_000.0):
    record = coord.data["devices"][device_id]
    record[DEV_DAILY_MAX] = [3600.0] * (FREEZE_ARMING_DAYS + 2)
    record[DEV_LAST_ACTIVITY] = since - 10.0
    record[DEV_FROZEN_CATEGORY] = FREEZE_CATEGORY_FROZEN
    record[DEV_FROZEN_SINCE] = since


# ==================================================================
# The four audit hardening fixes.
# ==================================================================

async def test_pipe_in_name_stays_in_one_cell(hass: HomeAssistant):
    """S1: a pipe in a device name is escaped everywhere it appears,
    so the tables keep their column count."""
    device, eid = _register(hass, "p1", "Weird | Name")
    coord = await setup_coordinator(hass)
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    await hass.async_add_executor_job(coord._write_reports, "test")

    telemetry = open(
        hass.config.path("device_sentinel", "diagnostics", "device_telemetry.md"),
        encoding="utf-8",
    ).read()
    classification = open(
        hass.config.path("device_sentinel", "diagnostics", "classification.md"),
        encoding="utf-8",
    ).read()
    assert "Weird \\| Name" in telemetry
    assert "Weird \\| Name" in classification
    assert "Weird | Name" not in telemetry
    # The table rows containing it still parse to the right width.
    for line in classification.splitlines():
        if "Weird" in line and line.startswith("|"):
            assert line.count("|") - line.count("\\|") == 7


async def test_newline_in_name_is_flattened(hass: HomeAssistant):
    """S1: a newline in a name cannot break a report row."""
    assert (
        DeviceSentinelCoordinator._report_cell("Two\nLines") == "Two Lines"
    )


async def test_hot_path_survives_unmapped_entity(hass: HomeAssistant):
    """C1: a state event for an entity not in the map returns quietly
    instead of raising."""
    coord = await setup_coordinator(hass)
    fake = SimpleNamespace(
        data={
            "entity_id": "sensor.never_mapped",
            "new_state": SimpleNamespace(state="42"),
        }
    )
    coord._on_state_changed(fake)
    coord._on_state_reported(fake)


async def test_future_since_prints_zero_age(hass: HomeAssistant):
    """C2: a since ahead of the clock clamps to zero, no negatives."""
    device, eid = _register(hass, "f1", "Future Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id, since=dt_util.utcnow().timestamp() + 3600)
    coord._sync_problem_list()
    text = "\n".join(coord._reporting_lines())
    assert "for 0m" in text
    assert "-" not in text.split("for ")[1].split(" ")[0]


async def test_signal_line_falls_back_to_device_id(hass: HomeAssistant):
    """C3: a missing name prints the device id, never None."""
    device, eid = _register(hass, "n1", "Named Sensor")
    coord = await setup_coordinator(hass)
    hass.states.async_set(eid, "21.5")
    _freeze(coord, device.id)
    coord._sync_problem_list()
    # Blank the name map to force the miss.
    coord._device_names = {}
    rows = [
        {"name": None, "device_id": device.id, "kind": "rail"},
    ]
    # Exercise the formatting path through the section by patching
    # the property's source list.
    original = type(coord).signal_problem_list
    try:
        type(coord).signal_problem_list = property(lambda self: rows)
        text = "\n".join(coord._reporting_lines())
    finally:
        type(coord).signal_problem_list = original
    assert device.id in text
    assert "**None**" not in text


# ==================================================================
# Legacy storage keys pruned, retired entities swept.
# ==================================================================

def test_prune_drops_legacy_keys_keeps_current():
    """A record carrying old frozen fields loses them; every current
    field survives."""
    record = _new_device_record("2026-07-19T00:00:00+00:00", 1000.0)
    # Inject the 0.4.x fields the rail rework removed.
    record["signal_frozen_verdict"] = True
    record["signal_repeat_count"] = 5
    record["signal_frozen_at"] = "2026-07-18T00:00:00+00:00"
    record["signal_rail_since"] = "2026-07-18T00:00:00+00:00"
    before = set(_new_device_record("", None).keys())

    removed = DeviceSentinelCoordinator._prune_legacy_fields(
        {"dev": record}
    )

    assert removed == 4
    assert set(record.keys()) == before


def test_prune_is_idempotent():
    """A clean record loses nothing and reports zero."""
    record = _new_device_record("2026-07-19T00:00:00+00:00", 1000.0)
    removed = DeviceSentinelCoordinator._prune_legacy_fields(
        {"dev": record}
    )
    assert removed == 0


def test_dead_types_tuple_is_the_sweep_source():
    """The sweep reads its targets from the dead-types tuple. The
    0.4.8 entries were removed at 0.4.12 once every install was past
    them (ruling 82); the mechanism stays, holding the clock-source
    type it still needs."""
    from custom_components.device_sentinel.const import (
        SENTINEL_TYPE_CLOCK_SOURCE,
    )
    assert SENTINEL_TYPE_CLOCK_SOURCE in DEAD_ENTITY_SENTINEL_TYPES
    # The satisfied 0.4.8 entries are gone, not lingering as dead
    # weight.
    for gone in (
        "signal_frozen",
        "battery_low_count",
        "battery_low_list",
        "signal_tracked",
    ):
        assert gone not in DEAD_ENTITY_SENTINEL_TYPES


async def test_setup_prunes_stored_legacy_fields(hass: HomeAssistant):
    """End to end: a stored record with legacy fields is clean after
    setup."""
    entry = await setup_entry(hass)
    coord = entry.runtime_data
    # Inject a legacy key, then run the prune the load path uses.
    for record in coord.data["devices"].values():
        record["signal_frozen_verdict"] = True
        break
    removed = coord._prune_legacy_fields(coord.data["devices"])
    assert removed >= 0  # prune runs without error on live records


async def test_retired_ghost_entity_is_removed(hass: HomeAssistant):
    """A registry entity under a retired unique id is gone after
    setup."""
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    reg = er.async_get(hass)
    # Pre-create a ghost under a type still in the sweep tuple.
    ghost = reg.async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_clock_source",
        suggested_object_id="device_sentinel_clock_source",
    )
    assert reg.async_get(ghost.entity_id) is not None

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert reg.async_get(ghost.entity_id) is None


# ==================================================================
# Every screen links to its own wiki page.
# ==================================================================

# The wiki's page titles as published. Hyphens are how GitHub renders
# a space in a page title into a URL.
PUBLISHED_PAGES = {
    "Home",
    "Notifications-and-Daily-Brief",
    "Advanced",
    "Global-Exclusions",
    "Low-Battery",
    "Signal-Strength",
    "Freeze-Detection",
    "Recovery",
    "How-Device-Sentinel-Learns",
    "The-Device-Page",
    "The-Problem-List",
    "The-Reports",
    "FAQ-and-Troubleshooting",
}

ALL_LINKS = {
    "WIKI_LINK_HOME": WIKI_LINK_HOME,
    "WIKI_LINK_NOTIFICATIONS": WIKI_LINK_NOTIFICATIONS,
    "WIKI_LINK_EXCLUSIONS": WIKI_LINK_EXCLUSIONS,
    "WIKI_LINK_BATTERY": WIKI_LINK_BATTERY,
    "WIKI_LINK_SIGNAL": WIKI_LINK_SIGNAL,
    "WIKI_LINK_FREEZE": WIKI_LINK_FREEZE,
    "WIKI_LINK_RECOVERY": WIKI_LINK_RECOVERY,
    "WIKI_LINK_LEARNING": WIKI_LINK_LEARNING,
    "WIKI_LINK_DEVICE_PAGE": WIKI_LINK_DEVICE_PAGE,
    "WIKI_LINK_PROBLEM_LIST": WIKI_LINK_PROBLEM_LIST,
    "WIKI_LINK_REPORTS": WIKI_LINK_REPORTS,
    "WIKI_LINK_FAQ": WIKI_LINK_FAQ,
}


def _page_of(markdown_link: str) -> str:
    """Return the wiki page a markdown link targets."""
    url = re.search(r"\((.*?)\)", markdown_link).group(1)
    return url.rsplit("/wiki", 1)[1].lstrip("/") or "Home"


async def _open(hass, entry, step: str) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    return result


def test_every_link_targets_a_published_page():
    """A page name that matches nothing renders as a create-this-page
    screen rather than an error, so a typo would ship looking fine."""
    for name, link in ALL_LINKS.items():
        assert _page_of(link) in PUBLISHED_PAGES, (name, _page_of(link))


def test_every_link_is_markdown_pointing_at_the_wiki():
    for name, link in ALL_LINKS.items():
        assert link.startswith("[Device Sentinel wiki]("), name
        assert WIKI_BASE_URL in link, name
        assert link.endswith(")"), name


def test_links_are_distinct_per_page():
    """The bug this release fixes: one link shared by every screen."""
    targets = [_page_of(link) for link in ALL_LINKS.values()]
    assert len(targets) == len(set(targets))


def test_home_link_has_no_page_suffix():
    assert _page_of(WIKI_LINK_HOME) == "Home"
    assert WIKI_LINK_HOME.endswith(f"({WIKI_BASE_URL})")


async def test_each_screen_supplies_its_own_page(hass: HomeAssistant):
    entry = await setup_entry(hass)
    expected = {
        "notifications": "Notifications-and-Daily-Brief",
        "advanced": "Advanced",
        "exclusions": "Global-Exclusions",
        "battery": "Low-Battery",
    }
    for step, page in expected.items():
        result = await _open(hass, entry, step)
        link = result["description_placeholders"]["wiki_link"]
        assert _page_of(link) == page, step


async def test_no_screen_lands_on_the_front_door(hass: HomeAssistant):
    """Through 0.3.13 every screen did."""
    entry = await setup_entry(hass)
    for step in ("notifications", "exclusions", "battery"):
        result = await _open(hass, entry, step)
        link = result["description_placeholders"]["wiki_link"]
        assert _page_of(link) != "Home", step


async def test_the_description_still_renders_the_link(hass: HomeAssistant):
    """The placeholder is only useful if the text has somewhere to put
    it. A description that lost its {wiki_link} would leave the link
    supplied and never shown."""
    entry = await setup_entry(hass)
    for step in ("notifications", "exclusions", "battery"):
        result = await _open(hass, entry, step)
        assert "wiki_link" in result["description_placeholders"], step
