---
name: paynuity-statement
description: >
  Extracts structured data from Paynuity merchant statement PDFs. Use this skill whenever analyzing,
  parsing, or extracting fees, volumes, or rates from a Paynuity processor statement. Triggers on any
  mention of Paynuity, NABC, or merchant statements with "Discount Due" / "Fees Due" two-bucket fee
  structures. Also use when the user uploads a PDF that contains "MERCHANT STATEMENT" with Paynuity
  branding (111 N. Orange Ave, Orlando). Covers: payment summary extraction, card brand volume breakdowns,
  interchange/transaction/card brand/other fee categorization, settlement reconciliation, effective rate
  computation, chargeback analysis, reserve tracking, and risk flag detection. Includes a pdfplumber-based
  parse script (scripts/parse_paynuity.py) with --json and --validate modes. Tested against 47 statements
  with 703/703 reconciliation checks passing.
---

# Paynuity Statement Extraction Skill

**Processor:** Paynuity (white-label of NABC North American Banking Company)
**Branding:** "111 N. Orange Ave, Suite 1800, Orlando, FL 32801"
**Tested against:** 47 statements (3 merchant groups, 2–10 pages, Apr–Aug 2025)

---

## 1. Statement Identification

A PDF is a Paynuity statement if page 1 contains ALL of:
- `MERCHANT STATEMENT` (title)
- `paynuity` (case-insensitive, in footer copyright)
- `DiscountDue` or `Discount Due`
- `PLAN SUMMARY`

## 2. Page Layout

### Page 1 — Header + Payment Summary + Plan Summary

```
111N.OrangeAve.
Suite1800                        MERCHANT STATEMENT
Orlando,FL32801
                                 for<Month> <Day>,<Year>
                                 Page1 of<N>

<MERCHANT_NAME>                  MerchantNumber <MERCHANT_NUMBER>
<ADDRESS_LINE_1>
                                 AssociationNumber <ASSOC_NUMBER>
<CITY_STATE_ZIP>
                                 RoutingNumber xxxxx<LAST4>
                                 DepositAccountNumber xxxxx<LAST4>

PAYMENT SUMMARY
DiscountDue          $<DISCOUNT_DUE>
                                 If you have any questionsaboutthisstatement
FeesDue              $<FEES_DUE>  or yourprocessing relationship please
                                 contact Customer Supportat +1 878.888.0877
Totalamounttobededucted  $<TOTAL_DEDUCTED>
fromyouraccount

PLAN SUMMARY
                SALES          CREDITS        NETSALES   DISCOUNTS
           Number  Amount   Number  Amount
<CardBrand>  <N>  $<AMT>    <N>   $<AMT>     $<AMT>     $<AMT>
...
TOTALS       <N>  $<AMT>    <N>   $<AMT>     $<AMT>     $<AMT>

<CardBrand> <PCT>%
...
```

**Gotchas:**
- Text extraction runs words together (no spaces): `DiscountDue`, `FeesDue`, `Totalamounttobededucted`
- Card brand names have no spaces: `VisaDebit`, `MasterCardBusiness`, etc.
- The TOTALS row Discounts value MUST equal the Payment Summary DiscountDue
- Pie chart percentages appear as loose text after the table — ignore for extraction
- Plan Summary can have 0 card brands (zero-activity statements) — only TOTALS row present

### Pages 2+ — Deposits (optional)

```
DEPOSITS
DAY  REFERENCE    TRAN  PLAN  NUMBEROF  AMOUNTOF  AMOUNTOF  FEES       NETDEPOSIT
     NUMBER       CODE  CODE  SALES     SALES     CREDITS   PAID

<DD> <REF>        D     T     <N>       <AMT>     <AMT>     <AMT>      <AMT>
...
DEPOSITTOTALS                  <N>       <AMT>     <AMT>     <AMT>      <AMT>
```

**Key fields:** DEPOSIT TOTALS row gives aggregate: total sales count, total sales amount, total credits amount, total fees paid, total net deposit.

### Pages 2+ — Chargebacks (optional, can span many pages)

```
CHARGEBACKS
DAY  REFERENCE    TRAN  PLAN  NUMBEROF  AMOUNTOF  AMOUNTOF  FEES       NETDEPOSIT
     NUMBER       CODE  CODE  SALES     SALES     CREDITS   PAID

<DD> <REF>        C     T     01        <AMT>     0.00      0.00       <AMT>
...
CHARGEBACKTOTALS               <N>       <AMT>     <AMT>     <AMT>      <AMT>
```

