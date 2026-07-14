# Device Sentinel

A Home Assistant custom integration that watches hardware liveness: frozen devices (silent but showing a healthy value), unavailable devices, low batteries, and weak radio links. It learns each device's own reporting rhythm and sets per-device freeze windows automatically, so it watches everything by default and false-alarms on almost nothing.

**Status: pre-release (0.3.x). Not intended for use.** Battery detection is live; freeze and unavailable detection, signal detection, problem lists, and notifications arrive in later versions. Until this project reaches its public release, the blueprints remain the supported tools.

Device Sentinel is the integration successor to the Sentinel template blueprints ([Battery Sentinel, Entity Sentinel, Sentinel Notify](https://github.com/TheThinkingHome/Automations)).

## What it does today

- Watches every device in the registry by default. Non-hardware devices (Sun, Backup, add-ons, frontend plugins) are set aside automatically.
- Detects low batteries: the percentage entity elected over the binary flag per device, a configurable threshold (dashboard slider, applied live), hysteresis so a cell at the line never flaps, and below-threshold-since carried in storage across restarts. Reported through battery_low_count and battery_low_list entities.
- Learns each device's reporting rhythm from the event bus: the worst normal silence per day, kept as a rolling per-device history in persistent storage that survives restarts and updates. Restart republishes, reconnect storms, and outages are recognized and excluded, so a device can never teach the system that being broken is normal.
- Records each device's signal strength (Zigbee linkquality, Wi-Fi RSSI) with rolling daily minima.
- One-press enable assist: a button that enables the last_seen and signal entities integrations ship disabled, so protocol truth flows without hand-enabling entities one by one. Entities a user disabled personally are left alone.
- Coverage, learning-progress, and classification sensors, plus two diagnostic files written nightly to `/config/device_sentinel/`: the learned-rhythms table (device_telemetry.txt) and the watched-versus-set-aside audit (classification.txt).

## What is coming

- Frozen-device detection at device level (any entity's activity vouches for the device), with each device's window set from its own learned rhythm plus a margin. No tiers, no hand-guessed windows.
- Unavailable, unknown, and missing detection at entity level.
- Signal detection against each device's own learned baseline (no global threshold; LQI has no cross-manufacturer standard).
- Acknowledgeable problem lists as the integration's own to-do entities, and notifications about additions only, with quiet hours and per-device priority.
- An exclude list (entity, device, label, area, integration) and tuning knobs, all through the options flow.

## Requirements

- Home Assistant 2026.5 or newer.

## Installation (development)

One click, on a machine with HACS installed:

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TheThinkingHome&repository=device_sentinel&category=integration)

Or by hand: HACS, the three-dot menu, Custom repositories, paste `https://github.com/TheThinkingHome/device_sentinel`, category Integration, Add. Then install Device Sentinel from HACS, restart Home Assistant, and add it under Settings, Devices and Services, Add Integration.

## From The Thinking Home

Design notes and articles live at [xeazy.com](https://xeazy.com). Blueprints live in the [Automations](https://github.com/TheThinkingHome/Automations) repository.

## License

GPL-3.0-or-later. Copyright (C) 2026 James Lander, The Thinking Home.
