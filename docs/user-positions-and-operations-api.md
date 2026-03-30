# 用户接口说明：持仓明细与操作录入

本文档面向“用户侧接口调用”，用于说明如何按用户维度获取持仓信息，以及如何做操作录入的校验和提交。

当前本地后端地址：

```text
http://127.0.0.1:3101
```

当前文档里的实测结果基于本地环境抓取时间：

```text
2026-03-30
```

## 1. 用户区分方式

当前后端通过请求头 `x-user-id` 区分用户。

- 查询用户列表时，不需要传 `x-user-id`
- 查询持仓、录入操作时，需要传 `x-user-id`

示例：

```bash
curl -sS -H 'x-user-id: test-user' http://127.0.0.1:3101/api/positions
```

## 2. 查询当前可用用户

接口：

```text
GET /api/users
```

调用：

```bash
curl -sS http://127.0.0.1:3101/api/users
```

当前实测返回：

```json
{
  "rows": [
    {
      "id": "test-user",
      "name": "Test User",
      "initialCash": 500000.0,
      "createdAt": "2026-03-26T21:50:07.375713+08:00",
      "updatedAt": "2026-03-26T21:50:07.375722+08:00"
    },
    {
      "id": "usr_0f3fd5bea1884507",
      "name": "gqx",
      "initialCash": 500000.0,
      "createdAt": "2026-03-26T21:53:53.060927+08:00",
      "updatedAt": "2026-03-26T21:53:53.061832+08:00"
    },
    {
      "id": "usr_d2d94d8dfc4044d2",
      "name": "WSL",
      "initialCash": 500000.0,
      "createdAt": "2026-03-27T14:49:07.097225+08:00",
      "updatedAt": "2026-03-27T14:49:07.097232+08:00"
    }
  ]
}
```

## 3. 获取用户持仓汇总

接口：

```text
GET /api/positions
```

请求头：

```text
x-user-id: <USER_ID>
```

示例调用：

```bash
curl -sS -H 'x-user-id: test-user' \
  http://127.0.0.1:3101/api/positions
```

当前实测返回：

```json
{
  "rows": [
    {
      "symbol": "000547",
      "name": "航天发展",
      "shares": 4000,
      "sellableShares": 3000,
      "frozenSellShares": 1000,
      "costPrice": 29.69,
      "lastPrice": 28.38,
      "marketValue": 113520.0,
      "pnl": -5240.0,
      "returnRate": -0.04412260020208825,
      "todayPnl": 4079.999999999998,
      "todayReturn": 0.03728070175438595
    }
  ]
}
```

字段说明：

- `shares`：当前剩余持仓股数
- `sellableShares`：当前可卖股数，已经扣除了冻结中的卖单占用
- `frozenSellShares`：已被待执行卖单冻结的股数
- `costPrice`：摊薄成本价
- `lastPrice`：当前最新价格
- `marketValue`：当前持仓市值
- `pnl`：累计盈亏
- `todayPnl`：持仓视角的当日盈亏

## 4. 获取用户单只持仓明细

接口：

```text
GET /api/positions/{symbol}/detail
```

请求头：

```text
x-user-id: <USER_ID>
```

示例调用：

```bash
curl -sS -H 'x-user-id: test-user' \
  http://127.0.0.1:3101/api/positions/000547/detail
```

当前实测返回：

```json
{
  "tradeDate": "2026-03-30",
  "sellableTradeDate": "2026-03-30",
  "marketStatus": "trading",
  "position": {
    "symbol": "000547",
    "name": "航天发展",
    "shares": 4000,
    "sellableShares": 3000,
    "frozenSellShares": 1000,
    "costPrice": 29.69,
    "lastPrice": 28.37,
    "marketValue": 113480.0,
    "pnl": -5280.0,
    "returnRate": -0.04445941394408892,
    "todayPnl": 4040.0000000000064,
    "todayReturn": 0.03691520467836263
  },
  "lots": [
    {
      "id": "lot_7fc70d185f074320",
      "openedDate": "2026-03-16",
      "openedAt": "2026-03-16 09:45:00",
      "originalShares": 7000,
      "remainingShares": 1000,
      "sellableShares": 1000,
      "frozenSellShares": 1000,
      "availableSellableShares": 0,
      "costPrice": 30.9,
      "costAmount": 30900.0,
      "marketValue": 28370.0
    },
    {
      "id": "lot_1cf81140ea9849d3",
      "openedDate": "2026-03-16",
      "openedAt": "2026-03-16 10:56:00",
      "originalShares": 1000,
      "remainingShares": 1000,
      "sellableShares": 1000,
      "frozenSellShares": 0,
      "availableSellableShares": 1000,
      "costPrice": 30.98,
      "costAmount": 30980.0,
      "marketValue": 28370.0
    },
    {
      "id": "lot_d1dca9af4c744505",
      "openedDate": "2026-03-17",
      "openedAt": "2026-03-17 13:28:00",
      "originalShares": 1000,
      "remainingShares": 1000,
      "sellableShares": 1000,
      "frozenSellShares": 0,
      "availableSellableShares": 1000,
      "costPrice": 31.11,
      "costAmount": 31110.0,
      "marketValue": 28370.0
    },
    {
      "id": "lot_f6fda2f3eef34903",
      "openedDate": "2026-03-18",
      "openedAt": "2026-03-18 09:35:00",
      "originalShares": 1000,
      "remainingShares": 1000,
      "sellableShares": 1000,
      "frozenSellShares": 0,
      "availableSellableShares": 1000,
      "costPrice": 30.35,
      "costAmount": 30350.0,
      "marketValue": 28370.0
    }
  ],
  "pendingSellOrders": [
    {
      "id": "ord_d84e4cad26df4850",
      "tradeDate": "2026-03-30",
      "orderPrice": 29.0,
      "lots": 10,
      "shares": 1000,
      "validity": "DAY",
      "status": "pending",
      "statusMessage": "等待触发",
      "createdAt": "2026-03-27 19:29:13",
      "updatedAt": "2026-03-30 11:10:14"
    }
  ]
}
```

