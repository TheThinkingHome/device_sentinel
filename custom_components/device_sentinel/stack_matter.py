# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: stack_matter.py, Version: 0.27.10 (2026-10-27)

"""Matter: everything Device Sentinel knows about this stack.

One file per coordinator stack (rule STACK-01), answering the same
three questions every stack module answers: does this device prove
the stack is present, does this stack own a device on that
integration domain, and give me a reader.

WHAT IS BUILT. Detection only, and it is the detection this project
already performs on every rebuild: a device whose integration domain
is `matter` means Matter is running. That much is proven by the
domain alone.

WHAT IS NOT BUILT, AND WHY. `make_reader` returns None. Matter is
further back than the other two: it is detected as present and
nothing more, and its commissioning observability has not been
researched at all, so there is no design from documentation to
record here. A house on Matter gets every other family of judgment
and falls to the per-device debounce for interventions (rule FRZ-15).
As on Z-Wave, a Matter integration that fails setup
and stays failed is still caught by the domain-agnostic integration
outage watcher, one row naming the integration with its devices
counted; what is missing here is the commissioning window and any
reading of the stack while it runs.

WHAT IS KNOWN AND UNVERIFIED. Beyond the domain, only how a device's
availability behaves is measured (rule STACK-06). Whether
commissioning is observable from Home Assistant, and whether a fabric
has any coordinator-wide state worth reading, are open questions
rather than unverified answers.

WHAT IS GATHERED. Not judged, only recorded. With Extended Diagnostics
on, the study in `study_stacks.py` gathers what Matter says about its
server and nodes: whether a node is available and which network it is
on, and the stack probe writes each change to
`stack_probe.md` beside Device Sentinel's own view of the same device,
the readers in shadow (rule STACK-12). Neither changes a verdict; both are
the evidence a reader would be built on.

THE ASK. This file stays as it is until somebody with Matter hardware
runs the named commands and attaches the output. Its first question
is narrower than the other two stacks': whether anything is published
at all (rule STACK-02).
"""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr

from .const import STACK_MATTER

STACK = STACK_MATTER

# Nothing but Matter publishes on the matter domain.
SHARED_DOMAIN = False

# A Matter device of a type that reports only on use, not behind a bridge, is
# judged by being available rather than by its rhythm, because an
# unplugged lamp or plug reads unavailable within about five minutes, and
# a button without its battery within about fourteen (rule STACK-06).
AVAILABLE_SPEAKS = True


def owns_domain(domain: str) -> bool:
    """Return whether a device on this integration domain is Matter's.

    Matter owns its own domain outright, which is the simple case:
    the stack's name and the integration domain are the same string,
    so ownership and presence ask the same question.
    """
    return domain == STACK_MATTER


def detects(domain: str, device: dr.DeviceEntry) -> bool:
    """Return whether this device proves Matter is running.

    The domain is the tell (rule STACK-01), so the device
    entry itself is not consulted. It stays in the signature because
    every stack module answers this question the same way and Z2M
    needs the device to find its bridge.
    """
    return owns_domain(domain)


def is_plumbing(domain: str, device: dr.DeviceEntry) -> bool:
    """Return whether this device is the stack itself, not hardware.

    No for Matter (rule WATCH-05). Matter has no reader yet, and nothing here
    is known to be plumbing rather than hardware. Answering no is the honest
    default: a stack that cannot say costs nothing.

    Every stack module answers this question so the walk can ask it
    without knowing which stacks exist (rule STACK-01). The signature
    matches the others; neither argument is consulted.
    """
    return False


def device_key(device: dr.DeviceEntry) -> None:
    """Return None: this stack's device identifiers are unverified.

    Z2M answers this with the IEEE address out of its identifier, and
    Matter very likely carries something equivalent. Very likely is
    not measured, and a join key guessed wrong joins a verdict to the
    wrong device, so nothing is claimed here until somebody with the
    hardware sends a real identifier (rule STACK-02).
    """
    return None


def make_reader(hass: object) -> None:
    """Return None: this stack has no reader yet.

    Not a placeholder for something half-built. Nothing judges from a
    Matter fabric's state today (the stack probe only records it), and
    the caller treats a None reader as a stack that cannot report on
    itself, which is exactly true.
    """
    return None
