---
name: fiserv-statement
description: >
  Extracts structured data from Fiserv merchant statement PDFs. Use this skill whenever analyzing,
  parsing, or extracting fees, volumes, or rates from a Fiserv/CardPointe/Newtek-branded card
  processing statement. Triggers on any mention of Fiserv, CardPointe, Newtek, or statements with
  "YOUR CARD PROCESSING STATEMENT" / "Total Amount Submitted" / "THIS IS NOT A BILL" structure.
  Covers: summary extraction, card type volume breakdowns, batch summaries, chargeback/reversal
  detail, adjustment detail, three-way fee breakdown (interchange + service charges + fees),
  transaction fee and account fee parsing, interchange charges/program fees detail, effective rate
  computation, and risk flag detection. Includes a pdfplumber-based parse script
  (scripts/parse_fiserv.py) with --json and --validate modes.
---

# Fiserv Statement Extraction Skill

**Processor:** Fiserv (white-labeled as Newtek Payments and CardPointe)
**Branding variants:**
- Newtek: "1981 Marcus Ave, Suite 130 Lake Success, NY 11042" / newtekone.com/payments
- CardPointe: "3975 NW 120th Avenue, Coral Springs, FL 33065" / cardpointe.com
**Tested against:** 17 statements (5 merchant groups, 2-10 pages, Jan-May 2025/2026)

---

## 1. Statement Identification

A PDF is a Fiserv statement if page 1 contains ALL of:
- `YOUR CARD PROCESSING STATEMENT` (title)
- `Total Amount Submitted` (in SUMMARY section)
- `THIS IS NOT A BILL`
- `SUMMARY BY DAY` (on page 1 or page 2 if IMPORTANT INFORMATION notice present)

Sub-brands share identical layout — one parser handles both Newtek and CardPointe.

## 2. Page Layout

### Page 1 — Header + Summary + Summary By Day (start)

```
<ADDRESS_LINE>
YOUR CARD PROCESSING STATEMENT
<MERCHANT_NAME>                    Page 1 of <N>  THIS IS NOT A BILL
<CONTACT_NAME>
                                   Statement Period <MM/DD/YY> - <MM/DD/YY>
<ADDRESS>
                                   Merchant Number <MERCHANT_NUMBER>
<CITY_STATE_ZIP>
                                   Customer Service Website - <URL>
                                   Phone - <PHONE>

SUMMARY  An overview of account activity for the statement period.
Page <N>  Total Amount Submitted     $<TOTAL_SUBMITTED>
Page <N>  Chargebacks/Reversals      -$<CHARGEBACKS>
Page <N>  Adjustments                -$<ADJUSTMENTS>    (or 0.00)
Page <N>  Fees                       -$<FEES>
          Total Amount Processed     $<TOTAL_PROCESSED>

[IMPORTANT INFORMATION ABOUT YOUR ACCOUNT — optional, can push Summary By Day to page 2]

SUMMARY BY DAY
Date       Submitted    Chargebacks/   Amount
           Amount       Reversals      Adjustments  Fees      Processed
<MM/DD/YY> $<AMT>       <AMT>          <AMT>        <AMT>     $<AMT>
...
```

**Gotchas:**
- Text extraction runs words together in some cases
- The "Page N" references before each summary line are page pointers, not values
- Summary lines can have negative amounts (e.g., `-$4,334.62`) or `0.00` (no dollar sign)
- IMPORTANT INFORMATION notice (optional) can push SUMMARY BY DAY to page 2
- Total Amount Processed = Total Amount Submitted + Chargebacks/Reversals + Adjustments + Fees (all signed)

### Pages 1-2 — Summary By Day (continued) + Total Row

```
...
Month End Charge    0.00    0.00    0.00    -$<FEES>    -$<FEES>
Total               $<AMT>  -$<AMT> -$<AMT> -$<AMT>    $<AMT>
```

The Total row in Summary By Day MUST match the SUMMARY section values.

### Summary By Card Type

```
SUMMARY BY CARD TYPE
                     Total Gross Sales You Submitted  Refunds    Total Amount You Submitted
              Average
Card Type     Ticket   Items  Amount    Items  Amount   Items  Amount
Mastercard    $<AVG>   <N>    $<AMT>    <N>    -$<AMT>  <N>    $<AMT>
VISA          $<AVG>   <N>    $<AMT>    <N>    -$<AMT>  <N>    $<AMT>
Discover      $<AVG>   <N>    $<AMT>    <N>    -$<AMT>  <N>    $<AMT>
AMEX ACQ      $<AVG>   <N>    $<AMT>    <N>    -$<AMT>  <N>    $<AMT>
Total                  <N>    $<AMT>    <N>    -$<AMT>  <N>    $<AMT>
```

