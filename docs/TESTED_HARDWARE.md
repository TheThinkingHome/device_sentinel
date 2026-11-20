# Tested Hardware

Device Sentinel watches devices on any integration. The hardware below has also run on real houses, watched by the people named with it. If yours is listed here, someone has already seen how Device Sentinel handles it going away and coming back.

The people:

- James Lander ([@TheThinkingHome](https://github.com/TheThinkingHome)), on his own house since July 2026. Each release runs here first.
- Tim Plas ([@tplas](https://github.com/tplas)), on his house since August 2026.
- Christopher Robert ([@Ranger2959](https://github.com/Ranger2959)), on his house in September 2026.
- A friend of Tim Plas, on his house in the United States since October 2026.
- Chris Jenkins ([@ChrisJ60](https://github.com/ChrisJ60)), on his house in the United Kingdom since November 2026, with Home Assistant in Docker.

## Zigbee2MQTT

| Coordinator | Firmware | Tested by |
|---|---|---|
| SMLIGHT SLZB-06M, on the network | EmberZNet | @TheThinkingHome |
| XZG UZG-01, on the network | Z-Stack | @tplas |

**What was tested:** the bridge stopped and restarted, power cuts, and devices re-paired. A bridge outage is one alert, not one per device, and a re-pair is not mistaken for a fault.

## ZHA

| Coordinator | Tested by |
|---|---|
| SMLIGHT coordinator with a Texas Instruments CC2652 | @TheThinkingHome |
| ConBee II, on USB | @tplas |

**What was tested:** ZHA reloading and restarting, and devices re-paired through ZHA. A coordinator outage is one alert, and a ZHA device keeps its verdict through a ZHA restart.

## MQTT Broker

| Broker | Tested by |
|---|---|
| Mosquitto, the Home Assistant add-on | @TheThinkingHome; also runs on @tplas's house |

**What was tested:** the broker stopped for minutes at a time and restarted. A broker outage is one alert, and it counts only the devices that reach Home Assistant through the broker.

## Wi-Fi And Routers

| Router integration | Tested by |
|---|---|
| TP-Link Router, with a wireless adapter in the Home Assistant server | @TheThinkingHome |
| UniFi Network | @tplas |

**What was tested:** the Wi-Fi network switched off and back on, on both houses. A Wi-Fi outage is one alert, dated from when the network went, and devices that come back on their own are not reported one by one. Wi-Fi support is experimental.

## Z-Wave

| Controller | Tested by |
|---|---|
| Aeotec Z-Stick Gen5+, on Z-Wave JS | @tplas |

**What was tested:** a Z-Wave smart plug was unplugged on 15 October 2026. Z-Wave JS marked it dead, Device Sentinel reported it unavailable from that moment, and reported it back when Z-Wave heard it again, with how long it was gone. Battery sensors that sleep and wake through the day are left alone while they do.

## Matter Over Wi-Fi

| Devices | Tested by |
|---|---|
| Govee H6076 floor lamp, TP-Link Tapo P125M plug | @tplas |

**What was tested:** both were unplugged on 19 October 2026. Home Assistant marked each unavailable about five minutes after it was last heard, and Device Sentinel reported it a few minutes later. Each was reported back a second after it was plugged in again. Since 0.26.8, a Matter light or plug with no battery is not called frozen while Home Assistant shows it available.

## Matter Over Thread

| Hardware | Tested by |
|---|---|
| Two SMLIGHT OpenThread Border Routers; IKEA BILRESA buttons and scroll wheel, IKEA GRILLPLATS plug, IKEA temperature and humidity sensor | @tplas |

**Still to test:** what happens when a battery button loses its battery.

## Lutron Caséta

| Hardware | Tested by |
|---|---|
| Lutron Caséta hub, with Lutron lights, switches, Pico remotes and Serena shades | @Ranger2959 |

**What was built from it:** Device Sentinel judges Lutron devices by their hub, so a light nobody uses is not a fault, and a Pico press counts as the remote reporting. A hub that goes down is one alert. Lutron support is experimental.

## Alarm.com

| Hardware | Tested by |
|---|---|
| An Alarm.com security system with its door, motion and freeze sensors and three cameras (ADC-V522IR, ADC-VC736), through the Alarm.com integration from HACS | a friend of @tplas |

**What was seen:** Alarm.com updates every device together from its cloud, every few minutes. When those updates stopped while the integration stayed loaded, each device was reported as stopped reporting. When the integration failed to start after a Home Assistant update, it was one integration outage, with none of its devices listed.

## Tado

| Hardware | Tested by |
|---|---|
| Tado internet bridge, with smart thermostats, radiator thermostats and temperature sensors (RU02, VA01, VA02, SU02, BU01) | @ChrisJ60 |

**What was seen:** Tado updates every device at once from its cloud. Device Sentinel recognizes it as a cloud integration that polls, and the burst of updates after a restart is not reported as a reload.

## Lightwave Smart

| Hardware | Tested by |
|---|---|
| Lightwave Link Plus (L2), with sockets (L42, L42MK3, L40MK2), dimmers (L21, L21MK2, L21MK3, L22, L22MK3, L23, L23MK3) and relays (L92) | @ChrisJ60 |

**What was seen:** a socket with a load reports about once an hour and is watched by its own rhythm. A dimmer reports only when it is used, so one left alone for a day can be listed as stopped reporting; Mute freeze is the right setting for those. The Lightwave integration never marks a device unavailable, so a long silence is the only sign one has gone.

## Philips Hue, SmartThings and Tuya

| Hardware | Tested by |
|---|---|
| Philips Hue Bridge with Hue lamps; SmartThings Hub v3 with CentraLite sensors; Tuya Wi-Fi dimmers and temperature and humidity sensors | a friend of @tplas |

**What was seen:** each hub's devices report on their own. A light that reports only when it is used can be listed as stopped reporting after a long quiet spell, as on Lightwave. Home Assistant lists each Tuya device twice; Device Sentinel watches it once and sets the empty copy aside.

## Home Assistant in Docker

| Install | Tested by |
|---|---|
| Home Assistant Container, in Docker | @ChrisJ60 |

**What was seen:** since 0.28.12, Device Sentinel's stored data comes through restarts and updates intact, with nothing to repair.

## Add Your Own

If your hardware is not here, open an issue or a pull request with what you run and what you saw.
