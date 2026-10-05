# Contributing to Device Sentinel

Home Assistant works with almost any device. Device Sentinel knows only what it has alread seen, on a limited number of houses. Your setup almost certainly has a hub, an integration, or a device not seen before. Sharing your data is how Device Sentinel learns, and you don't need to write a line of code to do that. Your data, your problem reports and your opinion are what shape it.

## Your House Is What's Missing

Hubs and integrations each report in their own way. A Z-Wave device that has died can still read "available" in Home Assistant. A Thread device drops out only when all the border routers it can reach have gone. Each one has to be read differently, and the only way to learn how is a record of it misbehaving on a real system.

Data from these is wanted most:

- **Z-Wave**: how the controller marks a device dead and alive again. See [Z-Wave](https://github.com/TheThinkingHome/device_sentinel/wiki/Z-Wave).
- **Matter and Thread**: what happens when a device or a border router drops out. See [Matter](https://github.com/TheThinkingHome/device_sentinel/wiki/Matter).
- **Philips Hue, SmartThings, Tuya and Lutron Caséta**: how each hub reports a device it can no longer reach.
- **Routers** (UniFi, FRITZ!Box, AsusWRT, NETGEAR and MikroTik): how each one sees a Wi-Fi device leave and come back. See [WiFi](https://github.com/TheThinkingHome/device_sentinel/wiki/WiFi).
- **Large Zigbee meshes**: one branch failing while the coordinator stays up. See [ZHA](https://github.com/TheThinkingHome/device_sentinel/wiki/ZHA) and [Zigbee2MQTT](https://github.com/TheThinkingHome/device_sentinel/wiki/Zigbee2MQTT).
- **Setups not seen yet**: more than one Zigbee2MQTT instance, or Home Assistant Container or Core instead of Home Assistant OS.

## How to Share Your Data

It takes about ten minutes to set up, then a few days of using your house normally.

1. Open Device Sentinel's settings, choose **Extended Diagnostics**, and turn on the hardware you'd like supported. It changes nothing about how Device Sentinel behaves; it only records.
2. Use your house normally for a few days.
3. Run three short tests and note the time of each: unplug a device for ten minutes, take a battery out until the device reads frozen, and unplug your hub for ten minutes.
4. Collect two things:
   - **The diagnostics download:** **Settings > Devices and Services > Device Sentinel**, the three dots, **Download diagnostics**.
   - **The probe log:** `stack_probe.md` from your `config/device_sentinel/` folder, with any older copies beside it (`stack_probe.md.1` to `.3`). This is where Extended Diagnostics records what your hub says about each device, and it is the file support is built from. The File editor or Samba share add-on can reach the folder. Zipping the whole folder is the simplest way to send it.
5. Open an issue titled with the hardware, for example "Extended Diagnostics: Z-Wave". Say what you tested and when, and attach both.

The [Extended Diagnostics](https://github.com/TheThinkingHome/device_sentinel/wiki/Extended-Diagnostics) page in the wiki walks through each step.

Nothing leaves your system unless you attach it yourself. Device Sentinel writes the files to your own configuration folder and sends nothing anywhere.

## What's in the File

Before you post anything, open the file in a text editor and read it. Here is what to expect in the diagnostics download.

**Never included:** passwords, tokens or other credentials, and the notification targets you set. Network addresses are replaced: a MAC address keeps only the half that names its maker, and your home network's IP addresses become stand-ins such as IP-01, the same one throughout the file.

**Included:** device and area names, makers and models, the Wi-Fi network names you chose to watch, your time zone, and the readings themselves. Names stay because a name is often what lets someone match a reading to the problem you described. If a device name says more than you'd like to share, edit it in the file before you attach it.

The probe log and the other files in your `config/device_sentinel/` folder carry device names and readings, and no passwords or tokens. If you turned on links in reports, the daily brief's links carry your Home Assistant address.

If you'd rather not post your files publicly at all, open the issue without them, and you'll be given an email address to send them to.

## Ask for Your Hub or Integration

If you run a hub or integration that Device Sentinel doesn't support yet, open an issue titled "Extend support for *name* integration" or "Extend support for *name* hub". Say what it is, what Device Sentinel does with its devices today, and what you'd like it to do.

## Tell Me What You Think

Run it for a week or two, then tell me how it went. What do you like? What don't you like? What confused you, and what did you expect it to do that it didn't? Open an issue titled "Review" and say it plainly. A short honest review is worth more than a long polite one.

## Something Not Working?

Use the bug report form. It asks for your diagnostics download (**Settings > Devices and Services > Device Sentinel**, the three dots, **Download diagnostics**), because that file answers most questions before they're asked. Say what you expected to see and what happened instead. A report with diagnostics gets fixed fastest.

## Feature Requests

Welcome, especially the real-situation kind: what happened in your home that this would have caught? Catching real failures comes first, everything else after.

## Pull Requests

Held until 1.0. Device Sentinel follows a single design under active development, and outside code, however good, would collide with work already in motion. After 1.0 this section changes.

## License

GPL-3.0-or-later. Contributions, when they open, are accepted under the same license. Copyright (C) 2026 James Lander, The Thinking Home.
