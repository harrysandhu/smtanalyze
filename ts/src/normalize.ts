import type { NormalizedStatement, RawStatementData } from "./schema.js";

/**
 * RawStatementData -> NormalizedStatement. The vision model already produced
 * the four universal fee buckets, so this is just derived totals and rates,
 * kept at full precision so rate x volume reproduces the dollar figure.
 */
export function normalize(raw: RawStatementData): NormalizedStatement {
  const { interchange, network_assessment, processor_markup, account_other } = raw.fees;
  const total = interchange + network_assessment + processor_markup + account_other;
  const passthrough = interchange + network_assessment;
  const volume = raw.volume;
  const txns = raw.transactions;

  return {
    processor: raw.processor,
    merchant_name: raw.merchant_name,
    merchant_id: raw.merchant_id,
    statement_period: raw.statement_period,
    currency: raw.currency,
    volume,
    transactions: txns,
    avg_ticket: txns ? volume / txns : 0,
    fees: {
      interchange,
      network_assessment,
      processor_markup,
      account_other,
      total,
      passthrough,
    },
    rates: {
      effective: volume ? total / volume : 0,
      interchange: volume ? interchange / volume : 0,
      network_assessment: volume ? network_assessment / volume : 0,
      processor_markup: volume ? processor_markup / volume : 0,
    },
    card_mix: raw.card_mix,
    confidence: raw.confidence,
    notes: raw.notes,
  };
}
