from __future__ import annotations

from sqlalchemy.orm import Session

from .models import ImportBatchStatus
from .repositories import OrderRepository, PortfolioRepository


class ImportService:
    def __init__(self, session: Session):
        self.session = session
        self.order_repo = OrderRepository(session)
        self.portfolio_repo = PortfolioRepository(session)

    def apply_sell_conflict_checks(self, user_id: str, rows: list[dict]) -> list[dict]:
        availability = self.portfolio_repo.get_available_sellable_shares(user_id)
        reserved_lots: dict[str, int] = {}
        output: list[dict] = []
        for row in rows:
            next_row = dict(row)
            if row["side"] == "SELL" and row["validationStatus"] != "ERROR":
                shares = int(row["lots"]) * 100
                symbol = row["symbol"]
                batch_reserved = reserved_lots.get(symbol, 0)
                sellable = availability.sellable_by_symbol.get(symbol, 0)
                reserved = availability.reserved_by_symbol.get(symbol, 0)
                available = availability.available_by_symbol.get(symbol, 0)
                if sellable == 0:
                    next_row["validationStatus"] = "ERROR"
                    next_row["validationMessage"] = "当前无可卖仓位"
                elif reserved >= sellable or available == 0:
                    next_row["validationStatus"] = "ERROR"
                    next_row["validationMessage"] = "当前可卖仓位已被其他卖单占用"
                elif batch_reserved + shares > available:
                    next_row["validationStatus"] = "WARNING"
                    next_row["validationMessage"] = "卖单与已有挂单存在仓位冲突，请确认"
                reserved_lots[symbol] = batch_reserved + shares
            output.append(next_row)
        return output

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
        checked_rows = self.apply_sell_conflict_checks(user_id, rows)
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
            "rows": checked_rows,
        }

    def commit_import_batch(self, user_id: str, batch_id: str, mode: str) -> dict:
        batch = self.order_repo.get_import_batch(batch_id)
        if not batch or batch.user_id != user_id:
            raise ValueError("Import batch not found")
        if batch.status == ImportBatchStatus.COMMITTED:
            raise ValueError("Import batch already committed")
        imported = self.order_repo.commit_import_batch(batch, mode)
        return {
            "batchId": batch.id,
            "targetTradeDate": batch.target_trade_date,
            "mode": mode,
            "importedCount": imported,
        }