字段说明：

- `position`：该股票的持仓汇总
- `lots`：lot 级别的持仓明细
- `pendingSellOrders`：该股票当前待执行的卖单
- `availableSellableShares`：该 lot 还可继续卖出的股数

## 5. 操作录入校验

接口：

```text
POST /api/operations/validate
```

请求头：

```text
Content-Type: application/json
x-user-id: <USER_ID>
```

请求体：

```json
{
  "targetTradeDate": "2026-03-30",
  "mode": "APPEND",
  "rows": [
    {
      "symbol": "000547",
      "side": "SELL",
      "price": 29.00,
      "lots": 1,
      "validity": "DAY"
    }
  ]
}
```

示例调用：

```bash
curl -sS -X POST http://127.0.0.1:3101/api/operations/validate \
  -H 'Content-Type: application/json' \
  -H 'x-user-id: test-user' \
  -d '{
    "targetTradeDate": "2026-03-30",
    "mode": "APPEND",
    "rows": [
      {
        "symbol": "000547",
        "side": "SELL",
        "price": 29.00,
        "lots": 1,
        "validity": "DAY"
      }
    ]
  }'
```

当前实测返回：

```json
{
  "batchId": "imp_afd9bb49cbce45c1",
  "targetTradeDate": "2026-03-30",
  "fileName": null,
  "sourceType": "MANUAL",
  "rows": [
    {
      "rowNumber": 1,
      "tradeDate": "2026-03-30",
      "symbol": "000547",
      "name": "航天发展",
      "side": "SELL",
      "price": 29.0,
      "lots": 1,
      "validity": "DAY",
      "validationStatus": "VALID",
      "validationMessage": "校验通过"
    }
  ],
  "confirmation": {
    "required": false,
    "token": null,
    "items": []
  }
}
```

说明：

- `batchId` 是后续提交时要使用的批次号
- `validationStatus` 可能是 `VALID`、`WARNING`、`ERROR`
- 当前环境返回里还带了 `confirmation`，用于后续需要二次确认的场景

## 6. 操作录入提交

接口：

```text
POST /api/operations/submit
```

请求头：

```text
Content-Type: application/json
x-user-id: <USER_ID>
```

请求体：

```json
{
  "batchId": "imp_afd9bb49cbce45c1",
  "mode": "APPEND"
}
```

示例调用：

```bash
curl -sS -i -X POST http://127.0.0.1:3101/api/operations/submit \
  -H 'Content-Type: application/json' \
  -H 'x-user-id: test-user' \
  -d '{
    "batchId": "imp_afd9bb49cbce45c1",
    "mode": "APPEND"
  }'
```

当前实测返回：

```http
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"当前为交易时段，仅允许在休盘时提交导入"}
```

说明：

- 当前实测时刻是 `2026-03-30` 交易时段，所以提交被拒绝
- 在盘前、午休、收盘后或休市时，提交才允许成功

## 7. 常见错误码

- `404`
  - 用户不存在
  - 持仓不存在
  - 校验批次不存在
- `403`
  - 当前为交易时段，仅允许在休盘时提交导入
- `409`
  - 校验结果已变化，需要重新校验后再提交
  - 批次已提交，不能重复提交

## 8. 推荐调用顺序

用户侧如果要做完整操作，建议按这个顺序：

1. `GET /api/users` 获取用户列表
2. 选中目标用户后，后续请求统一带 `x-user-id`
3. `GET /api/positions` 获取持仓汇总
4. `GET /api/positions/{symbol}/detail` 获取单票持仓明细
5. `POST /api/operations/validate` 做录入校验
6. 在允许提交的时间窗口内调用 `POST /api/operations/submit`
