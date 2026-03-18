export const seedCashBalance = 500000;

export type SeedQuoteSnapshot = {
  symbol: string;
  name: string;
  price: number;
  open: number;
  previousClose: number;
  high: number;
  low: number;
  updatedAt: string;
};

export type SeedHistoricalQuotesByDate = Record<string, SeedQuoteSnapshot[]>;

export type SeedOrderEvent = {
  eventType: string;
  eventTime: string;
  message: string;
};

export type SeedOrderTrade = {
  symbol: string;
  side: string;
  orderPrice: number;
  fillPrice: number;
  costBasisAmount: number;
  realizedPnl: number;
  lots: number;
  shares: number;
  fillTime: string;
  cashAfter: number;
  positionAfter: number;
};

export type SeedInstructionOrder = {
  key: string;
  tradeDate: string;
  symbol: string;
  symbolName: string;
  side: string;
  limitPrice: number;
  lots: number;
  shares: number;
  validity: string;
  status: string;
  statusReason: string;
  triggeredAt?: string;
  filledAt?: string;
  createdAt: string;
  updatedAt: string;
  events: SeedOrderEvent[];
  trade?: SeedOrderTrade;
};

export type SeedDailyPnlRow = {
  tradeDate: string;
  totalAssets: number;
  availableCash: number;
  positionMarketValue: number;
  dailyPnl: number;
  dailyReturn: number;
  cumulativePnl: number;
  buyAmount: number;
  sellAmount: number;
  tradeCount: number;
  details: Array<{
    symbol: string;
    symbolName: string;
    openingShares: number;
    closingShares: number;
    buyShares: number;
    sellShares: number;
    buyPrice: number;
    sellPrice: number;
    openPrice: number;
    closePrice: number;
    realizedPnl: number;
    unrealizedPnl: number;
    dailyPnl: number;
    dailyReturn: number;
  }>;
};

