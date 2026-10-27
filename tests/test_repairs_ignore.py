# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_repairs_ignore.py, Version: 0.27.10 (2026-10-27)

"""Every fixable repair offers an ignore (rule REP-06).

Home Assistant puts an Ignore button on an issue that is not fixable
and takes it away as soon as one is, because a fixable issue opens its
flow instead of the dialog carrying the button. A person who does not
want the fix is then stuck with the card, so the ignore lives inside
the flow, beside the fix.

The missing-target card is the fixable one left, and it keeps the rule.
A sensor a person switched off is listed already acknowledged on its
Recommendations card instead (rule REC-07).
"""

import homeassistant.helpers.issue_registry as ir
import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel import repairs as repairs_module
from custom_components.device_sentinel.const import (
    CONF_BRIEF_TARGETS,
    CONF_HIGH_PRIORITY_TARGETS,
    DOMAIN,
    REPAIR_MOMENT_GRACE,
    REPAIR_NOTIFY_TARGET_MISSING,
)

from tests.helpers import setup_entry


def _issue(hass: HomeAssistant, issue_id: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def test_the_target_card_offers_both_ways_out(
    hass: HomeAssistant,
) -> None:
    """The fixable repair carries both ways out."""
    entry = await setup_entry(
        hass,
        options={
            CONF_HIGH_PRIORITY_TARGETS: ["notify.gone_phone"],
            CONF_BRIEF_TARGETS: ["persistent_notification"],
        },
    )
    coordinator = entry.runtime_data
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_NOTIFY_TARGET_MISSING) is not None

    flow = await repairs_module.async_create_fix_flow(
        hass, REPAIR_NOTIFY_TARGET_MISSING, {"entry_id": entry.entry_id}
    )
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = REPAIR_NOTIFY_TARGET_MISSING
    menu = await flow.async_step_init()
    assert menu["type"] == "menu"
    assert menu["menu_options"] == ["confirm", "ignore"]

    await flow.async_step_ignore({})
    await hass.async_block_till_done()
    issue = _issue(hass, REPAIR_NOTIFY_TARGET_MISSING)
    assert issue is not None
    assert issue.dismissed_version is not None
    # The dead target is still in the settings: ignore changes
    # nothing but the badge.
    assert entry.options[CONF_HIGH_PRIORITY_TARGETS] == [
        "notify.gone_phone"
    ]


@pytest.mark.parametrize(
    "issue_id",
    [REPAIR_NOTIFY_TARGET_MISSING],
)
async def test_every_fixable_flow_has_an_ignore_step(
    hass: HomeAssistant, issue_id: str
) -> None:
    """The standing rule, pinned against every flow this module can hand
    out: a new fixable repair that forgets the ignore fails here
    (rule REP-06).
    """
    flow = await repairs_module.async_create_fix_flow(
        hass, issue_id, {"entry_id": "whatever"}
    )
    assert hasattr(flow, "async_step_ignore")
