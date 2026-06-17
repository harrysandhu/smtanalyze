# MSA Quote Engine — Generalized TypeScript Architecture

How to turn the working Python proof-of-concept in this repo into a production
TypeScript service that ingests merchant statement PDFs, analyzes them with the
processor skills, and emits a branded Interchange-Plus quote — with a
**zero-error tolerance** on the numbers that reach a merchant.

This document answers the three questions that drove it:

1. Can we use **Agent Skills** from a Claude SDK? (Yes — two ways, below.)
2. Do we get **web search**? (Yes — a server-side tool.)
3. What is the right shape for a **multi-step agentic loop** that PDFs demand,
   and how do we get to zero error rate?

It is grounded in the Claude API/SDK reference as of the assistant knowledge
cutoff (January 2026). Anywhere a number or field name could drift, it is
flagged "verify against docs."

---

## 1. The core insight: agent for judgment, code for arithmetic

A merchant statement PDF is not one extraction problem; it is a pipeline of
them, and the failure modes are different at each stage:

| Stage | Nature | Who should do it |
| --- | --- | --- |
| Identify the processor | Fuzzy pattern match over layout/branding | **LLM** (or a cheap fingerprint) |
| Extract every number | Deterministic, must be exact | **Python parser** (pdfplumber + regex) |
| Reconcile the extraction | Pure arithmetic | **Python** (reconciliation formulas) |
| OCR a scanned/photographed statement | Vision + judgment | **LLM** (multimodal) feeding the parser |
| Decide pricing / apply discount | Business rule | **Code** (deterministic) |
| Build the Excel quote | Templated, must be live formulas | **Python/`openpyxl`** (or the `xlsx` skill) |
| Verify the quote ties out | Arithmetic | **Python** (re-evaluate formulas) |

The zero-error requirement is impossible if a language model is asked to do the
arithmetic — LLMs do not reconcile sums to the penny reliably, and "usually
right" is not acceptable on a document a rep hands a merchant. The architecture
therefore confines the model to **judgment** (which processor is this? is this
page scanned? does this number look like an OCR misread?) and confines every
dollar figure to **deterministic Python that must pass reconciliation before a
quote is allowed to exist.** This is exactly what the proof-of-concept does:
`run_msa.py` aborts if reconciliation is not 100%, and `verify_quote.py`
re-evaluates the workbook's formulas with an independent engine and asserts the
sheet ties to the parser to the penny.

The agent loop is the orchestrator and the fallback handler — not the
calculator.

---

## 2. Can we use Skills? Yes — pick the surface

The processor knowledge in this repo is already in Agent Skill format
(`skills/*/SKILL.md` + `scripts/`). There are two first-party ways to run an
agent that loads them, and the choice drives the rest of the architecture.

### Option A — Managed Agents (recommended for this use case)

Anthropic hosts the agent loop and a per-session container; you create a
persisted **Agent** config and start **Sessions** against it.

- **Skills are a first-class field.** `agents.create({ skills: [...] })` accepts
  both Anthropic prebuilt skills and your custom skills:
  ```ts
  const agent = await client.beta.agents.create({
    name: "MSA Statement Analyzer",
    model: "claude-opus-4-8",
    system: MSA_SYSTEM_PROMPT,
    tools: [{ type: "agent_toolset_20260401" }],   // bash, read, write, edit, grep, web_search...
    skills: [
      { type: "anthropic", skill_id: "xlsx" },     // build the quote workbook
      { type: "anthropic", skill_id: "pdf" },
      { type: "custom", skill_id: "skill_msa_processor_knowledge", version: "latest" },
      { type: "custom", skill_id: "skill_fiserv_statement", version: "latest" },
      { type: "custom", skill_id: "skill_paynuity_statement", version: "latest" },
    ],
  });
  ```
  Custom skills are uploaded once via the Skills API (`POST /v1/skills`,
  `/v1/skills/{id}/versions`) — our `SKILL.md` + `scripts/` folders package
  directly. Max 20 skills per agent.
