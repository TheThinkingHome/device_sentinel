# Tests for 0.19.2, the ZHA join observer (ruling #360).
#
# It is an instrument, so what the tests hold is mostly what it must
# NOT do: never claim a pairing window, never touch a verdict, never
# break a setup, and never fill the log with messages it is not for.

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
        # A removal since 0.19.2 (ruling #362): a person removing a
        # device is handling it, and a sleeping battery device never
        # hears the leave request, so it rejoins by itself at the
        # next start. Measured on 29 August.
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
    with caplog.at_level(logging.INFO):
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
        ("97bdcccf073c7ebc33adf6edd9ab8907", "device_fully_initialized")
    ]
    assert "was handled" in caplog.text
    assert "97bdcccf073c7ebc33adf6edd9ab8907" in observer.handled
    observer.async_stop()


async def test_a_message_without_a_registry_id_records_nothing(
    hass: HomeAssistant,
):
    """device_joined and raw_device_initialized carry the ieee and no
    registry id, measured 29 August. A device this integration cannot
    name is one it cannot file, and mapping an ieee by guesswork
    would attach a person's action to the wrong record."""
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
    rather than under device_info, measured 29 August. Both shapes
    are read rather than one assumed."""
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
    is, since 0.19.2."""
    observer = stack_zha.make_join_observer(hass)
    with caplog.at_level(logging.INFO):
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
    """Ruling #147: what cannot be understood is said, never guessed."""
    seen = []
    observer = stack_zha.make_join_observer(
        hass, lambda device_id, kind: seen.append((device_id, kind))
    )
    with caplog.at_level(logging.INFO):
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
    """The observer exists because pairing is unclaimed on ZHA, so
    nothing it sees may change that until the design is ruled."""
    reader = stack_zha.make_reader(MagicMock())
    assert reader.pairing_open is False
    observer = stack_zha.make_join_observer(hass)
    observer._on_message(
        {"type": "device_joined", "device_info": {"ieee": "x"}}
    )
    assert reader.pairing_open is False
    assert not hasattr(observer, "pairing_open")


def test_the_observer_is_reached_through_the_registry():
    """Ruling #218: the caller names no stack. My first wiring put
    STACK_ZHA and a direct stack_zha import into interventions.py,
    and test_the_stack_agnostic_files_name_no_stack caught it, which
    is exactly the job that test was written for."""
    from unittest.mock import MagicMock

    from custom_components.device_sentinel import stacks
    from custom_components.device_sentinel.const import (
        STACK_MATTER, STACK_Z2M, STACK_ZHA, STACK_ZWAVE,
    )

    hass = MagicMock()
    assert stacks.make_join_observer(STACK_ZHA, hass) is not None
    for stack in (STACK_Z2M, STACK_ZWAVE, STACK_MATTER, "no_such_stack"):
        assert stacks.make_join_observer(stack, hass) is None


# ------------------------------- the handling tag, added in 0.19.2


async def test_a_handling_is_filed_under_the_registry_id(
    hass: HomeAssistant,
):
    """Ruling #362. The full init carries device_reg_id, which is the
    key the rest of the integration files records under, so nothing
    has to be matched by name or address."""
    from custom_components.device_sentinel.const import (
        ZHA_HANDLED_TAIL_SECONDS,
    )

    observer = stack_zha.make_join_observer(hass)
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
