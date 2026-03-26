# Instruction-Driven A-share Paper Trading

## Product Scope

This system is an execution-style simulator.

- The user provides explicit instructions before market open.
- The system does not decide whether to buy or sell.
- The system listens to market prices and simulates fills strictly by instruction rules.
- The frontend focuses on five tabs: current positions, today orders, history ledger, daily PnL, and data import.

Version 1 does not calculate commissions, stamp duty, or transfer fees.

## Quote Source

Real-time quotes use Tencent Finance quote endpoints.

- Poll frequency: once per second
- Poll window: only during A-share market sessions
- No polling before open, during non-trading hours, or after close
- Recommended access mode: frontend calls backend proxy, backend calls Tencent API
- Historical daily bars and EOD settlement use raw prices (`bfq`), not qfq-adjusted prices

### Market Sessions

China timezone (`Asia/Shanghai`):

- `09:30:00 - 11:30:00`: trading
- `11:30:01 - 12:59:59`: lunch break, no polling
- `13:00:00 - 15:00:00`: trading
- before `09:30:00` or after `15:00:00`: no polling
- weekends: no polling
- official holidays: no polling

## Frontend Information Architecture

### Global Header

- System name
- Trade date
- Market status
- Last quote update time
- Total assets
- Available cash
- Position market value
- Daily PnL
- Cumulative PnL
- Exposure ratio

### Tabs

1. `Positions`
   - current holdings only
   - fields: symbol, name, shares, sellable shares, diluted cost, last price, market value, cumulative PnL, return rate, today PnL
2. `Today Orders`
   - today's instructions and real-time status transitions
3. `History Ledger`
   - instruction, trigger, trade, expire, reject history
4. `Daily PnL`
   - monthly calendar and per-day profit detail table
5. `Data Import`
   - manual instruction entry and Excel/CSV import for next day actions

## Database Design

The database is designed around the frontend tabs and execution rules.

### 1. `instruction_orders`

Stores original user instructions.

Core fields:

- `id`
- `trade_date`
- `symbol`
- `symbol_name`
- `side` (`BUY`, `SELL`)
- `limit_price`
- `lots`
- `shares`
- `validity` (`DAY`, `GTC`)
- `note`
- `status` (`confirmed`, `pending`, `triggered`, `filled`, `expired`, `rejected`)
- `status_reason`
- `triggered_at`
- `filled_at`
- `created_at`
- `updated_at`

Supports tab: `Today Orders`

### 2. `order_events`

Stores all instruction lifecycle changes.

Core fields:

- `id`
- `order_id`
- `event_type` (`confirmed`, `pending`, `triggered`, `filled`, `expired`, `rejected`)
- `event_time`
- `message`
- `metadata_json`

Supports tabs: `Today Orders`, `History Ledger`

### 3. `execution_trades`

Stores simulated fills.

Core fields:

- `id`
- `order_id`
- `symbol`
- `side`
- `order_price`
- `fill_price`
- `cost_basis_amount`
- `realized_pnl`
- `lots`
- `shares`
- `fill_time`
- `cash_after`
- `position_after`

Supports tabs: `History Ledger`, `Daily PnL`

### 4. `position_lots`

Stores lot-level positions for T+1 and sellable share calculation.

Core fields:

- `id`
- `symbol`
- `symbol_name`
- `opened_order_id`
- `opened_trade_id`
- `opened_date`
- `opened_at`
- `cost_price`
- `original_shares`
- `remaining_shares`
- `sellable_shares`
- `status` (`OPEN`, `CLOSED`)
- `closed_at`

Supports tabs: `Positions`, `History Ledger`

Design note:

- `sellable_shares` is the direct frontend field.
- T+1 is not shown as a separate UI column in version 1.
- T+1 restriction is reflected by how `sellable_shares` is calculated.

### 5. `cash_ledger`

Stores cash changes.

Core fields:

- `id`
- `entry_time`
- `entry_type` (`INITIAL`, `BUY`, `SELL`, `MANUAL_ADJUSTMENT`)
- `amount`
- `reference_id`
- `reference_type`
- `note`

Global header metrics should be computed from `amount` over time, not from write-time balance snapshots.

### 6. `daily_pnl`

Stores daily aggregated results.

Core fields:

- `id`
- `trade_date`
- `total_assets`
- `available_cash`
- `position_market_value`
- `daily_pnl`
- `daily_return`
- `cumulative_pnl`
- `buy_amount`
- `sell_amount`
- `trade_count`

Supports tabs: `Daily PnL`, global header

Settlement rules:

- Trading session may compute temporary metrics, but does not persist `daily_pnl`
- Lunch break persists a non-final snapshot for the current trade date
- Market close persists the final snapshot for the current trade date
- Weekend and holiday sessions do not create `daily_pnl` rows for that date
- Query-side reads may self-heal missing lunch/close snapshots by running the same settlement path used by the engine

### 7. `daily_pnl_details`

Stores per-symbol detail for a selected day.

Core fields:

- `id`
- `trade_date`
- `symbol`
- `symbol_name`
- `opening_shares`
- `closing_shares`
- `buy_shares`
- `sell_shares`
- `buy_price`
- `sell_price`
- `open_price`
- `close_price`
- `daily_pnl`
- `daily_return`

Supports tab: `Daily PnL`

Design note:

- Daily detail exposes only the unified per-symbol `daily_pnl` result. It does not split realized and unrealized fields at the API layer.

### 8. `import_batches`

Stores each import session for next-day instructions.

Core fields:

- `id`
- `target_trade_date`
- `source_type` (`MANUAL`, `XLSX`, `CSV`)
- `file_name`
- `mode` (`DRAFT`, `OVERWRITE`, `APPEND`)
- `status` (`PENDING`, `VALIDATED`, `COMMITTED`, `FAILED`)
- `created_at`

### 9. `import_batch_items`

Stores parsed rows before confirmation.

Core fields:

- `id`
- `batch_id`
- `row_number`
- `symbol`
- `side`
- `limit_price`
- `lots`
- `validity`
- `note`
- `validation_status` (`VALID`, `WARNING`, `ERROR`)
- `validation_message`

Supports tab: `Data Import`

## API Design

### Core Read APIs

- `GET /api/dashboard`
- `GET /api/positions`
- `GET /api/orders/today`
- `GET /api/history`
- `GET /api/pnl/calendar?month=2026-03`
- `GET /api/pnl/daily/:date`

### Import APIs

- `POST /api/imports/preview`
- `POST /api/imports/commit`

### Quote API

- `GET /api/quotes?symbols=sh600519,sz000001`

Response should include:

- `marketStatus`
- `updatedAt`
- `quotes[]`

## Implementation Notes

### Why use backend proxy for Tencent quotes

- Avoid frontend CORS issues
- Keep quote parsing logic in one place
- Allow future caching and rate limiting

### Why store `sellable_shares`

- Frontend directly needs sellable quantity
- T+1 becomes a derived execution rule, not an extra UI concept
- Sell validation is simpler and more explicit

### Why separate `order_events` and `execution_trades`

- `order_events` answers status history questions
- `execution_trades` answers fill and PnL questions

## Development Plan

### Phase 1

- Build frontend shell with 5 tabs
- Build backend mock APIs
- Add Tencent quote proxy
- Implement market-session-aware polling every second
- Finalize backend data schema

### Phase 2

- Connect frontend data import flow to backend preview and commit APIs
- Replace mock repositories with Python persistence
- Add execution engine and scheduled intraday checks

### Phase 3

- Add authentication and multi-account support
- Add trading day calendar support
- Add more complete validation and replay tools
