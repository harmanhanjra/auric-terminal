from trade_quality import assess_setup


def bars(n=80):
    return [dict(open=100+i, close=100.5+i, low=99+i, high=102+i) for i in range(n)]


def test_conflicting_trend_blocks():
    assert not assess_setup(bars(), bars(), -1, 2, .1)['allowed']
    assert assess_setup(bars(), bars(), 1, 2, .1)['allowed']


def test_volatility_cost_and_reward_filters():
    shock = bars()
    shock[-1]['high'] += 20
    assert not assess_setup(shock, bars(), 1, 2, .1)['allowed']
    assert not assess_setup(bars(), bars(), 1, 2, 1)['allowed']
    assert not assess_setup(bars(), bars(), 1, .8, .1)['allowed']
