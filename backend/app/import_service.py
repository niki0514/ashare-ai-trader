from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import re

from sqlalchemy.orm import Session

from .market import market_clock, previous_trading_date
from .market_prices import trade_date_of
from .models import ImportBatchStatus, OrderStatus, ValidationStatus
from .quote_client import TencentQuoteClient, from_quote_symbol, to_quote_symbol
from .repositories import (
    ACTIVE_ORDER_STATUSES,
    MarketDataRepository,
    OrderRepository,
    PortfolioRepository,
    is_order_effective_on_trade_date,
    projected_lot_sellable_shares,
)


SYMBOL_PATTERN = re.compile(r"^\d{6}$")
WARNING_CODE_MISSING_REFERENCE_CLOSE = "MISSING_REFERENCE_CLOSE"
WARNING_CODE_OVERWRITE_ACTIVE_ORDERS = "OVERWRITE_ACTIVE_ORDERS"


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
                next_row.pop("validationCode", None)
            output.append(next_row)
        return output

    def apply_trade_date_checks(self, target_trade_date: str, rows: list[dict]) -> list[dict]:
        trade_date_error = market_clock.validate_import_trade_date(target_trade_date)
        if not trade_date_error:
            return rows

        output: list[dict] = []
        for row in rows:
            next_row = dict(row)
            if row["validationStatus"] != "ERROR":
                next_row["validationStatus"] = "ERROR"
                next_row["validationMessage"] = trade_date_error
                next_row.pop("validationCode", None)
            output.append(next_row)
        return output

    @staticmethod
    def _warning_confirmation_payload(
        *,
        user_id: str,
        target_trade_date: str,
        mode: str,
        items: list[dict],
    ) -> dict:
        if not items:
            return {"required": False, "token": None, "items": []}

        token_payload = {
            "userId": user_id,
            "targetTradeDate": target_trade_date,
            "mode": mode,
            "items": items,
        }
        token = hashlib.sha256(
            json.dumps(token_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {"required": True, "token": token, "items": items}

    def _target_trade_date_active_orders(
        self, user_id: str, target_trade_date: str
    ) -> list:
        return [
            order
            for order in self.order_repo.list_orders(
                user_id,
                statuses=ACTIVE_ORDER_STATUSES,
            )
            if order.trade_date == target_trade_date
        ]

    def _build_warning_confirmation(
        self,
        *,
        user_id: str,
        target_trade_date: str,
        mode: str,
        rows: list[dict],
    ) -> dict:
        grouped_row_numbers: dict[tuple[str, str], list[int]] = defaultdict(list)
        for row in rows:
            if row.get("validationStatus") != "WARNING":
                continue
            code = str(row.get("validationCode") or "GENERIC_WARNING")
            summary = str(row.get("validationMessage") or "存在需确认的警告")
            grouped_row_numbers[(code, summary)].append(int(row["rowNumber"]))

        items = [
            {
                "code": code,
                "summary": summary,
                "rowNumbers": sorted(row_numbers),
            }
            for (code, summary), row_numbers in sorted(
                grouped_row_numbers.items(), key=lambda item: (item[0][0], item[0][1])
            )
        ]

        if mode == "OVERWRITE":
            replaced_orders = self._target_trade_date_active_orders(
                user_id, target_trade_date
            )
            if replaced_orders:
                items.append(
                    {
                        "code": WARNING_CODE_OVERWRITE_ACTIVE_ORDERS,
                        "summary": (
                            f"继续提交将覆盖 {target_trade_date} 的 "
                            f"{len(replaced_orders)} 条已生效委托"
                        ),
                        "rowNumbers": [],
                    }
                )

        return self._warning_confirmation_payload(
            user_id=user_id,
            target_trade_date=target_trade_date,
            mode=mode,
            items=items,
        )

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

    @staticmethod
    def _reference_trade_date(target_trade_date: str) -> str:
        return previous_trading_date(target_trade_date)

    @staticmethod
    def _is_post_close_snapshot(quote_trade_date: str, reference_trade_date: str, quoted_at) -> bool:
        return (
            quote_trade_date == reference_trade_date
            and quoted_at.strftime("%H:%M:%S") >= "15:00:00"
        )

    def _market_snapshot_by_symbol(
        self,
        target_trade_date: str,
        symbols: list[str],
        *,
        allow_remote_fetch: bool = False,
    ) -> dict[str, dict[str, float | str]]:
        snapshots: dict[str, dict[str, float | str]] = {}
        reference_trade_date = self._reference_trade_date(target_trade_date)
        missing_symbols: list[str] = []
        for symbol in symbols:
            snapshot = snapshots.setdefault(symbol, {})
            reference_eod = self.market_repo.get_eod_price(symbol, reference_trade_date)
            if reference_eod:
                if reference_eod.symbol_name:
                    snapshot["name"] = reference_eod.symbol_name
                    snapshot["source"] = "eod"
                if reference_eod.close_price > 0:
                    snapshot["referenceClose"] = reference_eod.close_price

            quote = self.market_repo.latest_intraday_quote(to_quote_symbol(symbol))
            if quote:
                if quote.symbol_name and "name" not in snapshot:
                    snapshot["name"] = quote.symbol_name
                    snapshot["source"] = "intraday"
                if (
                    quote.trade_date == target_trade_date
                    and quote.previous_close > 0
                    and "referenceClose" not in snapshot
                ):
                    snapshot["referenceClose"] = quote.previous_close
                if (
                    self._is_post_close_snapshot(
                        quote.trade_date, reference_trade_date, quote.quoted_at
                    )
                    and quote.price > 0
                    and "referenceClose" not in snapshot
                ):
                    snapshot["referenceClose"] = quote.price

            if allow_remote_fetch and ("name" not in snapshot or "referenceClose" not in snapshot):
                missing_symbols.append(symbol)

        if allow_remote_fetch and missing_symbols:
            for symbol in sorted(set(missing_symbols)):
                snapshot = snapshots.setdefault(symbol, {})
                if "referenceClose" in snapshot:
                    continue
                try:
                    fetched_bars = self.quote_client.fetch_daily_bars_sync(
                        symbol,
                        start_trade_date=reference_trade_date,
                        end_trade_date=reference_trade_date,
                    )
                except Exception:
                    fetched_bars = []
                reference_bar = next(
                    (
                        row
                        for row in fetched_bars
                        if row.trade_date == reference_trade_date and row.close_price > 0
                    ),
                    None,
                )
                if not reference_bar:
                    continue

                previous_eod = self.market_repo.previous_eod_price(
                    symbol, reference_trade_date
                )
                self.market_repo.upsert_eod_price(
                    symbol=symbol,
                    symbol_name=reference_bar.name,
                    trade_date=reference_trade_date,
                    close_price=reference_bar.close_price,
                    open_price=reference_bar.open_price,
                    previous_close=previous_eod.close_price if previous_eod else 0,
                    high_price=reference_bar.high_price,
                    low_price=reference_bar.low_price,
                    is_final=True,
                    source="tencent_preview_validation",
                )
                if reference_bar.name:
                    snapshot["name"] = reference_bar.name
                snapshot["source"] = "eod"
                snapshot["referenceClose"] = reference_bar.close_price

            symbols_needing_quote = [
                symbol
                for symbol in sorted(set(missing_symbols))
                if "name" not in snapshots.setdefault(symbol, {})
                or "referenceClose" not in snapshots.setdefault(symbol, {})
            ]
            if symbols_needing_quote:
                try:
                    fetched_rows = self.quote_client.fetch_quotes_sync(
                        [to_quote_symbol(symbol) for symbol in symbols_needing_quote]
                    )
                except Exception:
                    fetched_rows = []

                for row in fetched_rows:
                    quoted_at = row.updated_at
                    quote_trade_date = trade_date_of(quoted_at) or target_trade_date
                    self.market_repo.append_intraday_quote(
                        {
                            "symbol": row.symbol,
                            "name": row.name,
                            "trade_date": quote_trade_date,
                            "price": row.price,
                            "open": row.open_price,
                            "previousClose": row.previous_close,
                            "high": row.high_price,
                            "low": row.low_price,
                            "quoted_at": quoted_at,
                            "source": "tencent_preview_validation",
                        }
                    )
                    symbol = from_quote_symbol(row.symbol)
                    snapshot = snapshots.setdefault(symbol, {})
                    if row.name and "name" not in snapshot:
                        snapshot["name"] = row.name
                        snapshot["source"] = "quote"
                    if (
                        quote_trade_date == target_trade_date
                        and row.previous_close > 0
                        and "referenceClose" not in snapshot
                    ):
                        snapshot["referenceClose"] = row.previous_close
                    if (
                        self._is_post_close_snapshot(
                            quote_trade_date, reference_trade_date, quoted_at
                        )
                        and row.price > 0
                        and "referenceClose" not in snapshot
                    ):
                        snapshot["referenceClose"] = row.price

        return snapshots

    def _attach_symbol_names(self, target_trade_date: str, rows: list[dict]) -> list[dict]:
        symbols = sorted(
            {
                str(row["symbol"])
                for row in rows
                if SYMBOL_PATTERN.fullmatch(str(row["symbol"]))
            }
        )
        snapshots = self._market_snapshot_by_symbol(
            target_trade_date,
            symbols,
            allow_remote_fetch=False,
        )
        output: list[dict] = []
        for row in rows:
            next_row = dict(row)
            symbol = str(row["symbol"])
            next_row["name"] = str(
                snapshots.get(symbol, {}).get("name") or row.get("name") or symbol
            )
            output.append(next_row)
        return output

    def resolve_symbols(
        self,
        *,
        target_trade_date: str,
        symbols: list[str],
    ) -> list[dict]:
        normalized_symbols = sorted(
            {
                str(symbol).strip().upper()
                for symbol in symbols
                if SYMBOL_PATTERN.fullmatch(str(symbol).strip().upper())
            }
        )
        snapshots = self._market_snapshot_by_symbol(
            target_trade_date,
            normalized_symbols,
            allow_remote_fetch=True,
        )
        rows: list[dict] = []
        for symbol in normalized_symbols:
            snapshot = snapshots.get(symbol, {})
            rows.append(
                {
                    "symbol": symbol,
                    "name": str(snapshot.get("name") or ""),
                    "resolved": bool(snapshot.get("name")),
                    "referenceClose": (
                        float(snapshot["referenceClose"])
                        if "referenceClose" in snapshot
                        else None
                    ),
                    "source": str(snapshot.get("source") or "unknown"),
                }
            )
        return rows

    def apply_price_limit_checks(
        self,
        target_trade_date: str,
        rows: list[dict],
        *,
        allow_remote_fetch: bool = False,
    ) -> list[dict]:
        symbols = sorted(
            {
                row["symbol"]
                for row in rows
                if row["validationStatus"] != "ERROR" and SYMBOL_PATTERN.fullmatch(str(row["symbol"]))
            }
        )
        snapshots = self._market_snapshot_by_symbol(
            target_trade_date,
            symbols,
            allow_remote_fetch=allow_remote_fetch,
        )
        output: list[dict] = []
        for row in rows:
            next_row = dict(row)
            if row["validationStatus"] != "ERROR":
                symbol = str(row["symbol"])
                snapshot = snapshots.get(symbol)
                if not snapshot or "referenceClose" not in snapshot:
                    next_row["validationStatus"] = "WARNING"
                    next_row["validationMessage"] = "暂未获取到昨收盘口径，未校验涨跌停区间"
                    next_row["validationCode"] = WARNING_CODE_MISSING_REFERENCE_CLOSE
                else:
                    reference_close = Decimal(str(snapshot["referenceClose"]))
                    ratio = self._limit_ratio(symbol, str(snapshot.get("name", "")))
                    lower = self._round_cny(reference_close * (Decimal("1") - ratio))
                    upper = self._round_cny(reference_close * (Decimal("1") + ratio))
                    price = Decimal(str(row["price"]))
                    if price < lower or price > upper:
                        next_row["validationStatus"] = "ERROR"
                        next_row["validationMessage"] = (
                            f"按昨收 {reference_close:.2f} 计算，涨跌停区间为 {lower:.2f} - {upper:.2f}，当前委托价 {price:.2f} 超出范围"
                        )
                        next_row.pop("validationCode", None)
            output.append(next_row)
        return output

    def _active_orders(self, user_id: str, target_trade_date: str, mode: str):
        orders = self.order_repo.list_orders(
            user_id,
            statuses=ACTIVE_ORDER_STATUSES,
        )
        orders = [
            order
            for order in orders
            if is_order_effective_on_trade_date(order, target_trade_date)
        ]
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
            sellable_by_symbol[lot.symbol] += projected_lot_sellable_shares(
                lot, target_trade_date
            )

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
                    next_row["validationStatus"] = "ERROR"
                    next_row["validationMessage"] = (
                        f"本批卖单累计将超出剩余可卖，当前剩余可卖 {available // 100} 手，前序已占用 {batch_reserved // 100} 手"
                    )
                    next_row.pop("validationCode", None)
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
        available_cash = self.portfolio_repo.cash_balance(user_id)
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
                    next_row["validationStatus"] = "ERROR"
                    next_row["validationMessage"] = (
                        f"与现有/本批买单合计后将超出可用现金，当前剩余可用 {remaining_cash:.2f} 元"
                    )
                    next_row.pop("validationCode", None)
                batch_buy_amount += row_amount
            output.append(next_row)
        return output

    def apply_preview_checks(
        self,
        user_id: str,
        target_trade_date: str,
        mode: str,
        rows: list[dict],
        *,
        allow_remote_fetch: bool = False,
    ) -> list[dict]:
        checked_rows = self.apply_trade_date_checks(target_trade_date, rows)
        checked_rows = self.apply_symbol_format_checks(checked_rows)
        checked_rows = self.apply_price_limit_checks(
            target_trade_date,
            checked_rows,
            allow_remote_fetch=allow_remote_fetch,
        )
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
                    "name": item.symbol_name,
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
            latest_name = latest.get("name")
            if latest_name:
                item.symbol_name = latest_name
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
        checked_rows = self.apply_preview_checks(
            user_id,
            target_trade_date,
            mode,
            rows,
            allow_remote_fetch=True,
        )
        confirmation = self._build_warning_confirmation(
            user_id=user_id,
            target_trade_date=target_trade_date,
            mode=mode,
            rows=checked_rows,
        )
        checked_rows = self._attach_symbol_names(target_trade_date, checked_rows)
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
            "confirmation": confirmation,
        }

    def commit_import_batch(
        self,
        user_id: str,
        batch_id: str,
        mode: str,
        *,
        confirm_warnings: bool = False,
        confirmation_token: str | None = None,
    ) -> dict:
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
            allow_remote_fetch=True,
        )
        self._update_batch_validation(batch, revalidated_rows)
        confirmation = self._build_warning_confirmation(
            user_id=user_id,
            target_trade_date=batch.target_trade_date,
            mode=mode,
            rows=revalidated_rows,
        )
        if mode != "DRAFT" and any(row["validationStatus"] == "ERROR" for row in revalidated_rows):
            raise ValueError("导入批次校验已变化，请重新校验后再提交")
        if (
            mode != "DRAFT"
            and confirmation["required"]
            and (
                not confirm_warnings
                or not confirmation_token
                or confirmation_token != confirmation["token"]
            )
        ):
            raise ValueError("存在需确认的警告，请重新校验并确认后再提交")
        imported = self.order_repo.commit_import_batch(batch, mode)
        return {
            "batchId": batch.id,
            "targetTradeDate": batch.target_trade_date,
            "mode": mode,
            "importedCount": imported,
        }
