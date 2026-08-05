# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_stacks.py, Version: 0.12.1 (2026-08-05)

"""The stack registry, the four stack modules, and the silence.

Three subjects. The contract each stack module implements, exercised
on all four rather than only on the one with a reader, because ruling
#218 asks that the contract be implemented three times before it is
relied on once and an unexercised implementation is a claim rather
than a proof.

The domain replay, which is the proof that the pairing lookup did not
change when it stopped naming a stack. The old form and the new form
are both evaluated over every domain a real fleet carries plus the
guarded cases, and asserted equal on each.

The silence, which is the part that has to keep being true. Ruling
#215's lesson was that a hand-maintained list inside a guard drifts
while the guard keeps passing, so this one reads the source with ast
rather than repeating what it expects to find.
"""

from __future__ import annotations

import ast
import pathlib

from custom_components.device_sentinel import (
    stack_matter,
    stack_z2m,
    stack_zha,
    stack_zwave,
    stacks,
)
from custom_components.device_sentinel.const import (
    STACK_MATTER,
    STACK_Z2M,
    STACK_ZHA,
    STACK_ZWAVE,
)

PKG = pathlib.Path(stacks.__file__).parent

# Every stack module, and the integration domain each owns. Z2M is the
# one whose stack name and domain differ, which is the whole reason
# presence is told by its bridge device (ruling #139).
OWNED_DOMAIN = {
    stack_zha: "zha",
    stack_zwave: "zwave_js",
    stack_matter: "matter",
    stack_z2m: "mqtt",
}

# Domains seen on the reference fleet, plus the four stack domains and
# the shapes that are not domains at all. The replay runs over this
# whole set rather than over a chosen example.
FLEET_DOMAINS = [
    "mqtt",
    "zha",
    "zwave_js",
    "matter",
    "hue",
    "esphome",
    "shelly",
    "tasmota",
    "sun",
    "device_tracker",
    "unifi",
    "google_assistant",
    "unknown",
    "",
    None,
]


class _Device:
    """The two fields detection reads off a registry entry."""

    def __init__(self, name="Kitchen Motion", model=None, manufacturer=None):
        self.name = name
        self.name_by_user = None
        self.model = model
        self.manufacturer = manufacturer


BRIDGE = _Device(name="SLZB-06M Zigbee2MQTT Bridge")
NOT_BRIDGE = _Device(name="Kitchen Motion")


def test_every_stack_module_implements_the_contract():
    """Four names on every stack module, not three plus a special case."""
    for module in stacks.STACK_MODULES:
        assert isinstance(module.STACK, str)
        assert callable(module.owns_domain)
        assert callable(module.detects)
        assert callable(module.make_reader)


def test_each_stack_owns_its_own_domain_and_no_other():
    """Ownership is exclusive: no domain is claimed by two stacks."""
    for module, domain in OWNED_DOMAIN.items():
        assert module.owns_domain(domain) is True
        for other, other_domain in OWNED_DOMAIN.items():
            if other is not module:
                assert module.owns_domain(other_domain) is False


def test_the_three_unbuilt_stacks_detect_by_domain_alone():
    """The detection the project already performed, moved not changed."""
    for module, domain in (
        (stack_zha, "zha"),
        (stack_zwave, "zwave_js"),
        (stack_matter, "matter"),
    ):
        assert module.detects(domain, NOT_BRIDGE) is True
        assert module.detects("mqtt", BRIDGE) is False
        assert module.detects("hue", NOT_BRIDGE) is False


def test_z2m_is_detected_by_its_bridge_device_and_not_its_domain():
    """The mqtt domain alone proves nothing (rulings #139 and #143)."""
    assert stack_z2m.detects("mqtt", BRIDGE) is True
    assert stack_z2m.detects("mqtt", NOT_BRIDGE) is False
    assert stack_z2m.detects("zha", BRIDGE) is False


def test_z2m_recognises_the_bridge_by_model_when_the_name_is_changed():
    """The second tell, for a bridge somebody has renamed."""
    renamed = _Device(
        name="Coordinator", model="Bridge", manufacturer="Zigbee2MQTT"
    )
    assert stack_z2m.is_bridge_device(renamed) is True
    assert stack_z2m.is_bridge_device(NOT_BRIDGE) is False


