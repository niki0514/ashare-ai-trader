import { parse } from "fast-csv";
import ExcelJS from "exceljs";
import { Readable } from "node:stream";
import type { ImportPreviewRow } from "./types.js";

type ImportSourceType = "CSV" | "XLSX";

type ParsedImportFile = {
  sourceType: ImportSourceType;
  rows: ImportPreviewRow[];
};

type RawImportRecord = Record<string, string>;

const REQUIRED_HEADERS = ["symbol", "side", "price", "lots", "validity"];
const HEADER_ALIASES: Record<string, string> = {
  "股票代码": "symbol",
  "证券代码": "symbol",
  symbol: "symbol",
  code: "symbol",
  "方向": "side",
  side: "side",
  "操作": "side",
  "委托价": "price",
  "价格": "price",
  price: "price",
  "手数": "lots",
  lots: "lots",
  "数量": "lots",
  "有效期": "validity",
  validity: "validity"
};

const SIDE_ALIASES: Record<string, "BUY" | "SELL"> = {
  buy: "BUY",
  买入: "BUY",
  b: "BUY",
  sell: "SELL",
  卖出: "SELL",
  s: "SELL"
};

const VALIDITY_ALIASES: Record<string, "DAY" | "GTC"> = {
  day: "DAY",
  当日有效: "DAY",
  gtc: "GTC",
  长期有效: "GTC"
};

function normalizeHeader(header: string) {
  return header.trim().replace(/\s+/g, "").toLowerCase();
}

function mapHeader(header: string) {
  return HEADER_ALIASES[normalizeHeader(header)] ?? normalizeHeader(header);
}

function normalizeString(value: unknown) {
  return String(value ?? "").trim();
}

function parsePositiveNumber(value: string) {
  if (!value) {
    return null;
  }

  const parsed = Number(value.replace(/,/g, ""));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function parsePositiveInteger(value: string) {
  if (!value) {
    return null;
  }

  const parsed = Number(value.replace(/,/g, ""));
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function parseSide(value: string) {
  return SIDE_ALIASES[value.trim().toLowerCase()] ?? null;
}

function parseValidity(value: string) {
  return VALIDITY_ALIASES[value.trim().toLowerCase()] ?? null;
}

function validateHeaders(headers: string[]) {
  const missing = REQUIRED_HEADERS.filter((header) => !headers.includes(header));
  if (missing.length > 0) {
    throw new Error(`导入模板缺少必填列: ${missing.join(", ")}`);
  }
}

function buildImportRow(record: RawImportRecord, rowNumber: number): ImportPreviewRow {
  const symbol = normalizeString(record.symbol);
  const side = parseSide(normalizeString(record.side));
  const price = parsePositiveNumber(normalizeString(record.price));
  const lots = parsePositiveInteger(normalizeString(record.lots));
  const validity = parseValidity(normalizeString(record.validity));
  const issues: string[] = [];

  if (!symbol) {
    issues.push("股票代码不能为空");
  }

  if (!side) {
    issues.push("方向仅支持 BUY/SELL 或 买入/卖出");
  }

  if (price === null) {
    issues.push("委托价必须为正数");
  }

  if (lots === null) {
    issues.push("手数必须为正整数");
  }

  if (!validity) {
    issues.push("有效期仅支持 DAY/GTC 或 当日有效/长期有效");
  }

  return {
    rowNumber,
    symbol,
    side: side ?? "BUY",
    price: price ?? 0,
    lots: lots ?? 0,
    validity: validity ?? "DAY",
    validationStatus: issues.length > 0 ? "ERROR" : "VALID",
    validationMessage: issues.length > 0 ? issues.join("；") : "文件解析成功"
  };
}

function mapRecordKeys(record: Record<string, string>) {
  return Object.entries(record).reduce<RawImportRecord>((result, [key, value]) => {
    result[mapHeader(key)] = normalizeString(value);
    return result;
  }, {});
}

async function parseCsvBuffer(buffer: Buffer) {
  return new Promise<ImportPreviewRow[]>((resolve, reject) => {
    const rows: ImportPreviewRow[] = [];

    const parser = parse<Record<string, string>, Record<string, string>>({
      headers: (headers) => headers.map((header) => mapHeader(normalizeString(header ?? ""))),
      ignoreEmpty: true,
      trim: true
    })
      .on("error", reject)
      .on("headers", (headers) => {
        validateHeaders(headers);
      })
      .on("data", (row: Record<string, string>) => {
        rows.push(buildImportRow(mapRecordKeys(row), rows.length + 1));
      })
      .on("end", () => resolve(rows));

    Readable.from([buffer.toString("utf-8")]).pipe(parser);
  });
}

async function parseXlsxBuffer(buffer: Buffer) {
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.read(Readable.from([buffer]));
  const worksheet = workbook.worksheets[0];

  if (!worksheet) {
    throw new Error("Excel 文件中未找到工作表");
  }

  const headerRow = worksheet.getRow(1);
  const headerValues = Array.isArray(headerRow.values) ? headerRow.values.slice(1) : [];
  const headers = headerValues
    .map((value) => mapHeader(normalizeString(value)))
    .filter(Boolean);

  validateHeaders(headers);

  const rows: ImportPreviewRow[] = [];

  worksheet.eachRow((row, rowNumber) => {
    if (rowNumber === 1) {
      return;
    }

    const values = Array.isArray(row.values) ? row.values.slice(1) : [];
    const isEmpty = values.every((value) => normalizeString(value) === "");

    if (isEmpty) {
      return;
    }

    const rawRecord = headers.reduce<RawImportRecord>((result, header, index) => {
      result[header] = normalizeString(values[index]);
      return result;
    }, {});

    rows.push(buildImportRow(rawRecord, rows.length + 1));
  });

  return rows;
}

export async function parseImportFile(fileName: string, buffer: Buffer): Promise<ParsedImportFile> {
  const normalizedFileName = fileName.toLowerCase();

  if (normalizedFileName.endsWith(".csv")) {
    return {
      sourceType: "CSV",
      rows: await parseCsvBuffer(buffer)
    };
  }

  if (normalizedFileName.endsWith(".xlsx")) {
    return {
      sourceType: "XLSX",
      rows: await parseXlsxBuffer(buffer)
    };
  }

  throw new Error("当前仅支持 .csv 和 .xlsx 文件");
}
