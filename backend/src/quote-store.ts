import type { QuoteRow } from "./types.js";

const quoteMap = new Map<string, QuoteRow>();
let lastQuoteUpdateAt: string | null = null;

export function setQuotes(rows: QuoteRow[]) {
  for (const row of rows) {
    quoteMap.set(row.symbol, row);
  }
  lastQuoteUpdateAt = new Date().toISOString();
}

export function getQuote(symbol: string) {
  return quoteMap.get(symbol.startsWith("sh") || symbol.startsWith("sz") ? symbol : toQuoteSymbol(symbol)) ?? null;
}

export function getQuotes(symbols: string[]) {
  return symbols
    .map((symbol) => getQuote(symbol))
    .filter((row): row is QuoteRow => Boolean(row));
}

export function getAllCachedQuotes(): QuoteRow[] {
  return Array.from(quoteMap.values());
}

export function getLastQuoteUpdateAt() {
  return lastQuoteUpdateAt;
}

export function toQuoteSymbol(symbol: string) {
  return symbol.startsWith("6") ? `sh${symbol}` : `sz${symbol}`;
}

export async function restoreQuotesFromDb() {
  if (quoteMap.size > 0) {
    return;
  }

  const { prisma } = await import("./prisma.js");

  const latestPnl = await prisma.dailyPnl.findFirst({
    orderBy: { tradeDate: "desc" },
    include: { details: true }
  });

  if (!latestPnl || latestPnl.details.length === 0) {
    return;
  }

  const rows: QuoteRow[] = latestPnl.details
    .filter((d) => Number(d.closePrice) > 0)
    .map((d) => ({
      symbol: toQuoteSymbol(d.symbol),
      name: d.symbolName ?? d.symbol,
      price: Number(d.closePrice),
      open: Number(d.openPrice),
      previousClose: Number(d.closePrice),
      high: Number(d.closePrice),
      low: Number(d.closePrice),
      updatedAt: `${latestPnl.tradeDate} 15:00:00`
    }));

  if (rows.length > 0) {
    setQuotes(rows);
  }
}
