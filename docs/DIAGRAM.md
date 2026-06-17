# MSA Quote Engine — System Diagram

```mermaid
flowchart TD
    PDF[("📄 Merchant Statement PDF")]

    subgraph PIPELINE["pipeline.ts — Agentic Loop"]
        direction TB

        EXTRACT["extract.ts\nVision-LLM Extraction\n─────────────────────\nclient.messages.parse()\nthinking: adaptive\noutput_config: effort high\nzodOutputFormat(RawStatementData)\nPDF cached w/ cache_control ephemeral"]

        RAW["RawStatementData\n─────────────────────\nvolume · transactions · fees{}\ncard_mix[]\nvalues[] — grounded to page + source_text\nidentities[] — model-authored"]

        RECON["reconcile.ts\nDeterministic Arithmetic Gate\n─────────────────────\n① buckets_equal_printed_total\n   interchange + network_assessment\n   + processor_markup + account_other\n   == printed_total_fees\n② execute each model-authored\n   identity in code (Map lookup)\n   — no LLM arithmetic"]

        CHECK{allPassed?}

        FEEDBACK["buildFeedback()\n─────────────────────\nfailing identity name\nexact figures vs expected\nsource_text per value\n→ appended to next extraction prompt"]

        RETRY{attempts\n≤ maxRetries?}

        ESCALATE["🚨 Human Review Queue\nstatus: needs_review\nrecon checks attached\nno quote emitted"]
    end

    subgraph OUTPUT["Output Stage"]
        NORM["normalize.ts\nRawStatementData → NormalizedStatement\n─────────────────────\nfour universal fee buckets\ninterchange · network_assessment\nprocessor_markup · account_other\ntotal · passthrough"]

        VERIFY["verifyQuote()\n─────────────────────\nindependent TS recompute\ncurrent == printed_total_fees ✓\nproposed == current × (1 − target) ✓\nasserts penny equality"]

        QUOTE["buildQuote() — quote.ts\n─────────────────────\nExcelJS workbook\nlive formulas (not baked numbers)\nF28 proposed markup rate formula\nD39 / F39 total formula\nbranded header · card mix table\npreparedBy · email"]

        XLSX[("📊 IC+ Quote .xlsx\nverified to the penny")]
    end

    subgraph SCHEMA["schema.ts — Zod v4 Schemas"]
        S1["ValueFact\nid · label · amount · page · source_text"]
        S2["Identity\nname · addends[] · equals · tolerance"]
        S3["RawStatementData\nprocessor · merchant · volume · fees{}\nvalues[] · identities[] · confidence"]
        S4["QuoteSettings\ntargetSavings · preparedBy · email"]
        S5["NormalizedStatement\nfees: interchange / net_assess\nprocessor_markup / account_other\ntotal · passthrough"]
    end

    subgraph SKILLS["Processor Knowledge (Skills)"]
        SK1["msa-processor-knowledge\nprocessor ID table\npricing model detection\nIC+ markup detection\nL2/L3 optimization"]
        SK2["fiserv-statement\npage layout · R1-R11 checks\nrisk flags · ground truth"]
        SK3["paynuity-statement\ntwo-bucket structure\nR1-R7 · direct-deduct quirk"]
    end

    CLI["cli.ts\nmsa-analyze &lt;pdf&gt;\n--out --target\n--prepared-by --email"]

    PDF --> CLI
    CLI --> EXTRACT
    SKILLS -. "loaded into\nextraction prompt" .-> EXTRACT

    EXTRACT --> RAW
    RAW --> RECON
    RECON --> CHECK

    CHECK -- "✅ PASS" --> NORM
    CHECK -- "❌ FAIL" --> FEEDBACK
    FEEDBACK --> RETRY
    RETRY -- "yes, retry" --> EXTRACT
    RETRY -- "no, give up" --> ESCALATE

    NORM --> VERIFY
    VERIFY --> QUOTE
    QUOTE --> XLSX

    SCHEMA -. "type contracts" .-> EXTRACT
    SCHEMA -. "type contracts" .-> RECON
    SCHEMA -. "type contracts" .-> NORM
    SCHEMA -. "type contracts" .-> QUOTE

    style ESCALATE fill:#ff6b6b,color:#fff
    style XLSX fill:#51cf66,color:#fff
    style CHECK fill:#ffd43b,color:#000
    style RETRY fill:#ffd43b,color:#000
    style PIPELINE fill:#1c1c2e,color:#ccc,stroke:#555
    style OUTPUT fill:#0d1f2d,color:#ccc,stroke:#555
    style SCHEMA fill:#1a1a2e,color:#ccc,stroke:#555
    style SKILLS fill:#1e1b2e,color:#ccc,stroke:#555
```

## Key design principles

| Layer | Who decides | Who executes |
|---|---|---|
| Extraction | Vision LLM (Claude) — reads PDF visually, no regex | SDK `messages.parse()` + structured outputs |
| Reconciliation identities | LLM — authors which identities apply for this statement | `reconcile.ts` — executes arithmetic exactly |
| Self-correction | `pipeline.ts` — feeds failing checks back as feedback | LLM re-extracts with grounding context |
| Quote math | `verifyQuote()` — TS recompute, penny assertion | ExcelJS live formulas in workbook |

The model **never adds numbers in its head** for verification.  
The code **never decides which identities to check** — it only executes what the model declared.
