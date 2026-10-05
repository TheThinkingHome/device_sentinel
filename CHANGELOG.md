# Changelog

Device Sentinel is under active development. These are the releases published as Latest, newest first, followed by the last release of each early version. Each version links to its full release notes, and the pre-releases between them are on the [releases page](https://github.com/TheThinkingHome/device_sentinel/releases).

## [0.23.20](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.23.20), October 1, 2026

An outage caused by a hub, broker or integration reaches you as one alert, and a recovery is announced only when a device actually reports again. A device that keeps dropping out becomes one problem instead of dozens. Batteries are read by the week, so a half-point wobble no longer reads as falling, and your brief and reports sit behind Home Assistant's sign-in.

## [0.22.29](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.22.29), September 27, 2026

Device Sentinel starts on any house, whatever your other integrations register, and the diagnostics download works again.

## [0.22.28](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.22.28), September 23, 2026

Device Sentinel gets its own dashboard in the Home Assistant sidebar: the daily brief, the problem list, battery and signal trends, and each device's own page. The daily brief recommends changes to your setup, such as a notification target that no longer exists. Battery, signal and rhythm graphs share one timeline, with outages shaded behind them.

## [0.21.14](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.21.14), September 18, 2026

An outage is reported as one row from start to finish, and Z-Wave, Matter and other integrations get time to rejoin before anything is reported. Each device name in your reports carries its room and can open that device's page.

## [0.21.10](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.21.10), September 16, 2026

Wi-Fi and Zigbee bridge outages are reported as one problem that names the cause, not forty separate devices. Sleeping computers no longer raise a false Wi-Fi alarm. After an outage, slow devices get time to reconnect, and your phone stays quiet while they do.

## [0.20.20](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.20.20), September 12, 2026

Your automations can react to an outage's cause, with the number of devices it affected. Device Sentinel detects a Wi-Fi outage by listening for your network or through your router integration. The battery report reads a history and recognizes a battery change, and the Advanced screen went from nine settings to four.

## [0.19.14](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.19.14), September 2, 2026

Repeat Offenders became a table, and restarts no longer fill the brief with noise. Backups are taken at each save instead of once a day, and Device Sentinel repairs damaged saved data without asking you. ZHA coordinators are watched, and a re-paired ZHA device is recognized on its own.

## [0.18.9](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.18.9), August 28, 2026

A damaged data file no longer takes Device Sentinel offline: it restores itself from its last good backup, and subtler damage comes with a fix you choose. Battery checks wait out Home Assistant's startup, so a slow-waking device is not reported.

## [0.17.10](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.17.10), August 25, 2026

Device Sentinel's data file is smaller and is checked in full each night. Repair cards can be dismissed without accepting the fix, and damaged saved data stops setup with a plain explanation instead of an error trace.

## [0.17.0](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.17.0), August 23, 2026

Exclude and Mute mean different things: excluding stops watching and discards the history, muting hides alerts while Device Sentinel keeps watching. The signal report asks whether a device suddenly got worse, with settings that define a bad day. A Data Trim tool removes the history of a device or integration that recorded bad data, and the settings screens were rebuilt for houses with hundreds of devices.

## [0.16.3](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.16.3), August 20, 2026

Device Sentinel starts reliably and stays up through the morning report.

## [0.15.7](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.15.7), August 18, 2026

Device Sentinel checks its learned data and keeps a backup of the last good copy, so an improper shutdown no longer costs weeks of learning. Where a device reports both signal strength and link quality, both are recorded. A bridge or broker going down reads as one line in the brief instead of a line for each device behind it.

## [0.14.4](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.14.4), August 16, 2026

Mobile App, Fully Kiosk, Spook and Ping are no longer watched by default, since their devices mean nothing to monitor, and you can leave out other integrations too. A device set aside is no longer judged or reported.

## [0.14.0](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.14.0), August 14, 2026

A broker or bridge outage is reported as one fault, announced once, instead of one fault for each device behind it. Disabled devices are set aside without losing what they learned.

## [0.13.0](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.13.0), August 12, 2026

Freeze detection and battery watching became stable. Signal reporting starts working properly, judging strong and weak links fairly on both signal scales.

## [0.12.16](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.12.16), August 8, 2026

Maintenance Mode lets you say you're working on your hardware, so battery swaps, re-pairings and repairs don't teach Device Sentinel false rhythms. Removing the integration removes everything it wrote.

## [0.12.10](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.12.10), August 7, 2026

Device Sentinel records what happens beneath your devices and names it in the daily brief: Home Assistant restarts, unclean shutdowns, your MQTT broker or coordinator going down, and integrations reloading. It watches the MQTT broker directly, with nothing to configure.

## [0.12.0](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.12.0), August 5, 2026

The 0.11 work came out of pre-release as one version. Device Sentinel watches each device in Home Assistant, learns its own reporting habits instead of asking you for a timeout, and tells you when one stops reporting, when a battery is low or about to be, and when a radio link is failing.

## [0.11.13](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.11.13), August 4, 2026

Each device's learned statistics begin to decide its verdicts, not only to be reported. Problem list items say plainly what they mean, such as "battery 16%, empty in about 2 weeks".

## [0.10.24](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.10.24), August 3, 2026

Routine saves write about ninety percent less to disk: only a small file of activity clocks changes as devices report, and everything else is written when it changes.

## [0.9.12](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.9.12), July 27, 2026

The daily brief can be emailed as a formatted document, with its tables intact. A device that flickers unavailable for a moment is no longer reported later as having been down for hours.

## [0.8.10](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.8.10), July 24, 2026

Device Sentinel reads when the coordinator last actually heard from a device, not when a message about it arrived, so a replayed message can no longer make a silent device look alive. That was why quiet devices had been reported as faulty night after night.

## [0.7.6](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.7.6), July 23, 2026

Device Sentinel records each problem from start to finish and writes a daily brief you can read each morning. The brief closes its day at the time you choose.

## [0.6.8](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.6.8), July 22, 2026

The problem list fills itself: a device appears the moment something is wrong and leaves when its last problem clears. Check a box to silence a problem you've decided to live with.

## [0.5.7](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.5.7), July 21, 2026

Freeze detection arrives, the reason the project exists. A device that stops reporting while still showing its last value is caught, judged against its own learned rhythm, with no timeouts to set.

## [0.4.13](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.4.13), July 20, 2026

Signal watching begins. Each device's radio link is judged against its own history, and a reading that has silently stopped changing is caught. It records only and sends no alerts.

## [0.3.14](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.3.14), July 17, 2026

Low battery detection arrives, with one setting: the threshold. Each settings screen links to its own wiki page.

## [0.2.6](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.2.6), July 13, 2026

Device Sentinel watches each device and learns how often it reports, without judging anything yet, and writes what it learns to readable reports.

## [0.1.2](https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.1.2), July 11, 2026

The first release: setup, saved data and a status sensor, the foundation the rest is built on. It was not yet meant for use.