**Transaction codes in chargebacks:**
- `C` = Chargeback
- `B` = Chargeback Reversal (representment won)

**Gotcha:** Chargebacks section can span 5+ pages on high-volume/high-dispute accounts. The `CHARGEBACKS -continued` header appears on continuation pages. Always scan ALL pages for the `CHARGEBACKTOTALS` line.

### Pages 2+ — Reserve Funding Summary (optional)

```
RESERVE FUNDING - SUMMARY
              AMOUNTOF    AMOUNTOF    RESERVE
              RESERVE     RELEASE     BALANCE
TOTALS        <AMT>       <AMT>       <AMT>
```

Present when the merchant has a rolling reserve. Extract all three values.

### Fee Pages — Fee Detail

```
FEES
COUNT    AMOUNT        DESCRIPTION                    TOTAL

<CATEGORY_HEADER>
<COUNT>  <VOLUME>      <FEE_NAME>                     <FEE_AMOUNT>
...
TOTAL<CATEGORY>FEES                                    <SUBTOTAL>

...

TOTALFEES                                              <GRAND_TOTAL>
```

**Fee categories (dynamic — not all present in every statement):**

| Category | Header Text | Subtotal Line | MSA v2 Bucket |
|----------|-------------|---------------|---------------|
| Interchange | `INTERCHANGE` | `TOTALINTERCHANGEFEES` | `interchange` |
| Authorization | `AUTHORIZATION` | `TOTALAUTHORIZATIONFEES` | `processor_markup` |
| Transaction | `TRANSACTION` | `TOTALTRANSACTIONFEES` | `processor_markup` |
| Card Brand | `CARDBRAND` | `TOTALCARDBRANDFEES` | `network_assessment` |
| Other | `OTHER` | `TOTALOTHERFEES` | `account_other` |

**Gotcha — fee line format is inconsistent:**
- Some lines have COUNT + AMOUNT + DESCRIPTION + TOTAL: `40  6,569.60  VSCPSeCommBasicDB  114.39`
- Some lines have only DESCRIPTION + TOTAL (no count/amount): `VSNAPFDomesticCRAuthorization  7.90`
- Some lines have AMOUNT + DESCRIPTION + TOTAL (no count): `719.97  VSUSAccountNameInquiry  .30`
- The TOTAL column (rightmost number) is always the fee charged
- The AMOUNT column (when present) is the volume the fee was assessed against

**Gotcha — fees span multiple pages:** Look for `FEES -continued` header on subsequent pages. Keep parsing until `TOTALFEES` is found.

### Last Page — Settlement Reconciliation

```
MinimumDiscountDue    <AMT>
DiscountPaid          <AMT>
NetDiscountDue        <AMT>

FeesDue               <AMT>
FeesPaid              <AMT>
NetFeesDue            <AMT>

AmountDeducted        <AMT>
```

This section always appears on the final page, before the PLAN CODES / TRANSACTION CODES legend.

---

## 3. Extraction Fields

### Header Fields
| Field | Source | Example |
|-------|--------|---------|
| `merchant_name` | Line above Merchant Number | `CHALLENGER WORLDWIDE LLC` |
| `merchant_number` | After "MerchantNumber" | `745300000111294` |
| `association_number` | After "AssociationNumber" | `777101` |
| `statement_date` | After "for" in header | `April 30, 2025` |
| `page_count` | "Page1 of<N>" | `3` |

### Payment Summary
| Field | Source | Example |
|-------|--------|---------|
| `discount_due` | After "DiscountDue" | `2524.59` |
| `fees_due` | After "FeesDue" | `1428.79` |
| `total_deducted` | After "Totalamounttobededucted" | `0.00` |

### Plan Summary (per card brand)
| Field | Source |
|-------|--------|
| `card_brand` | Row label (Visa, VisaDebit, MasterCard, etc.) |
| `sales_count` | Number column under SALES |
| `sales_amount` | Amount column under SALES |
| `credits_count` | Number column under CREDITS |
| `credits_amount` | Amount column under CREDITS |
| `net_sales` | NETSALES column |
| `discounts` | DISCOUNTS column |

Plus TOTALS row with all aggregate values.

