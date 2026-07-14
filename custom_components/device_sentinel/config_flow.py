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
    CONF_EXCLUDED_AREAS,
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_ENTITIES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_EXCLUDED_LABELS,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_LOW_THRESHOLD,
    CONF_NORMAL_PRIORITY_TARGETS,
    CONF_PERSISTENT_ENABLED,
    CONF_QUIET_ENABLED,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_REMINDER_MODE,
    CONF_REMINDER_TIME,
    DEFAULT_LOW_THRESHOLD,
    DEFAULT_PERSISTENT_ENABLED,
    DEFAULT_QUIET_ENABLED,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    DEFAULT_REMINDER_MODE,
    DEFAULT_REMINDER_TIME,
    DOMAIN,
    REMINDER_MODE_DAILY,
    REMINDER_MODE_NONE,
    REMINDER_MODE_OVERNIGHT,
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
            menu_options=["thresholds", "notifications", "exclusions"],
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

    async def async_step_exclusions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The exclude surface: five selectors, one list, every family.

        Exclusion suppresses judgment, not observation (a ruled
        decision): excluded devices and entities keep their clocks,
        statistics, and vouching, so undo is instant and the rhythm
        history carries no holes. Changes apply live on save through
        the options update listener, no restart.

        The integration picker is populated live from the config
        entries present on this system; an integration exclude
        catches only devices that integration owns, never multi-homed
        hardware it merely sees.
        """
        if user_input is not None:
            return self.async_create_entry(
                data={**self.config_entry.options, **user_input}
            )
        options = self.config_entry.options
        integration_domains = sorted(
            {
                entry.domain
                for entry in self.hass.config_entries.async_entries()
                if entry.domain != DOMAIN
            }
        )
        return self.async_show_form(
            step_id="exclusions",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_EXCLUDED_ENTITIES,
                        default=options.get(CONF_EXCLUDED_ENTITIES, []),
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(multiple=True)
                    ),
                    vol.Optional(
                        CONF_EXCLUDED_DEVICES,
                        default=options.get(CONF_EXCLUDED_DEVICES, []),
                    ): selector.DeviceSelector(
                        selector.DeviceSelectorConfig(multiple=True)
                    ),
                    vol.Optional(
                        CONF_EXCLUDED_LABELS,
                        default=options.get(CONF_EXCLUDED_LABELS, []),
                    ): selector.LabelSelector(
                        selector.LabelSelectorConfig(multiple=True)
                    ),
                    vol.Optional(
                        CONF_EXCLUDED_AREAS,
                        default=options.get(CONF_EXCLUDED_AREAS, []),
                    ): selector.AreaSelector(
                        selector.AreaSelectorConfig(multiple=True)
                    ),
                    vol.Optional(
                        CONF_EXCLUDED_INTEGRATIONS,
                        default=options.get(
                            CONF_EXCLUDED_INTEGRATIONS, []
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=integration_domains,
                            multiple=True,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The notification backbone, mirrored to Sentinel Notify.

        Two target lists: high-priority targets bypass Do Not Disturb
        and pierce quiet hours; normal-priority targets get standard
        delivery and are held during quiet hours. Either may be empty.
        A target in both is normalized to high on save, so the Step 5
        engine inherits the rule rather than re-deriving it. Also the
        persistent card, the quiet-hours window, and the daily
        reminder mode and time.

        Everything here is stored and inert until the engine reads it.
        """
        if user_input is not None:
            high = list(user_input.get(CONF_HIGH_PRIORITY_TARGETS, []))
            normal = [
                target
                for target in user_input.get(
                    CONF_NORMAL_PRIORITY_TARGETS, []
                )
                if target not in high
            ]
            user_input[CONF_NORMAL_PRIORITY_TARGETS] = normal
            return self.async_create_entry(
                data={**self.config_entry.options, **user_input}
            )
        options = self.config_entry.options
        discovered = _discover_notify_targets(self.hass)

        def target_selector() -> selector.SelectSelector:
            """A multi-select of discovered targets, typing allowed."""
            return selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=discovered,
                    multiple=True,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )

        return self.async_show_form(
            step_id="notifications",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_HIGH_PRIORITY_TARGETS,
                        default=options.get(
                            CONF_HIGH_PRIORITY_TARGETS, []
                        ),
                    ): target_selector(),
                    vol.Optional(
                        CONF_NORMAL_PRIORITY_TARGETS,
                        default=options.get(
                            CONF_NORMAL_PRIORITY_TARGETS, []
                        ),
                    ): target_selector(),
                    vol.Required(
                        CONF_PERSISTENT_ENABLED,
                        default=options.get(
                            CONF_PERSISTENT_ENABLED,
                            DEFAULT_PERSISTENT_ENABLED,
                        ),
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_QUIET_ENABLED,
                        default=options.get(
                            CONF_QUIET_ENABLED, DEFAULT_QUIET_ENABLED
                        ),
                    ): selector.BooleanSelector(),
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
                        CONF_REMINDER_MODE,
                        default=options.get(
                            CONF_REMINDER_MODE, DEFAULT_REMINDER_MODE
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                REMINDER_MODE_NONE,
                                REMINDER_MODE_OVERNIGHT,
                                REMINDER_MODE_DAILY,
                            ],
                            translation_key="reminder_mode",
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_REMINDER_TIME,
                        default=options.get(
                            CONF_REMINDER_TIME, DEFAULT_REMINDER_TIME
                        ),
                    ): selector.TimeSelector(),
                }
            ),
        )
