import {
  ImportBatchStatus,
  ImportMode,
  ImportSourceType,
  Prisma,
  type OrderSide,
  type OrderStatus,
  type OrderValidity
} from "@prisma/client";
import { getMarketSession } from "./market.js";
import { getAvailableSellableSharesBySymbol, getPendingSellOrdersBySymbol } from "./order-reservation.js";
import { recomputeDailyPnl } from "./pnl-service.js";
import { prisma } from "./prisma.js";
import { getLastQuoteUpdateAt, getQuote, setQuotes } from "./quote-store.js";
import { seedCashBalance, seedDailyPnl, seedHistoricalQuotesByDate, seedInstructionOrders } from "./seed-data.js";
import type { DailyPnlDetailRow, HistoryRow, ImportPreviewRow, PendingOrderRow, PositionRow, PositionViewRow } from "./types.js";

const decimalToNumber = (value: Prisma.Decimal | number | null | undefined) => Number(value ?? 0);

function formatDateTime(date: Date) {
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai",
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(date);
}

function formatSeedMarketTime(value: string) {
  return value
    .replace("T", " ")
    .replace(/\.\d{3}Z$/, "")
    .slice(0, 19);
}

function seedTimestamp(value: string) {
  return value.length === 16 ? `${value}:00.000Z` : value;
}

