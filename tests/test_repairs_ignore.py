# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_repairs_ignore.py, Version: 0.26.7 (2026-10-19)

"""Every fixable repair offers an ignore (ruling #325).

Home Assistant puts an Ignore button on an issue that is not fixable
and takes it away as soon as one is, because a fixable issue opens
its flow instead of the dialog carrying the button. A person who does
not want the fix was then stuck with the card, which is the fault
reported against 0.16.3 by a person holding 124 deliberately disabled
entities. The ignore now lives inside the flow, beside the fix.

The disabled-entities card that report was about is retired (ruling
#697); a sensor a person switched off is listed already acknowledged
on its Recommendations card instead (#699). The missing-target card
is the fixable one left, and it keeps the rule.
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
    """The standing rule (ruling #325), pinned against every flow
    this module can hand out: a new fixable repair that forgets the
    ignore fails here."""
    flow = await repairs_module.async_create_fix_flow(
        hass, issue_id, {"entry_id": "whatever"}
    )
    assert hasattr(flow, "async_step_ignore")
