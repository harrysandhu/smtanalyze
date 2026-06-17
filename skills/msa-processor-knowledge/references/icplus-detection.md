# IC+ Markup Detection — Implementation Guide

## Overview

These methods extract the processor's interchange-plus markup (basis points + per-transaction fee) from statement data alone, without needing external interchange tables. The card brands publish interchange tables twice a year (April and October), they contain hundreds of categories, and processor naming conventions don't match — so table-matching is fragile. These methods sidestep all of that.

## Known Interchange Anchors

These interchange rates are stable, well-known, and appear on most US merchant statements. Use them for the anchor method.

| Category | TSYS Name(s) | IC Rate | IC Per-Txn | Notes |
|----------|-------------|---------|------------|-------|
| Visa Regulated Debit | Regulated Debit, VS Reg Debit | 0.05% | $0.21 | Fixed by Durbin amendment. Most reliable anchor. |
| Visa CPS Retail | CPS Retail | 1.51% | $0.10 | Card-present swiped/dipped. Very common. |
| Visa CPS e-Commerce Basic | Merit3, CPS eComm Basic | 1.80% | $0.25 | Standard e-commerce qualified. |
| MC Core / Merit III | MC Merit 3 | 1.58% | $0.10 | Base MC consumer card-present. |
| MC Regulated Debit | MC Reg Debit | 0.05% | $0.21 | Same Durbin cap as Visa. |
| Discover Regulated Debit | DS Reg Debit | 0.05% | $0.21 | Same Durbin cap. |

**Caution**: Amex OptBlue rates vary by merchant volume tier AND card type. Do NOT use Amex as an anchor — solve for it separately after determining the V/MC markup.

## Method 2: Anchor Category — Step by Step

### The Math

For any interchange category on an IC+ plan:

```
Total_Fee = IC_Amount + (markup_pct × volume) + (per_txn × count)
```

Rearranged:

```
Excess = Total_Fee − IC_Amount = (markup_pct × volume) + (per_txn × count)
```

Where `IC_Amount = (ic_rate × volume) + (ic_per_txn × count)` using the known anchor rates.

With two categories (a and b):

```
Excess_a = markup_pct × vol_a + per_txn × count_a
Excess_b = markup_pct × vol_b + per_txn × count_b
```

Solve:

```
markup_pct = (Excess_a × count_b − Excess_b × count_a) / (vol_a × count_b − vol_b × count_a)
per_txn = (Excess_a − markup_pct × vol_a) / count_a
```

### Python Implementation

```python
def solve_icplus_anchor(categories):
    """
    Solve for IC+ markup using two anchor categories.
    
    Each category dict:
        name: str
        volume: float          # dollar volume
        count: int             # transaction count
        total_fee: float       # total fee charged on statement
        known_ic_pct: float    # known interchange rate (e.g., 0.0005 for 0.05%)
        known_ic_per_txn: float # known per-txn interchange (e.g., 0.21)
    
    Returns: (markup_pct, per_txn_fee) or None if unsolvable
    """
    if len(categories) < 2:
        return None
    
    # Calculate excess (fee above interchange) for each category
    for cat in categories:
        ic_amount = (cat['known_ic_pct'] * cat['volume']) + (cat['known_ic_per_txn'] * cat['count'])
        cat['excess'] = cat['total_fee'] - ic_amount
    
    a, b = categories[0], categories[1]
    
    denominator = (a['volume'] * b['count']) - (b['volume'] * a['count'])
    if abs(denominator) < 0.01:
        return None  # Categories too similar to solve
    
    markup_pct = (a['excess'] * b['count'] - b['excess'] * a['count']) / denominator
    per_txn = (a['excess'] - markup_pct * a['volume']) / a['count']
    
    return (markup_pct, per_txn)


# Example: US Coffee Inc (hypothetical)
result = solve_icplus_anchor([
    {
        'name': 'Visa Regulated Debit',
        'volume': 50000, 'count': 200,
        'total_fee': 167.00,
        'known_ic_pct': 0.0005, 'known_ic_per_txn': 0.21
    },
    {
        'name': 'Visa CPS Retail',
        'volume': 100000, 'count': 300,
        'total_fee': 2040.00,
        'known_ic_pct': 0.0151, 'known_ic_per_txn': 0.10
    }
])

if result:
    markup_pct, per_txn = result
    print(f"Markup: {markup_pct*100:.2f}% + ${per_txn:.2f}/txn")
```

### Validation

After solving, validate by checking 2-3 other categories:

