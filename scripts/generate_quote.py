#!/usr/bin/env python3
"""
Gratify MSA quote generator.

Builds a branded, single-location Interchange-Plus quote workbook from a
NormalizedStatement (see normalize.py) plus quote settings. Mirrors the
structure of the reference template (Klack Enterprises - IC+ Quote v1.xlsx).

Design rules (from MSA Feature Requirements v2, "Excel Download"):
  * ALL calculated values are live Excel formulas, never pre-computed numbers.
    Change any input cell and the whole sheet recalculates.
  * Interchange and card-brand assessments are PASSTHROUGH: the proposed
    column references the current column, so they never change.
  * The single competitive lever is the processor markup (discount rate).
    The proposed discount rate back-solves from one input cell, "Target
    Savings", so a rep can dial savings up or down and watch the rate move.

Usage (normally called by run_msa.py, but runnable directly):
    python generate_quote.py <normalized.json> <out.xlsx> \
        --target 0.15 --prepared-by "Name" --email "a@b.com"
"""

import argparse
import datetime as dt
import json

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# Gratify brand palette (from msa-processor-knowledge SKILL.md)
BLUE = "1A568E"
RED = "C00000"
GREEN_FILL = "E2EFDA"
BLUE_FILL = "D6E4F0"
AMBER_FILL = "FFF2CC"
GREY_FILL = "F2F2F2"

PCT = "0.0000%"
PCT2 = "0.00%"
USD = '"$"#,##0.00'
USD0 = '"$"#,##0'


def _thin(color="BFBFBF"):
    s = Side(style="thin", color=color)
    return Border(left=s, right=s, top=s, bottom=s)


