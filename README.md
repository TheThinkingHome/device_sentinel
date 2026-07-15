# Device Sentinel

![Tests](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/test.yml/badge.svg)
![Validate](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/validate.yml/badge.svg)
![Version](https://img.shields.io/github/v/release/TheThinkingHome/device_sentinel)
![License](https://img.shields.io/github/license/TheThinkingHome/device_sentinel)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)

Somewhere in your house right now, a sensor may be lying to you. It froze, and Home Assistant is still showing the last thing it heard. Temperature 22.4. Motion clear. Door closed. The dashboard looks healthy. The corpse looks fine.

Device Sentinel is a Home Assistant custom integration that watches for exactly that: frozen devices wearing healthy values, unavailable devices, low batteries, and weak radio links.

**Status: pre-release (0.3.x). Not ready for use.** Battery detection is live; freeze, unavailability, and signal detection, problem lists, and notifications arrive in later steps. Until public release, the [Sentinel blueprints](https://github.com/TheThinkingHome/Automations) remain the supported tools.

## Why an integration

Device Sentinel is the successor to the Sentinel blueprint series (Battery Sentinel, Entity Sentinel, Sentinel Notify). The blueprints work, and building them exposed two walls. A template blueprint has no storage and no clock that survives a restart: every reboot resets the freeze stopwatch, so a slow-reporting device dying on a frequently-restarted system is invisible to it by construction. And blueprints are complicated to set up: tiers to assign, helper entities to create by hand, a paragraph of documentation per input. A novice meets that wall and reasonably asks why any of it is their job.

An integration has its own storage and its own clocks, so a device twenty hours into a freeze is still twenty hours frozen after a reboot. And it installs like an integration should: add it and it runs on sensible defaults, watching everything immediately. You configure what you want to configure, notification targets, thresholds, exclusions, tuning knobs for the advanced user, and skip what you do not.

## What makes it different

It learns the system it is installed in. Every device's reporting rhythm is measured from the event bus, the longest it normally goes silent, tracked daily in restart-proof storage. Each device's freeze window is its own worst normal silence plus a margin. No tiers, no hand-guessed timings. Your chatty motion sensor earns a tight window; your twice-a-day rain gauge earns a generous one; a device added next spring starts its own clock and arms itself when its rhythm is established.

The learning defends itself. One anomalous day is set aside and moves nothing; a repeating anomaly counts as real. A frozen device can never teach the system that freezing is normal, because only silences that end get learned. Restart republishes, restored states, and reconnect storms are recognized by their pattern and excluded, with no hand-kept lists of integration names. Radio links get the same treatment: judged against each device's own learned baseline, because there is no cross-manufacturer LQI standard, so a global threshold would be a lie.

## What it does today

- Watches all devices by default; non-hardware devices (Sun, add-ons, dashboard plugins) classify themselves out, and the integration refuses to watch itself.
- Learns per-device rhythms and per-device signal baselines with anomaly-trimmed rolling histories, and reports coverage and learning progress through its own entities.
- Detects low batteries: percentage elected over the binary flag, a threshold on a dashboard slider applied live, hysteresis so a cell at the line never flaps, below-threshold-since carried across restarts.
- One-press enable assist: enables the last_seen and signal entities integrations ship disabled, respecting anything a user disabled personally.
- Writes two human-readable diagnostic files nightly: the learned-rhythms table and the watched-versus-set-aside audit.

## What is coming

- Frozen-device detection at device level, any entity's activity vouching for its siblings, each window armed per device from its own learned rhythm.
- Unavailable, unknown, and never-reported detection at entity level, with the last signal readings before a failure attached as forensics: 40, 32, 24, gone tells you the link died; 200, 201, 200 tells you to look elsewhere.
- Signal detection against the learned per-device baselines.
- Problem lists as real to-do entities, the checkbox as the acknowledgment, recovery deleting the item; notifications about additions only, with quiet hours and per-device priority piercing for the freezer at 3 AM.
- The exclude list (entity, device, label, area, integration) with pickers populated from what was detected.

## Requirements

- Home Assistant 2026.5 or newer.

## Installation (development)

One click, on a machine with HACS installed:

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TheThinkingHome&repository=device_sentinel&category=integration)

Or by hand: HACS, the three-dot menu, Custom repositories, paste `https://github.com/TheThinkingHome/device_sentinel`, category Integration, Add. Then install Device Sentinel from HACS, restart Home Assistant, and add it under Settings, Devices and Services, Add Integration.

## From The Thinking Home

The full story: [From Blueprints to Integration: Why Device Sentinel Exists](https://xeazy.com) on xeazy.com. Blueprints live in the [Automations](https://github.com/TheThinkingHome/Automations) repository.

## License

GPL-3.0-or-later. Copyright (C) 2026 James Lander, The Thinking Home.
