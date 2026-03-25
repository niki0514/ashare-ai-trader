# A-share AI Trader

This repository contains an instruction-driven A-share paper trading system.

## Structure

- `frontend/`: React + Vite trading dashboard
- `backend/`: Python FastAPI + SQLAlchemy backend（主服务）
- `docs/`: product and data model documentation

## Quick Start

### Backend

```bash
make dev-up
```

或手动执行：

```bash
docker compose up -d postgres
cd backend
uv run python -m app.bootstrap
uv run python -m app
```

Backend runs on `http://localhost:3101`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:5174`.

`make dev-up` 会一起拉起 Docker PostgreSQL、初始化表结构、启动 backend 和 frontend。

## Backend 验收

```bash
cd backend
uv run pytest
```

当前保留的是不依赖仓库内置 mock/seed 的最小 API 回归。

## Backend Notes

- Frontend API contract remains unchanged: `/api/dashboard`, `/api/positions`, `/api/history`, `/api/pnl/*`, `/api/imports/*`, `/api/quotes`
- Frontend dev server proxies `/api` to backend by default, so browsers no longer depend on direct `localhost:3001` access
- Users are fully managed in the database; user isolation is supported via request header `X-User-Id`
- During trading hours, the backend polls Tencent quotes and persists trades in real time
- At lunch break and market close, the engine freezes the current session prices into the database; outside trading, dashboard reads persisted snapshots instead of request-time quotes
- The default database is Docker PostgreSQL: `postgresql+psycopg://ashare:ashare@127.0.0.1:5433/ashare_ai_trader`
- `uv run python -m app.bootstrap` only initializes the active schema

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
Docker PostgreSQL setup notes live in `docs/docker-postgres-setup.md`.