```python
def validate_icplus(markup_pct, per_txn, categories):
    """
    Check solved markup against other categories.
    Returns list of (category_name, predicted_fee, actual_fee, error_pct).
    """
    results = []
    for cat in categories:
        ic_amount = (cat['known_ic_pct'] * cat['volume']) + (cat['known_ic_per_txn'] * cat['count'])
        predicted = ic_amount + (markup_pct * cat['volume']) + (per_txn * cat['count'])
        error_pct = abs(predicted - cat['total_fee']) / cat['total_fee'] * 100 if cat['total_fee'] > 0 else 0
        results.append((cat['name'], predicted, cat['total_fee'], error_pct))
    return results
```

If validation error is <1% across categories, you have high confidence. If certain categories show >5% error, they likely have different pricing (Amex, pin debit network fees, or the category isn't truly IC+).

## Method 3: Linear Regression

Use when the statement shows IC amounts per category (no need for known anchor rates).

```python
import numpy as np

def solve_icplus_regression(categories):
    """
    Solve IC+ markup via linear regression across all categories.
    
    Each category dict:
        volume: float
        count: int
        total_fee: float
        ic_amount: float  # interchange amount shown on statement
    
    Returns: (markup_pct, per_txn_fee, r_squared, outliers)
    """
    excesses = []
    volumes = []
    counts = []
    names = []
    
    for cat in categories:
        if cat['volume'] > 0 and cat['count'] > 0:
            excesses.append(cat['total_fee'] - cat['ic_amount'])
            volumes.append(cat['volume'])
            counts.append(cat['count'])
            names.append(cat.get('name', ''))
    
    if len(excesses) < 3:
        return None
    
    # y = markup_pct * volume + per_txn * count
    X = np.column_stack([volumes, counts])
    y = np.array(excesses)
    
    # Least squares: solve for [markup_pct, per_txn]
    result = np.linalg.lstsq(X, y, rcond=None)
    coeffs = result[0]
    markup_pct = coeffs[0]
    per_txn = coeffs[1]
    
    # R-squared
    y_pred = X @ coeffs
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    
    # Flag outliers (>5% residual)
    outliers = []
    for i, name in enumerate(names):
        if y[i] > 0:
            error_pct = abs(y[i] - y_pred[i]) / y[i] * 100
            if error_pct > 5:
                outliers.append((name, error_pct))
    
    return (markup_pct, per_txn, r_squared, outliers)
```

### Interpreting Results

- **R² > 0.99**: High confidence — true IC+ pricing confirmed
- **R² 0.95–0.99**: Likely IC+ with a few categories priced differently (check outliers)
- **R² < 0.95**: Probably not pure IC+ — could be tiered, blended, or mixed pricing
- **Outliers**: Usually Amex (different markup), pin debit (network fees), or downgrades (IC amount already includes the adjustment)

## Method 1: Summary-Level Blended

For quick estimates when per-category detail isn't available:

```python
def blended_markup(total_discount, total_ic, total_assessments, total_volume, total_count):
    """
    Quick blended markup estimate from statement summary totals.
    Returns (blended_markup_pct, markup_dollars).
    Cannot separate % from per-txn — gives a single blended number.
    """
    markup_dollars = total_discount - total_ic - total_assessments
    blended_pct = markup_dollars / total_volume if total_volume > 0 else 0
    return (blended_pct, markup_dollars)
```

This gives you the total cost above interchange but can't tell you if it's structured as 0.50% + $0.10 vs 0.30% + $0.15. Still useful for quick comparisons.

## Decision Tree: Which Method to Use

```
Statement shows IC amount per category?
├── YES → Method 3 (regression) for precision, validated by Method 2 (anchor) 
│         Report: "IC+ markup: X bps + $Y/txn (R²=Z, N categories)"
├── PARTIAL (only summary totals) → Method 1 (blended)
│         Report: "Blended markup: X bps above interchange (per-category breakdown unavailable)"
└── NO (flat-rate or tiered statement) → Cannot determine IC+ structure
          Report: "Statement shows flat/tiered pricing at X%. IC+ breakdown not available."

Has regulated debit on the statement?
├── YES → Best anchor available. Use as primary anchor for Method 2.
└── NO → Use Visa CPS Retail or MC Core Merit III as anchors (less certain, rates can shift ±2bps at April/October updates)
```

## Hidden Fees to Add Back

After solving for markup% + per-txn, don't forget that total processor cost includes fees OUTSIDE the per-category pricing:

- Settlement Funding Fee (0.10–0.20% of volume — common on TSYS)
- PCI Compliance Fee ($5–$15/mo)
- Statement Fee ($5–$25/mo)
- Batch Fee ($0.10–$0.25 per batch)
- Monthly Minimum (if volume is low)
- Authorization Fee (sometimes separate from per-txn markup)

Total processor cost = IC+ markup + hidden fees. The IC+ solve gives you just the first component.
