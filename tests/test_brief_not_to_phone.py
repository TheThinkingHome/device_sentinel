# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_brief_not_to_phone.py, Version: 0.28.12 (2026-11-11)

"""The full brief does not go to a phone (rule BRIEF-11).

The brief is for mail or a persistent notification. A phone's push
relay will not carry a brief of any size, the phone shows nothing, and
the brief was counted as sent. A phone chosen in Send the Full Brief To
is refused on Submit; one saved before is skipped when the brief is
sent, and the rest of the screen can still be saved.
"""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType

from custom_components.device_sentinel.const import CONF_BRIEF_TARGETS

from tests.helpers import setup_entry
from tests.test_brief_targets import _open, _section_collapsed, _submit

PHONE = "notify.mobile_app_pixel"
MAIL = "notify.house_mail"


def _services(hass: HomeAssistant) -> list[ServiceCall]:
    hass.data["notify_services"] = {
        "mobile_app": [SimpleNamespace(_service_name="mobile_app", registered_targets={"mobile_app_pixel": "x"})],
        "smtp": [SimpleNamespace(_service_name="house_mail", registered_targets={})],
    }
    calls: list[ServiceCall] = []

    async def _record(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("notify", "mobile_app_pixel", _record)
    hass.services.async_register("notify", "house_mail", _record)
    return calls


async def test_a_phone_chosen_for_the_brief_is_refused(hass: HomeAssistant):
    entry = await setup_entry(hass)
    _services(hass)
    result = await _open(hass, entry)
    result = await hass.config_entries.options.async_configure(result["flow_id"], _submit([PHONE]))
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"brief": "brief_target_is_phone"}
    assert _section_collapsed(result, "brief") is False
    assert PHONE not in (entry.options.get(CONF_BRIEF_TARGETS) or [])


async def test_a_phone_saved_before_is_kept_but_never_sent_the_brief(hass: HomeAssistant):
    entry = await setup_entry(hass)
    calls = _services(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_BRIEF_TARGETS: [PHONE, MAIL]})
    await hass.async_block_till_done()
    coord = entry.runtime_data
    # The rest of the screen still saves with it there.
    result = await _open(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit([PHONE, MAIL], quiet_start="23:00:00")
    )
    assert result["type"] is FlowResultType.MENU
    coord = entry.runtime_data
    coord._brief_should_send = lambda: True
    sent = await coord.async_send_brief("The brief.")
    await hass.async_block_till_done()
    assert sent == 1
    assert [call.service for call in calls] == ["house_mail"]