**Key fields per card type:** avg_ticket, gross_sales_items, gross_sales_amount, refund_items, refund_amount, total_items, total_amount

**Gotchas:**
- Not all card types present on every statement (Discover + Amex only on some merchants)
- Card type names vary: `Mastercard`, `VISA`, `Discover`, `AMEX ACQ`
- Refund items/amount can be `0` / `0.00` (no dollar sign)
- Total row's total_amount MUST equal SUMMARY's Total Amount Submitted

### Summary By Batch

```
SUMMARY BY BATCH
                     Total Gross Sales You Submitted  Refunds    Total Amount You Submitted
              Average
Batch         Submit Date  Ticket  Items  Amount  Items  Amount  Items  Amount
<BATCH_ID>    <MM/DD/YY>   $<AVG>  <N>    $<AMT>  <N>    -$<AMT> <N>   $<AMT>
...
Total                              <N>    $<AMT>  <N>    -$<AMT> <N>   $<AMT>
```

### Chargebacks/Reversals (optional, can span multiple pages)

```
CHARGEBACKS/REVERSALS  Transactions that are challenged or disputed by a cardholder or card-issuing bank.
                                                               Card Number
Date       Reference No.  Description                          (Last 4 Digits)  Amount
<MM/DD/YY> <REF>          <DESCRIPTION>                        <LAST4>          -$<AMT>
...
TOTAL                                                                           -$<AMT>
```

**Transaction types in chargebacks:**
- Negative amounts = chargebacks (money taken from merchant)
- Positive amounts = "Credit issued for a dispute previously debit to your account" (reversals/representments won)

### Adjustments (optional)

```
ADJUSTMENTS  The amounts credited to, or deducted from, your account...
Date        Description                              Amount
<MM/DD/YY>  <DESCRIPTION>                            -$<AMT>
...
TOTAL                                                -$<AMT>
```

Or if no adjustments:
```
No Adjustments for this Statement Period
Total 0.00
```

### Fee Pages — Fee Detail

```
FEES  Amount charged to authorize, process and settle card transactions...

TRANSACTION FEES                    Type              Amount
<CARD_BRAND>
<FEE_NAME> [<COUNT> TRANSACTIONS AT <RATE>]  <fee_type>  -$<AMT>
<FEE_NAME> [<MULTIPLIER> TIMES $<VOLUME>]    <fee_type>  -$<AMT>
<FEE_NAME> [<VOLUME> AT <RATE>]              <fee_type>  -$<AMT>
<FEE_NAME>                                   <fee_type>  -$<AMT>
...
TOTAL TRANSACTION FEES                                   -$<AMT>

ACCOUNT FEES                        Type              Amount
<FEE_NAME> [<COUNT> TRANSACTIONS AT <RATE>]  <fee_type>  -$<AMT>
...
TOTAL ACCOUNT FEES                                       -$<AMT>

TOTAL                                                    -$<GRAND_TOTAL>

Total Interchange Charges/Program Fees                   -$<AMT>
Total Service Charges                                    -$<AMT>
Total Fees                                               -$<AMT>
Total (Service Charges, Interchange Charges/Program Fees, and Fees)  -$<GRAND_TOTAL>
```

**Fee type labels (appear in the "Type" column):**
- `Interchange charges` — passthrough interchange costs
- `Service charges` — processor markup (discount rates, auth fees, connectivity fees)
- `Fees` — network fees, account fees, dispute fees, compliance fees
- `Program Fees` — Amex program fees (equivalent to interchange for Amex)

**CRITICAL — "Total Fees" Trap:**
The line `Total Fees -$<AMT>` near the bottom is ONLY the sum of fee lines labeled as type "Fees" — it is NOT the grand total. The actual grand total is:
```
Total (Service Charges, Interchange Charges/Program Fees, and Fees)  -$<GRAND_TOTAL>
```
Or equivalently, the `TOTAL` line appearing after `TOTAL ACCOUNT FEES`.

