# Device Sentinel Rulebook: Daily Brief (BRIEF)

*Version: rulebook, 27 October 2026, on Device Sentinel 0.27.10. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

The Daily Brief: what it says and in what order, how In Short tells a day, the tables, how causes are named, when and where it is sent, the links in it, and the maintainer files written beside it in `/config/device_sentinel/`. The brief's battery lines (Batteries falling faster each week, Batteries to Watch) are under [BAT](Rulebook__09_BAT_Battery.md), its Recommendations section under [REC](Rulebook__15_REC_Recommendations.md), and phone pushes and the Problem List under [NOTE](Rulebook__12_NOTE_Notifications.md) and LIST. What a mute covers is under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md).

### BRIEF-01 What the Brief Is

**The Daily Brief is a report for a person, not a diagnostic dump: plain language, human units, and none of the machinery (basis, window, lag, learning). It reads, in order: a line saying the hours it covers, In Short, Now (a table of what needs attention, with SINCE and FOR), Repeat Offenders, the battery lines (BAT), Recommendations (REC) and Last 24 Hours. An acknowledged problem is absent from Now, In Short and Last 24 Hours (see [NOTE](Rulebook__12_NOTE_Notifications.md)); Repeat Offenders keeps the device, since it shows a seven-day pattern. The rows a device's mutes cover are absent too ([BRIEF-08](#brief-08-what-a-mute-leaves-out)).**

*Proof:* [`test_brief_wording.py`](../tests/test_brief_wording.py), [`test_brief_window.py`](../tests/test_brief_window.py).

### BRIEF-02 In Short

