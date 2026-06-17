# MSA Quote Engine — Generalized TypeScript Architecture

How to turn the working Python proof-of-concept in this repo into a production
TypeScript service that ingests merchant statement PDFs, analyzes them with the
processor skills, and emits a branded Interchange-Plus quote — with a
**zero-error tolerance** on the numbers that reach a merchant.

This document answers the questions that drove it:

1. How do we **stop relying on brittle heuristic parsers** and extract
   agentically with vision models, so the system doesn't break on every new
   processor? (Section 1 — vision extracts, deterministic math verifies; the
   web-research basis is in 1b.)
2. Can we use **Agent Skills** from a Claude SDK? (Yes — two ways, Section 2.)
3. Do we get **web search**? (Yes — a server-side tool, Section 3.)
4. What is the right shape for a **multi-step agentic loop** that PDFs demand,
   and how do we get to zero error rate? (Sections 4–5.)

It is grounded in the Claude API/SDK reference as of the assistant knowledge
cutoff (January 2026). Anywhere a number or field name could drift, it is
flagged "verify against docs."

---

## 1. The core insight: vision-LLM extracts, deterministic math verifies

The proof-of-concept in this repo extracts with per-processor regex parsers
(`pdfplumber` + regular expressions). That is the right way to *prove the
pipeline* — the parsers are exact and reconcile to the penny — but it is the
**wrong long-term extraction strategy**, for exactly the reason a regex parser
always disappoints: it encodes one processor's precise layout, so a new
processor (every `x`-prefixed folder in the statement library) or even a layout
revision breaks it. The industry consensus is blunt about this — rule-based
parsing is "complicated and brittle to maintain," and the text it produces is
"lossy compression that removes layout, alignment, and visual cues." Writing a
new regex parser per processor does not scale and does not generalize.

So move extraction to a **vision-LLM**. But do it with eyes open about the one
failure mode that matters here: vision models **hallucinate numbers**. Studies
put ~68% of financial-extraction errors on hallucinated numerical values; a bare
single-shot VLM scored ~45% on dense forms; there is now a dedicated benchmark
(FinCriticalED, late 2025) precisely because VLMs misread financial figures at
measurable rates. "Feed the PDF to Claude vision and trust the JSON" would be
*less* safe on the dollars than the regex parser, not more.

The resolution is the reframing that makes both halves true:

> **The vision-LLM extracts (it generalizes across formats). Deterministic
> arithmetic verifies (it guarantees the dollars). An agentic loop connects
> them — re-examining the image and self-correcting until the numbers tie out,
> escalating to a human when they can't.**

The regex was doing two jobs at once: extracting *and* — via the reconciliation
formulas — verifying. We split them. Extraction becomes a vision task that needs
no per-processor code. Verification stays deterministic Python — but here is the
load-bearing point: **the reconciliation identities are processor-agnostic in
structure.** "Line items sum to the total," "fees = discount + interchange +
assessments," "rate × volume + per-item × count = total" hold for a processor
nobody has ever parsed. They validate a vision extraction from an *unseen*
format without anyone writing new regex. The deterministic layer stops being a
brittle per-processor *parser* and becomes a universal *checker*.

| Stage | Nature | Who does it |
| --- | --- | --- |
| Identify the processor | Fuzzy pattern match over layout/branding | **Vision-LLM** (cheap fingerprint only as a fast-path) |
| Extract every number | Read figures off the rendered page | **Vision-LLM** + structured output, grounded to bounding boxes |
| Reconcile the extraction | Processor-agnostic arithmetic identities | **Deterministic code** — the zero-error gate |
| Self-correct on mismatch | Re-read the image, fix the misread | **Agentic loop** (vision-LLM) |
| Decide pricing / apply discount | Business rule | **Code** (deterministic) |
| Build the Excel quote | Templated, live formulas | **`xlsx` skill** / `openpyxl` |
| Verify the quote ties out | Arithmetic | **Code** — re-evaluate the formulas |

What stays exactly as in the proof-of-concept: the reconciliation gate
(`run_msa.py` aborts unless 100%) and the independent quote verifier
(`verify_quote.py` re-evaluates the workbook's formulas and asserts penny
equality). Those become *more* important in a vision world, not less — they are
what converts a model that is "usually right" into a quote that is right on
every number that ships.

---

## 1b. Why this is the current best practice (web research, 2025–2026)

Synthesis of recent benchmarks and production write-ups:

- **Pure single-shot VLM is not production-grade for financial tables.** Bare
  VLMs "frequently hallucinated or dropped content on dense financial tables";
  ~45% accuracy on a forms benchmark; hallucinated numbers are the #1 error
  class. This is the trap to avoid.
- **Brittle regex/template parsing is the other trap.** Breaks on anything new;
  lossy; high maintenance. (Our PoC parsers are the demonstration, not the
  destination.)
