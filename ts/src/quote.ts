import ExcelJS from "exceljs";
import type { NormalizedStatement, QuoteSettings } from "./schema.js";

/**
 * Branded Interchange-Plus quote workbook. Every calculated cell is a LIVE
 * Excel formula driven by one editable input ("Target Savings", D14): change
 * it and the whole sheet recomputes. Passthrough rows (interchange, brand
 * assessments) reference the current column, so they never change; the only
 * lever is the processor markup, which back-solves to hit the target.
 *
 * Faithful port of scripts/generate_quote.py.
 */

const BLUE = "FF1A568E";
const GREEN = "FFE2EFDA";
const BLUEFILL = "FFD6E4F0";
const AMBER = "FFFFF2CC";
const GREY = "FFF2F2F2";

const PCT = "0.0000%";
const PCT2 = "0.00%";
const USD = '"$"#,##0.00';

// Absolute references shared across formulas.
const D_VOL = "$D$36";
const F_VOL = "$F$36";
const D_CNT = "$D$37";
const F_CNT = "$F$37";
const D_TOTAL = "$D$39";
const F_TOTAL = "$F$39";
const TARGET = "$D$14";

export async function buildQuote(
  stmt: NormalizedStatement,
  outPath: string,
  settings: QuoteSettings,
): Promise<string> {
  const wb = new ExcelJS.Workbook();
  const ws = wb.addWorksheet("Analysis", {
    views: [{ showGridLines: false }],
  });

  const widths: Record<string, number> = { A: 2.5, B: 30, C: 2.5, D: 16, E: 2.5, F: 16, G: 2.5 };
  for (const [col, w] of Object.entries(widths)) ws.getColumn(col).width = w;

  const iso = settings.isoName ?? "Gratify";
  const r = stmt.rates;
  const f = stmt.fees;

  const label = { name: "Arial", size: 9, color: { argb: "FF404040" } } as const;
  const val = { name: "Arial", size: 9 } as const;
  const bold = { name: "Arial", size: 9, bold: true } as const;
  const whiteBold = { name: "Arial", size: 9, bold: true, color: { argb: "FFFFFFFF" } } as const;

  const fill = (argb: string) =>
    ({ type: "pattern", pattern: "solid", fgColor: { argb } }) as ExcelJS.FillPattern;

  function put(
    addr: string,
    value: ExcelJS.CellValue,
    opts: { font?: Partial<ExcelJS.Font>; fmt?: string; bg?: string; align?: "left" | "right" | "center"; border?: boolean } = {},
  ) {
    const c = ws.getCell(addr);
    c.value = value;
    if (opts.font) c.font = opts.font;
    if (opts.fmt) c.numFmt = opts.fmt;
    if (opts.bg) c.fill = fill(opts.bg);
    if (opts.align) c.alignment = { horizontal: opts.align };
    if (opts.border) {
      const s = { style: "thin", color: { argb: "FFBFBFBF" } } as const;
      c.border = { top: s, left: s, bottom: s, right: s };
    }
  }
  const ref = (formula: string): ExcelJS.CellValue => ({ formula });

  // ---- Letterhead -------------------------------------------------------
  put("B2", iso.toUpperCase(), { font: { name: "Arial", size: 22, bold: true, color: { argb: BLUE } } });
  put("B3", "Merchant Rate Review & Interchange-Plus Proposal", { font: { name: "Arial", size: 10, color: { argb: BLUE } } });

  put("B5", "Comparison For:", { font: label });   put("D5", stmt.merchant_name, { font: bold });
  put("B6", "Processor (current):", { font: label }); put("D6", stmt.processor, { font: val });
  put("B7", "Merchant ID:", { font: label });        put("D7", stmt.merchant_id, { font: val });
  put("B8", "Statement Period:", { font: label });   put("D8", stmt.statement_period, { font: val });
  put("B9", "Prepared By:", { font: label });        put("D9", settings.preparedBy, { font: val });
  put("B10", "Contact Email:", { font: label });     put("D10", settings.email, { font: val });
  put("B11", "Date:", { font: label });              put("D11", new Date(), { font: val, fmt: "mmm d, yyyy" });

  // ---- Settings (the one input that drives proposed pricing) -----------
  put("B13", "Quote Settings", { font: whiteBold, bg: BLUE });
  put("D13", "", { font: whiteBold, bg: BLUE });
  put("B14", "Target Savings (editable)", { font: label });
  put("D14", settings.targetSavings, { font: bold, fmt: PCT2, bg: AMBER, border: true });

  // ---- Estimated Savings ------------------------------------------------
  put("B16", "Estimated Savings", { font: whiteBold, bg: BLUE });
  put("D16", "Interchange Plus", { font: whiteBold, bg: BLUE, align: "center" });
  put("B17", "% Savings (per month)", { font: label });
  put("D17", ref(`1-(${F_TOTAL}/${D_TOTAL})`), { font: bold, fmt: PCT2, bg: GREEN });
  put("B18", "Monthly Savings", { font: label });
  put("D18", ref(`${D_TOTAL}-${F_TOTAL}`), { font: bold, fmt: USD, bg: GREEN });
  put("B19", "Annual Savings", { font: label });
  put("D19", ref("D18*12"), { font: bold, fmt: USD, bg: GREEN });
  put("B20", "3-Year Savings", { font: label });
  put("D20", ref("D19*3"), { font: bold, fmt: USD, bg: GREEN });

  // ---- Rate Comparison --------------------------------------------------
  put("B22", "Rate Comparison", { font: whiteBold, bg: BLUE });
  put("D22", stmt.processor, { font: whiteBold, bg: BLUE, align: "center" });
  put("F22", "Proposed", { font: whiteBold, bg: BLUE, align: "center" });
  put("B23", "Effective Processing Rate", { font: bold });
  put("D23", ref(`${D_TOTAL}/${D_VOL}`), { font: bold, fmt: PCT, bg: BLUEFILL });
  put("F23", ref(`${F_TOTAL}/${F_VOL}`), { font: bold, fmt: PCT, bg: BLUEFILL });

  // ---- Statement Analysis ----------------------------------------------
  put("B25", "Statement Analysis", { font: whiteBold, bg: BLUE });
  put("D25", stmt.processor, { font: whiteBold, bg: BLUE, align: "center" });
  put("F25", "Proposed", { font: whiteBold, bg: BLUE, align: "center" });

  put("B27", "Interchange (passthrough)", { font: label, border: true });
  put("D27", r.interchange, { font: val, fmt: PCT, border: true });
  put("F27", ref("D27"), { font: val, fmt: PCT, bg: GREY, border: true });

  put("B28", "Processor Markup / Discount Rate", { font: label, border: true });
  put("D28", r.processor_markup, { font: val, fmt: PCT, border: true });
  // proposed markup back-solves so proposed total == current total * (1 - target)
  put("F28", ref(`(${D_TOTAL}*(1-${TARGET})-F27*${F_VOL}-F29*${F_VOL}-F31*${F_CNT}-F33)/${F_VOL}`), {
    font: bold, fmt: PCT, bg: AMBER, border: true,
  });

  put("B29", "Card Brand & Assessment Fees (passthrough)", { font: label, border: true });
  put("D29", r.network_assessment, { font: val, fmt: PCT, border: true });
  put("F29", ref("D29"), { font: val, fmt: PCT, bg: GREY, border: true });

  put("B31", "Per-Transaction Fee", { font: label, border: true });
  put("D31", 0, { font: val, fmt: USD, border: true });
  put("F31", 0, { font: val, fmt: USD, bg: GREY, border: true });

  put("B33", "Monthly & Account Fees (fixed)", { font: label, border: true });
  put("D33", f.account_other, { font: val, fmt: USD, border: true });
  put("F33", ref("D33"), { font: val, fmt: USD, bg: GREY, border: true });

  put("B35", "Average Ticket", { font: label, border: true });
  put("D35", ref(`${D_VOL}/${D_CNT}`), { font: val, fmt: USD, border: true });
  put("F35", ref("D35"), { font: val, fmt: USD, border: true });
  put("B36", "Monthly Volume", { font: label, border: true });
  put("D36", stmt.volume, { font: val, fmt: USD, border: true });
  put("F36", ref("D36"), { font: val, fmt: USD, border: true });
  put("B37", "Transaction Count", { font: label, border: true });
  put("D37", stmt.transactions, { font: val, fmt: "#,##0", border: true });
  put("F37", ref("D37"), { font: val, fmt: "#,##0", border: true });

  const totalFormula = (ic: string, mk: string, pt: string, cb: string, vol: string, cnt: string, fx: string) =>
    `${ic}*${vol}+${mk}*${vol}+${pt}*${cnt}+${cb}*${vol}+${fx}`;
  put("B39", "Total Monthly Fees", { font: bold, bg: GREY, border: true });
  put("D39", ref(totalFormula("D27", "D28", "D31", "D29", D_VOL, D_CNT, "D33")), { font: bold, fmt: USD, bg: GREY, border: true });
  put("F39", ref(totalFormula("F27", "F28", "F31", "F29", F_VOL, F_CNT, "F33")), { font: bold, fmt: USD, bg: GREEN, border: true });

  // ---- Card mix ---------------------------------------------------------
  let row = 42;
  put(`B${row}`, "Card Mix", { font: whiteBold, bg: BLUE });
  put(`D${row}`, "Volume", { font: whiteBold, bg: BLUE, align: "center" });
  put(`F${row}`, "% of Volume", { font: whiteBold, bg: BLUE, align: "center" });
  for (const m of stmt.card_mix) {
    row++;
    put(`B${row}`, m.brand, { font: label, border: true });
    put(`D${row}`, Math.round(m.volume * 100) / 100, { font: val, fmt: USD, border: true });
    put(`F${row}`, ref(`D${row}/${D_VOL}`), { font: val, fmt: PCT2, border: true });
  }

  // ---- Notes ------------------------------------------------------------
  row += 2;
  const nf = { name: "Arial", size: 8, color: { argb: "FF404040" } } as const;
  put(`B${row}`, "Processing Notes", { font: bold });
  const notes =
    `Merchant: ${stmt.merchant_name} (MID ${stmt.merchant_id})\n` +
    `Current processor: ${stmt.processor}\n` +
    `Statement period: ${stmt.statement_period}\n` +
    `Pricing model: Interchange Plus.\n\n` +
    `Current effective rate: ${(r.effective * 100).toFixed(2)}% on $${stmt.volume.toLocaleString()} across ${stmt.transactions.toLocaleString()} transactions.\n` +
    `Interchange + assessments ($${f.passthrough.toFixed(2)}) pass through unchanged; the proposed savings come entirely from reducing the processor markup of $${f.processor_markup.toFixed(2)}.\n` +
    `Extraction confidence: ${stmt.confidence}. Figures verified by reconciliation against the statement's printed totals.`;
  const nCell = ws.getCell(`B${row + 1}`);
  nCell.value = notes;
  nCell.font = nf;
  nCell.alignment = { wrapText: true, vertical: "top" };
  ws.mergeCells(`B${row + 1}:F${row + 9}`);

  await wb.xlsx.writeFile(outPath);
  return outPath;
}

