# MSA Quote Engine (TypeScript)

Vision-LLM extraction + deterministic verification + Interchange-Plus quote
generation. This is the production implementation of the design in
[`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) and the agentic-vs-deterministic
debate that shaped it.

## The split (why it's built this way)

- **Extraction is a vision-LLM** (`extract.ts`). It reads the statement as a
  visual document via Claude's PDF/document input and returns schema-valid JSON
  (structured outputs). This generalizes to new processors — no per-format regex.
- **The model authors the reconciliation, code executes it** (`reconcile.ts`).
  The model decides *which* identities should hold for this statement (adaptive)
  and returns them; this code performs the arithmetic **exactly and
  independently** against the statement's own printed grand total. The model
  never adds numbers in its head — that's the one thing ruled out for a
  zero-error financial deliverable.
- **Self-correction loop** (`pipeline.ts`). If reconciliation fails, the failing
  identity + the exact figures and source lines are fed back and the page is
  re-extracted (≤ N). Still failing → human-review queue, no quote.
- **Quote is live Excel formulas** (`quote.ts`), and an independent TS recompute
  (`verifyQuote`) asserts the sheet ties to the reconciled total to the penny.

## Files

```
src/
  schema.ts     Zod schemas — RawStatementData (incl. model-authored identities), NormalizedStatement, QuoteSettings
  extract.ts    vision extraction via client.messages.parse + zodOutputFormat (structured outputs)
  reconcile.ts  deterministic executor of the model's identities + printed-total cross-check; feedback builder
  normalize.ts  RawStatementData -> NormalizedStatement (four universal fee buckets)
  pipeline.ts   extract -> reconcile gate -> self-correct loop -> normalize
  quote.ts      ExcelJS workbook (live formulas) + independent verifyQuote
  cli.ts        msa-analyze <pdf> -> quote.xlsx
test/
  smoke.ts      deterministic-path test (no API key): reconcile/normalize/quote on the Sandhill numbers
```

## Run

```bash
npm install
export ANTHROPIC_API_KEY=sk-ant-...
npm run analyze -- "/path/to/statement.pdf" --out "output/quote.xlsx" \
    --target 0.15 --prepared-by "Your Name" --email "you@example.com"
```

`analyze` exits non-zero and prints the failing checks if the statement can't be
reconciled — it never emits a quote on unverified numbers.

Deterministic path only (no API key), to confirm the quote math:

```bash
npx tsx test/smoke.ts
```

## Notes / things to verify against current docs

- Built and typechecked against `@anthropic-ai/sdk` 0.104.x (structured outputs,
  `messages.parse`, `helpers/zod`) and Zod v4. `output_config.format` carries the
  schema; `output_config.effort` controls depth; `thinking: { type: "adaptive" }`.
- Grounding here is page + verbatim source line per value (what PDF document
  input gives you). Pixel-accurate bounding boxes require rendering pages to
  images and using high-res vision (Opus 4.7+ returns 1:1 pixel coords) — a
  drop-in swap in `extract.ts` if you want click-to-cell highlighting.
- The model-authored-identities + code-executes design is the controllable
  realization of "agentic decides, deterministic computes." The alternative —
  the server-side **code execution** tool, where the model writes and runs the
  verification Python itself — is equivalent in principle and a reasonable
  swap if you'd rather the model generate the checker than emit it as data.