def test_only_z2m_makes_a_reader():
    """A stack with no reader costs no subscription and no timer."""
    assert stack_zha.make_reader(None) is None
    assert stack_zwave.make_reader(None) is None
    assert stack_matter.make_reader(None) is None
    assert stacks.make_reader(STACK_ZHA, None) is None
    assert stacks.make_reader(STACK_ZWAVE, None) is None
    assert stacks.make_reader(STACK_MATTER, None) is None
    assert stacks.make_reader("no_such_stack", None) is None


def test_detect_returns_the_stack_a_device_proves():
    """One device, at most one stack, and None for everything else."""
    assert stacks.detect("mqtt", BRIDGE) == STACK_Z2M
    assert stacks.detect("mqtt", NOT_BRIDGE) is None
    assert stacks.detect("zha", NOT_BRIDGE) == STACK_ZHA
    assert stacks.detect("zwave_js", NOT_BRIDGE) == STACK_ZWAVE
    assert stacks.detect("matter", NOT_BRIDGE) == STACK_MATTER
    assert stacks.detect("hue", NOT_BRIDGE) is None


def _old_form(readers, domain):
    """The pairing lookup as detect_freeze.py held it in 0.12.0.

    Fetch the reader keyed z2m, then require the device's domain to
    be exactly mqtt. Kept here so the replacement is measured against
    the real thing rather than against a description of it.
    """
    found = readers.get(STACK_Z2M)
    if found is None:
        return None
    if domain != "mqtt":
        return None
    return found


def test_the_domain_replay_agrees_with_the_form_it_replaced():
    """The pairing lookup, old form against new, over every domain.

    Every reader set that can exist: the one Z2M reader, and none at
    all. Against every domain the reference fleet carries and the
    shapes that are not domains. They cannot disagree on any of them.
    """
    reader = object()
    for readers in ({STACK_Z2M: reader}, {}):
        for domain in FLEET_DOMAINS:
            assert stacks.reader_for_domain(readers, domain) == _old_form(
                readers, domain
            ), f"disagreed on {domain!r} with readers {sorted(readers)}"


def test_the_one_divergence_is_unreachable_and_stays_that_way():
    """Where the two forms differ, and why it cannot happen.

    Handed a reader filed under a stack other than Z2M, the old form
    returns nothing (it looked only for z2m) and the new form returns
    that reader (it asks who owns the domain). The new form is the
    generalization the old one would have become, so this is the
    intended difference rather than a fault, and it is unreachable:
    the only source of readers is the registry, and the registry
    makes one for Z2M alone. The day a second stack gains a reader
    this test is what says the divergence has become live, and the
    pairing behaviour of that stack has to be ruled before it ships.
    """
    reader = object()
    zha_only = {STACK_ZHA: reader}
    assert _old_form(zha_only, "zha") is None
    assert stacks.reader_for_domain(zha_only, "zha") is reader
    # Unreachable, because nothing but Z2M can produce a reader.
    for module in stacks.STACK_MODULES:
        made = module.make_reader(None)
        assert (made is None) is (module.STACK != STACK_Z2M)


def _imported_names(path: pathlib.Path) -> set[str]:
    """Return every name a module imports, by parsing rather than text."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def _string_constants(path: pathlib.Path) -> set[str]:
    """Return every string literal in a module, docstrings excluded.

    Parsed rather than grepped, so a docstring that mentions
    Zigbee2MQTT does not fail the guard while a live literal does.
    """
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    }


def test_the_stack_agnostic_files_name_no_stack():
    """The silence ruling #218 asks for, asserted rather than trusted.

    Three files held stack knowledge before this release: the registry
    walk in coordinator.py, the bridge test in interventions.py, and
    the pairing lookup in detect_freeze.py. None of them may import a
    STACK_ name or carry a stack's domain as a live literal. A fourth
    stack should change none of them, and this fails if one grows a
    branch back.
    """
    domains = {"mqtt", "zha", "zwave_js", "matter", "zigbee2mqtt"}
    for name in ("coordinator.py", "interventions.py", "detect_freeze.py"):
        path = PKG / name
        offending = {
            imported
            for imported in _imported_names(path)
            if imported.startswith("STACK_")
        }
        assert not offending, f"{name} imports {sorted(offending)}"
        literals = _string_constants(path) & domains
        assert not literals, f"{name} carries {sorted(literals)}"


def test_the_registry_is_the_only_place_a_stack_is_registered():
    """One line of registration, and every stack module is on it."""
    modules = {module.STACK for module in stacks.STACK_MODULES}
    assert modules == {STACK_ZHA, STACK_ZWAVE, STACK_MATTER, STACK_Z2M}
    assert len(stacks.STACK_MODULES) == 4
