from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx

from .config import settings

TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="


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
        with httpx.Client(timeout=settings.quote_timeout_seconds) as client:
            response = client.get(url)
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
                updated_at = datetime.now()
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


def to_quote_symbol(symbol: str) -> str:
    if symbol.startswith(("sh", "sz", "bj")):
        return symbol
    if symbol.startswith(("4", "8", "92")):
        return f"bj{symbol}"
    return f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}"
