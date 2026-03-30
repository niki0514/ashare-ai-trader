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

`make dev-up` 会以热更新模式启动本地 backend 和 frontend。

或手动执行：

```bash
docker compose up -d postgres
cd backend
cp .env.example .env
uv run python -m devtools.schema init
ASHARE_RELOAD=true uv run python -m app
```

Backend runs on `http://localhost:3101`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:5174`.

`make dev-up` 会一起拉起 Docker PostgreSQL、启动 backend 和 frontend。

## Docker 热更新开发

如果你希望前后端都跑在 Docker 里，同时保留热更新：

```bash
make dev-docker-up
```

这会启动：

- `postgres`
- `backend`：FastAPI + `uvicorn --reload`
- `frontend`：Vite HMR

访问地址仍然是：

- Frontend: `http://localhost:5174`
- Backend: `http://localhost:3101`

常用命令：

```bash
make dev-docker-down
make dev-docker-logs
```

## 数据库备份与迁移

备份当前 Docker PostgreSQL：

```bash
make db-backup
```

或直接执行：

```bash
./scripts/backup-db.sh
```

备份文件会写到仓库根目录的 `backups/`，格式为：

```text
backups/ashare_ai_trader_YYYYMMDD_HHMMSS.dump
```

如果你要把项目迁移到另一台机器，并继续用本地 `uv`/`npm` 启动前后端：

1. 把仓库和对应的 `.dump` 备份文件一起拷过去
2. 在新机器上安装好 `docker`、`uv`、`npm`
3. 在新机器上执行：

```bash
./scripts/dev-up.sh backups/ashare_ai_trader_YYYYMMDD_HHMMSS.dump
```

这个脚本会自动：

- 启动 Docker PostgreSQL
- 恢复备份
- 本地启动 backend
- 本地启动 frontend

默认访问地址：

- Frontend: `http://localhost:5174`
- Backend: `http://localhost:3101`

如果你只想恢复数据库，不立刻启动前后端：

```bash
make db-restore BACKUP=backups/ashare_ai_trader_YYYYMMDD_HHMMSS.dump
```

如果你想通过 Make 启动“恢复后本地启动”的完整流程：

```bash
make migrate-up BACKUP=backups/ashare_ai_trader_YYYYMMDD_HHMMSS.dump
```

## 数据安全

- PostgreSQL 使用固定命名卷 `ashare-ai-trader_ashare_postgres_data`，避免因 Compose 项目名变化误连到新空卷
- `docker compose restart postgres` 或 `docker compose down` 后再次启动，数据仍会保留在本地 volume
- `docker compose down -v` 会删除持久化卷，执行前务必确认不再需要当前数据
- 仓库内的开发工具不再提供“删库重建”操作；样例账户只允许在空库（新库未建表，或已建表但仍无业务数据）时显式初始化，不会覆盖现有数据

## Backend 验收

```bash
cd backend
uv run pytest
```

当前保留的是不依赖仓库内置 mock/seed 的最小 API 回归。
测试会自动使用临时 SQLite，不会写入运行中的 PostgreSQL。

## Backend Notes

- Frontend API contract remains unchanged: `/api/dashboard`, `/api/positions`, `/api/history`, `/api/pnl/*`, `/api/imports/*`, `/api/quotes`
- Frontend dev server proxies `/api` to backend by default, so browsers no longer depend on direct `localhost:3001` access
- Users are fully managed in the database; user isolation is supported via request header `X-User-Id`
- During trading hours, the backend polls Tencent quotes and persists trades in real time
- At lunch break and market close, the engine freezes the current session prices into the database; outside trading, dashboard reads persisted snapshots instead of request-time quotes
- Official dev entrypoints use Docker PostgreSQL: `postgresql+psycopg://ashare:ashare@127.0.0.1:5433/ashare_ai_trader`
- Ad-hoc `uv run python ...` commands no longer fall back to PostgreSQL; set `ASHARE_DATABASE_URL` explicitly or create `backend/.env` first
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
