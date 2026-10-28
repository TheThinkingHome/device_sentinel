# Device Sentinel Rulebook: Storage (STOR)

*Version: rulebook, 28 October 2026, on Device Sentinel 0.27.13. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

What Device Sentinel keeps on disk, how each file is written, checked, backed up and repaired, how long things are kept, what the diagnostics download carries, and what removing the integration deletes. The Storage Write Interval and How Much History to Keep are set on the Advanced screen (CFG); the Data Trim tool is [CFG-10](Rulebook__17_CFG_Settings.md#cfg-10-data-trim). The repair cards themselves are under [REP](Rulebook__16_REP_Repairs.md); the brief's sentences about storage are under [BRIEF](Rulebook__13_BRIEF_Daily_Brief.md).

### STOR-01 The Files

**Device Sentinel keeps four files in Home Assistant's `.storage` folder: the main file (`device_sentinel.storage`), which holds the last 30 days of each daily history, the tables and the to-do list; the history file (`device_sentinel.history`), which holds each daily history older than its newest 30 entries, up to the retention, and the house's events and signal stress rows older than the line set at each fold; the clocks file (`device_sentinel.clocks`), which holds the fast-changing activity clocks and the day's running figures; and the answers file (`device_sentinel.answers`), which holds what owners tell Device Sentinel: the pencil answers, the ticked rows and the battery replacement dates ([STOR-20](#stor-20-the-answers-file)). The main file never carries the clocks. Copies taken before a repair or a trim go to `config/device_sentinel/trim_backups`.**

*Proof:* [`test_storage_split.py`](../tests/test_storage_split.py), [`test_clock_strip.py`](../tests/test_clock_strip.py), [`test_history_file.py`](../tests/test_history_file.py), [`test_answers_store.py`](../tests/test_answers_store.py).

### STOR-02 When the Files Are Written

**Routine activity is held in memory and written once per Storage Write Interval (1 to 60 minutes, default 15): the clocks file each time, and the main file only when a log row is waiting. Anything that carries a judgment is written at once to both files, main file first: a freeze verdict, a battery change of state, a Problem List change, an acknowledgment, a settings change, midnight and a stop. One scheduler writes both files, so the clocks file is always the newer of the pair. A clean stop always writes both itself, main file first. Through the day the history file is not written; it is written only when its part changes ([STOR-03](#stor-03-the-history-file)).**

*Proof:* [`test_storage_timing.py`](../tests/test_storage_timing.py), [`test_storage_split.py`](../tests/test_storage_split.py), [`test_shutdown_flush.py`](../tests/test_shutdown_flush.py), [`test_settings.py`](../tests/test_settings.py).

### STOR-03 The History File

**At each save, the part of storage older than each history's newest 30 entries (and the house's events and signal stress rows older than a line set at each fold) is compared with what was last written, and the history file is written only if it differs: at the fold, and after a trim, an exclusion delete or a lowered retention. A history write runs four steps: the history file is renamed to its last-good copy, the new one is written and read back, the main file is written recording the history file's generation number, and the new history file is copied over its last-good copy; after a clean save the new main file is copied over its own last-good, so all four files hold one generation. At each start the load joins the history copy whose generation matches the main file, and a good copy is written over the other where they differ. A bad live file, or a pair whose generations do not match, restores the last-good set: the main file's last-good joined with the history copy of the same generation. With no matching copy, Device Sentinel starts with the main file's 30 days, never doubling a day, and says so as [STOR-12](#stor-12-no-silent-repair) sets out. There is no rollback below 0.26.2: an older release reads only the main file and runs on 30 days.**

*Proof:* [`test_history_file.py`](../tests/test_history_file.py), [`test_history_file_disk.py`](../tests/test_history_file_disk.py), [`test_history_file_campaign.py`](../tests/test_history_file_campaign.py), [`test_history_file_hostile.py`](../tests/test_history_file_hostile.py).

### STOR-04 Last-Good Copies

**Before each clean save of the main file, the live file is renamed to last-good and the new file put in place by Home Assistant's own safe write. A clean save is one whose outgoing file holds no faults; a save that repaired anything, and the first save after a load that needed a restore or repair, leaves last-good alone. So last-good is always the latest file that was clean when written, and freezes at it while the files are not clean. An empty file is never a clean save over a last-good that holds devices. The clocks file has no last-good copy; the history file's is kept as [STOR-03](#stor-03-the-history-file) says, and the answers file's as [STOR-20](#stor-20-the-answers-file) says.**

*Proof:* [`test_backup_integrity.py`](../tests/test_backup_integrity.py), [`test_restore.py`](../tests/test_restore.py), [`test_history_file_disk.py`](../tests/test_history_file_disk.py), [`test_routine_save_checked.py`](../tests/test_routine_save_checked.py).

### STOR-05 The Shape Check at Load

**Each start checks the file in two steps. The first, before any upgrade step reads the file, checks the containers: that the devices are a table, each record is a record, the list fields and tables are lists, and the top-level values have their kinds. The second, after the upgrade steps and the clocks merge and before anything else reads the file, checks each record field and each table row. A field is checked against each value Device Sentinel can write into it, and a time that says when a row happened may not be empty. An open silence episode, still waiting for its end, is not damage. An unknown field inside a row is passed over; each top-level key has a shape, and a key without one is a fault in the check, caught by a test.**

*Proof:* [`test_storage_shape.py`](../tests/test_storage_shape.py), [`test_storage_tables.py`](../tests/test_storage_tables.py), [`test_verify_restore.py`](../tests/test_verify_restore.py).

### STOR-06 Checked as Written and at Save

**A table row is checked the moment it is written, and refused there if its shape is wrong, while the writer carries on. Each save of the main file checks the whole outgoing file, which catches a row changed in place after it was written; such a row is seen only at the next save. No reader carries a guard of its own. A value of the right shape that is possible ([STOR-07](#stor-07-values-held-to-what-is-possible)) but wrong for the house passes each check; that is left to the test campaigns.**

*Proof:* [`test_storage_shape.py`](../tests/test_storage_shape.py), [`test_storage_tables.py`](../tests/test_storage_tables.py), [`test_routine_save_checked.py`](../tests/test_routine_save_checked.py).

### STOR-07 Values Held to What Is Possible

**Each stored value is held to what is possible, at load and at save: a moment from 2020 to 2100, a span up to 360 days, a battery level 0 to 100, a signal reading -130 to 255, a spread of signal readings 0 to 400, a count from zero to a trillion, any other number within a trillion either way. An impossible value is repaired as a wrong kind is ([STOR-09](#stor-09-damage-is-repaired-where-it-is-found)). A report that fails is logged and skipped, and the rest of the brief goes on.**

*Proof:* [`test_storage_shape.py`](../tests/test_storage_shape.py), [`test_reports.py`](../tests/test_reports.py).

### STOR-08 A Main File That Cannot Be Read

**A main file that is missing, or that Home Assistant could not parse and set aside as `.corrupt`, is replaced from last-good and the start goes on; nobody is asked. This is judged on what is found, not on an error: an empty load with a last-good that holds devices is a lost file, never a first install, and the `.corrupt` file is copied into trim_backups as evidence. A copy that does not parse, or holds no devices, is never written over the live file; one attempt, no retry. An empty load with no usable copy starts as a first install. A file that cannot be read at all, through a disk or permission fault, with no copy that helps, stops setup with a sentence naming the file, saying nothing was changed, and giving the two ways forward. A restore raises the Restored Its Storage repair card, a warning, and clears Home Assistant's own issue about the unreadable file; a restore that fails leaves that issue standing. When the startup grace closes, a notice of the restore goes to the Daily Brief targets and the high-priority targets, at any hour, Quiet Hours or not. The restore is reported as "the last-good backup", with the time lost counted in local midnights crossed, never as a count of events or readings.**

*Proof:* [`test_restore.py`](../tests/test_restore.py), [`test_storage_failures.py`](../tests/test_storage_failures.py), [`test_verify_restore.py`](../tests/test_verify_restore.py).

### STOR-09 Damage Is Repaired Where It Is Found

**Damage is repaired at the moment it is found, with no decision asked of anyone. Damage at load with a usable last-good restores the whole file from it; the first step of [STOR-05](#stor-05-the-shape-check-at-load) checks the copy with its own check before trusting it, and one boot restores at most once. Damage at load with no usable copy, or damage found at save, is repaired in place: a damaged row or record is dropped, and a damaged field is reset to its default with the rest of the record kept. A damaged activity clock restarts at the moment of repair. Nothing is rebuilt field by field from the backup. Each repair raises one card naming what was repaired and where the originals are. It asks no decision; its Submit button is the person's way to put it down, and a card the person submitted stays gone until a new repair.**

*Proof:* [`test_verify_restore.py`](../tests/test_verify_restore.py), [`test_storage_shape.py`](../tests/test_storage_shape.py), [`test_backup_integrity.py`](../tests/test_backup_integrity.py), [`test_storage_failures.py`](../tests/test_storage_failures.py).

### STOR-10 A Damaged or Missing Clocks File

**A clocks file that cannot be read, or holds a damaged value or a record that is not a record, is set aside whole before the merge, as if it were missing; it rebuilds within a day. Two cases keep the file: a damaged saved outage start is cleared on its own, and that device's next outage starts afresh; and a clocks file only missing a field still merges, since that is how an upgrade adding a clock looks on its first start. When the clocks are lost, each device with learned history, or first seen more than 48 hours ago and not stored as never reported, restarts its clock, and the time before counts as unwatched (LIST has what follows); a system event and a Daily Brief sentence say so.**

*Proof:* [`test_clock_loss.py`](../tests/test_clock_loss.py), [`test_clock_strip.py`](../tests/test_clock_strip.py), [`test_storage_failures.py`](../tests/test_storage_failures.py), [`test_saved_outage_start.py`](../tests/test_saved_outage_start.py).

### STOR-11 Evidence Copies

**Before any repair or restore writes, the main file, the clocks file, the history file and their last-good copies are copied byte for byte into trim_backups, under one stamp. Nothing ever reads these copies back; they are the person's way back. A copy that cannot be taken is a log line, never a stop. A notice names the files that were copied, not the files that were expected.**

*Proof:* [`test_backup_integrity.py`](../tests/test_backup_integrity.py), [`test_restore.py`](../tests/test_restore.py), [`test_history_file_disk.py`](../tests/test_history_file_disk.py).

### STOR-12 No Silent Repair

**Whatever Device Sentinel does to its own storage writes a system event naming what was done and what it was done from, and the Daily Brief gives it a sentence. The one exception is the container repair of [STOR-05](#stor-05-the-shape-check-at-load)'s first step, which raises its own notice card and writes no event, since the event table may be what it is emptying; the log carries the detail. A start that restored or repaired anything sets Status to Problem for the whole session; no repair, later check or button clears it, only a restart that loads clean. Status carries when last-good was taken, how old it is, and how many repairs the load made.**

*Proof:* [`test_restore.py`](../tests/test_restore.py), [`test_verify_restore.py`](../tests/test_verify_restore.py), [`test_storage_shape.py`](../tests/test_storage_shape.py), [`test_backup_integrity.py`](../tests/test_backup_integrity.py), [`test_load_repairs_counted.py`](../tests/test_load_repairs_counted.py).

### STOR-13 How Long the Trim Backups Are Kept

**At each fold, each copy in trim_backups is deleted 30 days after it was taken, all of its files alike, the copy of a corrupt file saved under the same stamp included, except the newest copy, which is kept for the full History retention. Any other file in the folder that Device Sentinel did not name is never touched. The last-good copies live in `.storage` and are never pruned by this.**

*Proof:* [`test_backup_integrity.py`](../tests/test_backup_integrity.py), [`test_history_file_disk.py`](../tests/test_history_file_disk.py), [`test_corrupt_copy_pruned.py`](../tests/test_corrupt_copy_pruned.py).

### STOR-14 How Much History Is Kept

**How Much History to Keep sets how many days of battery, signal and gap history are kept, from 30 to 360 days in steps of 30, default 90. It judges one thing only: a device's longest silence is learned at most as long as the retention (FRZ). Each other verdict reads its own fixed window, so on everything else two houses with different settings detect alike. A lower setting trims at the next midnight rather than on save, so a mistake can be undone. The house's events and signal stress rows are kept for the same retention; incidents and silence episodes for 14 days, except that an opening is kept while its problem stands on the Problem List, and an acknowledgment does not release it (LIST); and a silence episode is kept past 14 days while it has no ending, or while it ended other than by the device resuming and is still waiting for its lag.**

*Proof:* [`test_retention.py`](../tests/test_retention.py), [`test_history_file_campaign.py`](../tests/test_history_file_campaign.py), [`test_house_tables_trim.py`](../tests/test_house_tables_trim.py).

### STOR-15 What Is Recorded

**A reading is recorded as it was reported and judged when it is read, within [STOR-07](#stor-07-values-held-to-what-is-possible)'s bounds and the reading rules of BAT and SIG. A thing that happened to the house, such as a restart, an outage or a settings change, is its own row in the house's events, stamped when it happened and never on a device; it explains the device rows beneath it and never replaces them. The day's running figures, its reading count among them, live with the clocks and are folded into the daily histories at midnight. A device's second signal scale is one nested key on its record.**

*Proof:* [`test_storage_split.py`](../tests/test_storage_split.py), [`test_signal_stats.py`](../tests/test_signal_stats.py), [`test_clock_strip.py`](../tests/test_clock_strip.py), [`test_storage_shape.py`](../tests/test_storage_shape.py).

### STOR-16 Each History Carries Its Dates

**Each daily history records the date of its newest entry, how many entries the dates cover, and the days skipped, as ranges. A day the device was not heard writes nothing to its battery history. Histories saved before 0.24.4 read as consecutive days ending at their last fold, and dates already saved wrong are left as they are. A rollback to 0.23.20 with a full history, followed by a return, misdates a history by the nights spent on the older release.**

*Proof:* [`test_dated_histories.py`](../tests/test_dated_histories.py), [`test_daily_dates.py`](../tests/test_daily_dates.py).

### STOR-17 A Midnight Missed While Down

**A midnight that passed while Device Sentinel was not running is folded once at the next start, whether one midnight was missed or several, judged on the date the file carried when it was loaded. It is not folded when the statistics epoch wiped at that same start ([STOR-19](#stor-19-upgrades-and-older-releases)).**

*Proof:* [`test_missed_fold.py`](../tests/test_missed_fold.py).

### STOR-18 Starts and Stops

**A stop Device Sentinel was not told about is recorded as an unclean shutdown, named for the stop rather than any guess at its cause, and the restart after it as an unclean restart. At each start the silence episodes with no ending are counted and reported in the log and the diagnostics, and none is closed. A house event whose closing was never recorded ends at the first restart after it opened, or at the next opening of the same kind and scope, whichever comes first; the brief then says only that it went down, not that it came back.**

*Proof:* [`test_unclean_restart.py`](../tests/test_unclean_restart.py), [`test_journal.py`](../tests/test_journal.py), [`test_attribution.py`](../tests/test_attribution.py).

### STOR-19 Upgrades and Older Releases

**At each load the stored records are matched to the current record: a field missing is filled with its default, a field this code retired is removed, and any other unknown field is kept untouched, since it belongs to a newer release. A setting no code reads is cleared at setup with a log line naming it. A one-time conversion runs at load before the matching, marked with the release that ran it, so it runs once. A change to the statistics epoch wipes only the learned rhythm and the verdict drawn from it, takes a copy of the files first, and does not run if the copy fails. A clean-up mechanism stays; a named entry it carries for one old fault is removed once a fresh download shows the fault gone.**

*Proof:* [`test_hardening.py`](../tests/test_hardening.py), [`test_round_trip.py`](../tests/test_round_trip.py), [`test_storage_split.py`](../tests/test_storage_split.py), [`test_backup.py`](../tests/test_backup.py), [`test_options_migration.py`](../tests/test_options_migration.py).

### STOR-20 The Answers File

**The answers file holds what the owner has told Device Sentinel: the power and type answers, by model and for devices with no maker or model, the ticked rows and recommendations, and the confirmed or entered battery replacement dates. It is written when one of these is given or changed, besides the repair and the move below. The previous file is kept as its last-good copy before each write, except after a start that restored it, repaired it or read it damaged, so last-good stays the latest clean file; it is restored from at start when the file cannot be read. Before any repair of it, a copy goes to trim_backups dated the day it is made; an answer left out, a table that cannot be read, a restore and an empty start each record a storage event the brief shows, and the repair is written back once. Excluding or setting a device aside keeps its power and type answers. A device removed from Home Assistant keeps its power and type answers with its held record for 30 days, and they return if the device does; the fold after 30 days deletes them (see [WATCH](Rulebook__02_WATCH_What_Is_Watched.md)). An excluded device removed from Home Assistant loses them at once. A tick is forgotten at the first midnight after its device leaves its card or its line is gone, so excluding, setting aside or removing a device drops its ticks. A battery replacement date goes with the device's record: it stays while the record is kept and goes when the record does. The old power file is moved in and deleted at the first start of 0.25.1, and the move is removed at 1.0.0.**

*Proof:* [`test_answers_store.py`](../tests/test_answers_store.py), [`test_removed_hold.py`](../tests/test_removed_hold.py), [`test_recommendation_acknowledgement.py`](../tests/test_recommendation_acknowledgement.py), [`test_battery_last_replaced.py`](../tests/test_battery_last_replaced.py).

### STOR-21 The Diagnostics Download

**The diagnostics download carries each device's stored record and the tables: the to-do list and its additions journal, the house's events, silence episodes, incidents and signal stress rows, the history file's state, the answers (the recommendation ticks and the battery replacement dates included), and the count of open episodes. Network addresses are hidden: each MAC address keeps its maker's half, and each home-network address becomes a stand-in, the same throughout the file. Version-like numbers and Zigbee IEEE addresses stay. The reports are not redacted. A download is read beside the live entities, whose version says which build is running.**

*Proof:* [`test_diagnostics_privacy.py`](../tests/test_diagnostics_privacy.py), [`test_storage_tables.py`](../tests/test_storage_tables.py), [`test_device_page.py`](../tests/test_device_page.py), [`test_diagnostics_answers.py`](../tests/test_diagnostics_answers.py).

### STOR-22 The Log

**Retired.** What Device Sentinel writes to the log is set by [GEN-10](Rulebook__01_GEN_General.md#gen-10-the-log), which logs only an error or something that cannot be seen elsewhere.

### STOR-23 The Trim and the History File

**A trim from Settings, Advanced erases the device's older history as well as its 30 days and writes the history file at once. Its copy in trim_backups holds the whole record, older history included, so putting that one copy back restores everything. A device trimmed and found again starts from nothing, and no restart brings its old history back.**

*Proof:* [`test_trim.py`](../tests/test_trim.py), [`test_history_file.py`](../tests/test_history_file.py).

### STOR-24 Removing the Integration

**Deleting Device Sentinel from Home Assistant deletes only what it wrote: its four storage files with each copy beside them, the old power file if one is left, its own reports, the stack probe file and its numbered copies, the diagnostic folder, trim_backups and the www folder. Its folder in `config` goes only if it is then empty, and the log says what was left. Each target is removed on its own, and a failure is logged, never raised. A restart or a reload deletes nothing.**

*Proof:* [`test_entity_defaults.py`](../tests/test_entity_defaults.py), [`test_history_file_disk.py`](../tests/test_history_file_disk.py).
