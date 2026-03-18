import { Prisma } from "@prisma/client";
import { getMarketSession, isMarketPollingWindow } from "./market.js";
import { getAvailableSellableSharesBySymbol } from "./order-reservation.js";
import { recomputeDailyPnl } from "./pnl-service.js";
import { prisma } from "./prisma.js";
import { getQuote, setQuotes, toQuoteSymbol } from "./quote-store.js";
import { fetchTencentQuotes } from "./tencent.js";

let engineStarted = false;
let engineBusy = false;

function decimalToNumber(value: Prisma.Decimal | number | null | undefined) {
  return Number(value ?? 0);
}

async function markConfirmedOrdersPending(tradeDate: string) {
  const confirmed = await prisma.instructionOrder.findMany({
    where: {
      status: "confirmed",
      OR: [{ tradeDate }, { validity: "GTC" }]
    }
  });

  for (const order of confirmed) {
    await prisma.instructionOrder.update({
      where: { id: order.id },
      data: {
        status: "pending",
        statusReason: "等待触发"
      }
    });

    await prisma.orderEvent.create({
      data: {
        orderId: order.id,
        eventType: "pending",
        message: "等待触发"
      }
    });
  }
}

async function rejectReservedSellConflicts(tradeDate: string) {
  const orders = await prisma.instructionOrder.findMany({
    where: {
      side: "SELL",
      status: { in: ["confirmed", "pending"] },
      OR: [{ tradeDate }, { validity: "GTC" }]
    },
    orderBy: { createdAt: "asc" }
  });

  const lots = await prisma.positionLot.findMany({ where: { status: "OPEN" } });
  const sellableBySymbol = new Map<string, number>();
  for (const lot of lots) {
    sellableBySymbol.set(lot.symbol, (sellableBySymbol.get(lot.symbol) ?? 0) + lot.sellableShares);
  }

  const reservedBySymbol = new Map<string, number>();
  for (const order of orders) {
    const reservedShares = reservedBySymbol.get(order.symbol) ?? 0;
    const sellableShares = sellableBySymbol.get(order.symbol) ?? 0;
    const availableShares = Math.max(0, sellableShares - reservedShares);

    if (order.shares > availableShares) {
      await prisma.instructionOrder.update({
        where: { id: order.id },
        data: {
          status: "rejected",
          statusReason: sellableShares === 0 ? "受 T+1 限制不可卖" : "卖单与其他挂单冲突，仓位已被占用"
        }
      });

      await prisma.orderEvent.create({
        data: {
          orderId: order.id,
          eventType: "rejected",
          message: sellableShares === 0 ? "受 T+1 限制不可卖" : "多条卖单重复占用同一仓位"
        }
      });
      continue;
    }

    reservedBySymbol.set(order.symbol, reservedShares + order.shares);
  }
}

async function expireDayOrders(tradeDate: string) {
  const session = getMarketSession();
  if (session.marketStatus !== "closed") {
    return;
  }

  const pendingOrders = await prisma.instructionOrder.findMany({
    where: {
      tradeDate,
      validity: "DAY",
      status: { in: ["confirmed", "pending", "triggered"] }
    }
  });

  for (const order of pendingOrders) {
    await prisma.instructionOrder.update({
      where: { id: order.id },
      data: {
        status: "expired",
        statusReason: "当日未触价已失效"
      }
    });

    await prisma.orderEvent.create({
      data: {
        orderId: order.id,
        eventType: "expired",
        message: "当日未触价已失效"
      }
    });
  }
}

async function fillBuy(orderId: string, price: number) {
  await prisma.$transaction(async (tx) => {
    const order = await tx.instructionOrder.findUnique({ where: { id: orderId } });
    if (!order || order.status === "filled") {
      return;
    }

    const latestCash = await tx.cashLedger.findFirst({ orderBy: { entryTime: "desc" } });
    const availableCash = decimalToNumber(latestCash?.balanceAfter);
    const amount = price * order.shares;

    if (availableCash < amount) {
      await tx.instructionOrder.update({
        where: { id: order.id },
        data: { status: "rejected", statusReason: "资金不足" }
      });
      await tx.orderEvent.create({ data: { orderId: order.id, eventType: "rejected", message: "资金不足" } });
      return;
    }

    await tx.orderEvent.create({ data: { orderId: order.id, eventType: "triggered", message: "盘中价格达到买入条件" } });

    const balanceAfter = availableCash - amount;

    await tx.executionTrade.create({
      data: {
        orderId: order.id,
        symbol: order.symbol,
        side: order.side,
        orderPrice: order.limitPrice,
        fillPrice: new Prisma.Decimal(price),
        costBasisAmount: new Prisma.Decimal(amount),
        realizedPnl: new Prisma.Decimal(0),
        lots: order.lots,
        shares: order.shares,
        fillTime: new Date(),
        cashAfter: new Prisma.Decimal(balanceAfter),
        positionAfter: order.shares
      }
    });

    await tx.positionLot.create({
      data: {
        symbol: order.symbol,
        symbolName: order.symbolName,
        openedOrderId: order.id,
        openedDate: order.tradeDate,
        openedAt: new Date(),
        costPrice: new Prisma.Decimal(price),
        originalShares: order.shares,
        remainingShares: order.shares,
        sellableShares: 0,
        status: "OPEN"
      }
    });

    await tx.cashLedger.create({
      data: {
        entryType: "BUY",
        amount: new Prisma.Decimal(-amount),
        balanceAfter: new Prisma.Decimal(balanceAfter),
        referenceId: order.id,
        referenceType: "InstructionOrder"
      }
    });

    await tx.orderEvent.create({ data: { orderId: order.id, eventType: "filled", message: `按 ${price.toFixed(2)} 成交` } });

    await tx.instructionOrder.update({
      where: { id: order.id },
      data: {
        status: "filled",
        statusReason: "成交完成",
        triggeredAt: new Date(),
        filledAt: new Date()
      }
    });
  });

  await recomputeDailyPnl();
}

