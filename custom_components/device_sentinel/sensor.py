"""Config and options flows for the Device Sentinel integration.

The config flow is single instance, zero questions: the manifest's
single_config_entry flag makes Home Assistant itself refuse a second
entry, so the flow carries no duplicate guard of its own.

The options flow carries the battery low threshold. It is a UI knob
rather than a constant because batteries drift slowly: proving
detection live means sliding the threshold above a real cell's level
and watching it flag, then sliding it back. Changes apply live with
no restart. The flow is built to grow: the clear margin, the exclude
pickers, and the freeze tuning knobs join this same flow in later
steps.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import CONF_LOW_THRESHOLD, DEFAULT_LOW_THRESHOLD, DOMAIN


class DeviceSentinelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Device Sentinel config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry immediately, no questions asked."""
        return self.async_create_entry(title="Device Sentinel", data={})

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> DeviceSentinelOptionsFlow:
        """Return the options flow handler."""
        return DeviceSentinelOptionsFlow()


class DeviceSentinelOptionsFlow(OptionsFlow):
    """One field today: the battery low threshold, applied live."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the tuning options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current_threshold = self.config_entry.options.get(
            CONF_LOW_THRESHOLD, DEFAULT_LOW_THRESHOLD
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOW_THRESHOLD, default=current_threshold
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=99,
                            step=1,
                            unit_of_measurement="%",
                            mode=NumberSelectorMode.SLIDER,
                        )
                    )
                }
            ),
        )
