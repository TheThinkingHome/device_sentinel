# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tests/test_zha_join_observer.py, Version: 0.27.10 (2026-10-27)

"""The ZHA join observer marks a device a person handled, and nothing
else (rule FRZ-17).

It is an instrument, so what the tests hold is mostly what it must NOT
do: never claim a pairing window, never touch a verdict, never break a
setup, and never fill the log with messages it is not for.
"""

import logging
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.device_sentinel import stack_zha
from custom_components.device_sentinel.const import (
    ZHA_GATEWAY_SIGNAL,
    ZHA_JOIN_MESSAGES,
)


def test_the_signal_and_messages_are_plain_strings():
    """Named here rather than imported from ZHA: an import breaks a
    setup on an upgrade, a stale string simply stops delivering."""
    assert ZHA_GATEWAY_SIGNAL == "zha_gateway_message"
    assert ZHA_JOIN_MESSAGES == {
        "device_joined",
        "raw_device_initialized",
        "device_fully_initialized",
        # A removal: a person removing a device is handling it, and a
        # sleeping battery device never hears the leave request, so it
        # rejoins by itself at the next start (rule FRZ-17).
        "device_removed",
    }


async def test_it_subscribes_and_unsubscribes_cleanly(
    hass: HomeAssistant,
):
    observer = stack_zha.make_join_observer(hass)
    assert observer.async_start() is True
    # Starting twice is one subscription, not two.
    assert observer.async_start() is True
    observer.async_stop()
    # Stopping twice is harmless.
    observer.async_stop()


async def test_a_handling_is_recorded_by_registry_id(
    hass: HomeAssistant, caplog
):
    """The full init carries device_reg_id, which is the key this
    integration already files records under, so a handling needs no
    matching and no guesswork."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    observer.async_start()
    with caplog.at_level(logging.DEBUG):
        # A re-pair: the join comes first, carrying the address (rule FRZ-17).
        observer._on_message(PAIRING)
        observer._on_message(
            {"type": "device_joined", "device_info": {"ieee": "b4:0e:06:0f:ff:e0:fc:6f"}}
        )
        observer._on_message(
            {
                "type": "device_fully_initialized",
                "device_info": {
                    "ieee": "b4:0e:06:0f:ff:e0:fc:6f",
                    "device_reg_id": "97bdcccf073c7ebc33adf6edd9ab8907",
                    "user_given_name": "ZHA Test Device - Motion",
                    "pairing_status": "CONFIGURED",
                },
            }
        )
    assert seen == [
        ("97bdcccf073c7ebc33adf6edd9ab8907", "re-pair")
    ]
    assert "was handled" in caplog.text
    assert "97bdcccf073c7ebc33adf6edd9ab8907" in observer.handled
    observer.async_stop()


async def test_a_message_without_a_registry_id_records_nothing(
    hass: HomeAssistant,
):
    """device_joined and raw_device_initialized carry the ieee and no
    registry id. A device this integration cannot name is one it cannot
    file, and mapping an ieee by guesswork would attach a person's
    action to the wrong record."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    for payload in (
        {"type": "device_joined", "device_info": {"ieee": "aa", "nwk": 1}},
        {"type": "raw_device_initialized", "ieee": "aa", "nwk": 1},
    ):
        observer._on_message(payload)
    assert seen == []
    assert observer.handled == {}
    # It still counted them, because they are real messages.
    assert observer.seen == 2


async def test_the_top_level_shape_is_read_too(hass: HomeAssistant):
    """raw_device_initialized carries its fields at the top level
    rather than under device_info. Both shapes are read rather than one
    assumed."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    observer._on_message(
        {
            "type": "raw_device_initialized",
            "ieee": "b4:0e",
            "device_reg_id": "abc123",
            "pairing_status": "INTERVIEW_COMPLETE",
        }
    )
    assert seen == [("abc123", "raw_device_initialized")]


async def test_messages_it_is_not_for_are_ignored(
    hass: HomeAssistant, caplog
):
    """A busy network must not fill the log. Groups, log entries and
    connection notices are none of this reader's business; a removal
    is (rule GEN-10)."""
    observer = stack_zha.make_join_observer(hass)
    with caplog.at_level(logging.DEBUG):
        for kind in (
            "group_added",
            "log_entry",
            "connection_lost",
        ):
            observer._on_message({"type": kind, "device_info": {}})
    assert observer.seen == 0
    assert "ZHA join message" not in caplog.text


async def test_a_malformed_message_is_named_not_parsed(
    hass: HomeAssistant, caplog
):
    """What cannot be understood is said, never guessed (rule GEN-10)."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    with caplog.at_level(logging.DEBUG):
        observer._on_message("not a dict")
        observer._on_message(None)
        observer._on_message({"type": []})
    assert "unexpected shape" in caplog.text
    assert observer.seen == 0
    assert seen == []


