# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_owner_entry.py, Version: 0.23.20 (2026-10-01)

"""Who owns a device, read without the attributes 2026.10 deprecates.

Home Assistant 2026.8 gave every device one config entry, named by
`config_entry_id`, and 2026.10 reports any read of the two attributes
it replaced, `primary_config_entry` and `config_entries`. Device
Sentinel reads the owner in two places, the entry it watches and the
domain it files a device under. These check that the owner comes from
`config_entry_id` wherever it exists and the old attributes are never
touched there; that before 2026.8, where it does not exist, the old
order stands; and that the one case Home Assistant itself exempts, a
restored composite device, keeps the old order on new versions too.

The stand-in devices are plain objects whose old attributes raise
when read, so the never-touched checks hold on every Home Assistant
version, not only on 2026.10 where the read would be reported.
"""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.conftest import DEPRECATION_PREFIX, FrameLog
from tests.helpers import register_device, setup_coordinator


class _NewDevice:
    """A device as Home Assistant 2026.8 and later shape it.

    Reading either old attribute is a test failure, which is the
    strongest form of "never touched": no version can report a read
    that never happens.
    """

    def __init__(self, owner: str, composite: bool = False,
                 entries: tuple[str, ...] = ()) -> None:
        self.config_entry_id = owner
        self.is_composite_device = composite
        self._entries = entries

    @property
    def primary_config_entry(self) -> str:
        if not self.is_composite_device:
            raise AssertionError("primary_config_entry was read")
        return self.config_entry_id

    @property
    def config_entries(self) -> set[str]:
        if not self.is_composite_device:
            raise AssertionError("config_entries was read")
        return set(self._entries) | {self.config_entry_id}


def _old_device(primary: str | None, entries: tuple[str, ...]):
    """A device as Home Assistant 2026.5 to 2026.7 shape it."""
    return SimpleNamespace(
        primary_config_entry=primary, config_entries=set(entries)
    )


async def test_the_owner_is_config_entry_id_and_nothing_else_is_read(
    hass: HomeAssistant,
):
    """2026.8 and later: the owner is config_entry_id, alone."""
    owner = MockConfigEntry(domain="camera_brand")
    owner.add_to_hass(hass)
    coord = await setup_coordinator(hass)
    device = _NewDevice(owner.entry_id)
    assert coord._owner_candidates(device) == [owner.entry_id]
    assert coord._primary_entry(device) == owner.entry_id
    assert coord._primary_domain(device) == "camera_brand"


async def test_an_owner_whose_entry_is_gone_is_still_the_owner(
    hass: HomeAssistant,
):
    """The owner is returned as it stands, as 0.23.19 returned the primary.

    Its domain then reads unknown, the same answer 0.23.19 gave a
    device whose only entry had gone, and no other entry is consulted,
    because on 2026.8 and later there is no other.
    """
    coord = await setup_coordinator(hass)
    device = _NewDevice("no-such-entry")
    assert coord._primary_entry(device) == "no-such-entry"
    assert coord._primary_domain(device) == "unknown"


async def test_before_2026_8_the_primary_comes_first(hass: HomeAssistant):
    """2026.5 to 2026.7: the primary, then the rest sorted."""
    tracker = MockConfigEntry(domain="router_tracker", entry_id="a-tracker")
    tracker.add_to_hass(hass)
    owner = MockConfigEntry(domain="camera_brand", entry_id="z-owner")
    owner.add_to_hass(hass)
    coord = await setup_coordinator(hass)
    device = _old_device("z-owner", ("a-tracker", "z-owner"))
    assert coord._owner_candidates(device) == ["z-owner", "a-tracker", "z-owner"]
    assert coord._primary_entry(device) == "z-owner"
    assert coord._primary_domain(device) == "camera_brand"


async def test_before_2026_8_with_no_primary_the_first_living_entry_owns(
    hass: HomeAssistant,
):
    """No primary: the first entry, sorted, that still exists."""
    living = MockConfigEntry(domain="router_tracker", entry_id="m-living")
    living.add_to_hass(hass)
    coord = await setup_coordinator(hass)
    device = _old_device(None, ("a-gone", "m-living"))
    assert coord._primary_entry(device) == "m-living"
    assert coord._primary_domain(device) == "router_tracker"
    assert coord._primary_entry(_old_device(None, ())) is None
    assert coord._primary_domain(_old_device(None, ())) == "unknown"


async def test_a_restored_composite_keeps_the_old_order(hass: HomeAssistant):
    """The case Home Assistant exempts keeps 0.23.19's fallback.

    A restored composite is the stand-in Home Assistant builds for a
    device id from before the 2026.8 split. It can list several
    entries, and reading its old attributes reports nothing, so its
    domain falls back to another entry when its owner's has gone.
    """
    other = MockConfigEntry(domain="router_tracker", entry_id="b-other")
    other.add_to_hass(hass)
    coord = await setup_coordinator(hass)
    device = _NewDevice("a-gone", composite=True, entries=("b-other",))
    assert coord._owner_candidates(device) == ["a-gone", "a-gone", "b-other"]
    assert coord._primary_entry(device) == "a-gone"
    assert coord._primary_domain(device) == "router_tracker"


async def test_a_real_registry_device_reports_no_deprecation(
    hass: HomeAssistant, no_new_deprecations: FrameLog
):
    """On the running Home Assistant, a real device says nothing.

    On 2026.10 the fixture fails the test at teardown for any
    deprecated read; on earlier versions this holds trivially and the
    stand-in tests above are the proof.
    """
    registered, _entities = register_device(hass, "owner0", "Owner Device")
    coord = await setup_coordinator(hass)
    device = dr.async_get(hass).async_get(registered.id)
    assert device is not None
    entry_id = coord._primary_entry(device)
    assert entry_id is not None
    assert coord._primary_domain(device) == (
        hass.config_entries.async_get_entry(entry_id).domain
    )
    coord._rebuild_registry_view()
    ours = [
        message for message in no_new_deprecations.messages
        if message.startswith(DEPRECATION_PREFIX)
    ]
    assert ours == []