**Fee line format variants:**
- With count: `MC NETWORK ACCESS AUTH FEE 872 TRANSACTIONS AT 0.0195 Fees -$17.00`
- With disc rate: `MASTERCARD SALES DISCOUNT 0.0085 DISC RATE TIMES $99468.27 Service charges -$845.48`
- With volume rate: `VI DIGITAL COMMERCE SVCS FEE $17,132.33 AT .000075 Fees -$1.28`
- With multiplier: `VISA ASSESSMENT FEE CR 0.0014 TIMES $161687.99 Interchange charges -$226.36`
- Fixed (no count/rate): `MONTHLY STATEMENT FEE Fees -$10.00`
- With 0 count: `VS INTL ACQUIRER FEE 0 TRANS TOTALING $4656.15 Fees -$20.95`

**Fee categories by card brand in TRANSACTION FEES:**
Fee lines under TRANSACTION FEES are grouped by card brand headers:
- `MASTERCARD` — MC interchange, assessments, network fees
- `VISA` — Visa interchange, assessments, network fees
- `DISCOVER` — Discover interchange, assessments
- `AMERICAN EXPRESS` — Amex auth fees (non-ACQ)
- `AMEX ACQ` — Amex program fees (acquirer pricing)
- `Other` — Cross-brand fees (batch settlement, AVS, discount rates, connectivity)

**Gotchas:**
- Fees section can span 3+ pages — look for `FEES` header continuation
- Card brand subsections within TRANSACTION FEES don't have explicit subtotals per brand
- The "Other" section often contains the main processor markup (e.g., `NON SWIPED DISCOUNT`)
- ACCOUNT FEES section follows TRANSACTION FEES and contains fixed monthly/compliance fees
- Three-way breakdown at the bottom sums to TOTAL (the grand total)

### Last Pages — Interchange Charges/Program Fees Detail

```
INTERCHANGE CHARGES/PROGRAM FEES
These are the variable fees charged by Card Organizations for processing transactions.

                        Interchange/Program                    Total
Sales    % Of   Number of  % of Total  Cost Per  Interchange/Program
Product/Description   Total Sales  Transactions  Transactions  Rate  Transaction  Sub Total  Charges

<CARD_BRAND>
<PRODUCT_NAME>  $<SALES>  <PCT>%  <N>  <PCT>%  <RATE>  $<PER_TXN>  -$<CHARGES>
...
<CARD_BRAND> TOTAL  $<BRAND_TOTAL_SALES>  <N>  -$<BRAND_TOTAL_CHARGES>

...
TOTAL  $<GRAND_TOTAL_SALES>  <N>  -$<GRAND_TOTAL_CHARGES>
```

**Card brand sections:** MASTERCARD, VISA, DISCOVER, AMEX ACQ
**Key fields per product:** sales_amount, pct_of_sales, txn_count, pct_of_txns, rate, per_txn_cost, charges

**Gotchas:**
- Return/refund products have $0.00 charges and rate 0.0000
- Brand TOTAL row format: `<BRAND> TOTAL  $<sales>  <count>  -$<charges>`
- Grand TOTAL row: `TOTAL  $<total_sales>  <total_count>  -$<total_charges>`
- The grand total sales MUST equal Summary's Total Amount Submitted
- The grand total charges here are the sum of interchange/program fees only (subset of total fees)

---

## 3. Extraction Fields

### Header Fields
| Field | Source | Example |
|-------|--------|---------|
| `merchant_name` | First line after address, before "Page" | `FITFLEXGUMMIES.COM` |
| `merchant_number` | After "Merchant Number" | `815204582887` |
| `statement_period` | After "Statement Period" | `04/01/25 - 04/30/25` |
| `page_count` | "Page 1 of <N>" | `6` |
| `branding` | Address line (Newtek vs CardPointe) | `newtek` or `cardpointe` |

### Summary
| Field | Source | Example |
|-------|--------|---------|
| `total_submitted` | "Total Amount Submitted" | `11935.56` |
| `chargebacks_reversals` | "Chargebacks/Reversals" | `-4334.62` |
| `adjustments` | "Adjustments" | `-1104.65` |
| `fees` | "Fees" (SUMMARY line) | `-1342.73` |
| `total_processed` | "Total Amount Processed" | `5153.56` |

### Summary By Card Type (per card type)
| Field | Source |
|-------|--------|
| `card_type` | Row label (Mastercard, VISA, Discover, AMEX ACQ) |
| `avg_ticket` | Average Ticket column |
| `gross_items` | Gross Sales Items |
| `gross_amount` | Gross Sales Amount |
| `refund_items` | Refunds Items |
| `refund_amount` | Refunds Amount |
| `total_items` | Total Items |
| `total_amount` | Total Amount |

Plus Total row with aggregate values.