async def test_a_refused_subscription_does_not_break_anything(
    hass: HomeAssistant, monkeypatch
):
    """An instrument that can break a setup is worse than no
    instrument."""

    def boom(*args, **kwargs):
        raise RuntimeError("no dispatcher today")

    monkeypatch.setattr(stack_zha, "async_dispatcher_connect", boom)
    observer = stack_zha.make_join_observer(hass)
    assert observer.async_start() is False
    observer.async_stop()


async def test_it_claims_no_pairing_window(hass: HomeAssistant):
    """ZHA keeps no pairing window, so nothing the observer sees may
    claim one (rule FRZ-17)."""
    reader = stack_zha.make_reader(MagicMock())
    assert reader.pairing_open is False
    observer = stack_zha.make_join_observer(hass)
    observer._on_message(
        {"type": "device_joined", "device_info": {"ieee": "x"}}
    )
    assert reader.pairing_open is False
    assert not hasattr(observer, "pairing_open")


def test_the_observer_is_reached_through_the_registry():
    """The caller names no stack (rule STACK-01), which
    test_the_stack_agnostic_files_name_no_stack also guards."""
    from unittest.mock import MagicMock

    from custom_components.device_sentinel import stacks
    from custom_components.device_sentinel.const import (
        STACK_MATTER, STACK_Z2M, STACK_ZHA, STACK_ZWAVE,
    )

    hass = MagicMock()
    assert stacks.make_join_observer(STACK_ZHA, hass) is not None
    for stack in (STACK_Z2M, STACK_ZWAVE, STACK_MATTER, "no_such_stack"):
        assert stacks.make_join_observer(stack, hass) is None


# ----------------------------------------------------- the handling tag


async def test_a_handling_is_filed_under_the_registry_id(
    hass: HomeAssistant,
):
    """The full init carries device_reg_id, which is the key the rest of
    the integration files records under, so nothing has to be matched by
    name or address (rule FRZ-17)."""
    from custom_components.device_sentinel.const import (
        ZHA_HANDLED_TAIL_SECONDS,
    )

    observer = stack_zha.make_join_observer(hass)
    observer._on_message(PAIRING)
    observer._on_message(
        {"type": "device_joined", "device_info": {"ieee": "b4:0e:06:0f:ff:e0:fc:6f"}}
    )
    observer._on_message(
        {
            "type": "device_fully_initialized",
            "device_info": {
                "ieee": "b4:0e:06:0f:ff:e0:fc:6f",
                "device_reg_id": "97bdcccf073c7ebc33adf6edd9ab8907",
                "pairing_status": "CONFIGURED",
            },
        }
    )
    now = dt_util.utcnow().timestamp()
    assert observer.handled_since(
        "97bdcccf073c7ebc33adf6edd9ab8907", now
    ) is not None
    # And it expires, so a device handled an hour ago is not blamed
    # for a recovery today.
    assert observer.handled_since(
        "97bdcccf073c7ebc33adf6edd9ab8907",
        now + ZHA_HANDLED_TAIL_SECONDS + 1,
    ) is None


async def test_a_message_without_a_registry_id_tags_nothing(
    hass: HomeAssistant,
):
    """device_joined and raw_device_initialized carry the ieee and no
    registry id. Nothing is filed from them, and nothing is guessed:
    the full init follows within seconds carrying both, and mapping
    an address to a device by inference would risk attaching a
    person's action to the wrong record."""
    observer = stack_zha.make_join_observer(hass)
    observer._on_message(
        {"type": "device_joined", "device_info": {"ieee": "never:seen"}}
    )
    assert observer.handled == {}


async def test_a_removal_counts_as_handling(hass: HomeAssistant):
    observer = stack_zha.make_join_observer(hass)
    observer._on_message(
        {
            "type": "device_removed",
            "device_info": {
                "ieee": "dd:ee:ff",
                "device_reg_id": "reg-2",
            },
        }
    )
    assert observer.handled_since(
        "reg-2", dt_util.utcnow().timestamp()
    ) is not None


