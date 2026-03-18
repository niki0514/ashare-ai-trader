import cors from "cors";
import express from "express";
import multer from "multer";
import { z } from "zod";
import { parseImportFile } from "./import-parser.js";
import { buildImportTemplate } from "./import-template.js";
import { prisma } from "./prisma.js";
import { processInjectedOrder, runExecutionEngineTick, startExecutionEngine } from "./execution-engine.js";
import { getMarketSession, isImportWindowOpen, isMarketPollingWindow } from "./market.js";
import {
  commitImportBatch,
  createImportBatchFromRows,
  ensureSeedData,
  getCalendarData,
  getDailyPnlDetailData,
  getDashboardData,
  getHistoryData,
  getPendingOrdersData,
  getPositionsData,
  previewImportData
} from "./repository.js";
import { fetchTencentQuotes } from "./tencent.js";
import { getAllCachedQuotes, getLastQuoteUpdateAt, getQuotes, restoreQuotesFromDb } from "./quote-store.js";

const app = express();
const port = Number(process.env.PORT || 3001);
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 5 * 1024 * 1024 }
});

app.use(cors());
app.use(express.json());

app.get("/api/dashboard", async (_req, res) => {
  res.json(await getDashboardData());
});

app.get("/api/positions", async (_req, res) => {
  res.json({ rows: await getPositionsData() });
});

app.get("/api/orders/pending", async (_req, res) => {
  res.json({ rows: await getPendingOrdersData() });
});

app.get("/api/history", async (_req, res) => {
  res.json({ rows: await getHistoryData() });
});

app.get("/api/pnl/calendar", async (_req, res) => {
  res.json({ rows: await getCalendarData() });
});

app.get("/api/pnl/daily/:date", async (req, res) => {
  res.json({ date: req.params.date, rows: await getDailyPnlDetailData(req.params.date) });
});

const previewSchema = z.object({
  targetTradeDate: z.string(),
  mode: z.enum(["DRAFT", "OVERWRITE", "APPEND"]).optional(),
  sourceType: z.enum(["MANUAL", "XLSX", "CSV"]).optional(),
  fileName: z.string().optional(),
  rows: z.array(
    z.object({
      symbol: z.string(),
      side: z.enum(["BUY", "SELL"]),
      price: z.number().positive(),
      lots: z.number().int().positive(),
      validity: z.enum(["DAY", "GTC"])
    })
  )
});

const uploadSchema = z.object({
  targetTradeDate: z.string().min(1),
  mode: z.enum(["DRAFT", "OVERWRITE", "APPEND"]).optional().default("DRAFT")
});

app.post("/api/imports/upload", upload.single("file"), async (req, res) => {
  if (!isImportWindowOpen()) {
    return res.status(403).json({ message: "仅允许在交易所收盘后或开盘前导入数据" });
  }

  const payload = uploadSchema.safeParse(req.body);

  if (!payload.success) {
    return res.status(400).json({ message: "Invalid upload payload", issues: payload.error.flatten() });
  }

  if (!req.file) {
    return res.status(400).json({ message: "请选择要上传的文件" });
  }

  try {
    const parsed = await parseImportFile(req.file.originalname, req.file.buffer);
    const response = await createImportBatchFromRows({
      targetTradeDate: payload.data.targetTradeDate,
      sourceType: parsed.sourceType,
      fileName: req.file.originalname,
      mode: payload.data.mode,
      rows: parsed.rows
    });

    return res.json({
      ...response,
      fileName: req.file.originalname,
      sourceType: parsed.sourceType
    });
  } catch (error) {
    return res.status(400).json({
      message: error instanceof Error ? error.message : "文件解析失败"
    });
  }
});

