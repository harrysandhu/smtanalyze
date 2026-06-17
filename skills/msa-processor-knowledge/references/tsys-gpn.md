# TSYS / Global Payments Network (GPN) Statement Parsing Guide

## Identification Markers

- **"Plan Summary"** section near the top of the statement, often accompanied by a pie chart showing card brand volume distribution
- **16-digit MID** in `XXXX-XXXX-XXXX-XX` format (groups of 4-4-4-2)
- **"Merchant Services"** branding in the header
- Interchange category names use TSYS-specific conventions (see below)
- **NABU fee** (Network Access and Brand Usage) listed as a line item
- Authorization counts may split into regular auth count and a separate AXP (American Express) auth count

## Statement Structure

A typical TSYS statement has these sections in order:

1. **Header** — Merchant name, MID, statement period, DBA
2. **Plan Summary** — High-level totals: volume, transactions, discount amount, discount rate. Often includes a pie chart. The discount rate shown here is the BLENDED rate (interchange + markup combined), NOT just the processor markup.
3. **Interchange Detail / Qualification Summary** — Every interchange category with: item count, volume, interchange amount, and sometimes rate. This is the most important section for analysis.
4. **Fees Section** — Non-interchange fees: NABU, statement fee, PCI fee, settlement funding fee, monthly minimum, etc.
5. **Adjustments** — Chargebacks, retrieval requests, adjustments

## Interchange Naming Conventions

TSYS uses specific naming for interchange categories that differ from Visa/MC's official names:

### Visa
| TSYS Name | Actual Category | Typical Rate |
|-----------|----------------|-------------|
| CPS Retail | Visa CPS Retail (card-present swiped/dipped) | 1.51% + $0.10 |
| CPS Retail Key Entry | Visa CPS Retail Key-Entered | 1.80% + $0.25 |
| Merit3 | Visa Merit III / CPS e-Commerce Basic | 1.80% + $0.25 |
| VFN/VTR (various) | Visa Fixed Network / Value Transfer | Varies |
| PSL Retail | Visa Retail Preferred (rewards) | ~1.65% + $0.10 |
| Comm'l Card Not Present | Visa Commercial MOTO/e-Comm | 2.50%+ |
| Comm'l Tax Exempt L2 | Visa Commercial Level 2 Tax Exempt | Downgrade indicator |

### Mastercard
| TSYS Name | Actual Category | Notes |
|-----------|----------------|-------|
| MC Merit 3 | Mastercard Merit III | Core qualified |
| MC Commercial Data Rate I | MC Commercial with L2 data | Good qualification |
| MC Commercial No Level 2 | MC Commercial WITHOUT L2 | **DOWNGRADE** — preventable |
| MC Enhanced Key Entry | Mastercard key-entered enhanced | Higher rate tier |
| MC World | Mastercard World tier | Premium consumer |

### Debit
| TSYS Name | Category | Notes |
|-----------|---------|-------|
| Regulated Debit | Durbin-regulated debit | 0.05% + $0.21 cap |
| Non-Regulated Debit | Exempt from Durbin | Higher rates |
| Prepaid Debit | Prepaid/gift cards | Often regulated rate |
| Pin Debit | PIN-authenticated debit | Network-routed (STAR, Pulse, etc.) |

### American Express
| TSYS Name | Category | Notes |
|-----------|---------|-------|
| AXP OptBlue | Amex OptBlue program | Interchange rates vary by tier |

For Amex OptBlue, do NOT assume fixed rates. Calculate effective rate from the statement data (amount / volume). Common B2B Amex rates are in the 2.0-2.3% range, not the older 1.55%/1.95% that some analysis tools use.

## Critical Gotchas

### 1. Settlement Funding Fee (HIDDEN MARKUP)
TSYS statements often include a **"SETTLEMENT FUNDING FEE"** in the fees section. This is typically 0.10% to 0.20% of total volume. It is NOT interchange — it is additional processor markup. It does NOT appear in the Plan Summary discount rate. You MUST add it to the stated discount rate to get the true total processor cost.

**Example**: Plan Summary shows 1.50% discount rate. Fees section shows Settlement Funding Fee of 0.15% × volume. True cost = 1.65%, not 1.50%.

### 2. Plan Summary Discount Rate is Blended
The "Discount Rate" in the Plan Summary is interchange + processor markup blended together. To isolate processor markup: `Markup = Discount Rate - (Total Interchange / Total Volume)`. Don't forget to add settlement funding fee to the markup.

### 3. Assessment Separation
Card brand assessments (Visa APF, MC NABU, Discover assessment, etc.) are sometimes lumped into interchange totals and sometimes listed separately. When comparing your analysis against a manual review, check whether they separate assessments from interchange. The difference is typically $100-$200/month on a $100K merchant.

### 4. Authorization Count Split
TSYS may show regular authorization count and AXP authorization count separately. When calculating per-transaction fees, use the correct count for each card brand.

### 5. Debit Economics
On a TSYS IC+ statement, the processor markup (say 0.50% + $0.10) applies equally to credit and debit. For regulated debit at 0.05% + $0.21, the processor markup often exceeds the interchange cost itself. This is the single biggest savings lever for merchants with high debit volume — moving to a lower debit markup or flat per-transaction debit pricing.

## Parsing Strategy

1. **Start with Plan Summary** for anchor totals (volume, txn count, total fees)
2. **Parse Interchange Detail** line by line — each row has: category name, count, volume, IC amount
3. **Sum IC amounts** and compare against Plan Summary total — difference is assessments
4. **Parse Fees Section** for settlement funding fee, NABU, PCI, statement fee, monthly min
5. **Calculate processor markup**: `(Plan Summary Discount Amount + Settlement Funding Fee - IC Total - Assessment Total) / Volume`
6. **Verify**: Total fees on statement = IC + Assessments + Processor Markup + Fixed Fees

## Downgrade Identification

Any of these categories indicate preventable downgrades:
- "Commercial No Level 2" (any brand) — merchant not submitting L2 data
- "Commercial Tax Exempt" — tax amount field empty on commercial cards  
- "Standard" or "EIRF" categories — fallback rates from missing data
- "Key Entry" on a card-present merchant — should be EMV dip

Estimated annual downgrade cost = (downgraded volume) × (downgrade rate - would-have-been rate). Typical savings: 0.30-0.80% on affected volume.