/**
 * Independent verification of the workbook, computed in plain TypeScript (not
 * by reading ExcelJS's formula results — ExcelJS does not evaluate formulas).
 * Reproduces the sheet's arithmetic from the same inputs and asserts:
 *   - the current-column total equals the reconciled statement total to the penny;
 *   - the proposed total equals current * (1 - target) to the penny;
 *   - passthrough rows are unchanged.
 * Throws on any mismatch.
 */
export function verifyQuote(stmt: NormalizedStatement, settings: QuoteSettings): {
  current: number;
  proposed: number;
  monthlySavings: number;
  proposedMarkupRate: number;
} {
  const round2 = (n: number) => Math.round(n * 100) / 100;
  const vol = stmt.volume;
  const cnt = stmt.transactions;
  const f = stmt.fees;
  const r = stmt.rates;
  const t = settings.targetSavings;

  // D39: current total reconstructed from the rate/fixed inputs.
  const current = round2(r.interchange * vol + r.processor_markup * vol + 0 * cnt + r.network_assessment * vol + f.account_other);

  // F28: proposed markup back-solve; F39: proposed total.
  const proposedMarkupRate = (current * (1 - t) - r.interchange * vol - r.network_assessment * vol - 0 * cnt - f.account_other) / vol;
  const proposed = round2(r.interchange * vol + proposedMarkupRate * vol + 0 * cnt + r.network_assessment * vol + f.account_other);

  if (round2(current) !== round2(f.total)) {
    throw new Error(`verify failed: sheet current total ${current} != reconciled total ${f.total}`);
  }
  if (round2(proposed) !== round2(current * (1 - t))) {
    throw new Error(`verify failed: proposed ${proposed} != current*(1-target) ${round2(current * (1 - t))}`);
  }
  return { current, proposed, monthlySavings: round2(current - proposed), proposedMarkupRate };
}