# -------------------- a full init alone is not a person (rule FRZ-17)

# Pairing open: what ZHA's Add Device page leaves on the signal while it
# is open, its own log relayed line by line.
PAIRING = {"type": "log_output", "log_entry": {"message": "permit"}}

_RIG_21_OCTOBER = (
    ("75e24b03455f8289abdc2f77b6202ab9", "a4:c1:38:00:00:00:00:01", "ZHA Test Device - mmWave R"),
    ("97bdcccf073c7ebc33adf6edd9ab8907", "b4:0e:06:0f:ff:e0:fc:6f", "ZHA Test Device - Motion"),
    ("bc44cc1d3262aefa97d23153188aff5a", "a4:c1:38:00:00:00:00:02", "ZHA Test Device - mmWave J"),
)


def _full_init(registry_id, ieee, name):
    return {
        "type": "device_fully_initialized",
        "device_info": {
            "ieee": ieee, "device_reg_id": registry_id,
            "user_given_name": name, "pairing_status": "CONFIGURED",
        },
    }


async def test_a_full_init_alone_after_a_restart_is_not_handled(
    hass: HomeAssistant, caplog
):
    """Seconds after Home Assistant restarts, ZHA can send a full init
    alone for devices nobody touched. Replayed, none is filed, nothing
    reaches the coordinator, and the log says why (rule FRZ-17)."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    with caplog.at_level(logging.DEBUG):
        for registry_id, ieee, name in _RIG_21_OCTOBER:
            observer._on_message(_full_init(registry_id, ieee, name))
    assert seen == []
    assert observer.handled == {}
    assert caplog.text.count("not counted as handled") == 3
    # Still counted as messages heard.
    assert observer.seen == 3


async def test_a_reconfigure_still_counts(hass: HomeAssistant):
    """A reconfigure sends raw, then the full init (rule FRZ-17)."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    registry_id, ieee, name = _RIG_21_OCTOBER[0]
    observer._on_message({"type": "raw_device_initialized", "ieee": ieee, "nwk": 1})
    observer._on_message(_full_init(registry_id, ieee, name))
    assert seen == [(registry_id, "device_fully_initialized")]


async def test_a_re_pair_counts_both_full_inits(hass: HomeAssistant):
    """A re-pair sends the join, then the full init twice, while
    pairing is open."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    registry_id, ieee, name = _RIG_21_OCTOBER[1]
    observer._on_message(PAIRING)
    observer._on_message({"type": "device_joined", "device_info": {"ieee": ieee}})
    observer._on_message(_full_init(registry_id, ieee, name))
    observer._on_message(_full_init(registry_id, ieee, name))
    assert seen == [(registry_id, "re-pair")] * 2


async def test_another_devices_join_explains_nothing(hass: HomeAssistant):
    """A join is matched by its address, never by its timing alone."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    observer._on_message(PAIRING)
    observer._on_message({"type": "device_joined", "device_info": {"ieee": "ff:ff"}})
    for registry_id, ieee, name in _RIG_21_OCTOBER:
        observer._on_message(_full_init(registry_id, ieee, name))
    assert seen == []


async def test_an_old_join_explains_nothing(hass: HomeAssistant, freezer):
    """A join longer ago than the window is not the same handling."""
    from custom_components.device_sentinel.const import ZHA_HANDLING_WINDOW_SECONDS

    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    registry_id, ieee, name = _RIG_21_OCTOBER[2]
    observer._on_message(PAIRING)
    observer._on_message({"type": "device_joined", "device_info": {"ieee": ieee}})
    freezer.tick(ZHA_HANDLING_WINDOW_SECONDS + 1)
    observer._on_message(_full_init(registry_id, ieee, name))
    assert seen == []


async def test_odd_addresses_never_count(hass: HomeAssistant):
    """No address, an empty one or a number: nothing to match, so a full
    init with one is a device setting itself up, never a person."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    for ieee in (None, "", 7, ["a"]):
        observer._on_message(PAIRING)
        observer._on_message({"type": "device_joined", "device_info": {"ieee": ieee}})
        observer._on_message(_full_init("reg-odd", ieee, "Odd"))
    assert seen == []



# ------------------------------- a device moving on its own is not a person


async def test_a_device_changing_its_address_is_not_handled(hass: HomeAssistant, caplog):
    """zigpy sends a join, then ZHA two full inits, when a known
    device turns up at a new network address, with nobody near it. With
    pairing closed it is the device, not a person (rule FRZ-17)."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    registry_id, ieee, name = _RIG_21_OCTOBER[1]
    with caplog.at_level(logging.DEBUG):
        observer._on_message({"type": "device_joined", "device_info": {"ieee": ieee}})
        observer._on_message(_full_init(registry_id, ieee, name))
        observer._on_message(_full_init(registry_id, ieee, name))
    assert seen == [] and observer.handled == {}
    assert "joined with pairing closed" in caplog.text


