# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_placeholder_chip_makers.py, Version: 0.28.12 (2026-11-11)

"""Rule DEV-06: a chip maker naming its board is no product. 

ESPHome sends a device's chip maker as its manufacturer and the board as
its model when no project name is set. The chain in ESPHome's
api_connection.cpp: "Espressif" (ESP8266, ESP32), "Raspberry Pi" (RP2),
"Beken" (BK72xx), "Lightning" (LN882x), "Nordic Semiconductor" (nRF52),
"Realtek" (RTL87xx). Only Espressif is treated as standing for none, so
every Tuya plug, bulb and switch flashed with ESPHome on a CB2S or WB2S
module (Beken) shares one model: one type or power answer covers all of
them, and they pool in Model Groups and the battery pace.
"""

from __future__ import annotations

import pytest

from custom_components.device_sentinel.power_source import model_key, stands_for_none


@pytest.mark.parametrize(
    ("maker", "board"),
    [
        ("Espressif", "esp32dev"),  # covered today, the control
        ("Beken", "cb2s"),
        ("Beken", "generic-bk7231n-qfn32-tuya"),
        ("Realtek", "generic-rtl8710bn-2mb-788k"),
        ("Lightning", "generic-ln882hki"),
    ],
)
def test_an_esphome_chip_maker_and_board_stand_for_none(maker, board):
    assert stands_for_none(maker, board)
    assert model_key(maker, board, None) is None
