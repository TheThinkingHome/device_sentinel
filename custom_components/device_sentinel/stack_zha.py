# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: stack_zha.py, Version: 0.12.1 (2026-08-05)

"""ZHA: everything Device Sentinel knows about this stack.

One file per coordinator stack (ruling #218), answering the same
three questions every stack module answers: does this device prove
the stack is present, does this stack own a device on that
integration domain, and give me a reader.

WHAT IS BUILT. Detection only, and it is the detection this project
already performs on every rebuild: a device whose integration domain
is `zha` means ZHA is running. That much is proven, because it is
what the registry walk did before this file existed.

WHAT IS NOT BUILT, AND WHY. `make_reader` returns None, so no bridge
state and no pairing window is read on ZHA. That is a statement about
this project rather than about ZHA. There is no ZHA hardware on the
reference fleet, so every claim about its availability and pairing
model would be documentation repeated rather than measurement, and
nothing ships for a stack the author cannot test (ruling #218). A
house on ZHA gets every other family of judgment and falls to the
per-device debounce for interventions (ruling #138), which is what
every house did before any reader existed.

WHAT IS KNOWN AND UNVERIFIED. The design was ruled from documentation
and has never been measured. Pairing is expected to be observable
through the `zha.permit` service call, which fires when a join is
opened from the Home Assistant UI and is the common path. A join
opened out of band, by a button on a router or by Touchlink, calls no
service and is not detectable at all; that is a plain limit rather
than a gap to be closed later, and it falls to the debounce (ruling
#142). Whether ZHA publishes anything equivalent to a coordinator
liveness state, and what it names a device's availability, are both
unknown here.

THE ASK. This file stays as it is until somebody with ZHA hardware
runs the named commands and attaches the output. The wiki page for
this stack carries what is known, what is unverified, the exact
commands, and where to send each kind of answer (ruling #219).
"""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr

from .const import STACK_ZHA

STACK = STACK_ZHA


def owns_domain(domain: str) -> bool:
    """Return whether a device on this integration domain is ZHA's.

    ZHA owns its own domain outright, which is the simple case: the
    stack's name and the integration domain are the same string, so
    ownership and presence ask the same question.
    """
    return domain == STACK_ZHA


def detects(domain: str, device: dr.DeviceEntry) -> bool:
    """Return whether this device proves ZHA is running.

    The domain is the tell (rulings #139 and #143), so the device
    entry itself is not consulted. It stays in the signature because
    every stack module answers this question the same way and Z2M
    needs the device to find its bridge.
    """
    return owns_domain(domain)


def make_reader(hass: object) -> None:
    """Return None: this stack has no reader yet.

    Not a placeholder for something half-built. Nothing reads a ZHA
    coordinator's state today, and the caller treats a None reader as
    a stack that cannot report on itself, which is exactly true.
    """
    return None
