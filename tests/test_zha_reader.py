# Tests for 0.19.0, the ZHA coordinator reader (ruling #358).
#
# Every case here is a measurement from 28 August 2026 rather than an
# invention: the reload that lasts nine seconds, the outage that is
# still down at sixty, and the house with no ZHA at all.

from unittest.mock import MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.device_sentinel import stack_zha
from custom_components.device_sentinel.const import (
    BRIDGE_DOWN,
    BRIDGE_RUNNING,
    BRIDGE_UNKNOWN,
    ZHA_DOWN_DWELL_SECONDS,
)


def _hass_with(states):
    """A stand-in hass whose ZHA entries carry the given states."""
    fake = MagicMock()
    fake.config_entries.async_entries.return_value = [
        MagicMock(state=state) for state in states
    ]
    return fake


def _at(seconds):
    """Patch the clock the reader reads, in whole seconds."""
    return patch(
        "custom_components.device_sentinel.stack_zha.dt_util.utcnow",
        return_value=__import__("datetime").datetime.fromtimestamp(
            seconds, tz=__import__("datetime").timezone.utc
        ),
    )


def test_a_house_without_zha_reads_unknown():
    """No entry is not a fault: it is a house on another stack."""
    reader = stack_zha.make_reader(_hass_with([]))
    assert reader.state == BRIDGE_UNKNOWN
    assert reader.down_for is None


def test_a_loaded_entry_reads_running():
    reader = stack_zha.make_reader(
        _hass_with([ConfigEntryState.LOADED])
    )
    assert reader.state == BRIDGE_RUNNING
    assert reader.last_heard is not None


def test_a_nine_second_reload_never_reads_down():
    """The measured reload: every entity unavailable for nine seconds
    and back. It must never reach the reporting layer."""
    hass = _hass_with([ConfigEntryState.SETUP_IN_PROGRESS])
    reader = stack_zha.make_reader(hass)
    with _at(1000.0):
        assert reader.state == BRIDGE_RUNNING
    with _at(1005.0):
        assert reader.state == BRIDGE_RUNNING
    with _at(1009.0):
        assert reader.state == BRIDGE_RUNNING
    # The reload finishes and the entry loads again.
    hass.config_entries.async_entries.return_value = [
        MagicMock(state=ConfigEntryState.LOADED)
    ]
    with _at(1010.0):
        assert reader.state == BRIDGE_RUNNING
    assert reader.down_for is None


def test_an_outage_reads_down_once_the_dwell_passes():
    """The measured outage: the entry drops within a minute of the
    radio dying and stays down until power returns."""
    hass = _hass_with([ConfigEntryState.SETUP_RETRY])
    reader = stack_zha.make_reader(hass)
    with _at(2000.0):
        assert reader.state == BRIDGE_RUNNING
    with _at(2000.0 + ZHA_DOWN_DWELL_SECONDS - 1):
        assert reader.state == BRIDGE_RUNNING
    with _at(2000.0 + ZHA_DOWN_DWELL_SECONDS + 1):
        assert reader.state == BRIDGE_DOWN
    with _at(2000.0 + 300.0):
        assert reader.state == BRIDGE_DOWN
        assert reader.down_for == 300.0


def test_recovery_clears_the_dwell_immediately():
    """Recovery was whole or nothing on both runs, so the reader has
    nothing to wait for on the way back up."""
    hass = _hass_with([ConfigEntryState.SETUP_RETRY])
    reader = stack_zha.make_reader(hass)
    with _at(3000.0):
        reader.state
    with _at(3000.0 + ZHA_DOWN_DWELL_SECONDS + 1):
        assert reader.state == BRIDGE_DOWN
    hass.config_entries.async_entries.return_value = [
        MagicMock(state=ConfigEntryState.LOADED)
    ]
    with _at(3000.0 + ZHA_DOWN_DWELL_SECONDS + 2):
        assert reader.state == BRIDGE_RUNNING
    assert reader.down_for is None


def test_one_live_radio_among_several_is_not_an_outage():
    """A multi-radio house is up while any entry is loaded."""
    reader = stack_zha.make_reader(
        _hass_with(
            [ConfigEntryState.SETUP_RETRY, ConfigEntryState.LOADED]
        )
    )
    with _at(4000.0):
        assert reader.state == BRIDGE_RUNNING


def test_a_faulted_read_is_unknown_not_down():
    """Ruling #147: a reader that cannot answer never invents one."""
    hass = MagicMock()
    hass.config_entries.async_entries.side_effect = RuntimeError("boom")
    reader = stack_zha.make_reader(hass)
    assert reader.state == BRIDGE_UNKNOWN


def test_pairing_is_never_claimed():
    """Pairing is unmeasured on this stack, so it is a constant False
    rather than a guess: a wrong window discards a real silence."""
    reader = stack_zha.make_reader(_hass_with([ConfigEntryState.LOADED]))
    assert reader.pairing_open is False
    assert reader.pairing_active_within(300.0, 9999.0) is False


async def test_the_reader_starts_and_stops_clean(hass: HomeAssistant):
    """It holds no subscription, so starting and stopping is trivial,
    and a real hass with no ZHA reads unknown rather than failing."""
    reader = stack_zha.make_reader(hass)
    assert await reader.async_start() is True
    assert reader.state == BRIDGE_UNKNOWN
    assert reader.async_stop() is None