### Summary By Day
| Field | Source |
|-------|--------|
| `daily_entries[]` | Array of {date, submitted, chargebacks, adjustments, fees, processed} |
| `month_end_charge` | "Month End Charge" row fees value |
| `daily_total` | Total row (must match SUMMARY) |

### Chargebacks Summary
| Field | Source |
|-------|--------|
| `chargeback_total` | TOTAL line in CHARGEBACKS/REVERSALS |
| `chargeback_entries[]` | Array of {date, ref_no, description, last4, amount} |
| `chargeback_count` | Count of negative-amount entries |
| `reversal_count` | Count of positive-amount entries ("Credit issued...") |

### Adjustments Summary
| Field | Source |
|-------|--------|
| `adjustment_total` | TOTAL line in ADJUSTMENTS |
| `adjustment_entries[]` | Array of {date, description, amount} |

### Fee Breakdown
| Field | Source |
|-------|--------|
| `total_transaction_fees` | TOTAL TRANSACTION FEES |
| `total_account_fees` | TOTAL ACCOUNT FEES |
| `grand_total_fees` | TOTAL (after TOTAL ACCOUNT FEES) |
| `total_interchange_program` | Total Interchange Charges/Program Fees |
| `total_service_charges` | Total Service Charges |
| `total_fees_bucket` | Total Fees (the "Fees" type bucket only — NOT grand total) |
| `fee_line_items[]` | Array of {card_brand, description, fee_type, count, volume, rate, amount} |

### Interchange Detail (per product)
| Field | Source |
|-------|--------|
| `interchange_products[]` | Array of {brand, product, sales, pct_sales, txn_count, pct_txns, rate, per_txn, charges} |
| `interchange_brand_totals[]` | Array of {brand, total_sales, total_count, total_charges} |
| `interchange_grand_total` | {total_sales, total_count, total_charges} |

---

## 4. Reconciliation Formulas

These MUST all pass for a valid extraction:

### R1: Summary Math
```
total_processed == total_submitted + chargebacks_reversals + adjustments + fees
```
(All values are signed — chargebacks/adjustments/fees are negative)

### R2: Card Type Total = Total Submitted
```
sum(card_type.total_amount for all card types) == total_submitted
```

### R3: Card Type Internal Consistency
```
for each card type:
  total_amount == gross_amount + refund_amount  (refund_amount is negative)
  total_items == gross_items + refund_items
```

### R4: Summary By Day Total = Summary
```
daily_total.submitted == total_submitted
daily_total.chargebacks == chargebacks_reversals
daily_total.adjustments == adjustments
daily_total.fees == fees
daily_total.processed == total_processed
```

### R5: Grand Total Fees = Transaction Fees + Account Fees
```
grand_total_fees == total_transaction_fees + total_account_fees
```

### R6: Three-Way Fee Breakdown = Grand Total
```
grand_total_fees == total_interchange_program + total_service_charges + total_fees_bucket
```
Also confirmed by:
```
Total (Service Charges, Interchange Charges/Program Fees, and Fees) == grand_total_fees
```

### R7: Fees = Summary Fees
```
grand_total_fees == fees  (from SUMMARY section, both negative)
```

### R8: Chargebacks Total = Summary Chargebacks
```
chargeback_total == chargebacks_reversals  (from SUMMARY)
```

### R9: Adjustments Total = Summary Adjustments
```
adjustment_total == adjustments  (from SUMMARY)
```

### R10: Interchange Detail Total Sales = Total Submitted
```
interchange_grand_total.total_sales == total_submitted
```

### R11: Batch Total = Total Submitted
```
batch_total.total_amount == total_submitted
batch_total.gross_amount == card_type_total.gross_amount
```

---

## 5. Effective Rate Computation

### Gross Effective Rate
```
gross_rate = abs(grand_total_fees) / total_submitted * 100
```

### Interchange-Only Rate
```
ic_rate = abs(total_interchange_program) / total_submitted * 100
```

### Service Charge Rate (processor markup)
```
sc_rate = abs(total_service_charges) / total_submitted * 100
```

### Fee Rate (network/account fees)
```
fee_rate = abs(total_fees_bucket) / total_submitted * 100
```

### Per-Brand Interchange Rate (from interchange detail)
```
brand_ic_rate = abs(brand.total_charges) / brand.total_sales * 100
```

---

## 6. MSA v2 Fee Taxonomy Mapping