async function fillSell(orderId: string, price: number) {
  await prisma.$transaction(async (tx) => {
    const order = await tx.instructionOrder.findUnique({ where: { id: orderId } });
    if (!order || order.status === "filled") {
      return;
    }

    const { availableBySymbol } = await getAvailableSellableSharesBySymbol(order.id);
    const availableShares = availableBySymbol.get(order.symbol) ?? 0;

    if (availableShares < order.shares) {
      await tx.instructionOrder.update({
        where: { id: order.id },
        data: { status: "rejected", statusReason: availableShares === 0 ? "仓位已被其他卖单占用" : "卖单与其他挂单冲突，仓位已被占用" }
      });
      await tx.orderEvent.create({
        data: {
          orderId: order.id,
          eventType: "rejected",
          message: availableShares === 0 ? "仓位已被其他卖单占用" : "多条卖单重复占用同一仓位"
        }
      });
      return;
    }

    const lots = await tx.positionLot.findMany({
      where: {
        symbol: order.symbol,
        status: "OPEN",
        sellableShares: { gt: 0 }
      },
      orderBy: { openedAt: "asc" }
    });

    const sellableShares = lots.reduce((sum, row) => sum + row.sellableShares, 0);
    if (sellableShares < order.shares) {
      await tx.instructionOrder.update({
        where: { id: order.id },
        data: { status: "rejected", statusReason: sellableShares === 0 ? "受 T+1 限制不可卖" : "可卖不足" }
      });
      await tx.orderEvent.create({
        data: {
          orderId: order.id,
          eventType: "rejected",
          message: sellableShares === 0 ? "受 T+1 限制不可卖" : "可卖数量不足"
        }
      });
      return;
    }

    await tx.orderEvent.create({ data: { orderId: order.id, eventType: "triggered", message: "盘中价格达到卖出条件" } });

    let remaining = order.shares;
    let positionAfter = 0;
    let consumedCostAmount = 0;

    for (const lot of lots) {
      if (remaining <= 0) {
        break;
      }

      const consumed = Math.min(lot.sellableShares, remaining);
      const nextRemainingShares = lot.remainingShares - consumed;
      const nextSellableShares = lot.sellableShares - consumed;
      consumedCostAmount += consumed * decimalToNumber(lot.costPrice);
      remaining -= consumed;
      positionAfter += nextRemainingShares;

      await tx.positionLot.update({
        where: { id: lot.id },
        data: {
          remainingShares: nextRemainingShares,
          sellableShares: nextSellableShares,
          status: nextRemainingShares === 0 ? "CLOSED" : "OPEN",
          closedAt: nextRemainingShares === 0 ? new Date() : null
        }
      });
    }

    const latestCash = await tx.cashLedger.findFirst({ orderBy: { entryTime: "desc" } });
    const availableCash = decimalToNumber(latestCash?.balanceAfter);
    const amount = price * order.shares;
    const balanceAfter = availableCash + amount;
    const realizedPnl = amount - consumedCostAmount;

    await tx.executionTrade.create({
      data: {
        orderId: order.id,
        symbol: order.symbol,
        side: order.side,
        orderPrice: order.limitPrice,
        fillPrice: new Prisma.Decimal(price),
        costBasisAmount: new Prisma.Decimal(consumedCostAmount),
        realizedPnl: new Prisma.Decimal(realizedPnl),
        lots: order.lots,
        shares: order.shares,
        fillTime: new Date(),
        cashAfter: new Prisma.Decimal(balanceAfter),
        positionAfter
      }
    });

    await tx.cashLedger.create({
      data: {
        entryType: "SELL",
        amount: new Prisma.Decimal(amount),
        balanceAfter: new Prisma.Decimal(balanceAfter),
        referenceId: order.id,
        referenceType: "InstructionOrder"
      }
    });

    await tx.orderEvent.create({ data: { orderId: order.id, eventType: "filled", message: `按 ${price.toFixed(2)} 成交` } });

    await tx.instructionOrder.update({
      where: { id: order.id },
      data: {
        status: "filled",
        statusReason: "成交完成",
        triggeredAt: new Date(),
        filledAt: new Date()
      }
    });
  });

  await recomputeDailyPnl();
}

