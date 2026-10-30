# Device Sentinel Rulebook: Dashboard (DASH)

*Version: rulebook, 30 October 2026, on Device Sentinel 0.27.15. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

This section covers the Device Sentinel dashboard: how it is registered, its top band and tabs, Simple and Advanced, the device page's rows and actions, the Devices tab's filters, the update banner and the footer. The Battery chart and Battery Trends are under [BAT](Rulebook__09_BAT_Battery.md), the rhythm chart and the wait rules under [FRZ](Rulebook__05_FRZ_Freeze.md), and the signal chart under [SIG](Rulebook__10_SIG_Signal.md). The Recommendations tab and its cards are under [REC](Rulebook__15_REC_Recommendations.md), including the cards staying open. What a mute does is under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md). The answers in the Power, Type and Battery Last Replaced rows are under [DEV](Rulebook__04_DEV_Device_Identity.md) and BAT.

### DASH-01 How the Dashboard Is Registered

**The dashboard is registered through Home Assistant's panel_custom, for administrators. The integration lists frontend and panel_custom among its dependencies.**

*Proof:* [`test_dashboard_panel.py`](../tests/test_dashboard_panel.py), [`test_manifest_dependencies.py`](../tests/test_manifest_dependencies.py).

### DASH-02 The Top Band and the Tabs

**The status tiles and the action buttons sit in a band of their own above the tabs, and the tabs read as tabs.**
- **In the band:** Refresh, the Maintenance Mode button with its length list, the Active Recommendations button (REC), the Simple and Advanced switch, and the time the figures were read.
- **The Maintenance Mode button:** it says what pressing it does. Off, it reads "Start Maintenance Mode". Open, it reads "End Maintenance Mode" with the minutes left, counted down while the page is open.
- **The tabs:** Daily Brief, Problem List, Battery Trends, Signal Trends, Classification, Integrations, Devices and Recommendations, each with its own address.

*Proof:* [`tools/panel_checks/check_controls_band.js`](../tools/panel_checks/check_controls_band.js), `check_tab_addresses.js`, `check_recommendations.js`, `check_acknowledged_rows.js`.

### DASH-03 Simple or Advanced

**A setting on the Advanced settings screen, "Dashboard: Simple or Advanced", decides how the dashboard opens.**
- **The default:** Simple on a new install, Advanced on an install that upgraded to 0.26.7.
- **The switch:** the switch in the top band changes the view while the person stays on the dashboard, including while its browser tab is hidden.
- **Starting again:** leaving for another page of Home Assistant, closing the window or reloading starts again from the setting. Nothing is kept in the browser.

*Proof:* [`test_dashboard_mode.py`](../tests/test_dashboard_mode.py), [`tools/panel_checks/check_simple_dashboard.js`](../tools/panel_checks/check_simple_dashboard.js).

### DASH-04 What Simple Shows

