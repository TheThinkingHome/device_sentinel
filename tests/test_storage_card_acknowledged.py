# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_storage_card_acknowledged.py, Version: 0.27.8 (2026-10-27)

"""Submit on a storage repair card puts it down until a new repair (rules
REP-04, STOR-09): before, the next brief raised it again, because the
coordinator's notice was never cleared."""

from __future__ import annotations

from homeassistant.components.repairs import issue_handler, repairs_flow_manager
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel.const import (
    DOMAIN,
    REPAIR_CONTAINERS_REPAIRED,
    REPAIR_MOMENT_GRACE,
    REPAIR_STORAGE_REPAIRED,
)

from .helpers import setup_coordinator

NOTICE = {
    "moment": "load",
    "what": "1 row(s) dropped from incidents",
    "where": "the originals are in trim_backups under X",
}


def _issue(hass, issue_id):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def _raised(hass):
    hass.data["repairs"] = {}
    issue_handler.async_setup(hass)
    coordinator = await setup_coordinator(hass)
    coordinator._repair_notice = dict(NOTICE)
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_STORAGE_REPAIRED) is not None
    return coordinator


async def test_a_submitted_card_stays_down_at_the_next_brief(hass: HomeAssistant):
    coordinator = await _raised(hass)
    manager = repairs_flow_manager(hass)
    result = await manager.async_init(DOMAIN, context={"issue_id": REPAIR_STORAGE_REPAIRED}, data={"issue_id": REPAIR_STORAGE_REPAIRED})
    assert result["type"] == "form"
    result = await manager.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert coordinator._repair_notice is None
    await coordinator._on_brief_time(dt_util.utcnow())
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_STORAGE_REPAIRED) is None


async def test_a_new_repair_raises_a_new_card(hass: HomeAssistant):
    coordinator = await _raised(hass)
    manager = repairs_flow_manager(hass)
    result = await manager.async_init(DOMAIN, context={"issue_id": REPAIR_STORAGE_REPAIRED}, data={"issue_id": REPAIR_STORAGE_REPAIRED})
    await manager.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    coordinator._repair_notice = dict(NOTICE, what="2 row(s) dropped from incidents")
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_STORAGE_REPAIRED) is not None


async def test_a_repair_made_while_the_card_is_open_is_kept(hass: HomeAssistant):
    coordinator = await _raised(hass)
    manager = repairs_flow_manager(hass)
    result = await manager.async_init(DOMAIN, context={"issue_id": REPAIR_STORAGE_REPAIRED}, data={"issue_id": REPAIR_STORAGE_REPAIRED})
    newer = dict(NOTICE, what="3 row(s) dropped from incidents")
    coordinator._repair_notice = newer
    await manager.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert coordinator._repair_notice is newer
    await coordinator._on_brief_time(dt_util.utcnow())
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_STORAGE_REPAIRED) is not None


async def test_the_containers_card_is_put_down_the_same_way(hass: HomeAssistant):
    hass.data["repairs"] = {}
    issue_handler.async_setup(hass)
    coordinator = await setup_coordinator(hass)
    coordinator._container_notice = {"what": "incidents", "where": "trim_backups under X"}
    coordinator._evaluate_repairs(REPAIR_MOMENT_GRACE)
    await hass.async_block_till_done()
    assert _issue(hass, REPAIR_CONTAINERS_REPAIRED) is not None
    manager = repairs_flow_manager(hass)
    result = await manager.async_init(DOMAIN, context={"issue_id": REPAIR_CONTAINERS_REPAIRED}, data={"issue_id": REPAIR_CONTAINERS_REPAIRED})
    await manager.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert coordinator._container_notice is None
