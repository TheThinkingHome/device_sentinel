# Device Sentinel Rulebook: Battery (BAT)

*Version: rulebook, 21 November 2026, on Device Sentinel 0.30.1. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

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
- **Proved again after a clear (since 0.28.12):** after a battery change or a firmware update clears the raw mark, everything stored is in percent, since a reading over 100 is ignored until the scale is proved again. Proving it then halves nothing, where it once halved the history a second time and took the halved days for another new battery, every few days.

*Proof:* [`test_battery.py`](../tests/test_battery.py), [`test_storage_shape.py`](../tests/test_storage_shape.py).

### BAT-03 Low Battery

**A battery is low when its reading is at or below the threshold for its battery type (since 0.30.0): Alkaline Batteries 10%, Lithium and Other Batteries 20%, Rechargeable Batteries 20%, each a setting on the Low Battery screen.**
- **Which type:** from the owner's answer or Battery Notes' library ([DEV-08](Rulebook__04_DEV_Device_Identity.md)). Alkaline: AA, AAA, AAAA, C, D and their LR names. Rechargeable: anything named rechargeable, an LIR cell, an 18650, LiFePO4 or NiMH. Lithium and other: coin and CR cells, lithium AA and AAA, everything else, and a battery whose type is not known.
- **Why these:** an alkaline cell at 10% still has weeks of use. A lithium cell holds near full and then falls fast, and a rechargeable is charged, not replaced.
- **A coin cell's voltage:** a device with one coin or CR cell that reports its voltage is also low at a resting voltage of 2.9 V or under, wherever its percentage reads, and clears above 2.95 V. Its resting voltage is the higher of today's highest and the last day's, so a reading in a transmit's sag decides nothing. Not a setting.
- **The upgrade (since 0.30.0):** every house moved to these defaults, whatever single threshold it had, a breaking change told once in the Daily Brief ([BRIEF-17](Rulebook__13_BRIEF_Daily_Brief.md#brief-17-a-breaking-change-told-once)).
- **Clearing:** a low battery clears when it reads above its threshold plus 3 (23 percent at 20). So a cell that hovers near the line, or sags under load and recovers at rest, does clear.
- **When a reading is judged:** as soon as it arrives. A value the device sends again unchanged after an outage is recorded and judged at its next change.
- **Level only:** low is about the level only. A battery that stops reporting is judged by the freeze and unavailable rules, never as a battery problem.
- **Startup grace:** a battery that first reads low inside the startup grace is held until the grace closes, then judged. A low that stood before the restart stays.
- **The words:** while the level reads at or below the threshold plus 3, the brief, and the phone push that uses its words, say "battery crossed the threshold on <date>. Its current level is <N>%." Back above that, they say "battery read low, since recovered", or "battery read low, since replaced or recharged" at 95 percent or over, with no number.

*Proof:* [`test_battery.py`](../tests/test_battery.py), [`test_battery_thresholds_by_type.py`](../tests/test_battery_thresholds_by_type.py), [`test_battery_level_text.py`](../tests/test_battery_level_text.py), [`test_battery_wording.py`](../tests/test_battery_wording.py).

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

**A rise is a possible new battery when the level gains 25 points or more from one midnight to the next, or lands at 95 or more having gained 10 or more. It is a new battery when the whole next day stays above the old battery's highest level.**
- **How the level is sampled (since 0.28.12):** each moment the device is heard is a sample of the battery level it holds: its own battery report, and each time it speaks, such as a motion or a door report, since the level it holds is still its own. Each day keeps each whole-number level heard, at most 101 and none dropped, and how many moments each was heard at. The device speaking counts as a moment at most once a minute, read once the message's other entities are written, so a battery report and a link-quality change in one message are one moment, and the report is read at its new level. The day's low and high count only levels heard at two moments or more, so a value held for seconds, as a reconnect can give, decides nothing. A day with no level heard twice counts all its levels.
- **The test (since 0.28.12):** the new battery's first whole day must have its low above the old battery's high plus 2. The old battery's high is read from the days before the day of the change, which holds both:
  - **A rise that lands at full,** 95 or more: the whole day before. A battery that collapses and is changed after a day at its low is found.
  - **A rise that lands below full,** which a new battery never does: the two days before. A lock's low warning held a whole day, or a dip held over one night, comes back to where the old battery already read, and is refused.
- **What this refuses:** a lock's low warning held over a night or a day, a coin cell that sags one cold night, a battery that swings with the day's warmth, and a slow drift on a warm day. A swing reads at its old high the day before the rise, so its next day never clears it.
- **What is left to a person:** a battery that collapses from near full and is changed the very next day reads exactly as a sag does, and is refused. The person can give the day ([BAT-07](#bat-07-battery-last-replaced)). A sag at full held a whole day is taken for a change, and Cancel puts everything back.
- **Just after the upgrade:** with no day kept before a rise, the rise is judged on the midnight levels alone, as before. Three days fill from empty.
- **Each day's low and high are kept (since 0.29.3):** at midnight, a device heard that day keeps the day's lowest and highest level as one dated row, beside its lowest and highest voltage ([BAT-16](#bat-16-kept-for-a-better-forecast-later)). As many rows are kept as How Much History to Keep has days, as the daily levels are, and the rule reads its days before from the newest of them. A day the device was not heard writes no row, as it writes no daily level ([BAT-05](#bat-05-one-reading-a-day)). A day folded twice, as a restart across midnight can give, is one row holding both parts. The three days an older release kept become dated rows at the upgrade, the newest on the day before the file was last saved.
- **The day's samples survive a power cut (since 0.29.3):** the levels heard today, their counts and the day's voltages are written with the clocks, every few minutes, rather than with the main file ([STOR-15](Rulebook__18_STOR_Storage.md#stor-15-what-is-recorded)).
- **Back to an older release:** 0.29.2 and earlier read neither the rows nor the day's samples from the clocks, so for its first days back the rule judges a rise on the midnight levels alone, as just after an upgrade. The newest 30 rows are kept, unread, and in use again on the return. Older rows are lost at the older release's first write of the history file; the rest of that file is kept.
- **The history:** starts again from the day the rise appeared, so each trend and forecast describes the battery in the device today. The old history is kept, unread.
- **Raw scale:** a new battery is measured again for the raw scale ([BAT-02](#bat-02-what-counts-as-a-reading)).
- **The words:** each surface says "replaced or recharged", because the level cannot tell the two apart. The exception is the device page's Battery last replaced row and its card, which [BAT-07](#bat-07-battery-last-replaced) governs.

*Proof:* [`test_battery.py`](../tests/test_battery.py), [`test_battery_last_replaced.py`](../tests/test_battery_last_replaced.py), [`test_battery_wording.py`](../tests/test_battery_wording.py), [`test_battery_replacement_rule.py`](../tests/test_battery_replacement_rule.py), [`test_battery_day_fields_hostile.py`](../tests/test_battery_day_fields_hostile.py), [`test_battery_day_level_cap.py`](../tests/test_battery_day_level_cap.py), [`test_battery_stray_counted_twice.py`](../tests/test_battery_stray_counted_twice.py), [`test_battery_day_ranges.py`](../tests/test_battery_day_ranges.py).

### BAT-07 Battery Last Replaced

**The device page shows the day the battery was last replaced, in Simple and Advanced, in a row named "Battery last replaced".**
- **A detected replacement:** is used until the person answers, and the Confirm Battery Replacement card asks. Confirm keeps it, Change date splits the history at the day the person gives, and Cancel joins the history back.
- **Dates the person gives:** a future date is refused. A date older than the oldest kept day gives the whole kept history to the new battery.
- **Cancel:** leaves the 42-Day Log-Normal Percentile's day count as it stands.
- **Older detections:** a replacement detected before 0.26.7 counts as confirmed.
- **Rechargeable:** a device whose power answer is Rechargeable reads Battery last charged and Confirm Battery Charge.
- **No replacement yet:** the row reads, for example, "Device first detected August 12, 2026. No battery replacement yet."
- **Two detections waiting (since 0.28.12):** a second detected replacement while the first still waits for a person adds to the saved history rather than replacing it, so no day is lost and Cancel can join each back.

*Proof:* [`test_battery_last_replaced.py`](../tests/test_battery_last_replaced.py), [`test_battery_stacked_detections.py`](../tests/test_battery_stacked_detections.py).

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
- **On screen:** Battery Trends reads Smooth, Not enough data or Coarse. The device page's Battery reports in row, in Advanced, reads the same in plain words: "small steps", "not known yet" or "steps of 5% or more".

*Proof:* [`test_battery_steps.py`](../tests/test_battery_steps.py).

### BAT-10 When a Battery Is Judged

**A battery is judged for falling and given a time left only when all three hold:**
- **Level:** it reads at or under three times its battery type's low threshold (30 percent for alkaline at the default 10, 60 percent for lithium, other and rechargeable at the default 20).
- **History:** it was heard on at least 28 of the last 42 days.
- **Steps:** it is smooth ([BAT-09](#bat-09-coarse-batteries)).
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

**A judged battery is given a time left as a range.** The fit's own day is the far end, the longest the battery is likely to last, since its fall speeds up near the end. The near end is earlier by the battery's own swings: the width between the 10th and 90th percentiles of refitting its last six weeks with its weekly swings reshuffled (since 0.29.3; James, 15 November 2026, 19:26 to 19:50). Before 0.29.3 those two percentiles were the two ends, around the fit's day. Where fewer than nine in ten reshuffles reach the target, the near end is their 10th percentile, never after the fit's day. The far end is held to three years, and so is each day the width is taken from. The near end is never under a quarter of the far end, so a slow, noisy fall whose swings are wider than its own day never reads "under a week" while far from its target. On the chart, the near end's line is the fit's own, run faster to reach the target on the near day.
- **When it is worked out:** from the history to yesterday and today's reading, so a new reading during the day works it out again.
- **Where it starts (since 0.29.3):** from the fitted line's value today, not today's reading. A reading a step off the line, as a battery gives from one day to the next, moved the date by weeks when the reading started it. Today's reading still decides the target: a battery reading under the threshold runs to empty.
- **When the reading moves it:** the start is never further over today's reading than the six weeks' second deepest day under the line, and at least one point, so one stray low day never hides a collapse. A reading further under than that is a collapse the line has not caught up with, and the start follows it down without a jump. When the line is under the reading, the start is held one point over the target while the reading is still over it, so the time left never drops to nothing before the battery has crossed, and there is no jump where the line crosses.
- **Which line:** the curve of [BAT-12](#bat-12-accelerating) when it passes, the straight line otherwise.
- **To the threshold:** the time left runs to the low threshold and reads "reaches 10% in about 3 to 5 weeks".
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
- **What a row holds:** the day, its level, whether it was accelerating, the target and the range. From 0.29.3 a row's far end is the fit's own day, sooner than the 90th percentile older rows hold, so a row is scored later sooner than before; each row is scored against the range it holds, and the house tallies count both kinds.
- **Scoring:** when the battery reaches the target, its open rows are scored inside, earlier or later. A row whose far end passes first is later at once. A battery replaced first scores its rows replaced.
- **Forecasts to empty:** a forecast to empty ([BAT-13](#bat-13-how-long-a-battery-has-left)) is scored on a reading of 0, or on the last day heard when the device went silent two days or more before its replacement.
- **How many are kept:** each device keeps its newest 400 rows. The house tallies, one for the threshold and one for empty, never expire.
- **On screen:** Advanced shows the rows as Earlier Forecasts.

*Proof:* [`test_battery_forecasts.py`](../tests/test_battery_forecasts.py), [`test_battery_empty_forecasts.py`](../tests/test_battery_empty_forecasts.py).

### BAT-16 Kept for a Better Forecast Later

**These are shown or kept for a better forecast later, and nothing is judged on them:**
- **Lithium.** A battery whose type starts with CR is lithium. Its page says its level holds near full until close to its end while it is not falling, and Battery Trends says it once under Other Cells.
- **Its model's pace.** A battery's page and Battery Trends row show the slowest and fastest weekly fall of the other devices of the same maker and model that have a weekly fall, as "Others of this model lose 0.8 to 1.6 points a week", when at least two qualify. A device with no weekly fall yet is left out, and so is one with no maker or model, or one that stands for none ([DEV-06](Rulebook__04_DEV_Device_Identity.md#dev-06-what-powers-a-device)), since 0.28.11.
- **Voltage, temperature and messages.** At each midnight, each battery device heard that day keeps its battery voltage, its own temperature and its message count, from its own entities only. Since 0.29.3 the day's lowest and highest voltage, read each moment the device is heard once its message is written, are kept too, in the day's row of [BAT-06](#bat-06-a-new-battery-is-detected), for How Much History to Keep. A voltage outside 0.5 to 15 volts is left out. The rows are kept for the How Much History to Keep setting's days, and Advanced shows the newest day. A battery device whose voltage sensor is switched off is listed on the Battery Voltage Switched Off card (REC).

*Proof:* [`test_battery_lithium.py`](../tests/test_battery_lithium.py), [`test_battery_model_pace.py`](../tests/test_battery_model_pace.py), [`test_battery_evidence.py`](../tests/test_battery_evidence.py), [`test_battery_voltage_card.py`](../tests/test_battery_voltage_card.py), [`test_battery_day_ranges.py`](../tests/test_battery_day_ranges.py).

### BAT-17 The Battery on the Device Page

**The device page shows the five weekly averages with each week's loss, the reading, the time left and one sentence.**
- **The chart:** draws the daily line in blue, the last five weekly averages in orange, and a fitted line on a falling battery. The weekly bars and the fitted line show at 30 and 14 days only.
- **At 90 days and longer (since 0.29.4):** the smoothed line Simple draws, thinner and in the text colour, over the daily line, with the usual bounce shaded around it: at each day, the 10th to the 90th percentile of the readings' distance from the smoothed line, fifteen days either side, weighted by distance as the line is. The legend names them "Smoothed" and "Usual bounce". A reading outside the band is a real dip or jump. The line and the band break across more than three days with no reading, so they never bridge days with no data. Each battery's history starts again when it goes in, found or entered on the device page, so they never run across a change. Since 0.29.5 a rise that was not counted as a new battery, a reading that came back after a dip, stays one line; before, any rise of 15 points from one day to the next broke it. The Future view and Simple's chart break their smoothed line the same way, and join it to where the fall starts only when the newest stretch reaches today: not across more than three days with no reading, nor up to a battery put in today. Today's slot is inside the chart whether or not a fall is drawn.
- **Line widths (since 0.29.4):** the daily line is 1.5 wide, the weekly bars 3 wide with square ends, the fitted line 1.3 wide. An outage on the device's path is shaded at least 1.5 wide and lighter, on the battery, signal and rhythm charts alike, so a month of restarts does not bar the chart.
- **Simple, and Advanced's Future range:** draw each kept day as light dots under a smoothed line, and today's reading as a solid dot ringed in white with its level beside it, "today 10%", drawn over the lines. Since 0.29.5 the reading moves below the dot where it would land on the chart's own word "today". Since 0.29.4 the scale runs from empty to the highest kept day, today's reading, the start of the fall or the low line, rounded up to the next 20%, rather than to 100% always. Where a range shows, the smoothed line runs to where the expected fall starts ([BAT-13](#bat-13-how-long-a-battery-has-left)); otherwise to today's reading. The expected fall is two red lines that end where they reach the target, with the range shaded between and the day each reaches it under the axis. The low line shows only where the history or the range reaches it.
- **In Simple:** the expected fall is drawn only when the near end is inside Days Till Low Warning.
- **Future's limit:** the longer of half the days held and Days Till Low Warning.
- **Past the limit:** when the near end is past that limit, nothing is drawn and it reads "Reaches 10% after N days." or "Empty after N days.", with N the limit.
- **Otherwise:** the lines reach the far end's day, cut at twice the limit, and the words read "Expected to reach 10% in …".

*Proof:* [`tools/panel_checks/check_battery_weeks.js`](../tools/panel_checks/check_battery_weeks.js), `check_battery_chart.js`, `check_battery_future.js`, `check_battery_steps.js`.

### BAT-18 Battery Trends

**Battery Trends reads the same weeks as the device page.**
- **Batteries to Watch:** lists the steady fallers of [BAT-14](#bat-14-warnings).
- **Falling:** shows the five weeks and the pace a week.
- **Other Cells:** shows each remaining battery's last four weeks.
- **By Model:** shows the points a week for each model. A device with no maker or model, or one that stands for none ([DEV-06](Rulebook__04_DEV_Device_Identity.md#dev-06-what-powers-a-device)), is a row of its own, not pooled with unrelated hardware (since 0.28.11), with a type chosen too. Its maker and model are followed by the device's name, so two such rows can be told apart in Simple, which leaves out WHICH ONE (since 0.29.3).
- **The summary:** splits the batteries that report a level into three parts that add up: falling, at or under the threshold and not falling, and not falling or not yet judged.

*Proof:* [`test_dashboard_trends.py`](../tests/test_dashboard_trends.py), [`tools/panel_checks/check_battery_weeks.js`](../tools/panel_checks/check_battery_weeks.js), `check_type_filters.js`.

### BAT-19 Battery Trends While Learning

**While no battery has four weeks heard, Battery Trends opens with a box saying when forecasts start (since 0.29.2).**
- **The box:** "Battery forecasts start on December 4", then "Device Sentinel needs four weeks of readings to tell a battery that is falling from one that only wobbles, and to forecast its time left. Until then each level is shown as it is read, and a battery at or under its type's threshold (10% for alkaline, 20% for lithium and other, 20% for rechargeable) is reported from the first day: 2 are now." ("1 is now", "none are now"), and a bar, "Day 7 of 28" and "21 days to go". The count is of batteries marked low, as the Problem List and the headline count them. The day counted is the most days any battery has been heard; the start is today plus the days still to go. A battery heard only every other day gets there too, more slowly.
- **The headline:** "54 batteries report a level: 2 at or under its type's threshold (10% for alkaline, 20% for lithium and other, 20% for rechargeable), 52 above it. 51 watched devices report no battery at all."
- **By Model:** a model whose batteries all have under four weeks heard reads "learning" for its rate.
- **It ends:** the box and the headline go once one battery has its four weeks, and with no battery reporting a level there is no box.

*Proof:* [`test_learning_screens.py`](../tests/test_learning_screens.py), [`tools/panel_checks/check_learning_screens.js`](../tools/panel_checks/check_learning_screens.js).

### BAT-20 Keep the Curve

**Since 0.30.1, each battery's weeks are kept for good, and a battery that ends leaves its curve.** Nothing reads them yet; they are the data a later forecast is built from.
- **A week's row:** the week's Monday, the day the battery went in, the middle level of its days, its lowest and highest (from the day ranges where kept), its lowest and highest voltage where the device reports one, the messages the device sent that week where its running count never fell, and its mean temperature where it reports one.
- **Kept for good:** in the history file, under a key of its own, never trimmed by How Much History to Keep; up to 520 weeks a device. The weeks still held day by day are worked out again at each midnight; an older week stays as written. A house that upgrades gets the weeks of the days it holds at its first start. A replacement taken back, or moved to another day, takes its weeks with it, and each week is kept once. A device gone from the house takes its weeks with it.
- **The curve:** when a battery's life row is written ([BAT-08](#bat-08-each-batterys-life-is-kept)), its weeks, the daily level, range and voltage of its last 42 days, its threshold then, the first day it read at or under it and at 0, the voltage on that day and on the last day heard, and how it ended: ran out (the device silent two days or more before the replacement) or replaced (still reporting, so stopped early).
- **Kept when good:** its kept readings reach back to three times its threshold, where a time left begins ([BAT-10](#bat-10-when-a-battery-is-judged)), and from the last week at or over that line to the end it has readings in at least four weeks out of five. It is **full** when Device Sentinel also saw the battery go in (a replacement on record) and its whole life is covered the same way. A device keeps its newest kept curve, except that a full curve is not given up for one that is not full; a curve made again for the same replacement always replaces it. The house keeps up to 2,000. Cancel takes the curve its replacement made back.
- **In the download:** each battery's weeks and each kept curve, by device id, maker and model, never a name, and for each make and model: the number of curves and of full ones, the middle weeks lasted (full curves only), the middle weeks from three times the threshold to the threshold and to the end, and the middle level of each week counted back from the end, with how many curves reach it.
- **An older release** reads the history file without them and drops them at its next save.

*Proof:* [`test_battery_curves.py`](../tests/test_battery_curves.py).