def build_quote(stmt, out_path, target=0.15, prepared_by="Gratify Sales",
                email="sales@gratifypay.com", iso_name="Gratify"):
    wb = Workbook()
    ws = wb.active
    ws.title = "Analysis"

    # Column widths roughly matching the reference template.
    widths = {"A": 2.5, "B": 30, "C": 2.5, "D": 16, "E": 2.5, "F": 16, "G": 2.5}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    label = Font(name="Arial", size=9, color="404040")
    val = Font(name="Arial", size=9)
    bold = Font(name="Arial", size=9, bold=True)
    white_bold = Font(name="Arial", size=9, bold=True, color="FFFFFF")
    right = Alignment(horizontal="right")
    center = Alignment(horizontal="center")

    def put(cell, value, font=val, fmt=None, fill=None, align=None, border=None):
        c = ws[cell]
        c.value = value
        c.font = font
        if fmt:
            c.number_format = fmt
        if fill:
            c.fill = PatternFill("solid", fgColor=fill)
        if align:
            c.alignment = align
        if border:
            c.border = border

    cur = stmt["processor"]
    rates = stmt["rates"]
    fees = stmt["fees"]

    # Absolute cell references used across formulas. Direct refs (not named
    # ranges) keep the workbook portable across Excel / LibreOffice / Sheets.
    D_VOL, F_VOL = "$D$36", "$F$36"
    D_CNT, F_CNT = "$D$37", "$F$37"
    D_TOTAL, F_TOTAL = "$D$39", "$F$39"
    TARGET = "$D$14"

    # ---- Letterhead -------------------------------------------------------
    put("B2", iso_name.upper(), Font(name="Arial", size=22, bold=True, color=BLUE))
    put("B3", "Merchant Rate Review & Interchange-Plus Proposal", Font(name="Arial", size=10, color=BLUE))

    put("B5", "Comparison For:", label); put("D5", stmt["merchant_name"], bold)
    put("B6", "Processor (current):", label); put("D6", cur, val)
    put("B7", "Merchant ID:", label); put("D7", str(stmt.get("mid") or ""), val)
    put("B8", "Statement Period:", label); put("D8", stmt.get("period") or "", val)
    put("B9", "Prepared By:", label); put("D9", prepared_by, val)
    put("B10", "Contact Email:", label); put("D10", email, val)
    put("B11", "Date:", label); put("D11", dt.date.today(), val, fmt="mmm d, yyyy")

    # ---- Settings (the single input that drives proposed pricing) ---------
    put("B13", "Quote Settings", white_bold, fill=BLUE)
    put("D13", "", white_bold, fill=BLUE)
    put("B14", "Target Savings (editable)", label)
    put("D14", target, bold, fmt=PCT2, fill=AMBER_FILL, border=_thin())

    # ---- Estimated Savings ------------------------------------------------
    put("B16", "Estimated Savings", white_bold, fill=BLUE)
    put("D16", "Interchange Plus", white_bold, fill=BLUE, align=center)
    put("B17", "% Savings (per month)", label)
    put("D17", f"=1-({F_TOTAL}/{D_TOTAL})", bold, fmt=PCT2, fill=GREEN_FILL)
    put("B18", "Monthly Savings", label)
    put("D18", f"={D_TOTAL}-{F_TOTAL}", bold, fmt=USD, fill=GREEN_FILL)
    put("B19", "Annual Savings", label)
    put("D19", "=D18*12", bold, fmt=USD, fill=GREEN_FILL)
    put("B20", "3-Year Savings", label)
    put("D20", "=D19*3", bold, fmt=USD, fill=GREEN_FILL)

    # ---- Rate Comparison --------------------------------------------------
    put("B22", "Rate Comparison", white_bold, fill=BLUE)
    put("D22", cur, white_bold, fill=BLUE, align=center)
    put("F22", "Proposed", white_bold, fill=BLUE, align=center)
    put("B23", "Effective Processing Rate", bold)
    put("D23", f"={D_TOTAL}/{D_VOL}", bold, fmt=PCT, fill=BLUE_FILL)
    put("F23", f"={F_TOTAL}/{F_VOL}", bold, fmt=PCT, fill=BLUE_FILL)

    # ---- Statement Analysis table ----------------------------------------
    put("B25", "Statement Analysis", white_bold, fill=BLUE)
    put("D25", cur, white_bold, fill=BLUE, align=center)
    put("F25", "Proposed", white_bold, fill=BLUE, align=center)

    b = _thin()
    # row: (label, current_value_or_formula, current_fmt, proposed, proposed_fmt)
    # Named cells are wired afterward. Rates are % of volume.
    put("B27", "Interchange (passthrough)", label, border=b)
    put("D27", rates["interchange"], val, fmt=PCT, border=b)
    put("F27", "=D27", val, fmt=PCT, fill=GREY_FILL, border=b)  # passthrough

    put("B28", "Processor Markup / Discount Rate", label, border=b)
    put("D28", rates["processor_markup"], val, fmt=PCT, border=b)
    # Proposed markup back-solves so proposed total == current total * (1-target).
    # = (Target proposed total - passthrough$ - fixed monthly) / volume
    put("F28",
        f"=({D_TOTAL}*(1-{TARGET})-F27*{F_VOL}-F29*{F_VOL}-F31*{F_CNT}-F33)/{F_VOL}",
        bold, fmt=PCT, fill=AMBER_FILL, border=b)

    put("B29", "Card Brand & Assessment Fees (passthrough)", label, border=b)
    put("D29", rates["network_assessment"], val, fmt=PCT, border=b)
    put("F29", "=D29", val, fmt=PCT, fill=GREY_FILL, border=b)  # passthrough

    put("B31", "Per-Transaction Fee", label, border=b)
    put("D31", 0.0, val, fmt=USD, border=b)
    put("F31", 0.0, val, fmt=USD, fill=GREY_FILL, border=b)

    put("B33", "Monthly & Account Fees (fixed)", label, border=b)
    put("D33", fees["account_other"], val, fmt=USD, border=b)
    put("F33", "=D33", val, fmt=USD, fill=GREY_FILL, border=b)

    put("B35", "Average Ticket", label, border=b)
    put("D35", f"={D_VOL}/{D_CNT}", val, fmt=USD, border=b)
    put("F35", "=D35", val, fmt=USD, border=b)
    put("B36", "Monthly Volume", label, border=b)
    put("D36", stmt["volume"], val, fmt=USD, border=b)
    put("F36", "=D36", val, fmt=USD, border=b)
    put("B37", "Transaction Count", label, border=b)
    put("D37", stmt["transactions"], val, fmt="#,##0", border=b)
    put("F37", "=D37", val, fmt="#,##0", border=b)

    put("B39", "Total Monthly Fees", bold, fill=GREY_FILL, border=b)
    total_formula = "={ic}*{vol}+{mk}*{vol}+{pt}*{cnt}+{cb}*{vol}+{fx}"
    put("D39", total_formula.format(ic="D27", mk="D28", pt="D31", cnt=D_CNT, cb="D29", vol=D_VOL, fx="D33"),
        bold, fmt=USD, fill=GREY_FILL, border=b)
    put("F39", total_formula.format(ic="F27", mk="F28", pt="F31", cnt=F_CNT, cb="F29", vol=F_VOL, fx="F33"),
        bold, fmt=USD, fill=GREEN_FILL, border=b)

    # ---- Card mix ---------------------------------------------------------
    r = 42
    put(f"B{r}", "Card Mix", white_bold, fill=BLUE)
    put(f"D{r}", "Volume", white_bold, fill=BLUE, align=center)
    put(f"F{r}", "% of Volume", white_bold, fill=BLUE, align=center)
    for m in stmt["card_mix"]:
        r += 1
        put(f"B{r}", m["brand"], label, border=b)
        put(f"D{r}", round(m["volume"], 2), val, fmt=USD, border=b)
        put(f"F{r}", f"=D{r}/{D_VOL}", val, fmt=PCT2, border=b)

    # ---- Notes ------------------------------------------------------------
    r += 2
    recon = stmt["reconciliation"]
    flags = stmt.get("risk_flags", [])
    flag_lines = "\n".join(
        f"  - [{(fl.get('severity') if isinstance(fl, dict) else fl[1])}] "
        f"{(fl.get('detail') if isinstance(fl, dict) else fl[2])}"
        for fl in flags
    ) or "  - None"

    put(f"B{r}", "Processing Notes", bold)
    notes = (
        f"Merchant: {stmt['merchant_name']} (MID {stmt.get('mid')})\n"
        f"Current processor: {cur}\n"
        f"Statement period: {stmt.get('period')}\n"
        f"Pricing model: Interchange Plus.\n\n"
        f"Current effective rate: {rates['effective']*100:.2f}% on "
        f"${stmt['volume']:,.2f} across {stmt['transactions']:,} transactions.\n"
        f"Of total fees, interchange + assessments (${fees['passthrough']:,.2f}) are "
        f"passthrough and unchanged; the proposed savings come entirely from reducing "
        f"the processor markup of ${fees['processor_markup']:,.2f}.\n\n"
        f"Extraction integrity: {recon['passed']}/{recon['checks']} reconciliation "
        f"checks passed ({'VERIFIED' if recon['all_passed'] else 'REVIEW REQUIRED'})."
    )
    nf = Font(name="Arial", size=8, color="404040")
    put(f"B{r+1}", notes, nf)
    ws[f"B{r+1}"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(f"B{r+1}:F{r+9}")

    rr = r + 11
    put(f"B{rr}", "Risk Flags", bold)
    put(f"B{rr+1}", flag_lines, nf)
    ws[f"B{rr+1}"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(f"B{rr+1}:F{rr+4}")

    rr += 6
    put(f"B{rr}", "Terms", bold)
    terms = (
        "This Interchange-Plus proposal passes through Visa, Mastercard, Discover and "
        "Amex interchange and assessments at cost, with a transparent processor markup. "
        "Interchange and assessment figures are taken directly from the merchant's own "
        "statement and are not marked up.\n"
        "Quote valid for 30 days from the date above. Rates assume processing profile "
        "consistent with the analyzed statement. Final pricing subject to underwriting "
        "approval. Savings are estimates based on the statement provided."
    )
    put(f"B{rr+1}", terms, nf)
    ws[f"B{rr+1}"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(f"B{rr+1}:F{rr+6}")

    ws.sheet_view.showGridLines = False
    wb.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("normalized_json")
    ap.add_argument("out_xlsx")
    ap.add_argument("--target", type=float, default=0.15)
    ap.add_argument("--prepared-by", default="Gratify Sales")
    ap.add_argument("--email", default="sales@gratifypay.com")
    args = ap.parse_args()

    with open(args.normalized_json) as fh:
        stmt = json.load(fh)
    path = build_quote(stmt, args.out_xlsx, target=args.target,
                       prepared_by=args.prepared_by, email=args.email)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