- **The container already has what the parsers need.** The hosted code-execution
  environment ships `pdfplumber`, `openpyxl`, `pandas`, `pillow`, `pypdf`,
  `python-docx`/`python-pptx`, and `pytesseract`-adjacent tooling — so the
  `parse_fiserv.py` / `parse_paynuity.py` scripts and the `openpyxl` quote
  generator run as-is via the `bash`/`code_execution` tools, and the `xlsx`
  skill can produce branded workbooks.
- **Statements go in, quotes come out as files.** Upload the PDF as a session
  resource (mounted read-only); the agent writes the `.xlsx` to
  `/mnt/session/outputs/` and you pull it with
  `files.list({ scope_id: session.id })` → `files.download`.
- **Outcomes give a graded loop for free.** Instead of a chat turn, send
  `user.define_outcome` with a rubric ("every reconciliation check passes; the
  workbook's current-column total equals the parser total to the penny; the
  proposed total equals current × (1 − target)"). The harness iterates →
  grades → revises until the rubric passes or `max_iterations` is hit. This is
  the zero-error gate expressed as a first-class loop.
- **Trade-off:** Anthropic runs the compute. If the deterministic parsers must
  run inside your own VPC (PCI scope, statement data residency), use a
  `self_hosted` environment — the agent loop stays on Anthropic, tool execution
  moves to a worker you run — or use Option B.

### Option B — Claude Agent SDK / Messages API, you host the loop

If you want the parsers in-process and full control of the compute:

- **Agent SDK** (`@anthropic-ai/claude-agent-sdk`) discovers filesystem skills
  from `.claude/skills/*/SKILL.md` (loaded via `settingSources`, invoked through
  the `Skill` tool). *Verify the exact option name against the Agent SDK docs —
  it has moved between releases.*
- **Messages API** (`@anthropic-ai/sdk`) has **no** skills feature. You either
  (a) replicate the skill as a system prompt + custom tools, or (b) use the
  server-side **code execution** tool, whose container can run the parser
  scripts. The processor knowledge becomes the system prompt; the parsers
  become tools (next section).

**Recommendation:** Managed Agents (Option A) with the Outcome loop for the
production pipeline — it gives Skills, the hosted Python environment the parsers
need, file in/out, and a graded loop with the least glue code. Keep Option B
(Messages API + custom tools, self-hosted) as the path if statement PDFs may
not leave your infrastructure.

---

## 3. Web search — yes, as a server-side tool

Built-in. In the agent toolset it is `web_search`; on the raw Messages API it is
the `web_search_20260209` server tool (with `web_fetch_20260209`). You declare
it and Claude runs the queries server-side, returning cited results. Pricing is
per-search on top of tokens (commonly cited at ~$10 per 1,000 searches —
**verify current pricing in Console**, and it may need org enablement).

Where it earns its place in *this* pipeline (not the hot path):

- **Interchange table refresh.** Visa/Mastercard publish interchange every April
  and October; the L2/L3 and padded-interchange logic needs current tables.
  `web_search` + `web_fetch` can pull the published rates when the bundled
  reference PDFs are stale (>6 months), satisfying the "flag stale reference
  data" requirement in the feature spec.
- **Unknown processor research.** When a statement matches no parser fingerprint
  (the `x`-prefixed white-label folders), the agent can search for the
  processor's statement format before attempting a generic extraction.

Keep it off the per-statement extraction path: extraction must be deterministic
and offline. Web search is for reference-data and onboarding-new-processors
work, gated behind explicit steps.

---

## 4. The pipeline as an agentic loop

```
                 ┌─────────────────────────────────────────────────────────┐
   PDF  ─────────▶  STAGE 1  Identify processor                             │
                 │   fingerprint (regex on extracted text) → processor key  │
                 │   miss → LLM vision/judgment + optional web_search        │
                 ├─────────────────────────────────────────────────────────┤
                 │  STAGE 2  Extract (deterministic tool)                    │
                 │   parse_<processor>(pdf) → RawStatementData (JSON)        │
                 │   no text layer? → render @300dpi, OCR, LLM verifies      │
                 ├─────────────────────────────────────────────────────────┤
                 │  STAGE 3  Reconcile  ── HARD GATE ──                      │
                 │   all checks pass?  no → repair loop (≤ N) or human queue │
                 ├─────────────────────────────────────────────────────────┤
                 │  STAGE 4  Normalize → NormalizedStatement (4 buckets)     │
                 ├─────────────────────────────────────────────────────────┤
                 │  STAGE 5  Quote: apply settings (15% target), live xlsx   │
                 ├─────────────────────────────────────────────────────────┤
                 │  STAGE 6  Verify quote ── HARD GATE ──                    │
                 │   re-evaluate formulas; penny-equal to parser? else fail  │
                 └─────────────────────────────────────────────────────────┘
                                       │
                          Quote.xlsx + confidence report
```

Stages 1–6 mirror the Python proof-of-concept exactly (`run_msa.py` is stages
1–5; `verify_quote.py` is stage 6). The agent's job is the arrows *between*
stages and the **off-ramps**: an extraction that won't reconcile, a scanned
page, a processor with no parser.

### Idiomatic loop control

- **Messages API / Agent SDK manual loop:** call → inspect `stop_reason` →
  execute tool → feed `tool_result` back → repeat until `end_turn`. Bound it
  with a max-turn / max-budget cap; on `pause_turn` (server-tool iteration
  limit) re-send to continue.
- **Managed Agents:** stream session events; the loop is hosted. Drive the
  zero-error contract with `user.define_outcome` + rubric and read
  `span.outcome_evaluation_end.result`.
- **Subagents** for fan-out: a batch of statements for one merchant (trend
  quote) or different merchants (queue) maps to one subagent per statement so
  each gets a clean context; results return as a single tool result to the
  parent. Use a cheaper model (Haiku/Sonnet) for the per-statement extraction
  subagents and reserve Opus/Fable for identification of unknown formats and
  OCR verification.

### Custom tools (Option B shape)

Wrap each deterministic parser as an in-process tool so the model can call it
but never re-implement it:

```ts
import { tool, createSdkMcpServer } from "@anthropic-ai/claude-agent-sdk"; // verify import path
import { z } from "zod";
import { execFile } from "node:child_process";

const parseFiserv = tool(
  "parse_fiserv",
  "Extract + reconcile a Fiserv/CardPointe statement. Returns RawStatementData JSON with a reconciliation block.",
  { pdf_path: z.string() },
  async ({ pdf_path }) => {
    const out = await run("python3", ["scripts/parse_fiserv.py", pdf_path, "--json"]);
    return { content: [{ type: "text", text: out }], structuredContent: JSON.parse(out) };
  },
);
// register: createSdkMcpServer({ name: "msa", tools: [parseFiserv, parsePaynuity, generateQuote, verifyQuote] })
```

The tool returns the parser's own reconciliation result; the model is
instructed never to emit a quote when `reconciliation.all_passed` is false.

---

## 5. How we actually reach zero error

Zero error is not a model property; it is a property of the gates. Five
mechanisms, in order of importance:

1. **Deterministic extraction + reconciliation, not LLM arithmetic.** Every
   number on the quote traces to a Python-extracted value that passed the
   processor's reconciliation formulas (`R1…Rn`). The proof-of-concept runs
   16/16 (Fiserv) and 18/18 (Paynuity) on real statements; the gate refuses to
   continue otherwise.
2. **A second, independent verification of the output.** `verify_quote.py`
   re-evaluates the generated workbook's *formulas* with a separate engine and
   asserts the computed current total equals the parser total to the penny and
   the proposed total equals current × (1 − target). The generator is never
   trusted to be correct — it is checked.
3. **Live formulas, not baked numbers.** The feature spec mandates it and it is
   a correctness control: a reviewer (or the merchant's accountant) can change
   any input cell and watch the sheet recompute, so a wrong constant cannot
   hide.
4. **Structured outputs for anything the model does produce.** Use
   `output_config.format` with a JSON schema (or `client.messages.parse()` with
   Zod) for the identification verdict and the OCR-corrected fields — the model
   returns schema-valid JSON or the call fails, instead of free text we have to
   re-parse.
5. **Confidence + human-review queue.** When reconciliation can't be made to
   pass within N repair turns, or OCR confidence is low, the statement does not
   silently produce a quote — it lands in a review queue with the failing
   checks attached. "Zero error" includes "zero *wrong* quotes," which means
   sometimes the answer is "needs a human," surfaced explicitly.

Supporting mechanisms: **prompt caching** of the (stable) system prompt + skill
instructions + statement text so the repair loop is cheap (cache reads ~0.1× of
input); **token counting** before large batches; and **model choice** — Opus
4.8 (`claude-opus-4-8`) or Fable 5 (`claude-fable-5`) for the careful judgment
steps, Sonnet 4.6 (`claude-sonnet-4-6`) for high-volume extraction subagents,
Haiku 4.5 (`claude-haiku-4-5`) for cheap fingerprinting.

### Current models and pricing (verify in Console before relying on cost)

| Model | ID | Input $/MTok | Output $/MTok | Use here |
| --- | --- | --- | --- | --- |
| Claude Fable 5 | `claude-fable-5` | 10 | 50 | Hardest unknown-format / OCR judgment |
| Claude Opus 4.8 | `claude-opus-4-8` | 5 | 25 | Default orchestrator + verification |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | 3 | 15 | High-volume extraction subagents |
| Claude Haiku 4.5 | `claude-haiku-4-5` | 1 | 5 | Processor fingerprinting |

(Note for code: Fable 5 / Opus 4.8 use adaptive thinking only — no
`budget_tokens`, no `temperature`; control depth with `output_config.effort`.)

---

## 6. Data model and persistence

The normalizer's `NormalizedStatement` (see `scripts/normalize.py`) is the
single shape every downstream consumer reads — four universal fee buckets
(`interchange`, `network_assessment`, `processor_markup`, `account_other`) plus
volume, transactions, card mix, rates, risk flags, and the reconciliation
result. This matches the MSA-46 taxonomy and the v2 foundation
(`statements` table with `raw_data` jsonb + `normalized_data` jsonb in Supabase):

- `raw_data` ← the processor parser's full JSON output.
- `normalized_data` ← `NormalizedStatement`.
- The most recent quote attaches to the merchant's gKey for SmartMPA reuse
  (feature-spec requirement).

Multi-statement upload (same merchant, multiple months) is handled by running
stages 1–4 per file and aggregating into a trend before stage 5 — the
proof-of-concept already proves stages 1–4 are per-file and processor-agnostic.

---

## 7. Build sequence

1. **Lift the Python parsers as-is.** They are tested and reconcile. Whether
   Option A (run in the hosted container) or B (custom tools), do not rewrite
   them in TypeScript — that would re-introduce extraction risk for no gain.
2. **Package the three skills** via the Skills API (Option A) or drop them in
   `.claude/skills/` (Option B).
3. **Wire the orchestrator** — `query()` loop (Agent SDK) or sessions + Outcome
   (Managed Agents), with the reconciliation gate and the independent quote
   verifier as non-negotiable steps.
4. **TypeScript service surface** — REST/queue endpoint that takes a PDF + quote
   settings, returns the workbook + a confidence report, persists both jsonb
   blobs, and routes gate failures to the review queue.
5. **Interchange-table refresh job** — scheduled `web_search`/`web_fetch` to keep
   reference rates fresh and flag staleness.

The Python in this repo is the executable spec for stages 1–6; the TypeScript
service is the agentic shell, skill loader, persistence, and API around it.
