# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_restore_notice_telegram.py, Version: 0.28.12 (2026-11-11)

"""The storage-restore notice to a Telegram target (rule NOTE-02).

Device Sentinel tells Telegram every push and brief is plain text
(fitted_for: data {"parse_mode": "plain_text"}), because Telegram's
default parser is Markdown (telegram_bot config_flow default
PARSER_MD) and it refuses a message whose underscores do not pair.
messenger.async_announce_restore still calls the notify action directly,
without fitted_for. Its text names the folder and the stamp:
"Copies of the storage file were saved in device_sentinel/trim_backups
under the stamp 2026-11-11_103000." Three underscores, unpaired, so the
bot's send_message is refused. The legacy telegram notify platform calls
telegram_bot.send_message without blocking, so the refusal is only a
line in Home Assistant's log; Device Sentinel counts the notice as sent.

Correct behaviour: the restore notice to a Telegram target says it is
plain text, as every other message to Telegram does.
"""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant, ServiceCall

from tests.helpers import setup_coordinator


async def test_restore_notice_to_telegram_is_plain_text(hass: HomeAssistant) -> None:
    got: list[dict] = []

    async def telegram(call: ServiceCall) -> None:
        got.append(dict(call.data))

    hass.services.async_register("notify", "telegram_home", telegram)
    coord = await setup_coordinator(hass, {"brief_document_targets": ["notify.telegram_home"]})
    hass.data.setdefault("notify_services", {})["telegram"] = [
        SimpleNamespace(_service_name="telegram_home", registered_targets={})
    ]

    sent = await coord.async_announce_restore(
        "Device Sentinel could not read its storage file.",
        "Nothing was lost.\n\nCopies of the storage file were saved in "
        "device_sentinel/trim_backups under the stamp 2026-11-11_103000.",
    )
    await hass.async_block_till_done()

    assert sent == 1
    assert len(got) == 1, got
    assert (got[0].get("data") or {}).get("parse_mode") == "plain_text", got[0]
