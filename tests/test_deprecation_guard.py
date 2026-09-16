# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_deprecation_guard.py, Version: 0.21.11 (2026-09-16)

"""The deprecation guard can fail, and it reads what Home Assistant says.

A guard that has never been seen to fail proves nothing. These check
both halves: the matching, against the exact text Home Assistant
writes, and the collection, against a warning the real registry emits
when this integration's own code reads it.
"""

from __future__ import annotations

import pytest
from awesomeversion import AwesomeVersion
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant

from tests.conftest import (
    DEPRECATION_PREFIX,
    KNOWN_DEPRECATIONS,
    FrameLog,
    deprecation_findings,
)
from tests.helpers import register_device, setup_coordinator

# The text Home Assistant 2026.9.2 logged for issue #10, as captured on
# 16 September.
ISSUE_10 = (
    "Detected that custom integration 'device_sentinel' uses "
    "`device_registry.devices` as a mapping or calls its lookup methods, "
    "which is deprecated; iterate it to get the device entries, or use "
    "`async_get`, `async_entries_for_config_entry` and similar helpers "
    "for lookups at custom_components/device_sentinel/coordinator.py, "
    "line 1677: for device in dev_reg.devices.values(). This will stop "
    "working in Home Assistant 2027.9.0"
)

VIEW_ARRIVED = AwesomeVersion(HA_VERSION) >= AwesomeVersion("2026.9.0")


def test_a_new_deprecation_is_a_finding():
    new = ISSUE_10.replace(
        "coordinator.py", "router_ties.py"
    ).replace("dev_reg.devices.values()", "registry.devices.values()")
    assert deprecation_findings([new]) == [new]


def test_the_known_deprecation_is_not():
    assert deprecation_findings([ISSUE_10]) == []


def test_without_the_exception_it_would_be():
    assert deprecation_findings([ISSUE_10], known=()) == [ISSUE_10]


def test_another_integrations_warning_is_not_ours():
    other = ISSUE_10.replace("'device_sentinel'", "'someone_else'")
    assert not other.startswith(DEPRECATION_PREFIX)
    assert deprecation_findings([other], known=()) == []


def test_the_exception_list_stays_short():
    """Each entry is a debt with a release attached, not a shelf."""
    assert len(KNOWN_DEPRECATIONS) <= 1


@pytest.mark.skipif(
    not VIEW_ARRIVED,
    reason="the device registry view that warns arrives in 2026.9",
)
async def test_the_guard_hears_the_real_registry(
    hass: HomeAssistant, no_new_deprecations: FrameLog
):
    """The guard's own collector receives what the registry emits.

    Home Assistant reports a call site once per run, and setting the
    integration up walks the registry, so the collector the guard
    opened for this test is the one that must have heard it.
    """
    register_device(hass, "guard0", "Guard Device")
    await setup_coordinator(hass)
    ours = [
        message for message in no_new_deprecations.messages
        if message.startswith(DEPRECATION_PREFIX)
    ]
    assert ours, "the registry walk logged nothing"
    assert deprecation_findings(ours) == []
    assert deprecation_findings(ours, known=()) == ours
