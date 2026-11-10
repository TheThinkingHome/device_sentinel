# Device Sentinel Rulebook: Dashboard (DASH)

*Version: rulebook, 9 November 2026, on Device Sentinel 0.28.8. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

This section covers the Device Sentinel dashboard: how it is registered, its top band and tabs, Simple and Advanced, the device page's rows and actions, the Devices tab's filters, the update banner and the footer. The Battery chart and Battery Trends are under [BAT](Rulebook__09_BAT_Battery.md), the rhythm chart and the wait rules under [FRZ](Rulebook__05_FRZ_Freeze.md), and the signal chart under [SIG](Rulebook__10_SIG_Signal.md). The Recommendations tab and its cards are under [REC](Rulebook__15_REC_Recommendations.md), including the cards staying open. What a mute does is under [MUTE](Rulebook__03_MUTE_Muting_and_Exclusion.md). The answers in the Powered by, Type and Battery last replaced rows are under [DEV](Rulebook__04_DEV_Device_Identity.md) and BAT.

### DASH-01 How the Dashboard Is Registered

**The dashboard is registered through Home Assistant's panel_custom, for administrators. The integration lists frontend and panel_custom among its dependencies.**

*Proof:* [`test_dashboard_panel.py`](../tests/test_dashboard_panel.py), [`test_manifest_dependencies.py`](../tests/test_manifest_dependencies.py).

### DASH-02 The Top Band and the Tabs

