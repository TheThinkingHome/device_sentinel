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
| Every tab | `check_type_filters.js` | 30 | types on Battery Trends, Classification, Devices and Recommendations, and no "null" on a quiet day |
| Daily Brief | `check_repeat_offenders.js` | 10 | the Repeat Offenders table, and the devices on MQTT's page that ride the broker |
| Recommendations | `check_recommendations.js` | 2 | the opening line: what the recommendations are for, and that none is required |
| Classification | `check_classification_sources.js` | 16 | Classification's sources, the gear, the date beside "As of" |
| Integrations | `check_no_hardware_integrations.js` | 13 | an integration with no hardware of its own on the Integrations tab |
| Integrations | `check_no_hardware_pages.js` | 20 | its page, and a helper's, naming the devices it adds entities to |
| A device's page | `check_device_page_layout.js` | 32 | the page's order and groups, live values, sensor links, both rule charts, Previous and Next, and the device cards |
| A device's page | `check_device_actions.js` | 37 | rename, area, labels, Last Seen, mutes, a refused write, and excluding one device |
| A device's page | `check_names_and_mutes.js` | 17 | names, the Last seen fallback and inherited mutes, on the page and the Problem List |
| A device's page | `check_power_row.js` | 26 | the Power row: its words and icons, the pencil, and the report to Battery Notes |
| A device's page | `check_device_type.js` | 30 | the Type row, and the Devices tab's Type column and filter |
| A device's page | `check_same_hardware.js` | 16 | the Same hardware row and the Type row's clear label |
| A device's page | `check_rhythm_rules.js` | 14 | both freeze rules on the rhythm chart, the rule in use, and a swatch on every legend |
| A device's page | `check_real_device.js` | 6 | a page built by the server from a real mains plug's history |
| A device's page | `check_device_not_speaking.js` | 11 | what the page says when the device is not speaking |
| A device's page | `check_connects_line.js` | 4 | the Connects line, after Integration, absent where nothing is declared |
| A device's page | `check_mutes_shown.js` | 6 | mutes named on the page, the Devices tab and an integration's page |
| A device's page | `check_dated_histories.js` | 4 | a skipped day breaks a chart's line |
| Battery | `check_battery_steps.js` | 6 | how a battery reports, on its page and on Battery Trends |
| Battery | `check_battery_weeks.js` | 13 | five weekly averages, the knee and its sentence, and the weekly columns |
| Battery | `check_battery_chart.js` | 12 | the weekly bars and the fitted line only at 30 and 14 days, the knee only inside the range |
| Signal | `check_dropping_out.js` | 5 | a device that keeps dropping out, on its page and on Signal Trends |

444 checks in 27 files, as of 11 October 2026.

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
