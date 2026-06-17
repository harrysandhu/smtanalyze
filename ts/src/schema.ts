import { z } from "zod";

/**
 * The contract the vision model must fill. Two things travel together:
 *
 *  - the normalized read (volume, transactions, four fee buckets) used to
 *    build the quote, and
 *  - the AUDIT + VERIFICATION payload: every `value` the model used, grounded
 *    to a page and the verbatim source line, plus `identities` — reconciliation
 *    relationships the MODEL authors for THIS statement's structure.
 *
 * The model decides what should tie out (adaptive across processors). It does
 * NOT do the arithmetic — code executes the identities exactly (see reconcile.ts).
 */

export const ValueFact = z.object({
  id: z.string().describe("stable snake_case id, e.g. 'visa_volume', 'printed_total_fees', 'mc_discount'"),
  label: z.string().describe("human label for this figure"),
  amount: z.number().describe("the value in dollars; credits / deductions / negatives are negative"),
  page: z.number().int().describe("1-based page this was read from"),
  source_text: z.string().describe("the verbatim line/text on the statement this value came from (for audit)"),
});
export type ValueFact = z.infer<typeof ValueFact>;

export const Identity = z.object({
  name: z.string().describe("short name, e.g. 'fee_lines_sum_to_total'"),
  addends: z.array(z.string()).describe("value ids whose signed amounts should sum"),
  equals: z.string().describe("value id the addends must equal (use the statement's PRINTED total where possible)"),
  tolerance: z.number().describe("absolute $ tolerance, typically 0.02 for rounding"),
});
export type Identity = z.infer<typeof Identity>;

export const Fees = z.object({
  interchange: z.number().describe("card-network interchange passthrough (cost), monthly $"),
  network_assessment: z.number().describe("Visa/MC/Amex brand assessments & access fees, monthly $"),
  processor_markup: z.number().describe("acquirer/ISO margin — discount rate, auth markup, monthly $"),
  account_other: z.number().describe("fixed monthly / PCI / statement / dispute fees, monthly $"),
});

export const CardMix = z.object({
  brand: z.string(),
  volume: z.number(),
});

export const RawStatementData = z.object({
  processor: z.string().describe("processor / platform name as identified, e.g. 'Fiserv (CardPointe)'"),
  merchant_name: z.string(),
  merchant_id: z.string(),
  statement_period: z.string(),
  currency: z.string().describe("ISO code, e.g. USD, CAD"),
  volume: z.number().describe("total card volume processed (gross sales submitted), in dollars"),
  transactions: z.number().int(),
  fees: Fees,
  printed_total_fees: z
    .number()
    .nullable()
    .describe("the grand-total fee figure PRINTED on the statement; null if the statement prints no grand total"),
  card_mix: z.array(CardMix).describe("per-brand volume; empty array if not shown"),
  values: z.array(ValueFact).describe("every figure used above, grounded for audit"),
  identities: z
    .array(Identity)
    .describe(
      "reconciliation identities YOU author for this statement. At minimum: fee line items sum to the printed total, and the four buckets sum to the printed total.",
    ),
  confidence: z.enum(["high", "medium", "low"]),
  notes: z.string(),
});
export type RawStatementData = z.infer<typeof RawStatementData>;

/** Quote configuration supplied by the rep. */
export interface QuoteSettings {
  targetSavings: number; // e.g. 0.15 = save the merchant 15% of total processing cost
  preparedBy: string;
  email: string;
  isoName?: string; // default "Gratify"
}

export interface NormalizedStatement {
  processor: string;
  merchant_name: string;
  merchant_id: string;
  statement_period: string;
  currency: string;
  volume: number;
  transactions: number;
  avg_ticket: number;
  fees: {
    interchange: number;
    network_assessment: number;
    processor_markup: number;
    account_other: number;
    total: number;
    passthrough: number;
  };
  rates: {
    effective: number;
    interchange: number;
    network_assessment: number;
    processor_markup: number;
  };
  card_mix: { brand: string; volume: number }[];
  confidence: "high" | "medium" | "low";
  notes: string;
}
