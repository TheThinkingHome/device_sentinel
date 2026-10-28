# Device Sentinel Rulebook: Signal (SIG)

*Version: rulebook, 28 October 2026, on Device Sentinel 0.27.13. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

How Device Sentinel reads a device's radio signal, what it keeps each day, how it judges a bad signal day and a stuck reading, and what the Signal Trends tab shows. Signal muting is under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md). How a railed signal reads on the Problem List is in [LIST](Rulebook__11_LIST_Problem_List.md); how it reaches a phone is in [NOTE](Rulebook__12_NOTE_Notifications.md). A device that keeps dropping out is under [UNAV](Rulebook__06_UNAV_Unavailable.md).

### SIG-01 Each Device Against Its Own Normal

**A device's signal is judged against that device's own recent days, never against a fixed number for the house. LQI has no common scale between makers: a device that always reads 90 is fine, while one that usually reads 200 and falls to 90 is in trouble. Signal is recorded first and judged later. Each new judgment waits for recorded data to argue for it.**

*Proof:* [`test_signal_badday.py`](../tests/test_signal_badday.py).

### SIG-02 Which Entity Is a Signal

**An entity is a signal when its device class is signal strength. Otherwise it is a signal when its id, unique id or name holds "linkquality", "lqi" or "rssi". An entity matched only by its name whose unit is a percentage is a quality figure, not a measurement, and is refused. No entity is refused for any other word in its name.**

*Proof:* [`test_signal.py`](../tests/test_signal.py).

### SIG-03 Two Scales, One Judged

**A reading's scale is decided by its sign: below zero is RSSI in dBm, zero or above is LQI.** A device keeps one series per scale, never a mixture.
- **Both scales:** where a device reports both, RSSI is the one judged, and LQI is recorded beside it and never judged. If LQI arrived first, the two trade places so nothing already learned is lost.
- **Mixed history:** a stored history that holds both signs is not one measurement and is discarded once at load.

*Proof:* [`test_signal.py`](../tests/test_signal.py), [`test_storage_shape.py`](../tests/test_storage_shape.py), [`test_dated_histories.py`](../tests/test_dated_histories.py).

### SIG-04 Readings That Are Refused

**A signal reading must be a finite number inside its scale's physical range, -130 to 255. Text, infinity, NaN, or a number outside the range is ignored, never brought into range, and the next real reading is recorded as usual. A reading at the rail value ([SIG-07](#sig-07-a-railed-signal)) is counted as a rail and never feeds the day's statistics.**

*Proof:* [`test_signal.py`](../tests/test_signal.py), [`test_missed_fold.py`](../tests/test_missed_fold.py), [`test_storage_shape.py`](../tests/test_storage_shape.py).

### SIG-05 What Each Day Keeps

**At each midnight, a device that spoke that day keeps one row, with the day's date.**
- **What the row holds:** the level its link held for all but the worst 5 percent of the day (P5), the middle level (P50), the mean and spread, the highest reading, how many readings came, and how many were rails.
- **Weighed by time:** the levels are weighed by minutes held, not by readings, so a busy hour does not outvote a quiet one. A reading held for no time counts for nothing.
- **Empty days:** a day with no real reading writes no row. A day of nothing but rails writes a row with the rail count, a reading count of zero and no statistics.

*Proof:* [`test_signal_stats.py`](../tests/test_signal_stats.py), [`test_time_weighting.py`](../tests/test_time_weighting.py), [`test_dated_histories.py`](../tests/test_dated_histories.py).

### SIG-06 The Floor

**A device's floor is the lowest of its daily P5 levels over the last 30 calendar days, ending yesterday, with no day discarded. A day without readings is left empty and shows a dash. The floor judges nothing. Device Telemetry shows the 30 days newest first, the lowest day in bold and each bad signal day struck through.**

*Proof:* [`test_telemetry_signal_columns.py`](../tests/test_telemetry_signal_columns.py), [`test_signal_lows_by_day.py`](../tests/test_signal_lows_by_day.py).

### SIG-07 A Railed Signal

**A rail is a scale's fill value, 255 for LQI and -128 for RSSI. It is a field the device stopped filling, which looks like perfect signal and is the opposite.**
- **When a signal is railed:** when, on three days in a row by the calendar, the device spoke and said nothing but the rail.
- **On the Problem List:** a railed signal is a problem on the Problem List and reads "signal railed", never "low".
- **Steady values:** a steady real value is never called stuck, since a strong steady link looks the same.
- **Watching:** a railed device stays watched until a person mutes it for signal. Device Sentinel never stops watching it on its own.
- **Age:** its age is counted from when it reached the Problem List.

*Proof:* [`test_signal.py`](../tests/test_signal.py), [`test_signal_stats.py`](../tests/test_signal_stats.py), [`test_reports.py`](../tests/test_reports.py), [`test_notifications.py`](../tests/test_notifications.py).

### SIG-08 The Bad Signal Day

