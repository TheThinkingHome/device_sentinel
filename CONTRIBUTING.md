# Contributing to Device Sentinel

Device Sentinel gets better every time it runs on a house it hasn't seen before. You don't need to write a line of code to help. Your opinion, your problem reports and your data are what shape it.

## Tell Me What You Think

Run it for a week or two, then tell me how it went. What do you like? What don't you like? What confused you, and what did you expect it to do that it didn't? Open an issue titled "Review" and say it plainly. A short honest review is worth more than a long polite one.

## Something Not Working?

Use the bug report form. It asks for your diagnostics download (**Settings > Devices and Services > Device Sentinel**, the three dots, **Download diagnostics**), because that file answers most questions before they're asked. Say what you expected to see and what happened instead. A report with diagnostics gets fixed fastest.

## Share Your Data

Some hardware can only be supported once someone has seen how it behaves on a real system. Under **Extended Diagnostics** in Device Sentinel's settings, you can turn on the hardware you'd like supported, such as Z-Wave, Matter or your router. Device Sentinel then records how it behaves, in files on your own system. Nothing is sent anywhere unless you attach it yourself.

Let it run for a few days while you use your house normally, try a few simple tests (unplug a device for ten minutes, take a battery out until the device reads frozen, unplug your hub for ten minutes), and send the files. The [Extended Diagnostics](https://github.com/TheThinkingHome/device_sentinel/wiki/Extended-Diagnostics) page in the wiki walks you through each step and lists the files to attach.

The files carry device names and readings, and never passwords, tokens or addresses. If you'd still rather not post them publicly, open the issue without them, and you'll be given an email address to send them to.

## Ask for Your Hub or Integration

If you run a hub or integration that Device Sentinel doesn't support yet, open an issue titled "Extend support for *name* integration" or "Extend support for *name* hub". Say what it is, what Device Sentinel does with its devices today, and what you'd like it to do.

## Feature Requests

Welcome, especially the real-situation kind: what happened in your home that this would have caught? Catching real failures comes first, everything else after.

## Pull Requests

Held until 1.0. Device Sentinel follows a single design under active development, and outside code, however good, would collide with work already in motion. After 1.0 this section changes.

## License

GPL-3.0-or-later. Contributions, when they open, are accepted under the same license. Copyright (C) 2026 James Lander, The Thinking Home.