export async function ensureSeedData() {
  const count = await prisma.instructionOrder.count();
  if (count > 0) {
    return;
  }

  await prisma.cashLedger.create({
    data: {
      entryType: "INITIAL",
      amount: new Prisma.Decimal(seedCashBalance),
      balanceAfter: new Prisma.Decimal(seedCashBalance),
      entryTime: new Date("2026-03-16T09:30:00.000Z")
    }
  });

  for (const order of seedInstructionOrders) {
    const createdOrder = await prisma.instructionOrder.create({
      data: {
        tradeDate: order.tradeDate,
        symbol: order.symbol,
        symbolName: order.symbolName,
        side: order.side as OrderSide,
        limitPrice: new Prisma.Decimal(order.limitPrice),
        lots: order.lots,
        shares: order.shares,
        validity: order.validity as OrderValidity,
        status: order.status as OrderStatus,
        statusReason: order.statusReason,
        triggeredAt: order.triggeredAt ? new Date(seedTimestamp(order.triggeredAt)) : null,
        filledAt: order.filledAt ? new Date(seedTimestamp(order.filledAt)) : null,
        createdAt: new Date(seedTimestamp(order.createdAt)),
        updatedAt: new Date(seedTimestamp(order.updatedAt)),
      }
    });

    await prisma.orderEvent.createMany({
      data: order.events.map((event) => ({
        orderId: createdOrder.id,
        eventType: event.eventType as OrderStatus,
        eventTime: new Date(seedTimestamp(event.eventTime)),
        message: event.message
      }))
    });

    if (!order.trade) {
      continue;
    }

    await prisma.executionTrade.create({
      data: {
        orderId: createdOrder.id,
        symbol: order.trade.symbol,
        side: order.trade.side as OrderSide,
        orderPrice: new Prisma.Decimal(order.trade.orderPrice),
        fillPrice: new Prisma.Decimal(order.trade.fillPrice),
        costBasisAmount: new Prisma.Decimal(order.trade.costBasisAmount ?? 0),
        realizedPnl: new Prisma.Decimal(order.trade.realizedPnl ?? 0),
        lots: order.trade.lots,
        shares: order.trade.shares,
        fillTime: new Date(seedTimestamp(order.trade.fillTime)),
        cashAfter: new Prisma.Decimal(order.trade.cashAfter),
        positionAfter: order.trade.positionAfter
      }
    });

    if (order.trade.side === "BUY") {
      await prisma.positionLot.create({
        data: {
          symbol: order.symbol,
          symbolName: order.symbolName,
          openedOrderId: createdOrder.id,
          openedDate: order.tradeDate,
          openedAt: new Date(seedTimestamp(order.trade.fillTime)),
          costPrice: new Prisma.Decimal(order.trade.fillPrice),
          originalShares: order.trade.shares,
          remainingShares: order.trade.shares,
          sellableShares: 0,
          status: "OPEN"
        }
      });

      await prisma.cashLedger.create({
        data: {
          entryTime: new Date(seedTimestamp(order.trade.fillTime)),
          entryType: "BUY",
          amount: new Prisma.Decimal(-order.trade.costBasisAmount),
          balanceAfter: new Prisma.Decimal(order.trade.cashAfter),
          referenceId: createdOrder.id,
          referenceType: "InstructionOrder"
        }
      });

      continue;
    }

    let remaining = order.trade.shares;
    const lots = await prisma.positionLot.findMany({
      where: {
        symbol: order.symbol,
        status: "OPEN"
      },
      orderBy: { openedAt: "asc" }
    });

    for (const lot of lots) {
      if (remaining <= 0) {
        break;
      }

      const consumed = Math.min(lot.remainingShares, remaining);
      const nextRemainingShares = lot.remainingShares - consumed;
      const nextSellableShares = Math.max(0, lot.sellableShares - consumed);
      remaining -= consumed;

      await prisma.positionLot.update({
        where: { id: lot.id },
        data: {
          remainingShares: nextRemainingShares,
          sellableShares: nextSellableShares,
          status: nextRemainingShares === 0 ? "CLOSED" : "OPEN",
          closedAt: nextRemainingShares === 0 ? new Date(seedTimestamp(order.trade.fillTime)) : null
        }
      });
    }

    await prisma.cashLedger.create({
      data: {
        entryTime: new Date(seedTimestamp(order.trade.fillTime)),
        entryType: "SELL",
        amount: new Prisma.Decimal(order.trade.fillPrice * order.trade.shares),
        balanceAfter: new Prisma.Decimal(order.trade.cashAfter),
        referenceId: createdOrder.id,
        referenceType: "InstructionOrder"
      }
    });
  }

  const openLots = await prisma.positionLot.findMany({ where: { status: "OPEN" } });
  for (const lot of openLots) {
    await prisma.positionLot.update({
      where: { id: lot.id },
      data: { sellableShares: lot.remainingShares }
    });
  }

  for (const day of seedDailyPnl) {
    await prisma.dailyPnl.create({
      data: {
        tradeDate: day.tradeDate,
        totalAssets: new Prisma.Decimal(day.totalAssets),
        availableCash: new Prisma.Decimal(day.availableCash),
        positionMarketValue: new Prisma.Decimal(day.positionMarketValue),
        dailyPnl: new Prisma.Decimal(day.dailyPnl),
        dailyReturn: new Prisma.Decimal(day.dailyReturn),
        cumulativePnl: new Prisma.Decimal(day.cumulativePnl),
        buyAmount: new Prisma.Decimal(day.buyAmount),
        sellAmount: new Prisma.Decimal(day.sellAmount),
        tradeCount: day.tradeCount,
        details: {
          create: day.details.map((detail) => ({
            tradeDate: day.tradeDate,
            symbol: detail.symbol,
            symbolName: detail.symbolName,
            closingShares: detail.closingShares,
            buyPrice: new Prisma.Decimal(0),
            openPrice: new Prisma.Decimal(0),
            closePrice: new Prisma.Decimal(detail.closePrice),
            dailyPnl: new Prisma.Decimal(detail.dailyPnl),
            dailyReturn: new Prisma.Decimal(detail.dailyReturn)
          }))
        }
      }
    });
  }

  const sortedSeedDates = Object.keys(seedHistoricalQuotesByDate).sort();
  const latestSeedDate = sortedSeedDates[sortedSeedDates.length - 1];
  const latestQuotes = latestSeedDate ? seedHistoricalQuotesByDate[latestSeedDate] : undefined;
  if (latestQuotes) {
    setQuotes(latestQuotes);
  }
}