**Each day's P5 is judged against its normal: the middle of the device's P5 on the days before it, as many as Days of Signal History sets (default 7, from 4 to 14).** It needs at least four of those days.
- **A bad day:** the day is bad when its fall from the normal is at least the Bad Day Drop, 25 points on LQI (10 to 60) or 6 dB on RSSI (3 to 15), and also at least Bad Day Sensitivity (default 4, from 2 to 8) times the device's own spread over those days, the spread taken as at least 1.
- **Both must hold:** so a small wobble on a steady device and a large swing on a jittery one are each passed over.
- **Not judged:** a day whose sign differs from its normal, or whose normal mixes signs.
- **The bad-day line:** the line shown beside a device is its normal less the larger of the two gates. A past day always reads with today's settings.

*Proof:* [`test_signal_badday.py`](../tests/test_signal_badday.py), [`test_signal_badday_hostile.py`](../tests/test_signal_badday_hostile.py).

### SIG-09 Signal: Rails and Signal: Weak

**There are two sensors, counted apart as Battery: Low and Battery: Falling are.**
- **Signal: Rails:** counts the railed devices.
- **Signal: Weak:** counts the devices whose last recorded day was a bad signal day. It counts watched devices only, and leaves out railed devices and those muted for signal or for everything, so one fault never counts twice.
- **Leaving the count:** a weak device leaves the count the next day its signal holds, with nothing to acknowledge, because a weak day is a reading, not an incident.

*Proof:* [`test_signal_stats.py`](../tests/test_signal_stats.py), [`test_entity_defaults.py`](../tests/test_entity_defaults.py), [`test_set_aside_left_out.py`](../tests/test_set_aside_left_out.py).

### SIG-10 No Signal Alert Yet

**A weak signal raises no Problem List item, no push and no Daily Brief line. A railed signal is the one signal problem that does. Any future signal alert errs toward missing a drop-out rather than reporting one falsely. It reaches the Problem List only after a replay on captured drop-outs shows it is rarely wrong.**

*Proof:* [`test_signal_stats.py`](../tests/test_signal_stats.py).

### SIG-11 Evidence Kept for a Later Alert

**When a device's silence opens an episode, the episode keeps the last reading and the day's mean and spread so far.**
- **When the episode completes:** one row of who, when, how long and how it ended joins a stress table, kept as long as the history setting keeps.
- **When a device goes unavailable:** the incident keeps its signal at that moment, and the outcome when it closes.
- **No signal:** a device with no signal records nothing, never a zero.
- **Diagnostics:** the diagnostics download carries the stress table.

*Proof:* [`test_signal_capture.py`](../tests/test_signal_capture.py), [`test_signal_stats.py`](../tests/test_signal_stats.py).

### SIG-12 Signal Trends

**Signal Trends shows each watched, unmuted device with at least 21 days of signal.**
- **For each device:** the middle of its last 7 days' P50 (THIS WEEK), the middle of the days before them (BEFORE THIS WEEK), the CHANGE between the two numbers as shown, that change in its own spreads, its normal and bad-day line from [SIG-08](#sig-08-the-bad-signal-day), its bad days over the last 14 days, and its readings a day.
- **Above the table:** the text reads "Each device's typical signal this week, beside its history. A large drop means its radio link has weakened this week."
- **The lists:** devices with a bad day are listed under Devices With Unsteady Signals, and the rest, each named, under Devices With Steady Signals. Days Several Devices Had a Bad Day lists each day on which more than one device had one. Devices That Keep Dropping Out lists each device in a flap beside its signal.
- **Both scales:** where a house has both scales, they are filtered apart.
- **In Simple:** the tab is hidden and the page opens only from a link (see [DASH](Rulebook__14_DASH_Dashboard.md)).

*Proof:* [`test_dashboard_trends.py`](../tests/test_dashboard_trends.py), [`tools/panel_checks/check_signal_trends.js`](../tools/panel_checks/check_signal_trends.js).

### SIG-13 The Retired Dwell Line

**Dwell, the time a device spent below a danger line drawn from its own floor, is gone from each surface and from storage, and so is the danger line.**
- **Why:** a line drawn from the record it judges sinks to meet a failing device, so a broken link read healthy again within a week.
- **Settings removed:** the settings that shaped it are gone. Sensitivity, Line Lift, Red Threshold and the margin are removed from saved settings, and Anomaly Trim left with the trim itself.
- **Older episodes:** episodes saved before 0.23.19 keep the line they recorded.

*Proof:* [`test_options_migration.py`](../tests/test_options_migration.py), [`test_storage_shape.py`](../tests/test_storage_shape.py), [`test_telemetry_signal_columns.py`](../tests/test_telemetry_signal_columns.py).

### SIG-14 Zigbee Parent Tracking

**Retired.** Device Sentinel does not record which router or coordinator a Zigbee device connects through.

### SIG-15 A Signal Trail on a Freeze

**Retired.** A frozen device's report carries no trail of its last signal readings.
