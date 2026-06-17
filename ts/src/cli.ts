#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import path from "node:path";
import Anthropic from "@anthropic-ai/sdk";
import { analyzeStatement } from "./pipeline.js";
import { buildQuote, verifyQuote } from "./quote.js";
import type { QuoteSettings } from "./schema.js";

/**
 * Usage:
 *   msa-analyze <statement.pdf> [--out quote.xlsx] [--target 0.15]
 *                               [--prepared-by "Name"] [--email a@b.com]
 *
 * Requires ANTHROPIC_API_KEY in the environment.
 */
function parseArgs(argv: string[]) {
  const pos: string[] = [];
  const flags: Record<string, string> = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) flags[a.slice(2)] = argv[++i];
    else pos.push(a);
  }
  return { pos, flags };
}

async function main() {
  const { pos, flags } = parseArgs(process.argv.slice(2));
  const pdfPath = pos[0];
  if (!pdfPath) {
    console.error("usage: msa-analyze <statement.pdf> [--out quote.xlsx] [--target 0.15] [--prepared-by NAME] [--email EMAIL]");
    process.exit(2);
  }
  const out = flags.out ?? path.join("output", path.basename(pdfPath).replace(/\.pdf$/i, "") + " - Quote.xlsx");
  const settings: QuoteSettings = {
    targetSavings: flags.target ? Number(flags.target) : 0.15,
    preparedBy: flags["prepared-by"] ?? "Gratify Sales",
    email: flags.email ?? "sales@gratifypay.com",
    isoName: flags.iso ?? "Gratify",
  };

  const pdfBase64 = (await readFile(pdfPath)).toString("base64");
  const client = new Anthropic(); // reads ANTHROPIC_API_KEY

  console.log(`[1/4] Vision extraction + reconciliation loop: ${path.basename(pdfPath)}`);
  const result = await analyzeStatement(client, pdfBase64, { maxRetries: 2 });

  const passed = result.reconciliation.checks.filter((c) => c.passed).length;
  console.log(`[2/4] Reconciliation: ${passed}/${result.reconciliation.checks.length} checks passed after ${result.attempts} extraction pass(es)`);

  if (result.status !== "ok" || !result.normalized) {
    console.error("[x] Statement did not reconcile — routing to human review, no quote produced.");
    for (const c of result.reconciliation.checks.filter((c) => !c.passed)) {
      console.error(`    FAIL ${c.name}: expected ${c.expected}, got ${c.actual} (off ${c.diff}) — ${c.detail}`);
    }
    process.exit(1);
  }

  const n = result.normalized;
  console.log(`[3/4] ${n.merchant_name}  vol=$${n.volume.toLocaleString()}  eff=${(n.rates.effective * 100).toFixed(2)}%  markup=$${n.fees.processor_markup.toFixed(2)}`);

  const v = verifyQuote(n, settings);
  await buildQuote(n, out, settings);
  console.log(`[4/4] Quote -> ${out}`);
  console.log(`      VERIFIED penny-exact. Current $${v.current.toFixed(2)} -> Proposed $${v.proposed.toFixed(2)} (save $${v.monthlySavings.toFixed(2)}/mo at ${(settings.targetSavings * 100).toFixed(0)}% target)`);
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
