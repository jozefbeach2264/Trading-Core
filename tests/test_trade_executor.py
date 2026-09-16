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
    ex.exchange_info = {"filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                                    {"filterType": "MIN_NOTIONAL", "notional": "5"}]}
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


class _OkClient:
    def __init__(self, body='{"orderId": 42, "status": "FILLED"}'):
        self.body = body
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return httpx.Response(200, content=self.body, request=httpx.Request("POST", url))

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return httpx.Response(200, json=[{"asset": "BNB", "availableBalance": "1"}, {"asset": "USDT", "availableBalance": "1234.5"}],
                              request=httpx.Request("GET", url))


def _live_executor(config, client):
    config.dry_run_mode = False
    ms = make_market_state(config)
    ms.account_balance = 1000.0
    ex = TradeExecutor(config, ms, client)
    ex.memory_tracker = _Memory()
    ex.exchange_info = {"filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"}]}
    return ex


def test_order_side_is_the_exchange_enum_and_order_data_is_recorded(config):
    client = _OkClient()
    ex = _live_executor(config, client)
    run(ex._execute_live_trade({"direction": "LONG"}))
    params = client.calls[0][1]["params"]
    assert params["side"] == "BUY" and params["type"] == "MARKET" and "signature" in params
    assert "." not in params["quantity"] or len(params["quantity"].split(".")[1]) <= 3
    record = ex.memory_tracker.records[-1]["trade_data"]
    assert record["order_data"]["orderId"] == 42 and record.get("failed") is not True
    assert ex.open_position["direction"] == "LONG"
    run(ex._execute_live_trade({"direction": "SHORT"}))
    assert client.calls[1][1]["params"]["side"] == "SELL"


def test_non_json_2xx_body_is_recorded_not_raised(config):
    ex = _live_executor(config, _OkClient(body="<html>maintenance</html>"))
    run(ex._execute_live_trade({"direction": "LONG"}))
    assert "non-JSON" in ex.memory_tracker.records[-1]["trade_data"]["order_data"]["note"]


def test_missing_exchange_filters_or_dust_quantity_refuses_to_send(config):
    client = _OkClient()
    ex = _live_executor(config, client)
    ex.exchange_info = {}
    run(ex._execute_live_trade({"direction": "LONG"}))
    assert client.calls == [] and "filters unknown" in ex.memory_tracker.records[-1]["trade_data"]["reason"]
    ex = _live_executor(config, client)
    ex.market_state.account_balance = 1.0     # 0.25 USDT / 3000 → below a 0.001 step
    run(ex._execute_live_trade({"direction": "LONG"}))
    assert client.calls == [] and "step size" in ex.memory_tracker.records[-1]["trade_data"]["reason"]


def test_balance_is_fetched_from_the_exchange(config):
    ex = _live_executor(config, _OkClient())
    ex.market_state.account_balance = None
    run(ex._fetch_balance())
    assert ex.market_state.account_balance == 1234.5


def test_reduce_only_close_uses_the_opposite_side(config):
    client = _OkClient()
    ex = _live_executor(config, client)
    ex.open_position = {"direction": "LONG", "quantity": 0.05, "entry_price": 3000.0}
    run(ex.close_position(3010.0, reason="ROLLING5_COMPLETE"))
    params = client.calls[-1][1]["params"]
    assert params["side"] == "SELL" and params["reduceOnly"] == "true" and ex.open_position is None


def test_simulation_fee_is_a_percentage_and_close_realises_pnl(config, tmp_path):
    config.dry_run_mode = True
    config.simulation_state_file_path = str(tmp_path / "sim.json")
    config.simulation_initial_capital = 100.0
    config.risk_cap_percent = 0.25
    config.leverage = 200
    config.exchange_fee_rate_taker = 0.05
    ms = make_market_state(config)
    ex = TradeExecutor(config, ms, None)
    ex.memory_tracker = _Memory()
    run(ex._execute_simulated_trade({"direction": "LONG", "trade_type": "TrapX"}))
    state = ex._get_simulation_state()
    notional = 100.0 * 0.25 * 200                       # 5000 USDT
    assert abs(state["balance"] - (100.0 - notional * 0.0005)) < 1e-9
    assert state["balance"] > 0
    run(ex.close_position(ms.mark_price * 1.001, reason="test"))  # +0.1% → +5 USDT on 5000 notional
    state = ex._get_simulation_state()
    assert state["positions"] == {}
    assert abs(state["balance"] - (100.0 - 2 * notional * 0.0005 + 5.0)) < 1e-6
    assert state["history"][-1]["event"] == "close" and abs(state["history"][-1]["pnl"] - 5.0) < 1e-6