### Deposits Summary
| Field | Source |
|-------|--------|
| `deposit_count` | DEPOSITTOTALS sales count |
| `deposit_sales` | DEPOSITTOTALS sales amount |
| `deposit_credits` | DEPOSITTOTALS credits amount |
| `deposit_fees_paid` | DEPOSITTOTALS fees paid |
| `deposit_net` | DEPOSITTOTALS net deposit |

### Chargebacks Summary
| Field | Source |
|-------|--------|
| `chargeback_count` | CHARGEBACKTOTALS count |
| `chargeback_amount` | CHARGEBACKTOTALS sales amount |
| `chargeback_reversals` | Count of rows with TRAN CODE = B |

### Reserve Funding
| Field | Source |
|-------|--------|
| `reserve_amount` | RESERVE column |
| `reserve_release` | RELEASE column |
| `reserve_balance` | BALANCE column |

### Fee Breakdown
| Field | Source |
|-------|--------|
| `interchange_fees` | TOTALINTERCHANGEFEES |
| `authorization_fees` | TOTALAUTHORIZATIONFEES |
| `transaction_fees` | TOTALTRANSACTIONFEES |
| `card_brand_fees` | TOTALCARDBRANDFEES |
| `other_fees` | TOTALOTHERFEES |
| `total_fees` | TOTALFEES |
| `fee_line_items[]` | Array of {category, count, volume, description, amount} |

### Settlement
| Field | Source |
|-------|--------|
| `min_discount_due` | MinimumDiscountDue |
| `discount_paid` | DiscountPaid |
| `net_discount_due` | NetDiscountDue |
| `fees_due_settlement` | FeesDue |
| `fees_paid` | FeesPaid |
| `net_fees_due` | NetFeesDue |
| `amount_deducted` | AmountDeducted |

---

## 4. Reconciliation Formulas

These MUST all pass for a valid extraction:

### R1: Discount Due = Sum of Plan Summary Discounts
```
discount_due == sum(card_brand.discounts for all brands)
```

### R2: Plan Summary Net Sales = Sales - Credits
```
for each card brand:
  net_sales == sales_amount - credits_amount
```

### R3: Plan Summary TOTALS = Sum of all brands
```
totals.sales_count == sum(brand.sales_count)
totals.sales_amount == sum(brand.sales_amount)
# ... same for credits, net_sales, discounts
```

### R4: Total Fees = Sum of Fee Category Subtotals
```
total_fees == interchange_fees + authorization_fees + transaction_fees + card_brand_fees + other_fees
```
(Only include categories that are present)

### R5: Fees Due = Total Fees
```
fees_due == total_fees
```

### R6: Settlement Math
```
net_discount_due == min_discount_due - discount_paid  (within ±$0.02 rounding)
net_fees_due == fees_due_settlement - fees_paid        (within ±$0.02 rounding)
amount_deducted ≈ net_discount_due + net_fees_due      (within ±$0.02 rounding)
```

**Paynuity Quirk — Direct-Deduct Pattern:**
When `FeesPaid = $0.00`, Paynuity sets `NetFeesDue = $0.00` (regardless of FeesDue) and collects everything via AmountDeducted. In this case, the correct reconciliation is:
```
AmountDeducted == NetDiscountDue + FeesDue  (NOT NetFeesDue)
```
This pattern is common on accounts where fees were not deducted from daily deposits.

**Paynuity Quirk — Minimum Discount Fee:**
Zero-activity accounts (no sales, no card brands in Plan Summary) can still have `DiscountDue > $0` as a minimum fee. In this case R1 will show DiscountDue != Plan Summary discounts ($0). This is expected — flag as `minimum_discount_fee` rather than a parsing error.

### R7: Deposit Totals Cross-Check
```
deposit_sales == plan_summary_totals.sales_amount
deposit_count == plan_summary_totals.sales_count
```

---

## 5. Effective Rate Computation

### Gross Effective Rate (what the merchant pays on total volume)
```
gross_rate = (discount_due + fees_due) / plan_summary_totals.sales_amount * 100
```

### Net Effective Rate (what the merchant pays on net sales)
```
net_rate = (discount_due + fees_due) / plan_summary_totals.net_sales * 100
```

**CRITICAL — Two-Bucket Bug:**
The total processing cost is `discount_due + fees_due`, NOT just `discount_due`. The handoff doc documented a bug where effective rate showed 3.94% instead of 7.88% because `fees_due` was being ignored. Always sum both buckets.

