# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: config_flow.py, Version: 0.13.2 (2026-08-13)

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
files and asks for description placeholders instead. Every step
supplies its own link, so Full documentation lands on the page for
the screen the reader is standing on rather than on the wiki's
front door for them to navigate from.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector

from .const import (
    BATTERY_DAYS_MAX,
    BATTERY_DAYS_MIN,
    COALESCE_MINUTES_MAX,
    COALESCE_MINUTES_MIN,
    CONF_BATTERY_DAYS,
    CONF_BATTERY_EXCLUDED_DEVICES,
    CONF_BATTERY_EXCLUDED_INTEGRATIONS,
    CONF_BATTERY_EXCLUDED_LABELS,
    CONF_BRIEF_TARGETS,
    CONF_COALESCE_MINUTES,
    CONF_EPISODE_SHARE,
    CONF_EXCLUDED_DEVICES,
    CONF_EXCLUDED_INTEGRATIONS,
    CONF_IGNORED_INTEGRATIONS,
    CONF_EXCLUDED_LABELS,
    CONF_FREEZE_DELTA_HIGH,
    CONF_FREEZE_DELTA_LOW,
    CONF_FREEZE_EXCLUDED_DEVICES,
    CONF_FREEZE_EXCLUDED_INTEGRATIONS,
    CONF_FREEZE_EXCLUDED_LABELS,
    CONF_HIGH_PRIORITY_TARGETS,
    CONF_LOW_THRESHOLD,
    CONF_MAINTENANCE_MINUTES,
    CONF_NORMAL_PRIORITY_TARGETS,
    CONF_PERSISTENT_ENABLED,
    CONF_QUIET_ENABLED,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_REMINDER_MODE,
    CONF_REMINDER_TIME,
    CONF_RETENTION_DAYS,
    CONF_SETTLE_SHARE,
    CONF_SIGNAL_ANOMALY_TRIM,
    CONF_SIGNAL_EXCLUDED_DEVICES,
    CONF_SIGNAL_EXCLUDED_INTEGRATIONS,
    CONF_SIGNAL_EXCLUDED_LABELS,
    CONF_SIGNAL_LIFT,
    CONF_SIGNAL_MARGIN,
    CONF_SIGNAL_RED,
    CONF_TAINT_FLOOR,
    CONF_TAINT_SHARE,
    DEFAULT_BATTERY_DAYS,
    DEFAULT_COALESCE_MINUTES,
    DEFAULT_EPISODE_SHARE_PCT,
    DEFAULT_IGNORED_INTEGRATIONS,
    DEFAULT_FREEZE_DELTA_HIGH_HR,
    DEFAULT_FREEZE_DELTA_LOW_MIN,
    DEFAULT_LOW_THRESHOLD,
    DEFAULT_MAINTENANCE_MINUTES,
    DEFAULT_PERSISTENT_ENABLED,
    DEFAULT_QUIET_ENABLED,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    DEFAULT_REMINDER_MODE,
    DEFAULT_REMINDER_TIME,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_SETTLE_SHARE_PCT,
    DEFAULT_SIGNAL_ANOMALY_TRIM,
    DEFAULT_SIGNAL_LIFT,
    DEFAULT_SIGNAL_MARGIN,
    DEFAULT_SIGNAL_RED,
    DEFAULT_TAINT_FLOOR_MINUTES,
    DEFAULT_TAINT_SHARE_PCT,
    DOMAIN,
    FREEZE_DELTA_HIGH_HR_MAX,
    FREEZE_DELTA_HIGH_HR_MIN,
    FREEZE_DELTA_LOW_MIN_MAX,
    FREEZE_DELTA_LOW_MIN_MIN,
    LOW_THRESHOLD_MAX,
    LOW_THRESHOLD_MIN,
    MAINTENANCE_MINUTES_MAX,
    MAINTENANCE_MINUTES_MIN,
    MAINTENANCE_MINUTES_STEP,
    NOTIFY_DOMAIN,
    PERSISTENT_TARGET,
    REMINDER_MODE_DAILY,
    REMINDER_MODE_NONE,
    REMINDER_MODE_OVERNIGHT,
    RETENTION_DAYS_MAX,
    RETENTION_DAYS_MIN,
    RETENTION_DAYS_STEP,
    SHARE_PCT_MAX,
    SHARE_PCT_MIN,
    SHARE_PCT_STEP,
    SIGNAL_ANOMALY_TRIM_MAX,
    SIGNAL_ANOMALY_TRIM_MIN,
    SIGNAL_LIFT_MAX,
    SIGNAL_LIFT_MIN,
    SIGNAL_LIFT_STEP,
    SIGNAL_MARGIN_MAX,
    SIGNAL_MARGIN_MIN,
    SIGNAL_RED_MAX,
    SIGNAL_RED_MIN,
    TAINT_FLOOR_MINUTES_MAX,
    TAINT_FLOOR_MINUTES_MIN,
    WIKI_LINK_ADVANCED,
    WIKI_LINK_BATTERY,
    WIKI_LINK_EXCLUSIONS,
    WIKI_LINK_FREEZE,
    WIKI_LINK_HOME,
    WIKI_LINK_NOTIFICATIONS,
    WIKI_LINK_SIGNAL,
)

