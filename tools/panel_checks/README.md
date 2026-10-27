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
| Every tab | `check_tab_addresses.js` | 31 | each tab's own address, and the dashboard opening on the Daily Brief |
| Every tab | `check_back_links.js` | 19 | back links to the exact page a view was opened from, and Print beside the gear |
| Every tab | `check_controls_band.js` | 14 | the controls in a band above the tabs, and tabs that read as tabs |
| Every tab | `check_tables_hold_columns.js` | 15 | every table pinned, so filters and sorts leave the columns still |
| Every tab | `check_stale_tab.js` | 35 | a tab left open across an update: no error from the new copy, a line offering a reload, and its glow |
| Every tab | `check_release_line.js` | 11 | the release running at the foot, in Simple and Advanced, linked to its notes |
| Every tab | `check_type_filters.js` | 31 | types on Battery Trends, Classification, Devices and Recommendations, a type set from a card saying so, and no "null" on a quiet day |
| Daily Brief | `check_repeat_offenders.js` | 11 | the Repeat Offenders table, and the devices on MQTT's page that ride the broker, under Also on the Broker and Outages, Last 14 Days |
| Every tab | `check_simple_dashboard.js` | 54 | Simple and Advanced: the setting opens the dashboard, the switch holds while the page is open and through a hidden tab, Simple's tabs, its read-only device page with Not known for an unanswered Power or Type, no Rename, no Trimmed Maximum button, no turn-on buttons and no Firmware row, its battery chart with the time left, and Mute by label in Advanced |
| Recommendations | `check_recommendations.js` | 45 | the opening line and its count, which agrees with the tab and the button and reads Nothing to recommend right now at zero, the Slow Reporting Devices card, the switched-off cards' Turn on chips, Battery Voltage Switched Off among them, each saying it was pressed on the tab, a tick on each row, the count on the tab, the top band and each card's title, and a card that stays open after a tick |
| Recommendations | `check_exclusion_card.js` | 16 | the card that recommends excluding a newly seen integration, and Send to Battery Notes after a type is saved from the Power Not Set card |
| Classification | `check_classification_sources.js` | 16 | Classification's sources, the gear, the date beside "As of" |
| Classification | `check_integration_names.js` | 4 | the INTEGRATION column shows and sorts by the integration's name, its link keeping the id |
| Problem List | `check_problem_list.js` | 2 | a never-reported device's SINCE reads "discovered" with the time, as the Daily Brief says it |
| Integrations | `check_no_hardware_integrations.js` | 14 | an integration with no hardware of its own on the Integrations tab, and a summary led by the All chip's total |
| Integrations | `check_no_hardware_pages.js` | 20 | its page, and a helper's, naming the devices it adds entities to |
| A device's page | `check_device_page_layout.js` | 40 | the page's order and groups, the Firmware row with its history, live values, sensor links, both rule charts, headings in Title Case, Previous and Next, and the device cards, which say where each answer was given |
| A device's page | `check_device_actions.js` | 51 | rename, area, labels, Last Seen and the sensors turned on from the page, saying so, mutes, a refused write, and excluding one device |
| A device's page | `check_names_and_mutes.js` | 17 | names, the Last seen fallback and inherited mutes, on the page and the Problem List |
| A device's page | `check_power_row.js` | 37 | the Power row: its words and icons, the shield naming the device an answer was set on, the pencil, an answer saying it came from the page, and the report to Battery Notes; Battery Last Replaced beside it |
| A device's page | `check_node_status.js` | 12 | the Z-Wave status row: the node's status, red when dead, any other reading as not known yet, a switched-off sensor with its button, which says it was pressed on the page, and no row for other stacks |
| A device's page | `check_hub_pages.js` | 34 | a hub's page and the pages of the devices it controls, and the Classification tick |
| A device's page | `check_device_type.js` | 31 | the Type row, an answer saying it came from the page, and the Devices tab's Type column and filter |
| A device's page | `check_same_hardware.js` | 16 | the Same hardware row and the Type row's clear label |
| A device's page | `check_rhythm_rules.js` | 15 | both freeze rules on the rhythm chart, the rule in use, a swatch on every legend, and Use the 14-Day Trimmed Maximum only while the Log-Normal Percentile is in use |
| A device's page | `check_rhythm_words.js` | 11 | "learning" for a window not yet learned, a device judged by its connection, gaps rather than silences, "1 day", and the line where the 42-day chart stood while it counts again |
| A device's page | `check_real_device.js` | 6 | a page built by the server from a real mains plug's history |
| A device's page | `check_device_not_speaking.js` | 11 | what the page says when the device is not speaking |
| A device's page | `check_judged_by_line.js` | 22 | a device never judged for freezing: Judged by its hub, with a link to the hub, or Judged by its connection, in place of the window, the wait rule and the learning line, on its page and the Devices tab |
| A device's page | `check_connects_line.js` | 4 | the Connects line, after Integration, absent where nothing is declared |
| A device's page | `check_mutes_shown.js` | 7 | mutes named on the page, the Devices tab and an integration's page, which counts them as the Integrations tab does |
| A device's page | `check_dated_histories.js` | 4 | a skipped day breaks a chart's line |
| A device's page | `check_device_page_text.js` | 21 | the page reads at one size: secondary text at 14px, the heartbeat line plain, sensor names in the page's font, and other tabs unchanged |
| Devices | `check_device_finders.js` | 28 | the Devices tab's search, Area and Label filters, its Excluded list with Cancel the exclusion, and an integration's page excluding it or taking it back |
| Battery | `check_battery_steps.js` | 6 | how a battery reports, on its page and on Battery Trends |
| Battery | `check_battery_weeks.js` | 42 | five weekly averages, a model's pace as the slowest to the fastest of its other cells, an accelerating cell's sentence and no knee, a cell above twice the threshold not judged, the weekly columns, each battery named under Other Cells, with Not set where none is known, and a summary whose parts add up |
| Battery | `check_battery_future.js` | 30 | the device page's Future view: the expected fall as a shaded range, drawn as Simple's chart is |
| Battery | `check_battery_chart.js` | 15 | the weekly bars and the fitted line only at 30 and 14 days, and no straight line beside an accelerating cell's curve |
| Signal | `check_dropping_out.js` | 5 | a device that keeps dropping out, on its page and on Signal Trends |
| Signal | `check_signal_trends.js` | 8 | Signal Trends' rows add up: THIS WEEK, BEFORE THIS WEEK and CHANGE, the caption in James's words, and no "+0" or "-0.0" |
| Signal | `check_signal_chart.js` | 10 | the Signal chart on a device's page: RSSI named, the railed-day rings in the legend, and "recording began" inside the chart, above the plot area and clear of every line |

824 checks in 41 files, as of 27 October 2026 (0.27.9).

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