### Per-Brand Effective Rate
```
brand_rate = brand.discounts / brand.net_sales * 100
```
Note: This only captures the Discount Due portion. Card brand fees and interchange are not broken out per-brand on this statement format.

---

## 6. MSA v2 Fee Taxonomy Mapping

| Paynuity Category | MSA v2 Bucket | Notes |
|-------------------|---------------|-------|
| INTERCHANGE | `interchange` | Passthrough interchange fees |
| AUTHORIZATION | `processor_markup` | Per-auth fees charged by processor |
| TRANSACTION | `processor_markup` | Batch fees, chargeback fees |
| CARD BRAND | `network_assessment` | Visa/MC network assessments, digital enablement, NAPF, etc. |
| OTHER | `account_other` | Misc charges, PCI fees, statement fees, etc. |
| Plan Summary DISCOUNTS | `processor_markup` | The "Discount Due" bucket = processor's bundled rate markup |

---

## 7. Risk Flags

| Flag | Condition | Severity |
|------|-----------|----------|
| `high_effective_rate` | gross_rate > 5.0% | Warning |
| `excessive_chargebacks` | chargeback_count / sales_count > 1.0% | Critical |
| `chargeback_dollar_ratio` | chargeback_amount / sales_amount > 1.5% | Critical |
| `reserve_held` | reserve_balance > 0 | Info |
| `reserve_growing` | reserve_amount > reserve_release | Warning |
| `settlement_discrepancy` | amount_deducted != expected (±$1.00) | Warning |
| `zero_activity_fees` | sales_amount == 0 AND total_fees > 0 | Info |
| `misc_charges_present` | other_fees > 0 | Review |
| `high_credit_ratio` | credits_amount / sales_amount > 10% | Warning |

---

## 8. Test Results

**47/47 statements parsed, 703/703 reconciliation checks passed (100%)**

Tested across 3 merchant groups (Challenger Worldwide, Vita Fushion, Health Suite), page counts from 2–10, dates Apr–Aug 2025, volumes from $0 to $584K. Covers edge cases: zero-activity accounts, minimum fees, 181-chargeback months, 6-brand Plan Summaries, negative net sales, bare-decimal amounts, reserve funding, and the direct-deduct settlement pattern.

## 9. Ground Truth Reference

### Statement 1: HOME BASE DEPOT (2 pages, zero activity)
- Merchant: HEALTH SUITE INC, MID 745300000438036
- Date: August 31, 2025
- Sales: $0.00 (0 txns), Credits: $0.00
- Discount Due: $0.00, Fees Due: $0.36, Total Deducted: $0.36
- Fee breakdown: Authorization $0.30 + Card Brand $0.06 = $0.36
- Risk flags: zero_activity_fees

### Statement 2: CHALLENGER WORLDWIDE April (3 pages, typical)
- Merchant: CHALLENGER WORLDWIDE LLC, MID 745300000111294
- Date: April 30, 2025
- Sales: $79,292.64 (486 txns), Credits: $2,504.37 (35)
- Net Sales: $76,788.27
- Discount Due: $2,524.59, Fees Due: $1,428.79, Total Deducted: $0.00
- Fee breakdown: Interchange $1,256.57 + Transaction $2.00 + Card Brand $170.22 = $1,428.79
- Gross effective rate: (2,524.59 + 1,428.79) / 79,292.64 = 4.99%
- Reserve: $72,855.04 held, $0 released
- 5 card brands, Visa Debit dominant at 34%

### Statement 3: CHALLENGER WORLDWIDE May (10 pages, heavy volume + chargebacks)
- Merchant: CHALLENGER WORLDWIDE LLC, MID 745300000111294
- Date: May 30, 2025
- Sales: $584,485.19 (18,511 txns), Credits: $115,924.92 (982)
- Net Sales: $468,560.27
- Discount Due: $23,087.86, Fees Due: $18,403.54, Total Deducted: $249.78
- Fee breakdown: Interchange $13,480.66 + Transaction $2,821.00 + Card Brand $1,851.88 + Other $250.00 = $18,403.54
- Gross effective rate: (23,087.86 + 18,403.54) / 584,485.19 = 7.10%
- Chargebacks: 181 totaling $29,758.27 (chargeback ratio: 5.09% — CRITICAL)
- Reserve: $242,466.82 in, $265,858.49 released, balance $49,463.37
- 6 card brands (includes MasterCard Business), Visa Debit dominant at 34%
- Transaction fees include $2,790 in chargeback fees (186 × $15)
