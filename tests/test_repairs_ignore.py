# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: test_repairs_ignore.py, Version: 0.17.2 (2026-08-24)

"""Every fixable repair offers an ignore (ruling #325).

Home Assistant puts an Ignore button on an issue that is not fixable
and takes it away as soon as one is, because a fixable issue opens
its flow instead of the dialog carrying the button. A person who does
not want the fix was then stuck with the card, which is the fault
reported against 0.16.3 by a person holding 124 deliberately disabled
entities. The ignore now lives inside the flow, beside the fix.
"""

import homeassistant.helpers.issue_registry as ir
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.device_sentinel import repairs as repairs_module
from custom_components.device_sentinel.const import (
    CONF_BRIEF_TARGETS,
    CONF_HIGH_PRIORITY_TARGETS,
    DOMAIN,
    REPAIR_ENTITIES_DISABLED,
    REPAIR_MOMENT_GRACE,
    REPAIR_NOTIFY_TARGET_MISSING,
)

from tests.helpers import register_device, setup_entry


def _issue(hass: HomeAssistant, issue_id: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


def _disabled_signal_entity(hass: HomeAssistant, slug: str) -> None:
    """Register a device with its signal entity turned off.

    Disabled by the person rather than the integration, which is the
    reported case: 124 entities switched off deliberately.
    """
    _device, (entity_id,) = register_device(hass, slug)
    registry = er.async_get(hass)
    registry.async_update_entity(
        entity_id,
        device_class="signal_strength",
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    registry.async_update_entity(entity_id, unit_of_measurement="dBm")


async def _open_enable_flow(hass: HomeAssistant, entry):
    flow = await repairs_module.async_create_fix_flow(
        hass, REPAIR_ENTITIES_DISABLED, {"entry_id": entry.entry_id}
    )
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = REPAIR_ENTITIES_DISABLED
    return flow


async def test_the_enable_card_offers_both_ways_out(
    hass: HomeAssistant,
) -> None:
    """The first screen is a choice, not a confirmation."""
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    _disabled_signal_entity(hass, "ign1")
    coordinator._rebuild_registry_view()
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_ENTITIES_DISABLED) is not None

    flow = await _open_enable_flow(hass, entry)
    menu = await flow.async_step_init()
    assert menu["type"] == "menu"
    assert menu["menu_options"] == ["confirm", "ignore"]
    # The words come from the issue, so the card and the screen it
    # opens can never disagree about how many things are wrong.
    assert menu["description_placeholders"]["count"] == "1"


async def test_ignoring_hides_the_card_and_enables_nothing(
    hass: HomeAssistant,
) -> None:
    """The whole point of the report: a person who does not want
    124 entities turned on can still make the card go away, and
    nothing is turned on when they do."""
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    _disabled_signal_entity(hass, "ign2")
    coordinator._rebuild_registry_view()
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    before = coordinator.awaiting_enable_counts()["signal"]
    assert before == 1

    flow = await _open_enable_flow(hass, entry)
    await flow.async_step_init()
    result = await flow.async_step_ignore({})
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    issue = _issue(hass, REPAIR_ENTITIES_DISABLED)
    assert issue is not None
    assert issue.dismissed_version is not None
    # Nothing was enabled: the entity is still off.
    coordinator._rebuild_registry_view()
    assert coordinator.awaiting_enable_counts()["signal"] == before


async def test_an_ignored_card_does_not_come_back_by_itself(
    hass: HomeAssistant,
) -> None:
    """A later evaluation re-raises the same identifier, which Home
    Assistant treats as an update to the issue already there
    (ruling #293). The dismissal rides along, so the badge stays
    down until the person shows ignored issues again."""
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    _disabled_signal_entity(hass, "ign3")
    coordinator._rebuild_registry_view()
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()

    flow = await _open_enable_flow(hass, entry)
    await flow.async_step_init()
    await flow.async_step_ignore({})
    await hass.async_block_till_done()

    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    issue = _issue(hass, REPAIR_ENTITIES_DISABLED)
    assert issue is not None
    assert issue.dismissed_version is not None


async def test_choosing_enable_still_enables(
    hass: HomeAssistant,
) -> None:
    """The ignore is an addition, not a replacement: the fix path
    through the menu does exactly what it did before."""
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    _disabled_signal_entity(hass, "ign4")
    coordinator._rebuild_registry_view()
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()

    flow = await _open_enable_flow(hass, entry)
    await flow.async_step_init()
    await flow.async_step_confirm({})
    await hass.async_block_till_done()

    assert _issue(hass, REPAIR_ENTITIES_DISABLED) is None
    coordinator._rebuild_registry_view()
    assert coordinator.awaiting_enable_counts()["signal"] == 0


async def test_the_target_card_offers_both_ways_out(
    hass: HomeAssistant,
) -> None:
    """The second fixable repair carries the same choice."""
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
    [REPAIR_ENTITIES_DISABLED, REPAIR_NOTIFY_TARGET_MISSING],
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
