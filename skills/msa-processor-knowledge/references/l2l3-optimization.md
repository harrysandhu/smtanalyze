# L2/L3 Data Optimization — Detection & Savings Calculation

## Why This Matters

Commercial cards (Business, Purchasing, Corporate, Fleet) are priced in tiers based on the quality of transaction data submitted. Most merchants submit only basic data (Level 1 = card number, amount, date). Submitting enhanced data — Level 2 (tax amount, PO#, customer code) or Level 3 (line-item detail) — qualifies transactions at lower interchange rates.

This is NOT the same as fixing "downgrades." The transactions are correctly qualified for the data submitted — they're at the BASE rate for commercial cards. The opportunity is upgrading to a better tier. This distinction is why it's easy to miss: a scan for EIRF/Standard fallback categories won't find it.

## Detection: What to Look For

### Visa Commercial — "Product 1" Indicators

On TSYS-platform and Payroc statements, Visa commercial categories follow this naming:

| Pattern | Meaning | L2/L3 Opportunity? |
|---------|---------|-------------------|
| `VS Business Tr[1-5] Prod 1` | Business card, Tier 1-5, NO enhanced data | **Limited** — Visa Business L2 rates are often identical to Prod 1 in the same tier |
| `VS Purchasing CR Product 1` | Purchasing card, NO enhanced data | **YES** — Purchasing L2 is typically 20bps lower |
| `VS Corporate [X] Product 1` | Corporate card, NO enhanced data | **YES** — Corporate L2 saves ~20bps |
| `VS Non Qual Bus Cr` | Non-qualified Business Credit | **YES** — 35+ bps over qualified tiers |
| `VS Non-Qual Purchasing Credit` | Non-qualified Purchasing | **YES** — can drop to Purchasing L2 |
| `VS Business Level 2 T[1-5]` | Business card WITH L2 data | Already optimized |
| `VS Purchasing Non Travel Lvl 2` | Purchasing WITH L2 data | Already optimized |
| `VS Corporate Non Travel Lvl 2` | Corporate WITH L2 data | Already optimized |

**Key Visa insight**: Visa Business "Prod 1" and "Level 2" categories in the same tier often carry the **identical rate**. Don't promise savings on Visa Business cards without verifying from the statement itself that L2 rates are actually lower. Purchasing and Corporate cards are where Visa L2 savings concentrate.

### Mastercard Commercial — "Data Rate I" Indicators

Mastercard has a clearer tier structure where L2 data consistently lowers rates:

| Pattern | Meaning | L2/L3 Opportunity? |
|---------|---------|-------------------|
| `MC [X] Data Rate I` or `Data Rate 1` | Commercial card, NO enhanced data | **YES** — Data Rate II is typically 15-75bps lower |
| `MC Business Level [1-5] Data Rate I` | Business card by level, NO L2 | **YES** — especially Level 5 (75bps on some statements) |
| `Comm Data Rate 1 Large Market` | Large-market commercial, NO L2 | **YES** — high volume, 45-65bps potential |
| `MC Corporate Data Rate 1` | Corporate, NO L2 | **YES** — 15bps typical |
| `Commercial Data Rate II` or `Data Rate 2` | WITH L2 data submitted | Already at L2 |
| `Commercial Data Rate [X] Level 2` | Explicit L2 qualification | Already optimized |
| `Commercial Data Rate [X] Level 3/4` | L3 data submitted | Already optimized (best rate) |

**Key MC insight**: MC Business Level 5 Data Rate I → Data Rate II can save 75bps. On a $175K category, that's $1,300/month. Always check this category first.

### Discover Commercial

Discover commercial categories are less common but follow similar patterns. Look for:
- `DS Comm Elec Debit` (base commercial)
- Non-qualified Discover commercial tiers

## Savings Calculation

### Step 1: Identify Target Rates

Use the statement itself as evidence. If the same statement shows both "Data Rate I" and "Data Rate II" categories for the same commercial sub-program, you have a direct rate comparison.

Example from a real Payroc statement:
```
MC Business Level 5 Data Rate I:  3.00% + $0.10  (299 items, $175,692)
MC Business Level 5 Data Rate II: 2.25% + $0.10  (1 item, $142)
→ L2 saves 75bps on this category
```

If the statement only shows Data Rate I (no Data Rate II examples), use the official Mastercard US interchange table as the source of truth. The table is saved locally at `references/mastercard-us-interchange-april-2025-2026.pdf` (Canadian table also available as `references/mastercard-canada-interchange-april-2026.pdf`). Tables are updated by Mastercard every April and October — check for newer versions if the date is stale.

**Official MC US rates (Page 7 — Small Business Credit, Page 8 — Large Market Credit):**

| Category Type | DR-I (Published) | DR-II (Published) | DR-III | Δ I→II | Δ I→III | Source |
|---------------|-------------------|--------------------|---------|---------|---------|----|
| MC Business Level 1 (Core) | 2.65% + $0.10 | 1.90% + $0.10 | — | **75 bps** | — | Page 7 |
| MC Business Level 2 (World) | 2.80% + $0.10 | 2.05% + $0.10 | — | **75 bps** | — | Page 7 |
| MC Business Level 3 (World Elite) | 2.85% + $0.10 | 2.10% + $0.10 | — | **75 bps** | — | Page 7 |
| MC Business Level 4 | 2.95% + $0.10 | 2.20% + $0.10 | — | **75 bps** | — | Page 7 |
| MC Business Level 5 | 3.00% + $0.10 | 2.25% + $0.10 | — | **75 bps** | — | Page 7 |
| MC Large Market Credit | 2.70% + $0.10 | 2.50% + $0.10 | 1.90% + $0.10 | **20 bps** | **80 bps** | Page 8 |
| MC Commercial Debit | 2.65% + $0.10 | 2.10% + $0.10 | — | **55 bps** | — | Page 8 |
| Visa Purchasing | — | — | — | **~20 bps** | — | Statement evidence |
| Visa Corporate | — | — | — | **~20 bps** | — | Statement evidence |
| Visa Business | — | — | — | **0 bps** | — | Statement evidence (same rate) |

**Key takeaway**: MC Business Levels 1–5 ALL save exactly 75bps. MC Large Market saves only 20bps for L2, but 80bps for L3. Always quote L2 savings as the baseline and L3 as a stretch target.

### Step 2: Calculate Per-Category Savings

```python
def l2l3_savings(categories):
    """
    Calculate L2/L3 optimization savings.
    
    Each category dict:
        name: str
        items: int
        volume: float
        current_rate: float      # e.g., 0.0300 for 3.00%
        current_per_txn: float   # e.g., 0.10
        target_rate: float       # L2/L3 target rate
        target_per_txn: float    # L2/L3 target per-txn (usually same)
    
    Returns: list of (name, volume, savings_monthly, savings_annual)
    """
    results = []
    total_monthly = 0
    
    for cat in categories:
        rate_savings = (cat['current_rate'] - cat['target_rate']) * cat['volume']
        ptxn_savings = (cat['current_per_txn'] - cat['target_per_txn']) * cat['items']
        monthly = rate_savings + ptxn_savings
        total_monthly += monthly
        results.append({
            'name': cat['name'],
            'volume': cat['volume'],
            'bps_delta': (cat['current_rate'] - cat['target_rate']) * 10000,
            'monthly_savings': monthly,
            'annual_savings': monthly * 12
        })
    
    results.append({
        'name': 'TOTAL',
        'volume': sum(c['volume'] for c in categories),
        'bps_delta': None,
        'monthly_savings': total_monthly,
        'annual_savings': total_monthly * 12
    })
    
    return results
```

### Step 3: Present with Confidence Level

Always state which scenario you're using:

- **High confidence**: Target rate taken directly from another category on the same statement (e.g., statement shows both DR-I and DR-II for the same sub-program)
- **Moderate confidence**: Target rate from a related category on the same statement or from published MC interchange tables
- **Estimate**: Using default bps assumptions from the table above

### Step 4: Include in Report

Add an "L2/L3 Data Optimization" section to the quote template and/or Word report. Show:
1. Each affected category with current rate, target rate, delta bps, monthly savings
2. Total monthly and annual savings
3. A note explaining what L2/L3 data means and what the merchant needs to do (submit tax, PO#, line items with each transaction — usually a gateway/POS configuration change)

## What the Merchant Needs to Do

L2/L3 savings require the merchant to actually submit enhanced data with each transaction. This typically means:

**Level 2 (easier, most of the savings):**
- Tax amount (even $0.00 is better than blank)
- Customer code / PO number
- Usually a gateway or POS configuration setting — not a code change

**Level 3 (harder, incremental savings on MC):**
- Line-item detail: item description, quantity, unit price, commodity code
- Usually requires integration work or a specialized gateway that supports L3

**Realistic expectation**: Most merchants can achieve L2 relatively easily. L3 is harder and mainly benefits large B2B merchants with compatible systems. Quote L2 savings as the primary opportunity; L3 as a stretch goal.

## Common Pitfall: Overstating Visa Business Savings

On multiple statements we've observed that Visa Business "Prod 1" and "Level 2" carry the **same interchange rate** within each tier. This means submitting L2 data on Visa Business cards may not actually save anything — the card brands may have already aligned these rates.

Always verify from the statement itself before claiming Visa Business L2 savings. If the statement shows both categories at the same rate, do NOT include Visa Business in the savings estimate. Focus on Purchasing, Corporate, and Mastercard commercial categories where L2 consistently delivers rate reductions.