export async function getDashboardData() {
  const session = getMarketSession();
  await recomputeDailyPnl(session.tradeDate);
  const latestCash = await prisma.cashLedger.findFirst({ orderBy: { entryTime: "desc" } });
  const openLots = await prisma.positionLot.findMany({ where: { status: "OPEN" } });
  const latestDailyPnl = await prisma.dailyPnl.findUnique({ where: { tradeDate: session.tradeDate } });

  const positionMarketValue = openLots.reduce(
    (sum, row) => {
      const quotePrice = getQuote(row.symbol)?.price ?? decimalToNumber(row.costPrice);
      return sum + row.remainingShares * quotePrice;
    },
    0
  );
  const availableCash = decimalToNumber(latestCash?.balanceAfter);
  const totalAssets = availableCash + positionMarketValue;

  return {
    tradeDate: session.tradeDate,
    marketStatus: session.marketStatus,
    updatedAt: getLastQuoteUpdateAt() ?? new Date().toISOString(),
    metrics: {
      totalAssets,
      availableCash,
      positionMarketValue,
      dailyPnl: decimalToNumber(latestDailyPnl?.dailyPnl),
      cumulativePnl: decimalToNumber(latestDailyPnl?.cumulativePnl),
      exposureRatio: totalAssets === 0 ? 0 : positionMarketValue / totalAssets
    }
  };
}

export async function getPositionsData(): Promise<PositionViewRow[]> {
  const session = getMarketSession();
  const lots = await prisma.positionLot.findMany({ where: { status: "OPEN" }, orderBy: { symbol: "asc" } });
  const pendingSellOrdersBySymbol = await getPendingSellOrdersBySymbol();
  const previousDailyPnl = await prisma.dailyPnl.findFirst({
    where: { tradeDate: { lt: session.tradeDate } },
    orderBy: { tradeDate: "desc" },
    include: { details: true }
  });
  const previousCloseBySymbol = new Map(
    (previousDailyPnl?.details ?? []).map((row) => [row.symbol, decimalToNumber(row.closePrice)])
  );
  const grouped = new Map<string, PositionRow>();

  for (const lot of lots) {
    const current = grouped.get(lot.symbol);
    const shares = lot.remainingShares;
    const price = decimalToNumber(lot.costPrice);

    if (!current) {
        grouped.set(lot.symbol, {
          symbol: lot.symbol,
          name: lot.symbolName ?? lot.symbol,
          shares,
          sellableShares: lot.sellableShares,
          frozenSellShares: 0,
          costPrice: price,
          lastPrice: price,
          todayPnl: 0,
          todayReturn: 0
        });
        continue;
      }

    const totalShares = current.shares + shares;
    current.costPrice = (current.costPrice * current.shares + price * shares) / totalShares;
    current.shares = totalShares;
    current.sellableShares += lot.sellableShares;
  }

  return Array.from(grouped.values())
    .map((row) => {
      const pendingOrders = pendingSellOrdersBySymbol.get(row.symbol) ?? [];
      const frozenSellShares = pendingOrders.reduce((sum, order) => sum + order.shares, 0);
      const displaySellableShares = Math.max(0, row.sellableShares - frozenSellShares);
      const quote = getQuote(row.symbol);
      const quotePrice = quote?.price ?? row.lastPrice;
      const previousClose = quote?.previousClose ?? previousCloseBySymbol.get(row.symbol) ?? row.costPrice;
      const marketValue = row.shares * quotePrice;
      const pnl = (quotePrice - row.costPrice) * row.shares;
      const returnRate = row.costPrice === 0 ? 0 : pnl / (row.costPrice * row.shares);
      const todayPnl = (quotePrice - previousClose) * row.shares;
      const todayReturn = previousClose === 0 ? 0 : (quotePrice - previousClose) / previousClose;
      return {
        ...row,
        sellableShares: displaySellableShares,
        frozenSellShares,
        lastPrice: quotePrice,
        todayPnl,
        todayReturn,
        marketValue,
        pnl,
        returnRate,
        pendingOrders: pendingOrders.map((order) => ({
          id: order.id,
          side: order.side,
          price: decimalToNumber(order.limitPrice),
          shares: order.shares,
          lots: order.lots,
          status: order.status as "confirmed" | "pending" | "triggered"
        }))
      };
    })
    .sort((a, b) => b.marketValue - a.marketValue);
}

