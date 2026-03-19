from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .config import settings
from .db import Base, SessionLocal, engine, session_scope
from .import_io import build_import_template, parse_import_file
from .import_service import ImportService
from .market import market_clock
from .models import User
from .repositories import OrderRepository, PortfolioRepository, UserRepository
from .schemas import (
    CommitImportsRequest,
    DashboardResponse,
    ImportCommitResponse,
    ImportPreviewResponse,
    PreviewImportsRequest,
    QuoteResponse,
)
from .seed_data import SEED_CLOSE_PRICES
from .services import (
    PnlService,
    QueryService,
    QuoteService,
    SeedService,
    run_engine_tick_once,
    start_engine_if_needed,
    stop_engine_if_needed,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with session_scope() as session:
        seed = SeedService(session)
        seed.ensure_seed_data(settings.default_user_id)
        pnl_service = PnlService(session)
        for day in sorted(SEED_CLOSE_PRICES.keys()):
            pnl_service.recompute_daily_pnl(settings.default_user_id, day, use_realtime=False, is_final=True)
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
    finally:
        session.close()


def get_user_id(x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)) -> str:
    user_id = (x_user_id or settings.default_user_id).strip() or settings.default_user_id
    user_repo = UserRepository(db)
    user = user_repo.get_or_create(user_id, settings.default_user_name, settings.initial_cash)
    portfolio_repo = PortfolioRepository(db)
    if portfolio_repo.latest_cash(user_id) is None:
        portfolio_repo.add_cash_entry(
            user_id=user_id,
            entry_time=datetime.now(),
            entry_type="INITIAL",
            amount=user.initial_cash,
            balance_after=user.initial_cash,
            reference_type="UserBootstrap",
        )
    db.commit()
    return user_id


@app.get("/api/dashboard", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return QueryService(db).get_dashboard(user_id)


@app.get("/api/positions")
def get_positions(db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return {"rows": QueryService(db).get_positions(user_id)}


@app.get("/api/orders/pending")
def get_pending_orders(db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return {"rows": QueryService(db).get_pending_orders(user_id)}


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


@app.post("/api/imports/upload", response_model=ImportPreviewResponse)
async def upload_import_file(
    targetTradeDate: str = Form(...),
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
    result = ImportService(db).create_import_preview(
        user_id=user_id,
        target_trade_date=targetTradeDate,
        source_type=parsed.source_type,
        file_name=file.filename,
        mode=mode,
        rows=parsed.rows,
    )
    db.commit()
    return result


@app.get("/api/imports/template")
def download_import_template(targetTradeDate: str | None = None):
    content = build_import_template(targetTradeDate)
    file_name = f"import-template-{targetTradeDate or 'template'}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)


@app.post("/api/imports/commit", response_model=ImportCommitResponse)
def commit_imports(payload: CommitImportsRequest, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    if not market_clock.is_import_window_open():
        raise HTTPException(status_code=403, detail="仅允许在交易所收盘后或开盘前提交导入")
    try:
        result = ImportService(db).commit_import_batch(user_id, payload.batchId, payload.mode)
    except ValueError as exc:
        detail = str(exc)
        status_code = 409 if detail == "Import batch already committed" else 404
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


@app.post("/api/dev/reset-demo")
def reset_demo(db: Session = Depends(get_db)):
    from .models import (
        CashLedger,
        DailyPnl,
        DailyPnlDetail,
        DailyPrice,
        ExecutionTrade,
        ImportBatch,
        ImportBatchItem,
        InstructionOrder,
        OrderEvent,
        PositionLot,
        QuoteSnapshot,
    )

    for model in [
        OrderEvent,
        ExecutionTrade,
        InstructionOrder,
        PositionLot,
        CashLedger,
        DailyPnlDetail,
        DailyPnl,
        DailyPrice,
        QuoteSnapshot,
        ImportBatchItem,
        ImportBatch,
        User,
    ]:
        db.query(model).delete()

    seed = SeedService(db)
    seed.ensure_seed_data(settings.default_user_id)
    pnl_service = PnlService(db)
    for day in sorted(SEED_CLOSE_PRICES.keys()):
        pnl_service.recompute_daily_pnl(settings.default_user_id, day, use_realtime=False, is_final=True)
    db.commit()
    return {"message": "demo reset complete"}
