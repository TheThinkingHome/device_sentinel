# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: stack_zwave.py, Version: 0.27.10 (2026-10-27)

"""Z-Wave JS: everything Device Sentinel knows about this stack.

One file per coordinator stack (rule STACK-01), answering the same
three questions every stack module answers: does this device prove
the stack is present, does this stack own a device on that
integration domain, and give me a reader.

WHAT IS BUILT. Detection: a device whose integration domain is
`zwave_js` means Z-Wave JS is running. And the dead-node check
(rule STACK-05): Home Assistant keeps a dead Z-Wave node's entities
available, so the node status sensor Z-Wave makes for each node is the
only place a dead node shows, and a device whose sensor reads "dead" is
unavailable until it reads anything else. `is_node_status` recognises
the sensor and `node_dead` reads it; the stack-neutral files ask through
`stacks.py` and name no stack. A plug with no meter, unplugged, is
marked dead within two minutes of a failed command and alive within a
minute of being plugged back, with no other entity changing.
Z-Wave learns a node is dead only when a command to it fails, so a
device nobody tries to reach stays "alive" and is left to the freeze
rule. Asleep and awake changes on battery devices are the sensor's
only other traffic, and say nothing.

WHAT IS NOT BUILT, AND WHY. `make_reader` returns None, so no
controller state and no inclusion window is read on Z-Wave. The author
owns no Z-Wave hardware, so every claim about its inclusion model
would be documentation repeated rather than measurement, and nothing
ships for a stack the author cannot test (rule STACK-02). A house on
Z-Wave has no detector for a person's hand: Maintenance Mode says so,
and otherwise the outage rule decides (rule FRZ-15).

WHAT IS KNOWN AND UNVERIFIED. The design comes from documentation
and has never been measured. Inclusion is expected to be observable
as a subscribable event rather than a retained state, which is a
different shape from Z2M's topic: a reader would have to hold the
window itself rather than read it back after a restart. The rule that
matters is already settled and waits only on a way to read it: an
operator-driven inclusion is a person's hand on the network and its
gap is discarded, while a SmartStart auto-rejoin is the network
healing itself and its gap is a real measurement to learn (rule
FRZ-15). Whether the two can be told apart from what is published, and
what Z-Wave JS names a device's availability, are both unknown here.

WHAT A Z-WAVE HOUSE STILL GETS. Nothing above means a failed Z-Wave
stack goes unreported. The integration outage watcher is domain
agnostic and covers `zwave_js` like any other: a config entry that
fails and stays failed is one row naming the integration with the
devices behind it counted and cleared of blame. A coordinator pulled
and replugged clears with no false device faults in the window and
the folded statistics of the Z-Wave devices unchanged (rule UP-03).
What is missing is the running controller, not the outage.

WHAT IS GATHERED. Not judged, only recorded. With Extended Diagnostics
on, the study in `study_stacks.py` gathers what Z-Wave JS says about
its nodes: alive, asleep, dead or unknown, and whether each listens,
sleeps or wakes briefly, and the stack probe writes each
change to `stack_probe.md` beside Device Sentinel's own view of the
same device, the readers in shadow (rule STACK-12). Neither changes a
verdict; both are the evidence a reader would be built on.

THE ASK. This file stays as it is until somebody with Z-Wave hardware
runs the named commands and attaches the output. The wiki page for
this stack carries what is known, what is unverified, the exact
commands, and where to send each kind of answer (rule STACK-02).
"""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr

from .const import STACK_ZWAVE

STACK = STACK_ZWAVE

# Nothing but Z-Wave publishes on the zwave_js domain.
SHARED_DOMAIN = False


def owns_domain(domain: str) -> bool:
    """Return whether a device on this integration domain is Z-Wave's.

    Z-Wave JS owns its own domain outright, which is the simple case:
    the stack's name and the integration domain are the same string,
    so ownership and presence ask the same question.
    """
    return domain == STACK_ZWAVE


def detects(domain: str, device: dr.DeviceEntry) -> bool:
    """Return whether this device proves Z-Wave JS is running.

    The domain is the tell (rule STACK-01), so the device
    entry itself is not consulted. It stays in the signature because
    every stack module answers this question the same way and Z2M
    needs the device to find its bridge.
    """
    return owns_domain(domain)


def is_plumbing(domain: str, device: dr.DeviceEntry) -> bool:
    """Return whether this device is the stack itself, not hardware.

    No for Z-Wave JS (rule WATCH-05). A Z-Wave controller reports through its
    own entities like any other device: an Aeotec Z-Stick speaks every
    204 seconds and carries a real signal series, so
    watching it is right.

    Every stack module answers this question so the walk can ask it
    without knowing which stacks exist (rule STACK-01). The signature
    matches the others; neither argument is consulted.
    """
    return False


def device_key(device: dr.DeviceEntry) -> None:
    """Return None: this stack's device identifiers are unverified.

    Z2M answers this with the IEEE address out of its identifier, and
    Z-Wave JS very likely carries something equivalent. Very likely is
    not measured, and a join key guessed wrong joins a verdict to the
    wrong device, so nothing is claimed here until somebody with the
    hardware sends a real identifier (rule STACK-02).
    """
    return None


def make_reader(hass: object) -> None:
    """Return None: this stack has no reader yet.

    Not a placeholder for something half-built. Nothing judges from a
    Z-Wave controller's state today (the stack probe only records it),
    and the caller treats a None reader as a stack that cannot report
    on itself, which is exactly true.
    """
    return None


# The node status sensor's reading for a node the controller could not
# reach (rule STACK-05).
NODE_STATUS_DEAD = "dead"


def is_node_status(ent: object) -> bool:
    """Recognize Z-Wave's node status sensor (rule STACK-05).

    Home Assistant's Z-Wave integration makes one per node, enabled by
    default, with the unique id `<home id>.<node id>.node_status`. It
    reads alive, asleep, awake, dead or unknown, and it is the only
    place a dead node shows: Home Assistant keeps a node's other
    entities available whether the node is dead or alive.
    """
    return (
        getattr(ent, "platform", None) == STACK_ZWAVE
        and str(getattr(ent, "entity_id", "")).startswith("sensor.")
        and str(getattr(ent, "unique_id", "") or "").endswith(".node_status")
    )


def node_dead(state: str) -> bool:
    """Whether the node status sensor says the node is dead (rule STACK-05).

    Z-Wave JS marks a node dead when a command to it fails, and alive
    when it is heard again. Asleep and awake are a battery device's
    ordinary cycle and say nothing about whether it is down.
    """
    return state == NODE_STATUS_DEAD


# Readings that mean Z-Wave JS has heard the node: it marks a dead node
# alive, and a sleeping one awake, only on hearing from it.
NODE_STATUS_HEARD = ("alive", "awake")
# Readings that say the node is not dead: heard, or asleep as a battery
# device is between wake-ups.
NODE_STATUS_UP = ("alive", "awake", "asleep")


def node_heard(state: str) -> bool:
    """Whether the status reading means the stack has just heard the node.

    Unknown, unavailable or a missing state are none of these: the
    sensor cannot be read, which is not the node coming back.
    """
    return state in NODE_STATUS_HEARD


def node_up(state: str) -> bool:
    """Whether the status reading says the node is not dead."""
    return state in NODE_STATUS_UP
