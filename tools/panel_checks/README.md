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
| Every tab | `check_stale_tab.js` | 31 | a tab left open across an update: no error from the new copy, and a line offering a reload |
| Daily Brief | `check_repeat_offenders.js` | 10 | the Repeat Offenders table, and the devices on MQTT's page that ride the broker |
| Classification | `check_classification_sources.js` | 16 | Classification's sources, the gear, the date beside "As of" |
| Integrations | `check_no_hardware_integrations.js` | 13 | an integration with no hardware of its own on the Integrations tab |
| Integrations | `check_no_hardware_pages.js` | 20 | its page, and a helper's, naming the devices it adds entities to |
| A device's page | `check_device_not_speaking.js` | 11 | what the page says when the device is not speaking |
| A device's page | `check_connects_line.js` | 4 | the Connects line, after Integration, absent where nothing is declared |
| A device's page | `check_mutes_shown.js` | 6 | mutes named on the page, the Devices tab and an integration's page |
| Battery | `check_battery_steps.js` | 6 | how a battery reports, on its page and on Battery Trends |
| Battery | `check_battery_weeks.js` | 13 | five weekly averages, the knee and its sentence, and the weekly columns |
| Battery | `check_battery_chart.js` | 12 | the weekly bars and the fitted line only at 30 and 14 days, the knee only inside the range |
| Signal | `check_dropping_out.js` | 5 | a device that keeps dropping out, on its page and on Signal Trends |

195 checks in all.

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
