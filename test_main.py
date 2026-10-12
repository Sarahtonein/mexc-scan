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
