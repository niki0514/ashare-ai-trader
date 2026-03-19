# Python Backend

当前后端主实现已经切到 Python：`FastAPI + SQLAlchemy`。

## 目标

- 前端不改，继续使用 `http://localhost:3001/api`
- 数据库与服务解耦：`models / repositories / services / api`
- 默认按 `test` 用户返回现有测试数据
- 支持用户隔离：可通过请求头 `X-User-Id` 切换账户
- 盘中实时拉腾讯行情，成交即时落库
- 收盘后冻结当日收盘口径，不再变化

## 目录

- `app/main.py`：FastAPI 入口
- `app/models.py`：SQLAlchemy 数据模型
- `app/repositories.py`：数据库访问层
- `app/services.py`：行情、成交、PnL、执行引擎
- `app/import_io.py`：CSV/XLSX 导入解析和模板生成
- `app/quote_client.py`：腾讯行情客户端
- `app/seed_data.py`：`test` 用户测试数据
- `tests/`：后端回归测试

## 启动

```bash
cd backend
uv run python -m app
```

服务默认监听：`http://localhost:3001`

默认数据库已改为用户本地目录：`~/.ashare-ai-trader/ashare_ai_trader.db`。

- 如果你的机器上已有旧库 `backend/data/ashare_ai_trader.db`，首次启动会自动迁移到新位置
- 如果要切换到外部数据库，直接设置 `ASHARE_DATABASE_URL`
- 如果不希望启动时自动写入 demo 用户和样例成交，设置 `ASHARE_BOOTSTRAP_DEMO_DATA=false`

### 独立初始化数据库

```bash
cd backend
uv run python -m app.bootstrap
```

常见用法：

```bash
# 初始化外部数据库并保留空库
ASHARE_DATABASE_URL="postgresql+<driver>://user:pass@host:5432/ashare" \
ASHARE_BOOTSTRAP_DEMO_DATA=false \
uv run python -m app.bootstrap --no-seed-demo
```

## 测试

```bash
cd backend
uv run --with pytest --with pytest-asyncio pytest -q
```

### API 级 E2E Smoke（最小可验收）

```bash
cd backend
uv run --with pytest --with pytest-asyncio pytest -q tests/test_smoke_e2e.py
```

该 smoke 用例覆盖：

1. 下载导入模板：`GET /api/imports/template`
2. 上传并预览导入：`POST /api/imports/upload`
3. commit 导入：`POST /api/imports/commit`
4. 挂单回读：`GET /api/orders/pending`
5. 关键接口回读：
   - `GET /api/dashboard`
   - `GET /api/positions`
   - `GET /api/history`
   - `GET /api/pnl/calendar`
   - `GET /api/pnl/daily/{date}`

> 说明：该用例是 API 级可重复验收链路，不依赖浏览器点击流。

当前已验证：

- `history` 成交流水可回放 11 笔测试成交
- `positions` 返回当前剩余持仓：`000021=1000`、`000547=4000`
- `pnl/daily/2026-03-18` 满足“今日卖出后持仓数下降，但收益仍计入今日”
- 新用户默认空仓空流水，和 `test` 用户隔离
- `tests/test_pnl_consistency.py` 已固定 1 号口径：`calendar.dailyPnl == sum(detail.dailyPnl)`

## 收益口径（当前唯一真值）

当前统一采用 **账户资产变动口径**：

- 组合当日盈亏：`dailyPnl(d) = totalAssets(d) - totalAssets(d-1)`
- 累计盈亏：`cumulativePnl(d) = totalAssets(d) - initialCapital`
- 明细校验：`sum(detail.dailyPnl) = calendar.dailyPnl`
- 单票通用公式：`detailDailyPnl = closePrice * closingShares + sellAmount - prevClose * openingShares - buyAmount`
  - `prevClose` 来自前一交易日该票 `detail.closePrice`
  - `buyAmount / sellAmount` 来自当日该票成交金额聚合

这条单票公式可以统一覆盖四种情况：
- 纯持仓不交易
- 仅卖出旧仓
- 当日新买且留仓
- 当日买入又卖出

当前回归基线：

- `2026-03-16 total=521210, daily=21210, cumulative=21210`
- `2026-03-17 total=508980, daily=-12230, cumulative=8980`
- `2026-03-18 total=521570, daily=12590, cumulative=21570`

说明：

- 持仓页 `todayPnl` 是“剩余持仓相对昨收的变动”，仅用于持仓视角展示，不等于组合日收益。
- 收益真值基线以当前 Python 后端实现和回归测试为准。

## 说明

- 测试现在使用独立临时数据库，不再污染运行库。
- 默认运行库位于 `~/.ashare-ai-trader/ashare_ai_trader.db`。
- 更完整的数据库解耦与数据入库方案见 `../docs/database-decoupling-and-ingestion.md`。