**Simple shows six tabs: Daily Brief, Problem List, Battery Trends, Integrations, Devices and Recommendations.** Which recommendations Simple shows is in [REC](Rulebook__15_REC_Recommendations.md).
- **Tabs left off:** Signal Trends and Classification. Each still opens from its own address, and no page in Simple links to it.
- **Battery Trends in Simple:** it leaves out the TYPICAL LEVEL, LOWEST CELL and WHICH ONE columns, the weekly levels under Falling, DAYS RECORDED, STEPS and MODEL, A WEEK under Other Cells, and the Not a Percentage list. Advanced's At or Under the Threshold adds 4 WEEKS.
- **Battery Trends' tables:** they share one scale, so DEVICE, TYPE and LEVEL stand in the same place in each. A table with few columns ends short of the edge.
- **Devices tab in Simple:** it shows TYPE and its filter. It leaves out the label filter, AREA, BATTERY, LAST REPORT, RHYTHM and WINDOW.
- **"Not Set":** a type, an area or a battery type nobody has set reads "Not Set", in Simple and Advanced, on every tab and on the device page. It is a link that opens the way to set it in place, with no question first. A type or a battery type is set for every device of the model; an area for that one device, in Home Assistant. The brief says where it was set ([BRIEF-07](Rulebook__13_BRIEF_Daily_Brief.md#brief-07-last-24-hours)). A value that is set is words, with nothing to press; on Simple's device page it is grey. In Advanced the device page keeps the pencil beside each value, set or not, so anything set can be changed. The Type and Area filters name the choice "Not Set" too.
- **Asking for input:** nothing in Simple asks for more, except "Not Set", the Battery Last Replaced pencil, the Confirm Battery Replacement card and the Mute buttons.
- **Device page actions in Simple:** no Rename, no "Use the 14-Day Trimmed Maximum" and no button to turn a sensor on. A switched-off sensor is turned on from its Recommendations card (REC). Type, Area and Power (with the battery type) are read-only once set.
- **Labels in Simple:** the device page has no Labels row. A mute from a label is one line in the Muted row, "Freeze is muted by the label Outdoor. Switch to Advanced to change it.", where "Advanced" switches the view ([MUTE-09](Rulebook__03_MUTE_Muting_and_Exclusion.md#mute-09-mutes-on-the-device-page-and-the-problem-list)).
- **Exclusions in Simple:** Exclude this device is hidden. An exclusion already made still shows with its way back. Whole integrations are excluded and muted on the Integrations tab ([MUTE-03](Rulebook__03_MUTE_Muting_and_Exclusion.md#mute-03-excluding-one-device-or-one-integration)).
- **Device page rows in Simple:** the rhythm chart, its figures, the Wait rule row and the gaps table show only for a device that is frozen or has never reported. The Signal group shows only when the device's latest signal day is railed. The Last seen sensor row shows only when its sensor is switched off. The Z-Wave status row shows only when the node is dead or its sensor is switched off. The dropout counts show only while the device is dropping out. The firmware history never shows.

*Proof:* [`tools/panel_checks/check_simple_dashboard.js`](../tools/panel_checks/check_simple_dashboard.js), `check_integrations_tab.js`, `check_not_set.js`, `check_battery_weeks.js`, `check_type_filters.js`.

### DASH-05 The Look

**Name and Area carry small edit marks, and one-off acts are slim chips. The slim chip style is used wherever it fits across the dashboard.**
- **Helper lines:** no helper line sits beside an action on the device page, including the 14-Day Trimmed Maximum button. The page's notes under its headings and charts stay.
- **Dark theme:** each dropdown is readable on a dark theme.
- **Chart legends:** each legend entry has its swatch, drawn in the colour and style of its line.

*Proof:* [`tools/panel_checks/check_device_actions.js`](../tools/panel_checks/check_device_actions.js), `check_rhythm_rules.js`, `check_signal_chart.js`, `check_power_row.js`.

### DASH-06 The Device Page Reads at One Size

**On a device's page, text reads at the page's size, 14px, in the page's own font.**
- **What this covers:** the secondary text in its rows (such as "heard by Device Sentinel 9m ago" and "changed 3m ago"), the rhythm line, the chart notes and the page's closing note.
- **Heartbeat and sensor names:** the heartbeat line is plain grey text, not a pill, and a sensor's name is not monospace.
- **What keeps its size:** headings, column headings, the large figures, buttons, chips, the charts' own labels and the release line at the foot ([DASH-15](#dash-15-the-footer)).
- **Elsewhere:** other tabs and the printout are unchanged.

*Proof:* [`tools/panel_checks/check_device_page_text.js`](../tools/panel_checks/check_device_page_text.js).

### DASH-07 The Device Page's Top Row

**The top row carries the way back, Previous and Next, and "Open in Home Assistant", which appears once and only there.**
- **Previous and Next:** they step through the list the page was opened from (the Devices tab, the Problem List or a recommendation card), falling back to the Devices tab's order. They skip a device removed since the list was drawn.

*Proof:* [`tools/panel_checks/check_device_page_layout.js`](../tools/panel_checks/check_device_page_layout.js), `check_device_actions.js`.

### DASH-08 The Identity Section

**Below the status, the Identity section lists who the device is. There is no separate Live readings section.**
- **Identity rows:** Name, Type, Device ID, Area, Labels, Manufacturer, Model, Model ID, Hardware version, Integration, Connects, Same hardware (for a device another integration also lists) and its addresses.
- **Then three groups:** Power: Battery level, Battery sensor, Power, Battery Last Replaced and Battery steps. Signal: Signal and Signal sensor. Last seen: Last seen, Last seen sensor with its heartbeat tag, Z-Wave status, First seen, Events seen and Wait rule. A hub's own page leaves the Last seen group out.
- **Then:** Muted and Excluded.
- **Each row:** each value shows when it changed, and each sensor is a link that opens the entity in Home Assistant.
- **No readable Last seen sensor:** the device shows when Device Sentinel last heard it, which repeats the status line by choice.
- **Below:** everything from the gaps table, "Gaps, Last 14 Days", down is unchanged by this order.

*Proof:* [`tools/panel_checks/check_device_page_layout.js`](../tools/panel_checks/check_device_page_layout.js), `check_names_and_mutes.js`, `check_real_device.js`, `check_hub_pages.js`.

### DASH-09 Acting From the Device Page

**The device page lets a person rename the device, change its area and labels, turn on switched-off sensors, mute it and open it in Home Assistant.** Simple offers fewer of these ([DASH-04](#dash-04-what-simple-shows)).
- **What it offers:** Rename, with "Reset to" the integration's name. Area, changed with its pencil. A Labels row after Area. Mute, for freeze, unavailable, battery, signal or everything (see [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md)). Open in Home Assistant ([DASH-07](#dash-07-the-device-pages-top-row)).
- **Turning sensors on:** "Turn on its Last Seen" appears in the Last seen sensor row when that sensor is switched off, and a turn-on appears in the Battery sensor, Signal sensor and Z-Wave status rows the same way. A battery voltage sensor is turned on from its card only (see [REC](Rulebook__15_REC_Recommendations.md)).
- **Where changes are written:** labels, area and name are written through Home Assistant's own registries. A removed label is never deleted from Home Assistant.
- **New labels and areas:** one can be created from Device Sentinel's own pickers. A name Home Assistant already has is used as it is, so a second "Garage" is never made.
- **No button:** Manufacturer, Model, Model ID, Hardware version, the addresses and Device ID have none, since their integration would overwrite an edit.

*Proof:* [`tools/panel_checks/check_device_actions.js`](../tools/panel_checks/check_device_actions.js).

### DASH-10 Confirmations and Refusals

**An act that can be undone on the page asks for no confirmation; Mute everything asks once. When a write is refused, Home Assistant's reason shows under its row, and the row keeps its old value.**
- **No area:** choosing "No area" for a device that has one asks first, "Remove (device) from (area) in Home Assistant?", with "Remove from area" and "Keep its area", because taking a device out of its area changes Home Assistant's own dashboards, voice and area automations at once. Choosing another area does not ask.

*Proof:* [`tools/panel_checks/check_device_actions.js`](../tools/panel_checks/check_device_actions.js).

### DASH-11 A Change Shows on the Other Tabs

**After a change on a device page, the other tabs (Devices, Problem List and the rest) show it without pressing Refresh.**

*Proof:* [`tools/panel_checks/check_device_actions.js`](../tools/panel_checks/check_device_actions.js).

### DASH-12 Finding a Device

**The Devices tab has a name search, an Area filter with "Not Set", and a Label filter beside the type filter.**
- **An area in a row:** in both lists, a set area is a link. Pressing it narrows the list to that area, the same as choosing it in the Area filter. AREA shows in Advanced only.
- **The Excluded list:** a link, "Show the N excluded devices", opens it. It lists the devices on the exclusion lists, read live from Home Assistant's registry and the settings, with nothing stored.
- **Each row says:** whether the device was excluded by the person or with its integration, and whether its history is kept until midnight or already deleted. Its AREA reads "Not Set" when none is set ([DASH-04](#dash-04-what-simple-shows)).
- **Its columns:** the list has its own widths, so "Cancel the exclusion" or "Open its integration page" stays on one line.
- **Ways back:** a device excluded on its own has "Cancel the exclusion", which the brief records as "from the Devices tab". One excluded with its integration links to that integration's page. One whose history has gone opens Home Assistant's own device page.

*Proof:* [`tools/panel_checks/check_device_finders.js`](../tools/panel_checks/check_device_finders.js), `check_not_set.js`.

### DASH-13 Devices Behind the Broker

**The MQTT integration's page lists, beneath its own devices and under "Also on the Broker", the devices another integration owns that reach Home Assistant only through the broker, such as Tasmota's.**

*Proof:* [`test_dashboard_api.py`](../tests/test_dashboard_api.py).

### DASH-14 The Update Banner

**A dashboard left open across an update registers nothing new and raises no error.**
- **When it shows:** once the page knows it runs an older file than the one served, it shows "Device Sentinel was updated. Reload this page to use the new version." with a Reload button. The page learns this from the new copy's word, or from the file the server names in each status reply and change marker.
- **Motion:** the banner glows three times when it appears, then holds steady. A viewer whose device asks for less motion sees it still.

*Proof:* [`tools/panel_checks/check_stale_tab.js`](../tools/panel_checks/check_stale_tab.js), [`test_dashboard_panel.py`](../tests/test_dashboard_panel.py).

### DASH-15 The Footer

**"Device Sentinel" and the version running sit at the foot of each tab and page, in Simple and Advanced alike, linked to that release's notes. A version that does not read as a release tag is printed with no link.**

*Proof:* [`tools/panel_checks/check_release_line.js`](../tools/panel_checks/check_release_line.js), [`test_release_line.py`](../tests/test_release_line.py).

### DASH-16 Names and Counts on the Tabs

**The status band names the Wi-Fi tile "Wi-Fi", whatever the sensor is called. No page draws a part left out as the word "null".**
- **Classification tab:** it names each integration as Home Assistant shows it, not by its id, and a set-aside reason names the integration the same way.
- **Integrations tab summary:** it opens with the All chip's total. Its chips are All, Recommended, Trouble, Excluded and Muted.
- **Integrations tab columns in Simple:** three. INTEGRATION has the name, its device count in brackets and its id, and under them what Device Sentinel recommends and, for one with nothing to watch, what it is. EXCLUDE AND MUTE has the five buttons ([MUTE-03](Rulebook__03_MUTE_Muting_and_Exclusion.md#mute-03-excluding-one-device-or-one-integration)). TROUBLE has what is wrong on its devices at present, worst first, after "Down since" when the integration is down.
- **Integrations tab in Advanced:** it adds SET ASIDE and OUTAGES, 14 DAYS before TROUBLE, which stays last.
- **The five buttons:** each keeps one width on one line.
- **An integration's page:** it counts its devices muted from everything.
- **Devices tab in Advanced:** it shows DEVICE, TYPE, AREA, INTEGRATION, STANDING, PROBLEM, BATTERY (the level as a percentage; a raw value is left blank), LAST REPORT, RHYTHM and WINDOW.
- **Still learning:** on the Devices tab, a device whose wait is still being learned reads "learning" under WINDOW, never a blank.
- **Never judged for freezing:** such a device reads "Judged by its hub, <name>", the name opening the hub's page, or "Judged by its connection", in place of a window. This shows on the Devices tab and on the device page.

*Proof:* [`test_classification_sources.py`](../tests/test_classification_sources.py), [`test_integration_names.py`](../tests/test_integration_names.py), [`test_dashboard_integrations.py`](../tests/test_dashboard_integrations.py), [`test_wifi_outage.py`](../tests/test_wifi_outage.py), [`tools/panel_checks/check_integration_names.js`](../tools/panel_checks/check_integration_names.js), `check_no_hardware_integrations.js`, `check_mutes_shown.js`, `check_rhythm_words.js`, `check_judged_by_line.js`, [`test_judged_by.py`](../tests/test_judged_by.py), `check_integrations_tab.js`, [`test_integrations_tab.py`](../tests/test_integrations_tab.py), `check_no_stray_words.js`, [`test_dashboard_devices.py`](../tests/test_dashboard_devices.py).