export const seedInstructionOrders: SeedInstructionOrder[] = [
  {
    key: "seed_ord_1",
    tradeDate: "2026-03-16",
    symbol: "000547",
    symbolName: "航天发展",
    side: "BUY",
    limitPrice: 30.9,
    lots: 70,
    shares: 7000,
    validity: "DAY",
    status: "filled",
    statusReason: "成交完成",
    triggeredAt: "2026-03-16T09:45:00.000Z",
    filledAt: "2026-03-16T09:45:00.000Z",
    createdAt: "2026-03-16T09:35:00.000Z",
    updatedAt: "2026-03-16T09:45:00.000Z",
    events: [
      { eventType: "confirmed", eventTime: "2026-03-16T09:35:00.000Z", message: "已导入待执行" },
      { eventType: "pending", eventTime: "2026-03-16T09:40:00.000Z", message: "等待触发" },
      { eventType: "triggered", eventTime: "2026-03-16T09:45:00.000Z", message: "盘中价格达到买入条件" },
      { eventType: "filled", eventTime: "2026-03-16T09:45:00.000Z", message: "按 30.90 成交" }
    ],
    trade: {
      symbol: "000547",
      side: "BUY",
      orderPrice: 30.9,
      fillPrice: 30.9,
      costBasisAmount: 216300,
      realizedPnl: 0,
      lots: 70,
      shares: 7000,
      fillTime: "2026-03-16T09:45:00.000Z",
      cashAfter: 283700,
      positionAfter: 7000
    }
  },
  {
    key: "seed_ord_2",
    tradeDate: "2026-03-16",
    symbol: "000021",
    symbolName: "深科技",
    side: "BUY",
    limitPrice: 31.13,
    lots: 60,
    shares: 6000,
    validity: "DAY",
    status: "filled",
    statusReason: "成交完成",
    triggeredAt: "2026-03-16T10:02:00.000Z",
    filledAt: "2026-03-16T10:02:00.000Z",
    createdAt: "2026-03-16T09:50:00.000Z",
    updatedAt: "2026-03-16T10:02:00.000Z",
    events: [
      { eventType: "confirmed", eventTime: "2026-03-16T09:50:00.000Z", message: "已导入待执行" },
      { eventType: "pending", eventTime: "2026-03-16T09:55:00.000Z", message: "等待触发" },
      { eventType: "triggered", eventTime: "2026-03-16T10:02:00.000Z", message: "盘中价格达到买入条件" },
      { eventType: "filled", eventTime: "2026-03-16T10:02:00.000Z", message: "按 31.13 成交" }
    ],
    trade: {
      symbol: "000021",
      side: "BUY",
      orderPrice: 31.13,
      fillPrice: 31.13,
      costBasisAmount: 186780,
      realizedPnl: 0,
      lots: 60,
      shares: 6000,
      fillTime: "2026-03-16T10:02:00.000Z",
      cashAfter: 96920,
      positionAfter: 6000
    }
  },
  {
    key: "seed_ord_2b",
    tradeDate: "2026-03-16",
    symbol: "000021",
    symbolName: "深科技",
    side: "BUY",
    limitPrice: 31.39,
    lots: 10,
    shares: 1000,
    validity: "DAY",
    status: "filled",
    statusReason: "成交完成",
    triggeredAt: "2026-03-16T10:30:00.000Z",
    filledAt: "2026-03-16T10:30:00.000Z",
    createdAt: "2026-03-16T10:20:00.000Z",
    updatedAt: "2026-03-16T10:30:00.000Z",
    events: [
      { eventType: "confirmed", eventTime: "2026-03-16T10:20:00.000Z", message: "已导入待执行" },
      { eventType: "pending", eventTime: "2026-03-16T10:25:00.000Z", message: "等待触发" },
      { eventType: "triggered", eventTime: "2026-03-16T10:30:00.000Z", message: "盘中价格达到买入条件" },
      { eventType: "filled", eventTime: "2026-03-16T10:30:00.000Z", message: "按 31.39 成交" }
    ],
    trade: {
      symbol: "000021",
      side: "BUY",
      orderPrice: 31.39,
      fillPrice: 31.39,
      costBasisAmount: 31390,
      realizedPnl: 0,
      lots: 10,
      shares: 1000,
      fillTime: "2026-03-16T10:30:00.000Z",
      cashAfter: 65530,
      positionAfter: 7000
    }
  },
  {
    key: "seed_ord_2c",
    tradeDate: "2026-03-16",
    symbol: "000547",
    symbolName: "航天发展",
    side: "BUY",
    limitPrice: 30.98,
    lots: 10,
    shares: 1000,
    validity: "DAY",
    status: "filled",
    statusReason: "成交完成",
    triggeredAt: "2026-03-16T10:56:00.000Z",
    filledAt: "2026-03-16T10:56:00.000Z",
    createdAt: "2026-03-16T10:46:00.000Z",
    updatedAt: "2026-03-16T10:56:00.000Z",
    events: [
      { eventType: "confirmed", eventTime: "2026-03-16T10:46:00.000Z", message: "已导入待执行" },
      { eventType: "pending", eventTime: "2026-03-16T10:50:00.000Z", message: "等待触发" },
      { eventType: "triggered", eventTime: "2026-03-16T10:56:00.000Z", message: "盘中价格达到买入条件" },
      { eventType: "filled", eventTime: "2026-03-16T10:56:00.000Z", message: "按 30.98 成交" }
    ],
    trade: {
      symbol: "000547",
      side: "BUY",
      orderPrice: 30.98,
      fillPrice: 30.98,
      costBasisAmount: 30980,
      realizedPnl: 0,
      lots: 10,
      shares: 1000,
      fillTime: "2026-03-16T10:56:00.000Z",
      cashAfter: 34550,
      positionAfter: 8000
    }
  },
  {
    key: "seed_ord_3",
    tradeDate: "2026-03-17",
    symbol: "000547",
    symbolName: "航天发展",
    side: "SELL",
    limitPrice: 31.66,
    lots: 40,
    shares: 4000,
    validity: "DAY",
    status: "filled",
    statusReason: "成交完成",
    triggeredAt: "2026-03-17T10:00:00.000Z",
    filledAt: "2026-03-17T10:00:00.000Z",
    createdAt: "2026-03-17T09:40:00.000Z",
    updatedAt: "2026-03-17T10:00:00.000Z",
    events: [
      { eventType: "confirmed", eventTime: "2026-03-17T09:40:00.000Z", message: "已导入待执行" },
      { eventType: "pending", eventTime: "2026-03-17T09:45:00.000Z", message: "等待触发" },
      { eventType: "triggered", eventTime: "2026-03-17T10:00:00.000Z", message: "盘中价格达到卖出条件" },
      { eventType: "filled", eventTime: "2026-03-17T10:00:00.000Z", message: "按 31.66 成交" }
    ],
    trade: {
      symbol: "000547",
      side: "SELL",
      orderPrice: 31.66,
      fillPrice: 31.66,
      costBasisAmount: 123600,
      realizedPnl: 3040,
      lots: 40,
      shares: 4000,
      fillTime: "2026-03-17T10:00:00.000Z",
      cashAfter: 161190,
      positionAfter: 4000
    }
  },
  {
    key: "seed_ord_4",
    tradeDate: "2026-03-17",
    symbol: "000021",
    symbolName: "深科技",
    side: "SELL",
    limitPrice: 32.47,
    lots: 30,
    shares: 3000,
    validity: "DAY",
    status: "filled",
    statusReason: "成交完成",
    triggeredAt: "2026-03-17T14:00:00.000Z",
    filledAt: "2026-03-17T14:00:00.000Z",
    createdAt: "2026-03-17T13:30:00.000Z",
    updatedAt: "2026-03-17T14:00:00.000Z",
    events: [
      { eventType: "confirmed", eventTime: "2026-03-17T13:30:00.000Z", message: "已导入待执行" },
      { eventType: "pending", eventTime: "2026-03-17T13:35:00.000Z", message: "等待触发" },
      { eventType: "triggered", eventTime: "2026-03-17T14:00:00.000Z", message: "盘中价格达到卖出条件" },
      { eventType: "filled", eventTime: "2026-03-17T14:00:00.000Z", message: "按 32.47 成交" }
    ],
    trade: {
      symbol: "000021",
      side: "SELL",
      orderPrice: 32.47,
      fillPrice: 32.47,
      costBasisAmount: 93390,
      realizedPnl: 4020,
      lots: 30,
      shares: 3000,
      fillTime: "2026-03-17T14:00:00.000Z",
      cashAfter: 258600,
      positionAfter: 4000
    }
  },
  {
    key: "seed_ord_4b",
    tradeDate: "2026-03-17",
    symbol: "000547",
    symbolName: "航天发展",
    side: "BUY",
    limitPrice: 31.11,
    lots: 10,
    shares: 1000,
    validity: "DAY",
    status: "filled",
    statusReason: "成交完成",
    triggeredAt: "2026-03-17T13:28:00.000Z",
    filledAt: "2026-03-17T13:28:00.000Z",
    createdAt: "2026-03-17T13:18:00.000Z",
    updatedAt: "2026-03-17T13:28:00.000Z",
    events: [
      { eventType: "confirmed", eventTime: "2026-03-17T13:18:00.000Z", message: "已导入待执行" },
      { eventType: "pending", eventTime: "2026-03-17T13:23:00.000Z", message: "等待触发" },
      { eventType: "triggered", eventTime: "2026-03-17T13:28:00.000Z", message: "盘中价格达到买入条件" },
      { eventType: "filled", eventTime: "2026-03-17T13:28:00.000Z", message: "按 31.11 成交" }
    ],
    trade: {
      symbol: "000547",
      side: "BUY",
      orderPrice: 31.11,
      fillPrice: 31.11,
      costBasisAmount: 31110,
      realizedPnl: 0,
      lots: 10,
      shares: 1000,
      fillTime: "2026-03-17T13:28:00.000Z",
      cashAfter: 227490,
      positionAfter: 5000
    }
  },
  {
    key: "seed_ord_5",
    tradeDate: "2026-03-18",
    symbol: "000021",
    symbolName: "深科技",
    side: "SELL",
    limitPrice: 33.7,
    lots: 40,
    shares: 4000,
    validity: "DAY",
    status: "filled",
    statusReason: "成交完成",
    triggeredAt: "2026-03-18T14:20:00.000Z",
    filledAt: "2026-03-18T14:20:00.000Z",
    createdAt: "2026-03-18T13:50:00.000Z",
    updatedAt: "2026-03-18T14:20:00.000Z",
    events: [
      { eventType: "confirmed", eventTime: "2026-03-18T13:50:00.000Z", message: "已导入待执行" },
      { eventType: "pending", eventTime: "2026-03-18T13:55:00.000Z", message: "等待触发" },
      { eventType: "triggered", eventTime: "2026-03-18T14:20:00.000Z", message: "盘中价格达到卖出条件" },
      { eventType: "filled", eventTime: "2026-03-18T14:20:00.000Z", message: "按 33.70 成交" }
    ],
    trade: {
      symbol: "000021",
      side: "SELL",
      orderPrice: 33.7,
      fillPrice: 33.7,
      costBasisAmount: 124520,
      realizedPnl: 10280,
      lots: 40,
      shares: 4000,
      fillTime: "2026-03-18T14:20:00.000Z",
      cashAfter: 362290,
      positionAfter: 1000
    }
  },
  {
    key: "seed_ord_5b",
    tradeDate: "2026-03-18",
    symbol: "000547",
    symbolName: "航天发展",
    side: "BUY",
    limitPrice: 30.35,
    lots: 10,
    shares: 1000,
    validity: "DAY",
    status: "filled",
    statusReason: "成交完成",
    triggeredAt: "2026-03-18T09:35:00.000Z",
    filledAt: "2026-03-18T09:35:00.000Z",
    createdAt: "2026-03-18T09:25:00.000Z",
    updatedAt: "2026-03-18T09:35:00.000Z",
    events: [
      { eventType: "confirmed", eventTime: "2026-03-18T09:25:00.000Z", message: "已导入待执行" },
      { eventType: "pending", eventTime: "2026-03-18T09:30:00.000Z", message: "等待触发" },
      { eventType: "triggered", eventTime: "2026-03-18T09:35:00.000Z", message: "盘中价格达到买入条件" },
      { eventType: "filled", eventTime: "2026-03-18T09:35:00.000Z", message: "按 30.35 成交" }
    ],
    trade: {
      symbol: "000547",
      side: "BUY",
      orderPrice: 30.35,
      fillPrice: 30.35,
      costBasisAmount: 30350,
      realizedPnl: 0,
      lots: 10,
      shares: 1000,
      fillTime: "2026-03-18T09:35:00.000Z",
      cashAfter: 197140,
      positionAfter: 6000
    }
  },
  {
    key: "seed_ord_5c",
    tradeDate: "2026-03-18",
    symbol: "000021",
    symbolName: "深科技",
    side: "BUY",
    limitPrice: 32.94,
    lots: 10,
    shares: 1000,
    validity: "DAY",
    status: "filled",
    statusReason: "成交完成",
    triggeredAt: "2026-03-18T10:30:00.000Z",
    filledAt: "2026-03-18T10:30:00.000Z",
    createdAt: "2026-03-18T10:20:00.000Z",
    updatedAt: "2026-03-18T10:30:00.000Z",
    events: [
      { eventType: "confirmed", eventTime: "2026-03-18T10:20:00.000Z", message: "已导入待执行" },
      { eventType: "pending", eventTime: "2026-03-18T10:25:00.000Z", message: "等待触发" },
      { eventType: "triggered", eventTime: "2026-03-18T10:30:00.000Z", message: "盘中价格达到买入条件" },
      { eventType: "filled", eventTime: "2026-03-18T10:30:00.000Z", message: "按 32.94 成交" }
    ],
    trade: {
      symbol: "000021",
      side: "BUY",
      orderPrice: 32.94,
      fillPrice: 32.94,
      costBasisAmount: 32940,
      realizedPnl: 0,
      lots: 10,
      shares: 1000,
      fillTime: "2026-03-18T10:30:00.000Z",
      cashAfter: 194550,
      positionAfter: 5000
    }
  },
  {
    key: "seed_ord_5d",
    tradeDate: "2026-03-18",
    symbol: "000547",
    symbolName: "航天发展",
    side: "SELL",
    limitPrice: 31.67,
    lots: 20,
    shares: 2000,
    validity: "DAY",
    status: "filled",
    statusReason: "成交完成",
    triggeredAt: "2026-03-18T14:30:00.000Z",
    filledAt: "2026-03-18T14:30:00.000Z",
    createdAt: "2026-03-18T14:20:00.000Z",
    updatedAt: "2026-03-18T14:30:00.000Z",
    events: [
      { eventType: "confirmed", eventTime: "2026-03-18T14:20:00.000Z", message: "已导入待执行" },
      { eventType: "pending", eventTime: "2026-03-18T14:25:00.000Z", message: "等待触发" },
      { eventType: "triggered", eventTime: "2026-03-18T14:30:00.000Z", message: "盘中价格达到卖出条件" },
      { eventType: "filled", eventTime: "2026-03-18T14:30:00.000Z", message: "按 31.67 成交" }
    ],
    trade: {
      symbol: "000547",
      side: "SELL",
      orderPrice: 31.67,
      fillPrice: 31.67,
      costBasisAmount: 61800,
      realizedPnl: 1540,
      lots: 20,
      shares: 2000,
      fillTime: "2026-03-18T14:30:00.000Z",
      cashAfter: 257890,
      positionAfter: 4000
    }
  }
];

