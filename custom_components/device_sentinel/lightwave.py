# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: lightwave.py, Version: 0.30.2 (2026-11-22)

"""Lightwave Smart: each device's own link sensor (rule STACK-16).

Lightwave is a cloud integration, not a radio stack, so it is not one
of the stacks in `stacks.py`; it adds only a link sensor, which the
stack-neutral files read as they read Z-Wave's node status.

Lightwave Smart gives each Smart Series device, hubs aside, a
Connectivity binary sensor on its radio device ("<name> Device"),
unique id `<device id>_connectivity`. It reads on while the hub can
reach the device and off once it cannot, about 30 minutes after the
device loses power. It reads unavailable while Home Assistant's
Lightwave session is down, while the hub's own link is lost, and for
any status other than connected or disconnected, which is no opinion.

A device's lights and sockets are devices of their own, registered via
the radio device, so they follow its sensor (FOLLOWERS). A device whose
sensor reads on is never newly called frozen (SPARES_WHILE_UP): a
dimmer used once a week says nothing between uses, and its hub hears
it all the same.

Each hub carries a Cloud Link sensor, unique id `<hub id>_cloudLink`, on
the hub's own device, which Lightwave registers as a service. It reads
off once Home Assistant's Lightwave session is down or the hub's own
link has been lost for about 30 seconds, and unavailable when it cannot
be read. That sensor makes the device a hub (rule STACK-17): watched
though it is a service, judged by the sensor alone, and down while it
reads off. Every Lightwave device registered under it, directly or
through its radio device, is behind it; each keeps its own judgment
while the hub is up (MEMBERS_KEEP_OWN).
"""

from __future__ import annotations

DOMAIN = "lightwave_smart"

# Lights and sockets registered via the radio device follow its sensor.
FOLLOWERS = True
# A device whose sensor reads on is never newly called frozen.
SPARES_WHILE_UP = True
# The device page's Z-Wave status row is Z-Wave's alone.
SHOWS_STATUS_ROW = False

LINK_ON = "on"
LINK_OFF = "off"

# A hub's devices keep their own judgment while it is up, unlike a
# Lutron hub's, which report only when used (rule STACK-17).
MEMBERS_KEEP_OWN = True


def owns_domain(domain: str) -> bool:
    """Whether a device of this integration domain is Lightwave's."""
    return domain == DOMAIN


def is_node_status(ent: object) -> bool:
    """Recognize a device's Connectivity sensor, never the hub's Cloud Link."""
    return (
        getattr(ent, "platform", None) == DOMAIN
        and str(getattr(ent, "entity_id", "")).startswith("binary_sensor.")
        and str(getattr(ent, "unique_id", "") or "").endswith("_connectivity")
    )


def node_dead(state: str) -> bool:
    """Off: the hub cannot reach the device."""
    return state == LINK_OFF


def node_heard(state: str) -> bool:
    """On after off: the hub has heard the device again."""
    return state == LINK_ON


def node_up(state: str) -> bool:
    """On: the hub can reach the device."""
    return state == LINK_ON


def is_hub_link(ent: object) -> bool:
    """Recognize a hub's Cloud Link sensor (rule STACK-17)."""
    return (
        getattr(ent, "platform", None) == DOMAIN
        and str(getattr(ent, "entity_id", "")).startswith("binary_sensor.")
        and str(getattr(ent, "unique_id", "") or "").endswith("_cloudLink")
    )


def hub_link_up(state: str | None) -> bool | None:
    """On is up, off is down; anything else is no opinion."""
    if state == LINK_ON:
        return True
    if state == LINK_OFF:
        return False
    return None
