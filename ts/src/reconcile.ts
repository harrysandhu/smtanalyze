import type { RawStatementData } from "./schema.js";

/**
 * The zero-error gate. The model authored the identities; this code executes
 * the arithmetic — exactly, deterministically, and independently of whatever
 * the model "believes" the sums are. A misread that the model's own reasoning
 * would happily confirm cannot pass here: the numbers either add up or they
 * don't.
 *
 * The primary check is the statement's OWN printed grand total. That figure is
 * ground truth on the page, so "the four buckets sum to the printed total" is
 * a processor-agnostic check that needs no per-processor rules.
 */

export interface CheckResult {
  name: string;
  passed: boolean;
  expected: number;
  actual: number;
  diff: number;
  detail: string;
}

export interface ReconResult {
  allPassed: boolean;
  checks: CheckResult[];
}

const round2 = (n: number) => Math.round(n * 100) / 100;
const DEFAULT_TOL = 0.02;

export function reconcile(raw: RawStatementData): ReconResult {
  const byId = new Map(raw.values.map((v) => [v.id, v.amount]));
  const checks: CheckResult[] = [];

  // Primary cross-check: buckets vs the printed grand total (ground truth).
  if (raw.printed_total_fees != null) {
    const bucketSum =
      raw.fees.interchange +
      raw.fees.network_assessment +
      raw.fees.processor_markup +
      raw.fees.account_other;
    const diff = round2(bucketSum - raw.printed_total_fees);
    checks.push({
      name: "buckets_sum_to_printed_total",
      passed: Math.abs(diff) <= DEFAULT_TOL,
      expected: round2(raw.printed_total_fees),
      actual: round2(bucketSum),
      diff,
      detail: "interchange + network_assessment + processor_markup + account_other == printed grand total",
    });
  }

  // Model-authored identities, executed in code.
  for (const id of raw.identities) {
    const refs = [...id.addends, id.equals];
    const missing = refs.filter((r) => !byId.has(r));
    if (missing.length) {
      checks.push({
        name: id.name,
        passed: false,
        expected: NaN,
        actual: NaN,
        diff: NaN,
        detail: `unknown value id(s): ${missing.join(", ")}`,
      });
      continue;
    }
    const sum = id.addends.reduce((s, r) => s + (byId.get(r) as number), 0);
    const expected = byId.get(id.equals) as number;
    const diff = round2(sum - expected);
    const tol = id.tolerance ?? DEFAULT_TOL;
    checks.push({
      name: id.name,
      passed: Math.abs(diff) <= tol,
      expected: round2(expected),
      actual: round2(sum),
      diff,
      detail: `${id.addends.join(" + ")} == ${id.equals} (±${tol})`,
    });
  }

  // No checks at all is a failure: we will not ship a quote we couldn't verify.
  const allPassed = checks.length > 0 && checks.every((c) => c.passed);
  return { allPassed, checks };
}

/** Feedback for the self-correction loop: name the failing identities and the
 *  exact figures + source lines involved, so the next vision pass re-reads the
 *  right cells instead of re-reading the whole document blindly. */
export function buildFeedback(raw: RawStatementData, recon: ReconResult): string {
  const byId = new Map(raw.values.map((v) => [v.id, v]));
  const failing = recon.checks.filter((c) => !c.passed);
  const lines: string[] = [
    "Your previous extraction did not reconcile. The arithmetic below was computed by code from the values you returned — re-examine the statement image for the specific figures named and return a corrected extraction.",
    "",
    "Failing checks:",
  ];
  for (const c of failing) {
    lines.push(`- ${c.name}: expected ${c.expected}, the values you gave sum to ${c.actual} (off by ${c.diff}). ${c.detail}`);
  }
  lines.push("", "Values referenced (id | label | amount | page | source_text):");
  const involved = new Set<string>();
  for (const c of failing) {
    for (const r of raw.identities.find((i) => i.name === c.name)?.addends ?? []) involved.add(r);
    const eq = raw.identities.find((i) => i.name === c.name)?.equals;
    if (eq) involved.add(eq);
  }
  for (const id of involved) {
    const v = byId.get(id);
    if (v) lines.push(`  ${v.id} | ${v.label} | ${v.amount} | p${v.page} | "${v.source_text}"`);
  }
  lines.push(
    "",
    "Most likely causes: a digit misread (e.g. $1,044.55 read as $1.044), a line included that should be excluded (rebates/credits/non-card-brand rows), or a fee mapped to the wrong bucket. Prefer the statement's own printed grand total as the right-hand side of your identities.",
    "",
    "Here is your previous extraction to amend:",
    JSON.stringify(raw),
  );
  return lines.join("\n");
}