**The status tiles and the action buttons sit in a band of their own above the tabs, and the tabs read as tabs.**
- **In the band:** Refresh, the Maintenance Mode button with its length list, the Active Recommendations button (REC), the Simple and Advanced switch, and the time the figures were read.
- **One row (since 0.28.0):** the status tiles and the buttons sit in one row, each part as wide as its words, wrapping onto a second row only on a narrow screen. "As of" sits under the band, at its right edge, in small text.
- **The Maintenance Mode button:** it says what pressing it does. Off, it reads "Start Maintenance Mode". Open, it reads "End Maintenance Mode" with the minutes left, counted down while the page is open.
- **The tabs:** Daily Brief, Problem List, Battery Trends, Signal Trends, Integrations, Networks ([DASH-17](#dash-17-the-networks-tab)), Devices and Recommendations, each with its own address. Since 0.28.8 there is no Classification tab: the Devices tab shows every device found ([DASH-12](#dash-12-finding-a-device)), and Classification's old address opens it on the Set aside chip.

*Proof:* [`tools/panel_checks/check_controls_band.js`](../tools/panel_checks/check_controls_band.js), `check_tab_addresses.js`, `check_recommendations.js`, `check_acknowledged_rows.js`.

### DASH-03 Simple or Advanced

**A setting on the Advanced settings screen, "Dashboard: Simple or Advanced", decides how the dashboard opens.**
- **The default:** Simple on a new install, Advanced on an install that upgraded to 0.26.7.
- **The switch:** the switch in the top band changes the view while the person stays on the dashboard, including while its browser tab is hidden.
- **Starting again:** leaving for another page of Home Assistant, closing the window or reloading starts again from the setting. Nothing is kept in the browser.

*Proof:* [`test_dashboard_mode.py`](../tests/test_dashboard_mode.py), [`tools/panel_checks/check_simple_dashboard.js`](../tools/panel_checks/check_simple_dashboard.js).

### DASH-04 What Simple Shows

**Simple shows seven tabs: Daily Brief, Problem List, Battery Trends, Integrations, Networks, Devices and Recommendations.** Which recommendations Simple shows is in [REC](Rulebook__15_REC_Recommendations.md).
- **Tab left off:** Signal Trends. It still opens from its own address, and no page in Simple links to it.
- **Battery Trends in Simple:** it leaves out the TYPICAL LEVEL, LOWEST CELL and WHICH ONE columns, the weekly levels under Falling, DAYS RECORDED, STEPS and MODEL, A WEEK under Other Cells, and the Not a Percentage list. Advanced's At or Under the Threshold adds 4 WEEKS.
- **Battery Trends' tables:** they share one scale, so DEVICE, TYPE and LEVEL stand in the same place in each. A table with few columns ends short of the edge.
- **Devices tab in Simple:** it shows TYPE and its filter, and the Excluded chip. It leaves out the Set aside chip, the label filter, AREA, LAST REPORT and WINDOW.
- **"Not Set":** a type, an area or a battery type nobody has set reads "Not Set", in Simple and Advanced, on every tab and on the device page. It is a link that opens the way to set it in place, with no question first. A type or a battery type is set for every device of the model; an area for that one device, in Home Assistant. The brief says where it was set ([BRIEF-07](Rulebook__13_BRIEF_Daily_Brief.md#brief-07-last-24-hours)). A value that is set is words, with nothing to press; on Simple's device page it is grey. In Advanced the device page keeps the pencil beside each value, set or not, so anything set can be changed. The Type and Area filters name the choice "Not Set" too.
- **Asking for input:** nothing in Simple asks for more, except "Not Set", the Battery last replaced pencil, the Confirm Battery Replacement card and the Mute buttons.
- **Device page actions in Simple:** no Rename, no "Use the 14-Day Trimmed Maximum" and no button to turn a sensor on. A switched-off sensor is turned on from its Recommendations card (REC). Type, Area and Power (with the battery type) are read-only once set.
- **Labels in Simple:** the device page has no Labels row. A mute from a label is one line in the Muted row, "Freeze is muted by the label Outdoor. Switch to Advanced to change it.", where "Advanced" switches the view ([MUTE-09](Rulebook__03_MUTE_Muting_and_Exclusion.md#mute-09-mutes-on-the-device-page-and-the-problem-list)).
- **Exclusions in Simple:** Exclude this device is hidden. An exclusion already made still shows with its way back. Whole integrations are excluded and muted on the Integrations tab ([MUTE-03](Rulebook__03_MUTE_Muting_and_Exclusion.md#mute-03-excluding-one-device-or-one-integration)).
- **Device page rows in Simple:** the Device ID shows; the Model ID, the addresses (Zigbee Address, Z-Wave Node and the like), Battery reports in and the battery evidence line do not. The rhythm chart, its figures, the wait rule and the gaps table show only for a device that is frozen or has never reported. The Signal group shows only when the device's latest signal day is railed. The Last seen sensor row shows only when its sensor is switched off. The Z-Wave status row shows only when the node is dead or its sensor is switched off, and a Z-Wave controller's Controller status row only when it is not Ready ([STACK-15](Rulebook__08_STACK_Stacks.md#stack-15-a-z-wave-controllers-own-status)). The Last restart row never shows ([DEV-17](Rulebook__04_DEV_Device_Identity.md#dev-17-why-a-tasmota-device-restarted)). The Short drop-outs row shows only while the device has short drop-outs; the Signal group then shows for that row ([SIG-16](Rulebook__10_SIG_Signal.md)). The IP Address row shows only while another device holds the same address, and the Access Point row never ([UP-19](Rulebook__07_UP_Upstream_Outages.md)). The firmware history never shows.

*Proof:* [`tools/panel_checks/check_simple_dashboard.js`](../tools/panel_checks/check_simple_dashboard.js), `check_integrations_tab.js`, `check_not_set.js`, `check_battery_weeks.js`, `check_type_filters.js`.

### DASH-05 The Look

**Name and Area carry small edit marks, and one-off acts are slim chips. The slim chip style is used wherever it fits across the dashboard.**
- **Helper lines:** no helper line sits beside an action on the device page, including the 14-Day Trimmed Maximum button. The page's notes under its headings and charts stay.
- **Dark theme:** each dropdown is readable on a dark theme.
- **Chart legends:** each legend entry has its swatch, drawn in the colour and style of its line.

*Proof:* [`tools/panel_checks/check_device_actions.js`](../tools/panel_checks/check_device_actions.js), `check_rhythm_rules.js`, `check_signal_chart.js`, `check_power_row.js`.

### DASH-06 The Device Page Reads at One Size

**On a device's page, text reads at the page's size, 14px, in the page's own font.**
- **What this covers:** the secondary text in its rows (such as "heard by Device Sentinel 9m ago" and "changed 3m ago"), the rhythm line and the chart notes. The page has no closing note since 0.27.16.
- **Sensor notes and names:** the note beside the Last seen sensor ("used to tell it's alive") is plain grey text, not a pill, and a sensor's name is not monospace.
- **What keeps its size:** headings (the rhythm charts' titles among them), column headings, the large figures, buttons, chips, the charts' own labels and the release line at the foot ([DASH-15](#dash-15-the-footer)).
- **Elsewhere:** other tabs and the printout are unchanged.

*Proof:* [`tools/panel_checks/check_device_page_text.js`](../tools/panel_checks/check_device_page_text.js).

### DASH-07 The Device Page's Top Row

**The top row carries the way back, Previous and Next, and "Open in Home Assistant", which appears once and only there.**
- **Previous and Next:** they step through the list the page was opened from, in the order it was shown: the Devices tab (on any of its chips), the Problem List, a recommendation card, or, since 0.28.7, any other page that links to devices, such as an integration's or a network's page, the Daily Brief or Battery Trends. On such a page the list is the table, list or card the device was pressed in, so Next from the Daily Brief's Last 24 Hours table stays in that table; pressed outside any, it is every device the page links to. They skip a device removed from the house since the list was drawn; a set-aside or excluded device the page showed is stepped to. A device opened straight from its own address steps through the Devices tab's order. Since 0.28.7, a device opened from another page whose list is gone, as after a reload, has nowhere to step: Previous and Next are grey, so Next never leaves the list the page was opened from (before, it fell back to the Devices tab and walked into other integrations' devices).

*Proof:* [`tools/panel_checks/check_device_page_layout.js`](../tools/panel_checks/check_device_page_layout.js), `check_device_actions.js`.

### DASH-08 The Identity Section

**Below the status, the Identity section lists who the device is. There is no separate Live readings section.**
- **Identity rows:** Name, Type, Device ID, Area, Labels, Manufacturer, Model, Model ID, Hardware version, Firmware, Integration, Connects, Same hardware (for a device another integration also lists), its addresses, and, for a Wi-Fi device its router reports, IP Address and Access Point, each with when it last changed ([UP-19](Rulebook__07_UP_Upstream_Outages.md)).
- **Then four groups:** Power: Battery level, Battery sensor, Powered by, Battery last replaced and Battery reports in. Signal: Signal, Signal sensor and Short drop-outs ([SIG-16](Rulebook__10_SIG_Signal.md)). Reporting: Last seen, Last seen sensor with a note saying how it tells the device is alive, Z-Wave status, Controller status for a Z-Wave controller, Last restart for a Tasmota device, First seen and Events seen. Actions: Muted and Excluded. A hub's own page leaves the Reporting group out.
- **The wait rule:** under the Its Rhythm heading, "Wait rule: 40-Day Log-Normal Percentile, 2.6h", with Use the 14-Day Trimmed Maximum at its own width beneath it, and a line under both before the charts. The charts' titles read at 16px, the size of Its Rhythm, with room between the two charts.
- **The status line:** a reporting device reads "Last report 28s ago. Called frozen after 62m of silence." An unavailable or unknown device reads "Unavailable since 7:49 AM, 43m ago." (or "Unknown since"), with the date in front of the time when it went on an earlier day. The time is when the device itself went, so a device frozen first and unavailable later is dated from when it became unavailable. A hub's own page reads its own down moment the same way, even when its trouble began as a freeze (since 0.28.0). Without that moment, such a device keeps its freeze line rather than show the freeze's time. A time that cannot be read leaves the freeze line in place.
- **The status bar:** it fills toward the freeze window. Green while the device is within its rhythm, yellow once it is past its rhythm and not yet called frozen, red when frozen. Unavailable is gray, its dot too, and its bar stops where it stood when the device became unavailable. A muted device's bar is gray.
- **Plain words:** Battery reports in reads "small steps", "steps of 5% or more" or "not known yet". The Gaps table's LEARNED column reads "Yes", "No, re-paired" and the like. The signal legend calls a railed day "readings stuck at the end of the scale that day". The battery evidence line, in Advanced, reads "Saved for future battery forecasts: 2.9 V and 311 messages on Oct 30."
- **Each row:** each value shows when it changed, and each sensor is a link that opens the entity in Home Assistant.
- **No readable Last seen sensor:** the device shows when Device Sentinel last heard it, which repeats the status line by choice.
- **Below:** everything from the gaps table, "Gaps, Last 14 Days", down is unchanged by this order.

*Proof:* [`tools/panel_checks/check_device_page_layout.js`](../tools/panel_checks/check_device_page_layout.js), `check_names_and_mutes.js`, `check_real_device.js`, `check_hub_pages.js`, `check_rhythm_words.js`, `check_status_bar.js`, [`test_device_page_words.py`](../tests/test_device_page_words.py), [`test_dashboard_devices.py`](../tests/test_dashboard_devices.py).

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
- **Refused buttons:** since 0.28.7 a refused button's reason shows beside it on every tab, "Turn it on" and Exclude among them. Before, the reason was lost once the click had been handled, and the button stayed greyed.
- **A day removed by hand:** pressing a bar on a freeze chart asks first, "Remove (day) from this device's rhythm?", with the warning, "Remove this day" and "Keep it"; pressing a removed bar asks "Count (day) again?", with "Count it again" and "Cancel". Both change the device's wait at once ([FRZ-25](Rulebook__05_FRZ_Freeze.md#frz-25-a-day-removed-by-hand)).
- **No area:** choosing "No area" for a device that has one asks first, "Remove (device) from (area) in Home Assistant?", with "Remove from area" and "Keep its area", because taking a device out of its area changes Home Assistant's own dashboards, voice and area automations at once. Choosing another area does not ask.

*Proof:* [`tools/panel_checks/check_device_actions.js`](../tools/panel_checks/check_device_actions.js), [`tools/panel_checks/check_removed_days.js`](../tools/panel_checks/check_removed_days.js).

### DASH-11 A Change Shows on the Other Tabs

**After a change on a device page, the other tabs (Devices, Problem List and the rest) show it without pressing Refresh.**

*Proof:* [`tools/panel_checks/check_device_actions.js`](../tools/panel_checks/check_device_actions.js).

### DASH-12 Finding a Device

**The Devices tab shows every device Device Sentinel found, and opens on the ones it watches.**
- **Its chips (since 0.28.8):** Watched, the default, With a problem, Muted, Excluded and Set aside, each with its count. Excluded shows in Simple and Advanced; Set aside in Advanced only. Before 0.28.8, a link, "Show the N excluded devices", opened the excluded devices, and the devices set aside were on a Classification tab of their own.
- **Its finders:** a name search, an Area filter with "Not Set", a Label filter in Advanced, and the Type filter ([DEV-12](Rulebook__04_DEV_Device_Identity.md)). Each narrows whichever chip is chosen, and each chip keeps its own Area, Label and Type choices, so going back to a chip finds them as they were. A network's filter ([DASH-17](#dash-17-the-networks-tab)) narrows only the watched devices' chips, since only a watched device is on a network.
- **An area in a row:** on each chip, a set area is a link. Pressing it narrows the list to that area, the same as choosing it in the Area filter. AREA shows in Advanced only.
- **STANDING:** "Watched" or "Muted: " and what mutes it. A hub reads "a hub" and a device judged by its hub "judged by its hub" ([STACK-10](Rulebook__08_STACK_Stacks.md)), and a device whose name other watched devices share reads how many carry it, such as "Watched, 2 copies", the COPIES of classification.md ([DEV-01](Rulebook__04_DEV_Device_Identity.md)). After a mute's own list, these start a sentence of their own. A device set aside reads "Set aside: " and its reason, in the words of classification.md, with the meaning of each reason under the table. RHYTHM and BATTERY are no longer columns; they are read on the device page and on Battery Trends.
- **Excluded:** it lists the devices on the exclusion lists, read live from Home Assistant's registry and the settings, with nothing stored. A device excluded on its own reads whether its history is kept until midnight or already deleted; one excluded with its integration reads "Excluded with its integration". Its TYPE is the type Device Sentinel knows for it, or "Not Watched". Its AREA reads "Not Set" when none is set ([DASH-04](#dash-04-what-simple-shows)). LAST REPORT and WINDOW, blank on the Excluded and Set aside chips, do not sort there.
- **Ways back:** a device excluded on its own has "Cancel the exclusion", which the brief records as "from the Devices tab". One excluded with its integration links to that integration's page.
- **A name not watched (since 0.28.8):** wherever a device is named, on the Devices tab's chips, an integration's page, MQTT's Also on the Broker, a network page's hardware and the Daily Brief's tables, a device Device Sentinel watches or keeps a record for opens its page here; any other device still in Home Assistant opens Home Assistant's own device page; one removed from Home Assistant is its name in plain words. Previous and Next step only through the ones with a page here.
- **The summary:** "Watching N of M devices", how many have a problem and are muted, then how many are excluded and set aside, so M counts every device found. Simple, with no Set aside chip, leaves the devices set aside out of M and the sentence.

*Proof:* [`tools/panel_checks/check_device_finders.js`](../tools/panel_checks/check_device_finders.js), `check_not_set.js`, `check_classification_sources.js`, `check_hub_pages.js`, `check_type_filters.js`, `check_tab_addresses.js`, `check_integrations_tab.js`, `check_device_links.js`.

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
- **Devices tab:** it names each integration as Home Assistant shows it, not by its id, and a set-aside reason names the integration the same way.
- **Integrations tab summary:** it opens with the All chip's total. Its chips are All, Recommended, Trouble, Excluded and Muted.
- **Integrations tab columns in Simple:** three. INTEGRATION has the name, its device count in brackets and its id, and under them what Device Sentinel recommends and, for one with nothing to watch, what it is. EXCLUDE AND MUTE has the five buttons ([MUTE-03](Rulebook__03_MUTE_Muting_and_Exclusion.md#mute-03-excluding-one-device-or-one-integration)). TROUBLE has what is wrong on its devices at present, worst first, after "Down since" when the integration is down.
- **Integrations tab in Advanced:** it adds SET ASIDE and OUTAGES, 14 DAYS before TROUBLE, which stays last.
- **The five buttons:** each keeps one width on one line.
- **An integration's page:** it counts its devices muted from everything.
- **Devices tab in Advanced:** it shows DEVICE, TYPE, AREA, INTEGRATION, STANDING, PROBLEM, LAST REPORT and WINDOW. Before 0.28.8 it also had BATTERY and RHYTHM.
- **Still learning:** on the Devices tab, a device whose wait is still being learned reads "learning" under WINDOW, never a blank.
- **Never judged for freezing:** such a device reads "Judged by its hub, <name>", the name opening the hub's page, or "Judged by its connection", in place of a window. This shows on the Devices tab and on the device page.

*Proof:* [`test_classification_sources.py`](../tests/test_classification_sources.py), [`test_integration_names.py`](../tests/test_integration_names.py), [`test_dashboard_integrations.py`](../tests/test_dashboard_integrations.py), [`test_wifi_outage.py`](../tests/test_wifi_outage.py), [`tools/panel_checks/check_integration_names.js`](../tools/panel_checks/check_integration_names.js), `check_no_hardware_integrations.js`, `check_mutes_shown.js`, `check_rhythm_words.js`, `check_judged_by_line.js`, [`test_judged_by.py`](../tests/test_judged_by.py), `check_integrations_tab.js`, [`test_integrations_tab.py`](../tests/test_integrations_tab.py), `check_no_stray_words.js`, [`test_dashboard_devices.py`](../tests/test_dashboard_devices.py).

### DASH-17 The Networks Tab

**Since 0.28.6, the Networks tab, after Integrations and shown in Simple and Advanced alike, lists each network the house has, how it is doing, its devices and those with a problem. Each network has a page. Nothing on it changes another integration's settings.**
- **Its networks:** Zigbee2MQTT, ZHA, Z-Wave and Matter where the house runs them and their integration is not excluded, Wi-Fi where Device Sentinel can see a Wi-Fi outage, the MQTT broker where an MQTT integration is set up, and each hub Device Sentinel watches, such as a Lutron Caseta Smart Bridge. A network appears only where the house has it.
- **A device's network:** its radio stack, else its hub where Device Sentinel watches the hub (a hub is on its own), else Wi-Fi where it is tied to a router. A device that reaches Home Assistant through the broker, such as Tasmota's, is counted under the broker as well. A Zigbee2MQTT device is counted under Zigbee2MQTT only, and the broker's outages show on Zigbee2MQTT's page.
- **The tab's columns:** NETWORK, STATUS, DEVICES, WITH A PROBLEM and, in Advanced, LAST OUTAGE. STATUS reads the bridge, the broker, the hub or Wi-Fi as the status band does; Zigbee2MQTT reads "Integration not loaded" while the MQTT integration is not loaded. While Z-Wave JS is loaded, Z-Wave reads its controller's own status where one is recorded, Ready in green and anything else as down ([STACK-15](Rulebook__08_STACK_Stacks.md#stack-15-a-z-wave-controllers-own-status)); otherwise it and Matter read whether their integration is loaded. WITH A PROBLEM counts devices, with each kind in brackets, and opens the Devices tab on that network's devices with a problem.
- **Open buttons:** since 0.28.7 a network's page opens its own page in Home Assistant where it has one (Open ZHA, Open Z-Wave JS, Open Matter) and the app that runs it where its panel is in the sidebar (Open Zigbee2MQTT, Open Z-Wave JS UI), found by the app's name in the panel; with no such panel there is no button. "Open in Home Assistant" still opens the integration. Zigbee2MQTT's Availability notice carries Open Zigbee2MQTT too. An app's panel opens at its own first page: Home Assistant does not pass a page inside the app through its address.
- **A network's page in Simple:** its state, its recommendations ([DASH-18](#dash-18-a-networks-outage-patterns-and-radio-noise)), a count of its devices per problem (Frozen, Unavailable, Battery and Signal railed, then Never reported and Short drop-outs when there are any), each opening the Devices tab on those devices, its devices (folded, with DEVICE, MODEL and PROBLEM), and its Status Sensors and Settings.
- **Status Sensors and Settings:** for each sensor the network's devices carry (Last Seen, Signal or Link quality, Battery, the Z-Wave status and, since 0.28.7, Home Assistant's firmware update check), how many have it on, and each device with it switched off with "Turn it on", one device at a time, the same action as its device page ([REC-05](Rulebook__15_REC_Recommendations.md#rec-05-switched-off-sensors)). The brief records it as "from the Networks tab". A setting of the network's own, such as Zigbee2MQTT's Availability, is told with where to change it, never changed ([STACK-13](Rulebook__08_STACK_Stacks.md#stack-13-what-device-sentinel-never-sends-to-a-stack)).
- **A network's page in Advanced** adds its coordinator, controller or hub as its integration reports it (for Zigbee2MQTT: the device, its type, firmware, Zigbee channel, how it is connected and the Zigbee2MQTT version, read from Zigbee2MQTT's bridge information), its outages in the last 30 days (14 for a hub, whose outages are kept 14 days), its signal health this week (devices with a bad-signal day, judged on their own days however young the device, short drop-outs and signal railed), the devices added in 30 days and, for Zigbee2MQTT, which says when pairing opens, its pairing windows, and for Wi-Fi the networks watched by name, the access points its devices are joined to and the addresses two devices hold at once ([UP-19](Rulebook__07_UP_Upstream_Outages.md#up-19-a-wi-fi-devices-address-and-an-address-two-devices-share)).
- **More in Advanced, since 0.28.7:** its devices with MAKER, IN THE MESH (a Zigbee device's part, Router or End device, as Zigbee2MQTT or ZHA says), POWER and FIRMWARE added; What It Is Made Of (the parts in the mesh, how its devices are powered and its five most common makers); when it has run since, from the end of its last outage (left out while it is down or an outage stands); Devices That Keep Failing This Week (the Daily Brief's repeat offenders on it and the most short drop-outs, ten of each at most); Firmware (the updates Home Assistant offers, the versions that changed in 30 days and models whose devices run different versions); for Wi-Fi, each device's address changes and access point moves in 30 days, a first reading not counted; and for Z-Wave, Radio Noise ([DASH-18](#dash-18-a-networks-outage-patterns-and-radio-noise)).
- **The Devices tab:** a network's counts open it filtered to that network and problem, with "Showing the devices on Zigbee2MQTT with a battery problem only." and Show all, which takes every filter a count set off again.
- **Printing:** a network's page prints under the network's name.
- **Nothing new is stored but the expected outages:** everything else is read from what Device Sentinel already keeps, Home Assistant's registries and states, and for radio noise its statistics. If the networks fail to load, the Networks tab says so and every other tab still draws.

*Proof:* [`test_networks_tab.py`](../tests/test_networks_tab.py), [`test_network_page_extras.py`](../tests/test_network_page_extras.py), [`tools/panel_checks/check_networks.js`](../tools/panel_checks/check_networks.js), `check_network_page_extras.js`, `check_simple_dashboard.js`, `check_device_page_layout.js`.

### DASH-18 A Network's Outage Patterns and Radio Noise

**Since 0.28.7, a network that goes down at the same time of day again and again is told in one sentence, shown twice: as a recommendation that asks whether it is expected, and over the outages it covers. A person can say yes.**
- **A pattern:** outages on three or more occasions within 30 days, each starting within 15 minutes of one time of day, that make up at least a third of the network's outages in those 30 days. An occasion is a day around that time, so outages at 11:58 PM and 12:03 AM on one night are one. A network that drops at random has no pattern, nor does one with more than 120 outages in 30 days. A time with too small a share is passed over and the next time tried. On days in a row it reads "Down 6 nights in a row at 3:40 AM, Oct 29 to Nov 3." ("days" for a time between 6 AM and 8 PM); otherwise "Down 3 times at about 3:40 AM in the last 30 days, most recently Nov 3."
- **The recommendation:** under Recommendations for This Network, first on the network's page and on the Recommendations tab under the network's name, in Simple and Advanced, counted in the tab's number. It asks "Is this expected?" and names the usual cause, a nightly backup or scheduled restart on the device that runs it (for Wi-Fi, the router or its access points). Its buttons: Yes, it is expected; Open the logbook, at the newest outage from 10 minutes before it began to 10 minutes after it ended, worded in the house's own time; and the network's app or page. A network card has no Acknowledged box: a pattern is answered by Yes, it is expected, a long run's card ends after its week, and a noise card ends when the noise does. Each counts in the tab's number until then. A pattern whose outages have no recorded length offers no Yes.
- **Its outages:** the outage list puts the sentence over the outages it covers.
- **Expected:** Yes remembers the network, the time of day and the pattern's usual length. An outage of that network within 15 minutes of that time, no longer than twice the usual length (or a minute more, for a short one), is expected, those before it was marked included; an outage of any other length never is, nor is any outage at a time with no usual length: listed and marked "(expected)", left out of the Networks tab's LAST OUTAGE (the newest outage not expected shows there; when every outage was expected, the newest shows marked "(expected)"), never a recommendation, and said as expected in the Daily Brief and its notification ("It was expected."). In Short tells the longest outage that was not expected first, and an expected one only when nothing else is worth telling. A hub's outages are marked on its page but not in the brief. The broker's outages listed on Zigbee2MQTT's page are the broker's: only the broker's expected times cover them, and they make no Zigbee2MQTT pattern.
- **Still told:** an outage at another time is an ordinary outage. One at the expected time that runs past the allowance, or has not ended within it, is told on its own for 7 days: "The outage you expect at 3:40 AM ran 60 minutes on Nov 10, against its usual 4 minutes."
- **Forgotten:** an expected outage that has not happened for 14 days is forgotten at the midnight fold, so a schedule removed since never hides a future outage at the same time.
- **Taken back:** each is listed under Expected Outages on the Integrations tab, with the mutes, and over its outages on the network's page, each with Stop expecting this. Only a pattern can be marked, by an administrator. Marked again, while still marked, it keeps the time it was first marked. An expected outage of a network the house no longer has can still be taken back.
- **Radio noise (Z-Wave):** for a controller with Z-Wave JS's noise sensors on, each channel's noise now, Z-Wave JS's own average, and its typical day: the middle of its daily means over the last 30 days, the newest 3 left out, from Home Assistant's long-term statistics, whole days only, once 14 days are recorded ("learning, 5 of 14 days" before). A channel whose last 3 daily means were each 10 dB or more above its typical is a recommendation naming likely sources of interference near the stick. No fixed level is judged: sticks differ, and Z-Wave JS turns a reading the radio could not make into unknown. Zigbee and Matter offer no such sensor.

*Proof:* [`test_network_outage_patterns.py`](../tests/test_network_outage_patterns.py), [`test_network_page_extras.py`](../tests/test_network_page_extras.py), [`tools/panel_checks/check_network_page_extras.js`](../tools/panel_checks/check_network_page_extras.js).
