# Device Sentinel

A Home Assistant custom integration that watches hardware liveness: frozen devices (silent but showing a healthy value), unavailable devices, and low batteries. It learns each device's own reporting rhythm and sets per-device freeze windows automatically, so it watches everything by default and false-alarms on almost nothing.

**Status: pre-release backbone (0.1.0). Not intended for use.** This version proves the installation path, the config flow, and persistent storage. It detects nothing and alerts nothing yet. Detection, problem lists, and notifications arrive in later versions.

Device Sentinel is the integration successor to the Sentinel template blueprints ([Battery Sentinel, Entity Sentinel, Sentinel Notify](https://github.com/TheThinkingHome/Automations)). Until this project reaches its public release, the blueprints remain the supported tools.

## What it will do

- Watch every device in the registry by default, with an exclude list for exceptions. Non-hardware devices (Sun, Backup, add-ons, frontend plugins) are set aside automatically.
- Learn each device's reporting rhythm from the event bus and set its freeze window from its own worst normal silence plus a margin. No tiers, no hand-guessed windows.
- Detect frozen devices at device level (any entity's activity vouches for the device), and unavailable, unknown, or missing entities at entity level.
- Track batteries against a threshold, with below-threshold-since carried across restarts.
- Keep acknowledgeable problem lists as its own to-do entities, and notify about additions only, with quiet hours and per-device priority.

## Requirements

- Home Assistant 2026.5 or newer.

## Installation (development)

Through HACS custom repositories: HACS, Custom repositories, paste this repository's URL, category Integration, install, restart, then add Device Sentinel under Settings, Devices and Services.

## From The Thinking Home

Design notes and articles live at [xeazy.com](https://xeazy.com). Blueprints live in the [Automations](https://github.com/TheThinkingHome/Automations) repository.

## License

GPL-3.0-or-later. Copyright (C) 2026 James Lander, The Thinking Home.
