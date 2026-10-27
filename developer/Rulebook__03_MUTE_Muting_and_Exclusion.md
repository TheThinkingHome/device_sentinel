# Device Sentinel Rulebook: Muting and Exclusion (MUTE)

*Version: rulebook, 27 October 2026, on Device Sentinel 0.27.10. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

The two choices a person makes about what Device Sentinel reports: excluding, which stops the watching, and muting, which stops only the reporting. What else sets a device aside is under [WATCH](Rulebook__02_WATCH_What_Is_Watched.md). A hub's mute covering the devices it controls is under [STACK](Rulebook__08_STACK_Stacks.md); battery mutes are also in [BAT](Rulebook__09_BAT_Battery.md); the brief leaving out what a device is muted for is under [BRIEF](Rulebook__13_BRIEF_Daily_Brief.md).

### MUTE-01 Excluding and Muting

**Excluding a device or an integration stops the watching: its devices are set aside as excluded, nothing is learned or kept, and what they had recorded is discarded at the next local midnight, so taking one back before then loses nothing. Muting stops only the judging and reporting: a muted device is still watched, learned and recorded, and comes back at once with its history when the mute is lifted. Mute everything (the Globally Muted lists) means a device is judged for nothing, and that is enforced where the judging runs, not by hiding it afterwards. The one exception is the low-battery flag: it is still worked out and kept, and never reported, so the device comes back at once when the mute is lifted. Each family's own mute (freeze, unavailable, battery, signal) silences that family only. A muted device counts in its model group; an excluded one is in none. The settings screen holding both is Exclusions and Muting.**

*Proof:* [`test_exclusions.py`](../tests/test_exclusions.py), [`test_options_migration.py`](../tests/test_options_migration.py), [`test_model_groups.py`](../tests/test_model_groups.py).

### MUTE-02 Excluded Integrations

**An excluded integration's devices, their open episodes and incidents included, are discarded at the next local midnight. A new install's list holds mobile_app, fully_kiosk, spook and ping, the routers tplink_router and unifi, and Music Assistant, Alexa Media Player, Google Cast and the television and media integrations (music_assistant, alexa_media, cast, webostv, androidtv, androidtv_remote, samsungtv, apple_tv, dlna_dmr). On a house that already exists, nothing is added behind the person's back: a router integration or one of those media integrations, seen and not on the list, raises a card on the Recommendations tab, in Simple and Advanced alike, naming it, saying why it is usually excluded and listing its devices, with an Exclude button and a tick to keep watching it. The Daily Brief says once that the card is there. Once excluded or ticked, the card does not come back. An integration added to the list automatically by an earlier release stays as it is; the list is the person's, and one taken off it stays off. An integration entry the person ignored or disabled in Home Assistant is not seen.**

*Proof:* [`test_ignored_integrations.py`](../tests/test_ignored_integrations.py), [`test_first_seen_exclusions.py`](../tests/test_first_seen_exclusions.py).

### MUTE-03 Excluding One Device or One Integration

**One device can be excluded on its own, in Settings under Integrations and Devices to Exclude or from the Excluded row on its device page, on the same terms as an integration; taken back before midnight it loses nothing, its mutes included. An excluded device removed from Home Assistant is not held for 30 days: its record and answers go with it. The page asks once before excluding and says that after midnight the device is taken back in Settings, and that another listing of the same hardware may be watched instead. The Excluded row shows only "Exclude this device" until it is used; then it reads "Excluded. Device Sentinel has stopped watching this device and deletes its history at midnight" and offers "Cancel the exclusion" until midnight. An integration's page has "Exclude this integration", or "Cancel the exclusion" when it is excluded, which writes the same setting as Settings and settles the ladder ([MUTE-04](#mute-04-the-ladder)); the brief records it as one row: "ZHA: excluded, from its integration page, at 9:14 AM." In Simple, both exclude buttons are hidden.**

*Proof:* [`test_exclusions.py`](../tests/test_exclusions.py), [`test_config_screens.py`](../tests/test_config_screens.py), `check_device_actions.js`, `check_device_finders.js`.

### MUTE-04 The Ladder