app.get("/api/imports/template", async (req, res) => {
  const targetTradeDate = typeof req.query.targetTradeDate === "string" ? req.query.targetTradeDate : undefined;
  const fileName = `import-template-${targetTradeDate ?? new Date().toISOString().slice(0, 10)}.xlsx`;
  const buffer = await buildImportTemplate(targetTradeDate);

  res.setHeader("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  res.setHeader("Content-Disposition", `attachment; filename="${fileName}"`);
  return res.send(buffer);
});

app.post("/api/imports/preview", async (req, res) => {
  if (!isImportWindowOpen()) {
    return res.status(403).json({ message: "仅允许在交易所收盘后或开盘前导入数据" });
  }

  const payload = previewSchema.safeParse(req.body);

  if (!payload.success) {
    return res.status(400).json({ message: "Invalid payload", issues: payload.error.flatten() });
  }

  return res.json(await previewImportData(payload.data));
});

app.post(
  "/api/imports/commit",
  async (
    req: express.Request<unknown, unknown, { batchId: string; mode: "OVERWRITE" | "APPEND" | "DRAFT" }>,
    res
  ) => {
    if (!req.body?.batchId) {
      return res.status(400).json({ message: "batchId is required" });
    }

    if (!isImportWindowOpen()) {
      return res.status(403).json({ message: "仅允许在交易所收盘后或开盘前导入数据" });
    }

    return res.json(await commitImportBatch(req.body.batchId, req.body.mode ?? "DRAFT"));
  }
);

app.get("/api/imports/latest", async (req, res) => {
  const tradeDate = String(req.query.tradeDate || "");
  const { prisma } = await import("./prisma.js");
  const rows = await prisma.importBatch.findMany({
    where: tradeDate ? { targetTradeDate: tradeDate } : undefined,
    include: { items: { orderBy: { rowNumber: "asc" } } },
    orderBy: { createdAt: "desc" },
    take: 5
  });

  return res.json({ rows });
});

app.post("/api/dev/trigger-order/:id", async (req, res) => {
  const order = await prisma.instructionOrder.findUnique({ where: { id: req.params.id } });
  if (!order) {
    return res.status(404).json({ message: "Order not found" });
  }

  const nextPrice = order.side === "BUY" ? Number(order.limitPrice) - 0.01 : Number(order.limitPrice) + 0.01;
  const quoteSymbol = order.symbol.startsWith("6") ? `sh${order.symbol}` : `sz${order.symbol}`;
  const { setQuotes } = await import("./quote-store.js");
  setQuotes([
    {
      symbol: quoteSymbol,
      name: order.symbolName ?? order.symbol,
      price: nextPrice,
      open: nextPrice,
      previousClose: nextPrice,
      high: nextPrice,
      low: nextPrice,
      updatedAt: new Date().toISOString()
    }
  ]);

  const processed = await processInjectedOrder(order.id);

  return res.json({ message: "Injected in-memory quote for testing", orderId: order.id, price: nextPrice, processed });
});

app.post("/api/dev/create-conflict-sell", async (_req, res) => {
  const created = await prisma.instructionOrder.create({
    data: {
      tradeDate: getMarketSession().tradeDate,
      symbol: "600519",
      symbolName: "贵州茅台",
      side: "SELL",
      limitPrice: 1725,
      lots: 2,
      shares: 200,
      validity: "DAY",
      status: "confirmed",
      statusReason: "已导入待执行"
    }
  });

  await runExecutionEngineTick();

  const refreshed = await prisma.instructionOrder.findUnique({ where: { id: created.id } });
  return res.json({ row: refreshed });
});

app.post("/api/dev/reset-demo", async (_req, res) => {
  await prisma.orderEvent.deleteMany();
  await prisma.executionTrade.deleteMany();
  await prisma.instructionOrder.deleteMany();
  await prisma.positionLot.deleteMany();
  await prisma.cashLedger.deleteMany();
  await prisma.dailyPnlDetail.deleteMany();
  await prisma.dailyPnl.deleteMany();
  await prisma.importBatchItem.deleteMany();
  await prisma.importBatch.deleteMany();
  const { ensureSeedData } = await import("./repository.js");
  await ensureSeedData();
  return res.json({ message: "demo reset complete" });
});

app.get("/api/quotes", async (req, res) => {
  const session = getMarketSession();
  const symbols = String(req.query.symbols || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);

  if (!isMarketPollingWindow()) {
    const cached = symbols.length > 0 ? getQuotes(symbols) : getAllCachedQuotes();
    return res.json({
      marketStatus: session.marketStatus,
      updatedAt: getLastQuoteUpdateAt() ?? new Date().toISOString(),
      stale: true,
      quotes: cached
    });
  }

  try {
    const quotes = await fetchTencentQuotes(symbols);
    return res.json({
      marketStatus: session.marketStatus,
      updatedAt: new Date().toISOString(),
      stale: false,
      quotes
    });
  } catch (error) {
    return res.status(502).json({
      message: "Failed to fetch Tencent quotes",
      marketStatus: session.marketStatus,
      error: error instanceof Error ? error.message : "Unknown error"
    });
  }
});

await ensureSeedData();
await restoreQuotesFromDb();
startExecutionEngine();

app.listen(port, () => {
  console.log(`Backend listening on http://localhost:${port}`);
});
