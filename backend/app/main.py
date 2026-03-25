from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .bootstrap import bootstrap_database
from .config import settings
from .db import SessionLocal
from .import_io import build_import_template, parse_import_file
from .import_service import ImportService
from .market import market_clock
from .repositories import OrderRepository
from .schemas import (
    CommitImportsRequest,
    CreateUserRequest,
    DashboardResponse,
    DeleteOrderResponse,
    ImportCommitResponse,
    ImportPreviewResponse,
    ImportUploadResponse,
    PreviewImportsRequest,
    QuoteResponse,
    UserSummary,
)
from .services import (
    OrderService,
    QueryService,
    QuoteService,
    run_engine_tick_once,
    start_engine_if_needed,
    stop_engine_if_needed,
)
from .user_service import UserService

@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap_database()
    await start_engine_if_needed()
    try:
        yield
    finally:
        await stop_engine_if_needed()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _serialize_user(user) -> UserSummary:
    return UserSummary(
        id=user.id,
        name=user.name,
        initialCash=user.initial_cash,
        createdAt=user.created_at.isoformat(),
        updatedAt=user.updated_at.isoformat(),
    )


def get_user_id(x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)) -> str:
    try:
        return UserService(db).resolve_user_id(x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/users")
def list_users(db: Session = Depends(get_db)):
    rows = UserService(db).list_users()
    return {"rows": [_serialize_user(user) for user in rows]}


@app.post("/api/users", response_model=UserSummary)
def create_user(payload: CreateUserRequest, db: Session = Depends(get_db)):
    try:
        user = UserService(db).create_user(
            name=payload.name,
            initial_cash=payload.initialCash,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 409 if detail == "User name already exists" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    db.commit()
    return _serialize_user(user)


@app.get("/api/dashboard", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return QueryService(db).get_dashboard(user_id)


@app.get("/api/positions")
def get_positions(db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return {"rows": QueryService(db).get_positions(user_id)}


@app.get("/api/orders/pending")
def get_pending_orders(db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return {"rows": QueryService(db).get_pending_orders(user_id)}


@app.delete("/api/orders/{order_id}", response_model=DeleteOrderResponse)
def delete_order(order_id: str, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    try:
        deleted_id = OrderService(db).delete_order(user_id, order_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "委托不存在" else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc
    db.commit()
    return {"deletedId": deleted_id}


@app.get("/api/history")
def get_history(db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return {"rows": QueryService(db).get_history(user_id)}


@app.get("/api/pnl/calendar")
def get_calendar(db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return {"rows": QueryService(db).get_calendar(user_id)}


@app.get("/api/pnl/daily/{date}")
def get_daily_detail(date: str, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return {"date": date, "rows": QueryService(db).get_daily_detail(user_id, date)}


@app.post("/api/imports/preview", response_model=ImportPreviewResponse)
def preview_imports(payload: PreviewImportsRequest, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    rows = [
        {
            "rowNumber": idx + 1,
            "tradeDate": payload.targetTradeDate,
            "symbol": row.symbol,
            "side": row.side,
            "price": row.price,
            "lots": row.lots,
            "validity": row.validity,
            "validationStatus": "VALID",
            "validationMessage": "校验通过",
        }
        for idx, row in enumerate(payload.rows)
    ]
    result = ImportService(db).create_import_preview(
        user_id=user_id,
        target_trade_date=payload.targetTradeDate,
        source_type=payload.sourceType,
        file_name=payload.fileName,
        mode=payload.mode,
        rows=rows,
    )
    db.commit()
    return result


@app.post("/api/imports/upload", response_model=ImportUploadResponse)
async def upload_import_file(
    mode: str = Form("DRAFT"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_user_id),
):
    content = await file.read()
    try:
        parsed = parse_import_file(file.filename or "upload.xlsx", content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    grouped_rows: dict[str, list[dict]] = {}
    for row in parsed.rows:
        grouped_rows.setdefault(row["tradeDate"], []).append(row)

    preview_rows: list[dict] = []
    batch_ids: dict[str, str] = {}
    import_service = ImportService(db)
    for trade_date in sorted(grouped_rows):
        result = import_service.create_import_preview(
            user_id=user_id,
            target_trade_date=trade_date,
            source_type=parsed.source_type,
            file_name=file.filename,
            mode=mode,
            rows=grouped_rows[trade_date],
        )
        batch_ids[trade_date] = result["batchId"]
        preview_rows.extend(result["rows"])

    db.commit()
    preview_rows.sort(key=lambda row: row["rowNumber"])
    return {
        "fileName": file.filename,
        "sourceType": parsed.source_type,
        "batchIds": batch_ids,
        "rows": preview_rows,
    }


@app.get("/api/imports/template")
def download_import_template(targetTradeDate: str | None = None):
    content = build_import_template(targetTradeDate)
    file_name = f"import-template-{targetTradeDate or 'template'}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)


@app.post("/api/imports/commit", response_model=ImportCommitResponse)
def commit_imports(payload: CommitImportsRequest, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    if not market_clock.is_import_window_open():
        raise HTTPException(status_code=403, detail="当前为休市日，仅允许在交易日提交导入")
    try:
        result = ImportService(db).commit_import_batch(user_id, payload.batchId, payload.mode)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "Import batch not found" else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc
    db.commit()
    return result


@app.get("/api/imports/latest")
def latest_imports(tradeDate: str = Query(default=""), db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    rows = OrderRepository(db).latest_import_batches(user_id, tradeDate or None)
    output = []
    for batch in rows:
        output.append(
            {
                "id": batch.id,
                "targetTradeDate": batch.target_trade_date,
                "sourceType": batch.source_type.value,
                "fileName": batch.file_name,
                "mode": batch.mode.value,
                "status": batch.status.value,
                "createdAt": batch.created_at.isoformat(),
                "items": [
                    {
                        "rowNumber": item.row_number,
                        "symbol": item.symbol,
                        "side": item.side.value,
                        "limitPrice": item.limit_price,
                        "lots": item.lots,
                        "validity": item.validity.value,
                        "validationStatus": item.validation_status.value,
                        "validationMessage": item.validation_message,
                    }
                    for item in sorted(batch.items, key=lambda x: x.row_number)
                ],
            }
        )
    return {"rows": output}


@app.delete("/api/imports/draft")
def clear_import_drafts(
    tradeDate: str = Query(...),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_user_id),
):
    deleted_count = OrderRepository(db).delete_draft_import_batches(user_id, tradeDate)
    db.commit()
    return {"deletedCount": deleted_count}


@app.get("/api/quotes", response_model=QuoteResponse)
async def get_quotes(
    symbols: str = Query(default=""),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_user_id),
):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    quote_service = QuoteService(db)
    market_session = market_clock.get_session()

    if not market_clock.is_market_polling_window():
        rows = quote_service.get_quotes(symbol_list if symbol_list else None)
        return {
            "marketStatus": market_session.market_status,
            "updatedAt": quote_service.latest_updated_at(),
            "stale": True,
            "quotes": rows,
        }

    rows = await quote_service.fetch_and_store_quotes(symbol_list)
    db.commit()
    return {
        "marketStatus": market_session.market_status,
        "updatedAt": quote_service.latest_updated_at(),
        "stale": False,
        "quotes": rows,
    }


@app.post("/api/dev/tick")
async def dev_tick():
    processed = await run_engine_tick_once()
    return {"processed": processed, "updatedAt": datetime.now().isoformat()}
