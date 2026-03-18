import ExcelJS from "exceljs";

const TEMPLATE_HEADERS = ["股票代码", "方向", "委托价", "手数", "有效期"];

const SAMPLE_ROWS = [
  ["600519", "BUY", 1650, 5, "DAY"],
  ["000858", "SELL", 130, 3, "DAY"]
];

export async function buildImportTemplate(targetTradeDate?: string) {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = "A-share AI Trader";
  workbook.created = new Date();

  const sheet = workbook.addWorksheet("导入模板", {
    views: [{ state: "frozen", ySplit: 3 }]
  });

  sheet.mergeCells("A1:E1");
  sheet.getCell("A1").value = "A-share AI Trader 指令导入模板";
  sheet.getCell("A1").font = { name: "Microsoft YaHei", bold: true, size: 14, color: { argb: "FF102033" } };
  sheet.getCell("A1").alignment = { vertical: "middle", horizontal: "left" };

  sheet.mergeCells("A2:E2");
  sheet.getCell("A2").value = `目标交易日：${targetTradeDate ?? "下载后填写"}；方向支持 BUY/SELL，手数为正整数，有效期支持 DAY/GTC。`;
  sheet.getCell("A2").font = { name: "Microsoft YaHei", size: 11, color: { argb: "FF617086" } };
  sheet.getCell("A2").alignment = { vertical: "middle", horizontal: "left", wrapText: true };

  const headerRow = sheet.getRow(3);
  TEMPLATE_HEADERS.forEach((header, index) => {
    const cell = headerRow.getCell(index + 1);
    cell.value = header;
    cell.font = { name: "Microsoft YaHei", bold: true, color: { argb: "FF102033" } };
    cell.fill = {
      type: "pattern",
      pattern: "solid",
      fgColor: { argb: "FFEAF0FF" }
    };
    cell.alignment = { vertical: "middle", horizontal: "center" };
    cell.border = {
      top: { style: "thin", color: { argb: "FFD7DCE5" } },
      left: { style: "thin", color: { argb: "FFD7DCE5" } },
      bottom: { style: "thin", color: { argb: "FFD7DCE5" } },
      right: { style: "thin", color: { argb: "FFD7DCE5" } }
    };
  });

  SAMPLE_ROWS.forEach((row) => {
    const addedRow = sheet.addRow(row);
    addedRow.eachCell((cell) => {
      cell.border = {
        top: { style: "thin", color: { argb: "FFE5EAF2" } },
        left: { style: "thin", color: { argb: "FFE5EAF2" } },
        bottom: { style: "thin", color: { argb: "FFE5EAF2" } },
        right: { style: "thin", color: { argb: "FFE5EAF2" } }
      };
    });
  });

  sheet.getColumn(1).width = 16;
  sheet.getColumn(2).width = 12;
  sheet.getColumn(3).width = 12;
  sheet.getColumn(4).width = 10;
  sheet.getColumn(5).width = 12;

  sheet.getColumn(3).numFmt = "0.00";

  const guideSheet = workbook.addWorksheet("填写说明");
  guideSheet.columns = [{ width: 22 }, { width: 88 }];
  guideSheet.addRows([
    ["字段", "说明"],
    ["股票代码", "A 股 6 位股票代码，例如 600519"],
    ["方向", "支持 BUY / SELL，也兼容 买入 / 卖出"],
    ["委托价", "正数，最多保留两位小数"],
    ["手数", "正整数，1 手 = 100 股"],
    ["有效期", "支持 DAY / GTC"]
  ]);

  guideSheet.getRow(1).font = { name: "Microsoft YaHei", bold: true, color: { argb: "FF102033" } };
  guideSheet.getRow(1).fill = {
    type: "pattern",
    pattern: "solid",
    fgColor: { argb: "FFF3F5F8" }
  };

  const buffer = await workbook.xlsx.writeBuffer();
  return Buffer.from(buffer);
}