export async function getPendingOrdersData(): Promise<PendingOrderRow[]> {
  const rows = await prisma.instructionOrder.findMany({
    where: { status: { in: ["confirmed", "pending", "triggered"] } },
    include: {
      events: { orderBy: { eventTime: "asc" } },
      trades: { orderBy: { fillTime: "asc" } }
    },
    orderBy: [{ tradeDate: "asc" }, { updatedAt: "desc" }]
  });

  return rows.map((row) => ({
    id: row.id,
    tradeDate: row.tradeDate,
    symbol: row.symbol,
    name: row.symbolName ?? row.symbol,
    side: row.side,
    orderPrice: decimalToNumber(row.limitPrice),
    lots: row.lots,
    shares: row.shares,
    validity: row.validity,
    status: row.status,
    statusMessage: row.statusReason ?? "",
    updatedAt: formatDateTime(row.updatedAt),
    detail: {
      orderText: `${row.tradeDate},${row.symbol},${row.side},${decimalToNumber(row.limitPrice).toFixed(2)},${row.lots},${row.validity}`,
      transitions: row.events.map((event) => ({
        at: formatDateTime(event.eventTime),
        status: event.eventType,
        message: event.message
      })),
      fillPrice: row.trades[0] ? decimalToNumber(row.trades[0].fillPrice) : undefined,
      fillTime: row.trades[0] ? formatDateTime(row.trades[0].fillTime) : undefined
    }
  }));
}

export async function getHistoryData(): Promise<HistoryRow[]> {
  const orders = await prisma.instructionOrder.findMany({
    include: {
      trades: { orderBy: { fillTime: "asc" } }
    },
    orderBy: { updatedAt: "desc" }
  });

  const rows: HistoryRow[] = [];

  for (const order of orders) {
    for (const trade of order.trades) {
      rows.push({
        id: trade.id,
        time: formatSeedMarketTime(trade.fillTime.toISOString()),
        fillTime: trade.fillTime.toISOString(),
        symbol: trade.symbol,
        name: order.symbolName ?? trade.symbol,
        side: trade.side,
        orderPrice: decimalToNumber(trade.orderPrice),
        fillPrice: decimalToNumber(trade.fillPrice),
        lots: trade.lots,
        shares: trade.shares
      });
    }
  }

  return rows.sort((a, b) => b.fillTime.localeCompare(a.fillTime));
}

export async function getCalendarData() {
  const rows = await prisma.dailyPnl.findMany({ orderBy: { tradeDate: "asc" } });
  return rows.map((row) => ({
    date: row.tradeDate,
    dailyPnl: decimalToNumber(row.dailyPnl),
    dailyReturn: decimalToNumber(row.dailyReturn),
    tradeCount: row.tradeCount
  }));
}

export async function getDailyPnlDetailData(date: string): Promise<DailyPnlDetailRow[]> {
  const rows = await prisma.dailyPnlDetail.findMany({ where: { tradeDate: date }, orderBy: { symbol: "asc" } });
  return rows.map((row) => ({
    symbol: row.symbol,
    name: row.symbolName ?? row.symbol,
    openingShares: row.openingShares,
    closingShares: row.closingShares,
    buyShares: row.buyShares,
    sellShares: row.sellShares,
    buyPrice: decimalToNumber(row.buyPrice),
    sellPrice: decimalToNumber(row.sellPrice),
    openPrice: decimalToNumber(row.openPrice),
    closePrice: decimalToNumber(row.closePrice),
    realizedPnl: decimalToNumber(row.realizedPnl),
    unrealizedPnl: decimalToNumber(row.unrealizedPnl),
    dailyPnl: decimalToNumber(row.dailyPnl),
    dailyReturn: decimalToNumber(row.dailyReturn)
  }));
}

