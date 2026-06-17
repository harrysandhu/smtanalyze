/**
 * Deterministic-path smoke test (no API key needed). Feeds a hand-built
 * extraction that mirrors the Sandhill Crane statement, then exercises
 * reconcile -> normalize -> verifyQuote -> buildQuote and asserts the numbers
 * match the Python proof-of-concept to the penny.
 */
import assert from "node:assert";
import { reconcile } from "../src/reconcile.js";
import { normalize } from "../src/normalize.js";
import { buildQuote, verifyQuote } from "../src/quote.js";
import type { RawStatementData, QuoteSettings } from "../src/schema.js";

const raw: RawStatementData = {
  processor: "Fiserv (CardPointe)",
  merchant_name: "CITY OF PBG SANDHILL 2",
  merchant_id: "496372494880",
  statement_period: "01/01/26 - 01/31/26",
  currency: "USD",
  volume: 446986.19,
  transactions: 3447,
  fees: { interchange: 7568.92, network_assessment: 757.83, processor_markup: 4040.87, account_other: 286.72 },
  printed_total_fees: 12654.34,
  card_mix: [
    { brand: "Mastercard", volume: 110423.31 },
    { brand: "VISA", volume: 212783.84 },
    { brand: "Discover", volume: 6040.37 },
    { brand: "AMEX ACQ", volume: 117738.67 },
  ],
  values: [
    { id: "interchange", label: "Total Interchange", amount: 7568.92, page: 5, source_text: "Total Interchange Charges/Program Fees -$7,568.92" },
    { id: "network_assessment", label: "Assessments/Network", amount: 757.83, page: 5, source_text: "assessment + network access lines" },
    { id: "processor_markup", label: "Service Charges", amount: 4040.87, page: 5, source_text: "Total Service Charges -$4,040.87" },
    { id: "account_other", label: "Account Fees", amount: 286.72, page: 6, source_text: "TOTAL ACCOUNT FEES -$286.72" },
    { id: "printed_total", label: "Grand Total Fees", amount: 12654.34, page: 1, source_text: "Fees -$12,654.34" },
  ],
  identities: [
    { name: "buckets_equal_printed_total", addends: ["interchange", "network_assessment", "processor_markup", "account_other"], equals: "printed_total", tolerance: 0.02 },
  ],
  confidence: "high",
  notes: "Government merchant, low chargebacks.",
};

const settings: QuoteSettings = { targetSavings: 0.15, preparedBy: "Harry Sandhu", email: "hrrsandhu6@gmail.com" };

const recon = reconcile(raw);
console.log("reconcile:", recon.allPassed ? "PASS" : "FAIL", `(${recon.checks.filter((c) => c.passed).length}/${recon.checks.length})`);
assert(recon.allPassed, "reconciliation should pass");

const n = normalize(raw);
assert(Math.round(n.fees.total * 100) / 100 === 12654.34, `total ${n.fees.total}`);

const v = verifyQuote(n, settings);
console.log(`verify: current $${v.current.toFixed(2)}  proposed $${v.proposed.toFixed(2)}  save $${v.monthlySavings.toFixed(2)}/mo`);
assert(v.current === 12654.34, `current ${v.current}`);
assert(v.proposed === 10756.19, `proposed ${v.proposed}`);

await buildQuote(n, "/tmp/ts-sandhill.xlsx", settings);
console.log("wrote /tmp/ts-sandhill.xlsx");
console.log("ALL ASSERTIONS PASSED");
