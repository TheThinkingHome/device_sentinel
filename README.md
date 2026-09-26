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

&nbsp;
&nbsp;

<figure>
  <img src="https://xeazy.com/wp-content/uploads/Dashboard-Mockup-scaled.png" alt="Dashboard Mock-Up">
</figure>

&nbsp;
&nbsp;

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

| Problem | Why you care |
|---|---|
| **Frozen** | Silent while still showing a healthy value. Your automations are acting on a dead reading. |
| **Unavailable** | Home Assistant knows it's gone. You probably don't. |
| **Flapping** | Drops out and comes back again and again. One alert, not dozens. |
| **Never reported** | Ghost entries, and devices that died before you installed this. |
| **Low or falling battery** | Warned while you can still act, even when a coin cell still reads 80%. |
| **Weak or stuck signal** | Links degrade before they fail. |

![Device Sentinel battery decay beside a device's radio link](https://xeazy.com/wp-content/uploads/Battery-Decay-Signal-Dwell.png)

## What You Get

**Zero-Config Monitoring From Day One**
Every device in your registry is watched from the moment you install the integration. Non-hardware entries (like Sun or HACS) and disabled devices are automatically ignored.

**One Unified Problem List**
Every fault lands in one Home Assistant to-do list. A device that is both frozen and low on battery is one line, not two. Tick the item to acknowledge it, and it stops making noise on your phone while staying on the list until it recovers.

**Smart Upstream Outage Detection**
When a coordinator, broker, or Wi-Fi network goes down, every device behind it goes quiet. Device Sentinel reports the one failure you can fix, rather than giving you sixty separate alerts for sixty silent devices. When it comes back, the report shows the devices that have reconnected and gives the devices not yet reconnected time to rejoin before anything is reported. 

**A Dashboard in Your Sidebar**
The daily brief, the problem list, battery and signal trends, and a page for each device, one click apart. Administrators only.

**Alerts That Respect Your Evening**
Live push notifications are sent for real faults, and quiet hours keep your phone silent overnight. A daily brief, delivered by email or push on your schedule, summarizes what happened and highlights devices that keep failing for no clear reason.

Every screen and setting is explained in the [wiki](https://github.com/TheThinkingHome/device_sentinel/wiki).

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
2. At the top of the Device Sentinel dashboard, press the three **Enable** buttons (Battery, Signals, Last Seen) so the integration has data to learn from.

![The Device Sentinel device page in Home Assistant, with its three enable buttons and diagnostic sensors](https://xeazy.com/wp-content/uploads/integration_page.webp)

It takes time to learn your house. Freeze detection arms after a week, battery trends after two weeks, and signal baselines settle after a month.

## Configuration Overview

Device Sentinel's settings are designed to be set once and forgotten. For complete details, see the [Wiki Configuration Guide](https://github.com/TheThinkingHome/device_sentinel/wiki).

![The Device Sentinel configuration screens in Home Assistant](https://xeazy.com/wp-content/uploads/integration_settings.webp)

| Section | What it controls |
|---|---|
| **[Notifications](https://github.com/TheThinkingHome/device_sentinel/wiki/Notifications-and-Daily-Brief)** | Where your instant alerts go, your quiet hours, when the Daily Brief is generated and sent, and whether device names in the daily brief open their pages on the dashboard. |
| **[Exclusions and Muting](https://github.com/TheThinkingHome/device_sentinel/wiki/Exclusions-and-Muting)** | Manage the hardware you want ignored. *Exclude* integrations that provide useless data (like mobile apps). *Mute* devices to stop alerts while keeping their history. |
| **[Low Battery](https://github.com/TheThinkingHome/device_sentinel/wiki/Low-Battery)** | Set your flat percentage threshold and your "Days Till Empty" horizon. |
| **[Signal Strength](https://github.com/TheThinkingHome/device_sentinel/wiki/Signal-Strength)** | Define what constitutes a "bad signal day" by adjusting how far a signal must drop below its own normal baseline. |
| **[Freeze Detection](https://github.com/TheThinkingHome/device_sentinel/wiki/Freeze-Detection)** | Fine-tune the grace period added to a device's learned reporting rhythm before it is flagged as frozen. |
| **[WiFi](https://github.com/TheThinkingHome/device_sentinel/wiki/WiFi)** | Configure the integration to watch your server's wireless adapter to detect home-wide Wi-Fi outages. |
| **[Advanced](https://github.com/TheThinkingHome/device_sentinel/wiki/Advanced)** | Storage, history and maintenance-window settings, and the Data Trim tool. |
| **[Extended Diagnostics](https://github.com/TheThinkingHome/device_sentinel/wiki/Extended-Diagnostics)** | Volunteer hardware data to help build support for new routers and coordinators. |

## Integration Status

| Area | Status | Notes |
|---|---|---|
| **Dashboard** | Working | Everything Device Sentinel knows, one click apart, with a page for each device. Administrators only. |
| **Freeze Detection** | Stable | Catches frozen, unavailable and flapping devices, each on its own rhythm. |
| **Battery** | Stable | Warns on low batteries and on batteries falling or speeding up. |
| **Storage** | Stable | Survives power cuts and restores itself from a backup. |
| **Zigbee2MQTT** | Working | A bridge outage is one alert, and your re-pairs are never mistaken for faults. |
| **MQTT** | Working | A broker outage is one alert, not one per device. |
| **ZHA** | Working | A coordinator outage is one alert, and your re-pairs are recognized. |
| **Signal** | Experimental | Weak links shown on the dashboard; stuck readings alert. |
| **WiFi** | Experimental | A Wi-Fi outage is one alert. Needs a wireless adapter on your server or a supported router. |
| **Z-Wave** | Basic Detection | Devices watched; an integration outage is one alert. Controller support is being built. |
| **Matter** | Basic Detection | Devices watched; an integration outage is one alert. Controller support is being built. |

## AI Disclosure

Device Sentinel was built with AI assistance under my direction. Every design decision is mine, and nothing reaches this repository without my review and a full test gate, with detection proven on real hardware. [AI_DISCLOSURE.md](AI_DISCLOSURE.md) explains exactly what the AI did and how every release is checked.

## From The Thinking Home

The full story: [From Blueprints to Integration: Why Device Sentinel Exists](https://xeazy.com/reliable-home-assistant-dead-sensor-detection/). 

**License:** GPL-3.0-or-later. Copyright (C) 2026 James Lander, The Thinking Home.
