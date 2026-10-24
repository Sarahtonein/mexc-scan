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
    prices = [100, 110, 120, 130, 125, 128, 135]
    rsi_values = [30, 40, 55, 65, 60, 58, 50]

    assert main_module.detect_bearish_divergence(prices, rsi_values) == "regular"


def test_detect_hidden_bearish_divergence():
    prices = [100, 96, 92, 90, 88, 85, 83, 81]
    rsi_values = [70, 65, 60, 50, 56, 58, 62, 66]

    assert main_module.detect_bearish_divergence(prices, rsi_values) == "hidden"


def test_divergence_monitor_window_ends_after_48_hours():
    now = datetime.now(timezone.utc)
    started = now - __import__("datetime").timedelta(hours=48)
    assert main_module.is_divergence_monitor_active(started, now) is False
    assert main_module.is_divergence_monitor_active(started + __import__("datetime").timedelta(hours=47), now) is True
