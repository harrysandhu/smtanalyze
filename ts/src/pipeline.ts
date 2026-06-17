import Anthropic from "@anthropic-ai/sdk";
import { extractStatement } from "./extract.js";
import { reconcile, buildFeedback, type ReconResult } from "./reconcile.js";
import { normalize } from "./normalize.js";
import type { NormalizedStatement, RawStatementData } from "./schema.js";

export interface AnalyzeResult {
  status: "ok" | "needs_review";
  raw: RawStatementData;
  reconciliation: ReconResult;
  normalized?: NormalizedStatement;
  attempts: number;
}

/**
 * The agentic loop, with the deterministic gate in the middle:
 *   vision-extract -> reconcile (code) -> if fail, feed the failing identities
 *   back and re-extract (<= maxRetries) -> else escalate to human review.
 *
 * A quote is only ever produced from a fully-reconciled extraction.
 */
export async function analyzeStatement(
  client: Anthropic,
  pdfBase64: string,
  { maxRetries = 2 }: { maxRetries?: number } = {},
): Promise<AnalyzeResult> {
  let raw = await extractStatement(client, pdfBase64);
  let recon = reconcile(raw);
  let attempts = 1;

  while (!recon.allPassed && attempts <= maxRetries) {
    const feedback = buildFeedback(raw, recon);
    raw = await extractStatement(client, pdfBase64, { feedback });
    recon = reconcile(raw);
    attempts++;
  }

  if (!recon.allPassed) {
    return { status: "needs_review", raw, reconciliation: recon, attempts };
  }
  return {
    status: "ok",
    raw,
    reconciliation: recon,
    normalized: normalize(raw),
    attempts,
  };
}
