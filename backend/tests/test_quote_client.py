from __future__ import annotations

from app.quote_client import TencentQuoteClient, to_quote_symbol


def test_to_quote_symbol_maps_a_share_symbols() -> None:
    assert to_quote_symbol("000021") == "sz000021"
    assert to_quote_symbol("sz000547") == "sz000547"
    assert to_quote_symbol("600519") == "sh600519"
    assert to_quote_symbol("sh600519") == "sh600519"


def test_tencent_quote_client_parses_daily_bars() -> None:
    payload = {
        "data": {
            "sz000021": {
                "day": [
                    ["2026-03-20", "32.520", "30.490", "32.700", "30.410", "1252330.000"],
                    ["2026-03-23", "29.210", "28.460", "29.990", "28.170", "990323.000"],
                ],
                "qt": {
                    "sz000021": ["51", "深科技", "000021"]
                },
            }
        }
    }

    rows = TencentQuoteClient._parse_kline_payload("000021", payload)

    assert len(rows) == 2
    assert rows[0].symbol == "000021"
    assert rows[0].name == "深科技"
    assert rows[0].trade_date == "2026-03-20"
    assert rows[0].open_price == 32.52
    assert rows[0].close_price == 30.49
    assert rows[1].trade_date == "2026-03-23"
    assert rows[1].high_price == 29.99
    assert rows[1].low_price == 28.17
