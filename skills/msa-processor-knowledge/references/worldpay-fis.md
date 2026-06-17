# Worldpay / FIS Statement Parsing Guide

## Identification Markers

- **MM-303 report format** — The statement is titled or formatted as an "MM-303" report
- **"VISANET-VIRT NET"** authorization descriptors in the transaction detail
- Report header may reference Worldpay, FIS, or Vantiv (legacy name)
- Interchange detail organized by card brand sections with adjustment columns

## Critical Understanding: MM-303 is Information-Only

The MM-303 report is an **interchange detail report**. It shows what interchange was charged by the card brands, but it does NOT show the processor's markup. Processor markup fees are **billed separately** — typically on a different statement or invoice.

This means:
- You CANNOT determine total processing cost from MM-303 alone
- You CAN determine interchange cost, card mix, and downgrade exposure
- You need a separate fee statement to calculate processor markup
- If you only have MM-303, state this limitation clearly in any analysis

## Statement Structure

1. **Header** — Merchant name, MID, report period
2. **Visa Section** — Interchange categories with: volume, count, interchange amount, adjustment amount
3. **Mastercard Section** — Same format
4. **Discover Section** — Same format  
5. **American Express Section** — If OptBlue
6. **Summary** — Totals by brand

## Interchange Detail Columns

Worldpay MM-303 typically shows these columns per interchange category:
- **Description**: Interchange category name
- **Items**: Transaction count
- **Amount**: Transaction volume
- **IC Amount**: Interchange cost
- **IC Adj Amount**: Interchange adjustments/downgrades

The **IC Adj Amount** column is critical — it shows the ADDITIONAL cost from downgrades above the base interchange rate.

## Interchange Naming Conventions

Worldpay uses names closer to the card brand official names than TSYS does:

### Visa
- CPS/Retail 2, CPS/e-Commerce, CPS/Card Not Present
- Commercial Standard, Commercial Level II, Commercial Level III  
- Signature Preferred, Infinite

### Mastercard
- Core, Enhanced, World, World Elite
- Commercial Data Rate I, Commercial Data Rate II
- Regulated/Non-Regulated Debit

## Gotchas

### 1. Fees Not on This Report
Cannot calculate effective rate or processor markup from MM-303 alone. Always ask: "Do you also have the fee statement / invoice from Worldpay?"

### 2. Adjustment Column
The IC Adj column shows downgrade costs. A row with $0 in IC Amount but a value in IC Adj means that volume was downgraded and the adjustment is the penalty amount.

### 3. B2B / Commercial Card Analysis
Worldpay MM-303 is actually excellent for B2B downgrade analysis because it separates commercial card tiers clearly. Look for:
- Commercial Standard (downgraded — no L2/L3 data)
- Commercial Level II (qualified with L2)
- Commercial Level III (best rate — L3 data submitted)

### 4. Volume Reconciliation
MM-303 volume should reconcile with the merchant's bank deposits + fees withheld. If it doesn't match, there may be adjustments, chargebacks, or reserves not shown on MM-303.

## Parsing Strategy

1. **Parse by card brand section** — each brand has its own block
2. **Sum IC Amount + IC Adj Amount** per brand for total interchange cost
3. **Identify downgrades** from the adjustment column — nonzero adj amounts
4. **Calculate brand mix** from volume per brand / total volume
5. **Note limitation** — cannot determine processor markup without fee statement
6. **Focus analysis on**: interchange optimization (downgrades), card mix insights, volume trends (if multi-month)