async function processOrders(tradeDate: string) {
  const orders = await prisma.instructionOrder.findMany({
    where: {
      OR: [
        { tradeDate, status: { in: ["confirmed", "pending"] } },
        { validity: "GTC", status: { in: ["confirmed", "pending"] } }
      ]
    },
    orderBy: { createdAt: "asc" }
  });

  for (const order of orders) {
    const quote = getQuote(order.symbol);
    if (!quote || quote.price <= 0) {
      continue;
    }

    const shouldBuy = order.side === "BUY" && quote.price <= decimalToNumber(order.limitPrice);
    const shouldSell = order.side === "SELL" && quote.price >= decimalToNumber(order.limitPrice);

    if (!shouldBuy && !shouldSell) {
      continue;
    }

    if (order.side === "BUY") {
      await fillBuy(order.id, Math.min(quote.price, decimalToNumber(order.limitPrice)));
    } else {
      await fillSell(order.id, Math.max(quote.price, decimalToNumber(order.limitPrice)));
    }
  }
}

async function processOrder(orderId: string) {
  const order = await prisma.instructionOrder.findUnique({ where: { id: orderId } });
  if (!order || !["confirmed", "pending"].includes(order.status)) {
    return false;
  }

  const quote = getQuote(order.symbol);
  if (!quote || quote.price <= 0) {
    return false;
  }

  const shouldBuy = order.side === "BUY" && quote.price <= decimalToNumber(order.limitPrice);
  const shouldSell = order.side === "SELL" && quote.price >= decimalToNumber(order.limitPrice);

  if (!shouldBuy && !shouldSell) {
    return false;
  }

  if (order.side === "BUY") {
    await fillBuy(order.id, Math.min(quote.price, decimalToNumber(order.limitPrice)));
  } else {
    await fillSell(order.id, Math.max(quote.price, decimalToNumber(order.limitPrice)));
  }

  return true;
}

async function unlockPreviousLots(tradeDate: string) {
  const rows = await prisma.positionLot.findMany({
    where: {
      status: "OPEN",
      openedDate: { lt: tradeDate }
    }
  });

  for (const row of rows) {
    if (row.sellableShares !== row.remainingShares) {
      await prisma.positionLot.update({ where: { id: row.id }, data: { sellableShares: row.remainingShares } });
    }
  }
}

async function tickEngine() {
  if (engineBusy) {
    return;
  }

  engineBusy = true;
  try {
    const session = getMarketSession();
    await unlockPreviousLots(session.tradeDate);
    await markConfirmedOrdersPending(session.tradeDate);
    await rejectReservedSellConflicts(session.tradeDate);

    if (!isMarketPollingWindow()) {
      await recomputeDailyPnl(session.tradeDate);
      await expireDayOrders(session.tradeDate);
      return;
    }

    const activeOrders = await prisma.instructionOrder.findMany({
      where: {
        OR: [
          { tradeDate: session.tradeDate, status: { in: ["pending", "confirmed"] } },
          { validity: "GTC", status: { in: ["pending", "confirmed"] } }
        ]
      },
      select: { symbol: true }
    });

    const positionSymbols = await prisma.positionLot.findMany({ where: { status: "OPEN" }, select: { symbol: true } });
    const symbols = Array.from(
      new Set([...activeOrders.map((row) => row.symbol), ...positionSymbols.map((row) => row.symbol)]).values()
    ).map((symbol) => toQuoteSymbol(symbol));

    if (symbols.length > 0) {
      const quotes = await fetchTencentQuotes(symbols);
      setQuotes(quotes);
    }

    await processOrders(session.tradeDate);
    await recomputeDailyPnl(session.tradeDate);
  } catch (error) {
    console.error("Execution engine tick failed", error);
  } finally {
    engineBusy = false;
  }
}

export async function runExecutionEngineTick() {
  await tickEngine();
}

export async function processInjectedOrder(orderId: string) {
  const session = getMarketSession();
  await unlockPreviousLots(session.tradeDate);
  await markConfirmedOrdersPending(session.tradeDate);
  await rejectReservedSellConflicts(session.tradeDate);
  return processOrder(orderId);
}

export function startExecutionEngine() {
  if (engineStarted) {
    return;
  }

  engineStarted = true;
  void tickEngine();
  setInterval(() => {
    void tickEngine();
  }, 1000);
}
