from datetime import datetime, time, timezone

from conftest import run, make_market_state
import filters.time_of_day_filter as tod
from filters.time_of_day_filter import TimeOfDayFilter, parse_trade_windows


class _Clock:
    def __init__(self, hh, mm, ss):
        self._t = time(hh, mm, ss)

    def now(self, tz=None):
        return datetime(2026, 9, 16, self._t.hour, self._t.minute, self._t.second, tzinfo=timezone.utc)


def test_parse_is_strict():
    assert parse_trade_windows("") == set()
    assert parse_trade_windows("22:00-04:00,09:00-11:00") == {(time(22, 0), time(4, 0)), (time(9, 0), time(11, 0))}
    for bad in ("9am-5pm", "09:00", "09:00-11:00,foo"):
        try:
            parse_trade_windows(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should be rejected")


def test_default_window_covers_the_last_minute_of_the_day(config, monkeypatch):
    config.allowed_windows = "00:00-23:59"
    flt = TimeOfDayFilter(config)
    monkeypatch.setattr(tod, "datetime", _Clock(23, 59, 30))
    assert run(flt.generate_report(make_market_state(config)))["flag"] == "✅ Hard Pass"


def test_overnight_window(config, monkeypatch):
    config.allowed_windows = "22:00-04:00"
    flt = TimeOfDayFilter(config)
    monkeypatch.setattr(tod, "datetime", _Clock(1, 15, 0))
    assert run(flt.generate_report(make_market_state(config)))["flag"] == "✅ Hard Pass"
    monkeypatch.setattr(tod, "datetime", _Clock(12, 0, 0))
    assert run(flt.generate_report(make_market_state(config)))["flag"] == "❌ Block"
