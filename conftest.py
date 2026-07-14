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
