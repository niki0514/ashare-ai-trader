# Python Backend

当前后端主实现已经切到 Python：`FastAPI + SQLAlchemy`。

## 目标

- 前端不改，开发环境继续使用 `/api`，由 Vite 代理转发到 backend
- 数据库与服务解耦：`models / repositories / services / api`
- 账户完全由数据库管理，不再内置 demo 用户或示例数据
- 支持用户隔离：通过请求头 `X-User-Id` 切换账户
- 仅盘中轮巡实时行情，成交即时落库
- 午休和收盘在阶段切换时落库当日价格，非交易时段只读取已冻结快照

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

或手动执行：

```bash
docker compose up -d postgres
cd backend
uv run python -m app.bootstrap
uv run python -m app
```

服务默认监听：`http://localhost:3101`

默认数据库为 Docker PostgreSQL：

```bash
postgresql+psycopg://ashare:ashare@127.0.0.1:5433/ashare_ai_trader
```

- Docker 编排文件在项目根目录 `../docker-compose.yml`
- `uv run python -m app.bootstrap` 只负责初始化当前表结构
- 如果要切换到别的数据库，直接设置 `ASHARE_DATABASE_URL`
- 首次启动后若数据库为空，需要先通过前端或 `POST /api/users` 创建账户

### 独立初始化数据库

```bash
cd backend
uv run python -m app.bootstrap
```

## 测试

```bash
cd backend
uv run --with pytest --with pytest-asyncio pytest -q
```

当前保留的是不依赖本地 mock 数据的最小 API 回归用例，覆盖：

1. 空库时访问账户数据返回正确错误
2. 新建用户后基础账户接口可正常回读
3. 重名用户创建会被拒绝

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
- 默认运行库为 Docker PostgreSQL，不再依赖本地 `.db` 文件。
- 更简单的启动与入库说明见 `../docs/docker-postgres-setup.md`。