| Fiserv Category | Fee Type Label | MSA v2 Bucket | Notes |
|-----------------|---------------|---------------|-------|
| Interchange charges | `Interchange charges` | `interchange` | Passthrough IC from card networks |
| Program Fees | `Program Fees` | `interchange` | Amex program fees (IC equivalent) |
| Service charges | `Service charges` | `processor_markup` | Discount rates, sales discounts, connectivity fees |
| Fees (Transaction) | `Fees` in TRANSACTION FEES | `network_assessment` | Network access, auth, digital commerce fees |
| Fees (Account) | `Fees` in ACCOUNT FEES | `account_other` | Monthly fees, PCI, compliance, dispute fees |
| Assessment fees | `Interchange charges` (named "Assessment") | `network_assessment` | Card brand assessments — override bucket |

**Assessment fee override:** Lines containing "ASSESSMENT FEE" are labeled `Interchange charges` by Fiserv but are actually network assessments. Map these to `network_assessment` instead of `interchange`.

---

## 7. Risk Flags

| Flag | Condition | Severity |
|------|-----------|----------|
| `high_effective_rate` | gross_rate > 5.0% | Warning |
| `excessive_chargebacks` | chargeback_count / total_items > 1.0% | Critical |
| `chargeback_dollar_ratio` | abs(chargebacks_reversals) / total_submitted > 1.5% | Critical |
| `high_adjustments` | abs(adjustments) / total_submitted > 1.0% | Warning |
| `high_account_fees` | abs(total_account_fees) > 500 | Review |
| `dispute_fees_present` | any fee line contains "CHARGEBACK" or "DISPUTE" | Info |
| `intl_fees_present` | any fee line contains "INTL" or "CROSS BORDER" | Info |
| `high_refund_ratio` | abs(refund_amount) / gross_amount > 10% | Warning |

---

## 8. Ground Truth Reference

### Statement 1: Fitflexgummies April (6 pages, Newtek, typical e-commerce)
- Merchant: FITFLEXGUMMIES.COM, MID 815204582887
- Period: 04/01/25 - 04/30/25
- Total Submitted: $11,935.56 (100 items: 82 gross sales, 18 refunds)
- Chargebacks/Reversals: -$4,334.62
- Adjustments: -$1,104.65
- Fees: -$1,342.73
- Total Processed: $5,153.56
- Card types: Mastercard (53 items, $6,492.35), VISA (47 items, $5,443.21)
- Fee breakdown: Transaction Fees -$577.91, Account Fees -$764.82, TOTAL -$1,342.73
- Three-way: Interchange -$242.64, Service Charges -$296.61, Fees -$803.48
- Interchange detail: MC TOTAL $6,492.35 / 53 / -$122.47, VISA TOTAL $5,443.21 / 47 / -$100.39, TOTAL $11,935.56 / 100 / -$222.86
- Gross effective rate: 1,342.73 / 11,935.56 = 11.25% (HIGH — due to chargebacks/disputes inflating account fees)

### Statement 2: Sandhill Crane January (8 pages, CardPointe, high volume government)
- Merchant: CITY OF PBG SANDHILL 2, MID 496372494880
- Period: 01/01/26 - 01/31/26
- Total Submitted: $446,986.19 (3,447 items: 3,388 gross, 59 refunds)
- Chargebacks/Reversals: -$594.92
- Adjustments: $0.00
- Fees: -$12,654.34
- Total Processed: $433,736.93
- Card types: Mastercard (869, $110,423.31), VISA (1,694, $212,783.84), Discover (68, $6,040.37), AMEX ACQ (816, $117,738.67)
- Fee breakdown: Transaction Fees -$12,367.62, Account Fees -$286.72, TOTAL -$12,654.34
- Three-way: Interchange -$7,568.92, Service Charges -$4,040.87, Fees -$1,044.55
- Interchange detail: MC TOTAL $110,423.31 / 869 / -$1,701.86, VISA TOTAL $212,783.84 / 1,694 / -$3,121.33, DISCOVER TOTAL $6,040.37 / 68 / -$95.90, AMEX ACQ TOTAL $117,738.67 / 816 / -$1,974.63, TOTAL $446,986.19 / 3,447 / -$6,893.72
- Gross effective rate: 12,654.34 / 446,986.19 = 2.83%

### Statement 3: Fitflexgummies February (10 pages, Newtek, high chargebacks)
- Merchant: FITFLEXGUMMIES.COM, MID 815204582887
- Period: 02/01/25 - 02/28/25
- Has IMPORTANT INFORMATION notice on page 1 (pushes Summary By Day to page 2)
- High chargeback volume
- Same structural layout, confirms parser handles page overflow
