# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
#   Version: 0.3.11 (2026-07-16)

"""Config and options flows for the Device Sentinel integration.

The config flow is single instance, zero questions: the manifest's
single_config_entry flag makes Home Assistant itself refuse a second
entry, so the flow carries no duplicate guard of its own.

The options flow is a menu that branches to each configuration
surface, so it grows without becoming one long form. The menu runs
in the order a new installation is best worked through:

- Exclusions: what is never judged or reported. It leads because
  narrowing the field costs nothing to undo and every later family
  inherits the result.
- Battery: the low threshold and the battery-only excludes. The
  threshold is a UI knob rather than a constant because batteries
  drift slowly, and proving detection live means sliding the
  threshold above a real cell's level and watching it flag.
- Notifications: the backbone of the Step 5 engine, built ahead of
  it because the configuration surface is self-contained and touches
  no detection path. Discovered notify targets, the quiet-hours
  window, the daily-reminder time, and whether high-priority items
  pierce quiet hours. These settings are stored and inert until the
  engine reads them.

Both exclude screens run one priority ladder, broadest first:
integration, label, device, entity (Battery stops at device). Each
picker lists only what the kinds above it have not already caught,
and a pick a broader kind covers is pruned from stored options on
save. Pruning is silent and permanent by ruling: the screens warn
about it up front, and undoing a broad exclusion does not restore
the narrower picks it erased.

Each step's description carries a wiki_link placeholder rather than
a literal URL, because hassfest rejects URLs in the translation
files and asks for description placeholders instead.
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
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_BATTERY_EXCLUDED_INTEGRATIONS,
    CONF_BATTERY_EXCLUDED_LABELS,
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
    WIKI_LINK_MARKDOWN,
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


def _devices_covered_by(
    rows: list[dict[str, Any]],
    excluded_integrations: list[str],
    excluded_labels: list[str],
) -> set[str]:
    """Return the device ids an integration or label exclusion already
    catches.

    Coverage is positive only: a device is named here because a broader
    exclusion demonstrably reaches it. An id we cannot account for, a
    device deleted or belonging to an integration that has not loaded
    yet, is never named, so a pick can only be pruned on proof rather
    than on absence.
    """
    labels = set(excluded_labels)
    integrations = set(excluded_integrations)
    return {
        row["device_id"]
        for row in rows
        if row["integration"] in integrations or (row["labels"] & labels)
    }


def _entities_covered_by(
    rows: list[dict[str, Any]],
    excluded_integrations: list[str],
    excluded_labels: list[str],
    excluded_devices: list[str],
) -> set[str]:
    """Return the entity ids a broader exclusion already catches.

    Same positive-coverage rule as the device pass: an entity is named
    only because its integration, one of its labels, or its device is
    excluded.
    """
    labels = set(excluded_labels)
    integrations = set(excluded_integrations)
    devices = set(excluded_devices)
    return {
        row["entity_id"]
        for row in rows
        if row["integration"] in integrations
        or (row["labels"] & labels)
        or row["device_id"] in devices
    }


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
            menu_options=["exclusions", "battery", "notifications"],
        )

    async def async_step_battery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The battery section: the threshold and the battery-only
        excludes, together, the family pattern (a family's knobs and
        its excludes share one screen).

        The excludes run the same priority ladder as the global
        surface, broadest first: integration, label, device. There is
        no entity kind here by ruling, because battery judgment is
        device-level and an entity pick could be dodged by a battery
        re-election.

        The device picker is populated from the detected batteries,
        the pick-from-detected ruling: what you see listed is exactly
        what is being judged, named by device with its elected entity
        shown.
        """
        battery_rows = self.config_entry.runtime_data.detected_batteries
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    **self._pruned_battery_input(user_input, battery_rows),
                }
            )
        options = self.config_entry.options
        covered = _devices_covered_by(
            battery_rows,
            options.get(CONF_BATTERY_EXCLUDED_INTEGRATIONS, []),
            options.get(CONF_BATTERY_EXCLUDED_LABELS, []),
        )
        # The list only ever shows what still needs a decision: a
        # device an integration or label exclude already reaches is
        # gone from it. Options forms are static once rendered, so
        # the filter applies at each open, one save behind the tick.
        device_options = [
            selector.SelectOptionDict(
                value=row["device_id"],
                label=f"{row['name']} ({row['entity_id']})",
            )
            for row in battery_rows
            if row["device_id"] not in covered
        ]
        integration_options = sorted(
            {row["integration"] for row in battery_rows}
        )
        return self.async_show_form(
            step_id="battery",
            description_placeholders={"wiki_link": WIKI_LINK_MARKDOWN},
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOW_THRESHOLD,
                        default=options.get(
                            CONF_LOW_THRESHOLD, DEFAULT_LOW_THRESHOLD
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=99,
                            step=1,
                            unit_of_measurement="%",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_BATTERY_EXCLUDED_INTEGRATIONS,
                        default=options.get(
                            CONF_BATTERY_EXCLUDED_INTEGRATIONS, []
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=integration_options,
                            multiple=True,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_BATTERY_EXCLUDED_LABELS,
                        default=options.get(
                            CONF_BATTERY_EXCLUDED_LABELS, []
                        ),
                    ): selector.LabelSelector(
                        selector.LabelSelectorConfig(multiple=True)
                    ),
                    vol.Optional(
                        CONF_BATTERY_EXCLUDED_DEVICES,
                        default=[
                            device_id
                            for device_id in options.get(
                                CONF_BATTERY_EXCLUDED_DEVICES, []
                            )
                            if device_id not in covered
                        ],
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=device_options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    @staticmethod
    def _pruned_battery_input(
        user_input: dict[str, Any], battery_rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Drop device picks the same save's broader excludes cover.

        Pruning happens here rather than being left to the frontend so
        that the result is deterministic: a superseded pick is gone
        because this code removed it, not because a hidden field
        happened not to round-trip.
        """
        pruned = dict(user_input)
        covered = _devices_covered_by(
            battery_rows,
            pruned.get(CONF_BATTERY_EXCLUDED_INTEGRATIONS, []),
            pruned.get(CONF_BATTERY_EXCLUDED_LABELS, []),
        )
        pruned[CONF_BATTERY_EXCLUDED_DEVICES] = [
            device_id
            for device_id in pruned.get(CONF_BATTERY_EXCLUDED_DEVICES, [])
            if device_id not in covered
        ]
        return pruned

    async def async_step_exclusions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The exclude surface: four selectors, one list, every family.

        Exclusion suppresses judgment, not observation (a ruled
        decision): excluded devices and entities keep their clocks,
        statistics, and vouching, so undo is instant and the rhythm
        history carries no holes. Changes apply live on save through
        the options update listener, no restart.

        The four kinds are a priority ladder, broadest first:
        integration, label, device, entity. Each picker lists only
        what the ones above it have not already caught, and a pick the
        ladder supersedes is pruned on save rather than lingering
        invisibly under a parent.

        The integration picker is populated live from the config
        entries present on this system; an integration exclude
        catches only devices that integration owns, never multi-homed
        hardware it merely sees.

        The label picker is deliberately unfiltered. A label belongs
        to no integration, and a label with no bearers yet is exactly
        the one worth picking early, so filtering it would hide the
        case it is for.
        """
        coordinator = self.config_entry.runtime_data
        device_rows = coordinator.watched_device_rows
        entity_rows = coordinator.watched_entity_rows
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    **self._pruned_exclusion_input(
                        user_input, device_rows, entity_rows
                    ),
                }
            )
        options = self.config_entry.options
        integration_domains = sorted(
            {
                entry.domain
                for entry in self.hass.config_entries.async_entries()
                if entry.domain != DOMAIN
            }
        )
        excluded_integrations = options.get(CONF_EXCLUDED_INTEGRATIONS, [])
        excluded_labels = options.get(CONF_EXCLUDED_LABELS, [])
        covered_devices = _devices_covered_by(
            device_rows, excluded_integrations, excluded_labels
        )
        surviving_device_picks = [
            device_id
            for device_id in options.get(CONF_EXCLUDED_DEVICES, [])
            if device_id not in covered_devices
        ]
        covered_entities = _entities_covered_by(
            entity_rows,
            excluded_integrations,
            excluded_labels,
            surviving_device_picks,
        )
        device_options = [
            selector.SelectOptionDict(
                value=row["device_id"],
                label=f"{row['name']} ({row['integration']})",
            )
            for row in device_rows
            if row["device_id"] not in covered_devices
        ]
        return self.async_show_form(
            step_id="exclusions",
            description_placeholders={"wiki_link": WIKI_LINK_MARKDOWN},
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_EXCLUDED_INTEGRATIONS,
                        default=excluded_integrations,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=integration_domains,
                            multiple=True,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_EXCLUDED_LABELS, default=excluded_labels
                    ): selector.LabelSelector(
                        selector.LabelSelectorConfig(multiple=True)
                    ),
                    vol.Optional(
                        CONF_EXCLUDED_DEVICES,
                        default=surviving_device_picks,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=device_options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_EXCLUDED_ENTITIES,
                        default=[
                            entity_id
                            for entity_id in options.get(
                                CONF_EXCLUDED_ENTITIES, []
                            )
                            if entity_id not in covered_entities
                        ],
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            multiple=True,
                            exclude_entities=sorted(covered_entities),
                        )
                    ),
                }
            ),
        )

    @staticmethod
    def _pruned_exclusion_input(
        user_input: dict[str, Any],
        device_rows: list[dict[str, Any]],
        entity_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Drop device and entity picks the same save's broader
        excludes cover, top of the ladder downward.

        Devices are pruned first, then entities are judged against the
        pruned device list, so one save settles the whole ladder and
        no pick survives under a parent that hides it.
        """
        pruned = dict(user_input)
        excluded_integrations = pruned.get(CONF_EXCLUDED_INTEGRATIONS, [])
        excluded_labels = pruned.get(CONF_EXCLUDED_LABELS, [])
        covered_devices = _devices_covered_by(
            device_rows, excluded_integrations, excluded_labels
        )
        pruned[CONF_EXCLUDED_DEVICES] = [
            device_id
            for device_id in pruned.get(CONF_EXCLUDED_DEVICES, [])
            if device_id not in covered_devices
        ]
        covered_entities = _entities_covered_by(
            entity_rows,
            excluded_integrations,
            excluded_labels,
            pruned[CONF_EXCLUDED_DEVICES],
        )
        pruned[CONF_EXCLUDED_ENTITIES] = [
            entity_id
            for entity_id in pruned.get(CONF_EXCLUDED_ENTITIES, [])
            if entity_id not in covered_entities
        ]
        return pruned

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
            description_placeholders={"wiki_link": WIKI_LINK_MARKDOWN},
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
