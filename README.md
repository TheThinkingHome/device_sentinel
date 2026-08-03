# Device Sentinel

![Tests](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/test.yml/badge.svg)
![Validate](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/validate.yml/badge.svg)
![Lint](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/lint.yml/badge.svg)
![CodeQL](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/codeql.yml/badge.svg)
![Version](https://img.shields.io/github/v/release/TheThinkingHome/device_sentinel)
![License](https://img.shields.io/github/license/TheThinkingHome/device_sentinel)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)

**Your dashboard cannot tell a quiet device from a dead one. Device Sentinel can, and it watches the batteries and radio links that fail first.**

# Pre-Release Notice

> Device Sentinel is in active, rapid development and breaking changes will occur. Please read all release notes carefully before updating. The integration is fully functional and actively producing real freeze, battery, and signal data for live environments.

## The Problem

Home Assistant reacts to what devices tell it. When a device stops telling it anything, the last thing it said stays on your dashboard forever. Nothing turns red. Nothing goes unavailable. The reading just stops changing, and it keeps looking perfectly reasonable.

- A door sensor dies while the door is closed. Your security automations believe that door is shut, indefinitely.
- A freezer sensor drops off the mesh. The dashboard shows a comfortable minus eighteen while the food spoils.
- A leak sensor stops answering. You find out during the next burst pipe.

Worse, the two warnings that arrive *before* a device dies are sitting in plain sight, unread.

- The batteries in your door lock have been draining for a month. Nothing mentions it until the lock stops answering and you are on the wrong side of it.
- A sensor at the far end of the house has been losing packets for weeks. It mostly works, which is worse than not working, because nothing you build on it can be trusted.

Both numbers are already in Home Assistant. Nobody watches them because neither means anything on its own: twenty percent is two weeks on one device and Tuesday on another, and radio link quality has no shared scale at all, so the same reading is healthy on one manufacturer's hardware and dying on another's.

> **Image placeholder:** the frozen-sensor problem. A door opens while the dashboard stays on "Closed", then the Device Sentinel alert arrives.

## The Solution

Device Sentinel watches how often each device actually reports, and learns its rhythm. Every device gets its own deadline, measured from its own habits, and nobody has to guess a number.

Your chatty motion sensor earns a tight window and gets flagged within minutes of dying. Your twice-a-day rain gauge earns a generous one and is left alone. A device you add next spring starts learning the day you pair it and arms itself once its rhythm is established.

The same idea settles the other two. A radio link is judged against the floor that device has actually held, not a threshold borrowed from another manufacturer's scale. A battery is judged against a level you choose and against its own rate of decay. An AAA cell loses charge slowly and steadily, but a lithium does not: it holds almost full charge until it fails. The same percentage means different things depending on what is inside, so each device's own curve is learned rather than assumed.

## What It Catches

Four ways a device goes dark:

| Verdict | What it means | Why you care |
|---|---|---|
| **Frozen** | Silent past its own learned window, while still showing a healthy value. | The dangerous one. Nothing looks wrong, and your automations are acting on a dead reading. |
| **Unavailable** | Every live entity on the device reports unavailable. | Home Assistant knows. You probably do not, until something fails to happen. |
| **Unknown** | Every live entity reports unknown. | Usually a protocol or integration problem rather than the device itself. |
| **Never reported** | Known to the registry but has produced nothing for 48 hours. | Ghost entries, and devices that died before you installed this. |

And two that give you warning first:

| Verdict | What it means | Why you care |
|---|---|---|
| **Low battery** | The level falls past your threshold, default twenty percent, and stays there. | Warning while you can still act, rather than a post-mortem once the device has gone quiet. |
| **Weak or railed signal** | A link that spends much of its day at or below that device's own learned floor, or stuck at the value that means no reading at all. | Links degrade before they fail. This is the part you can fix with a repeater. |

## What You Get

### It Watches Everything From The Moment You Install It

There is no watch list to maintain. Every device in your registry is observed from the start, so the leak sensor you paired last month is already covered, and the one you pair tomorrow will be too. Non-hardware entries like Sun, Backup, and HACS classify themselves out.
![Device Sentinel Battery Decay vs. Signal Dwell](https://xeazy.com/wp-content/uploads/Battery-Decay-Signal-Dwell.png)

It cannot watch what your integrations ship switched off, and most of them ship battery, signal, and last-seen entities disabled. Three buttons turn them on in bulk, one per kind, leaving alone anything you disabled on purpose.

![The Device Sentinel device page in Home Assistant, with its three enable buttons and diagnostic sensors](https://xeazy.com/wp-content/uploads/integration_page.webp)

You curate by exception. Exclude a whole integration, a label, or a single device. Excluding stops the judging and the reporting; it does not stop the learning, so a device you un-exclude next year already knows its own rhythm and needs no relearning period.

### Warnings Before The Failure

A low battery is caught on the percentage rather than the binary flag, against a threshold you set with a slider. Every device's daily level is recorded as well, which is the groundwork for telling you a cell is falling unusually fast while it is still nowhere near the threshold.

A radio link is watched against the floor that device has actually held over the past two weeks, and what gets reported is dwell: how much of the day it spent down at that floor. A link stuck at its rail, the 255 or the minus 128 that means the field was filled in rather than measured, is called out for what it is rather than read as a strong signal.

![The Device Sentinel signal dwell chart, one colored bar per device showing how much of the day its radio link spent below its own learned floor](https://xeazy.com/wp-content/uploads/signal_report.webp)

### One List Of What Is Actually Wrong

Every fault, whatever kind, lands in one Home Assistant to-do list. A device that is both frozen and low on battery is one line, not two. Tick it to acknowledge: it stays listed and keeps updating, but stops making noise on your phone and on the dashboard card until it recovers, on its own or by your intervention.

> **Image placeholder:** the problem list and the whole-home dashboard card, side by side.

### Alerts That Respect Your Evening

- **A dashboard card** that is always current and never makes a sound. When nothing is wrong it says so.
- **Phone pushes** for real faults, one per kind rather than one per device, so a bridge dropping forty sensors is one message. Faults arrive audibly, recoveries silently.
- **A daily brief** in plain language: two paragraphs on what happened and what is still broken, then the exact times. Delivered by email or push on your schedule.

Quiet hours hold every phone push, while the card and the morning brief still carry what happened. A new fault waits a short, per-device moment before it reaches you, so a problem that fixes itself in thirty seconds never wakes you at all.

![A Device Sentinel daily brief, listing the devices that need attention and what happened over the last day](https://xeazy.com/wp-content/uploads/daily_brief.webp)

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

It runs on sensible defaults the moment it is added. Two things are worth doing straight away: tell it where alerts should go, and press the three enable buttons so there is battery and signal data to watch.

## Configuration

Every screen explains itself and links to its own wiki page. Most people change one thing and never open the rest.

![The Device Sentinel configuration screens in Home Assistant](https://xeazy.com/wp-content/uploads/integration_settings.webp)

| Screen | What it is for |
|---|---|
| **Notifications** | Where alerts go, quiet hours, and when the daily brief is written. The brief's time is also the boundary of its window: a 7 AM brief covers 7 AM to 7 AM. |
| **Global Exclusions** | Hardware you never want judged, by integration, label, or device. |
| **Low Battery** | The threshold, default twenty percent, and devices to leave out of battery reporting. |
| **Signal Strength** | How sensitive the fleet-wide judgment is, and devices to leave out of signal reporting. |
| **Freeze Detection** | Two sliders shaping how much grace a device gets on top of its learned rhythm. Fast devices are governed by the first (1 to 8 minutes, default 3), slow ones by the second (4 to 12 hours, default 8). |
| **Advanced** | Settings most people never need: how long a fault must persist before your phone hears about it, how long a device may be unreachable before that counts as real downtime, how often work is written to disk, and how much history to keep. |

## Reports And Diagnostics

Alongside the daily brief, three files are written for whoever maintains the system:

- **Device telemetry**, one row per device with its learned rhythm, its signal history, and its battery trend.
- **Classification**, showing which devices are watched, which are set aside, and why anything is excluded.
- **Silence episodes**, recording every time a device went quiet past its own learned rhythm, whether it came back on its own or something intervened, and whether the gap was learned. This answers a question nothing else does: did the device recover, or did your restart make it look like it recovered?

## Documentation

The [wiki](https://github.com/TheThinkingHome/device_sentinel/wiki) is the full documentation. Worth starting with:

- [How Device Sentinel Learns](https://github.com/TheThinkingHome/device_sentinel/wiki/How-Device-Sentinel-Learns)
- [Notifications and Daily Brief](https://github.com/TheThinkingHome/device_sentinel/wiki/Notifications-and-Daily-Brief)
- [Low Battery](https://github.com/TheThinkingHome/device_sentinel/wiki/Low-Battery)
- [Signal Strength](https://github.com/TheThinkingHome/device_sentinel/wiki/Signal-Strength)
- [The Problem List](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Problem-List)
- [The Reports](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Reports)
- [FAQ and Troubleshooting](https://github.com/TheThinkingHome/device_sentinel/wiki/FAQ-and-Troubleshooting)

## On The Roadmap

Found while building the core, and worked on in this order:

- **Telling a self-recovery from a hand-fix.** Where a coordinator publishes its pairing state, a device that comes back while you are standing there re-pairing it should not have that silence learned as normal.
- **The signal trail on an alert.** The last few readings before a device went dark, attached to the alert. Forty, thirty-two, twenty-four, then gone tells you the link died. Two hundred, two hundred and one, then gone tells you to look elsewhere.
- **Discharge velocity.** Catching a cell that is falling fast while it is still above the threshold, from the daily levels already being recorded.
- **Recovery.** Trying to revive a stuck device rather than only reporting it, from the gentlest nudge upward, and saying what it did either way. Detection comes first, because nothing should be fixed automatically until finding things is proven.

## Why An Integration

Device Sentinel replaces the Sentinel blueprint series, and building those showed why a blueprint could never finish the job. A template blueprint has no storage and no clock that survives a restart, so every reboot resets the stopwatch and a slow device dying on a frequently restarted system is invisible by construction. Blueprints also ask a lot of you up front: tiers to assign, helpers to create, a paragraph of documentation per input.

An integration keeps its own clocks and its own storage. A device twenty hours into a freeze is still twenty hours frozen after a reboot. And it installs the way an integration should: add it, and it is already watching.

## From The Thinking Home

The full story: [From Blueprints to Integration: Why Device Sentinel Exists](https://xeazy.com/reliable-home-assistant-dead-sensor-detection/). Blueprints live in the [Automations](https://github.com/TheThinkingHome/Automations) repository.

## License

GPL-3.0-or-later. Copyright (C) 2026 James Lander, The Thinking Home.
