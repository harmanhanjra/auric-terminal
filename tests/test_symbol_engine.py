import asyncio
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from multi_engine import SymbolEngine


def make_engine(monkeypatch):
    import engine as strategies
    monkeypatch.setattr(strategies, 'signal', lambda *args: (1, 'test setup'))
    now = int(time.time())
    def rates(symbol, tf, start, count):
        seconds = 900 if tf == 15 else 3600
        end = now // seconds * seconds - (seconds if start else 0)
        return [dict(time=end-(count-1-i)*seconds, open=1+i*.0001,
                     close=1.0002+i*.0001, high=1.0008+i*.0001,
                     low=.9998+i*.0001, tick_volume=100) for i in range(count)]
    broker = NS(symbol_info=lambda _: NS(visible=True), copy_rates_from_pos=rates,
                symbol_info_tick=lambda _: NS(bid=1.1, ask=1.1001, time_msc=time.time()*1000),
                positions_get=lambda **kw: (), history_deals_get=lambda *args: ())
    executor = NS(submit=AsyncMock(return_value=NS(volume=.1, price=1.1, order=12)))
    obj = SymbolEngine('EURUSD', broker, {'ok': True}, 144021, True, 1, 500,
                       NS(add=lambda **kw: None), AsyncMock(), None, False,
                       {'M15': 15, 'H1': 60}, None, executor=executor)
    obj.config.update(enabled=True, timeframe='M15', rr=2)
    obj.kronos_confirm = False
    return obj, executor


def test_closed_bar_runs_once_through_shared_executor(monkeypatch):
    obj, executor = make_engine(monkeypatch)
    async def run():
        await obj._step()
        await obj._step()
    asyncio.run(run())
    assert executor.submit.await_count == 1
    assert obj.state['status'] == 'in_position'


def test_disarmed_engine_evaluates_without_submission(monkeypatch):
    obj, executor = make_engine(monkeypatch)
    obj.live_enabled = False
    asyncio.run(obj._step())
    assert executor.submit.await_count == 0
    assert obj.state['status'] == 'shadow'


def test_stale_quote_blocks_engine(monkeypatch):
    obj, executor = make_engine(monkeypatch)
    obj.mt5.symbol_info_tick = lambda _: NS(bid=1.1, ask=1.1001, time_msc=1)
    with pytest.raises(ValueError, match='stale'):
        asyncio.run(obj._step())
    assert executor.submit.await_count == 0


def test_enabled_ai_confirmation_fails_closed(monkeypatch):
    obj, _ = make_engine(monkeypatch)
    obj.kronos_confirm = True
    assert not obj._kronos_agrees(1)['ok']


def test_auto_strategy_is_chosen_from_regime(monkeypatch):
    import engine as strategies
    obj, executor = make_engine(monkeypatch)
    obj.config['strategy'] = 'auto'
    asyncio.run(obj._step())
    known = {sid for sid, _, _ in strategies.STRATEGIES}
    assert obj.state['effective_strategy'] in known
    assert obj.state['regime'] is not None
    assert obj.state['regime']['strategy'] == obj.state['effective_strategy']
    assert executor.submit.await_count == 1


def test_auto_pool_restricts_selection(monkeypatch):
    import engine as strategies
    obj, _ = make_engine(monkeypatch)
    obj.config['strategy'] = 'auto'
    monkeypatch.setenv('ENGINE_AUTO_POOL', 'bb_rsi')
    asyncio.run(obj._step())
    assert obj.state['effective_strategy'] == 'bb_rsi'
    assert 'bb_rsi' in {sid for sid, _, _ in strategies.STRATEGIES}
