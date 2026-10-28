# Device Sentinel Rulebook: Recommendations (REC)

*Version: rulebook, 27 October 2026, on Device Sentinel 0.27.10. Index and how the IDs work: [Main__Rulebook.md](Main__Rulebook.md).*

What Device Sentinel suggests a person change about their own setup: the Recommendations tab and its cards, the ticks and counts, and the lines the emailed Daily Brief carries for them. The rest of the brief is under [BRIEF](Rulebook__13_BRIEF_Daily_Brief.md); the dashboard around the tab, and Simple and Advanced in general, are under [DASH](Rulebook__14_DASH_Dashboard.md). What each card's answer does to a device (power, type, a battery replacement) is under [DEV](Rulebook__04_DEV_Device_Identity.md) and BAT.

### REC-01 The Recommendations Tab

**The tab opens with "N recommendations to help Device Sentinel run better. None of them is required." N counts the rows and written lines not ticked, the same count the tab name and the Active Recommendations button carry ([REC-08](#rec-08-counts)). No card is singled out as more needed than another; each one is a suggestion a person can ignore. The written recommendations come first, then the cards about single devices, then a closing paragraph saying these are suggestions drawn from what Device Sentinel has observed. With nothing to suggest the tab reads "Nothing to recommend right now." and nothing else; with N at zero and ticked rows left, that line opens the tab and the ticked cards and the closing paragraph still show beneath it.**

*Proof:* [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js), [`test_recommendations.py`](../tests/test_recommendations.py).

### REC-02 The Written Recommendations

**A written recommendation is about the house's setup rather than one device. Each line opens with its condition, a colon, then what it costs and where to change it, and stands until its condition is gone. All lines show, worst first: a notification target that no longer exists, no target set at all, a Links in Reports address Home Assistant no longer holds, a detection family muted or excluded for all the devices it judges, a wireless adapter with no network chosen and no router ties, Zigbee2MQTT availability switched off, a router integration watched again, a polling integration worth excluding, and the library's integrations ([REC-03](#rec-03-the-library)). Each line can be ticked Acknowledged ([REC-07](#rec-07-acknowledged)); nothing else dismisses it.**

*Proof:* [`test_recommendations.py`](../tests/test_recommendations.py), [`test_recommendation_acknowledgement.py`](../tests/test_recommendation_acknowledgement.py).

### REC-03 The Library

**Device Sentinel carries a short list, as data, of integrations whose devices come and go for reasons that are not faults. Presence trackers and televisions (ping, mobile_app, webostv, androidtv, samsungtv, apple_tv, dlna_dmr, samsung_infrared) give one line naming them as Home Assistant shows them and suggesting they be excluded. Integrations that own no devices (spook) give a second line with each one's device count. An integration already excluded or muted is left alone. Router trackers are not in the list; they have a line of their own.**

*Proof:* [`test_recommendations.py`](../tests/test_recommendations.py).

### REC-04 The Device Cards

**Each card lists the watched devices it covers, by name with the area, and each name opens the device's page. The cards, in order: Confirm Battery Replacement (or Confirm Battery Charge) for a detected new battery (BAT), Power Not Set, the switched-off cards of [REC-05](#rec-05-switched-off-sensors), No Area Assigned, Devices Sharing A Name (names compared without regard to capitals), Slow Reporting Devices ([REC-06](#rec-06-slow-reporting-devices)), and last Type Not Set and Model With More Than One Type. Power Not Set lists each watched device with no power type, mains included, and stays that way. Power and type are set right in the list; a switched-off sensor is turned on in the list; area and name are changed from the device's page. A device leaves a card once its condition is gone.**

*Proof:* [`test_recommendations.py`](../tests/test_recommendations.py), [`test_power_source.py`](../tests/test_power_source.py), [`test_device_type.py`](../tests/test_device_type.py), [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js), `check_device_page_layout.js`, `check_type_filters.js`.

### REC-05 Switched-Off Sensors

**A sensor is switched on one device at a time, by an administrator, from its card, or in Advanced from the device's page; a battery voltage sensor is switched on from its card only. Nothing switches on a whole kind at once. The cards are Last Seen Sensor Switched Off, Battery Sensor Switched Off, Z-Wave Status Switched Off, Signal Sensor Switched Off and Battery Voltage Switched Off, each with a chip per device that names the sensor: "Turn on its Last Seen", "Turn on its battery sensor", "Turn on its Z-Wave status", "Turn on its signal sensor" and "Turn on its battery voltage". Only a device's own entities count, never one another integration added, such as Battery Notes'; a device is listed only when none of its own entities of that kind is on. Battery Voltage Switched Off lists only a device with a battery reading, whose power is not set to mains, USB or PoE, and whose voltage nothing else already reports, and reads "These devices have battery voltage entities which can be used for more accurate battery reporting and forecasting." With one device listed it reads "This device has a battery voltage entity which can be used for more accurate battery reporting and forecasting."**

*Proof:* [`test_switched_off_sensors.py`](../tests/test_switched_off_sensors.py), [`test_battery_voltage_card.py`](../tests/test_battery_voltage_card.py), [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js).

### REC-06 Slow Reporting Devices

**The Slow Reporting Devices card lists each watched device whose wait in use is over 36 hours, offering a freeze mute with a "Mute freeze" chip and changing nothing by itself. A device already muted for freeze or for everything is left off, and so is one the freeze rules never judge frozen (see [FRZ](Rulebook__05_FRZ_Freeze.md)). The card reads: "These devices go quiet for long periods. They are often devices that sleep until a person triggers or interacts with them. Because these devices do not report on a rhythm, Device Sentinel has trouble accurately reporting a frozen verdict. Often a freeze verdict for this device is noise and the best practice is to mute it. Device Sentinel will still report when it becomes unavailable or its battery runs low."**

*Proof:* [`test_recommendations.py`](../tests/test_recommendations.py), [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js).

### REC-07 Acknowledged

**Each row of a device card, and each written recommendation, has an Acknowledged checkbox that can be unticked again. A ticked row stays listed, faded, and leaves the counts and the Daily Brief. The tick is kept in the answers file. At the midnight run, a tick whose device has left the card, or whose line has gone, is forgotten, so a problem that comes back on a later day is active again; one that leaves and comes back the same day, or across a restart, comes back ticked. A sensor a person switched off themselves starts ticked. A Confirm Battery Replacement row is answered, not ticked.**

*Proof:* [`test_recommendation_acknowledgement.py`](../tests/test_recommendation_acknowledgement.py), [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js).

### REC-08 Counts

**N counts the rows and lines not ticked, in the cards and lines the dashboard's mode shows. The tab reads "Recommendations (N)", a highlighted "Active Recommendations (N)" button in the top band opens it and is hidden at zero, and the Daily Brief tab carries "N active recommendations on the Recommendations tab." at its top. Each card's title carries "(N)" for its rows not ticked, with no number at zero and none on a written recommendation.**

*Proof:* [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js), [`test_recommendation_acknowledgement.py`](../tests/test_recommendation_acknowledgement.py).

### REC-09 What Simple Shows

**Simple shows what Device Sentinel needs to work at its best, and nothing extra: Notifications Recipient Not Valid and Not Set, Last Seen, Battery, Z-Wave Status, Signal Sensor and Battery Voltage Switched Off, Slow Reporting Devices, Devices Sharing A Name, a family muted for all its devices ("All devices are muted..."), and Confirm Battery Replacement. Simple's device page offers no sensor to turn on, so each such sensor has its card here. All other cards and lines are Advanced only.**

*Proof:* [`test_recommendation_acknowledgement.py`](../tests/test_recommendation_acknowledgement.py), [`test_battery_voltage_card.py`](../tests/test_battery_voltage_card.py), [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js), [`tools/panel_checks/check_simple_dashboard.js`](../tools/panel_checks/check_simple_dashboard.js).

### REC-10 In the Emailed Daily Brief

**The emailed Daily Brief, and its file in `/config/device_sentinel/`, carries a Recommendations section above Last 24 Hours: each written recommendation not ticked, then one line per device card with its title, its count of rows not ticked in brackets, and a link opening that card on the tab where Links in Reports allows one. It counts as Advanced does. Slow Reporting Devices, Type Not Set and Model With More Than One Type stay out, because a slow device or a missing or mixed type is not a fault; a card whose rows are all ticked stays out too. The dashboard's Daily Brief tab carries the count of [REC-08](#rec-08-counts) and, under it, the Confirm Battery Replacement card's line while that card has a row not answered ("Battery replaced on X, detected Oct 18. Confirm it on the Recommendations tab."); it carries no other recommendation lines.**

*Proof:* [`test_recommendations.py`](../tests/test_recommendations.py), [`test_recommendation_acknowledgement.py`](../tests/test_recommendation_acknowledgement.py), [`test_battery_voltage_card.py`](../tests/test_battery_voltage_card.py).

### REC-11 Cards Stay Open

**A card the person opened stays open after a tick or an action, and the page keeps its place; a card the person closed stays closed. This is remembered while the dashboard is open, and nothing is kept in the browser. A brief's link opens its card and scrolls to it once.**

*Proof:* [`tools/panel_checks/check_recommendations.js`](../tools/panel_checks/check_recommendations.js).
