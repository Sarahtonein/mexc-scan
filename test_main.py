import importlib.util
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("main_module", Path(__file__).with_name("main.py"))
main_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main_module)


def test_is_stock_symbol():
    assert main_module.is_stock_symbol("SHELSTOCK_USDT") is True
    assert main_module.is_stock_symbol("BTCUSDT") is False
    assert main_module.is_stock_symbol("stock_usdt") is True


def test_format_aest_time():
    dt = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    assert main_module.format_aest_time(dt) == "2026-10-12 22:00:00 AEST"


def test_detect_regular_bearish_divergence():
    prices = [90, 92, 94, 96, 98, 100, 103, 106, 109, 112, 115, 118, 120, 122, 124, 126, 128, 130, 128, 126, 123, 120, 118, 116, 118, 124, 130, 128, 135, 140, 138, 136]
    rsi_values = [60, 61, 63, 64, 65, 66, 68, 69, 70, 72, 74, 76, 80, 82, 79, 75, 70, 82, 80, 78, 76, 74, 72, 70, 68, 66, 60, 58, 56, 54, 55, 52]

    assert main_module.detect_bearish_divergence(prices, rsi_values) == "regular"


def test_detect_hidden_bearish_divergence():
    prices = [100, 98, 96, 92, 90, 88, 82, 80, 84, 78, 76, 74, 70, 68, 66, 64, 62, 60, 58, 56, 59, 62, 60, 58, 57, 59, 60]
    rsi_values = [62, 60, 58, 56, 54, 52, 48, 42, 46, 44, 42, 40, 36, 34, 32, 30, 28, 26, 24, 22, 38, 46, 52, 58, 70, 68, 66]

    assert main_module.detect_bearish_divergence(prices, rsi_values) == "hidden"


def test_divergence_monitor_window_ends_after_48_hours():
    now = datetime.now(timezone.utc)
    started = now - __import__("datetime").timedelta(hours=48)
    assert main_module.is_divergence_monitor_active(started, now) is False
    assert main_module.is_divergence_monitor_active(started + __import__("datetime").timedelta(hours=47), now) is True


def test_check_spot_bearish_divergence_sends_post_alert(monkeypatch):
    prices = [90, 92, 94, 96, 98, 100, 103, 106, 109, 112, 115, 118, 120, 122, 124, 126, 128, 130, 128, 126, 123, 120, 118, 116, 118, 124, 130, 128, 135, 140, 138, 136]
    candles = [[0, 0, 0, 0, price, 0] for price in prices]
    rsi_values = [60, 61, 63, 64, 65, 66, 68, 69, 70, 72, 74, 76, 80, 82, 79, 75, 70, 82, 80, 78, 76, 74, 72, 70, 68, 66, 60, 58, 56, 54, 55, 52]

    monkeypatch.setattr(main_module, "fetch_spot_klines", lambda symbol, interval="15m", limit=200: candles)
    monkeypatch.setattr(main_module, "calculate_rsi", lambda closes, period=14: rsi_values)
    monkeypatch.setattr(main_module, "get_token_price", lambda symbol: 150.0)
    monkeypatch.setattr(main_module, "DISCORD_WEBHOOK_URL", None)
    monkeypatch.setattr(main_module, "POST_URL", "https://example.com/hook")

    seen = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

    def fake_post(url, json=None, timeout=15):
        seen["url"] = url
        seen["payload"] = json
        return FakeResponse()

    monkeypatch.setattr(main_module.requests, "post", fake_post)

    assert main_module.check_spot_bearish_divergence("NEWCOIN") == "regular"
    assert seen["payload"]["event"] == "bearish_divergence"
    assert seen["payload"]["timeframe"] == "15m"
