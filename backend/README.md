# Python Backend

当前后端主实现已经切到 Python：`FastAPI + SQLAlchemy`。

## 目标

- 前端不改，开发环境继续使用 `/api`，由 Vite 代理转发到 backend
- 数据库与服务解耦：`models / repositories / services / api`
- 账户完全由数据库管理，不再内置 demo 用户或示例数据
- 支持用户隔离：通过请求头 `X-User-Id` 切换账户
- 仅盘中轮巡实时行情，成交即时落库
- 历史日线、收盘回补、实时结算统一采用 raw 价格口径（腾讯 `bfq`）
- 盘中只计算不落库；午休落非 final 快照，收盘落 final 快照；周末/节假日不生成 `daily_pnl`

## 目录

- `app/main.py`：FastAPI 入口
- `app/models.py`：SQLAlchemy 数据模型
- `app/repositories.py`：数据库访问层
- `app/services.py`：行情、成交、PnL、执行引擎
- `app/import_io.py`：CSV/XLSX 导入解析和模板生成
- `app/quote_client.py`：腾讯行情客户端
- `tests/`：后端回归测试

## 启动

```bash
make dev-up
```

`make dev-up` 默认就是热更新模式，会以 `ASHARE_RELOAD=true` 启动后端。

或手动执行：

```bash
docker compose up -d postgres
cd backend
ASHARE_RELOAD=true uv run python -m app
```

服务默认监听：`http://localhost:3101`

默认数据库为 Docker PostgreSQL：

```bash
postgresql+psycopg://ashare:ashare@127.0.0.1:5433/ashare_ai_trader
```

- Docker 编排文件在项目根目录 `../docker-compose.yml`
- 如果你想把 backend/frontend 一起跑在 Docker 里并保留热更新，可在项目根目录执行 `make dev-docker-up`
- 当前应用启动不再自动执行任何 schema 初始化
- 如果要切换到别的数据库，直接设置 `ASHARE_DATABASE_URL`
- 如果你连接的是新的空数据库，需要先在库外执行 `uv run python -m devtools.schema init`
- Docker PostgreSQL 数据保存在固定 volume `ashare-ai-trader_ashare_postgres_data`，容器重启不会影响业务数据
- 后端开发工具中已不再提供任何“删库重建”入口
- 如果你要恢复本地 `Test User` 测试数据，可执行 `ASHARE_CONFIRM_RESTORE_TEST_USER=1 uv run python -m devtools.restore_test_user`
  这属于开发辅助脚本；针对 PostgreSQL 运行时现在要求显式确认，避免误写持久化运行库
- 如果你已经保留了用户和成交事实、只想按新口径重建衍生层，可执行 `ASHARE_CONFIRM_REBUILD_DERIVED_DATA=1 uv run python -m devtools.rebuild_derived_data`
  该脚本会删除并重建 `eod_prices`、`daily_pnl`、`daily_pnl_details`，不会删除用户、成交、持仓和现金流水
- 如果你要在空库里初始化样例账户（新库未建表，或已建表但仍无业务数据），可显式执行 `ASHARE_CONFIRM_SAMPLE_ACCOUNT_INIT=INIT_SAMPLE_ACCOUNT uv run python -m devtools.sample_account`
  该脚本会先补齐空库表结构；一旦检测到现有业务数据，会直接拒绝，不会覆盖现有库

## 测试

```bash
cd backend
uv run pytest
```

当前保留的是不依赖本地 mock 数据的最小 API 回归用例，覆盖：

1. 空库时访问账户数据返回正确错误
2. 新建用户后基础账户接口可正常回读
3. 重名用户创建会被拒绝

测试会自动使用临时 SQLite，不会连接运行中的 PostgreSQL。

## 收益口径（当前唯一真值）

当前统一采用 **账户资产变动口径**：

- 组合当日盈亏：`dailyPnl(d) = totalAssets(d) - totalAssets(d-1)`
- 累计盈亏：`cumulativePnl(d) = totalAssets(d) - initialCapital`
- 明细校验：`sum(detail.dailyPnl) = calendar.dailyPnl`
- 日收益明细只保留 `dailyPnl / dailyReturn`，不再拆 `realized/unrealized`
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
- 查询链路会在午休/收盘时自愈补结算；如果引擎停掉，`dashboard/calendar` 仍会按同一套结算逻辑补齐交易日快照。
- 周末/节假日不会为当天生成 `daily_pnl`；只会在有条件时回补上一个缺失的交易日。
- 收益真值基线以当前 Python 后端实现和回归测试为准。

## 说明

- 默认运行库为 Docker PostgreSQL，不再依赖本地 `.db` 文件。
- 更简单的启动与入库说明见 `../docs/docker-postgres-setup.md`。
