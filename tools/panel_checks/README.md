# Panel Checks

The dashboard is JavaScript, which pytest cannot run. These checks load
`custom_components/device_sentinel/frontend/panel.js` into a simulated
browser (jsdom), answer its WebSocket calls with replies captured from
the integration, paint each tab, and check what it draws. Each file
holds the checks written for one release.

| File | Checks | What it proves |
|---|---|---|
| `check_0_22_13.js` | 16 | Classification's sources, the gear, the date beside "As of" |
| `check_0_22_14.js` | 31 | each tab's own address, and the dashboard opening on the Daily Brief |
| `check_0_22_15.js` | 19 | back links to the exact page a view was opened from |
| `check_0_22_16.js` | 6 | mutes named on a device's page, the Devices tab and an integration's page |
| `check_0_22_17.js` | 15 | every table pinned, so filters and sorts leave the columns still |
| `check_0_23_6.js` | 13 | battery trends by the week: five weekly averages, the knee and its sentence on a device's page, and Battery Trends' weekly columns |
| `check_0_23_7.js` | 12 | the weekly bars in orange and the fitted line only at 30 and 14 days, cut to the range, the knee marked only when it is inside it |

## Running Them

The build container's setup script installs jsdom, and the gate runs
every check here against the tree it is gating. By hand:

```
NODE_PATH=/home/claude/jsdom/node_modules node tools/panel_checks/check_0_22_17.js
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
