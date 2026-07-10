"""Config flow for the Device Sentinel integration.

Single instance, zero questions. The manifest's single_config_entry
flag makes Home Assistant itself refuse a second entry, so the flow
carries no duplicate guard of its own. Configuration arrives through
the options flow in a later step; there is nothing to ask at setup.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class DeviceSentinelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Device Sentinel config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry immediately, no questions asked."""
        return self.async_create_entry(title="Device Sentinel", data={})
