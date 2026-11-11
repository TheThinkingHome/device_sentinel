# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_notify_validation_errors.py, Version: 0.28.12 (2026-11-11)

"""A push reaches Signal Messenger on a real Home Assistant 2026.10.

Home Assistant 2026.10 validates with probatio, not voluptuous. Its
Signal Messenger platform (components/signal_messenger/notify.py)
checks `data` against a probatio schema and re-raises probatio.Invalid,
which is not a voluptuous.Invalid. async_notify catches only
vol.Invalid and ServiceValidationError, so on a real house the retry
without `data` never runs and every push to Signal is lost.

Correct behaviour: the push reaches the target.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant, ServiceCall

from tests.helpers import setup_coordinator

# Home Assistant releases before probatio validate with voluptuous only,
# which the other notify tests already cover.
probatio = pytest.importorskip("probatio")

_TEXTMODE = probatio.Optional("text_mode", default="normal")
# As in Home Assistant 2026.10.4 signal_messenger/notify.py.
SIGNAL_DATA_SCHEMA = probatio.Any(
    None,
    probatio.Schema({_TEXTMODE: probatio.In(["normal", "styled"])}),
    probatio.Schema({probatio.Required("attachments"): [str], _TEXTMODE: probatio.In(["normal", "styled"])}),
    probatio.Schema({probatio.Required("urls"): [str], probatio.Optional("verify_ssl", default=True): bool,
                     _TEXTMODE: probatio.In(["normal", "styled"])}),
)


async def test_push_reaches_signal_under_probatio(hass: HomeAssistant) -> None:
    got: list[str] = []

    async def handler(call: ServiceCall) -> None:
        SIGNAL_DATA_SCHEMA(call.data.get("data"))  # raises probatio.Invalid
        got.append("signal_home")

    hass.services.async_register("notify", "signal_home", handler)
    coord = await setup_coordinator(
        hass, {"high_priority_targets": ["notify.signal_home"]}
    )
    await coord._push_family_event("battery", "At 8:00 am, Door battery is low.", False)
    await hass.async_block_till_done()
    assert got == ["signal_home"], got
