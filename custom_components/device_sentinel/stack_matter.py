# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: stack_matter.py, Version: 0.12.1 (2026-08-05)

"""Matter: everything Device Sentinel knows about this stack.

One file per coordinator stack (ruling #218), answering the same
three questions every stack module answers: does this device prove
the stack is present, does this stack own a device on that
integration domain, and give me a reader.

WHAT IS BUILT. Detection only, and it is the detection this project
already performs on every rebuild: a device whose integration domain
is `matter` means Matter is running. That much is proven, because it
is what the registry walk did before this file existed.

WHAT IS NOT BUILT, AND WHY. `make_reader` returns None. Matter is
further back than the other two: it is detected as present and
nothing more, and its commissioning observability has not been
researched at all, so there is not even a design ruled from
documentation to record here. Recorded as banked rather than as
work in progress. A house on Matter gets every other family of
judgment and falls to the per-device debounce for interventions
(ruling #138).

WHAT IS KNOWN AND UNVERIFIED. Nothing is known beyond the domain.
Whether commissioning is observable from Home Assistant, what a
Matter device's availability looks like, and whether a fabric has any
coordinator-wide state worth reading, are all open questions rather
than unverified answers.

THE ASK. This file stays as it is until somebody with Matter hardware
runs the named commands and attaches the output. Its first question
is narrower than the other two stacks': whether anything is published
at all (ruling #219).
"""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr

from .const import STACK_MATTER

STACK = STACK_MATTER


def owns_domain(domain: str) -> bool:
    """Return whether a device on this integration domain is Matter's.

    Matter owns its own domain outright, which is the simple case:
    the stack's name and the integration domain are the same string,
    so ownership and presence ask the same question.
    """
    return domain == STACK_MATTER


def detects(domain: str, device: dr.DeviceEntry) -> bool:
    """Return whether this device proves Matter is running.

    The domain is the tell (rulings #139 and #143), so the device
    entry itself is not consulted. It stays in the signature because
    every stack module answers this question the same way and Z2M
    needs the device to find its bridge.
    """
    return owns_domain(domain)


def make_reader(hass: object) -> None:
    """Return None: this stack has no reader yet.

    Not a placeholder for something half-built. Nothing reads a
    Matter fabric's state today, and the caller treats a None reader
    as a stack that cannot report on itself, which is exactly true.
    """
    return None
