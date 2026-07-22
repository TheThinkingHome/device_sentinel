# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_v0314_wiki_links.py, Version: 0.7.1 (2026-07-22)

"""0.3.14 tests: every screen links to its own page.

Through 0.3.13 all three screens shared one link and landed on the
wiki's front door, leaving the reader to navigate to the page for the
screen they were already standing on.

A wrong page name cannot be caught by rendering: GitHub answers an
unknown wiki page with a create-this-page screen rather than an
error, so a typo would look like a working link and read as a missing
document. These tests pin the names instead.
"""

import re

from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_sentinel.const import (
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

DOMAIN = "device_sentinel"

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


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Device Sentinel", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _open(hass, entry, step: str) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    return result


# The constants themselves.


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


# The screens, rendered.


async def test_each_screen_supplies_its_own_page(hass: HomeAssistant):
    entry = await _setup(hass)
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
    entry = await _setup(hass)
    for step in ("notifications", "exclusions", "battery"):
        result = await _open(hass, entry, step)
        link = result["description_placeholders"]["wiki_link"]
        assert _page_of(link) != "Home", step


async def test_the_description_still_renders_the_link(hass: HomeAssistant):
    """The placeholder is only useful if the text has somewhere to put
    it. A description that lost its {wiki_link} would leave the link
    supplied and never shown."""
    entry = await _setup(hass)
    for step in ("notifications", "exclusions", "battery"):
        result = await _open(hass, entry, step)
        assert "wiki_link" in result["description_placeholders"], step
