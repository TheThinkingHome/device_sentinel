# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: stacks.py, Version: 0.12.3 (2026-08-05)

"""The one place a coordinator stack is registered.

Ruling #218 asks that adding a stack touch one new file and one line
of registration. This is that line: STACK_MODULES below. Everything
else in the package asks its questions here and never names a stack,
so a fifth stack changes no detector, no sensor and no registry walk.

The registry deliberately holds no knowledge of its own. Every
question is answered by asking each stack module in turn, and the
answers come from the module rather than from a table here, because
a table here would be the fourth place stack knowledge lived and
this file exists to end the other three.

Order is the order the registry walk used before this file existed:
ZHA, Z-Wave, Matter, then Z2M. It does not matter today, since a
device's integration domain can satisfy only one stack, but the
order is kept rather than sorted so that the behaviour of the walk
is unchanged by inspection as well as by proof.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import stack_matter, stack_z2m, stack_zha, stack_zwave

# The one line of registration (ruling #218).
STACK_MODULES = (stack_zha, stack_zwave, stack_matter, stack_z2m)


def detect(domain: str, device: dr.DeviceEntry) -> str | None:
    """Return the stack this device proves is running, if any.

    Called once per device during the registry rebuild that already
    happens, which is what makes stack detection a reduction over an
    existing walk rather than a new traversal (ruling #143). The
    result is derived and recomputed each rebuild, never persisted,
    so a stack added or removed needs no migration.
    """
    for module in STACK_MODULES:
        if module.detects(domain, device):
            return module.STACK
    return None


def device_key(domain: str, device: dr.DeviceEntry) -> tuple[str, str] | None:
    """Return the stack owning this device and the key it knows it by.

    Asked once per device during the registry rebuild that already
    happens, beside detection. A stack that cannot say how it names a
    device returns None and the device simply has no key, which is
    what every unbuilt stack does today.
    """
    for module in STACK_MODULES:
        if not module.owns_domain(domain):
            continue
        key = module.device_key(device)
        if key is None:
            return None
        return module.STACK, key
    return None


def make_reader(stack: str, hass: HomeAssistant) -> Any | None:
    """Return a bridge reader for a stack, or None if it has none.

    A stack that cannot report on its own liveness and pairing state
    returns None here and gets no reader, no subscription and no
    timer. That is what makes an absent or unbuilt stack cost
    nothing at all.
    """
    for module in STACK_MODULES:
        if module.STACK == stack:
            return module.make_reader(hass)
    return None


def reader_for_domain(
    readers: dict[str, Any], domain: str | None
) -> Any | None:
    """Return the reader belonging to a device on this domain, if any.

    The pairing check asks this: a device recovering during a pairing
    window is only a pairing candidate if the window belongs to the
    stack that owns the device. A domain no stack claims, a stack
    with no reader, and a device the registry view has never seen all
    return None, which every caller reads as "cannot tell" and
    handles by falling back to the debounce (ruling #147).
    """
    if domain is None:
        return None
    for module in STACK_MODULES:
        if module.owns_domain(domain):
            return readers.get(module.STACK)
    return None
