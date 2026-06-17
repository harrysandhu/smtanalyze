#!/usr/bin/env python3
"""
MSA orchestrator (reference Python pipeline).

End-to-end: a statement PDF (or a folder + merchant filter) in, a branded
Interchange-Plus quote workbook out. This is the deterministic backbone that
the planned TypeScript / Claude Agent SDK system wraps in an agentic loop
(see docs/ARCHITECTURE.md).

Stages:
  1. Identify    - fingerprint the processor from the extracted text.
  2. Parse       - run the matching processor parser.
  3. Verify      - reconciliation must be 100%. This is a hard gate: a
                   statement that does not fully reconcile never produces a
                   quote. Zero-error tolerance is enforced here, not hoped for.
  4. Normalize   - collapse to the universal NormalizedStatement schema.
  5. Quote       - generate the Excel workbook with live formulas.

Usage:
    python run_msa.py <pdf>  --out output/quote.xlsx --target 0.15
    python run_msa.py <folder> --merchant "SANDHILL" --out output/quote.xlsx
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import parse_fiserv
import parse_paynuity
import normalize
from generate_quote import build_quote


def identify_and_parse(pdf_path):
    """Return (processor_key, parse_data) or (None, None)."""
    data = parse_fiserv.parse_statement(pdf_path)
    if data is not None:
        return "fiserv", data

    data = parse_paynuity.parse_statement(pdf_path)
    if data and "error" not in data:
        return "paynuity", data

    return None, None


def normalize_for(key, data, source_file):
    if key == "fiserv":
        return normalize.normalize_fiserv(data, source_file)
    if key == "paynuity":
        return normalize.normalize_paynuity(data, source_file)
    raise ValueError(f"no normalizer for {key}")


def pick_statement(path, merchant_filter):
    """Resolve the input path to a single PDF."""
    if os.path.isfile(path):
        return path
    candidates = []
    for fn in sorted(os.listdir(path)):
        if not fn.lower().endswith(".pdf"):
            continue
        if merchant_filter and merchant_filter.lower() not in fn.lower():
            continue
        candidates.append(os.path.join(path, fn))
    if not candidates:
        sys.exit(f"No matching PDF found in {path} (filter={merchant_filter!r})")
    if len(candidates) > 1:
        print(f"[info] {len(candidates)} statements match; using first: "
              f"{os.path.basename(candidates[0])}")
        for c in candidates[1:]:
            print(f"       (also matched: {os.path.basename(c)})")
    return candidates[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="PDF file or folder of statements")
    ap.add_argument("--merchant", help="substring filter when path is a folder")
    ap.add_argument("--out", default="output/quote.xlsx")
    ap.add_argument("--target", type=float, default=0.15, help="target savings, e.g. 0.15")
    ap.add_argument("--prepared-by", default="Gratify Sales")
    ap.add_argument("--email", default="sales@gratifypay.com")
    ap.add_argument("--allow-unverified", action="store_true",
                    help="bypass the reconciliation gate (NOT recommended)")
    args = ap.parse_args()

    pdf = pick_statement(args.path, args.merchant)
    print(f"[1/5] Statement: {os.path.basename(pdf)}")

    key, data = identify_and_parse(pdf)
    if key is None:
        sys.exit("[2/5] Could not identify processor — no parser matched.")
    print(f"[2/5] Identified processor: {key}")

    stmt = normalize_for(key, data, os.path.basename(pdf))
    recon = stmt["reconciliation"]
    print(f"[3/5] Reconciliation: {recon['passed']}/{recon['checks']} checks passed")
    if not recon["all_passed"] and not args.allow_unverified:
        sys.exit("[3/5] ABORT: statement did not fully reconcile. "
                 "Refusing to generate a quote on unverified data. "
                 "(Override with --allow-unverified.)")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    norm_path = os.path.splitext(args.out)[0] + ".normalized.json"
    with open(norm_path, "w") as fh:
        json.dump(stmt, fh, indent=2)
    print(f"[4/5] Normalized -> {norm_path}")
    print(f"      {stmt['merchant_name']}  vol=${stmt['volume']:,.2f}  "
          f"eff={stmt['rates']['effective']*100:.2f}%  "
          f"markup=${stmt['fees']['processor_markup']:,.2f}")

    build_quote(stmt, args.out, target=args.target,
                prepared_by=args.prepared_by, email=args.email)
    print(f"[5/5] Quote -> {args.out}  (target savings {args.target*100:.0f}%)")


if __name__ == "__main__":
    main()