**In Short is written to be read, not scanned. It opens with the storage restore sentence on a day a restore happened (see [STOR](Rulebook__18_STOR_Storage.md)), then tells the house's events, then the window's history as episodes in the order each began ("Since …"), with the sentences for a device dropping out and for a stitched silence ([BRIEF-06](#brief-06-a-device-that-goes-and-returns)) last, then what stands ("Right now: …"): devices oldest problem first, and each device's problems worst first inside its line. A stop and its recovery are one sentence, with the recovery's clock time left to the table; a device that has never reported does not pair. With no device incidents in the window it says "No device problems started or ended in this window."; with nothing standing, "Nothing needs attention right now." In Short is never capped: it names each device, where a push names three and counts the rest (see [NOTE](Rulebook__12_NOTE_Notifications.md)). A sentence in it that reads badly is fixed when it is seen; In Short is not searched for rewording.**

*Proof:* [`test_brief_wording.py`](../tests/test_brief_wording.py).

### BRIEF-03 House Events in In Short

**In Short tells what is abnormal and the tables tell everything. A restart, a bridge outage or a broker outage earns a sentence only by lasting five minutes or more, and then only the longest of each is told, with its length and its time. A clean stop reads "The system was shut down cleanly and was unwatched for …, ending …". An unclean stop is abnormal in itself, so each one is told whatever its length, outside the choice of the longest restart, and it says what it cost and stops: "Home Assistant did not shut down cleanly at …: 2m went unwatched and 96 devices had their silence timers restarted." Two things are never left out, no matter how often they happen: a settings change, and a storm, grouped per integration and named as Home Assistant shows it ("The TP-Link Router integration reloaded 20 times between 12:50 PM and 1:56 PM, the largest affecting 5 devices."). A storm run inside one minute reads "The ZHA integration reloaded 3 times at 5:11 PM, the largest affecting 41 devices." An integration recognised as a synchronized poller writes no storm event, so its storms are not told at all (see [UP](Rulebook__07_UP_Upstream_Outages.md)).**

*Proof:* [`test_brief_wording.py`](../tests/test_brief_wording.py), [`test_attribution.py`](../tests/test_attribution.py).

### BRIEF-04 Paired Events and Storms Inside a Restart

**An event recorded in two halves is told in both or neither: a storm whose opening fell inside the startup grace loses its closing too. An ending whose beginning fell before the window is not told in In Short; Last 24 Hours, being the log, lists it. A storm inside a restart is the restart, and is left out of In Short and Last 24 Hours alike, decided by the same matching the incidents use rather than a threshold of its own.**

*Proof:* [`test_brief_wording.py`](../tests/test_brief_wording.py), [`test_attribution.py`](../tests/test_attribution.py).

### BRIEF-05 What Explains an Incident

**An incident is matched to a recorded event whose window overlapped it and whose scope covers the device: a restart covers each device, a broker the MQTT devices, a bridge or a pairing window its own stack's devices, an integration outage or a storm its own integration's devices, a Wi-Fi outage each device, and a person handling a ZHA device that device alone. Where several match, the one already in effect when the device went quiet wins, and the earliest of those; where none was, one covering the recovery is used. Each outage kind the brief announces takes part in this matching, so its devices are never counted as mysteries. Devices one event took down are told as one sentence ("2 devices became unavailable at 3:35 PM, with a restart.") while the table still lists each. A restart or an outage is never credited with a recovery.**

*Proof:* [`test_attribution.py`](../tests/test_attribution.py), [`test_forward_outage_shape.py`](../tests/test_forward_outage_shape.py).

### BRIEF-06 A Device That Goes and Returns

**A device interrupted twice or more in the window is one sentence with the count and the total ("went silent twice and recovered each time, silent for 3.0h in total", or still down where the last has not returned), one sentence per kind, and a rail reads "signal railed" or "railed", never silent. A sentence is dropped for this only when each device behind it is already told this way. A row recording a person's act (an acknowledgment, a deletion, a re-addition) is never counted as a device failing and never joins a group. A silence the restarts only segmented is told as one silence, with its true start and span: a device is stitched when something in the window claimed a recovery and the device still holds a standing verdict that began before the window's earliest interruption, frozen, unavailable and unknown judged together as one pile, and the rows behind it leave Last 24 Hours. A device that has never reported keeps its own sentence.**

*Proof:* [`test_brief_wording.py`](../tests/test_brief_wording.py), [`test_brief_stitching.py`](../tests/test_brief_stitching.py), [`test_flapping.py`](../tests/test_flapping.py).

### BRIEF-07 Last 24 Hours

**Last 24 Hours is the tester's log: each device incident and house event in the window, newest first, with its time to the second, while the summary above keeps minutes. A device that became unavailable or unknown is timed from when it went, if that was within 15 minutes of its listing. In Short and the dashboard date it the same way. A Wi-Fi outage's recovery beginning and stalling each get a row, and the row that closes the outage says it ended. Each act a person takes on a device (a mute, an exclusion, a sensor turned on, a power source or a type set) is one row on the device's own line, saying where it was done: "from its device page", "from the Recommendations tab" or "from the Problem List"; a page mute's options stay out of the Settings changed row. A battery change and a device handled by hand go on the device's own line here and on the Daily Brief tab. A setting a person changed is named by the label its own screen carries, in In Short, in this table and on the Daily Brief tab alike.**

*Proof:* [`test_brief_log.py`](../tests/test_brief_log.py), [`test_device_actions.py`](../tests/test_device_actions.py), [`test_device_handled.py`](../tests/test_device_handled.py), [`test_unavailable_opening_time.py`](../tests/test_unavailable_opening_time.py), [`test_action_source.py`](../tests/test_action_source.py), [`test_settings_change_words.py`](../tests/test_settings_change_words.py).

### BRIEF-08 What a Mute Leaves Out

**Last 24 Hours, Repeat Offenders, In Short and the dashboard's Daily Brief tab leave out a device's rows of the kinds its mutes cover, read as the device is muted today: Mute everything each kind, a freeze mute frozen and never reported, an unavailable mute unavailable, unknown and dropping out, and the battery and signal mutes their own. The row saying a device was muted stays, unless it is muted for everything. House events are never left out for a device's mute.**

*Proof:* [`test_brief_mutes.py`](../tests/test_brief_mutes.py).

### BRIEF-09 Repeat Offenders

**Repeat Offenders is a table under its own heading below Now, with DEVICE, WHAT HAPPENED, TIMES, WHEN, TYPICAL and WITH. It lists devices that failed in one way, with nothing to explain it, as often in the last seven days as Repeat Offender Threshold asks (two by default; see [CFG](Rulebook__17_CFG_Settings.md)). A device whose whole pattern is today, and already told in In Short, is left off. WITH names a device that failed in the same second more than once, since one shared second is not a pattern; where the device has only one failure, a partner in that one is named. It says "every time" only when the partner matched each time. The paragraph beneath it is James's and states the seven days the code reads. The section is left out when it is empty.**

*Proof:* [`test_brief_wording.py`](../tests/test_brief_wording.py), [`test_attribution.py`](../tests/test_attribution.py), [`tools/panel_checks/check_repeat_offenders.js`](../tools/panel_checks/check_repeat_offenders.js).

### BRIEF-10 The Window

**A sent brief covers the time from the last brief time to this one, and its first line counts the hours it covers, 23 or 25 across a daylight saving change. Between sends the file carries a rolling day, the last 24 hours, marked "(in progress)" with its span stated. Now is read from the Problem List, so it is current either way.**

*Proof:* [`test_brief_window.py`](../tests/test_brief_window.py).

### BRIEF-11 When and Where It Is Sent

**The brief is sent at When to Send It. How Often decides whether it goes: Every Day, with an All-Clear When Nothing Needs Attention; Only When Something Needs Attention; or Never. The file is written either way. Quiet hours do not hold the file or its sending, because the brief carries what quiet hours held back. Only the brief that closes a window is sent, once, and never one written by a start, a regenerate or a midnight rewrite. It is one document, the same for each target, and it goes only to Send the Full Brief To, its own list for email and other services that carry the whole document, empty by default; the high-priority and normal-priority targets receive pushes, never the brief (see [NOTE](Rulebook__12_NOTE_Notifications.md)). Mail goes through Home Assistant's own services, never by Device Sentinel itself. An SMTP recipient is offered as its notify entity and sent the page through smtp.send_message; an old-style notify action already chosen keeps working until Home Assistant removes it. A brief time inside the hour daylight saving repeats sends one brief, and one inside the hour it skips still sends that day's.**

*Proof:* [`test_brief_email.py`](../tests/test_brief_email.py), [`test_smtp_brief.py`](../tests/test_smtp_brief.py), [`test_notifications.py`](../tests/test_notifications.py), [`test_brief_window.py`](../tests/test_brief_window.py), [`test_priority_targets.py`](../tests/test_priority_targets.py).

### BRIEF-12 One Page, Sent as Written

**The brief is one HTML page, `daily_brief.html`, rendered once from the composed text by one renderer, which escapes what it renders, so a device name cannot carry markup. The emailed body is that page as written to disk, and it is used only when it was rendered from the very text being sent; otherwise the text is rendered again. The composed text is the persistent notification's body and the plain body for services without HTML.**

*Proof:* [`test_brief_email.py`](../tests/test_brief_email.py), [`test_hostile_names.py`](../tests/test_hostile_names.py).

### BRIEF-13 Links in the Brief

**Links in Reports decides whether device names are links: None, Internal URL or External URL, defaulting to None. Each choice shows the address it would publish, and one Home Assistant does not hold is refused. It governs strictly: None prints names plain, Internal uses only the internal address, External only the external one, and a chosen address later removed prints names plain. A device's link opens its page on the Device Sentinel dashboard, /device-sentinel/device/<id>. The area beside a name is not an address, so this setting never withholds it; it is left out only where the name already ends in a bracket, as "Soil Moisture (Monstera)" does.**

*Proof:* [`test_www_retired.py`](../tests/test_www_retired.py), [`test_device_labels.py`](../tests/test_device_labels.py), [`test_settings.py`](../tests/test_settings.py).

### BRIEF-14 Where the Files Live

**The brief and the maintainer files are written to `/config/device_sentinel/`, which Home Assistant does not serve: `daily_brief.html`, `device_telemetry.md`, `classification.md` and `silence_episodes.md`. Nothing is written under www, and at each start a `www/device_sentinel/` folder left from an older release is deleted whole, after its current brief is copied out unless one is already in place. No dated copies are kept. Each file is written to a temporary name beside it and moved into place, so a reader never meets half a file. Square brackets, pipes and angle brackets in a name are escaped in the raw files, so a name reads `\[LG\] webOS TV` there, and a line break in a name becomes a space.**

*Proof:* [`test_www_retired.py`](../tests/test_www_retired.py), [`test_report_thread_race.py`](../tests/test_report_thread_race.py), [`test_hostile_names.py`](../tests/test_hostile_names.py), [`test_reports.py`](../tests/test_reports.py).

### BRIEF-15 The Device Telemetry File

**`device_telemetry.md` opens with Devices With A Fault: each device with a fault, grouped Freeze, Dropping Out, Battery, Signal, alphabetical within each, the header counting distinct devices. Each line carries the fault, its age from that family's own start, and the Problem List state: [○ open], [✓ acknowledged] or [✗ removed from list]; an acknowledged fault is shown, since the checkbox silences notifications, never diagnostics. The STATUS column reads plain grammar, Reported or Muted with its reasons. GAPS shows the last 14 days' longest gaps. The 14-Day Trimmed Maximum is bold inside that series and the day it sets aside is struck. Beside it, TRIMMED and LOG-NORMAL give the two rhythms, and RULE IN USE names the shorter one. In SIGNAL the lowest of the 30 days is bold at its first appearance, and each bad signal day is struck, the lowest day included (see [SIG](Rulebook__10_SIG_Signal.md)).**

*Proof:* [`test_reports.py`](../tests/test_reports.py), [`test_flapping.py`](../tests/test_flapping.py).

### BRIEF-16 The Silence Episodes File

**`silence_episodes.md` records each silence that has spent half the device's own patience: the rhythm in use (the shorter of its two rhythms, see [FRZ](Rulebook__05_FRZ_Freeze.md)) plus half the way to its freeze line, so an episode always opens before the device is called frozen. No house-wide threshold opens one. An episode closes as resumed or as ended by an intervention, with the lag from that intervention to the device's next real report. It explains freeze verdicts and decides nothing. A device muted for everything or for freeze, or judged by its hub, opens no episode. Rows are kept fourteen days, and the header names when the newest row opened, so an empty stretch reads differently from a stopped recorder.**

*Proof:* [`test_reports.py`](../tests/test_reports.py), [`test_journal.py`](../tests/test_journal.py).
