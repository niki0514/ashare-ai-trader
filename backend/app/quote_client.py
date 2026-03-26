from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx

from .config import settings
from .time_utils import market_now

TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
DEFAULT_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass(slots=True)
class Quote:
    symbol: str
    name: str
    price: float
    previous_close: float
    open_price: float
    high_price: float
    low_price: float
    updated_at: datetime


@dataclass(slots=True)
class DailyBar:
    symbol: str
    name: str
    trade_date: str
    open_price: float
    close_price: float
    high_price: float
    low_price: float


class TencentQuoteClient:
    async def fetch_quotes(self, symbols: list[str]) -> list[Quote]:
        if not symbols:
            return []
        url = f"{TENCENT_QUOTE_URL}{','.join(symbols)}"
        async with httpx.AsyncClient(timeout=settings.quote_timeout_seconds) as client:
            response = await client.get(url)
            response.raise_for_status()
            text = response.text
        rows: list[Quote] = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            parsed = self._parse_line(line)
            if parsed:
                rows.append(parsed)
        return rows

    def fetch_quotes_sync(self, symbols: list[str]) -> list[Quote]:
        if not symbols:
            return []
        url = f"{TENCENT_QUOTE_URL}{','.join(symbols)}"
        text = ""
        last_error: Exception | None = None
        for _ in range(3):
            try:
                with httpx.Client(
                    timeout=settings.quote_timeout_seconds,
                    headers=DEFAULT_HTTP_HEADERS,
                ) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    text = response.text
                last_error = None
                break
            except Exception as exc:  # pragma: no cover
                last_error = exc
        if last_error is not None:
            raise last_error
        rows: list[Quote] = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            parsed = self._parse_line(line)
            if parsed:
                rows.append(parsed)
        return rows

    def fetch_daily_bars_sync(
        self,
        symbol: str,
        *,
        start_trade_date: str,
        end_trade_date: str,
    ) -> list[DailyBar]:
        normalized_symbol = to_quote_symbol(symbol)
        params = {
            "param": f"{normalized_symbol},day,{start_trade_date},{end_trade_date},640,bfq"
        }
        payload: dict = {}
        last_error: Exception | None = None
        for _ in range(3):
            try:
                with httpx.Client(
                    timeout=settings.quote_timeout_seconds,
                    headers=DEFAULT_HTTP_HEADERS,
                ) as client:
                    response = client.get(TENCENT_KLINE_URL, params=params)
                    response.raise_for_status()
                    payload = response.json()
                last_error = None
                break
            except Exception as exc:  # pragma: no cover
                last_error = exc
        if last_error is not None:
            raise last_error
        return self._parse_kline_payload(symbol, payload)

    @staticmethod
    def _parse_line(line: str) -> Quote | None:
        # v_sz000001="51~平安银行~000001~11.62~11.68~11.63~..."
        if not line.startswith("v_") or "=\"" not in line:
            return None
        try:
            left, right = line.split('="', 1)
            symbol = left.replace("v_", "")
            payload = right.rstrip('";')
            fields = payload.split("~")
            if len(fields) < 35:
                return None
            raw_time = fields[30] if fields[30] else ""
            if len(raw_time) >= 14 and raw_time.isdigit():
                # YYYYMMDDHHMMSS
                updated_at = datetime.strptime(raw_time, "%Y%m%d%H%M%S")
            else:
                updated_at = market_now()
            return Quote(
                symbol=symbol,
                name=fields[1] or symbol,
                price=float(fields[3] or 0),
                previous_close=float(fields[4] or 0),
                open_price=float(fields[5] or 0),
                high_price=float(fields[33] or 0),
                low_price=float(fields[34] or 0),
                updated_at=updated_at,
            )
        except Exception:
            return None

    @staticmethod
    def _parse_kline_payload(symbol: str, payload: dict) -> list[DailyBar]:
        normalized_symbol = to_quote_symbol(symbol)
        data = ((payload.get("data") or {}).get(normalized_symbol) or {})
        qt_data = data.get("qt") or {}
        qt_row = qt_data.get(normalized_symbol) or []
        name = qt_row[1] if len(qt_row) > 1 and qt_row[1] else symbol
        rows: list[DailyBar] = []
        for fields in data.get("day") or []:
            if len(fields) < 5:
                continue
            rows.append(
                DailyBar(
                    symbol=symbol,
                    name=name,
                    trade_date=fields[0],
                    open_price=float(fields[1] or 0),
                    close_price=float(fields[2] or 0),
                    high_price=float(fields[3] or 0),
                    low_price=float(fields[4] or 0),
                )
            )
        return rows


def to_quote_symbol(symbol: str) -> str:
    if symbol.startswith(("sh", "sz", "bj")):
        return symbol
    if symbol.startswith(("4", "8", "92")):
        return f"bj{symbol}"
    return f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}"


def from_quote_symbol(symbol: str) -> str:
    if symbol.startswith(("sh", "sz", "bj")):
        return symbol[2:]
    return symbol
