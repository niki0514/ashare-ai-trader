import { Prisma } from "@prisma/client";
import { getMarketSession } from "./market.js";
import { prisma } from "./prisma.js";
import { getQuote } from "./quote-store.js";

const decimalToNumber = (value: Prisma.Decimal | number | null | undefined) => Number(value ?? 0);

function getPositionSnapshotValue(symbol: string, shares: number, fallbackPrice: number) {
  const quote = getQuote(symbol);
  const quotePrice = quote?.price ?? fallbackPrice;
  return {
    openPrice: quote?.open ?? fallbackPrice,
    closePrice: quotePrice,
    marketValue: shares * quotePrice
  };
}

export async function recomputeDailyPnl(tradeDate = getMarketSession().tradeDate) {
  const latestCash = await prisma.cashLedger.findFirst({ orderBy: { entryTime: "desc" } });
  const availableCash = decimalToNumber(latestCash?.balanceAfter);

  const openLots = await prisma.positionLot.findMany({ where: { status: "OPEN" }, orderBy: { symbol: "asc" } });
  const grouped = new Map<
    string,
    { symbol: string; symbolName: string; shares: number; costAmount: number; fallbackPrice: number }
  >();

  for (const lot of openLots) {
    const current = grouped.get(lot.symbol);
    const lotCostPrice = decimalToNumber(lot.costPrice);
    const lotCostAmount = lot.remainingShares * lotCostPrice;

    if (!current) {
      grouped.set(lot.symbol, {
        symbol: lot.symbol,
        symbolName: lot.symbolName ?? lot.symbol,
        shares: lot.remainingShares,
        costAmount: lotCostAmount,
        fallbackPrice: lotCostPrice
      });
      continue;
    }

    current.shares += lot.remainingShares;
    current.costAmount += lotCostAmount;
  }

  const previousDay = await prisma.dailyPnl.findFirst({
    where: { tradeDate: { lt: tradeDate } },
    orderBy: { tradeDate: "desc" },
    include: { details: true }
  });
  const firstDay = await prisma.dailyPnl.findFirst({ orderBy: { tradeDate: "asc" } });

  const previousDetails = new Map(
    (previousDay?.details ?? []).map((row) => [row.symbol, { shares: row.closingShares, price: decimalToNumber(row.closePrice) }])
  );

  const todayTrades = await prisma.executionTrade.findMany({
    where: {
      fillTime: {
        gte: new Date(`${tradeDate}T00:00:00.000Z`),
        lte: new Date(`${tradeDate}T23:59:59.999Z`)
      }
    },
    include: {
      order: {
        select: {
          symbolName: true
        }
      }
    }
  });

  const tradeStatsBySymbol = new Map<
    string,
    {
      symbolName: string;
      buyShares: number;
      buyAmount: number;
      sellShares: number;
      sellAmount: number;
      realizedPnl: number;
      costBasisAmount: number;
    }
  >();

  for (const trade of todayTrades) {
    const current = tradeStatsBySymbol.get(trade.symbol) ?? {
      symbolName: trade.order.symbolName ?? trade.symbol,
      buyShares: 0,
      buyAmount: 0,
      sellShares: 0,
      sellAmount: 0,
      realizedPnl: 0,
      costBasisAmount: 0,
    };

    if (trade.side === "BUY") {
      current.buyShares += trade.shares;
      current.buyAmount += decimalToNumber(trade.fillPrice) * trade.shares;
    } else {
      current.sellShares += trade.shares;
      current.sellAmount += decimalToNumber(trade.fillPrice) * trade.shares;
      current.realizedPnl += decimalToNumber(trade.realizedPnl);
      current.costBasisAmount += decimalToNumber(trade.costBasisAmount);
    }

    tradeStatsBySymbol.set(trade.symbol, current);
  }

  if (tradeStatsBySymbol.size > 0) {
    const lots = await prisma.positionLot.findMany({ where: { status: { in: ["OPEN", "CLOSED"] } } });
    for (const [symbol, current] of tradeStatsBySymbol.entries()) {
      if (current.sellShares === 0 || current.costBasisAmount > 0) {
        continue;
      }

      const symbolLots = lots.filter((lot) => lot.symbol === symbol);
      const averageCost =
        symbolLots.length > 0
          ? symbolLots.reduce((sum, lot) => sum + decimalToNumber(lot.costPrice) * lot.originalShares, 0) /
            symbolLots.reduce((sum, lot) => sum + lot.originalShares, 0)
          : 0;
      current.costBasisAmount = averageCost * current.sellShares;
      current.realizedPnl = current.sellAmount - current.costBasisAmount;
    }
  }

  const detailSymbols = new Set<string>([
    ...grouped.keys(),
    ...previousDetails.keys(),
    ...tradeStatsBySymbol.keys()
  ]);

  const detailRows = Array.from(detailSymbols).map((symbol) => {
    const currentHolding = grouped.get(symbol);
    const previous = previousDetails.get(symbol);
    const tradeStats = tradeStatsBySymbol.get(symbol);

    const closingShares = currentHolding?.shares ?? 0;
    const costAmount = currentHolding?.costAmount ?? 0;
    const fallbackPrice = currentHolding?.fallbackPrice ?? previous?.price ?? 0;
    const { openPrice, closePrice, marketValue } = getPositionSnapshotValue(symbol, closingShares, fallbackPrice);

    const previousShares = previous?.shares ?? 0;
    const previousPrice = previous?.price ?? (previousShares === 0 ? fallbackPrice : 0);
    const buyShares = tradeStats?.buyShares ?? 0;
    const buyAmount = tradeStats?.buyAmount ?? 0;
    const sellShares = tradeStats?.sellShares ?? 0;
    const sellAmount = tradeStats?.sellAmount ?? 0;
    const realizedPnl = tradeStats?.realizedPnl ?? 0;
    const realizedCostBasisAmount = tradeStats?.costBasisAmount ?? 0;

    const soldFromPreviousShares = Math.max(0, Math.min(previousShares, sellShares));
    const remainingPreviousShares = Math.max(0, previousShares - soldFromPreviousShares);
    const sameDayBoughtRemainingShares = Math.max(0, closingShares - remainingPreviousShares);
    const sameDayBoughtAndSoldShares = Math.max(0, buyShares - sameDayBoughtRemainingShares);

    const averageBuyPrice = buyShares === 0 ? 0 : buyAmount / buyShares;
    const averageSellPrice = sellShares === 0 ? 0 : sellAmount / sellShares;
    const buyPrice =
      closingShares > 0
        ? costAmount / closingShares
        : realizedCostBasisAmount > 0 && sellShares > 0
          ? realizedCostBasisAmount / sellShares
          : 0;

    const carriedPnl = remainingPreviousShares * (closePrice - previousPrice);
    const soldPreviousPnl = soldFromPreviousShares * (averageSellPrice - previousPrice);
    const boughtRemainingPnl = sameDayBoughtRemainingShares * (closePrice - averageBuyPrice);
    const boughtAndSoldPnl = sameDayBoughtAndSoldShares * (averageSellPrice - averageBuyPrice);
    const dailyPnl = carriedPnl + soldPreviousPnl + boughtRemainingPnl + boughtAndSoldPnl;

    const denominator =
      previousShares > 0
        ? previousShares * previousPrice
        : buyShares > 0
          ? buyAmount || 1
          : realizedCostBasisAmount || 1;

    return {
      symbol,
      symbolName: currentHolding?.symbolName ?? tradeStats?.symbolName ?? symbol,
      openingShares: previousShares,
      closingShares,
      buyShares,
      sellShares,
      buyPrice,
      sellPrice: averageSellPrice,
      openPrice,
      closePrice,
      realizedPnl,
      unrealizedPnl: carriedPnl + boughtRemainingPnl,
      dailyPnl,
      dailyReturn: denominator === 0 ? 0 : dailyPnl / denominator,
      marketValue,
      soldPreviousPnl,
      boughtAndSoldPnl
    };
  });

  const positionMarketValue = detailRows.reduce((sum, row) => sum + row.marketValue, 0);
  const totalAssets = availableCash + positionMarketValue;
  const previousTotalAssets = previousDay ? decimalToNumber(previousDay.totalAssets) : totalAssets;
  const dailyPnl = totalAssets - previousTotalAssets;
  const dailyReturn = previousTotalAssets === 0 ? 0 : dailyPnl / previousTotalAssets;
  const initialCapital = firstDay
    ? decimalToNumber(firstDay.totalAssets) - decimalToNumber(firstDay.cumulativePnl)
    : totalAssets;
  const cumulativePnl = totalAssets - initialCapital;

  const buyAmount = todayTrades
    .filter((trade) => trade.side === "BUY")
    .reduce((sum, trade) => sum + decimalToNumber(trade.fillPrice) * trade.shares, 0);
  const sellAmount = todayTrades
    .filter((trade) => trade.side === "SELL")
    .reduce((sum, trade) => sum + decimalToNumber(trade.fillPrice) * trade.shares, 0);

  const existing = await prisma.dailyPnl.findUnique({ where: { tradeDate } });

  if (existing) {
    await prisma.dailyPnlDetail.deleteMany({ where: { dailyPnlId: existing.id } });
  }

  const row = await prisma.dailyPnl.upsert({
    where: { tradeDate },
    update: {
      totalAssets: new Prisma.Decimal(totalAssets),
      availableCash: new Prisma.Decimal(availableCash),
      positionMarketValue: new Prisma.Decimal(positionMarketValue),
      dailyPnl: new Prisma.Decimal(dailyPnl),
      dailyReturn: new Prisma.Decimal(dailyReturn),
      cumulativePnl: new Prisma.Decimal(cumulativePnl),
      buyAmount: new Prisma.Decimal(buyAmount),
      sellAmount: new Prisma.Decimal(sellAmount),
      tradeCount: todayTrades.length,
        details: {
          create: detailRows.map((detail) => ({
            tradeDate,
            symbol: detail.symbol,
            symbolName: detail.symbolName,
            openingShares: detail.openingShares,
            closingShares: detail.closingShares,
            buyShares: detail.buyShares,
            sellShares: detail.sellShares,
            buyPrice: new Prisma.Decimal(detail.buyPrice),
            sellPrice: new Prisma.Decimal(detail.sellPrice),
            openPrice: new Prisma.Decimal(detail.openPrice),
            closePrice: new Prisma.Decimal(detail.closePrice),
            realizedPnl: new Prisma.Decimal(detail.realizedPnl),
            unrealizedPnl: new Prisma.Decimal(detail.unrealizedPnl),
            dailyPnl: new Prisma.Decimal(detail.dailyPnl),
            dailyReturn: new Prisma.Decimal(detail.dailyReturn)
          }))
      }
    },
    create: {
      tradeDate,
      totalAssets: new Prisma.Decimal(totalAssets),
      availableCash: new Prisma.Decimal(availableCash),
      positionMarketValue: new Prisma.Decimal(positionMarketValue),
      dailyPnl: new Prisma.Decimal(dailyPnl),
      dailyReturn: new Prisma.Decimal(dailyReturn),
      cumulativePnl: new Prisma.Decimal(cumulativePnl),
      buyAmount: new Prisma.Decimal(buyAmount),
      sellAmount: new Prisma.Decimal(sellAmount),
      tradeCount: todayTrades.length,
        details: {
          create: detailRows.map((detail) => ({
            tradeDate,
            symbol: detail.symbol,
            symbolName: detail.symbolName,
            openingShares: detail.openingShares,
            closingShares: detail.closingShares,
            buyShares: detail.buyShares,
            sellShares: detail.sellShares,
            buyPrice: new Prisma.Decimal(detail.buyPrice),
            sellPrice: new Prisma.Decimal(detail.sellPrice),
            openPrice: new Prisma.Decimal(detail.openPrice),
            closePrice: new Prisma.Decimal(detail.closePrice),
            realizedPnl: new Prisma.Decimal(detail.realizedPnl),
            unrealizedPnl: new Prisma.Decimal(detail.unrealizedPnl),
            dailyPnl: new Prisma.Decimal(detail.dailyPnl),
            dailyReturn: new Prisma.Decimal(detail.dailyReturn)
          }))
      }
    }
  });

  return row;
}
