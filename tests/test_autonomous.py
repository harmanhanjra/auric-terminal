import asyncio
import time
from types import SimpleNamespace as NS

import pytest

from autonomous import AutonomousExecutor
from execution_v2 import ExecutionLedger


class Broker:
    ORDER_TYPE_BUY = POSITION_TYPE_BUY = ORDER_FILLING_FOK = 0
    ORDER_TYPE_SELL = ORDER_FILLING_IOC = TRADE_ACTION_DEAL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    def __init__(self):
        self.sent = []
        self.rows = ()
        self.tick = NS(bid=1.1, ask=1.1001, time_msc=time.time()*1000)
        self.preflight = NS(retcode=0)
        self.response = NS(retcode=10009, order=12, price=1.1001, volume=0.05)
    def terminal_info(self): return NS(connected=True, trade_allowed=True, tradeapi_disabled=False)
    def account_info(self): return NS(equity=10000, margin_free=10000, login=1, server='test', trade_allowed=True, trade_expert=True)
    def symbol_info(self, symbol): return NS(trade_mode=4, point=.00001, digits=5, trade_tick_size=.00001, volume_min=.01, volume_max=100, volume_step=.01, trade_stops_level=10, filling_mode=2)
    def symbol_info_tick(self, symbol): return self.tick
    def positions_get(self): return self.rows
    def orders_get(self): return ()
    def history_deals_get(self, *args): return ()
    def order_calc_profit(self, typ, symbol, volume, price, stop): return -abs(price-stop)*100000*volume
    def order_calc_margin(self, *args): return 10
    def order_check(self, request): return self.preflight
    def order_send(self, request):
        self.sent.append(request)
        return self.response


def setup(tmp_path):
    broker = Broker()
    ledger = ExecutionLedger(str(tmp_path/'execution.db'))
    executor = AutonomousExecutor(broker, ledger, 144021, lambda _: {'allowed': True})
    engine = NS(symbol='EURUSD', config={'rr':2, 'risk_pct':.5, 'timeframe':'M15', 'strategy':'test'},
                max_spread_points=30, max_lot=1, max_daily_loss=500,
                journal=NS(add=lambda **kw: None), risk=NS(kill=lambda: None))
    return broker, executor, engine


def test_entry_is_sized_in_account_currency_and_restart_deduplicated(tmp_path):
    broker, executor, engine = setup(tmp_path)
    asyncio.run(executor.submit(engine, 1, .001, 123))
    assert len(broker.sent) == 1
    assert broker.sent[0]['sl'] == pytest.approx(1.0991)
    assert broker.sent[0]['volume'] * 100 <= 50 + .001
    recreated = AutonomousExecutor(broker, executor.ledger, 144021, lambda _: {'allowed': True})
    with pytest.raises(ValueError, match='already submitted'):
        asyncio.run(recreated.submit(engine, 1, .001, 123))
    assert len(broker.sent) == 1


@pytest.mark.parametrize('failure', ['stale', 'missing_positions', 'preflight', 'minimum_lot'])
def test_failures_never_send(tmp_path, failure):
    broker, executor, engine = setup(tmp_path)
    if failure == 'stale': broker.tick.time_msc = 1
    if failure == 'missing_positions': broker.rows = None
    if failure == 'preflight': broker.preflight = None
    if failure == 'minimum_lot': engine.config['risk_pct'] = .00001
    with pytest.raises(ValueError):
        asyncio.run(executor.submit(engine, 1, .001, 123))
    assert broker.sent == []


def test_unknown_send_is_not_retried(tmp_path):
    broker, executor, engine = setup(tmp_path)
    broker.response = None
    with pytest.raises(ValueError, match='reconciliation'):
        asyncio.run(executor.submit(engine, 1, .001, 123))
    with pytest.raises(ValueError, match='reconciliation'):
        asyncio.run(executor.submit(engine, 1, .001, 123))
    assert len(broker.sent) == 1


def test_account_loss_and_missing_protection_block(tmp_path):
    broker, executor, engine = setup(tmp_path)
    broker.rows = (NS(symbol='XAUUSD', profit=-501, swap=0),)
    with pytest.raises(ValueError, match='daily loss'):
        asyncio.run(executor.submit(engine, 1, .001, 123))
    broker.rows = (NS(symbol='XAUUSD', profit=0, swap=0, sl=0),)
    with pytest.raises(ValueError, match='unprotected'):
        asyncio.run(executor.submit(engine, 1, .001, 123))
    assert not broker.sent


def test_drawdown_halt_survives_restart(tmp_path):
    broker, executor, engine = setup(tmp_path)
    executor.ledger.state('risk:1:test', {'peak': 20000, 'halted': False})
    with pytest.raises(ValueError, match='drawdown'):
        asyncio.run(executor.submit(engine, 1, .001, 123))
    assert executor.ledger.state('risk:1:test')['halted']
    assert not broker.sent
