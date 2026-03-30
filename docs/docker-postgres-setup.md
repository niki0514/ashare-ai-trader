# Docker PostgreSQL 方案

## 目标

- 数据库统一由 Docker 管理
- 后端默认连接 PostgreSQL
- 不再依赖本地 `.db` 文件
- 默认使用固定命名卷，避免因 Compose 项目名变化误连到新空卷

## 启动步骤

最简单方式：

```bash
make dev-up
```

脚本会自动：

- 启动 Docker PostgreSQL
- 等数据库健康
- 同时以热更新模式启动 backend 和 frontend

如果你想把前后端也放进 Docker 容器里运行，并保留热更新：

```bash
make dev-docker-up
```

其中：

- backend 使用 `uvicorn --reload`
- frontend 使用 Vite HMR，并开启 polling 以兼容 Docker 挂载目录

如果你要手动分步执行：

1. 在项目根目录启动数据库

```bash
docker compose up -d postgres
```

2. 启动后端

```bash
cd backend
cp .env.example .env
uv run python -m devtools.schema init
ASHARE_RELOAD=true uv run python -m app
```

## 推荐连接

官方开发入口会显式使用：

```bash
postgresql+psycopg://ashare:ashare@127.0.0.1:5433/ashare_ai_trader
```

如果你要改连接串，在 `backend/.env` 中覆盖 `ASHARE_DATABASE_URL` 即可。
任意临时 `uv run python ...` 命令如果没有显式数据库连接，现在会直接失败，不再静默写入默认 PostgreSQL。

当前默认持久化卷名为：

```bash
ashare-ai-trader_ashare_postgres_data
```

只要不执行 `docker compose down -v`，普通容器重启、`docker compose down`、宿主机重启后再次拉起，都仍然会复用这个本地 volume。

## 账户初始化

- `devtools.schema init` 只负责准备表结构，不会自动创建任何用户
- 首次启动后请通过前端或 `POST /api/users` 创建账户
- 当前开发工具中不再提供“删库重建”入口
- 如果你需要本地测试数据，可执行 `cd backend && ASHARE_CONFIRM_RESTORE_TEST_USER=1 uv run python -m devtools.restore_test_user`
- 如果你已经保留了用户和成交事实，只想按新结算口径重建衍生层，可执行 `cd backend && ASHARE_CONFIRM_REBUILD_DERIVED_DATA=1 uv run python -m devtools.rebuild_derived_data`
- 如果你要在空库里初始化样例账户（新库未建表，或已建表但仍无业务数据），必须显式执行 `cd backend && ASHARE_CONFIRM_SAMPLE_ACCOUNT_INIT=INIT_SAMPLE_ACCOUNT uv run python -m devtools.sample_account`
  该脚本会先补齐空库表结构；若检测到已有业务数据，会直接拒绝，不会覆盖原库

## 入库建议

目前推荐保持 4 类数据分层入库：

1. 指令导入：写 `import_batches`、`import_batch_items`、`instruction_orders`
2. 成交回报：写 `execution_trades`、`cash_ledger`、`position_lots`
3. 实时行情：仅盘中轮巡并写 `intraday_quotes`
4. 午休/收盘冻结：交易日午休写非 final 快照，收盘写 final 快照；周末/节假日不为当天写 `daily_pnl`

价格和重建规则：

- 历史日线和 EOD 统一使用 raw 价格口径（腾讯 `bfq`）
- `rebuild_derived_data` 只重建 `eod_prices`、`daily_pnl`、`daily_pnl_details`
- 用户、成交、持仓和现金流水属于事实层，不在重建脚本内删除

## 常用命令

查看数据库状态：

```bash
docker compose ps
```

查看 PostgreSQL 日志：

```bash
docker compose logs -f postgres
```

停止数据库：

```bash
docker compose down
```

连同数据卷一起删除：

```bash
docker compose down -v
```

`docker compose down -v` 会直接删除持久化卷，只应在你确认不再需要当前数据、且已经完成备份时使用。