- **Agentic vision + verification is what wins.** Hybrid agentic platforms reach
  ~90% table accuracy vs 64–83% for single-model cloud OCR. The shared recipe:
  treat the document as a *visual object*, run *multiple extraction passes* with
  a *critic/verification step*, and **ground every field to a bounding box**, so
  a hallucinated value has no valid source location and is caught — and a human
  can be shown the exact cell it came from.
- **Critic/verification agents measurably cut hallucinations** and beat
  single-pass, at ~2× compute. Mitigation that works: ground answers in the
  source, require citations/coordinates, route low-confidence items to a
  stronger model or a human, track per-field confidence.

Net: the field is converging on exactly the split above — generalize with
vision, guarantee with deterministic checks and grounding, iterate with an
agent. For *our* problem we have an unusually strong verifier (the statement's
own arithmetic must close), which is what lets us aim at zero error rather than
~90%.

Sources:
- [Best LLM-Ready Document Parsers in 2025 — Reducto](https://llms.reducto.ai/best-llm-ready-document-parsers-2025)
- [FinCriticalED: A Visual Benchmark for Financial Fact-Level OCR](https://arxiv.org/pdf/2511.14998)
- [Why Agentic Document Extraction Finally Makes Sense (LandingAI DPT-2)](https://pub.towardsai.net/landingais-dpt-2-in-2026-why-agentic-document-extraction-finally-makes-sense-629a5115b80f)
- [Benchmarking Multi-Agent LLM Architectures for Financial Document Processing](https://arxiv.org/pdf/2603.22651)
- [Towards reducing hallucination in extracting information from financial documents](https://arxiv.org/pdf/2310.10760)
- [What is Agentic Document Extraction? (2026 Guide) — Parseur](https://parseur.com/blog/agentic-document-extraction)

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
- **Unknown processor research.** When the vision model can't confidently
  identify a processor (the `x`-prefixed white-label folders), the agent can
  search for the processor's statement format to inform extraction — then the
  reconciliation gate still validates whatever it reads.

Keep it off the inner extraction loop — extraction reads the rendered page, not
the web. Web search is for reference-data refresh and onboarding new processors,
gated behind explicit steps.

---

## 4. The pipeline as an agentic loop

```
                 ┌─────────────────────────────────────────────────────────┐
   PDF  ─────────▶  STAGE 1  Identify processor (vision-LLM)                 │
   (render pages   │   read branding/layout → processor key + format notes  │
    to images)     │   unknown? → load generic skill + optional web_search   │
                 ├─────────────────────────────────────────────────────────┤
                 │  STAGE 2  Extract (vision-LLM, structured output)         │
                 │   read every figure off the rendered page →               │
                 │   RawStatementData JSON, each value grounded to a bbox     │
                 ├─────────────────────────────────────────────────────────┤
                 │  STAGE 3  Reconcile  ── HARD GATE (deterministic) ──      │
                 │   processor-agnostic identities (sums close, fees=parts)  │
                 │   pass? → on.  fail? → STAGE 2b                            │
                 ├─────────────────────────────────────────────────────────┤
                 │  STAGE 2b Self-correct (agentic loop, ≤ N)               │
                 │   show the failing identity + bbox crops; re-read; retry  │
                 │   still failing after N → human-review queue              │
                 ├─────────────────────────────────────────────────────────┤
                 │  STAGE 4  Normalize → NormalizedStatement (4 buckets)     │
                 ├─────────────────────────────────────────────────────────┤
                 │  STAGE 5  Quote: apply settings (15% target), live xlsx   │
                 ├─────────────────────────────────────────────────────────┤
                 │  STAGE 6  Verify quote ── HARD GATE (deterministic) ──    │
                 │   re-evaluate formulas; penny-equal to extraction? else   │
                 │   fail                                                    │
                 └─────────────────────────────────────────────────────────┘
                                       │
                          Quote.xlsx + confidence + grounding report
```

The deterministic stages (3, 6) are lifted directly from the proof-of-concept —
the reconciliation formulas and `verify_quote.py` are unchanged. What changes is
stages 1–2: vision-LLM extraction replaces the per-processor regex parsers, so a
new processor needs **knowledge** (a skill describing its layout), not new code.
The reconciliation gate validates that extraction regardless of processor,
because the identities are structural. The agent's real work is the **2 ⇄ 3
self-correction loop** and the **off-ramps**: an extraction that won't reconcile
after N tries, a page the model is unsure about, a processor it can't identify.

> **Migration note.** The repo's regex parsers don't get thrown away on day one
> — they stay as a fast, free, exact path for the handful of high-volume
> processors already covered (Fiserv, Paynuity), and as an oracle to evaluate
> the vision extractor against. New/long-tail processors go straight to the
> vision path. Over time the vision path is the default and the regex parsers
> are an optimization, not a requirement.

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

### Tools: a verifier, not a parser

The custom tools the agent calls are the **deterministic guarantees**, not the
extraction. The vision-LLM produces `RawStatementData` (via structured output);
the tools then check and build:

```ts
import { tool, createSdkMcpServer } from "@anthropic-ai/claude-agent-sdk"; // verify import path
import { z } from "zod";

// The model extracts via vision + structured output; this tool only CHECKS it.
const reconcile = tool(
  "reconcile_statement",
  "Run processor-agnostic reconciliation identities on extracted statement data. " +
    "Returns each check with pass/fail and the exact discrepancy. The agent must " +
    "NOT proceed to a quote unless all_passed is true.",
  { statement: RawStatementSchema },          // the vision extraction
  async ({ statement }) => {
    const result = await run("python3", ["scripts/reconcile.py", "--json"], JSON.stringify(statement));
    return { content: [{ type: "text", text: result }], structuredContent: JSON.parse(result) };
  },
);
// plus generate_quote (openpyxl / xlsx skill) and verify_quote (re-evaluates formulas).
// register: createSdkMcpServer({ name: "msa", tools: [reconcile, generateQuote, verifyQuote] })
```

A failed reconciliation is fed back to the model with the failing identity and
the relevant bounding-box crops, so the next pass re-reads exactly the cells in
doubt. The regex parsers, where they exist, are registered as an *optional*
fast-path tool the agent tries first — but the reconcile/verify tools are the
contract, and they are identical whether extraction came from regex or vision.

---

## 5. How we actually reach zero error

Zero error is not a model property; it is a property of the gates. Five
mechanisms, in order of importance:

1. **Deterministic reconciliation as the gate — even when extraction is a
   vision-LLM.** The model may read the numbers, but no number reaches a quote
   until it passes the processor-agnostic reconciliation identities (`R1…Rn`).
   This is what makes vision extraction safe: a misread breaks an identity (a
   sum stops closing), the agent is shown the failing identity plus the
   bounding-box crop, and it re-reads until the arithmetic ties out — or the
   statement is escalated. The proof-of-concept already runs this gate (16/16
   Fiserv, 18/18 Paynuity) and aborts otherwise; vision extraction plugs into
   the same gate unchanged. **Grounding to bounding boxes** is the partner
   control: a hallucinated value has no valid source coordinate and is caught.
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

- `raw_data` ← the full extraction JSON (`RawStatementData`), now including the
  per-field bounding boxes from the vision pass and the reconciliation result.
- `normalized_data` ← `NormalizedStatement`.
- The most recent quote attaches to the merchant's gKey for SmartMPA reuse
  (feature-spec requirement).

Storing the bounding boxes is what makes the output auditable: ops can click any
figure on the quote and see the exact cell it was read from — the compliance and
trust property the agentic-extraction literature centers on.

Multi-statement upload (same merchant, multiple months) runs extraction +
reconciliation per file and aggregates into a trend before quoting — the
per-file stages are processor-agnostic by construction.

---

## 7. Build sequence

The migration is deliberately staged so the deterministic guarantees come up
first and extraction is swapped underneath them — never the reverse.

1. **Stand up the deterministic verifier as a standalone, processor-agnostic
   tool.** Lift the reconciliation identities out of the per-processor parsers
   into one `reconcile.py` that takes `RawStatementData` and returns the
   pass/fail checks, plus the existing `verify_quote.py`. This is the contract
   everything else plugs into.
2. **Turn the skills into vision-extraction guides.** Each `SKILL.md` keeps the
   layout/fee-structure knowledge but reframes it as instructions for a vision
   model reading the rendered page (what sections exist, what each fee means,
   the gotchas) plus the `RawStatementData` JSON schema to emit — not a regex
   script. Package via the Skills API (Option A) or `.claude/skills/` (Option B).
3. **Build the extraction loop:** render PDF pages to images → vision-LLM emits
   `RawStatementData` (structured output, grounded to bounding boxes) →
   `reconcile` tool → on failure, feed the failing identity + bbox crops back
   and retry (≤ N) → escalate to human queue. Keep the regex parsers registered
   as an optional fast-path for the processors they already cover, and use them
   as the **evaluation oracle** to measure the vision extractor's accuracy
   before trusting it in production.
4. **Wire the orchestrator** — sessions + Outcome (Managed Agents) or `query()`
   loop (Agent SDK), with the reconciliation gate and the independent quote
   verifier as non-negotiable steps; quote built by the `xlsx` skill / `openpyxl`.
5. **TypeScript service surface** — REST/queue endpoint that takes a PDF + quote
   settings, returns the workbook + a confidence + grounding report, persists
   both jsonb blobs, and routes gate failures to the review queue.
6. **Interchange-table refresh job** — scheduled `web_search`/`web_fetch` to keep
   reference rates fresh and flag staleness.

The Python in this repo is the executable spec for the deterministic stages
(reconcile, quote, verify); the vision-LLM replaces the regex extractor; the
TypeScript service is the agentic shell, skill loader, persistence, and API.