async def test_the_permit_action_opens_pairing_for_its_duration(hass: HomeAssistant, freezer):
    """zha.permit opens pairing for as long as it asks; a join after
    that is a device moving on its own."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    assert observer.async_start()
    registry_id, ieee, name = _RIG_21_OCTOBER[0]
    hass.bus.async_fire("call_service", {"domain": "zha", "service": "permit", "service_data": {"duration": 60}})
    await hass.async_block_till_done()
    observer._on_message({"type": "device_joined", "device_info": {"ieee": ieee}})
    observer._on_message(_full_init(registry_id, ieee, name))
    assert seen == [(registry_id, "re-pair")]
    freezer.tick(61)
    other_id, other_ieee, other_name = _RIG_21_OCTOBER[2]
    observer._on_message({"type": "device_joined", "device_info": {"ieee": other_ieee}})
    observer._on_message(_full_init(other_id, other_ieee, other_name))
    assert seen == [(registry_id, "re-pair")]
    # Another action opens nothing.
    hass.bus.async_fire("call_service", {"domain": "light", "service": "turn_on", "service_data": {"duration": 60}})
    await hass.async_block_till_done()
    observer._on_message({"type": "device_joined", "device_info": {"ieee": other_ieee}})
    observer._on_message(_full_init(other_id, other_ieee, other_name))
    assert len(seen) == 1
    observer.async_stop()


async def test_the_add_device_page_closes_after_its_last_line(hass: HomeAssistant, freezer):
    """The page relays the log while open; 254 seconds after the last
    line, pairing is closed whatever the page did."""
    from custom_components.device_sentinel.const import ZHA_PERMIT_LONGEST_SECONDS

    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    registry_id, ieee, name = _RIG_21_OCTOBER[0]
    observer._on_message(PAIRING)
    freezer.tick(ZHA_PERMIT_LONGEST_SECONDS + 1)
    observer._on_message({"type": "device_joined", "device_info": {"ieee": ieee}})
    observer._on_message(_full_init(registry_id, ieee, name))
    assert seen == []
    # The relay is not a message about a device, and is not counted.
    assert observer.seen == 2


async def test_a_slow_reconfigure_still_counts(hass: HomeAssistant, freezer):
    """A sleepy battery device can take minutes to configure; the raw
    init's window holds for fifteen."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    registry_id, ieee, name = _RIG_21_OCTOBER[2]
    observer._on_message({"type": "raw_device_initialized", "ieee": ieee, "nwk": 1})
    freezer.tick(600)
    observer._on_message(_full_init(registry_id, ieee, name))
    assert seen == [(registry_id, "device_fully_initialized")]


async def test_initialized_ends_the_handling(hass: HomeAssistant):
    """ZHA's last full init of a pairing says INITIALIZED; a full init
    after it is the device again, not the same handling."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    registry_id, ieee, name = _RIG_21_OCTOBER[1]
    observer._on_message(PAIRING)
    observer._on_message({"type": "device_joined", "device_info": {"ieee": ieee}})
    observer._on_message(_full_init(registry_id, ieee, name))
    done = _full_init(registry_id, ieee, name)
    done["device_info"]["pairing_status"] = "INITIALIZED"
    observer._on_message(done)
    observer._on_message(_full_init(registry_id, ieee, name))
    assert len(seen) == 2


async def test_begun_handlings_are_bounded(hass: HomeAssistant):
    from custom_components.device_sentinel.const import ZHA_BEGUN_KEPT

    observer = stack_zha.make_join_observer(hass)
    for n in range(ZHA_BEGUN_KEPT + 50):
        observer._on_message({"type": "raw_device_initialized", "ieee": f"00:{n:06x}", "nwk": n})
    assert len(observer._begun) == ZHA_BEGUN_KEPT
    assert "00:000000" not in observer._begun