export const seedHistoricalQuotesByDate: SeedHistoricalQuotesByDate = {
  "2026-03-16": [
    {
      symbol: "sz000547",
      name: "航天发展",
      price: 31.87,
      open: 30.7,
      previousClose: 30.7,
      high: 31.88,
      low: 30.18,
      updatedAt: "2026-03-16T15:00:00.000Z"
    },
    {
      symbol: "sz000021",
      name: "深科技",
      price: 33.1,
      open: 30.9,
      previousClose: 30.9,
      high: 33.12,
      low: 30.55,
      updatedAt: "2026-03-16T15:00:00.000Z"
    }
  ],
  "2026-03-17": [
    {
      symbol: "sz000547",
      name: "航天发展",
      price: 30.49,
      open: 31.88,
      previousClose: 31.87,
      high: 32.35,
      low: 30.35,
      updatedAt: "2026-03-17T15:00:00.000Z"
    },
    {
      symbol: "sz000021",
      name: "深科技",
      price: 32.26,
      open: 32.47,
      previousClose: 33.1,
      high: 33.18,
      low: 32.12,
      updatedAt: "2026-03-17T15:00:00.000Z"
    }
  ],
  "2026-03-18": [
    {
      symbol: "sz000547",
      name: "航天发展",
      price: 31.4,
      open: 30.24,
      previousClose: 30.49,
      high: 32,
      low: 29.89,
      updatedAt: "2026-03-18T15:00:00.000Z"
    },
    {
      symbol: "sz000021",
      name: "深科技",
      price: 33.63,
      open: 32.77,
      previousClose: 32.26,
      high: 33.79,
      low: 32.51,
      updatedAt: "2026-03-18T15:00:00.000Z"
    }
  ]
};

