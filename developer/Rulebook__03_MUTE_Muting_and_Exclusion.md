# Device Sentinel Rulebook: Muting and Exclusion (MUTE)

*Version: rulebook, 29 October 2026, on Device Sentinel 0.27.14. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

A person makes two choices about what Device Sentinel reports. Excluding stops the watching; muting stops only the reporting. What else sets a device aside is under [WATCH](Rulebook__02_WATCH_What_Is_Watched.md). A hub's mute covering the devices it controls is under [STACK](Rulebook__08_STACK_Stacks.md). Battery mutes are also in [BAT](Rulebook__09_BAT_Battery.md), and the brief leaving out what a device is muted for is under [BRIEF](Rulebook__13_BRIEF_Daily_Brief.md).

### MUTE-01 Excluding and Muting

**Excluding a device or an integration stops the watching. Muting stops only the judging and reporting.** The settings screen holding both is Exclusions and Muting.
- **Excluding:** its devices are set aside as excluded, and nothing is learned or kept. What they had recorded is discarded at the next local midnight, so taking one back before then loses nothing.
- **Muting:** a muted device is still watched, learned and recorded, and comes back at once with its history when the mute is lifted.
- **Mute everything:** Mute everything (the Globally Muted lists) means a device is judged for nothing. That is enforced where the judging runs, not by hiding it afterwards.
- **The one exception:** the low-battery flag is still worked out and kept, and never reported, so the device comes back at once when the mute is lifted.
- **Family mutes:** each family's own mute (freeze, unavailable, battery, signal) silences that family only.
- **Model groups:** a muted device counts in its model group; an excluded one is in none.

*Proof:* [`test_exclusions.py`](../tests/test_exclusions.py), [`test_options_migration.py`](../tests/test_options_migration.py), [`test_model_groups.py`](../tests/test_model_groups.py).

### MUTE-02 Excluded Integrations