export async function previewImportData(payload: {
  targetTradeDate: string;
  mode?: "DRAFT" | "OVERWRITE" | "APPEND";
  sourceType?: "MANUAL" | "XLSX" | "CSV";
  fileName?: string;
  rows: Array<{ symbol: string; side: "BUY" | "SELL"; price: number; lots: number; validity: "DAY" | "GTC" }>;
}) {
  const { sellableBySymbol, reservedBySymbol, availableBySymbol } = await getAvailableSellableSharesBySymbol();

  const reservedSellLots = new Map<string, number>();

  const previewRows: ImportPreviewRow[] = payload.rows.map((row, index) => {
    let validationStatus: ImportPreviewRow["validationStatus"] = "VALID";
    let validationMessage = "校验通过";

    if (row.side === "SELL") {
      const shares = row.lots * 100;
      const batchReservedShares = reservedSellLots.get(row.symbol) ?? 0;
      const sellableShares = sellableBySymbol.get(row.symbol) ?? 0;
      const reservedShares = reservedBySymbol.get(row.symbol) ?? 0;
      const availableShares = availableBySymbol.get(row.symbol) ?? 0;

      if (sellableShares === 0) {
        validationStatus = "ERROR";
        validationMessage = "当前无可卖仓位";
      } else if (reservedShares >= sellableShares || availableShares === 0) {
        validationStatus = "ERROR";
        validationMessage = "当前可卖仓位已被其他卖单占用";
      } else if (batchReservedShares + shares > availableShares) {
        validationStatus = "WARNING";
        validationMessage = "卖单与已有挂单存在仓位冲突，请确认";
      }

      reservedSellLots.set(row.symbol, batchReservedShares + shares);
    }

    return {
      rowNumber: index + 1,
      symbol: row.symbol,
      side: row.side,
      price: row.price,
      lots: row.lots,
      validity: row.validity,
      validationStatus,
      validationMessage
    };
  });

  return createImportBatchFromRows({
    targetTradeDate: payload.targetTradeDate,
    sourceType: payload.sourceType ?? "MANUAL",
    fileName: payload.fileName,
    mode: payload.mode ?? "DRAFT",
    rows: previewRows
  });
}

export async function createImportBatchFromRows(payload: {
  targetTradeDate: string;
  sourceType: "MANUAL" | "XLSX" | "CSV";
  fileName?: string;
  mode: "DRAFT" | "OVERWRITE" | "APPEND";
  rows: ImportPreviewRow[];
}) {
  const previewRows = payload.rows;

  const batch = await prisma.importBatch.create({
    data: {
      targetTradeDate: payload.targetTradeDate,
      sourceType: (payload.sourceType ?? "MANUAL") as ImportSourceType,
      fileName: payload.fileName,
      mode: (payload.mode ?? "DRAFT") as ImportMode,
      status: "VALIDATED",
      items: {
        create: previewRows.map((row) => ({
          rowNumber: row.rowNumber,
          symbol: row.symbol,
          side: row.side,
          limitPrice: new Prisma.Decimal(row.price),
          lots: row.lots,
          validity: row.validity,
          validationStatus: row.validationStatus,
          validationMessage: row.validationMessage
        }))
      }
    }
  });

  return { batchId: batch.id, targetTradeDate: payload.targetTradeDate, rows: previewRows };
}

export async function commitImportBatch(batchId: string, mode: "OVERWRITE" | "APPEND" | "DRAFT") {
  const batch = await prisma.importBatch.findUnique({ include: { items: true }, where: { id: batchId } });
  if (!batch) {
    throw new Error("Import batch not found");
  }

  if (mode === "OVERWRITE") {
    await prisma.instructionOrder.deleteMany({ where: { tradeDate: batch.targetTradeDate } });
  }

  if (mode !== "DRAFT") {
    await prisma.instructionOrder.createMany({
      data: batch.items
        .filter((item) => item.validationStatus !== "ERROR")
        .map((item) => ({
          tradeDate: batch.targetTradeDate,
          symbol: item.symbol,
          side: item.side,
          limitPrice: item.limitPrice,
          lots: item.lots,
          shares: item.lots * 100,
          validity: item.validity,
          status: "confirmed",
          statusReason: "已导入待执行"
        }))
    });
  }

  await prisma.importBatch.update({
    where: { id: batchId },
    data: { status: mode === "DRAFT" ? ImportBatchStatus.VALIDATED : ImportBatchStatus.COMMITTED, mode }
  });

  return {
    batchId,
    targetTradeDate: batch.targetTradeDate,
    mode,
    importedCount: batch.items.filter((item) => item.validationStatus !== "ERROR").length
  };
}
