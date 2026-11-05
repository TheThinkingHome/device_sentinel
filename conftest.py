# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
"""Root conftest for the Device Sentinel test suite (sandbox only).

The harness pre-imports its own custom_components package; this pins
the resolution to this repo's tree before any test collects.
"""

import pathlib
import sys

# Home Assistant 2026.11 ships its own test harness, pytest_homeassistant,
# in place of pytest_homeassistant_custom_component, with the same
# helpers. The tests import the older name; on a 2026.11 harness that
# name is pointed at the new one, so the suite runs unchanged on both
# (rule REL-03).
try:
    import pytest_homeassistant_custom_component  # noqa: F401
except ImportError:
    import pytest_homeassistant
    import pytest_homeassistant.common
    import pytest_homeassistant.typing

    sys.modules["pytest_homeassistant_custom_component"] = pytest_homeassistant
    sys.modules["pytest_homeassistant_custom_component.common"] = pytest_homeassistant.common
    sys.modules["pytest_homeassistant_custom_component.typing"] = pytest_homeassistant.typing

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