export const seedDailyPnl: SeedDailyPnlRow[] = [
  {
    tradeDate: "2026-03-16",
    totalAssets: 521210,
    availableCash: 34550,
    positionMarketValue: 486660,
    dailyPnl: 21210,
    dailyReturn: 0.04242,
    cumulativePnl: 21210,
    buyAmount: 465450,
    sellAmount: 0,
    tradeCount: 4,
    details: [
      {
        symbol: "000547",
        symbolName: "航天发展",
        openingShares: 0,
        closingShares: 8000,
        buyShares: 8000,
        sellShares: 0,
        buyPrice: 30.91,
        sellPrice: 0,
        openPrice: 30.7,
        closePrice: 31.87,
        realizedPnl: 0,
        unrealizedPnl: 7680,
        dailyPnl: 7680,
        dailyReturn: 0.03106
      },
      {
        symbol: "000021",
        symbolName: "深科技",
        openingShares: 0,
        closingShares: 7000,
        buyShares: 7000,
        sellShares: 0,
        buyPrice: 31.17,
        sellPrice: 0,
        openPrice: 31.34,
        closePrice: 33.1,
        realizedPnl: 0,
        unrealizedPnl: 13530,
        dailyPnl: 13530,
        dailyReturn: 0.06127
      }
    ]
  },
  {
    tradeDate: "2026-03-17",
    totalAssets: 509600,
    availableCash: 227490,
    positionMarketValue: 282110,
    dailyPnl: -11610,
    dailyReturn: -0.02228,
    cumulativePnl: 9600,
    buyAmount: 31110,
    sellAmount: 224050,
    tradeCount: 3,
    details: [
      {
        symbol: "000547",
        symbolName: "航天发展",
        openingShares: 8000,
        closingShares: 5000,
        buyShares: 1000,
        sellShares: 4000,
        buyPrice: 30.95,
        sellPrice: 31.66,
        openPrice: 31.88,
        closePrice: 30.49,
        realizedPnl: 3040,
        unrealizedPnl: -3320,
        dailyPnl: -6360,
        dailyReturn: -0.02496
      },
      {
        symbol: "000021",
        symbolName: "深科技",
        openingShares: 7000,
        closingShares: 4000,
        buyShares: 0,
        sellShares: 3000,
        buyPrice: 31.2,
        sellPrice: 32.47,
        openPrice: 32.47,
        closePrice: 32.26,
        realizedPnl: 4020,
        unrealizedPnl: -3360,
        dailyPnl: -5250,
        dailyReturn: -0.02267
      }
    ]
  },
  {
    tradeDate: "2026-03-18",
    totalAssets: 521570,
    availableCash: 362340,
    positionMarketValue: 159230,
    dailyPnl: 11970,
    dailyReturn: 0.02349,
    cumulativePnl: 21570,
    buyAmount: 63290,
    sellAmount: 198140,
    tradeCount: 4,
    details: [
      {
        symbol: "000547",
        symbolName: "航天发展",
        openingShares: 5000,
        closingShares: 4000,
        buyShares: 1000,
        sellShares: 2000,
        buyPrice: 30.76,
        sellPrice: 31.67,
        openPrice: 30.24,
        closePrice: 31.4,
        realizedPnl: 1540,
        unrealizedPnl: 3780,
        dailyPnl: 6140,
        dailyReturn: 0.04027
      },
      {
        symbol: "000021",
        symbolName: "深科技",
        openingShares: 4000,
        closingShares: 1000,
        buyShares: 1000,
        sellShares: 4000,
        buyPrice: 32.94,
        sellPrice: 33.7,
        openPrice: 32.77,
        closePrice: 33.63,
        realizedPnl: 10280,
        unrealizedPnl: 690,
        dailyPnl: 6450,
        dailyReturn: 0.04981
      }
    ]
  }
];