# The notify domain exposes one service per target; the persistent
# notification is always available. These are what the engine will
# eventually call, discovered live so the picker shows real targets.


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


def _device_options(
    rows: list[dict[str, Any]],
    picks: list[str],
    covered: set[str],
    label_for: Callable[[dict[str, Any]], str],
    dev_reg: dr.DeviceRegistry,
) -> list[selector.SelectOptionDict]:
    """Return a picker's options, including any pick the rows lack.

    A screen must be able to show every value it holds. Each picker
    builds from a narrower set than the registry: the battery screen
    lists devices that have a battery entity, the signal screen those
    that report a signal, and both drop a device the moment that
    entity is disabled. A pick left holding such a device seeded the
    form with a value its own selector rejected, and the save failed
    for the whole screen rather than the one pick, so no exclusion of
    any kind could be changed while one such id sat in the options.

    So a pick whose device is still in the registry is offered back,
    named, and the person decides. Disabling an entity for an
    afternoon is a normal thing to do and must not quietly cost the
    exclusion that goes with it. A pick whose device the registry no
    longer holds is not offered here at all: it is pruned on save,
    which is the one case where absence is proof rather than
    inference (ruling #45).
    """
    options = [
        selector.SelectOptionDict(
            value=row["device_id"], label=label_for(row)
        )
        for row in rows
        if row["device_id"] not in covered
    ]
    listed = {option["value"] for option in options}
    for device_id in picks:
        if device_id in listed or device_id in covered:
            continue
        device = dev_reg.async_get(device_id)
        if device is None:
            continue
        name = device.name_by_user or device.name or device_id
        options.append(
            selector.SelectOptionDict(
                value=device_id, label=f"{name} (not currently listed)"
            )
        )
    return options


def _surviving_picks(
    picks: list[str], covered: set[str], dev_reg: dr.DeviceRegistry
) -> list[str]:
    """Return the picks worth keeping: covered ones go, deleted ones go.

    Ruling #45 prunes on proof and never on absence, and a device
    missing from the registry is proof: the registry holds every
    device of every config entry, loaded or not, enabled or not, so
    an id it cannot find belongs to hardware that has been removed.
    Its name went with it, which is why keeping the pick helps nobody:
    it can only ever be shown as a raw id.
    """
    return [
        device_id
        for device_id in picks
        if device_id not in covered
        and dev_reg.async_get(device_id) is not None
    ]


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


