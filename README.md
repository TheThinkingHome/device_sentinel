# Device Sentinel

![Tests](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/test.yml/badge.svg)
![Validate](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/validate.yml/badge.svg)
![Lint](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/lint.yml/badge.svg)
![CodeQL](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/codeql.yml/badge.svg)
![Version](https://img.shields.io/github/v/release/TheThinkingHome/device_sentinel)
![License](https://img.shields.io/github/license/TheThinkingHome/device_sentinel)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)

Somewhere in your house right now, a sensor may be lying to you. It froze, and Home Assistant is still showing the last thing it heard. Temperature 22.4. Motion clear. Door closed. The dashboard looks healthy. The corpse looks fine.

Device Sentinel is a Home Assistant custom integration that watches for exactly that: frozen devices wearing healthy values, unavailable devices, low batteries, and weak radio links.

**Status: pre-release.** Learning, low battery, signal recording, and freeze detection (frozen, unavailable, unknown, and never-reported) are all live. Every detection feeds a problem list you act on, every problem's whole life is recorded, and a daily brief writes it up in plain language. Sending that brief to a phone or an email is the next step, and recovery follows it. Until public release, the [Sentinel blueprints](https://github.com/TheThinkingHome/Automations/tree/main/blueprints) remain the supported tools.

## Why an integration

Device Sentinel is the successor to the Sentinel blueprint series (Battery Sentinel, Entity Sentinel, Sentinel Notify). The blueprints work, and building them exposed two walls. A template blueprint has no storage and no clock that survives a restart: every reboot resets the freeze stopwatch, so a slow-reporting device dying on a frequently-restarted system is invisible to it by construction. And blueprints are complicated to set up: tiers to assign, helper entities to create by hand, a paragraph of documentation per input. A novice meets that wall and reasonably asks why any of it is their job.

An integration has its own storage and its own clocks, so a device twenty hours into a freeze is still twenty hours frozen after a reboot. And it installs like an integration should: add it and it runs on sensible defaults, watching everything immediately. You configure what you want to configure, notification targets, thresholds, exclusions, tuning knobs for the advanced user, and skip what you do not.

## What makes it different

It learns the system it is installed in. Every device's reporting rhythm is measured from the event bus, the longest it normally goes silent, tracked daily in restart-proof storage. Each device's freeze window is its own worst normal silence plus a margin. No tiers, no hand-guessed timings. Your chatty motion sensor earns a tight window; your twice-a-day rain gauge earns a generous one; a device added next spring starts its own clock and arms itself when its rhythm is established.

The learning defends itself. One anomalous day is set aside and moves nothing; a repeating anomaly counts as real. A frozen device can never teach the system that freezing is normal, because only silences that end get learned. Restart republishes, restored states, and reconnect storms are recognized by their pattern and excluded, with no hand-kept lists of integration names. Radio links get the same treatment: judged against each device's own learned baseline, because there is no cross-manufacturer LQI standard, so a global threshold would be a lie.

## What it does today

- Watches all devices by default; non-hardware devices (Sun, add-ons, dashboard plugins) classify themselves out, and the integration refuses to watch itself.
- Learns per-device rhythms and per-device signal baselines with anomaly-trimmed rolling histories, and reports Devices Watched and Devices Learned through its own entities.
- Detects low batteries: percentage elected over the binary flag, a threshold on a dashboard slider applied live, hysteresis so a cell at the line never flaps, below-threshold-since carried across restarts. Tracked Batteries counts what is watched; Low Batteries reports what is low, with the device rows and thresholds in its attributes. Records each battery's daily level too, the groundwork for warning when a cell is discharging fast, before it hits the threshold.
- Watches signal strength against each device's own learned floor, reporting how much of each day a device spent at or below that floor (dwell), and flagging a signal stuck at the rail (the 255 or -128 fill value) when its daily low holds there for three days running. A config screen sets fleet-wide sensitivity and can exclude a stubborn device from signal reporting without blinding the watcher. Tracked Signals counts what is watched; Signal Problems reports what has a fault, rail now, weak-link dwell once its danger line is ruled. Recording and reporting now; alerting comes with the notification engine.
- Enable Signals, Enable Last Seen, Enable Battery: three buttons, one per diagnostic kind, each turning on the entities that integrations ship disabled, respecting anything a user disabled personally. A fourth button, Regenerate Reports, judges every device and rewrites both report files on demand.
- Exclusions on a priority ladder (integration, label, device), with pickers populated from what was actually detected, and per-section lists beside the global one. Device Sentinel judges devices, not entities, so there is no per-entity exclude; a label on an entity still keeps it from feeding its device. Exclusion suppresses judgment, not observation: an excluded device keeps learning, so undoing costs nothing.
- Detects frozen, unavailable, unknown, and never-reported devices at the device level, any entity's activity vouching for its siblings. Each freeze window is armed per device from its own learned rhythm plus a grace margin set by two sliders. A device silent past its window while wearing a stale value is frozen; a device whose live entities all read unavailable or unknown is that; a device that has produced nothing at all for 48 hours since install is never-reported. The verdict survives a reboot (measured from the stored clock) and clears the instant the device reports. Device: Frozen counts what is down, each row carrying its category and how long it has been down.
- Gathers every detection into one problem list, a standard Home Assistant to-do entity, so there is a single place to see what is wrong now. A device appears the moment any detection flags it and is deleted the moment the last one clears; a device with two problems shows as one line, name first, carrying both. Checking the box acknowledges a problem: it stays listed, keeps updating, survives reboots checked, and stays silent to the notifications coming next, until it recovers on its own. Open items sort alphabetically, acknowledged items in the order you checked them.
- Records when a device was genuinely last heard from, rather than when a message about it happened to arrive. Many integrations publish a last-contact time, and where one exists Device Sentinel reads it on every check, so a bridge republishing its stored state cannot make a silent device look alive. Where no such time exists, a report is a report, including the one a device makes when the system restarts: a nightly restart is part of a home's rhythm, not interference to filter out.
- Records the whole life of every problem: when it opened, when it cleared, how long it lasted, what revived it where that is knowable, and when you acknowledged it. This is the memory a blueprint cannot have, and it is what lets a report say a device broke at 1:02 AM and came back two hours later rather than only that something is wrong now.
- Writes a daily brief in plain language, one file per day: two paragraphs saying what happened and what is still wrong, then tables with the exact times. It is written whether or not anything is configured to send it, and it is deliberately free of the integration's own machinery, no rhythms, no windows, no thresholds.
- Writes three diagnostic files nightly for whoever maintains the system: the learned-rhythms table (alphabetical, with each device's integration and exclusion status), a one-row-per-device classification table showing whether each device is watched or set aside and why any is excluded from judgment, and a silence-episode record. That last one answers a question nothing else can: when a device goes quiet far longer than usual and then speaks again, did it choose to speak, or did a restart or a reconnect make it speak?
- An Advanced screen for the settings most people never need: how long a problem must persist before it is sent, how quiet a device must be before its silence is recorded for study, and how often routine activity is written to disk, which matters on an SD card.

## What is coming

- The signal forensics trail: the last signal readings before a device went dark attached to its alert, 40, 32, 24, gone tells you the link died; 200, 201, 200 tells you to look elsewhere. The rule is specified; the trail is the next signal step.
- A battery discharge-velocity flag: catching a cell dropping fast before it reaches the threshold, from the daily-level history already being recorded.
- The sending engine behind the settings already built and waiting. The messages are already written and recorded, one per device, plain sentences, so what will be sent can be read in the daily brief before anything is sent at all. Nothing pierces quiet hours, not even high priority: a problem at 3 AM is recorded, kept, and told to you in the morning brief rather than waking the house, and the phone is brought up to date the moment quiet hours end.
- Recovery: attempting to revive a stuck device rather than only reporting it.

## Documentation

The [wiki](https://github.com/TheThinkingHome/device_sentinel/wiki) is the full documentation. Worth starting with:

- [How Device Sentinel Learns](https://github.com/TheThinkingHome/device_sentinel/wiki/How-Device-Sentinel-Learns): the rhythm, the windows, and why there is no fixed timeout anywhere.
- [Notifications and Daily Brief](https://github.com/TheThinkingHome/device_sentinel/wiki/Notifications-and-Daily-Brief): the one thing to configure, so alerts reach your phone.
- [The Device Page](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Device-Page): what every sensor and button means.
- [The Problem List](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Problem-List): how detections reach the list, and what the checkbox does.
- [The Reports](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Reports): the daily brief, and the three diagnostic files behind it.
- [FAQ and Troubleshooting](https://github.com/TheThinkingHome/device_sentinel/wiki/FAQ-and-Troubleshooting)

Every configuration screen also explains itself and links to its own page.

## Requirements

- Home Assistant 2026.5 or newer.

## Installation (development)

One click, on a machine with HACS installed:

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TheThinkingHome&repository=device_sentinel&category=integration)

Or by hand: HACS, the three-dot menu, Custom repositories, paste `https://github.com/TheThinkingHome/device_sentinel`, category Integration, Add. Then install Device Sentinel from HACS, restart Home Assistant, and add it under Settings, Devices and Services, Add Integration.

## From The Thinking Home

The full story: [From Blueprints to Integration: Why Device Sentinel Exists](https://xeazy.com/reliable-home-assistant-dead-sensor-detection/) on xeazy.com. Blueprints live in the [Automations](https://github.com/TheThinkingHome/Automations) repository.

## License

GPL-3.0-or-later. Copyright (C) 2026 James Lander, The Thinking Home.
