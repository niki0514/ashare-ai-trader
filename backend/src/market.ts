import type { MarketStatus } from "./types.js";

const formatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  hour12: false,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  weekday: "short"
});

function getChinaParts(date = new Date()) {
  const parts = formatter.formatToParts(date);
  const map = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return {
    date: `${map.year}-${map.month}-${map.day}`,
    time: `${map.hour}:${map.minute}:${map.second}`,
    weekday: map.weekday
  };
}

export function getMarketSession(date = new Date()): { marketStatus: MarketStatus; tradeDate: string; time: string } {
  const { date: tradeDate, time, weekday } = getChinaParts(date);

  if (weekday === "Sat" || weekday === "Sun") {
    return { marketStatus: "weekend", tradeDate, time };
  }

  if (time < "09:30:00") {
    return { marketStatus: "pre_open", tradeDate, time };
  }

  if (time <= "11:30:00") {
    return { marketStatus: "trading", tradeDate, time };
  }

  if (time < "13:00:00") {
    return { marketStatus: "lunch_break", tradeDate, time };
  }

  if (time <= "15:00:00") {
    return { marketStatus: "trading", tradeDate, time };
  }

  return { marketStatus: "closed", tradeDate, time };
}

export function isMarketPollingWindow(date = new Date()) {
  return getMarketSession(date).marketStatus === "trading";
}

export function isImportWindowOpen(date = new Date()) {
  const status = getMarketSession(date).marketStatus;
  return status === "pre_open" || status === "closed";
}
