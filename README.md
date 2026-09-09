# Device Sentinel

![Tests](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/test.yml/badge.svg)
![Validate](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/validate.yml/badge.svg)
![Lint](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/lint.yml/badge.svg)
![CodeQL](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/codeql.yml/badge.svg)
![Version](https://img.shields.io/github/v/release/TheThinkingHome/device_sentinel)
![License](https://img.shields.io/github/license/TheThinkingHome/device_sentinel)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)


**Your dashboard cannot tell a quiet device from a dead one. Device Sentinel can, and it catches failing batteries and dropping radio links before they take your smart home down.**

> **Pre-Release.** This integration is under rapid development. Check the table below to see what is stable today.

## The Blind Spot

Home Assistant only reacts to what your devices tell it. When a device quietly dies, Home Assistant doesn't blink. The last value reported stays on your dashboard forever. Nothing turns red. Nothing throws an error.

* A freezer sensor drops off the mesh. Your dashboard shows a comfortable -18°C while the food inside slowly thaws.
* A door sensor dies while the door is closed. Your security automations happily believe that door is secure, indefinitely.
* The batteries in your smart lock have been draining for a month. Nothing warns you until you are standing outside, locked out.

The early warning signs are usually there, in battery levels and radio signal data, but they are ignored because a battery reading of 20% means "two weeks left" on one device and "dead this afternoon" on another. 

## The Solution

Device Sentinel doesn't guess. It watches how often each device *actually* reports and learns its unique rhythm. 

There are no watch lists to maintain and no arbitrary timeouts to assign. A chatty motion sensor earns a tight window and gets flagged within minutes if it goes dark. A twice-a-day rain gauge earns a generous window and is left alone. 

It applies that same logic to your batteries and radio links. A radio link is judged against the baseline *that specific device* normally holds. A battery is judged twice: once against a flat level you choose, and again against how fast it is actually draining. 

If a battery is projected to reach empty inside your chosen horizon, say thirty days, it is flagged, even if it still reads 80%.

### What It Catches

Device Sentinel spots four ways a device goes dark:

| Verdict | What it means | Why you care |
|---|---|---|
| **Frozen** | Silent past its own learned window, while still showing a healthy value. | The dangerous one. Your automations are acting on a dead reading. |
| **Unavailable** | Every live entity on the device reports `unavailable`. | Home Assistant knows it's gone. You probably don't. |
| **Unknown** | Every live entity reports `unknown`. | Usually an integration or protocol failure. |
| **Never reported** | Known to the registry but has produced nothing for 48 hours. | Ghost entries, and devices that died before you installed this. |

And two warnings that arrive *before* the failure:

| Verdict | What it means | Why you care |
|---|---|---|
| **Low battery** | The level falls past your threshold (default 20%). | Warning while you can still act. |
| **Falling battery** | The cell is projected to reach empty inside your chosen horizon, based on how fast it is *actually* dropping. | A lithium coin cell at 82% that is falling steadily can be dead within days, while an alkaline cell sitting at 24% that hasn't moved in a month keeps going. |
| **Weak or railed signal** | A link spending much of its day worse than that device has ever normally run, or stuck at a "no reading" value. | Links degrade before they fail. |

![Device Sentinel battery decay beside a device's radio link](https://xeazy.com/wp-content/uploads/Battery-Decay-Signal-Dwell.png)

![The Device Sentinel signal report, charting the devices whose radio link is worse than usual, with every steady device named below](https://xeazy.com/wp-content/uploads/signal_report.webp)

## What You Get

**Zero-Config Monitoring From Day One**
Every device in your registry is watched from the moment you install the integration. Non-hardware entries (like Sun or HACS) and disabled devices are automatically ignored.

**One Unified Problem List**
Every fault lands in one Home Assistant to-do list. A device that is both frozen and low on battery is one line, not two. Tick the item to acknowledge it, and it stops making noise on your phone while staying on the list until it recovers.

**Smart Upstream Outage Detection**
When a coordinator, broker, or Wi-Fi network goes down, every device behind it goes quiet. Device Sentinel reports the one failure you can fix, rather than giving you sixty separate alerts for sixty silent devices. 

**Alerts That Respect Your Evening**
Live push notifications are sent for real faults, but quiet hours hold them overnight. A daily brief, delivered by email or push on your schedule, summarizes what happened and highlights devices that keep failing for no clear reason.

![A Device Sentinel daily brief, listing the devices that need attention and what happened over the last day](https://xeazy.com/wp-content/uploads/daily_brief.webp)

## Installation

Device Sentinel is not in the default HACS store yet.

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TheThinkingHome&repository=device_sentinel&category=integration)

1. Open **HACS** > **Custom repositories**.
2. Paste `https://github.com/TheThinkingHome/device_sentinel`, choose **Integration**, and click **Add**.
3. Download Device Sentinel, then **Restart Home Assistant**.
4. Go to **Settings > Devices and Services > Add Integration** and search for Device Sentinel.

*(Requires Home Assistant 2026.5 or newer)*

### First Steps

It runs on sensible defaults immediately. Two things are worth doing on day one:
1. Open the integration settings and configure **Notifications and Daily Brief**.
2. On the Device Sentinel device page, press the three **Enable** buttons (Battery, Signals, Last Seen) so the integration has data to learn from.

![The Device Sentinel device page in Home Assistant, with its three enable buttons and diagnostic sensors](https://xeazy.com/wp-content/uploads/integration_page.webp)

It takes time to learn your house. Freeze detection arms after a week, and signal baselines settle after a month.

## Configuration Overview

Device Sentinel's settings are designed to be set once and forgotten. For complete details, see the [Wiki Configuration Guide](https://github.com/TheThinkingHome/device_sentinel/wiki).

![The Device Sentinel configuration screens in Home Assistant](https://xeazy.com/wp-content/uploads/integration_settings.webp)

| Section | What it controls |
|---|---|
| **[Notifications](https://github.com/TheThinkingHome/device_sentinel/wiki/Notifications-and-Daily-Brief)** | Where your instant alerts go, your quiet hours, and when the Daily Brief is generated and sent. |
| **[Exclusions and Muting](https://github.com/TheThinkingHome/device_sentinel/wiki/Exclusions-and-Muting)** | Manage the hardware you want ignored. *Exclude* integrations that provide useless data (like mobile apps). *Mute* devices to stop alerts while keeping their history. |
| **[Low Battery](https://github.com/TheThinkingHome/device_sentinel/wiki/Low-Battery)** | Set your flat percentage threshold and your "Days Till Empty" horizon. |
| **[Signal Strength](https://github.com/TheThinkingHome/device_sentinel/wiki/Signal-Strength)** | Define what constitutes a "bad signal day" by adjusting how far a signal must drop below its own normal baseline. |
| **[Freeze Detection](https://github.com/TheThinkingHome/device_sentinel/wiki/Freeze-Detection)** | Fine-tune the grace period added to a device's learned reporting rhythm before it is flagged as frozen. |
| **[WiFi](https://github.com/TheThinkingHome/device_sentinel/wiki/WiFi)** | Configure the integration to watch your server's wireless adapter to detect home-wide Wi-Fi outages. |
| **[Advanced](https://github.com/TheThinkingHome/device_sentinel/wiki/Advanced)** | Deep system tuning: debounce timers, repeat offender thresholds, and storage write intervals. Also includes the Data Trim tool. |
| **[Extended Diagnostics](https://github.com/TheThinkingHome/device_sentinel/wiki/Extended-Diagnostics)** | Volunteer hardware data to help build support for new routers and coordinators. |

## The Reports

Device Sentinel generates several reports to help you understand your network's health, all viewable as dashboard cards or plain text files. 

*   **[The Problem List](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Problem-List):** The live Home Assistant To-Do list where you acknowledge active faults.
*   **[The Daily Brief](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Daily-Brief):** A plain-English summary of what is wrong right now and what happened over the last 24 hours.
*   **[The Battery Report](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Battery-Report):** Ranks every falling battery by how much time it has left.
*   **[The Signal Report](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Signal-Report):** Charts the devices struggling with unusually bad radio links.
*   **[The Diagnostic Reports](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Diagnostic-Reports):** The raw data. View exactly what rhythm Device Sentinel learned for each sensor and investigate silence episodes.

## Integration Status

| Area | Status | Notes |
|---|---|---|
| **Freeze Detection** | Stable | Rhythms fully modeled. Differentiates frozen, unavailable, unknown, and never reported. |
| **Battery** | Stable | Dual-evaluation (flat threshold + predictive trend) is live. |
| **Storage** | Stable | Highly resilient data storage with automatic last-good backups. |
| **Zigbee2MQTT** | Working | Supports pairing window recognition and bridge/broker outage detection. |
| **MQTT** | Working | Watches the MQTT broker itself; devices clear blame during broker outages. |
| **ZHA** | Working | Coordinator outage detection. Re-pairs/reconfigures recognized automatically. |
| **Signal** | Experimental | Weak links charted; alerts held back until logic is field-proven. |
| **WiFi** | Experimental | Detects Wi-Fi outages from the host adapter, or from supported router integrations (like TP-Link and UniFi). Requires server wireless capability if a supported router is not used. See the [WiFi](https://github.com/TheThinkingHome/device_sentinel/wiki/WiFi) documentation. |
| **Z-Wave** | Basic Detection | Watches the integration itself. An integration outage or a storm of devices dropping simultaneously is reported as a single event, clearing the individual devices of blame. The running controller is not built yet. See [Z-Wave](https://github.com/TheThinkingHome/device_sentinel/wiki/Z-Wave) to contribute. |

## AI Disclosure

See [AI_DISCLOSURE.md](AI_DISCLOSURE.md).

## From The Thinking Home

The full story: [From Blueprints to Integration: Why Device Sentinel Exists](https://xeazy.com/reliable-home-assistant-dead-sensor-detection/). 

**License:** GPL-3.0-or-later. Copyright (C) 2026 James Lander, The Thinking Home.
