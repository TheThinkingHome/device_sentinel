# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_deprecation_guard.py, Version: 0.21.11 (2026-09-16)

"""The deprecation guard can fail, and it reads what Home Assistant says.

A guard that has never been seen to fail proves nothing. These check
both halves: the matching, against the exact text Home Assistant
writes, and the collection, against a warning Home Assistant's own
reporter emits for this integration. And the one use that raised a
warning, issue #10, raises none.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import frame

from tests.conftest import (
    DEPRECATION_PREFIX,
    KNOWN_DEPRECATIONS,
    FrameLog,
    deprecation_findings,
)
from tests.helpers import DOMAIN, register_device, setup_coordinator

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
ISSUE_10_FRAGMENTS = (
    "uses `device_registry.devices` as a mapping",
    "custom_components/device_sentinel/coordinator.py",
    "for device in dev_reg.devices.values()",
)


def test_a_deprecation_is_a_finding():
    assert deprecation_findings([ISSUE_10]) == [ISSUE_10]


def test_a_listed_exception_is_not():
    assert deprecation_findings(
        [ISSUE_10], known=(ISSUE_10_FRAGMENTS,)
    ) == []


def test_an_exception_does_not_cover_the_same_api_elsewhere():
    elsewhere = ISSUE_10.replace(
        "coordinator.py", "router_ties.py"
    ).replace("dev_reg.devices.values()", "registry.devices.values()")
    assert deprecation_findings(
        [elsewhere], known=(ISSUE_10_FRAGMENTS,)
    ) == [elsewhere]


def test_another_integrations_warning_is_not_ours():
    other = ISSUE_10.replace("'device_sentinel'", "'someone_else'")
    assert not other.startswith(DEPRECATION_PREFIX)
    assert deprecation_findings([other]) == []


def test_the_exception_list_stays_short():
    """Each entry is a debt with a release attached, not a shelf."""
    assert len(KNOWN_DEPRECATIONS) <= 1


async def test_the_guard_hears_home_assistant(
    hass: HomeAssistant, no_new_deprecations: FrameLog
):
    """The guard's collector receives what Home Assistant writes.

    Reported through Home Assistant's own function, naming this
    integration, so the text is the real one on whichever harness runs
    this rather than a copy that could drift from it. The guard would
    then fail this test at teardown, which is the point; once the
    finding is confirmed, the one message this test caused is taken
    back so the test can pass.
    """
    await setup_coordinator(hass)
    frame.report_usage(
        "is exercising the deprecation guard",
        integration_domain=DOMAIN,
    )
    ours = [
        message for message in no_new_deprecations.messages
        if message.startswith(DEPRECATION_PREFIX)
    ]
    assert len(ours) == 1, no_new_deprecations.messages
    assert "is exercising the deprecation guard" in ours[0]
    assert deprecation_findings(ours) == ours
    no_new_deprecations.messages.remove(ours[0])


async def test_the_registry_walk_raises_no_deprecation(
    hass: HomeAssistant, no_new_deprecations: FrameLog
):
    """Issue #10: setting up and walking the registry says nothing.

    On 2026.9.2 this walk logged the warning once per run before the
    fix. On 2026.5.0 there was nothing to log, so there this holds
    trivially and the 2026.9.2 run is the proof.
    """
    register_device(hass, "guard0", "Guard Device")
    coord = await setup_coordinator(hass)
    coord._rebuild_registry_view()
    ours = [
        message for message in no_new_deprecations.messages
        if message.startswith(DEPRECATION_PREFIX)
    ]
    assert ours == []
