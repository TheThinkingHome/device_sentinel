# Device Sentinel

Somewhere in your house right now, a sensor may be lying to you. It froze, and Home Assistant is still showing the last thing it heard. The dashboard looks healthy. The corpse looks fine.

Device Sentinel is a Home Assistant custom integration that watches for exactly that: frozen devices (silent but wearing healthy values), unavailable devices, low batteries, and weak radio links. It learns the system it is installed in, so you do not have to configure it.

**Status: pre-release (0.3.x). Not ready for use.** Battery detection is live; freeze, unavailability, and signal detection, problem lists, and notifications arrive in later steps. Until public release, the [Sentinel blueprints](https://github.com/TheThinkingHome/Automations) remain the supported tools. Device Sentinel is their successor.

## The idea

Install it, add it, answer zero questions. From that moment it watches every device in your registry by default. Non-hardware devices (Sun, add-ons, dashboard plugins) classify themselves out automatically, and you exclude the rare exception in two clicks. Where customization earns its place it exists, sliders and per-device overrides for the tuner, but a novice never needs to touch any of it.

Then it learns. It measures each device's reporting rhythm from the event bus, the longest it normally goes silent, tracked daily in storage that survives every restart and update. Each device's freeze window is its own worst normal silence plus a margin. No tiers, no hand-guessed timings, no helper entities to create. One anomalous day moves nothing; a repeating anomaly counts; a frozen device can never teach the system that freezing is normal, because only silences that end get learned. Restart republishes, restored states, and reconnect storms are recognized and excluded on their pattern alone.

## What it does today

- Watches all devices by default with automatic service-device classification, and reports coverage, learning progress, and classification through its own entities.
- Learns per-device reporting rhythms and per-device signal baselines (Zigbee linkquality, Wi-Fi RSSI), with anomaly-trimmed rolling histories.
- Detects low batteries: the percentage entity elected over the binary flag, a threshold on a dashboard slider applied live, hysteresis so a cell at the line never flaps, and below-threshold-since carried across restarts. Reported through battery_low_count and battery_low_list.
- One-press enable assist: a button that enables the last_seen and signal entities integrations ship disabled, so protocol truth flows without hand-enabling entities. Entities a user disabled personally are left alone.
- Writes two human-readable diagnostic files nightly to `/config/device_sentinel/`: the learned-rhythms table and the watched-versus-set-aside audit.

## What is coming

- Frozen-device detection at device level (any entity's activity vouches for its siblings), each window armed per device from its own learned rhythm.
- Unavailable, unknown, and never-reported detection at entity level, with the last signal readings before a failure attached as forensics.
- Signal detection against each device's own learned baseline; there is no cross-manufacturer LQI standard, so there is no global threshold.
- Problem lists as real to-do entities (the checkbox is the acknowledgment; recovery deletes), and notifications about additions only, with quiet hours and per-device priority.
- The exclude list (entity, device, label, area, integration) with pickers populated from what was detected.

## Requirements

- Home Assistant 2026.5 or newer.

## Installation (development)

One click, on a machine with HACS installed:

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TheThinkingHome&repository=device_sentinel&category=integration)

Or by hand: HACS, the three-dot menu, Custom repositories, paste `https://github.com/TheThinkingHome/device_sentinel`, category Integration, Add. Then install Device Sentinel from HACS, restart Home Assistant, and add it under Settings, Devices and Services, Add Integration.

## From The Thinking Home

The story behind this project: [From Blueprints to Integration: Why Device Sentinel Exists](https://xeazy.com) on xeazy.com, where design notes and articles live. Blueprints live in the [Automations](https://github.com/TheThinkingHome/Automations) repository.

## License

GPL-3.0-or-later. Copyright (C) 2026 James Lander, The Thinking Home.
