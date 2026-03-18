import type { QuoteRow } from "./types.js";

const TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q=";

function parseLine(line: string): QuoteRow | null {
  const match = line.match(/v_(\w+)="(.+)";/);
  if (!match) {
    return null;
  }

  const symbol = match[1];
  const fields = match[2].split("~");

  if (fields.length < 34) {
    return null;
  }

  return {
    symbol,
    name: fields[1] || symbol,
    price: Number(fields[3] || 0),
    previousClose: Number(fields[4] || 0),
    open: Number(fields[5] || 0),
    high: Number(fields[33] || 0),
    low: Number(fields[34] || 0),
    updatedAt: fields[30] || ""
  };
}

export async function fetchTencentQuotes(symbols: string[]) {
  if (symbols.length === 0) {
    return [];
  }

  const response = await fetch(`${TENCENT_QUOTE_URL}${symbols.join(",")}`);
  const text = await response.text();

  return text
    .split("\n")
    .map((line) => parseLine(line.trim()))
    .filter((row): row is QuoteRow => Boolean(row));
}
