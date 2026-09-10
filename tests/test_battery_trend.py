"""The battery trend: nested windows, earlier periods, and the reading.

The projection has always been drawn from a seven day slope, which
says what a cell is doing now and cannot say whether that is new.
These are the tests for the two windows and the run of earlier
periods that answer it, and for the rule that decides what to call
the shape (ruling #395).

Every series here is either taken from the reference fleet or built
to a shape it demonstrated.
"""

from __future__ import annotations

from custom_components.device_sentinel.const import (
    TREND_ACCELERATING,
    TREND_DISAGREE,
    TREND_JUST_STARTED,
    TREND_STABILIZED,
    TREND_STEADY,
    TREND_TOO_NEW,
)
from custom_components.device_sentinel.report_battery import (
    BatteryReportMixin,
)

TREND = BatteryReportMixin()


def _falling(days: int, per_day: float, start: float = 90.0) -> list[float]:
    return [start - per_day * i for i in range(days)]


# ----------------------------------------------- the spread


def test_days_that_agree_report_a_small_spread():
    """A clean decline: every pair of days says the same thing."""
    assert TREND._battery_spread(_falling(7, 1.0)) == 0.0


def test_a_sag_and_a_recovery_widens_the_spread():
    """The shape Theil-Sen exists for still shows in the spread.

    The reference fleet's proof device dropped ten points and came
    back eight and a half the next day. The median ignores that, and
    should; the spread is where it becomes visible.
    """
    steady = TREND._battery_spread([90, 89, 88, 87, 86, 85, 84])
    sagged = TREND._battery_spread([90, 89, 79, 87.5, 86, 85, 84])

    assert sagged > steady


def test_a_spread_needs_four_slopes():
    """Three readings cannot be quartered."""
    assert TREND._battery_spread([90, 89]) is None


# ----------------------------------------------- the windows


def test_each_window_reads_only_its_own_days():
    """A cell flat for a month and falling this week.

    Thirty days reads exactly flat, which is the median doing its
    job: most pairs of days in that window are both from the
    plateau, and a handful of falling pairs cannot move a median.
    Seven days reads the fall. That gap between the two windows is
    the whole signature of a decline that has just begun.
    """
    series = [90.0] * 30 + _falling(7, 0.5, 90.0)

    windows = TREND._battery_windows(series)

    assert windows[7] < 0
    assert windows[30] == 0.0
    assert windows[7] < windows[30]


def test_a_window_with_too_few_days_is_absent():
    """Ten days of history cannot fill a thirty day window."""
    windows = TREND._battery_windows(_falling(10, 0.5))

    assert windows[7] is not None
    assert windows[14] is None
    assert windows[30] is None


# ----------------------------------------------- earlier periods


def test_the_first_ninety_days_are_read_a_month_at_a_time():
    series = _falling(120, 0.2)

    blocks = TREND._battery_blocks(series)

    assert [(start, end) for start, end, _ in blocks] == [
        (120, 90),
        (90, 60),
        (60, 30),
    ]


def test_older_history_is_read_a_quarter_at_a_time():
    """A year is five periods, not eleven."""
    blocks = TREND._battery_blocks(_falling(360, 0.1))

    assert len(blocks) == 5
    assert blocks[0][0] == 360


def test_a_period_covers_itself_and_nothing_since():
    """A cell that fell hard, then held.

    A running total back from today averages the fall and the
    plateau together and reports neither. The period says what
    happened in it.
    """
    series = _falling(30, 1.0, 90.0) + [60.0] * 30

    blocks = TREND._battery_blocks(series)

    assert len(blocks) == 1
    assert blocks[0][2] < -0.9


def test_a_stub_of_days_is_not_reported_as_a_period():
    """Four days left over say nothing worth a column."""
    assert TREND._battery_blocks(_falling(34, 0.5)) == []


# ----------------------------------------------- the reading


def test_a_cell_that_is_not_falling_has_no_reading():
    assert TREND._battery_reading(TREND._battery_windows([90.0] * 40), 40) == ""


def test_a_new_install_is_told_only_that_a_cell_is_falling():
    """Three weeks of history buys no comparison."""
    series = _falling(10, 0.5)

    assert (
        TREND._battery_reading(TREND._battery_windows(series), len(series))
        == TREND_TOO_NEW
    )


def test_windows_that_steepen_at_every_step_are_accelerating():
    """Motion Master Shower 2 on the reference fleet, 10 September."""
    windows = {30: -0.025, 14: -0.056, 7: -0.167}

    assert TREND._battery_reading(windows, 51) == TREND_ACCELERATING


def test_a_flat_month_does_not_stop_an_acceleration_being_named():
    """Window Living Room Left on the reference fleet, 10 September.

    Thirty days reads positive because the recent fall has not yet
    outweighed what came before it. The three windows still steepen
    at every step, and that is what acceleration is.
    """
    windows = {30: +0.028, 14: +0.000, 7: -0.100}

    assert TREND._battery_reading(windows, 51) == TREND_ACCELERATING


def test_a_month_inside_the_rounding_band_is_not_a_baseline():
    """Door 2nd Bedroom on the reference fleet, 10 September.

    Thirty days reads -0.025, which a cell reporting in half point
    steps produces from rounding alone. There is no decline there to
    accelerate from, so the cell is level across the month and
    falling this week, and that is what it is called.
    """
    windows = {30: -0.025, 14: +0.000, 7: -0.100}

    assert TREND._battery_reading(windows, 51) == TREND_JUST_STARTED


def test_a_middle_window_that_contradicts_a_real_decline_is_not_overruled():
    """A month of genuine decline, with the fortnight disagreeing.

    Seven days is far steeper than thirty, which two numbers alone
    would call acceleration. Fourteen sits between them reading
    shallower than both, so the three do not form a progression and
    the reading says so rather than asserting one.
    """
    windows = {30: -0.200, 14: -0.050, 7: -0.300}

    assert TREND._battery_reading(windows, 51) == TREND_DISAGREE


def test_a_progression_too_small_to_matter_is_steady():
    """A cell drifting down at a tenth of a point a day.

    Every window is steeper than the one before it, so the
    progression holds. The gap between seven and thirty is eight
    thousandths, which is not a change in pace.
    """
    windows = {30: -0.100, 14: -0.104, 7: -0.108}

    assert TREND._battery_reading(windows, 51) == TREND_STEADY


def test_a_fall_with_no_negative_month_behind_it_is_new():
    """Ragged, so not an acceleration, and no baseline to divide by."""
    windows = {30: +0.010, 14: -0.200, 7: -0.100}

    assert TREND._battery_reading(windows, 51) == TREND_JUST_STARTED


def test_a_decline_that_has_eased_is_stabilized():
    windows = {30: -0.400, 14: -0.300, 7: -0.100}

    assert TREND._battery_reading(windows, 51) == TREND_STABILIZED


def test_a_decline_holding_its_pace_is_steady():
    windows = {30: -0.100, 14: -0.100, 7: -0.100}

    assert TREND._battery_reading(windows, 51) == TREND_STEADY
