import Anthropic from "@anthropic-ai/sdk";
import { zodOutputFormat } from "@anthropic-ai/sdk/helpers/zod";
import { RawStatementData } from "./schema.js";
import { EXTRACTION_MODEL } from "./models.js";

const SYSTEM = `You are a meticulous merchant card-processing statement analyst. You read the
statement as a visual document (layout, columns, totals — not just loose text) and extract
everything needed to build an Interchange-Plus quote.

Map every fee into exactly one of four buckets (monthly dollars):
- interchange: card-network interchange passthrough (the cost, not margin)
- network_assessment: Visa/MC/Amex brand assessments, network access / auth fees
- processor_markup: the acquirer/ISO margin — discount rate, sales discount, auth markup
- account_other: fixed monthly fees, PCI, statement fee, dispute/chargeback fees

Record EVERY figure you use in "values", each with the page and the verbatim source line, so
it can be audited later.

CRITICAL — do not verify by doing arithmetic in your head. You will get sums subtly wrong and
you will not notice. Instead, AUTHOR reconciliation "identities" that downstream code executes
exactly. Always include:
  1) an identity that the individual fee line items sum to the printed grand total, and
  2) an identity that the four buckets sum to the printed grand total.
Use the statement's OWN printed totals as the right-hand side ("equals") wherever they exist —
that is ground truth on the page. Exclude rebate/credit/non-card-brand rows from sums where the
statement does. If the statement prints no grand total, set printed_total_fees to null and lower
your confidence.

Exhaustiveness matters: a missing fee line is the most common reason an identity fails to close.`;

export interface ExtractOpts {
  /** Correction feedback from a failed reconciliation (drives the self-correction loop). */
  feedback?: string;
}

/**
 * One vision-extraction pass. Returns schema-valid RawStatementData or throws
 * (e.g. on a refusal / max_tokens that left no parseable output).
 */
export async function extractStatement(
  client: Anthropic,
  pdfBase64: string,
  opts: ExtractOpts = {},
): Promise<RawStatementData> {
  const instruction =
    opts.feedback ?? "Extract this merchant statement into the required schema.";

  // The PDF is large and identical across retries — cache it so the
  // self-correction loop only pays for the (small) feedback turn.
  const content = [
    {
      type: "document",
      source: { type: "base64", media_type: "application/pdf", data: pdfBase64 },
      cache_control: { type: "ephemeral" },
    },
    { type: "text", text: instruction },
  ];

  const res = await client.messages.parse({
    model: EXTRACTION_MODEL,
    max_tokens: 16000,
    system: SYSTEM,
    thinking: { type: "adaptive" },
    output_config: { effort: "high", format: zodOutputFormat(RawStatementData) },
    messages: [{ role: "user", content }] as Anthropic.MessageParam[],
  });

  if (!res.parsed_output) {
    throw new Error(
      `extraction produced no structured output (stop_reason=${res.stop_reason}` +
        (res.stop_reason === "refusal" ? `, category=${res.stop_details?.category}` : "") +
        ")",
    );
  }
  return res.parsed_output;
}
