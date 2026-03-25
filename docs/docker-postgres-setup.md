# Docker PostgreSQL 方案

## 目标

- 数据库统一由 Docker 管理
- 后端默认连接 PostgreSQL
- 不再依赖本地 `.db` 文件

## 启动步骤

最简单方式：

```bash
make dev-up
```

脚本会自动：

- 启动 Docker PostgreSQL
- 等数据库健康
- 执行 `bootstrap`
- 同时启动 backend 和 frontend

如果你要手动分步执行：

1. 在项目根目录启动数据库

```bash
docker compose up -d postgres
```

2. 初始化表结构

```bash
cd backend
uv run python -m app.bootstrap
```

3. 启动后端

```bash
cd backend
uv run python -m app
```

## 默认连接

后端默认连接：

```bash
postgresql+psycopg://ashare:ashare@127.0.0.1:5433/ashare_ai_trader
```

如果你要改连接串，在 `backend/.env` 中覆盖 `ASHARE_DATABASE_URL` 即可。

## 账户初始化

- `bootstrap` 不会自动创建任何用户
- 首次启动后请通过前端或 `POST /api/users` 创建账户
- 如果你需要测试数据，请直接写入数据库，不依赖仓库内置 seed

## 入库建议

目前推荐保持 4 类数据分层入库：

1. 指令导入：写 `import_batches`、`import_batch_items`、`instruction_orders`
2. 成交回报：写 `execution_trades`、`cash_ledger`、`position_lots`
3. 实时行情：仅盘中轮巡并写 `intraday_quotes`
4. 午休/收盘冻结：在阶段切换时写 `eod_prices`、`daily_pnl`、`daily_pnl_details`

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
