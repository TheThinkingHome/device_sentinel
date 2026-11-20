# Untrusted Devices

Some integrations report live for most of their devices, but have a few makes and models that sleep. After Home Assistant restarts, those devices are shown with their cached values before the device itself has woken up and spoken. This file lists the makes and models Device Sentinel treats as reporting cached values in such integrations, why, how sure we are, and every make and model we checked and left off.

A device on this list stays on the Problem List after a restart until one of its values changes, which proves the device itself answered. You can change that on the device's page, in the After a restart row: "Reports live" if your device of that model answers for itself, or "Device Sentinel's Setting" to go back to this list.

Integrations whose devices all report cached values are listed in [Integrations That Report Cached Values](TRUSTED_INTEGRATIONS.md). A device with a Last Seen sensor is not affected by either list.

How to read the tables:

- **Manufacturer, Model and Model ID:** exactly as Home Assistant shows them on the device's page. "none" means the integration gives no model ID.
- **Why:** what the device and its integration do after a restart.
- **How sure:** "Strong" means the integration's code or its library names the model as one that sleeps. "Fair" means the evidence points that way, but no line of code names it.
- **Evidence:** "Code" means we read the integration's code. "Code and library" means we also read the library it uses.
- **Seen in a data file:** whether we have seen the model behave this way in a real house's diagnostics.
- **Checked:** the date we checked it.

## Makes and Models That Report Cached Values

| Manufacturer | Model | Model ID | Integration | Why | How sure | Evidence | Seen in a data file | Checked |
|---|---|---|---|---|---|---|---|---|
| Shelly | Shelly H&T | SHHT-1 | Shelly (`shelly`) | Sleeps between readings. Home Assistant shows its restored values, available, until it misses more than two of its wake-ups. | Strong | Code | No | 15 Nov 2026 |
| Shelly | Shelly Door/Window | SHDW-1 | Shelly (`shelly`) | Sleeps until the door or window moves. Home Assistant shows its restored values, available, until it misses more than two of its wake-ups. | Strong | Code | No | 15 Nov 2026 |
| Shelly | Shelly Door/Window 2 | SHDW-2 | Shelly (`shelly`) | Sleeps until the door or window moves. Home Assistant shows its restored values, available, until it misses more than two of its wake-ups. | Strong | Code | No | 15 Nov 2026 |
| Shelly | Shelly Flood | SHWT-1 | Shelly (`shelly`) | Sleeps until it detects water or wakes on its timer. Home Assistant shows its restored values, available, until it misses more than two of its wake-ups. | Strong | Code | No | 15 Nov 2026 |
| Shelly | Shelly Smoke | SHSM-01 | Shelly (`shelly`) | Battery-only and not among the Shelly battery devices that stay connected, so it sleeps like the H&T and is shown the same way. | Fair | Code | No | 15 Nov 2026 |
| Shelly | Shelly Smoke 2 | SHSM-02 | Shelly (`shelly`) | Battery-only and not among the Shelly battery devices that stay connected, so it sleeps like the H&T and is shown the same way. | Fair | Code | No | 15 Nov 2026 |
| Govee | H5121 | none | Govee Bluetooth (`govee_ble`) | A motion sensor the Govee library marks as sleepy. Home Assistant keeps a sleepy model shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Govee | H5122 | none | Govee Bluetooth (`govee_ble`) | A one-button remote the Govee library marks as sleepy. Home Assistant keeps a sleepy model shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Govee | H5123 | none | Govee Bluetooth (`govee_ble`) | A window sensor the Govee library marks as sleepy. Home Assistant keeps a sleepy model shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Govee | H5124 | none | Govee Bluetooth (`govee_ble`) | A vibration sensor the Govee library marks as sleepy. Home Assistant keeps a sleepy model shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Govee | H5125 | none | Govee Bluetooth (`govee_ble`) | A six-button remote the Govee library marks as sleepy. Home Assistant keeps a sleepy model shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Govee | H5126 | none | Govee Bluetooth (`govee_ble`) | A two-button remote the Govee library marks as sleepy. Home Assistant keeps a sleepy model shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Govee | H5127 | none | Govee Bluetooth (`govee_ble`) | A presence sensor the Govee library marks as sleepy. Home Assistant keeps a sleepy model shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Govee | H5130 | none | Govee Bluetooth (`govee_ble`) | A pressure sensor the Govee library marks as sleepy. Home Assistant keeps a sleepy model shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | CGH1 | none | Xiaomi BLE (`xiaomi_ble`) | A door and window sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Linptech | ES3 | none | Xiaomi BLE (`xiaomi_ble`) | A presence sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | MC-COMM | none | Xiaomi BLE (`xiaomi_ble`) | A door and window sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Linptech | ES5BB | none | Xiaomi BLE (`xiaomi_ble`) | A presence sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Linptech | PS1BB | none | Xiaomi BLE (`xiaomi_ble`) | A seat pressure sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | JTYJGD03MI | none | Xiaomi BLE (`xiaomi_ble`) | A smoke detector the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | MCCGQ02HL | none | Xiaomi BLE (`xiaomi_ble`) | A door and window sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | MS1BB(MI) | none | Xiaomi BLE (`xiaomi_ble`) | A door and window sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | RTCGQ02LM | none | Xiaomi BLE (`xiaomi_ble`) | A motion sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | MMC-W505 | none | Xiaomi BLE (`xiaomi_ble`) | A body thermometer the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | RS1BB(MI) | none | Xiaomi BLE (`xiaomi_ble`) | A flood and rain sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | SJWS02LM | none | Xiaomi BLE (`xiaomi_ble`) | A water leak sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | XMOSB01XS | none | Xiaomi BLE (`xiaomi_ble`) | A occupancy sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | MJTZC01YM | none | Xiaomi BLE (`xiaomi_ble`) | A body composition scale the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | MJTZC02YM | none | Xiaomi BLE (`xiaomi_ble`) | A smart scale the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | MJTZC03YM | none | Xiaomi BLE (`xiaomi_ble`) | A body composition scale the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | HS1BB(MI) | none | Xiaomi BLE (`xiaomi_ble`) | A motion sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | XMPIRO2SXS | none | Xiaomi BLE (`xiaomi_ble`) | A motion sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | XMPIRO2GSXS | none | Xiaomi BLE (`xiaomi_ble`) | A motion sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | M2456B1 | none | Xiaomi BLE (`xiaomi_ble`) | A fitness band the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | M2457B1 | none | Xiaomi BLE (`xiaomi_ble`) | A fitness band the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |
| Xiaomi | zhiee.flood.sj01 | none | Xiaomi BLE (`xiaomi_ble`) | A water leak sensor the Xiaomi library marks as sleepy. Home Assistant keeps a sleepy device shown available with its restored values. | Strong | Code and library | No | 15 Nov 2026 |

