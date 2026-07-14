# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel

"""The Device Sentinel integration.

"""Root conftest for the Device Sentinel test suite (sandbox only).

The harness pre-imports its own custom_components package; this pins
the resolution to this repo's tree before any test collects.
"""

import pathlib
import sys

_ROOT = str(pathlib.Path(__file__).parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.modules.pop("custom_components", None)
import custom_components  # noqa: E402,F401

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in every test."""
    yield