**Each list runs broad to narrow: integration, label, device. Area is never a kind, since a room reorganised for a dashboard must not change what is watched, and nothing is muted or excluded by entity. Across screens, exclusion stands above Mute everything, which stands above each family's mute. Each integration and device list offers only what the broader ones have not caught; a label list offers all the person's labels, globally muted ones included, since Home Assistant's label picker cannot leave any out. Each save removes a pick a broader decision already covers, across screens: an excluded integration clears its own mutes and its devices' picks, and a globally muted integration, label or device clears the family mutes it covers. A device excluded on its own clears nothing: its mutes are kept, so taking it back before midnight loses none ([MUTE-03](#mute-03-excluding-one-device-or-one-integration)). A pick is removed only where its coverage is shown; an excluded integration clears no label, since a label spans integrations. A removed pick does not come back when the broader decision is undone, so an integration taken back from exclusion is watched and reported, not muted.**

*Proof:* [`test_exclusions.py`](../tests/test_exclusions.py), [`test_stale_picks.py`](../tests/test_stale_picks.py).

### MUTE-05 A Label Mutes Devices

**A muted label mutes the devices that carry it, and nothing else. A label on a single entity mutes nothing.**

*Proof:* [`test_classification_sources.py`](../tests/test_classification_sources.py).

### MUTE-06 The Freeze Mute and the Unavailable Mute

**A freeze mute, by integration, label, device or hub, silences frozen and never reported and nothing else: a freeze-muted device is still listed and pushed when it becomes unavailable or drops out (its main entities unavailable, an ESPHome connection dropped, a Z-Wave node dead, a Lutron hub down). An unavailable mute, by label or device and never by integration, silences unavailable and dropping out only; a device muted only for unavailable that goes quiet is still listed frozen. To silence both, set both. The settings screen is Freeze and Unavailable Detection, with a Freeze Muting section and an Unavailable Muting section, and both name dropping out. At the first start of 0.26.6 or later on an install from 0.26.5 or earlier, each label and device muted for freeze is muted for unavailable as well, once; an integration muted for freeze stays freeze only.**

*Proof:* [`test_freeze_and_unavailable_mutes.py`](../tests/test_freeze_and_unavailable_mutes.py), [`test_freeze_unavailable_split.py`](../tests/test_freeze_unavailable_split.py).

### MUTE-07 A Mute Is Silent and Immediate

**Muting takes a device off the Problem List at once for what the mute covers, with no notification; a freeze mute leaves an unavailable device listed ([MUTE-06](#mute-06-the-freeze-mute-and-the-unavailable-mute)). A mute is a person's act, not a recovery: an item that leaves the list because a mute of any kind, or its device's Mute everything, covers it leaves with no phone push, no recovery on the bus, and no "recovered" in the brief or the record. The brief records where the mute was pressed, on the device's line: "from its device page", "from the Recommendations tab" or "from the Problem List". That line stays unless the device is muted for everything, which leaves all its rows out of the brief (see [BRIEF](Rulebook__13_BRIEF_Daily_Brief.md)).**

*Proof:* [`test_exclusions.py`](../tests/test_exclusions.py), [`test_freeze_and_unavailable_mutes.py`](../tests/test_freeze_and_unavailable_mutes.py), [`test_device_actions.py`](../tests/test_device_actions.py), `check_recommendations.js`.

### MUTE-08 Lifting a Mute

**A lifted mute lists a device that is still down again from when its trouble began, worked out rather than kept, and pushes again: unavailable from the saved outage start, frozen from the last report plus its window (counting only time Device Sentinel was listening), never reported from first seen plus the wait. An unavailable outage the mute hid is listed unavailable on the lift even if its entities have since turned unknown, unless Home Assistant restarted in between; then the device is listed by its clock. Muting one kind on a device that is down another way lists it as that kind, with one push. Mutes are meant to be set once to quiet a noisy device; muting and unmuting a device while it is in trouble can leave it listed oddly, and that is accepted.**
*Proof:* [`test_freeze_and_unavailable_mutes.py`](../tests/test_freeze_and_unavailable_mutes.py).

### MUTE-09 Mutes on the Device Page and the Problem List

**The device page's Muted row carries Mute freeze, Mute unavailable, Mute battery, Mute signal and Mute everything, each a toggle. A mute that is on is filled and reads with "✓ " before its name; there is no "nothing". A mute set by a label or an integration, Mute everything included, shows lit and fixed, and says where it came from and the settings section that changes it: Exclusions and Muting, Freeze and Unavailable Detection, Low Battery or Signal Strength. Mute everything, once on, shows the four single mutes lit and fixed. Mute everything asks before it is set. In Advanced the row also offers "Mute by label": one of the person's labels, or a new one, muted for one kind in the lists Settings writes, with the count of devices carrying it shown before it saves. Beside each Problem List item sits only the mute that matches its problem: frozen and never reported take the freeze mute, unavailable and dropping out the unavailable mute, then battery and signal. The mute buttons show in Simple as well as Advanced.**

*Proof:* [`test_device_actions.py`](../tests/test_device_actions.py), [`test_mute_by_label.py`](../tests/test_mute_by_label.py), [`test_freeze_unavailable_split.py`](../tests/test_freeze_unavailable_split.py), `check_device_actions.js`, `check_names_and_mutes.js`, `check_mutes_shown.js`, `check_simple_dashboard.js`.

### MUTE-10 How Mutes Are Named

**A device's mutes are tagged "Muted (FRZ)", "Muted (UNAV)" or "Muted (FRZ, UNAV)", with BAT and SIG for the battery and signal mutes and "Muted (GLB)" alone for Mute everything. The mute text names each kind and its source, "freeze (device); unavailable (device)". A device muted for unavailable or for everything shows no flapping status; a device muted only for freeze that keeps dropping out is still listed ([MUTE-06](#mute-06-the-freeze-mute-and-the-unavailable-mute)).**

*Proof:* [`test_freeze_and_unavailable_mutes.py`](../tests/test_freeze_and_unavailable_mutes.py), [`test_freeze_unavailable_split.py`](../tests/test_freeze_unavailable_split.py), [`test_reports.py`](../tests/test_reports.py), [`test_integration_names.py`](../tests/test_integration_names.py).
