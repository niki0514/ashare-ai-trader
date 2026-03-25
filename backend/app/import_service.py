from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
import re

from sqlalchemy.orm import Session

from .models import ImportBatchStatus, OrderStatus, ValidationStatus
from .quote_client import TencentQuoteClient, to_quote_symbol
from .repositories import MarketDataRepository, OrderRepository, PortfolioRepository


SYMBOL_PATTERN = re.compile(r"^\d{6}$")


class ImportService:
    def __init__(self, session: Session):
        self.session = session
        self.order_repo = OrderRepository(session)
        self.portfolio_repo = PortfolioRepository(session)
        self.market_repo = MarketDataRepository(session)
        self.quote_client = TencentQuoteClient()

    def apply_symbol_format_checks(self, rows: list[dict]) -> list[dict]:
        output: list[dict] = []
        for row in rows:
            next_row = dict(row)
            symbol = str(row["symbol"]).strip().upper()
            next_row["symbol"] = symbol
            if row["validationStatus"] != "ERROR" and not SYMBOL_PATTERN.fullmatch(symbol):
                next_row["validationStatus"] = "ERROR"
                next_row["validationMessage"] = "股票代码必须为 6 位数字"
            output.append(next_row)
        return output

    @staticmethod
    def _symbol_from_quote_symbol(symbol: str) -> str:
        if symbol.startswith(("sh", "sz", "bj")):
            return symbol[2:]
        return symbol

    @staticmethod
    def _limit_ratio(symbol: str, symbol_name: str | None) -> Decimal:
        normalized_name = (symbol_name or "").upper()
        if "ST" in normalized_name:
            return Decimal("0.05")
        if symbol.startswith(("300", "301", "688", "689")):
            return Decimal("0.20")
        if symbol.startswith(("4", "8", "92")):
            return Decimal("0.30")
        return Decimal("0.10")

    @staticmethod
    def _round_cny(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def _price_reference_by_symbol(self, target_trade_date: str, symbols: list[str]) -> dict[str, dict[str, float | str]]:
        references: dict[str, dict[str, float | str]] = {}
        missing_symbols: list[str] = []
        for symbol in symbols:
            latest_eod = self.market_repo.latest_eod_price(symbol, trade_date_lte=target_trade_date)
            if latest_eod and latest_eod.close_price > 0:
                references[symbol] = {
                    "name": latest_eod.symbol_name or symbol,
                    "referenceClose": latest_eod.close_price,
                }
                continue

            quote = self.market_repo.latest_intraday_quote(to_quote_symbol(symbol))
            if quote and quote.previous_close > 0:
                references[symbol] = {
                    "name": quote.symbol_name or symbol,
                    "referenceClose": quote.previous_close,
                }
                continue

            missing_symbols.append(symbol)

        if missing_symbols:
            try:
                fetched_rows = self.quote_client.fetch_quotes_sync(
                    [to_quote_symbol(symbol) for symbol in missing_symbols]
                )
            except Exception:
                fetched_rows = []

            for row in fetched_rows:
                quoted_at = row.updated_at
                self.market_repo.append_intraday_quote(
                    {
                        "symbol": row.symbol,
                        "name": row.name,
                        "trade_date": quoted_at.date().isoformat(),
                        "price": row.price,
                        "open": row.open_price,
                        "previousClose": row.previous_close,
                        "high": row.high_price,
                        "low": row.low_price,
                        "quoted_at": quoted_at,
                        "source": "tencent_preview_validation",
                    }
                )
                symbol = self._symbol_from_quote_symbol(row.symbol)
                if row.previous_close > 0:
                    references[symbol] = {
                        "name": row.name or symbol,
                        "referenceClose": row.previous_close,
                    }

        return references

    def apply_price_limit_checks(self, target_trade_date: str, rows: list[dict]) -> list[dict]:
        symbols = sorted(
            {
                row["symbol"]
                for row in rows
                if row["validationStatus"] != "ERROR" and SYMBOL_PATTERN.fullmatch(str(row["symbol"]))
            }
        )
        references = self._price_reference_by_symbol(target_trade_date, symbols)
        output: list[dict] = []
        for row in rows:
            next_row = dict(row)
            if row["validationStatus"] != "ERROR":
                symbol = str(row["symbol"])
                reference = references.get(symbol)
                if not reference:
                    next_row["validationStatus"] = "WARNING"
                    next_row["validationMessage"] = "暂未获取到昨收盘口径，未校验涨跌停区间"
                else:
                    reference_close = Decimal(str(reference["referenceClose"]))
                    ratio = self._limit_ratio(symbol, str(reference.get("name", "")))
                    lower = self._round_cny(reference_close * (Decimal("1") - ratio))
                    upper = self._round_cny(reference_close * (Decimal("1") + ratio))
                    price = Decimal(str(row["price"]))
                    if price < lower or price > upper:
                        next_row["validationStatus"] = "ERROR"
                        next_row["validationMessage"] = (
                            f"按昨收 {reference_close:.2f} 计算，涨跌停区间为 {lower:.2f} - {upper:.2f}，当前委托价 {price:.2f} 超出范围"
                        )
            output.append(next_row)
        return output

    def _active_orders(self, user_id: str, target_trade_date: str, mode: str):
        orders = self.order_repo.list_orders(
            user_id,
            statuses=[OrderStatus.confirmed, OrderStatus.pending, OrderStatus.triggered],
        )
        if mode == "OVERWRITE":
            return [order for order in orders if order.trade_date != target_trade_date]
        return orders

    def apply_sell_conflict_checks(
        self,
        user_id: str,
        target_trade_date: str,
        mode: str,
        rows: list[dict],
    ) -> list[dict]:
        sellable_by_symbol: dict[str, int] = defaultdict(int)
        for lot in self.portfolio_repo.open_lots(user_id):
            projected_sellable = lot.remaining_shares if lot.opened_date < target_trade_date else lot.sellable_shares
            sellable_by_symbol[lot.symbol] += projected_sellable

        reserved_by_symbol: dict[str, int] = defaultdict(int)
        for order in self._active_orders(user_id, target_trade_date, mode):
            if order.side.value == "SELL":
                reserved_by_symbol[order.symbol] += order.shares

        reserved_lots: dict[str, int] = {}
        output: list[dict] = []
        for row in rows:
            next_row = dict(row)
            if row["side"] == "SELL" and row["validationStatus"] != "ERROR":
                shares = int(row["lots"]) * 100
                symbol = row["symbol"]
                batch_reserved = reserved_lots.get(symbol, 0)
                sellable = sellable_by_symbol.get(symbol, 0)
                reserved = reserved_by_symbol.get(symbol, 0)
                available = max(0, sellable - reserved)
                if sellable == 0:
                    next_row["validationStatus"] = "ERROR"
                    next_row["validationMessage"] = "当前无可卖仓位"
                elif shares > sellable:
                    next_row["validationStatus"] = "ERROR"
                    next_row["validationMessage"] = (
                        f"当前可卖仓位仅 {sellable // 100} 手（{sellable} 股），无法卖出 {shares // 100} 手"
                    )
                elif reserved >= sellable or available == 0:
                    next_row["validationStatus"] = "ERROR"
                    next_row["validationMessage"] = (
                        f"当前可卖仓位共 {sellable // 100} 手，已被其他卖单全部占用"
                    )
                elif shares > available:
                    next_row["validationStatus"] = "ERROR"
                    next_row["validationMessage"] = (
                        f"当前剩余可卖仅 {available // 100} 手（{available} 股），另有 {reserved // 100} 手已被已有挂单占用"
                    )
                elif batch_reserved + shares > available:
                    next_row["validationStatus"] = "WARNING"
                    next_row["validationMessage"] = (
                        f"本批卖单累计将超出剩余可卖，当前剩余可卖 {available // 100} 手，前序已占用 {batch_reserved // 100} 手"
                    )
                reserved_lots[symbol] = batch_reserved + shares
            output.append(next_row)
        return output

    def apply_buy_cash_checks(
        self,
        user_id: str,
        target_trade_date: str,
        mode: str,
        rows: list[dict],
    ) -> list[dict]:
        latest_cash = self.portfolio_repo.latest_cash(user_id)
        available_cash = latest_cash.balance_after if latest_cash else 0.0
        active_buy_amount = 0.0
        for order in self._active_orders(user_id, target_trade_date, mode):
            if order.side.value == "BUY":
                active_buy_amount += order.limit_price * order.shares

        batch_buy_amount = 0.0
        output: list[dict] = []
        for row in rows:
            next_row = dict(row)
            if row["side"] == "BUY" and row["validationStatus"] != "ERROR":
                row_amount = float(row["price"]) * int(row["lots"]) * 100
                reserved_amount = active_buy_amount + batch_buy_amount
                remaining_cash = max(0.0, available_cash - reserved_amount)
                if row_amount > available_cash:
                    next_row["validationStatus"] = "ERROR"
                    next_row["validationMessage"] = (
                        f"按委托价估算需 {row_amount:.2f} 元，当前可用现金仅 {available_cash:.2f} 元"
                    )
                elif row_amount > remaining_cash:
                    next_row["validationStatus"] = "WARNING"
                    next_row["validationMessage"] = (
                        f"与现有/本批买单合计后将超出可用现金，当前剩余可用 {remaining_cash:.2f} 元"
                    )
                batch_buy_amount += row_amount
            output.append(next_row)
        return output

    def apply_preview_checks(
        self,
        user_id: str,
        target_trade_date: str,
        mode: str,
        rows: list[dict],
    ) -> list[dict]:
        checked_rows = self.apply_symbol_format_checks(rows)
        checked_rows = self.apply_price_limit_checks(target_trade_date, checked_rows)
        checked_rows = self.apply_sell_conflict_checks(user_id, target_trade_date, mode, checked_rows)
        return self.apply_buy_cash_checks(user_id, target_trade_date, mode, checked_rows)

    def _rows_from_batch(self, batch) -> list[dict]:
        rows: list[dict] = []
        for item in sorted(batch.items, key=lambda value: value.row_number):
            rows.append(
                {
                    "rowNumber": item.row_number,
                    "tradeDate": batch.target_trade_date,
                    "symbol": item.symbol,
                    "side": item.side.value,
                    "price": item.limit_price,
                    "lots": item.lots,
                    "validity": item.validity.value,
                    "validationStatus": item.validation_status.value,
                    "validationMessage": item.validation_message or "校验通过",
                }
            )
        return rows

    def _update_batch_validation(self, batch, rows: list[dict]) -> None:
        rows_by_number = {row["rowNumber"]: row for row in rows}
        for item in batch.items:
            latest = rows_by_number[item.row_number]
            item.validation_status = ValidationStatus(latest["validationStatus"])
            item.validation_message = latest["validationMessage"]
        self.session.flush()

    def create_import_preview(
        self,
        *,
        user_id: str,
        target_trade_date: str,
        source_type: str,
        file_name: str | None,
        mode: str,
        rows: list[dict],
    ) -> dict:
        checked_rows = self.apply_preview_checks(user_id, target_trade_date, mode, rows)
        preview_rows = [{**row, "tradeDate": target_trade_date} for row in checked_rows]
        batch = self.order_repo.create_import_batch(
            user_id=user_id,
            target_trade_date=target_trade_date,
            source_type=source_type,
            file_name=file_name,
            mode=mode,
            rows=checked_rows,
        )
        return {
            "batchId": batch.id,
            "targetTradeDate": target_trade_date,
            "fileName": file_name,
            "sourceType": source_type,
            "rows": preview_rows,
        }

    def commit_import_batch(self, user_id: str, batch_id: str, mode: str) -> dict:
        batch = self.order_repo.get_import_batch(batch_id)
        if not batch or batch.user_id != user_id:
            raise ValueError("Import batch not found")
        if batch.status == ImportBatchStatus.COMMITTED:
            raise ValueError("Import batch already committed")
        revalidated_rows = self.apply_preview_checks(
            user_id,
            batch.target_trade_date,
            mode,
            self._rows_from_batch(batch),
        )
        self._update_batch_validation(batch, revalidated_rows)
        if mode != "DRAFT" and any(row["validationStatus"] == "ERROR" for row in revalidated_rows):
            raise ValueError("导入批次校验已变化，请重新校验后再提交")
        imported = self.order_repo.commit_import_batch(batch, mode)
        return {
            "batchId": batch.id,
            "targetTradeDate": batch.target_trade_date,
            "mode": mode,
            "importedCount": imported,
        }
