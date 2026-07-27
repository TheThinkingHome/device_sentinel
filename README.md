# Device Sentinel

![Tests](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/test.yml/badge.svg)
![Validate](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/validate.yml/badge.svg)
![Lint](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/lint.yml/badge.svg)
![CodeQL](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/codeql.yml/badge.svg)
![Version](https://img.shields.io/github/v/release/TheThinkingHome/device_sentinel)
![License](https://img.shields.io/github/license/TheThinkingHome/device_sentinel)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)

**Your dashboard cannot tell a quiet device from a dead one. Device Sentinel can.**

> **Image placeholder:** hero banner, 1200x300. Device Sentinel alongside the Home Assistant and HACS marks.

## The Problem

Home Assistant reacts to what devices tell it. When a device stops telling it anything, the last thing it said stays on your dashboard forever. Nothing turns red. Nothing goes unavailable. The reading just stops changing, and it keeps looking perfectly reasonable.

- A door sensor dies while the door is closed. Your security automations believe that door is shut, indefinitely.
- A freezer sensor drops off the mesh. The dashboard shows a comfortable minus eighteen while the food spoils.
- A leak sensor's battery runs out. You find out during the next burst pipe.

The usual answer is a fixed timeout: tell me if anything has gone quiet for twenty-four hours. That breaks immediately, because your devices are nothing like each other. A hallway motion sensor reports hundreds of times a day, so twenty-four hours of silence means it died last night and you are hearing about it far too late. A door button might legitimately say nothing for three days, so the same rule cries wolf every week until you mute it.

> **Image placeholder:** the frozen-sensor problem. A door opens while the dashboard stays on "Closed", then the Device Sentinel alert arrives.

## The Solution

Device Sentinel watches how often each device actually reports, and learns its rhythm. Every device gets its own deadline, measured from its own habits, and nobody has to guess a number.

Your chatty motion sensor earns a tight window and gets flagged within minutes of dying. Your twice-a-day rain gauge earns a generous one and is left alone. A device you add next spring starts learning the day you pair it and arms itself once its rhythm is established.

The learning defends itself. Only silences that end are learned, so a device that freezes can never teach the system that freezing is normal. One anomalous day is set aside rather than widening the window. Restart storms and reconnect floods are recognised by their shape and kept out of the baseline. It runs continuously on the author's own system, a household of around two hundred devices.

## What It Catches

| Verdict | What it means | Why you care |
|---|---|---|
| **Frozen** | Silent past its own learned window, while still showing a healthy value. | The dangerous one. Nothing looks wrong, and your automations are acting on a dead reading. |
| **Unavailable** | Every live entity on the device reports unavailable. | Home Assistant knows. You probably do not, until something fails to happen. |
| **Unknown** | Every live entity reports unknown. | Usually a protocol or integration problem rather than the device itself. |
| **Never reported** | Known to the registry, but has produced nothing for 48 hours. | Ghost entries, and devices that died before you installed this. |

Judgment is made per device, not per entity. If any one entity on a device is still reporting, the device is alive. One sensor with six entities does not become six separate alarms.

## What You Get

### It Watches Everything From The Moment You Install It

There is no watch list to maintain. Every device in your registry is observed from the start, so the leak sensor you paired last month is already covered and the one you pair tomorrow will be too. Non-hardware entries like Sun, add-ons and dashboard plugins classify themselves out, and the integration refuses to watch itself.

You curate by exception. Exclude a whole integration, a label, or a single device. Excluding stops the judging and the reporting; it does not stop the watching, so a device you un-exclude next year already knows its own rhythm and needs no relearning period.

### One List Of What Is Actually Wrong

Every fault, whatever kind, lands in one Home Assistant to-do list. One device with two problems is one line, not two. Tick it to acknowledge: it stays listed and keeps updating, but stops making noise on your phone and on the dashboard card until it recovers on its own.

> **Image placeholder:** the problem list and the whole-home dashboard card, side by side.

### Alerts That Respect Your Evening

- **A dashboard card** that is always current and never makes a sound. When nothing is wrong it says so.
- **Phone pushes** for real faults, one per kind rather than one per device, so a bridge dropping forty sensors is one message. Faults arrive audibly, recoveries silently.
- **A daily brief** in plain language: two paragraphs on what happened and what is still broken, then the exact times. Delivered by email or push on your schedule.

Quiet hours hold every phone push, while the card and the morning brief still carry what happened. A new fault waits a short, per-device moment before it reaches you, so a problem that fixes itself in thirty seconds never wakes you at all.

> **Image placeholder:** the daily brief as it arrives by email.

### Batteries And Radio Links, Judged Properly

Low battery detection uses the percentage rather than the binary flag, on a threshold you set with a slider. A cell sitting exactly on the line does not flap, because it has to climb two points clear before the alert lifts. Daily levels are recorded too, groundwork for warning you that a cell is falling fast before it reaches the threshold at all.

Signal strength is judged against each device's own learned floor, because there is no cross-manufacturer standard for link quality and a global threshold would be a lie. A link stuck at its rail value, the 255 or the minus 128 that means "no reading", is caught for what it is.

## Installation

One click, if you already have HACS:

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TheThinkingHome&repository=device_sentinel&category=integration)

By hand:

1. Open **HACS**, then the three-dot menu, then **Custom repositories**.
2. Paste `https://github.com/TheThinkingHome/device_sentinel`, choose the **Integration** category, and click **Add**.
3. Find **Device Sentinel** in HACS and download it.
4. Restart Home Assistant.
5. Go to **Settings, Devices and Services, Add Integration** and search for Device Sentinel.

**Requires** Home Assistant 2026.5 or newer.

It runs on sensible defaults the moment it is added. The one thing worth setting up is where alerts should go.

## Configuration

Every screen explains itself and links to its own wiki page. Most people change one thing and never open the rest.

| Screen | What it is for |
|---|---|
| **Notifications** | Where alerts go, quiet hours, and when the daily brief is written. The brief's time is also the boundary of its window: a 7 AM brief covers 7 AM to 7 AM. |
| **Global Exclusions** | Hardware you never want judged, by integration, label, or device. |
| **Low Battery** | The threshold, and devices to leave out of battery reporting. |
| **Signal Strength** | Fleet-wide sensitivity, and devices to leave out of signal reporting. |
| **Freeze Detection** | Two sliders shaping how much grace a device gets on top of its learned rhythm. Fast devices are governed by the first (1 to 8 minutes, default 3), slow ones by the second (4 to 12 hours, default 8). |
| **Advanced** | Settings most people never need: how long a fault must persist before your phone hears about it, how long a device may be unreachable before that counts as real downtime, how often work is written to disk, and how much history to keep. |

## Reports And Diagnostics

Three files are written for whoever maintains the system, alongside the daily brief:

- **Device telemetry**, one row per device with its learned rhythm, signal history and battery trend.
- **Classification**, showing which devices are watched, which are set aside, and why anything is excluded.
- **Silence episodes**, recording every time a device went quiet past its own basis, whether it came back on its own or something intervened, and whether the gap was learned. This answers a question nothing else does: did the device recover, or did your restart make it look like it recovered?

To report a problem, download a diagnostics file from **Settings, Devices and Services, Device Sentinel**, the three-dot menu, then **Download Diagnostics**, and attach it to a GitHub issue. It contains the learned state, your settings, and the episode records. Your notification targets are redacted; device names are not, so read it before you post it.

## Documentation

The [wiki](https://github.com/TheThinkingHome/device_sentinel/wiki) is the full documentation. Worth starting with:

- [How Device Sentinel Learns](https://github.com/TheThinkingHome/device_sentinel/wiki/How-Device-Sentinel-Learns)
- [Notifications and Daily Brief](https://github.com/TheThinkingHome/device_sentinel/wiki/Notifications-and-Daily-Brief)
- [The Problem List](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Problem-List)
- [The Reports](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Reports)
- [FAQ and Troubleshooting](https://github.com/TheThinkingHome/device_sentinel/wiki/FAQ-and-Troubleshooting)

## On The Roadmap

Found while building the core, and worked on in this order:

- **Telling a self-recovery from a hand-fix.** Where a coordinator publishes its pairing state, a device that comes back while you are stood at it re-pairing should not have that silence learned as normal.
- **The signal trail on an alert.** The last few readings before a device went dark, attached to the alert. Forty, thirty-two, twenty-four, gone tells you the link died. Two hundred, two hundred and one, two hundred, gone tells you to look elsewhere.
- **Discharge velocity.** Catching a cell that is falling fast before it reaches the threshold.
- **Recovery.** Trying to revive a stuck device rather than only reporting it, from the gentlest nudge upward, and saying what it did either way. Detection comes first, because nothing should be fixed automatically until finding things is proven.

## Why An Integration

Device Sentinel replaces the Sentinel blueprint series, and building those showed why a blueprint could never finish the job. A template blueprint has no storage and no clock that survives a restart, so every reboot resets the stopwatch and a slow device dying on a frequently restarted system is invisible by construction. Blueprints also ask a lot of you up front: tiers to assign, helpers to create, a paragraph of documentation per input.

An integration keeps its own clocks and its own storage. A device twenty hours into a freeze is still twenty hours frozen after a reboot. And it installs the way an integration should: add it, and it is already watching.

## From The Thinking Home

The full story: [From Blueprints to Integration: Why Device Sentinel Exists](https://xeazy.com/reliable-home-assistant-dead-sensor-detection/). Blueprints live in the [Automations](https://github.com/TheThinkingHome/Automations) repository.

## License

GPL-3.0-or-later. Copyright (C) 2026 James Lander, The Thinking Home.
