# Device Sentinel

![Tests](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/test.yml/badge.svg)
![Validate](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/validate.yml/badge.svg)
![Lint](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/lint.yml/badge.svg)
![CodeQL](https://github.com/TheThinkingHome/device_sentinel/actions/workflows/codeql.yml/badge.svg)
![Version](https://img.shields.io/github/v/release/TheThinkingHome/device_sentinel)
![License](https://img.shields.io/github/license/TheThinkingHome/device_sentinel)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)


**Your dashboard cannot tell a quiet device from a dead one. Device Sentinel can, and it watches the batteries and radio links that fail first.**

## Integration Status

| Area | Status | What you get |
| --- | --- | --- |
| Freeze detection | Stable | Every device gets its own deadline, learned from its own habits. A device that has gone quiet is caught while its last reading still looks perfectly fine. |
| Battery | Stable | Warning while you can still act, from the level you set and from how fast the cell is actually falling. |
| Signal | Experimental | Weak links are found and charted against each device's own normal. Nothing reaches your phone yet except a link stuck at a false value. |
| Zigbee2MQTT | Coordinator watched | When the coordinator stops, you get one message naming it instead of sixty devices blamed for it. Re-pair a device by hand and that is not learned as its normal behavior. |
| ZHA | Coordinator watched | When the coordinator stops, you get one message naming it, timed from when the radio really stopped. Press Maintenance Mode before you work on a device and your fix is not learned as its normal behavior. |
| MQTT | Broker watched | When the broker stops, every device behind it goes quiet at once. You get one message naming the broker, and none of them is blamed. |
| Z-Wave | Devices watched | Every device is watched as usual. The controller is not, so a controller outage reads as a fault on each device behind it. [Help change that](https://github.com/TheThinkingHome/device_sentinel/wiki/Z-Wave). |

## The Problem

Home Assistant reacts to what devices tell it. When a device stops telling it anything, the last thing it said stays on your dashboard forever. Nothing turns red. Nothing goes unavailable. The reading just stops changing, and it keeps looking perfectly reasonable.

- A door sensor dies while the door is closed. Your security automations believe that door is shut, indefinitely.
- A freezer sensor drops off the mesh. The dashboard shows a comfortable minus eighteen while the food spoils.
- A leak sensor stops answering. You find out during the next burst pipe.

Worse, the two warnings that arrive *before* a device dies are sitting in plain sight, unread.

- The batteries in your door lock have been draining for a month. Nothing mentions it until the lock stops answering and you are on the wrong side of it.
- A sensor at the far end of the house has been losing packets for weeks. It mostly works, which is worse than not working, because nothing you build on it can be trusted.

Both numbers are already in Home Assistant. Nobody watches them because neither means anything on its own: twenty percent is two weeks on one device and Tuesday on another, and radio link quality has no shared scale at all, so the same reading is healthy on one manufacturer's hardware and dying on another's.

## The Solution

Device Sentinel watches how often each device actually reports, and learns its rhythm. Every device gets its own deadline, measured from its own habits, and nobody has to guess a number.

Your chatty motion sensor earns a tight window and gets flagged within minutes of dying. Your twice-a-day rain gauge earns a generous one and is left alone. A device you add next spring starts learning the day you pair it and arms itself once its rhythm is established.

The same idea settles the other two. A radio link is judged against the floor that device has actually held, not a threshold borrowed from another manufacturer's scale. And a battery is judged twice: against a level you choose, and against how fast it is actually falling.

That second judgment is the one a percentage cannot make. In the author's own house, one morning, a soil sensor read 82 percent and a door sensor read 24. The percentages say the soil sensor is in better shape. It was not. The door sensor had about a week left and the soil sensor had two months, and Device Sentinel said so on the problem list while the door sensor still read a comfortable-looking 24 percent.

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
| **Falling battery** | The cell is projected to reach empty inside your chosen horizon, default thirty days, from how fast it is actually dropping. | The earlier warning. A cell at 24 percent falling steadily can have less life left than one sitting at 80 that has not moved in a month. |
| **Weak or railed signal** | A link that spends much of its day below its own danger line, which sits just above the floor that device has actually held, or stuck at the value that means no reading at all. | Links degrade before they fail. This is the part you can fix with a repeater. Weak links are listed and charted today; only the railed case reaches your phone, until the alerting formula has earned trust. |

## What You Get

### It Watches Everything From The Moment You Install It

There is no watch list to maintain. Every device in your registry is observed from the start, so the leak sensor you paired last month is already covered, and the one you pair tomorrow will be too. Non-hardware entries like Sun, Backup, and HACS classify themselves out, and so does anything Home Assistant has disabled, since a disabled device cannot report and watching for its silence would say nothing.

It cannot watch what your integrations ship switched off, and most of them ship battery, signal, and last-seen entities disabled. Three buttons turn them on in bulk, one per kind. Each turns on every disabled entity of its kind, including any you switched off yourself, so leave a button alone if there is something you meant to keep off.

![The Device Sentinel device page in Home Assistant, with its three enable buttons and diagnostic sensors](https://xeazy.com/wp-content/uploads/integration_page.webp)

You curate by exception, with two verbs that mean different things. Muting a whole integration, a label, or a single device stops the judging and the reporting; it does not stop the learning, so a device you un-mute next year already knows its own rhythm and needs no relearning period. Excluding an integration is the harder act: its devices are never watched, never learned from, and what they had recorded is discarded at the next midnight.

### Warnings Before The Failure

A low battery is caught on the percentage rather than the binary flag, against a threshold you set. Every device's daily level is recorded too, and that is where the second warning comes from: a cell losing charge fast enough to run out inside your chosen horizon is flagged while it is still nowhere near the threshold.

The time left is said in words rather than days, "empty in about 2 weeks" rather than "13 days", and that is deliberate. The projection assumes the last week continues, which a dying cell often does not. Read it as a ranking of which cell to replace first, because that part it gets right.

![Device Sentinel battery decay beside a device's radio link](https://xeazy.com/wp-content/uploads/Battery-Decay-Signal-Dwell.png)

A radio link is judged against its own recent history rather than a fixed number. Each night the day's readings become a time-weighted fifth percentile, and that is compared against the median of the days before it. The day counts as bad only when the fall is large in the device's own units and also large measured in the device's own spread, which is what lets a steady link and a jittery one be read on the same page. A link stuck at its rail, the 255 or the minus 128 that means the field was filled in rather than measured, is called out for what it is rather than read as a strong signal.

![The Device Sentinel signal report, one row per device worth a look, each day shaded by how far it fell below that device's own normal](https://xeazy.com/wp-content/uploads/signal_report.webp)

### It Does Not Learn Your Repairs As Normal

The learning has to survive you. A battery swap, a re-pair, a Home Assistant restart: each looks exactly like a device choosing to be silent, and an integration that learned those gaps would slowly teach itself that broken is normal. Device Sentinel tells them apart. A recovery during a Zigbee2MQTT pairing window is recognized as your hand, and on a coordinator with no window to read, Maintenance Mode says the same thing. A silence that spans a restart is not counted against anybody, because nothing was listening. And for everything no coordinator can see, there is a Maintenance Mode button: press it before you work on your hardware, and whatever recovers in the next ten minutes is credited to you rather than learned as the device's own rhythm.

### One List Of What Is Actually Wrong

Every fault, whatever kind, lands in one Home Assistant to-do list. A device that is both frozen and low on battery is one line, not two. Tick it to acknowledge: it stays listed and keeps updating, but stops making noise on your phone and on the dashboard card until it recovers, on its own or by your intervention.

### Alerts That Respect Your Evening

- **A dashboard card** that is always current and never makes a sound. When nothing is wrong it says so.
- **Phone pushes** for real faults, one per kind rather than one per device. When a bridge or broker goes down, the devices behind it are counted rather than listed, and you get one message naming the thing you can actually fix. Faults arrive audibly, recoveries silently.
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

And should you ever remove it, it removes everything it wrote: its storage, its reports, and its pages. No trace is left behind.

It runs on sensible defaults the moment it is added. Two things are worth doing straight away: tell it where alerts should go, and press the three enable buttons so there is battery and signal data to watch.

### What You Get, And When

It learns your house rather than asking you to describe it, so some of it works at once and some of it earns its accuracy.

| When | What is working |
|---|---|
| **Immediately** | Flat batteries, devices that are unavailable or unknown, and devices in your registry that have never reported at all. |
| **After a week** | Freeze detection arms, device by device, as each one establishes a rhythm. |
| **After two weeks** | Rhythms have settled, so freeze windows stop shifting as new evidence arrives. |
| **After a month** | A device has enough signal history that a bad day is measured against a settled normal rather than a short one. |

Batteries are their own clock. A cell holds its level for most of its life and then falls, so the projection means little until a particular cell leaves its plateau. The one that proved this held 32 percent for ten days before it broke.

Nothing here needs your attention while it happens. The list stays short on purpose, and a quiet first week means it is working.

## Configuration

Every screen explains itself and links to its own wiki page. Most people change one thing and never open the rest.

![The Device Sentinel configuration screens in Home Assistant](https://xeazy.com/wp-content/uploads/integration_settings.webp)

| Screen | What it is for |
|---|---|
| **Notifications** | Where alerts go, quiet hours, and when the daily brief is written. The brief's time is also the boundary of its window: a 7 AM brief covers 7 AM to 7 AM. |
| **Exclusions and Muting** | Integrations to exclude, whose devices are never watched or recorded, and hardware to mute by integration, label, or device, which is still watched but never reported. |
| **Low Battery** | The threshold, default twenty percent; how far ahead a falling cell is flagged, default thirty days; and devices to leave out of battery reporting. |
| **Signal Strength** | What counts as a bad signal day: how far a link must fall in its own units, how far in its own spread, and how many past days form the normal it is measured against. Also devices to leave out of signal reporting. |
| **Freeze Detection** | Two sliders shaping how much grace a device gets on top of its learned rhythm. Fast devices are governed by the first (1 to 8 minutes, default 3), slow ones by the second (4 to 12 hours, default 8). |
| **Advanced** | Settings most people never need: how long a fault must persist before your phone hears about it, how long a device may be unreachable before that counts as real downtime, how long the Maintenance Mode window lasts, how often work is written to disk, and how much history to keep. |

## Reports And Diagnostics

Two more pages are written for a person, beside the daily brief: **the battery report**, which ranks every falling cell by how long it has left, and **the signal report**, which names the devices whose radio link is worse than it usually is and leaves the rest off the page. Both live under `www` so a dashboard card can point at them.

Three further files are written for whoever maintains the system:

- **Device telemetry**, one row per device with its learned rhythm, its signal history, and its battery trend.
- **Classification**, showing which devices are watched, which are set aside, and why anything is muted.
- **Silence episodes**, recording every time a device went quiet past its own learned rhythm, whether it came back on its own or something intervened, and whether the gap was learned. This answers a question nothing else does: did the device recover, or did your restart make it look like it recovered?

## Documentation

The [wiki](https://github.com/TheThinkingHome/device_sentinel/wiki) is the full documentation. Worth starting with:

- [How Device Sentinel Learns](https://github.com/TheThinkingHome/device_sentinel/wiki/How-Device-Sentinel-Learns)
- [Notifications and Daily Brief](https://github.com/TheThinkingHome/device_sentinel/wiki/Notifications-and-Daily-Brief)
- [Low Battery](https://github.com/TheThinkingHome/device_sentinel/wiki/Low-Battery)
- [The Battery Report](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Battery-Report)
- [Signal Strength](https://github.com/TheThinkingHome/device_sentinel/wiki/Signal-Strength)
- [The Problem List](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Problem-List)
- [The Diagnostic Reports](https://github.com/TheThinkingHome/device_sentinel/wiki/The-Diagnostic-Reports)
- [FAQ and Troubleshooting](https://github.com/TheThinkingHome/device_sentinel/wiki/FAQ-and-Troubleshooting)

## On The Roadmap

Worked on in this order:

- **Signal alerts.** Weak links are already found, charted, and listed; they do not yet reach your phone. Nobody yet knows which signal pattern predicts a device actually failing: a link can sit low for months and never miss a report, and another can look healthy and drop out weekly. Alerting on that today would mean warnings about devices that are fine, which teaches you to ignore the one that is not.

  What settles it is meshes that misbehave. **If yours does, you can help.** Open an issue titled **contribute signal**, attach a diagnostics download and your signal report from `config/www/device_sentinel/signal_report.html`, and say which devices actually give you trouble and how often. A healthy mesh cannot answer the question, however long it runs.
- **The signal trail on an alert.** The last few readings before a device went dark, attached to the alert. Forty, thirty-two, twenty-four, then gone tells you the link died. Two hundred, two hundred and one, then gone tells you to look elsewhere.
- **A dashboard card.** One card showing the problem list, the counts, and the maintenance state, installable from HACS beside the integration.

## Why An Integration

Device Sentinel replaces the Sentinel blueprint series, and building those showed why a blueprint could never finish the job. A template blueprint has no storage and no clock that survives a restart, so every reboot resets the stopwatch and a slow device dying on a frequently restarted system is invisible by construction. Blueprints also ask a lot of you up front: tiers to assign, helpers to create, a paragraph of documentation per input.

An integration keeps its own clocks and its own storage. A device twenty hours into a freeze is still twenty hours frozen after a reboot. And it installs the way an integration should: add it, and it is already watching.

## From The Thinking Home

The full story: [From Blueprints to Integration: Why Device Sentinel Exists](https://xeazy.com/reliable-home-assistant-dead-sensor-detection/). Blueprints live in the [Automations](https://github.com/TheThinkingHome/Automations) repository.

## AI Disclosure

See [AI_DISCLOSURE.md](AI_DISCLOSURE.md).

## License

GPL-3.0-or-later. Copyright (C) 2026 James Lander, The Thinking Home.
