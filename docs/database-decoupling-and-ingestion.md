# 数据库解耦与数据入库方案

## 1. 当前改动

本次已经落地 3 个关键调整：

1. 运行库与代码目录解耦
   默认库从仓库内的 `backend/data/ashare_ai_trader.db` 挪到 `~/.ashare-ai-trader/ashare_ai_trader.db`。

2. 启动初始化与应用服务解耦
   建库、补 demo 数据、重算基线收益已抽到 `python -m app.bootstrap`。

3. 测试库与运行库解耦
   `pytest` 会自动使用临时 SQLite，不再覆盖你平时运行的数据库。

## 2. 今日收益归零的根因

`2026-03-19` 这类“今日收益重启后回到 `0.0%`”的问题，之前主要有两层原因：

1. 收盘结算会拿到上一交易日残留的 `quote_snapshots`，把当天错误封盘成 `is_final=1`
2. `GET /api/dashboard` 虽然会重算当日收益，但请求结束时没有统一提交事务，导致结果没真正落库

现在的处理方式是：

- 只有拿到“属于当前交易日”的行情快照，才允许把 `daily_prices` 和 `daily_pnl` 封成最终值
- 交易日已收盘但行情不新鲜时，只生成 `is_final=0` 的临时收益快照
- 请求级事务会统一提交，dashboard 触发的重算结果会真实落库

## 3. 推荐部署形态

### 开发环境

- 数据库：SQLite
- 连接：默认 `sqlite:///$HOME/.ashare-ai-trader/ashare_ai_trader.db`
- 用途：单机开发、自测、前后端联调

### 生产 / 多实例环境

- 数据库：PostgreSQL
- 应用只通过 `ASHARE_DATABASE_URL` 连接数据库
- demo 数据关闭：`ASHARE_BOOTSTRAP_DEMO_DATA=false`
- 首次部署先执行一次 `uv run python -m app.bootstrap --no-seed-demo`
- 如果使用 PostgreSQL，需要额外安装对应驱动后再启动

## 4. 入库分层

建议把数据拆成 4 条链路，分别入库：

### A. 指令数据

来源：

- 前端手工录入
- Excel / CSV 导入
- 外部策略系统推送

落库表：

- `import_batches`
- `import_batch_items`
- `instruction_orders`
- `order_events`

要求：

- 以 `batch_id + row_number` 保证幂等
- commit 时只做“指令入库”，不要和行情入库耦合

### B. 成交数据

来源：

- 模拟撮合引擎
- 券商回报

落库表：

- `execution_trades`
- `cash_ledger`
- `position_lots`

要求：

- 以 `order_id + fill_time + shares + fill_price` 做去重键
- 成交入库后立即重算当日 `daily_pnl`

### C. 实时行情

来源：

- 腾讯行情
- 其他实时行情源

落库表：

- `quote_snapshots`

要求：

- 主键维度保持 `symbol`
- 每次 upsert 都记录 `updated_at` 和 `source`
- 只把“当天快照”用于盘中收益和收盘封盘

### D. 日线与收益快照

来源：

- 收盘后由实时快照封盘
- 或者由外部 EOD 数据源批量导入

落库表：

- `daily_prices`
- `daily_pnl`
- `daily_pnl_details`

要求：

- `daily_prices(symbol, trade_date)` 幂等 upsert
- `daily_pnl(user_id, trade_date)` 幂等重算
- 当前交易日只有在市场数据完整时才置 `is_final=1`

## 5. 推荐入库时序

### 盘前

1. 导入下一交易日指令到 `instruction_orders`
2. 校验卖单仓位、现金和重复提交

### 盘中

1. 定时拉取实时行情，刷新 `quote_snapshots`
2. 撮合成交后写入 `execution_trades / cash_ledger / position_lots`
3. 每次成交后重算当日 `daily_pnl(is_final=0)`

### 收盘后

1. 检查 `quote_snapshots.updated_at` 是否属于当日
2. 若是，则固化到 `daily_prices`
3. 重算 `daily_pnl` 与 `daily_pnl_details`
4. 仅在行情完整时写 `is_final=1`
5. 让 `calendar` 只展示 `is_final=1` 的当日收益

### 夜间补数

1. 从正式 EOD 数据源批量导入 `daily_prices`
2. 对受影响交易日批量重算 `daily_pnl`
3. 覆盖临时封盘结果

## 6. 迁移步骤

### 从当前本地库切到新的默认运行库

1. 直接启动后端
2. 首次启动会自动把旧的 `backend/data/ashare_ai_trader.db` 复制到 `~/.ashare-ai-trader/ashare_ai_trader.db`
3. 后续运行只使用新路径

### 从 SQLite 切到外部数据库

1. 准备目标数据库和驱动
2. 设置 `ASHARE_DATABASE_URL`
3. 设置 `ASHARE_BOOTSTRAP_DEMO_DATA=false`
4. 执行 `uv run python -m app.bootstrap --no-seed-demo`
5. 通过批量脚本把旧库中的业务表迁移到新库
6. 回放或重算 `daily_pnl`

## 7. 后续建议

- 补一套正式迁移工具，把 SQLite 历史表批量搬到 PostgreSQL
- 给 `daily_prices` 增加数据完整性标记，例如 `is_final`、`source`、`updated_at`
- 把行情抓取服务独立成单独 worker，API 只负责读写业务表
- 长期建议补 Alembic 迁移，避免后续 schema 变更只能靠 `create_all`
