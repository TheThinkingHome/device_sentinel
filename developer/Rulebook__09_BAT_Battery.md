# Device Sentinel Rulebook: Battery (BAT)

*Version: rulebook, 29 October 2026, on Device Sentinel 0.27.14. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

This section covers how Device Sentinel reads a battery, says when it is low, judges where it is heading, and keeps what a better forecast will need. What powers a device (the Power row and its answers) is under [DEV](Rulebook__04_DEV_Device_Identity.md). Battery mutes are in [BAT-04](#bat-04-battery-mutes), and muting in general is under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md).

### BAT-01 Which Entity Is Read

**A device's battery is read from one entity of its own with device class battery.**
- **Percentage first:** a percentage is chosen over a binary low sensor. The binary is used only where there is no percentage, and reads "on" as low.
- **Several to choose from:** one from the device's own integration is chosen over one another integration added, and the lowest entity id breaks a tie.
- **Added entities:** an entity another integration added, such as Battery Notes', never counts as the device reporting.

*Proof:* [`test_battery.py`](../tests/test_battery.py), [`test_foreign_entities.py`](../tests/test_foreign_entities.py).

### BAT-02 What Counts as a Reading

**A battery reading is a finite number from 0 to 100.** Anything else is ignored and the last verdict holds: text, infinity, NaN, or a number out of range.
- **Raw scale:** a device whose battery reads over 110 on two different days is on Zigbee's raw scale of 0 to 200. Its readings are halved, and its stored history is halved once.
- **How long the mark lasts:** until the next battery change or firmware update, when the device is measured again.
- **Before it is proved raw:** a reading over 100 is ignored.

*Proof:* [`test_battery.py`](../tests/test_battery.py), [`test_storage_shape.py`](../tests/test_storage_shape.py).

### BAT-03 Low Battery

**A battery is low when its reading is at or below the Low Battery Threshold, which defaults to 15 percent.** An install from before 0.20.11 that never chose a threshold keeps 20.
- **Clearing:** a low battery clears when it reads above the threshold plus 3 (18 percent at the default 15). So a cell that hovers near the line, or sags under load and recovers at rest, does clear.
- **When a reading is judged:** as soon as it arrives. A value the device sends again unchanged after an outage is recorded and judged at its next change.
- **Level only:** low is about the level only. A battery that stops reporting is judged by the freeze and unavailable rules, never as a battery problem.
- **Startup grace:** a battery that first reads low inside the startup grace is held until the grace closes, then judged. A low that stood before the restart stays.
- **The words:** while the level reads at or below the threshold plus 3, the brief, and the phone push that uses its words, say "battery crossed the threshold on <date>. Its current level is <N>%." Back above that, they say "battery read low, since recovered", or "battery read low, since replaced or recharged" at 95 percent or over, with no number.

*Proof:* [`test_battery.py`](../tests/test_battery.py), [`test_battery_level_text.py`](../tests/test_battery_level_text.py), [`test_battery_wording.py`](../tests/test_battery_wording.py).

### BAT-04 Battery Mutes

**A battery mute is set by integration, label or device, never by entity, since a device can change which battery entity it reports through.**
- **While muted:** the battery is still judged and its verdict kept, but it is never shown. It stays off all lists.
- **On unmute:** a low battery appears at once, with the time it first read low.
- **Leaving the Problem List:** an item that leaves because of a battery mute leaves silently.

*Proof:* [`test_exclusions.py`](../tests/test_exclusions.py), [`test_brief_mutes.py`](../tests/test_brief_mutes.py).

### BAT-05 One Reading a Day

**At each midnight, a battery device heard that day keeps one level for the day, with the day's date. A day the device was not heard writes nothing, so a gap never reads as a flat stretch.**

*Proof:* [`test_battery_trend.py`](../tests/test_battery_trend.py), [`test_battery_last_replaced.py`](../tests/test_battery_last_replaced.py).

### BAT-06 A New Battery Is Detected

**A new battery is a rise of 25 points or more from one day to the next, or a cell at or under 90 percent landing at or over 95.** It counts once the next day's reading confirms it against the level before the rise.
- **The history:** starts again from the day the rise appeared, so each trend and forecast describes the battery in the device today. The old history is kept, unread.
- **Raw scale:** a new battery is measured again for the raw scale ([BAT-02](#bat-02-what-counts-as-a-reading)).
- **The words:** each surface says "replaced or recharged", because one reading a day cannot tell the two apart. The exception is the device page's Battery Last Replaced row and its card, which [BAT-07](#bat-07-battery-last-replaced) governs.

*Proof:* [`test_battery.py`](../tests/test_battery.py), [`test_battery_last_replaced.py`](../tests/test_battery_last_replaced.py), [`test_battery_wording.py`](../tests/test_battery_wording.py).

### BAT-07 Battery Last Replaced

**The device page shows the day the battery was last replaced, in Simple and Advanced.**
- **A detected replacement:** is used until the person answers, and the Confirm Battery Replacement card asks. Confirm keeps it, Change date splits the history at the day the person gives, and Cancel joins the history back.
- **Dates the person gives:** a future date is refused. A date older than the oldest kept day gives the whole kept history to the new battery.
- **Cancel:** leaves the 42-Day Log-Normal Percentile's day count as it stands.
- **Older detections:** a replacement detected before 0.26.7 counts as confirmed.
- **Rechargeable:** a device whose power answer is Rechargeable reads Battery Last Charged and Confirm Battery Charge.
- **No replacement yet:** the row reads, for example, "Device first detected August 12, 2026. No battery replacement yet."

*Proof:* [`test_battery_last_replaced.py`](../tests/test_battery_last_replaced.py).

### BAT-08 Each Battery's Life Is Kept

**When a battery is replaced, one row is kept for the battery that ended.** Nothing reads these rows yet.
- **What a row holds:** the device, its maker and model, battery type and count, the days it went in and came out, whether its start was seen, its first kept day and level, its last level, and the last day the device was heard.
- **Where the start comes from:** the replacement on record, detected, confirmed or given by the person. With none, it comes from the day Device Sentinel first saw the device, marked as a start not seen.
- **The first kept day as the start:** only where the first kept day is older than the start on record, or there is neither a start nor a first-seen day, is the first kept day taken as the start, marked not seen. Otherwise the start is never read from the kept history, which retention trims.
- **How many:** the house keeps up to 5,000 rows for good, and the diagnostics download carries them.
- **Corrections:** Cancel takes a row back. A day the person gives over a waiting detection corrects its row, and any other day adds one. A rise the person already dated keeps one row.

*Proof:* [`test_battery_lives.py`](../tests/test_battery_lives.py).

### BAT-09 Coarse Batteries

**A fall of 5 points or more from one day to the next is a coarse step.**
- **When a battery is coarse:** after two coarse steps, while its kept history of at least 30 days holds no smaller change. Any smaller change makes it smooth again. A battery that never changed is not coarse.
- **What it changes:** its forecast is withheld from the first coarse step, and a coarse battery is judged by the low threshold alone.
- **On screen:** the device page's Battery steps row and Battery Trends read Smooth, Not enough data or Coarse.

*Proof:* [`test_battery_steps.py`](../tests/test_battery_steps.py).

### BAT-10 When a Battery Is Judged

**A battery is judged for falling and given a time left only when all three hold:**
- **Level:** it reads at or under three times the low threshold (45 percent at the default 15).
- **History:** it was heard on at least 28 of the last 42 days.
- **Steps:** it reads Smooth under Battery steps ([BAT-09](#bat-09-coarse-batteries)).
- **Otherwise:** its page and Battery Trends row show the level and the weekly averages, and say nothing more.
- **Coarse batteries:** are judged by the low threshold alone, and the page reads "Coarse", never steady or falling.
- **Low:** low ([BAT-03](#bat-03-low-battery)) is judged whatever the history.

*Proof:* [`test_battery_ceiling.py`](../tests/test_battery_ceiling.py), [`test_battery_trend.py`](../tests/test_battery_trend.py).

### BAT-11 Falling

**A judged battery is falling when its last week's average is at least 1 point below the week before's, and the fitted line through its last six weeks falls at least half a point a week.**

*Proof:* [`test_battery_trend.py`](../tests/test_battery_trend.py).

### BAT-12 Accelerating

**A judged battery is accelerating when all of these hold:**
- **The curve:** a curve through its last six weeks bends down and fits clearly better than a straight line (an F of 10 or more, and at least 1 square point better).
- **Today:** it is still falling.
- **Recent drops:** the days it was heard among the last 14 calendar days hold at least three day-to-day drops. So a device with silent days has fewer days to find them in.

One slow week does not take accelerating off. An accelerating battery reads "Falling faster each week, about N points a week today."

*Proof:* [`test_battery_trend.py`](../tests/test_battery_trend.py), [`test_battery_projection.py`](../tests/test_battery_projection.py).

### BAT-13 How Long a Battery Has Left

**A judged battery is given a time left as a range.** The range comes from refitting its own last six weeks with its weekly swings reshuffled.
- **When it is worked out:** from the history to yesterday and today's reading, so a new reading during the day works it out again.
- **Which line:** the curve of [BAT-12](#bat-12-accelerating) when it passes, the straight line otherwise.
- **To the threshold:** the time left runs to the low threshold and reads "reaches 15% in about 3 to 5 weeks".
- **To empty:** a battery already under the threshold, or one that has been low and not yet replaced, runs to empty and reads "empty in about …".
- **Units:** each end is said in its own unit. A near end under 13 weeks is said in weeks, and so is a far end beside it that rounds to under four months.
- **The caution:** where a time left shows, Device Sentinel says many devices stop working before 0 percent.

*Proof:* [`test_battery_projection.py`](../tests/test_battery_projection.py).

### BAT-14 Warnings

**There are two warning levels. Both are decided by the near end of the time left against Days Till Low Warning (7 to 30 days, default 30).**
- **Full warning:** an accelerating battery whose near end is inside Days Till Low Warning, and which is not already low, gets an item on the Problem List, a phone push, the Daily Brief and the Battery: Falling sensor.
- **Batteries to Watch:** a battery falling at a steady pace inside Days Till Low Warning, and not already low, is listed under Batteries to Watch in the Daily Brief and on Battery Trends. It gets no push and no Problem List item.
- **Already low:** a battery already low is left out of both, since it has its own line.
- **Low and falling:** a device both low and falling reads as one line, the level and then the direction: "battery 16%, empty in about 2 weeks".
- **No time left:** where no time left can be given, the falling clause reads "battery running down".

*Proof:* [`test_battery_watch.py`](../tests/test_battery_watch.py), [`test_battery_report.py`](../tests/test_battery_report.py), [`test_battery_ceiling.py`](../tests/test_battery_ceiling.py), [`test_falling_surfaces.py`](../tests/test_falling_surfaces.py).

### BAT-15 Forecasts Are Kept and Scored

**At each midnight, each judged battery whose time left comes from the six-week range of [BAT-13](#bat-13-how-long-a-battery-has-left) gains one forecast row.** A time left from the straight pace alone writes none. Nothing here changes a judgment.
- **What a row holds:** the day, its level, whether it was accelerating, the target and the range.
- **Scoring:** when the battery reaches the target, its open rows are scored inside, earlier or later. A row whose far end passes first is later at once. A battery replaced first scores its rows replaced.
- **Forecasts to empty:** a forecast to empty ([BAT-13](#bat-13-how-long-a-battery-has-left)) is scored on a reading of 0, or on the last day heard when the device went silent two days or more before its replacement.
- **How many are kept:** each device keeps its newest 400 rows. The house tallies, one for the threshold and one for empty, never expire.
- **On screen:** Advanced shows the rows as Earlier Forecasts.

*Proof:* [`test_battery_forecasts.py`](../tests/test_battery_forecasts.py), [`test_battery_empty_forecasts.py`](../tests/test_battery_empty_forecasts.py).

### BAT-16 Kept for a Better Forecast Later

**These are shown or kept for a better forecast later, and nothing is judged on them:**
- **Lithium.** A battery whose type starts with CR is lithium. Its page says its level holds near full until close to its end while it is not falling, and Battery Trends says it once under Other Cells.
- **Its model's pace.** A battery's page and Battery Trends row show the slowest and fastest weekly fall of the other devices of the same maker and model that have a weekly fall, as "Others of this model lose 0.8 to 1.6 points a week", when at least two qualify. A device with no weekly fall yet is left out.
- **Voltage, temperature and messages.** At each midnight, each battery device heard that day keeps its battery voltage, its own temperature and its message count, from its own entities only. A voltage outside 0.5 to 15 volts is left out. The rows are kept for the How Much History to Keep setting's days, and Advanced shows the newest day. A battery device whose voltage sensor is switched off is listed on the Battery Voltage Switched Off card (REC).

*Proof:* [`test_battery_lithium.py`](../tests/test_battery_lithium.py), [`test_battery_model_pace.py`](../tests/test_battery_model_pace.py), [`test_battery_evidence.py`](../tests/test_battery_evidence.py), [`test_battery_voltage_card.py`](../tests/test_battery_voltage_card.py).

### BAT-17 The Battery on the Device Page

**The device page shows the five weekly averages with each week's loss, the reading, the time left and one sentence.**
- **The chart:** draws the daily line in blue, the last five weekly averages in orange, and a fitted line on a falling battery. The weekly bars and the fitted line show at 30 and 14 days only.
- **Simple, and Advanced's Future range:** draw each kept day as light dots under a smoothed line. The expected fall is two red lines that end where they reach the target, with the range shaded between and the day each reaches it under the axis. The low line shows only where the history or the range reaches it.
- **In Simple:** the expected fall is drawn only when the near end is inside Days Till Low Warning.
- **Future's limit:** the longer of half the days held and Days Till Low Warning.
- **Past the limit:** when the near end is past that limit, nothing is drawn and it reads "Reaches 15% after N days." or "Empty after N days.", with N the limit.
- **Otherwise:** the lines reach the far end's day, cut at twice the limit, and the words read "Expected to reach 15% in …".

*Proof:* [`tools/panel_checks/check_battery_weeks.js`](../tools/panel_checks/check_battery_weeks.js), `check_battery_chart.js`, `check_battery_future.js`, `check_battery_steps.js`.

### BAT-18 Battery Trends

**Battery Trends reads the same weeks as the device page.**
- **Batteries to Watch:** lists the steady fallers of [BAT-14](#bat-14-warnings).
- **Falling:** shows the five weeks and the pace a week.
- **Other Cells:** shows each remaining battery's last four weeks.
- **By Model:** shows the points a week for each model.
- **The summary:** splits the batteries that report a level into three parts that add up: falling, at or under the threshold and not falling, and not falling or not yet judged.

*Proof:* [`test_dashboard_trends.py`](../tests/test_dashboard_trends.py), [`tools/panel_checks/check_battery_weeks.js`](../tools/panel_checks/check_battery_weeks.js), `check_type_filters.js`.
