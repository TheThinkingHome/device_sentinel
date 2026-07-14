"""Config and options flows for the Device Sentinel integration.

The config flow is single instance, zero questions: the manifest's
single_config_entry flag makes Home Assistant itself refuse a second
entry, so the flow carries no duplicate guard of its own.

The options flow is a menu that branches to each configuration
surface, so it grows without becoming one long form. Today:

- Thresholds: the battery low threshold, applied live. It is a UI
  knob rather than a constant because batteries drift slowly, and
  proving detection live means sliding the threshold above a real
  cell's level and watching it flag.
- Notifications: the backbone of the Step 5 engine, built ahead of
  it because the configuration surface is self-contained and touches
  no detection path. Discovered notify targets, the quiet-hours
  window, the daily-reminder time, and whether high-priority items
  pierce quiet hours. These settings are stored and inert until the
  engine reads them.

The Exclusions surface joins this same menu in a later step.
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
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_HIGH_PRIORITY_PIERCES_QUIET,
    CONF_LOW_THRESHOLD,
    CONF_NOTIFY_TARGETS,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_REMINDER_TIME,
    DEFAULT_HIGH_PRIORITY_PIERCES_QUIET,
    DEFAULT_LOW_THRESHOLD,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    DEFAULT_REMINDER_TIME,
    DOMAIN,
)

# The notify domain exposes one service per target; the persistent
# notification is always available. These are what the engine will
# eventually call, discovered live so the picker shows real targets.
NOTIFY_DOMAIN = "notify"
PERSISTENT_TARGET = "persistent_notification"


def _discover_notify_targets(hass: Any) -> list[str]:
    """Return the notify targets present on this system.

    Every registered notify service is a target (mobile apps, custom
    notifiers), plus the always-present persistent notification. This
    is a live registry read, so the picker reflects the system as it
    is now rather than a hand-kept list.
    """
    targets = {PERSISTENT_TARGET}
    for service_name in hass.services.async_services().get(
        NOTIFY_DOMAIN, {}
    ):
        targets.add(f"{NOTIFY_DOMAIN}.{service_name}")
    return sorted(targets)


class DeviceSentinelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Device Sentinel config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry immediately, no questions asked."""
        return self.async_create_entry(title="Device Sentinel", data={})

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> DeviceSentinelOptionsFlow:
        """Return the options flow handler."""
        return DeviceSentinelOptionsFlow()


class DeviceSentinelOptionsFlow(OptionsFlow):
    """A menu branching to each configuration surface."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the top-level menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["thresholds", "notifications"],
        )

    async def async_step_thresholds(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The battery low threshold, applied live on save."""
        if user_input is not None:
            return self.async_create_entry(
                data={**self.config_entry.options, **user_input}
            )
        current = self.config_entry.options.get(
            CONF_LOW_THRESHOLD, DEFAULT_LOW_THRESHOLD
        )
        return self.async_show_form(
            step_id="thresholds",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOW_THRESHOLD, default=current
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=99,
                            step=1,
                            unit_of_measurement="%",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    )
                }
            ),
        )

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The notification backbone: targets, quiet hours, reminder.

        Stored and inert until the Step 5 engine reads them. High
        priority pierces quiet hours so a critical item (a freezer
        sensor at 3 AM) is never held back.
        """
        if user_input is not None:
            return self.async_create_entry(
                data={**self.config_entry.options, **user_input}
            )
        options = self.config_entry.options
        discovered = _discover_notify_targets(self.hass)
        return self.async_show_form(
            step_id="notifications",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_NOTIFY_TARGETS,
                        default=options.get(CONF_NOTIFY_TARGETS, []),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=discovered,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                            custom_value=True,
                        )
                    ),
                    vol.Required(
                        CONF_QUIET_START,
                        default=options.get(
                            CONF_QUIET_START, DEFAULT_QUIET_START
                        ),
                    ): selector.TimeSelector(),
                    vol.Required(
                        CONF_QUIET_END,
                        default=options.get(
                            CONF_QUIET_END, DEFAULT_QUIET_END
                        ),
                    ): selector.TimeSelector(),
                    vol.Required(
                        CONF_REMINDER_TIME,
                        default=options.get(
                            CONF_REMINDER_TIME, DEFAULT_REMINDER_TIME
                        ),
                    ): selector.TimeSelector(),
                    vol.Required(
                        CONF_HIGH_PRIORITY_PIERCES_QUIET,
                        default=options.get(
                            CONF_HIGH_PRIORITY_PIERCES_QUIET,
                            DEFAULT_HIGH_PRIORITY_PIERCES_QUIET,
                        ),
                    ): selector.BooleanSelector(),
                }
            ),
        )
