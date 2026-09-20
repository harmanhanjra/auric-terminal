from types import SimpleNamespace

import pytest

from mt5_data import checked_tick, checked_bars


@pytest.mark.parametrize("bid,ask,stamp", [(0, 2, 100000), (2, 1, 100000), (float('nan'), 2, 100000), (1, 2, 1000), (1, 2, 200000)])
def test_bad_ticks_fail_closed(bid, ask, stamp):
    with pytest.raises(ValueError):
        checked_tick(SimpleNamespace(bid=bid, ask=ask, time_msc=stamp), now=100)


def test_tick_preserves_broker_timestamp():
    assert checked_tick(SimpleNamespace(bid=1, ask=2, time_msc=99000), now=100) == (1, 2, 99000)


def test_duplicate_and_invalid_bars_rejected():
    row = dict(time=10, open=2, high=3, low=1, close=2, tick_volume=1)
    with pytest.raises(ValueError):
        checked_bars([row, row], minimum=2)
    with pytest.raises(ValueError):
        checked_bars([{**row, 'high': 1}], minimum=1)