def _globally_excluded(
    rows: list[dict[str, Any]], options: dict[str, Any]
) -> set[str]:
    """Return the device ids the global exclude already reaches.

    The section pickers subtract these: a globally excluded device is
    judged by nothing, so offering to also exclude it from a section
    would be redundant. Covers the global integration and label
    ladder plus the explicit global device list.
    """
    covered = _devices_covered_by(
        rows,
        options.get(CONF_EXCLUDED_INTEGRATIONS, []),
        options.get(CONF_EXCLUDED_LABELS, []),
    )
    return covered | set(options.get(CONF_EXCLUDED_DEVICES, []))



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
        """Show the top-level menu.

        Notifications leads because it is the one section a new
        installation must visit for alerts to reach a phone; the
        description says so and sends people here first. Only
        sections with a screen are named here.
        """
        return self.async_show_menu(
            step_id="init",
            description_placeholders={"wiki_link": WIKI_LINK_HOME},
            menu_options=[
                "notifications",
                "exclusions",
                "battery",
                "signal",
                "freeze",
                "advanced",
            ],
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
                    **self._pruned_battery_input(
                        user_input, battery_rows, dr.async_get(self.hass)
                    ),
                }
            )
        options = self.config_entry.options
        covered = _devices_covered_by(
            battery_rows,
            options.get(CONF_BATTERY_EXCLUDED_INTEGRATIONS, []),
            options.get(CONF_BATTERY_EXCLUDED_LABELS, []),
        )
        # Also drop devices the global exclude already reaches: a
        # globally excluded device is judged by nothing, so offering
        # to battery-exclude it is redundant.
        globally = _globally_excluded(battery_rows, options)
        covered = covered | globally
        # The list only ever shows what still needs a decision: a
        # device an integration or label exclude already reaches is
        # gone from it. Options forms are static once rendered, so
        # the filter applies at each open, one save behind the tick.
        dev_reg = dr.async_get(self.hass)
        device_options = _device_options(
            battery_rows,
            options.get(CONF_BATTERY_EXCLUDED_DEVICES, []),
            covered,
            lambda row: f"{row['name']} ({row['entity_id']})",
            dev_reg,
        )
        integration_options = sorted(
            {
                row["integration"]
                for row in battery_rows
                if row["device_id"] not in globally
            }
        )
        return self.async_show_form(
            step_id="battery",
            description_placeholders={"wiki_link": WIKI_LINK_BATTERY},
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOW_THRESHOLD,
                        default=options.get(
                            CONF_LOW_THRESHOLD, DEFAULT_LOW_THRESHOLD
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=LOW_THRESHOLD_MIN,
                            max=LOW_THRESHOLD_MAX,
                            step=1,
                            unit_of_measurement="%",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    # The second question the screen answers. The
                    # threshold says which cells are low; this says
                    # how far ahead a falling one is called out
                    # (ruling #197). It sits beside the threshold
                    # because they are one decision made twice, and
                    # a person setting one should meet the other.
                    vol.Optional(
                        CONF_BATTERY_DAYS,
                        default=options.get(
                            CONF_BATTERY_DAYS, DEFAULT_BATTERY_DAYS
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=BATTERY_DAYS_MIN,
                            max=BATTERY_DAYS_MAX,
                            step=1,
                            unit_of_measurement="days",
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
                        default=_surviving_picks(
                            options.get(CONF_BATTERY_EXCLUDED_DEVICES, []),
                            covered,
                            dev_reg,
                        ),
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
        user_input: dict[str, Any],
        battery_rows: list[dict[str, Any]],
        dev_reg: dr.DeviceRegistry,
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
        pruned[CONF_BATTERY_EXCLUDED_DEVICES] = _surviving_picks(
            pruned.get(CONF_BATTERY_EXCLUDED_DEVICES, []), covered, dev_reg
        )
        return pruned

    async def async_step_signal(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The signal section: sensitivity and the signal-only
        excludes, together, the family pattern.

        The sensitivity is a whole-fleet setting, one slider for LQI
        and RSSI alike, and it applies to readings going forward
        only: time already counted against the old floor stays
        counted, so its true effect shows after a full clean day.
        That forward-only nature is why it lives here rather than as
        a live entity, which would promise an immediacy the setting
        cannot deliver.

        The excludes run the same priority ladder as battery,
        broadest first: integration, label, device. Exclusion
        suppresses judgment, not observation: an excluded device
        keeps recording, so re-including it is instant and arrives
        with history.
        """
        signal_rows = self.config_entry.runtime_data.detected_signals
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    **self._pruned_signal_input(
                        user_input, signal_rows, dr.async_get(self.hass)
                    ),
                }
            )
        options = self.config_entry.options
        covered = _devices_covered_by(
            signal_rows,
            options.get(CONF_SIGNAL_EXCLUDED_INTEGRATIONS, []),
            options.get(CONF_SIGNAL_EXCLUDED_LABELS, []),
        )
        globally = _globally_excluded(signal_rows, options)
        covered = covered | globally
        dev_reg = dr.async_get(self.hass)
        device_options = _device_options(
            signal_rows,
            options.get(CONF_SIGNAL_EXCLUDED_DEVICES, []),
            covered,
            lambda row: f"{row['name']} ({row['integration']})",
            dev_reg,
        )
        integration_options = sorted(
            {
                row["integration"]
                for row in signal_rows
                if row["device_id"] not in globally
            }
        )
        return self.async_show_form(
            step_id="signal",
            description_placeholders={"wiki_link": WIKI_LINK_SIGNAL},
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SIGNAL_MARGIN,
                        default=options.get(
                            CONF_SIGNAL_MARGIN, DEFAULT_SIGNAL_MARGIN
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=SIGNAL_MARGIN_MIN,
                            max=SIGNAL_MARGIN_MAX,
                            step=1,
                            unit_of_measurement="%",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_SIGNAL_LIFT,
                        default=options.get(
                            CONF_SIGNAL_LIFT, DEFAULT_SIGNAL_LIFT
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=SIGNAL_LIFT_MIN,
                            max=SIGNAL_LIFT_MAX,
                            step=SIGNAL_LIFT_STEP,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_SIGNAL_RED,
                        default=options.get(
                            CONF_SIGNAL_RED, DEFAULT_SIGNAL_RED
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=SIGNAL_RED_MIN,
                            max=SIGNAL_RED_MAX,
                            step=1,
                            unit_of_measurement="%",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_SIGNAL_ANOMALY_TRIM,
                        default=options.get(
                            CONF_SIGNAL_ANOMALY_TRIM,
                            DEFAULT_SIGNAL_ANOMALY_TRIM,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=SIGNAL_ANOMALY_TRIM_MIN,
                            max=SIGNAL_ANOMALY_TRIM_MAX,
                            step=1,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_SIGNAL_EXCLUDED_INTEGRATIONS,
                        default=options.get(
                            CONF_SIGNAL_EXCLUDED_INTEGRATIONS, []
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
                        CONF_SIGNAL_EXCLUDED_LABELS,
                        default=options.get(
                            CONF_SIGNAL_EXCLUDED_LABELS, []
                        ),
                    ): selector.LabelSelector(
                        selector.LabelSelectorConfig(multiple=True)
                    ),
                    vol.Optional(
                        CONF_SIGNAL_EXCLUDED_DEVICES,
                        default=_surviving_picks(
                            options.get(CONF_SIGNAL_EXCLUDED_DEVICES, []),
                            covered,
                            dev_reg,
                        ),
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
    def _pruned_signal_input(
        user_input: dict[str, Any],
        signal_rows: list[dict[str, Any]],
        dev_reg: dr.DeviceRegistry,
    ) -> dict[str, Any]:
        """Drop device picks the same save's broader excludes cover,
        and round the slider to the integer it is. Same determinism
        rule as battery: a superseded pick is gone because this code
        removed it."""
        pruned = dict(user_input)
        if CONF_SIGNAL_ANOMALY_TRIM in pruned:
            pruned[CONF_SIGNAL_ANOMALY_TRIM] = int(
                pruned[CONF_SIGNAL_ANOMALY_TRIM]
            )
        if CONF_SIGNAL_MARGIN in pruned:
            pruned[CONF_SIGNAL_MARGIN] = int(pruned[CONF_SIGNAL_MARGIN])
        if CONF_SIGNAL_RED in pruned:
            pruned[CONF_SIGNAL_RED] = int(pruned[CONF_SIGNAL_RED])
        if CONF_SIGNAL_LIFT in pruned:
            pruned[CONF_SIGNAL_LIFT] = float(pruned[CONF_SIGNAL_LIFT])
        covered = _devices_covered_by(
            signal_rows,
            pruned.get(CONF_SIGNAL_EXCLUDED_INTEGRATIONS, []),
            pruned.get(CONF_SIGNAL_EXCLUDED_LABELS, []),
        )
        pruned[CONF_SIGNAL_EXCLUDED_DEVICES] = _surviving_picks(
            pruned.get(CONF_SIGNAL_EXCLUDED_DEVICES, []), covered, dev_reg
        )
        return pruned

    async def async_step_freeze(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The freeze section: the two margin deltas.

        A device is called frozen when it goes silent past its own
        learned rhythm plus a grace margin. The margin is not a flat
        multiple, because rhythms span seconds to hours and no single
        multiple fits both ends; it follows a curve the two deltas
        shape, generous where the rhythm is fast and tight where it
        is slow (ruling #85). delta-low is the grace a fast device
        gets, the
        floor in minutes, so a device reporting every few seconds is
        not called dead for missing a couple of reports. delta-high
        is the grace a slow device gets, the ceiling in hours, so the
        slowest devices are still caught in a bounded time. The two
        reshape the whole curve between them, and they are the hard
        floor and ceiling on the grace.

        This is a considered setting, not a daily knob, which is why
        it lives on its own screen. The learned rhythm underneath is
        never touched here; the deltas tune only the patience.

        The excludes run the same broad-to-narrow ladder as battery
        and signal: integration, label, device. A freeze-excluded
        device keeps its clock and rhythm and is simply never given a
        freeze verdict, so a device intermittent by nature can be
        silenced here without being hidden everywhere.
        """
        device_rows = self.config_entry.runtime_data.watched_device_rows
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    **self._pruned_freeze_input(
                        user_input, device_rows, dr.async_get(self.hass)
                    ),
                }
            )
        options = self.config_entry.options
        covered = _devices_covered_by(
            device_rows,
            options.get(CONF_FREEZE_EXCLUDED_INTEGRATIONS, []),
            options.get(CONF_FREEZE_EXCLUDED_LABELS, []),
        )
        globally = _globally_excluded(device_rows, options)
        covered = covered | globally
        dev_reg = dr.async_get(self.hass)
        device_options = _device_options(
            device_rows,
            options.get(CONF_FREEZE_EXCLUDED_DEVICES, []),
            covered,
            lambda row: f"{row['name']} ({row['integration']})",
            dev_reg,
        )
        integration_options = sorted(
            {
                row["integration"]
                for row in device_rows
                if row["device_id"] not in globally
            }
        )
        return self.async_show_form(
            step_id="freeze",
            description_placeholders={"wiki_link": WIKI_LINK_FREEZE},
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_FREEZE_DELTA_LOW,
                        default=options.get(
                            CONF_FREEZE_DELTA_LOW,
                            DEFAULT_FREEZE_DELTA_LOW_MIN,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=FREEZE_DELTA_LOW_MIN_MIN,
                            max=FREEZE_DELTA_LOW_MIN_MAX,
                            step=1,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_FREEZE_DELTA_HIGH,
                        default=options.get(
                            CONF_FREEZE_DELTA_HIGH,
                            DEFAULT_FREEZE_DELTA_HIGH_HR,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=FREEZE_DELTA_HIGH_HR_MIN,
                            max=FREEZE_DELTA_HIGH_HR_MAX,
                            step=1,
                            unit_of_measurement="h",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_FREEZE_EXCLUDED_INTEGRATIONS,
                        default=options.get(
                            CONF_FREEZE_EXCLUDED_INTEGRATIONS, []
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
                        CONF_FREEZE_EXCLUDED_LABELS,
                        default=options.get(
                            CONF_FREEZE_EXCLUDED_LABELS, []
                        ),
                    ): selector.LabelSelector(
                        selector.LabelSelectorConfig(multiple=True)
                    ),
                    vol.Optional(
                        CONF_FREEZE_EXCLUDED_DEVICES,
                        default=_surviving_picks(
                            options.get(CONF_FREEZE_EXCLUDED_DEVICES, []),
                            covered,
                            dev_reg,
                        ),
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
    def _pruned_freeze_input(
        user_input: dict[str, Any],
        device_rows: list[dict[str, Any]],
        dev_reg: dr.DeviceRegistry,
    ) -> dict[str, Any]:
        """Round the two deltas and drop device picks a broader freeze
        exclude already covers, the same determinism rule as signal
        and battery."""
        pruned = dict(user_input)
        pruned[CONF_FREEZE_DELTA_LOW] = int(pruned[CONF_FREEZE_DELTA_LOW])
        pruned[CONF_FREEZE_DELTA_HIGH] = int(pruned[CONF_FREEZE_DELTA_HIGH])
        covered = _devices_covered_by(
            device_rows,
            pruned.get(CONF_FREEZE_EXCLUDED_INTEGRATIONS, []),
            pruned.get(CONF_FREEZE_EXCLUDED_LABELS, []),
        )
        pruned[CONF_FREEZE_EXCLUDED_DEVICES] = _surviving_picks(
            pruned.get(CONF_FREEZE_EXCLUDED_DEVICES, []), covered, dev_reg
        )
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
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    **self._pruned_exclusion_input(
                        user_input, device_rows, dr.async_get(self.hass)
                    ),
                }
            )
        options = self.config_entry.options
        # Offer only integrations that own a watched device. An
        # integration whose devices are all service-type was never
        # watched, so excluding it would do nothing; listing every
        # integration in Home Assistant buried the real ones under
        # service entries. This matches the battery and signal steps,
        # which already build their picker from their watched rows.
        integration_domains = sorted(
            {row["integration"] for row in device_rows}
        )
        excluded_integrations = options.get(CONF_EXCLUDED_INTEGRATIONS, [])
        excluded_labels = options.get(CONF_EXCLUDED_LABELS, [])
        covered_devices = _devices_covered_by(
            device_rows, excluded_integrations, excluded_labels
        )
        dev_reg = dr.async_get(self.hass)
        surviving_device_picks = _surviving_picks(
            options.get(CONF_EXCLUDED_DEVICES, []),
            covered_devices,
            dev_reg,
        )
        device_options = _device_options(
            device_rows,
            options.get(CONF_EXCLUDED_DEVICES, []),
            covered_devices,
            lambda row: f"{row['name']} ({row['integration']})",
            dev_reg,
        )
        return self.async_show_form(
            step_id="exclusions",
            description_placeholders={"wiki_link": WIKI_LINK_EXCLUSIONS},
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
                }
            ),
        )

    @staticmethod
    def _pruned_exclusion_input(
        user_input: dict[str, Any],
        device_rows: list[dict[str, Any]],
        dev_reg: dr.DeviceRegistry,
    ) -> dict[str, Any]:
        """Drop device picks the same save's broader excludes cover.

        A device an integration or label exclude already reaches is
        removed from the device list, so one save settles the ladder
        and no pick survives under a parent that hides it.
        """
        pruned = dict(user_input)
        excluded_integrations = pruned.get(CONF_EXCLUDED_INTEGRATIONS, [])
        excluded_labels = pruned.get(CONF_EXCLUDED_LABELS, [])
        covered_devices = _devices_covered_by(
            device_rows, excluded_integrations, excluded_labels
        )
        pruned[CONF_EXCLUDED_DEVICES] = _surviving_picks(
            pruned.get(CONF_EXCLUDED_DEVICES, []), covered_devices, dev_reg
        )
        return pruned

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Who hears about a problem, and when.

        Three sections on one screen: the instant messages, the
        quiet window, and the daily brief. They sit together because
        they are all about who hears, which is a different question
        from how a detector is tuned, and tuning stays on its own
        detector's screen (ruling #117). High-priority targets get a
        message when a device develops a problem and the brief with
        its history; normal-priority targets get the brief alone. A
        target in both is normalized to high on save, so the engine
        inherits the rule rather than re-deriving it. The brief's own
        target list carries the whole document, which is why it is
        separate: the payload differs, not the urgency.

        Quiet hours suppress both tiers; nothing pierces, not even a
        high-priority message, because an event inside quiet hours is
        dropped rather than queued and the morning brief carries it
        instead (ruling #111).
        """
        if user_input is not None:
            flat: dict[str, Any] = {}
            for key, value in user_input.items():
                if isinstance(value, dict):
                    flat.update(value)
                else:
                    flat[key] = value
            high = list(flat.get(CONF_HIGH_PRIORITY_TARGETS, []))
            flat[CONF_NORMAL_PRIORITY_TARGETS] = [
                target
                for target in flat.get(CONF_NORMAL_PRIORITY_TARGETS, [])
                if target not in high
            ]
            return self.async_create_entry(
                data={**self.config_entry.options, **flat}
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

        instant_section = vol.Schema(
            {
                vol.Optional(
                    CONF_HIGH_PRIORITY_TARGETS,
                    default=options.get(CONF_HIGH_PRIORITY_TARGETS, []),
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
            }
        )
        quiet_section = vol.Schema(
            {
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
                    default=options.get(CONF_QUIET_END, DEFAULT_QUIET_END),
                ): selector.TimeSelector(),
            }
        )
        brief_section = vol.Schema(
            {
                vol.Required(
                    CONF_REMINDER_TIME,
                    default=options.get(
                        CONF_REMINDER_TIME, DEFAULT_REMINDER_TIME
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
                            REMINDER_MODE_DAILY,
                            REMINDER_MODE_OVERNIGHT,
                            REMINDER_MODE_NONE,
                        ],
                        translation_key="reminder_mode",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_BRIEF_TARGETS,
                    default=options.get(CONF_BRIEF_TARGETS, []),
                ): target_selector(),
            }
        )
        return self.async_show_form(
            step_id="notifications",
            description_placeholders={"wiki_link": WIKI_LINK_NOTIFICATIONS},
            data_schema=vol.Schema(
                {
                    vol.Required("instant"): section(instant_section, {}),
                    vol.Required("quiet"): section(
                        quiet_section, {"collapsed": True}
                    ),
                    vol.Required("brief"): section(
                        brief_section, {"collapsed": True}
                    ),
                }
            ),
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Settings a person may change and most never will.

        Cross-cutting values live here while anything that tunes one
        detector stays on that detector's own screen, where a person
        adjusting it expects to find it (ruling #117).

        Each is a share of something the device already earned, or a
        plain interval, so no value here can produce a nonsensical
        result: the bands are enforced by the selectors and clamped
        again where they are read. One sentence each on the screen and
        the reasoning on the wiki page, per the standing rule that
        configuration says what a setting does and the wiki says why.
        """
        if user_input is not None:
            return self.async_create_entry(
                data={**self.config_entry.options, **user_input}
            )
        options = self.config_entry.options
        ignored = list(
            options.get(
                CONF_IGNORED_INTEGRATIONS, DEFAULT_IGNORED_INTEGRATIONS
            )
        )
        # Integrations with something left to ignore, plus the ones
        # already ignored. An integration whose devices are every one
        # of them set aside already is not offered: Device Sentinel
        # has classified them out, and ignoring them would change
        # nothing while burying the real choices under three dozen
        # add-ons and dashboard cards. The already-ignored are kept
        # because ignoring took them out of the watched set, and a
        # picker that forgot them would strand a choice it had just
        # made. An integration since uninstalled survives as a custom
        # value rather than failing the form (the 0.13.2 fault).
        breakdown = self.config_entry.runtime_data.classification_breakdown
        integration_domains = sorted(
            {
                domain
                for domain, counts in breakdown.items()
                if counts.get("watched")
            }
            | set(ignored)
        )

        def share_selector() -> selector.NumberSelector:
            """A ten-to-ninety percent slider in steps of ten."""
            return selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=SHARE_PCT_MIN,
                    max=SHARE_PCT_MAX,
                    step=SHARE_PCT_STEP,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            )

        return self.async_show_form(
            step_id="advanced",
            description_placeholders={"wiki_link": WIKI_LINK_ADVANCED},
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SETTLE_SHARE,
                        default=options.get(
                            CONF_SETTLE_SHARE, DEFAULT_SETTLE_SHARE_PCT
                        ),
                    ): share_selector(),
                    vol.Required(
                        CONF_EPISODE_SHARE,
                        default=options.get(
                            CONF_EPISODE_SHARE, DEFAULT_EPISODE_SHARE_PCT
                        ),
                    ): share_selector(),
                    vol.Required(
                        CONF_TAINT_FLOOR,
                        default=options.get(
                            CONF_TAINT_FLOOR, DEFAULT_TAINT_FLOOR_MINUTES
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=TAINT_FLOOR_MINUTES_MIN,
                            max=TAINT_FLOOR_MINUTES_MAX,
                            step=1,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_TAINT_SHARE,
                        default=options.get(
                            CONF_TAINT_SHARE, DEFAULT_TAINT_SHARE_PCT
                        ),
                    ): share_selector(),
                    vol.Required(
                        CONF_COALESCE_MINUTES,
                        default=options.get(
                            CONF_COALESCE_MINUTES, DEFAULT_COALESCE_MINUTES
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=COALESCE_MINUTES_MIN,
                            max=COALESCE_MINUTES_MAX,
                            step=1,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_RETENTION_DAYS,
                        default=options.get(
                            CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=RETENTION_DAYS_MIN,
                            max=RETENTION_DAYS_MAX,
                            step=RETENTION_DAYS_STEP,
                            unit_of_measurement="days",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_MAINTENANCE_MINUTES,
                        default=options.get(
                            CONF_MAINTENANCE_MINUTES,
                            DEFAULT_MAINTENANCE_MINUTES,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MAINTENANCE_MINUTES_MIN,
                            max=MAINTENANCE_MINUTES_MAX,
                            step=MAINTENANCE_MINUTES_STEP,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_IGNORED_INTEGRATIONS, default=ignored
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