## Checked and Left Off

These were checked and are not on the list. Device Sentinel treats them as their integration does, which for each of these is reporting live.

| Devices | Integration | Why not | Checked |
|---|---|---|---|
| Shelly Button1 (SHBTN-1, SHBTN-2) | Shelly (`shelly`) | It can run from USB power, and then it may stay awake and report live. | 15 Nov 2026 |
| Shelly Motion, Shelly Motion 2 (SHMOS-01, SHMOS-02) | Shelly (`shelly`) | Home Assistant lists them as battery devices that keep a permanent connection. They report live. | 15 Nov 2026 |
| Shelly Valve (SHTRV-01) | Shelly (`shelly`) | Home Assistant lists it as a battery device that keeps a permanent connection. It reports live. | 15 Nov 2026 |
| Shelly second-generation and newer sleeping devices, such as the Plus H&T | Shelly (`shelly`) | Each has a Last Seen sensor, switched on as it ships, so Device Sentinel judges it by last seen. | 15 Nov 2026 |
| Shelly BLU and other BTHome devices | BTHome (`bthome`) | Whether a device sleeps is a flag it sets in its own broadcasts, not something its make and model tell. Home Assistant shows a device that sets it with its restored values. | 15 Nov 2026 |
| ESPHome devices using deep sleep | ESPHome (`esphome`) | Deep sleep is set in each device's own configuration, and the model Home Assistant shows is the chip's board, which names no product. | 15 Nov 2026 |
| Tasmota devices using deep sleep | Tasmota (`tasmota`) | Deep sleep is a setting on the device, and most Tasmota devices report the model as Generic. | 15 Nov 2026 |
| HomeKit accessories paired over Bluetooth | HomeKit Device (`homekit_controller`) | The same product, such as an Eve sensor, can also connect over Thread or Wi-Fi and then reports live. The model name doesn't say which. | 15 Nov 2026 |
| Tapo sensors behind a hub, such as the T310, T315, T100 and T110 | TP-Link Smart Home (`tplink`) | Their values come from the hub at each poll. We could not show whether the hub keeps a dead sensor's last values. | 15 Nov 2026 |
| Devices behind a Bond Bridge | Bond (`bond`) | One-way radio and infrared devices; the bridge reports what it last sent. Not checked down to the model. | 15 Nov 2026 |
| Freebox Home sensors | Freebox (`freebox`) | The router keeps each sensor's last values. Not checked down to the model. | 15 Nov 2026 |
| Zigbee radiator thermostats and room sensors behind a ViCare gateway | Viessmann ViCare (`vicare`) | What the cloud returns for an offline device could not be shown. | 15 Nov 2026 |
| Rachio controllers | Rachio (`rachio`) | Its values are mostly settings, and an Online sensor shows when it is offline. Not checked down to the model. | 15 Nov 2026 |
| Tesla vehicles | Tesla Fleet (`tesla_fleet`) | A sleeping car's values are restored, but a sleeping car is not a dead device. Held for a later decision. | 15 Nov 2026 |
| Devices from Scrypted plugins without an online check | Scrypted (`scrypted`) | Depends on the plugin, not the model. | 15 Nov 2026 |

## If a Device Is Wrong or Missing

This list is a starting point, and none of it has yet been seen on a real house. If Device Sentinel treats one of your devices the wrong way after a restart, set it on the device's page, then open an issue at https://github.com/TheThinkingHome/device_sentinel/issues and attach your diagnostics download. A make and model that is not in the table has not been checked yet, and Device Sentinel treats it as its integration does.
