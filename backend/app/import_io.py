from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from openpyxl import Workbook, load_workbook


@dataclass(slots=True)
class ParsedImportFile:
    source_type: str
    rows: list[dict]


REQUIRED_HEADERS = ["symbol", "side", "price", "lots", "validity"]
HEADER_ALIASES = {
    "股票代码": "symbol",
    "证券代码": "symbol",
    "symbol": "symbol",
    "code": "symbol",
    "方向": "side",
    "side": "side",
    "操作": "side",
    "委托价": "price",
    "价格": "price",
    "price": "price",
    "手数": "lots",
    "lots": "lots",
    "数量": "lots",
    "有效期": "validity",
    "validity": "validity",
}
SIDE_ALIASES = {
    "buy": "BUY",
    "买入": "BUY",
    "b": "BUY",
    "sell": "SELL",
    "卖出": "SELL",
    "s": "SELL",
}
VALIDITY_ALIASES = {
    "day": "DAY",
    "当日有效": "DAY",
    "gtc": "GTC",
    "长期有效": "GTC",
}


def _norm_header(value: str) -> str:
    return value.strip().replace(" ", "").lower()


def _map_header(value: str) -> str:
    return HEADER_ALIASES.get(_norm_header(value), _norm_header(value))


def _positive_float(value: str) -> float | None:
    try:
        parsed = float(value.replace(",", ""))
        return parsed if parsed > 0 else None
    except Exception:
        return None


def _positive_int(value: str) -> int | None:
    try:
        parsed = int(float(value.replace(",", "")))
        return parsed if parsed > 0 else None
    except Exception:
        return None


def _build_row(record: dict, idx: int) -> dict:
    symbol = str(record.get("symbol", "")).strip().upper()
    side = SIDE_ALIASES.get(str(record.get("side", "")).strip().lower())
    price = _positive_float(str(record.get("price", "")).strip())
    lots = _positive_int(str(record.get("lots", "")).strip())
    validity = VALIDITY_ALIASES.get(str(record.get("validity", "")).strip().lower())
    issues: list[str] = []
    if not symbol:
        issues.append("股票代码不能为空")
    if not side:
        issues.append("方向仅支持 BUY/SELL 或 买入/卖出")
    if price is None:
        issues.append("委托价必须为正数")
    if lots is None:
        issues.append("手数必须为正整数")
    if not validity:
        issues.append("有效期仅支持 DAY/GTC 或 当日有效/长期有效")

    return {
        "rowNumber": idx,
        "symbol": symbol,
        "side": side or "BUY",
        "price": price or 0,
        "lots": lots or 0,
        "validity": validity or "DAY",
        "validationStatus": "ERROR" if issues else "VALID",
        "validationMessage": "；".join(issues) if issues else "文件解析成功",
    }


def _find_header_row(rows: list[list[str]]) -> tuple[int, list[str]]:
    for idx, row in enumerate(rows):
        mapped_headers = [_map_header(cell) for cell in row]
        if all(required in mapped_headers for required in REQUIRED_HEADERS):
            return idx, mapped_headers
    raise ValueError(f"导入模板缺少必填列: {', '.join(REQUIRED_HEADERS)}")



def parse_import_file(file_name: str, content: bytes) -> ParsedImportFile:
    lower = file_name.lower()
    if lower.endswith(".csv"):
        text = content.decode("utf-8")
        raw_rows = [[str(cell or "") for cell in row] for row in csv.reader(io.StringIO(text))]
        header_idx, headers = _find_header_row(raw_rows)
        rows: list[dict] = []
        for raw in raw_rows[header_idx + 1 :]:
            if not raw or all(str(v).strip() == "" for v in raw):
                continue
            mapped = {}
            for idx, header in enumerate(headers):
                mapped[header] = "" if idx >= len(raw) or raw[idx] is None else str(raw[idx])
            rows.append(_build_row(mapped, len(rows) + 1))
        return ParsedImportFile(source_type="CSV", rows=rows)

    if lower.endswith(".xlsx"):
        wb = load_workbook(io.BytesIO(content), data_only=True)
        ws = wb.worksheets[0] if wb.worksheets else None
        if ws is None:
            raise ValueError("Excel 文件中未找到工作表")
        raw_rows = [["" if cell is None else str(cell) for cell in row] for row in ws.iter_rows(values_only=True)]
        header_idx, headers = _find_header_row(raw_rows)

        rows: list[dict] = []
        for row in raw_rows[header_idx + 1 :]:
            if not row or all(v is None or str(v).strip() == "" for v in row):
                continue
            mapped = {}
            for idx, header in enumerate(headers):
                mapped[header] = "" if idx >= len(row) or row[idx] is None else str(row[idx])
            rows.append(_build_row(mapped, len(rows) + 1))
        return ParsedImportFile(source_type="XLSX", rows=rows)

    raise ValueError("当前仅支持 .csv 和 .xlsx 文件")


def build_import_template(target_trade_date: str | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "导入模板"
    ws.append(["A-share AI Trader 指令导入模板"])
    ws.append([f"目标交易日：{target_trade_date or '下载后填写'}；方向支持 BUY/SELL，手数为正整数，有效期支持 DAY/GTC。"])
    ws.append(["股票代码", "方向", "委托价", "手数", "有效期"])
    ws.append(["600519", "BUY", 1650, 5, "DAY"])
    ws.append(["000858", "SELL", 130, 3, "DAY"])

    guide = wb.create_sheet("填写说明")
    guide.append(["字段", "说明"])
    guide.append(["股票代码", "A 股 6 位股票代码，例如 600519"])
    guide.append(["方向", "支持 BUY / SELL，也兼容 买入 / 卖出"])
    guide.append(["委托价", "正数，最多保留两位小数"])
    guide.append(["手数", "正整数，1 手 = 100 股"])
    guide.append(["有效期", "支持 DAY / GTC"])

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()
