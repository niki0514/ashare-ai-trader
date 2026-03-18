import { prisma } from "./prisma.js";

export async function getPendingSellOrdersBySymbol() {
  const rows = await prisma.instructionOrder.findMany({
    where: {
      side: "SELL",
      status: { in: ["confirmed", "pending", "triggered"] }
    },
    orderBy: { createdAt: "asc" },
    select: {
      id: true,
      symbol: true,
      side: true,
      limitPrice: true,
      shares: true,
      lots: true,
      status: true
    }
  });

  const grouped = new Map<string, typeof rows>();
  for (const row of rows) {
    grouped.set(row.symbol, [...(grouped.get(row.symbol) ?? []), row]);
  }
  return grouped;
}

export async function getReservedSellSharesBySymbol(excludeOrderId?: string) {
  const rows = await prisma.instructionOrder.findMany({
    where: {
      side: "SELL",
      status: { in: ["confirmed", "pending", "triggered"] },
      ...(excludeOrderId ? { id: { not: excludeOrderId } } : {})
    },
    select: { symbol: true, shares: true }
  });

  const reservedBySymbol = new Map<string, number>();
  for (const row of rows) {
    reservedBySymbol.set(row.symbol, (reservedBySymbol.get(row.symbol) ?? 0) + row.shares);
  }
  return reservedBySymbol;
}

export async function getAvailableSellableSharesBySymbol(excludeOrderId?: string) {
  const lots = await prisma.positionLot.findMany({ where: { status: "OPEN" } });
  const sellableBySymbol = new Map<string, number>();

  for (const lot of lots) {
    sellableBySymbol.set(lot.symbol, (sellableBySymbol.get(lot.symbol) ?? 0) + lot.sellableShares);
  }

  const reservedBySymbol = await getReservedSellSharesBySymbol(excludeOrderId);
  const availableBySymbol = new Map<string, number>();

  for (const [symbol, sellableShares] of sellableBySymbol.entries()) {
    const reservedShares = reservedBySymbol.get(symbol) ?? 0;
    availableBySymbol.set(symbol, Math.max(0, sellableShares - reservedShares));
  }

  return { sellableBySymbol, reservedBySymbol, availableBySymbol };
}