**An excluded integration's devices, their open episodes and incidents included, are discarded at the next local midnight.**
- **A new install:** the list holds mobile_app, fully_kiosk, spook and ping, the routers tplink_router and unifi, and Music Assistant, Alexa Media Player, Google Cast and the television and media integrations (music_assistant, alexa_media, cast, webostv, androidtv, androidtv_remote, samsungtv, apple_tv, dlna_dmr). On a new install, a router integration first seen, FRITZ!Box, AsusWRT and the others Device Sentinel knows as well as the two above, is added to the list.
- **A house that already exists:** nothing is added behind the person's back.
- **The list is the person's:** an integration added to the list automatically by an earlier release stays as it is, and one taken off it stays off.
- **Its card:** each integration Device Sentinel recommends excluding has its own card on the Recommendations tab, in Simple and Advanced alike ([REC-03](Rulebook__15_REC_Recommendations.md#rec-03-integrations-worth-excluding)). The card names it, says why it is usually excluded and lists its devices, with an Exclude button and a tick to keep watching it.
- **When the card shows:** the card stands while the integration has a watched device, is neither excluded nor muted for everything, and is not ticked. An exclusion taken back, or a mute lifted, brings it back; only the tick keeps it quiet.
- **In the Daily Brief:** a router integration or one of those media integrations seen for the first time is told in the Daily Brief the day it is seen, pointing to its card, unless it is muted for everything. The card itself is in the emailed Daily Brief each morning until it is answered ([REC-10](Rulebook__15_REC_Recommendations.md#rec-10-in-the-emailed-daily-brief)).
- **Ignored or disabled:** an integration entry the person ignored or disabled in Home Assistant is not seen.
- **The recommended list:** the integrations Device Sentinel recommends excluding are in one list, each group with one reason, which the Integrations tab, the Recommendations tab and the brief all read. It holds the routers and media integrations above, more media players (kodi, plex), phones, tablets and addresses that leave or sleep (mobile_app, ping, fully_kiosk), tools (spook), virtual remotes (hair, smartir, samsung_infrared), readings worked out from another device (tank_volume, thermal_comfort and Home Assistant's helpers), and a poller measured on the house ([UP-18](Rulebook__07_UP_Upstream_Outages.md#up-18-advice-on-a-noisy-integration)).
- **Printers:** a printer is not on it. One that goes off is a fault worth telling.

*Proof:* [`test_ignored_integrations.py`](../tests/test_ignored_integrations.py), [`test_first_seen_exclusions.py`](../tests/test_first_seen_exclusions.py), [`test_router_entry_disabled.py`](../tests/test_router_entry_disabled.py), [`test_exclusion_recommendations.py`](../tests/test_exclusion_recommendations.py).

### MUTE-03 Excluding One Device or One Integration

**One device can be excluded on its own, on the same terms as an integration. Taken back before midnight it loses nothing, its mutes included.**
- **Where:** in Settings under Integrations and Devices to Exclude, or from the Excluded row on its device page. One press excludes it, with no question.
- **Removed from Home Assistant:** an excluded device removed from Home Assistant is not held for 30 days. Its record and answers go with it.
- **The Excluded row:** it shows only "Exclude this device" until it is used. Then it reads "Excluded. Device Sentinel has stopped watching this device and deletes its history at midnight" and offers "Cancel the exclusion" until midnight. It says that after midnight the device is taken back in Settings, and that another listing of the same hardware may be watched instead.
- **An integration's page:** it has "Exclude this integration", or "Cancel the exclusion" when it is excluded. This writes the same setting as Settings and keeps the integration's mutes and its devices' own, as a device's exclusion does, so taking it back before midnight loses nothing. The brief records it as one row: "ZHA: excluded, from its integration page, at 9:14 AM."
- **In Simple:** Exclude this device is hidden. Exclude this integration shows in both views.

**The Integrations tab, in Simple and Advanced alike, lists each integration with five buttons on its row: Exclude, Mute everything, Mute freeze, Mute battery and Mute signal. One press sets it, with no question, and a second press undoes it.**
- **Lit buttons:** a button that is on is lit and reads with "✓ ". Mute everything lights the three single mutes and holds them, and an excluded integration's mutes rest.
- **No Mute unavailable:** there is no Mute unavailable, which is never set by integration ([MUTE-06](#mute-06-the-freeze-mute-and-the-unavailable-mute)), and an excluded integration is not muted.
- **What a press writes:** each press writes the list Settings writes and clears nothing narrower, so a second press undoes it exactly. A Settings save settles the ladder ([MUTE-04](#mute-04-the-ladder)).
- **In the brief:** each press is recorded as one row: "ZHA: muted for freeze, from the Integrations tab, at 9:14 AM."
- **Hovering Excluded:** the lit Excluded button says that the history is deleted at midnight and that pressing it again before then keeps it.
- **One device:** a single device is muted and excluded on its own page.

*Proof:* [`test_exclusions.py`](../tests/test_exclusions.py), [`test_config_screens.py`](../tests/test_config_screens.py), `check_device_actions.js`, `check_device_finders.js`, [`test_integrations_tab.py`](../tests/test_integrations_tab.py), `check_integrations_tab.js`.

### MUTE-04 The Ladder

**Each list runs broad to narrow: integration, label, device. Across screens, exclusion stands above Mute everything, which stands above each family's mute.**
- **No area, no entity:** area is never a kind, since a room reorganised for a dashboard must not change what is watched. Nothing is muted or excluded by entity.
- **What each list offers:** each integration and device list offers only what the broader ones have not caught. A label list offers all the person's labels, globally muted ones included, since Home Assistant's label picker cannot leave any out.
- **A Settings save:** each save removes a pick a broader decision already covers, across screens. An excluded integration clears its own mutes and its devices' picks, and a globally muted integration, label or device clears the family mutes it covers.
- **What clears nothing:** a device excluded on its own clears nothing, and neither does a press on an integration's page or the Integrations tab. Their mutes are kept, so taking it back before midnight loses none ([MUTE-03](#mute-03-excluding-one-device-or-one-integration)).
- **Where a pick is removed:** only where its coverage is shown. An excluded integration clears no label, since a label spans integrations.
- **Undoing:** a removed pick does not come back when the broader decision is undone, so an integration taken back from exclusion is watched and reported, not muted.

*Proof:* [`test_exclusions.py`](../tests/test_exclusions.py), [`test_stale_picks.py`](../tests/test_stale_picks.py).

### MUTE-05 A Label Mutes Devices

**A muted label mutes the devices that carry it, and nothing else. A label on a single entity mutes nothing.**

*Proof:* [`test_classification_sources.py`](../tests/test_classification_sources.py).

### MUTE-06 The Freeze Mute and the Unavailable Mute

**A freeze mute silences frozen and never reported, and nothing else. An unavailable mute silences unavailable and dropping out only. To silence both, set both.**
- **Freeze mute:** set by integration, label, device or hub. A freeze-muted device is still listed and pushed when it becomes unavailable or drops out (its main entities unavailable, an ESPHome connection dropped, a Z-Wave node dead, a Lutron hub down).
- **Unavailable mute:** set by label or device, never by integration. A device muted only for unavailable that goes quiet is still listed frozen.
- **The settings screen:** Freeze and Unavailable Detection, with a Freeze Muting section and an Unavailable Muting section. Both name dropping out.
- **Upgrading:** at the first start of 0.26.6 or later on an install from 0.26.5 or earlier, each label and device muted for freeze is muted for unavailable as well, once. An integration muted for freeze stays freeze only.

*Proof:* [`test_freeze_and_unavailable_mutes.py`](../tests/test_freeze_and_unavailable_mutes.py), [`test_freeze_unavailable_split.py`](../tests/test_freeze_unavailable_split.py).

### MUTE-07 A Mute Is Silent and Immediate

**Muting takes a device off the Problem List at once for what the mute covers, with no notification.** A freeze mute leaves an unavailable device listed ([MUTE-06](#mute-06-the-freeze-mute-and-the-unavailable-mute)).
- **Not a recovery:** a mute is a person's act. An item that leaves the list because a mute of any kind, or its device's Mute everything, covers it leaves with no phone push, no recovery on the bus, and no "recovered" in the brief or the record.
- **In the brief:** the brief records where the mute was pressed, on the device's line: "from its device page", "from the Recommendations tab" or "from the Problem List". That line stays unless the device is muted for everything, which leaves all its rows out of the brief (see [BRIEF](Rulebook__13_BRIEF_Daily_Brief.md)).

*Proof:* [`test_exclusions.py`](../tests/test_exclusions.py), [`test_freeze_and_unavailable_mutes.py`](../tests/test_freeze_and_unavailable_mutes.py), [`test_device_actions.py`](../tests/test_device_actions.py), `check_recommendations.js`.

### MUTE-08 Lifting a Mute

**When a mute is lifted on a device that is still down, the device is listed again from when its trouble began, and pushed again. That start is worked out, not kept.**
- **Where it starts:** unavailable from the saved outage start; frozen from the last report plus its window (counting only time Device Sentinel was listening); never reported from first seen plus the wait.
- **A hidden outage:** an unavailable outage the mute hid is listed unavailable on the lift even if its entities have since turned unknown, unless Home Assistant restarted in between. Then the device is listed by its clock.
- **Down another way:** muting one kind on a device that is down another way lists it as that kind, with one push.
- **Set once:** mutes are meant to be set once to quiet a noisy device. Muting and unmuting a device while it is in trouble can leave it listed oddly, and that is accepted.

*Proof:* [`test_freeze_and_unavailable_mutes.py`](../tests/test_freeze_and_unavailable_mutes.py).

### MUTE-09 Mutes on the Device Page and the Problem List

**The device page's Muted row carries Mute freeze, Mute unavailable, Mute battery, Mute signal and Mute everything. Each mute is one press, with no question, and a second press lifts it.**
- **What the buttons show:** only the device's own mutes, so every lit button lifts its mute when pressed. A lit button is filled and reads with "✓ " before its name, and its hover reads "Muted. Press to lift the mute." There is no "nothing".
- **Set by a label, an integration or a hub:** such a mute, Mute everything included, lights no button. A line says where it came from and where it is changed: an integration's on the Integrations tab, a hub's on the hub's page. A label's reads "Remove the label above to lift it for this device, or change it in Device Sentinel's settings", with the settings section for its kind: Exclusions and Muting, Freeze and Unavailable Detection, Low Battery or Signal Strength. In Simple it reads "Switch to Advanced to change it." ([DASH-04](Rulebook__14_DASH_Dashboard.md#dash-04-what-simple-shows)).
- **The label that mutes:** in Advanced the Labels row draws it lit. Its × takes the label off this device in Home Assistant, which lifts the mute for this device only; its hover says so.
- **A device's own mute under a broader one:** it still lights its button, and pressing it lifts only the device's own. Under a label the line reads "… is also muted by the label Outdoor, which stays when you lift your own."; under an integration it names the integration. A hub's mute is not named while the device has its own.
- **Mute everything:** set on the device, it shows the four single mutes lit and held.
- **Label mutes:** they are made and lifted in settings only. The device page offers no Mute by label.
- **On the Problem List:** beside each item sits only the mute that matches its problem. Frozen and never reported take the freeze mute, unavailable and dropping out the unavailable mute, then battery and signal.
- **In Simple:** the mute buttons show in Simple as well as Advanced.

*Proof:* [`test_device_actions.py`](../tests/test_device_actions.py), [`test_freeze_unavailable_split.py`](../tests/test_freeze_unavailable_split.py), `check_device_actions.js`, `check_names_and_mutes.js`, `check_mutes_shown.js`, `check_simple_dashboard.js`.

### MUTE-10 How Mutes Are Named

**A device's mutes are tagged by kind, and the mute text names each kind and its source.**
- **Tags:** "Muted (FRZ)", "Muted (UNAV)" or "Muted (FRZ, UNAV)", with BAT and SIG for the battery and signal mutes, and "Muted (GLB)" alone for Mute everything.
- **Mute text:** for example "freeze (device); unavailable (device)".
- **Flapping:** a device muted for unavailable or for everything shows no flapping status. A device muted only for freeze that keeps dropping out is still listed ([MUTE-06](#mute-06-the-freeze-mute-and-the-unavailable-mute)).

*Proof:* [`test_freeze_and_unavailable_mutes.py`](../tests/test_freeze_and_unavailable_mutes.py), [`test_freeze_unavailable_split.py`](../tests/test_freeze_unavailable_split.py), [`test_reports.py`](../tests/test_reports.py), [`test_integration_names.py`](../tests/test_integration_names.py).
