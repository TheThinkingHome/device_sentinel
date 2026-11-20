# Integrations That Report Cached Values

After Home Assistant restarts, some integrations show a device's cached values before the device has spoken. Device Sentinel can't take those values as proof the device is working. This file lists every integration we have checked, whether Device Sentinel treats it as reporting cached values, and why.

An integration marked "Reports cached values" is ticked by default under Integrations That Report Cached Values in settings. You can tick or untick any integration there, and set a single make and model on its device page.

In an integration marked "Some models only", the makes and models known to report cached values are listed in [Untrusted Devices](UNTRUSTED_DEVICES.md). Device Sentinel treats each of those as reporting cached values unless you set it otherwise on its device page.

A device with a Last Seen sensor is not affected by this list. Device Sentinel judges it by when it was last seen. That covers Zigbee2MQTT, ZHA and Z-Wave JS devices.

How to read the table:

- **Verdict:** Reports live, Reports cached values, or Some models only. "Judged by last seen" is never on the list. "Not settled" is treated as reporting live.
- **Why:** what the integration does after a restart.
- **Evidence:** "Code" means we read the integration's code. "Seen running" means we also saw it happen on a real house, with the date.
- **Checked:** the date we checked it.

| Integration | Verdict | Why | Evidence | Checked |
|---|---|---|---|---|
| Acaia (`acaia`) | Reports cached values | Coffee scales. A sensor with a restored value stays available after a restart, whether or not the scale is on. | Code | 15 Nov 2026 |
| Alarm.com (`alarmdotcom`) | Reports cached values | A sensor stays available while the Alarm.com cloud answers, with its last state. | Seen running, Nov 2026 | 14 Nov 2026 |
| Alexa Devices (`alexa_devices`) | Reports live | Its cloud says when a device is offline, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| Android Debug Bridge (`androidtv`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Android TV Remote (`androidtv_remote`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| August (`august`) | Reports cached values | The lock follows its bridge, but the battery and operator sensors show their last values and stay available. | Code and library | 14 Nov 2026 |
| Belkin WeMo (`wemo`) | Reports live | A device that isn't found gets no entities, so it shows as unavailable. | Code | 14 Nov 2026 |
| Blink (`blink`) | Reports cached values | A camera that is offline stays available with the cloud's last temperature, battery and Wi-Fi values. | Code and library | 14 Nov 2026 |
| BlueSight (`bluesight`) | Reports live | A Bluetooth proxy that is missing after a restart shows as offline. It has a Last Seen sensor. | Code | 14 Nov 2026 |
| Bluetooth (`bluetooth`) | Reports live | It has no devices of its own. It carries the Bluetooth devices of other integrations. | Code | 14 Nov 2026 |
| Bond (`bond`) | Some models only | Devices with Bond built in show as unavailable. Fans, shades and lights behind a Bond Bridge show what the Bridge last sent them. | Code | 14 Nov 2026 |
| Broadlink (`broadlink`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Brother Printer (`brother`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| BTHome (`bthome`) | Some models only | Most devices show as unavailable. Devices that mark themselves as sleepy, such as battery buttons and contact sensors, show their restored values. | Code | 14 Nov 2026 |
| Daikin AC (`daikin`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Danfoss Link (`danfoss_link`) | Reports cached values | Each room is a device behind the Link CC. A room whose thermostat has lost radio contact stays available with the CC's last values, and its radio contact sensor turns off. | Code | 15 Nov 2026 |
| Denon AVR (`denonavr`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Denon HEOS (`heos`) | Reports live | Its hub says when a device can't be reached, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| DLNA Digital Media Renderer (`dlna_dmr`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Drayton Wiser (`wiser`) | Reports cached values | Devices behind the HeatHub stay available with the hub's last values while the hub answers. A device the hub can't hear shows only "NoSignal" on its signal sensor. | Code | 15 Nov 2026 |
| Easee (`easee`) | Reports cached values | Every entity is always available. A charger that is offline shows the Easee cloud's last values, and its Online sensor turns off. | Code | 15 Nov 2026 |
| ecobee (`ecobee`) | Not settled | Thermostats show as unavailable when offline. The code doesn't show what the cloud sends for a remote sensor that is gone. Treated as reporting live. | Code | 14 Nov 2026 |
| Ecovacs (`ecovacs`) | Reports live | A robot shows no values until it reports. | Code | 14 Nov 2026 |
| Ecowitt (`ecowitt`) | Reports live | A reading shows as unavailable until the gateway sends it, and again 5 minutes after it stops. | Code | 14 Nov 2026 |
| Energi Data Service (`energidataservice`) | Reports live | A price service, not a device. Its sensors show no value after a restart until prices are fetched. | Code | 15 Nov 2026 |
| EnOcean (`enocean`) | Reports cached values | Sensors restore their last values after a restart, and no entity ever goes unavailable. | Code | 15 Nov 2026 |
| Enphase Envoy (`enphase_envoy`) | Some models only | An Envoy that can't be reached shows as unavailable. Inverters and batteries show the Envoy's last values for them; each has a Last Reported sensor. | Code | 14 Nov 2026 |
| ESPHome (`esphome`) | Some models only | Most devices are unavailable until they connect. Devices built with deep sleep show their stored values as current. | Code | 14 Nov 2026 |
| EufyLife (`eufylife_ble`) | Reports cached values | Bluetooth scales. The weight sensor is always shown available, with its restored value, because the scale sleeps between weighings. | Code | 15 Nov 2026 |
| EZVIZ (`ezviz`) | Reports live | Its cloud says when a device is offline, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| FlightRadar24 (`flightradar24`) | Reports cached values | A web service, not a device. Its sensors are always available, and its tracked flight sensors restore their last values after a restart. | Code | 15 Nov 2026 |
| Freebox (`freebox`) | Some models only | The router itself reports live. Freebox Home sensors, covers and cameras show the router's last values for them. | Code | 14 Nov 2026 |
| Frigate (`frigate`) | Reports live | A camera that stops sending video shows as unavailable. | Code | 14 Nov 2026 |
| FRITZ!Box Tools (`fritz`) | Reports live | A router that can't be reached shows as unavailable, and each client shows whether it is connected now. | Code | 14 Nov 2026 |
| FRITZ!SmartHome (`fritzbox`) | Reports live | Its hub says when a device can't be reached, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| Fronius (`fronius`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Fully Kiosk Browser (`fully_kiosk`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| GE Home (SmartHQ) (`ge_home`) | Not settled | The code doesn't show whether the cloud sends values for an appliance that is offline. Treated as reporting live. | Code | 14 Nov 2026 |
| Gecko (`gecko`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Google Cast (`cast`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Google Nest (`nest`) | Reports live | Its cloud says when a device is offline, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| Govee Bluetooth (`govee_ble`) | Some models only | Most models show as unavailable. Models that sleep, such as window and motion sensors, show their restored values. | Code | 14 Nov 2026 |
| Govee Lights Local (`govee_light_local`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Gree Climate (`gree`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Home Connect (`home_connect`) | Reports live | Its cloud says when a device is offline, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| HomeKit Device (`homekit_controller`) | Some models only | Wi-Fi and Thread accessories show as unavailable. Bluetooth accessories show their stored values until they are next read. | Code | 14 Nov 2026 |
| HomematicIP Cloud (`homematicip_cloud`) | Reports live | Its cloud says when a device is offline, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| HomeWizard Energy (`homewizard`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| HP Printer (`hp_printer`) | Reports live | A printer that doesn't answer, such as one switched off, shows as unavailable. | Code | 15 Nov 2026 |
| Hypervolt Charger (`hypervolt_charger`) | Not settled | The code doesn't show what the cloud sends for a charger that is offline. Treated as reporting live. | Code | 14 Nov 2026 |
| IKEA TRÅDFRI (`tradfri`) | Reports live | Its hub says when a device can't be reached, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| Internet Printing Protocol (IPP) (`ipp`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| InvisOutlet (`invisoutlet`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| iRobot Roomba (`roomba`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| KNX (`knx`) | Reports cached values | Sensors, switches and covers restore their last state, and a device is unavailable only when the whole KNX connection is down. | Code | 14 Nov 2026 |
| Kodi (`kodi`) | Reports live | A TV that can't be reached shows as off, never its last values. | Code | 14 Nov 2026 |
| LeaOne (`leaone`) | Reports cached values | Bluetooth scales. Every sensor is always shown available, because the scale sleeps between weighings. | Code | 15 Nov 2026 |
| LG ThinQ (`lg_thinq`) | Reports live | Its cloud says when a device is offline, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| LG webOS TV (`webostv`) | Reports live | A TV that can't be reached shows as off, never its last values. | Code | 14 Nov 2026 |
| LIFX (`lifx`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Lightwave Smart (`lightwave_smart`) | Reports cached values | No device is ever marked unavailable. Each shows the values the Lightwave link gives at a restart. | Code | 14 Nov 2026 |
| LinkPlay (`linkplay`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Logitech Harmony Hub (`harmony`) | Reports live | Its hub says when a device can't be reached, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| Lutron Caséta (`lutron_caseta`) | Reports cached values | No device is ever marked unavailable. Each shows the level or state the bridge last had for it. | Code | 14 Nov 2026 |
| Magic Home (`flux_led`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Matter (`matter`) | Reports live | Its hub says when a device can't be reached, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| Miele (`miele`) | Reports live | Its cloud says when a device is offline, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| Mobile App (`mobile_app`) | Reports cached values | A phone's sensors are restored at a restart. The phone is not contacted. | Code | 14 Nov 2026 |
| Modbus (`modbus`) | Reports cached values | Sensors restore their last values at a restart. A device that doesn't answer its first read turns unavailable, but a connection that is down leaves the restored values showing. | Code | 14 Nov 2026 |
| Mopeka (`mopeka`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Motionblinds (`motion_blinds`) | Not settled | The code doesn't show whether the gateway answers for a blind that is gone. Treated as reporting live. | Code | 14 Nov 2026 |
| MQTT (`mqtt`) | Not settled | It depends on what each device publishes. Zigbee2MQTT devices are judged by their Last Seen sensor. Other MQTT devices are treated as reporting live. | Seen running, Nov 2026 | 14 Nov 2026 |
| MusicCast (`yamaha_musiccast`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Nanoleaf (`nanoleaf`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Navimow (`navimow`) | Reports cached values | The mower stays available with the last state the Navimow cloud sent. | Code | 15 Nov 2026 |
| NaviMower (`navimower`) | Reports cached values | The mower stays available with the Navimow cloud's last values while the cloud answers. Its Online sensor shows whether it is connected. | Code | 15 Nov 2026 |
| Netatmo (`netatmo`) | Reports live | Its cloud says when a module can't be reached, and the module then shows as unavailable. | Code | 15 Nov 2026 |
| Network UPS Tools (NUT) (`nut`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Nmap Tracker (`nmap_tracker`) | Reports live | A device not found by the first scan shows as away. | Code | 14 Nov 2026 |
| Node-RED (`nodered`) | Reports cached values | Values come from Node-RED flows. After a restart, Node-RED sends each sensor's last state again, which its sensor nodes do by default. | Code | 15 Nov 2026 |
| OctoPrint (`octoprint`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Octopus Energy (`octopus_energy`) | Reports cached values | Its sensors restore their last values at a restart and keep them when the cloud can't be read. | Code | 14 Nov 2026 |
| OKOK Scale (`okok_scale`) | Reports cached values | Bluetooth scales. Every sensor is always shown available, because the scale sleeps between weighings. | Code | 15 Nov 2026 |
| ONVIF (`onvif`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Oral-B (`oralb`) | Reports cached values | A toothbrush is always shown as available, with its restored values, because it sleeps. | Code | 14 Nov 2026 |
| Overkiz (`overkiz`) | Reports live | Its hub says when a device can't be reached, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| Philips Hue (`hue`) | Reports live | Its hub says when a device can't be reached, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| Philips TV (`philips_js`) | Reports live | A TV that can't be reached shows as off, never its last values. | Code | 14 Nov 2026 |
| Ping (`ping`) | Reports live | Each check pings the device, so one that can't be reached shows as disconnected. | Code | 14 Nov 2026 |
| Rachio (`rachio`) | Some models only | Hose timers show as unavailable when offline. A controller's zones and schedules stay available with the cloud's last state. | Code | 14 Nov 2026 |
| Reolink (`reolink`) | Reports live | A camera that can't be reached shows as unavailable, on its own or behind a recorder or hub. | Code | 14 Nov 2026 |
| RFXCOM RFXtrx (`rfxtrx`) | Reports cached values | One-way radio devices. Every entity restores its last state after a restart and never goes unavailable. | Code | 15 Nov 2026 |
| Ring (`ring`) | Reports cached values | A doorbell or camera that is offline stays available with the cloud's last battery and Wi-Fi values. | Code and library | 14 Nov 2026 |
| Roborock (`roborock`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Roku (`roku`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Samsung Smart TV (`samsungtv`) | Reports live | A TV that can't be reached shows as off, never its last values. | Code | 14 Nov 2026 |
| Scrypted (`scrypted`) | Some models only | Devices that report whether they are online show as unavailable when offline. The others show the last values Scrypted has. | Code | 14 Nov 2026 |
| Sensibo (`sensibo`) | Reports live | Its cloud says when a device is offline, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| Shelly (`shelly`) | Some models only | Mains devices that can't be reached show as unavailable. First-generation battery devices that sleep (H&T, Flood, Door/Window, Smoke) show their restored values. Motion, Motion 2 and the Valve stay connected and report live, and newer sleeping devices have a Last Seen sensor. | Code | 15 Nov 2026 |
| SmartThings (`smartthings`) | Reports live | Its cloud says when a device is offline, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| SMLIGHT SLZB (`smlight`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| SNMP Printer (`snmp_printer`) | Reports cached values | A printer that can't be reached keeps its saved values, such as its ink and toner levels, and its status reads "offline". | Code | 15 Nov 2026 |
| SolarEdge (`solaredge`) | Not settled | The code doesn't show what the cloud sends once an inverter stops reporting. Treated as reporting live. | Code | 14 Nov 2026 |
| Sonos (`sonos`) | Reports live | A speaker that can't be reached gets no entities until it answers, so it shows as unavailable. | Code, and issue #36 | 14 Nov 2026 |
| Sony Bravia TV (`braviatv`) | Reports live | A TV that can't be reached shows as off, never its last values. | Code | 14 Nov 2026 |
| Starlink (`starlink`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| SwitchBot Bluetooth (`switchbot`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| SwitchBot Cloud (`switchbot_cloud`) | Not settled | The code doesn't show what the cloud sends for a device that is offline. Treated as reporting live. | Code | 14 Nov 2026 |
| Synology DSM (`synology_dsm`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Tado (`tado`) | Reports cached values | Only the climate entity follows Tado's online flag. Temperature, humidity and battery show the cloud's last readings. | Code and library | 14 Nov 2026 |
| Tasmota (`tasmota`) | Some models only | Most devices show as unavailable when they are gone. Devices with deep sleep turned on are always shown as available. | Code | 14 Nov 2026 |
| Tesla Fleet (`tesla_fleet`) | Some models only | Energy sites report live. A vehicle that is asleep or offline shows its restored values. | Code | 14 Nov 2026 |
| Tesla Wall Connector (`tesla_wall_connector`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| TP-Link Smart Home (`tplink`) | Some models only | A device connected directly shows as unavailable. Sensors and buttons behind a Tapo hub stay available while the hub answers. | Code | 14 Nov 2026 |
| TRMNL (`trmnl`) | Reports cached values | The display sleeps between check-ins, so every value is the cloud's stored copy. | Code and library | 14 Nov 2026 |
| Tronity (`tronity`) | Reports cached values | It shows the last record the cloud holds for the vehicle. | Code | 14 Nov 2026 |
| Tuya (`tuya`) | Reports live | Its cloud says when a device is offline, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| UniFi Network (`unifi`) | Reports cached values | An access point, switch or gateway that is disconnected stays available with the controller's last figures for it. | Code and library | 14 Nov 2026 |
| UniFi Protect (`unifiprotect`) | Reports live | Its hub says when a device can't be reached, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| UPnP/IGD (`upnp`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| VeSync (`vesync`) | Reports live | Its cloud says when a device is offline, and the device then shows as unavailable. | Code | 14 Nov 2026 |
| Viessmann ViCare (`vicare`) | Some models only | A gateway that is offline shows as unavailable. Thermostats and room sensors behind a gateway show the cloud's values for them. | Code | 14 Nov 2026 |
| Withings (`withings`) | Reports cached values | A device stays available while it is listed in the account, with the cloud's last battery level. | Code and library | 14 Nov 2026 |
| WiZ (`wiz`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| WLED (`wled`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Xbox (`xbox`) | Reports live | A console that is off shows as off, from the cloud's status for it. | Code | 14 Nov 2026 |
| Xiaomi BLE (`xiaomi_ble`) | Some models only | Most devices show as unavailable until heard. Models the library marks as sleepy, such as door, motion and leak sensors, show their restored values. | Code and library | 15 Nov 2026 |
| Yale (`yale`) | Reports cached values | The lock follows its bridge, but the battery and operator sensors show their last values and stay available. | Code and library | 14 Nov 2026 |
| Yeelight (`yeelight`) | Reports live | A device that can't be reached shows as unavailable after a restart. | Code | 14 Nov 2026 |
| Z-Wave JS (`zwave_js`) | Judged by last seen | Every Z-Wave device has a Last Seen sensor. It ships switched off, and Device Sentinel asks for it on the Last Seen Sensor Switched Off card. | Code | 14 Nov 2026 |
| ZHA (`zha`) | Judged by last seen | ZHA keeps its own last-seen time for every device, and Device Sentinel reads it. | Code | 14 Nov 2026 |

## If Your Integration Is Wrong or Missing

This list is our best judgment, and most of it comes from reading code, not from watching real houses. If Device Sentinel treats one of your integrations the wrong way, open an issue at https://github.com/TheThinkingHome/device_sentinel/issues and attach your diagnostics download. An integration that is not in the table has not been checked yet, and Device Sentinel treats it as reporting live.
