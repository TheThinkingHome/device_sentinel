<!-- File: tools/panel_checks/README.md, Version: 0.28.9 (2026-11-10) -->
# Panel Checks

The dashboard is JavaScript, which pytest cannot run. These checks load
`custom_components/device_sentinel/frontend/panel.js` into a simulated
browser (jsdom), answer its WebSocket calls with replies captured from
the integration, paint each tab, and check what it draws. Each file
holds the checks for one subject, named for it (since 0.23.19; they
were named for the release that wrote them, which said when a check was
written rather than what it proves).

| Where | File | Checks | What it proves |
|---|---|---|---|
| Every tab | `check_tab_addresses.js` | 31 | each tab's own address, Classification's old address opening the Devices tab, the Problem List's opening the Daily Brief, and the dashboard opening on the Daily Brief |
| Every tab | `check_back_links.js` | 19 | back links to the exact page a view was opened from, and Print beside the gear |
| Every tab | `check_controls_band.js` | 20 | the controls in a band above the tabs, and tabs that read as tabs |
| Every tab | `check_tables_hold_columns.js` | 14 | every table pinned, so filters and sorts leave the columns still |
| Every tab | `check_stale_tab.js` | 35 | a tab left open across an update: no error from the new copy, a line offering a reload, and its glow |
| Every tab | `check_release_line.js` | 11 | the release running at the foot, in Simple and Advanced, linked to its notes |
| Every tab | `check_type_filters.js` | 35 | types on Battery Trends, Devices and Recommendations, a type in a row as a link that narrows the tab and Not Set to set one, a type set from a card saying so, and no "null" on a quiet day |
| Every tab | `check_not_set.js` | 17 | "Not Set" for a type, an area or a battery: a link that sets it in place on the Devices tab, Battery Trends and the device page, saved with where it was pressed, and "Not Watched" on the Devices tab's Excluded and Set aside chips for a device not watched, offered under its own words in the Type filter |
| Every tab | `check_acknowledged_rows.js` | 13 | an acknowledged row fades to 75% but its tick and "Acknowledged", with the hover, on the Daily Brief's Problem List, a past day's problems with nothing to press, and the Recommendations cards; the Maintenance Mode button's words |
| Every tab | `check_no_stray_words.js` | 56 | no "null" or "undefined" drawn on any tab, in Simple or Advanced |
| Integrations | `check_integrations_tab.js` | 58 | the Integrations tab's columns and buttons in both views, its chips and recommendations, and the Devices tab's columns in Simple and Advanced |
| Networks | `check_networks.js` | 41 | the Networks tab after Integrations in Simple and Advanced, its columns in each, a network's page with its counts, sensors and settings in Simple, and its coordinator, 30 days of outages, signal health and pairing in Advanced, Turn it on from the page, a count opening the Devices tab on those devices, and the other tabs drawing when the Networks answer fails |
| A network's page, more | `check_network_page_extras.js` | 48 | the Open buttons for a network's own page and its app, the Availability notice's button, its devices, makeup, offenders, firmware, Wi-Fi changes and radio noise, outage patterns with their one sentence used twice, Yes it is expected and Stop expecting this, the logbook button, the same cards on the Recommendations tab, the expected outages on the Integrations tab, and a refused button saying why |
| Daily Brief | `check_repeat_offenders.js` | 11 | the Repeat Offenders table, and the devices on MQTT's page that ride the broker, under Also on the Broker and Outages, Last 14 Days |
| Every tab | `check_simple_dashboard.js` | 57 | Simple and Advanced: the setting opens the dashboard, the switch holds while the page is open and through a hidden tab, Simple's tabs, its device page with Not Set to set an unanswered Type or Power, a set value in grey, no Labels row and a label's mute pointing to Advanced, no Rename, no Trimmed Maximum button, no turn-on buttons and no Firmware row, its battery chart with the time left, and no Mute by label anywhere; Device ID kept in Simple while the Model ID and address rows are Advanced's, and no note at the foot of the page |
| Recommendations | `check_recommendations.js` | 54 | the opening line and its count, which agrees with the tab and the button and reads Nothing to recommend right now at zero, the Slow Reporting Devices card, the switched-off cards' Turn on chips, Battery Voltage Switched Off among them, each saying it was pressed on the tab, a tick on each row, the count on the tab, the top band and each card's title, and a card that stays open after a tick, and the area, name and model type set in each card's rows |
| Recommendations | `check_exclusion_card.js` | 18 | the card that recommends excluding a newly seen integration, and Send to Battery Notes after a type is saved from the Power Not Set card |
| Devices | `check_classification_sources.js` | 19 | the gear, the date beside "As of", the Devices tab's Watched, Excluded and Set aside chips with each one's STANDING, Classification's old address opening Set aside, and Simple without Set aside |
| Devices | `check_integration_names.js` | 4 | the INTEGRATION column shows and sorts by the integration's name, its link keeping the id |
| Every tab | `check_device_links.js` | 6 | a device's name opens a page that is there: its page here when Device Sentinel has one, Home Assistant's own device page for any other device still in Home Assistant, plain words for one removed from it, in the Daily Brief's tables, MQTT's Also on the Broker and a network page's hardware |
| Daily Brief | `check_problem_list.js` | 14 | the Problem List at the head of the Daily Brief: one tab, its sections Problem List, Repeat Offenders and What Happened, today's list with its filters, ticks and mutes, a past day's to read only and kept through a device page, today again from another tab or the tab pressed, a late answer never drawn over another tab, today's list kept when the rest fails, the old address, and a never-reported device's SINCE reading "discovered" with the time |
| Integrations | `check_no_hardware_integrations.js` | 8 | an integration with no hardware of its own on the Integrations tab, and a summary led by the All chip's total |
| Integrations | `check_no_hardware_pages.js` | 18 | its page, and a helper's, naming the devices it adds entities to |
| A device's page | `check_device_page_layout.js` | 58 | the page's order and its four groups (Power, Signal, Reporting, Actions), the Firmware row with its history or one line for one version, live values, sensor links, both rule charts, headings in Title Case, Previous and Next from every page that lists devices (staying in the table or list pressed, stepping to set-aside and excluded devices with a page here and passing by those without, grey after a reload), and the device cards, which say where each answer was given |
| A device's page | `check_device_actions.js` | 55 | rename, area with No area asking first, labels with the one that mutes drawn lit by its id (a comma in its name included), Last Seen and the sensors turned on from the page, saying so, mute buttons showing only the device's own mutes, a refused write, and excluding one device |
| A device's page | `check_names_and_mutes.js` | 17 | names, the Last seen fallback and inherited mutes, on the page and the Problem List |
| A device's page | `check_power_row.js` | 38 | the Powered by row: its words and icons, the shield naming the device an answer was set on, the pencil, an answer saying it came from the page, and the report to Battery Notes; Battery last replaced beside it |
| A device's page | `check_node_status.js` | 12 | the Z-Wave status row: the node's status, red when dead, any other reading as not known yet, a switched-off sensor with its button, which says it was pressed on the page, and no row for other stacks |
| A device's page | `check_hub_pages.js` | 40 | a hub's page and the pages of the devices it controls, and a hub and a device judged by its hub in the Devices tab's STANDING |
| A device's page | `check_device_type.js` | 31 | the Type row, an answer saying it came from the page, and the Devices tab's Type column and filter |
| A device's page | `check_same_hardware.js` | 16 | the Same hardware row and the Type row's clear label |
| A device's page | `check_removed_days.js` | 21 | a day removed by hand: any bar pressable in Advanced for a person who may act, the removal's warning and the question to count it again, nothing sent before the answer, the removed day in its own colour at its height and never hatched or grey, the keyboard, a refusal under the charts, and nothing to press in Simple or for a viewer |
| A device's page | `check_status_readings.js` | 9 | a Z-Wave controller's status with when it began, shown in Simple only when it is not Ready; a Tasmota device's last restart and reason with the earlier ones folded under it, in Advanced only |
| A device's page | `check_rhythm_rules.js` | 15 | both freeze rules on the rhythm chart, the rule in use, a swatch on every legend, and Use the 14-Day Trimmed Maximum only while the Log-Normal Percentile is in use |
| A device's page | `check_rhythm_words.js` | 19 | "learning" for a window not yet learned, a device judged by its connection, gaps rather than silences, "1 day", the LEARNED column in plain words, and the line where the 42-day chart stood while it counts again, naming why when it is known |
| A device's page | `check_real_device.js` | 6 | a page built by the server from a real mains plug's history |
| A device's page | `check_device_not_speaking.js` | 11 | what the page says when the device is not speaking |
| A device's page | `check_judged_by_line.js` | 22 | a device never judged for freezing: Judged by its hub, with a link to the hub, or Judged by its connection, in place of the window, the wait rule and the learning line, on its page and the Devices tab |
| A device's page | `check_connects_line.js` | 4 | the Connects line, after Integration, absent where nothing is declared |
| A device's page | `check_mutes_shown.js` | 7 | mutes named on the page, the Devices tab and an integration's page, which counts them as the Integrations tab does |
| A device's page | `check_dated_histories.js` | 4 | a skipped day breaks a chart's line |
| A device's page | `check_status_bar.js` | 16 | the status bar: green within the rhythm, yellow past it, red when frozen, gray for unavailable with "Unavailable since" (with the date when it went on an earlier day) and the bar stopped when the device went, and no NaN from a time that cannot be read; and Its Rhythm's line under the wait rule, the button at its own width, chart titles at 16px and room between the charts |
| A device's page | `check_device_page_text.js` | 21 | the page reads at one size: secondary text at 14px, the heartbeat line plain, sensor names in the page's font, and other tabs unchanged |
| Devices | `check_device_finders.js` | 50 | the Devices tab's search, Area and Label filters, an area in a row as a link that narrows the list, its Excluded chip, information only, and Set aside chip, each chip's own choices, the known type of an excluded device, the page a name opens, and an integration's page with the Integrations tab's five buttons, lit when on and undone by a second press |
| Battery | `check_battery_steps.js` | 9 | how a battery reports, "Battery reports in" on its page in Advanced, and on Battery Trends |
| Battery | `check_battery_weeks.js` | 46 | five weekly averages, a model's pace as the slowest to the fastest of its other cells, an accelerating cell's sentence and no knee, a cell above twice the threshold not judged, the weekly columns, each battery named under Other Cells, with Not set where none is known, and a summary whose parts add up |
| Battery | `check_battery_future.js` | 30 | the device page's Future view: the expected fall as a shaded range, drawn as Simple's chart is |
| Battery | `check_battery_chart.js` | 15 | the weekly bars and the fitted line only at 30 and 14 days, and no straight line beside an accelerating cell's curve |
| Signal | `check_short_drop_outs.js` | 15 | a device with short drop-outs, on its page and on Signal Trends, and its Short drop-outs row |
| A device's page | `check_wifi_address.js` | 11 | a Wi-Fi device's IP Address and Access Point, and devices sharing one address on the Recommendations tab |
| Signal | `check_signal_trends.js` | 8 | Signal Trends' rows add up: THIS WEEK, BEFORE THIS WEEK and CHANGE, the caption's fixed wording, and no "+0" or "-0.0" |
| Signal | `check_signal_chart.js` | 10 | the Signal chart on a device's page: RSSI named, the railed-day rings in the legend, and "recording began" inside the chart, above the plot area and clear of every line |

1193 checks in 51 files, as of 9 November 2026 (0.28.7).

## Running Them

The build container's setup script installs jsdom, and the gate runs
every check here against the tree it is gating. By hand:

```
NODE_PATH=/home/claude/jsdom/node_modules node tools/panel_checks/check_tables_hold_columns.js
```

Each check reads the repository's own `panel.js` unless a path to
another is passed as the first argument. `npm install` in this folder
works as well, if jsdom is wanted beside the checks.

## The Replies They Read

`payloads.json` comes from a four-device test house built by
`capture_test_house.py`. `payloads_fleet.json` comes from the committed
reference fleet in `tests/fleets/`, anonymized, through
`capture_reference_fleet.py`, because widths and volumes only show on a
real house. To capture again, copy the script into `tests/`, run it
with pytest, and delete the copy. Never commit replies captured from
the private archive's real files: they carry real device names.

A harness has to behave like Home Assistant's router. A tab click moves
the address and waits for Home Assistant to hand the panel a new route,
so a harness that never sets `panel.route` shows tabs that never paint.
