# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: stack_zwave.py, Version: 0.12.3 (2026-08-05)

"""Z-Wave JS: everything Device Sentinel knows about this stack.

One file per coordinator stack (ruling #218), answering the same
three questions every stack module answers: does this device prove
the stack is present, does this stack own a device on that
integration domain, and give me a reader.

WHAT IS BUILT. Detection only, and it is the detection this project
already performs on every rebuild: a device whose integration domain
is `zwave_js` means Z-Wave JS is running. That much is proven,
because it is what the registry walk did before this file existed.

WHAT IS NOT BUILT, AND WHY. `make_reader` returns None, so no
controller state and no inclusion window is read on Z-Wave. That is a
statement about this project rather than about Z-Wave. There is no
Z-Wave hardware on the reference fleet, so every claim about its
availability and inclusion model would be documentation repeated
rather than measurement, and nothing ships for a stack the author
cannot test (ruling #218). A house on Z-Wave gets every other family
of judgment and falls to the per-device debounce for interventions
(ruling #138).

WHAT IS KNOWN AND UNVERIFIED. The design was ruled from documentation
and has never been measured. Inclusion is expected to be observable
as a subscribable event rather than a retained state, which is a
different shape from Z2M's topic: a reader would have to hold the
window itself rather than read it back after a restart. The rule that
matters is already settled and waits only on a way to read it: an
operator-driven inclusion is a person's hand on the network and its
gap is discarded, while a SmartStart auto-rejoin is the network
healing itself and its gap is a real measurement to learn (ruling
#141). Whether the two can be told apart from what is published, and
what Z-Wave JS names a device's availability, are both unknown here.

THE ASK. This file stays as it is until somebody with Z-Wave hardware
runs the named commands and attaches the output. The wiki page for
this stack carries what is known, what is unverified, the exact
commands, and where to send each kind of answer (ruling #219).
"""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr

from .const import STACK_ZWAVE

STACK = STACK_ZWAVE


def owns_domain(domain: str) -> bool:
    """Return whether a device on this integration domain is Z-Wave's.

    Z-Wave JS owns its own domain outright, which is the simple case:
    the stack's name and the integration domain are the same string,
    so ownership and presence ask the same question.
    """
    return domain == STACK_ZWAVE


def detects(domain: str, device: dr.DeviceEntry) -> bool:
    """Return whether this device proves Z-Wave JS is running.

    The domain is the tell (rulings #139 and #143), so the device
    entry itself is not consulted. It stays in the signature because
    every stack module answers this question the same way and Z2M
    needs the device to find its bridge.
    """
    return owns_domain(domain)


def device_key(device: dr.DeviceEntry) -> None:
    """Return None: this stack's device identifiers are unverified.

    Z2M answers this with the IEEE address out of its identifier, and
    Z-Wave JS very likely carries something equivalent. Very likely is
    not measured, and a join key guessed wrong joins a verdict to the
    wrong device, so nothing is claimed here until somebody with the
    hardware sends a real identifier (rulings #218 and #219).
    """
    return None


def make_reader(hass: object) -> None:
    """Return None: this stack has no reader yet.

    Not a placeholder for something half-built. Nothing reads a
    Z-Wave controller's state today, and the caller treats a None
    reader as a stack that cannot report on itself, which is exactly
    true.
    """
    return None
