#!/usr/bin/env python3
"""
Quote verifier — the last gate in the zero-error pipeline.

Re-evaluates the generated workbook's formulas with an independent engine
(no openpyxl cached values, no trust in the generator) and asserts:

  1. The current-column total the SHEET computes equals the total the PARSER
     extracted, to the penny.
  2. The proposed total equals current x (1 - target), to the penny.
  3. Passthrough rows (interchange, assessments) are identical current vs
     proposed.

If any assertion fails the script exits non-zero. Wire this into CI so a
broken template can never ship a wrong number to a merchant.

Usage:
    python verify_quote.py <quote.xlsx> <normalized.json>
"""

import json
import logging
import sys

logging.disable(logging.WARNING)
import formulas  # noqa: E402


def cell(sol, name, c):
    key = [k for k in sol if k.endswith(f"!{c}")]
    if not key:
        raise KeyError(f"cell {c} not found")
    return float(sol[key[0]].value[0, 0])


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: verify_quote.py <quote.xlsx> <normalized.json>")
    quote_path, norm_path = sys.argv[1], sys.argv[2]

    with open(norm_path) as fh:
        stmt = json.load(fh)

    xl = formulas.ExcelModel().loads(quote_path).finish()
    sol = xl.calculate()

    parser_total = stmt["fees"]["total"]
    target = cell(sol, "target", "D14")
    d_total = cell(sol, "current_total", "D39")
    f_total = cell(sol, "proposed_total", "F39")
    d_ic, f_ic = cell(sol, "", "D27"), cell(sol, "", "F27")
    d_as, f_as = cell(sol, "", "D29"), cell(sol, "", "F29")

    fails = []
    if round(d_total, 2) != round(parser_total, 2):
        fails.append(f"current total {d_total:.2f} != parser total {parser_total:.2f}")
    expected_proposed = d_total * (1 - target)
    if round(f_total, 2) != round(expected_proposed, 2):
        fails.append(f"proposed total {f_total:.2f} != current*(1-target) {expected_proposed:.2f}")
    if round(d_ic, 8) != round(f_ic, 8):
        fails.append("interchange not passed through unchanged")
    if round(d_as, 8) != round(f_as, 8):
        fails.append("assessments not passed through unchanged")

    print(f"Merchant:        {stmt['merchant_name']}")
    print(f"Parser total:    ${parser_total:,.2f}")
    print(f"Sheet current:   ${d_total:,.2f}")
    print(f"Sheet proposed:  ${f_total:,.2f}  ({target*100:.0f}% target -> "
          f"${d_total-f_total:,.2f}/mo savings)")

    if fails:
        print("\nVERIFY FAILED:")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print("\nVERIFY PASSED: sheet is penny-exact and passthrough is intact.")


if __name__ == "__main__":
    main()
