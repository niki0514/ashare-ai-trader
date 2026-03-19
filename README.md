# A-share AI Trader

This repository contains an instruction-driven A-share paper trading system.

## Structure

- `frontend/`: React + Vite trading dashboard
- `backend/`: Python FastAPI + SQLAlchemy backend（主服务）
- `docs/`: product and data model documentation

## Quick Start

### Backend

```bash
cd backend
uv run python -m app
```

Backend runs on `http://localhost:3001`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:5173`.

## Backend Notes

- Frontend API contract remains unchanged: `/api/dashboard`, `/api/positions`, `/api/history`, `/api/pnl/*`, `/api/imports/*`, `/api/quotes`
- Default user is `test`; user isolation is supported via request header `X-User-Id`
- During market hours, the backend polls Tencent quotes and persists trades in real time
- After market close, close prices and the day’s frozen PnL snapshot are persisted to SQLite

## PnL Source of Truth

- 当前统一采用 **账户资产变动口径** 作为唯一真值（source of truth）
- 组合当日盈亏：`dailyPnl(d) = totalAssets(d) - totalAssets(d-1)`
- 单票通用公式：`detailDailyPnl = closePrice * closingShares + sellAmount - prevClose * openingShares - buyAmount`
- `calendar.dailyPnl` 与 `sum(detail.dailyPnl)` 必须一致
- 当前回归基线：
  - `2026-03-16 dailyPnl = 21210`
  - `2026-03-17 dailyPnl = -12230`
  - `2026-03-18 dailyPnl = 12590`
- 收益真值基线以当前 Python 后端回归测试为准，不再依赖历史迁移样本

See `backend/README.md` for more details.
