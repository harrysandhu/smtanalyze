# smtanalyze — Merchant Statement Analysis → Quote

Ingest a merchant processing statement (PDF), extract and reconcile every fee to
the penny, and produce a branded **Interchange-Plus quote** as an Excel workbook
with live formulas — the document a rep hands a merchant.

This repo contains:

1. A **working Python proof-of-concept** that runs the whole process end-to-end
   on the sample statements, with a hard zero-error reconciliation gate and an
   independent quote verifier.
2. The **processor skills** (Agent Skill format) that encode how to read each
   processor's statement.
3. A **generalized architecture** (`docs/ARCHITECTURE.md`) for the production
   TypeScript / Claude Agent SDK service.

## What it does (demonstrated)

Given the Fiserv sample statement for **City of Palm Beach Gardens (Sandhill
Crane)** — $446,986.19 volume, 3,447 transactions — the pipeline:

- identifies the processor (Fiserv/CardPointe),
- extracts and **reconciles 16/16 checks** (total fees = $12,654.34, matching
  the documented ground truth to the penny),
- normalizes to the four universal fee buckets,
- and emits a 15%-savings Interchange-Plus quote:

| | Current (Fiserv) | Proposed (Gratify IC+) |
| --- | --- | --- |
| Effective rate | 2.83% | 2.41% |
| Processor markup | 0.90% | 0.48% |
| Monthly fees | $12,654.34 | $10,756.19 |
| **Monthly savings** | | **$1,898.15** |
| **Annual savings** | | **$22,777.81** |
| **3-year savings** | | **$68,333.44** |

Interchange and card-brand assessments pass through unchanged; the savings come
entirely from reducing the processor markup. All figures in the workbook are
**live Excel formulas** driven by one editable "Target Savings" cell.

Output workbooks are in `output/`. The same pipeline also runs on Paynuity
(18/18 checks) — see `output/Core Vital Medical - Gratify IC+ Quote.xlsx`.

## Run it

```bash
pip install -r requirements.txt   # pdfplumber, openpyxl, formulas

# Folder + merchant filter (or pass a single PDF path), with quote settings:
python3 scripts/run_msa.py "<statements folder>" --merchant "Sandhill" \
    --out "output/Sandhill Crane - Gratify IC+ Quote.xlsx" \
    --target 0.15 --prepared-by "Your Name" --email "you@example.com"

# Independently verify the workbook ties out to the penny:
python3 scripts/verify_quote.py \
    "output/Sandhill Crane - Gratify IC+ Quote.xlsx" \
    "output/Sandhill Crane - Gratify IC+ Quote.normalized.json"
```

`run_msa.py` **aborts** unless reconciliation is 100% — a statement that does
not fully reconcile never produces a quote.

## Layout

```
scripts/
  run_msa.py          orchestrator: identify -> parse -> RECONCILE GATE -> normalize -> quote
  parse_fiserv.py     Fiserv/CardPointe/Newtek parser (pdfplumber, --json/--validate)
  parse_paynuity.py   Paynuity (TSYS white-label) parser
  normalize.py        processor-specific output -> universal NormalizedStatement (4 buckets)
  generate_quote.py   branded IC+ quote workbook, live formulas (mirrors the Klack template)
  verify_quote.py     re-evaluates the workbook's formulas; asserts penny-equal to the parser
skills/
  msa-processor-knowledge/   processor ID, pricing-model detection, L2/L3, report spec
  fiserv-statement/          Fiserv extraction skill + parser
  paynuity-statement/        Paynuity extraction skill + parser
samples/                     reference quote template (Klack IC+)
output/                      generated quotes (.xlsx) + normalized data (.json)
docs/ARCHITECTURE.md         the production TypeScript / Claude Agent SDK design
```

## The generalized system

`docs/ARCHITECTURE.md` lays out the TypeScript service: how to load these Agent
Skills (Managed Agents `skills` field, or the Agent SDK's filesystem skills),
how to use web search for interchange-table refresh, the multi-step agentic loop
with two hard verification gates, and how the "agent for judgment, code for
arithmetic" split gets to a zero-error tolerance on the numbers that reach a
merchant.
