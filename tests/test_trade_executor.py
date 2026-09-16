"""Live order path: a transport error (timeout, connection reset) is recorded and never escapes."""
import httpx

from conftest import run, make_market_state
from system_managers.trade_executor import TradeExecutor


class _Client:
    def __init__(self, exc):
        self.exc = exc
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        raise self.exc


class _Memory:
    def __init__(self):
        self.records = []

    async def update_memory(self, **kw):
        self.records.append(kw)


def _executor(config, exc):
    config.dry_run_mode = False
    ms = make_market_state(config)
    ms.account_balance = 1000.0
    client = _Client(exc)
    ex = TradeExecutor(config, ms, client)
    ex.memory_tracker = _Memory()
    return ex, client


def test_read_timeout_is_recorded_not_raised(config):
    ex, client = _executor(config, httpx.ReadTimeout("slow exchange"))
    run(ex._execute_live_trade({"direction": "LONG"}))
    assert client.calls and client.calls[0][1]["timeout"] == 5.0
    assert ex.memory_tracker.records[-1]["trade_data"]["failed"] is True


def test_connect_error_is_recorded_not_raised(config):
    ex, _ = _executor(config, httpx.ConnectError("refused"))
    run(ex._execute_live_trade({"direction": "SHORT"}))
    assert "transport error" in ex.memory_tracker.records[-1]["trade_data"]["reason"]
