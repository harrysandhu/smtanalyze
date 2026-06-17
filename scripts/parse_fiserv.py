#!/usr/bin/env python3
"""
Fiserv / CardPointe / Newtek statement parser.

Extracts structured data from Fiserv-family merchant statement PDFs using pdfplumber.
Supports --json (machine-readable output) and --validate (reconciliation checks) modes.

Usage:
    python parse_fiserv.py <pdf_path>                   # human-readable summary
    python parse_fiserv.py <pdf_path> --json             # JSON output
    python parse_fiserv.py <pdf_path> --validate         # reconciliation checks only
    python parse_fiserv.py <directory> --validate         # batch validate all PDFs
"""

import sys
import os
import re
import json
import argparse
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber required. Install with: pip install pdfplumber")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Amount parsing
# ---------------------------------------------------------------------------

def parse_amount(s):
    """Parse a dollar amount string into Decimal. Handles: $1,234.56, -$1,234.56, 0.00, .30, -$0.00"""
    if s is None:
        return Decimal("0")
    s = str(s).strip()
    if not s or s == '-':
        return Decimal("0")
    negative = False
    if s.startswith('-'):
        negative = True
        s = s[1:]
    s = s.replace('$', '').replace(',', '').strip()
    if not s or s == '.':
        return Decimal("0")
    try:
        val = Decimal(s)
    except InvalidOperation:
        return Decimal("0")
    return -val if negative else val


# Amount regex pattern — handles $1,234.56, -$1,234.56, 0.00, .30
AMT = r"-?\$?\.?\d[\d,]*\.?\d*"


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_full_text(pdf_path):
    """Extract text from all pages, return list of page texts and concatenated full text."""
    pdf = pdfplumber.open(pdf_path)
    pages = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        pages.append(text)
    pdf.close()
    full_text = "\n".join(pages)
    return pages, full_text


def is_fiserv_statement(full_text):
    """Check if text matches Fiserv statement fingerprint."""
    return (
        "YOUR CARD PROCESSING STATEMENT" in full_text
        and "Total Amount Submitted" in full_text
    )


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

def parse_header(full_text, pages):
    """Extract header fields from page 1."""
    header = {}

    # Merchant number
    m = re.search(r"Merchant Number\s+(\d+)", full_text)
    header['merchant_number'] = m.group(1) if m else None

    # Statement period
    m = re.search(r"Statement Period\s+(\d{2}/\d{2}/\d{2})\s*-\s*(\d{2}/\d{2}/\d{2})", full_text)
    if m:
        header['statement_period'] = f"{m.group(1)} - {m.group(2)}"
        header['period_start'] = m.group(1)
        header['period_end'] = m.group(2)
    else:
        header['statement_period'] = None
        header['period_start'] = None
        header['period_end'] = None

    # Page count
    m = re.search(r"Page 1 of (\d+)", pages[0])
    header['page_count'] = int(m.group(1)) if m else len(pages)

    # Merchant name — first line of page 1 that appears before "Page 1 of"
    # It's on the same line as "Page 1 of N" in many cases
    p1_lines = pages[0].split('\n')
    for line in p1_lines:
        if 'Page 1 of' in line:
            name = line.split('Page 1 of')[0].strip()
            if name:
                header['merchant_name'] = name
                break
    else:
        header['merchant_name'] = None

    # Branding
    if 'cardpointe' in full_text.lower():
        header['branding'] = 'cardpointe'
    elif 'newtek' in full_text.lower():
        header['branding'] = 'newtek'
    else:
        header['branding'] = 'fiserv'

    return header


# ---------------------------------------------------------------------------
# Summary parsing
# ---------------------------------------------------------------------------

def parse_summary(full_text):
    """Extract SUMMARY section values."""
    summary = {}

    # Total Amount Submitted
    m = re.search(rf"Total Amount Submitted\s+({AMT})", full_text)
    summary['total_submitted'] = parse_amount(m.group(1)) if m else Decimal("0")

    # Chargebacks/Reversals
    m = re.search(rf"Chargebacks/Reversals\s+({AMT})", full_text)
    summary['chargebacks_reversals'] = parse_amount(m.group(1)) if m else Decimal("0")

    # Adjustments
    m = re.search(rf"(?:Page \d+\s+)?Adjustments\s+({AMT})", full_text)
    summary['adjustments'] = parse_amount(m.group(1)) if m else Decimal("0")

    # Fees (in SUMMARY — the line with "Page N Fees")
    # Must be careful not to match other "Fees" lines
    m = re.search(rf"Page \d+\s+Fees\s+({AMT})", full_text)
    summary['fees'] = parse_amount(m.group(1)) if m else Decimal("0")

    # Total Amount Processed
    m = re.search(rf"Total Amount Processed\s+({AMT})", full_text)
    summary['total_processed'] = parse_amount(m.group(1)) if m else Decimal("0")

    return summary


# ---------------------------------------------------------------------------
# Summary By Card Type
# ---------------------------------------------------------------------------

def parse_card_types(full_text):
    """Extract SUMMARY BY CARD TYPE section."""
    card_types = []
    totals = {}

    # Find the section
    section_match = re.search(r"SUMMARY BY CARD TYPE(.*?)(?:SUMMARY BY BATCH|$)", full_text, re.DOTALL)
    if not section_match:
        return card_types, totals

    section = section_match.group(1)

    # Card type line pattern:
    # Mastercard $127.07 855 $111,306.71 14 -$883.40 869 $110,423.31
    # VISA $125.61 1,662 $216,918.02 32 -$4,134.18 1,694 $212,783.84
    # Pattern: <name> <avg_ticket> <gross_items> <gross_amount> <refund_items> <refund_amount> <total_items> <total_amount>
    card_pattern = re.compile(
        rf"^(Mastercard|VISA|Discover|AMEX ACQ)\s+"
        rf"({AMT})\s+"          # avg_ticket
        rf"([\d,]+)\s+"         # gross_items
        rf"({AMT})\s+"          # gross_amount
        rf"([\d,]+)\s+"         # refund_items
        rf"({AMT})\s+"          # refund_amount
        rf"([\d,]+)\s+"         # total_items
        rf"({AMT})",            # total_amount
        re.MULTILINE
    )

    for m in card_pattern.finditer(section):
        ct = {
            'card_type': m.group(1),
            'avg_ticket': parse_amount(m.group(2)),
            'gross_items': int(m.group(3).replace(',', '')),
            'gross_amount': parse_amount(m.group(4)),
            'refund_items': int(m.group(5).replace(',', '')),
            'refund_amount': parse_amount(m.group(6)),
            'total_items': int(m.group(7).replace(',', '')),
            'total_amount': parse_amount(m.group(8)),
        }
        card_types.append(ct)

    # Total row
    total_match = re.search(
        rf"Total\s+([\d,]+)\s+({AMT})\s+([\d,]+)\s+({AMT})\s+([\d,]+)\s+({AMT})",
        section
    )
    if total_match:
        totals = {
            'gross_items': int(total_match.group(1).replace(',', '')),
            'gross_amount': parse_amount(total_match.group(2)),
            'refund_items': int(total_match.group(3).replace(',', '')),
            'refund_amount': parse_amount(total_match.group(4)),
            'total_items': int(total_match.group(5).replace(',', '')),
            'total_amount': parse_amount(total_match.group(6)),
        }

    return card_types, totals


# ---------------------------------------------------------------------------
# Chargebacks
# ---------------------------------------------------------------------------

def parse_chargebacks(full_text):
    """Extract CHARGEBACKS/REVERSALS section."""
    result = {
        'total': Decimal("0"),
        'entries': [],
        'chargeback_count': 0,
        'reversal_count': 0,
    }

    # Find TOTAL line in chargebacks section
    # Look for CHARGEBACKS/REVERSALS section first
    cb_section = re.search(rf"CHARGEBACKS/REVERSALS.*?(?:TOTAL\s+({AMT}))", full_text, re.DOTALL)
    if cb_section:
        result['total'] = parse_amount(cb_section.group(1))

    # Count individual entries
    # Negative = chargeback, Positive = reversal
    cb_amounts = re.findall(
        rf"(\d{{2}}/\d{{2}}/\d{{2}})\s+(\d+)\s+.*?((?:-|\+)?\$[\d,]+\.\d+)\s*$",
        full_text, re.MULTILINE
    )
    for date, ref, amt in cb_amounts:
        amount = parse_amount(amt)
        if amount < 0:
            result['chargeback_count'] += 1
        elif amount > 0:
            result['reversal_count'] += 1

    return result


# ---------------------------------------------------------------------------
# Adjustments
# ---------------------------------------------------------------------------

def parse_adjustments(full_text):
    """Extract ADJUSTMENTS section."""
    result = {
        'total': Decimal("0"),
        'entries': [],
    }

    # Check for "No Adjustments"
    if "No Adjustments for this Statement Period" in full_text:
        return result

    # Find adjustment total — bounded by FEES section
    adj_section = re.search(
        rf"ADJUSTMENTS.*?(?:TOTAL|Total)\s+({AMT})",
        full_text, re.DOTALL
    )

    if adj_section:
        result['total'] = parse_amount(adj_section.group(1))

    return result


# ---------------------------------------------------------------------------
# Fee parsing
# ---------------------------------------------------------------------------

def parse_fees(full_text):
    """Extract fee breakdown from FEES section."""
    fees = {
        'total_transaction_fees': Decimal("0"),
        'total_account_fees': Decimal("0"),
        'grand_total_fees': Decimal("0"),
        'total_interchange_program': Decimal("0"),
        'total_service_charges': Decimal("0"),
        'total_fees_bucket': Decimal("0"),
        'three_way_total': Decimal("0"),
        'fee_line_items': [],
    }

    # TOTAL TRANSACTION FEES
    m = re.search(rf"TOTAL TRANSACTION FEES\s+({AMT})", full_text)
    if m:
        fees['total_transaction_fees'] = parse_amount(m.group(1))

    # TOTAL ACCOUNT FEES
    m = re.search(rf"TOTAL ACCOUNT FEES\s+({AMT})", full_text)
    if m:
        fees['total_account_fees'] = parse_amount(m.group(1))

    # Grand total — the TOTAL line that appears after TOTAL ACCOUNT FEES
    # Be precise: look for standalone TOTAL after TOTAL ACCOUNT FEES
    m = re.search(rf"TOTAL ACCOUNT FEES\s+{AMT}\s*\n\s*TOTAL\s+({AMT})", full_text)
    if m:
        fees['grand_total_fees'] = parse_amount(m.group(1))
    else:
        # Fallback: "Total (Service Charges, Interchange Charges/Program Fees, and Fees)"
        m = re.search(rf"Total \(Service Charges, Interchange Charges/Program Fees, and Fees\)\s+({AMT})", full_text)
        if m:
            fees['grand_total_fees'] = parse_amount(m.group(1))

    # Three-way breakdown
    m = re.search(rf"Total Interchange Charges/Program Fees\s+({AMT})", full_text)
    if m:
        fees['total_interchange_program'] = parse_amount(m.group(1))

    m = re.search(rf"Total Service Charges\s+({AMT})", full_text)
    if m:
        fees['total_service_charges'] = parse_amount(m.group(1))

    # Total Fees (the bucket, NOT grand total) — line right after Total Service Charges
    # Must distinguish from "TOTAL TRANSACTION FEES", "TOTAL ACCOUNT FEES", and the grand "TOTAL"
    m = re.search(rf"Total Service Charges\s+{AMT}\s*\nTotal Fees\s+({AMT})", full_text)
    if m:
        fees['total_fees_bucket'] = parse_amount(m.group(1))
    else:
        # Alternate: just find "Total Fees" that's not "TOTAL TRANSACTION FEES" or "TOTAL ACCOUNT FEES"
        m = re.search(rf"(?<!\w)Total Fees\s+({AMT})", full_text)
        if m:
            fees['total_fees_bucket'] = parse_amount(m.group(1))

    # Three-way total (for verification)
    m = re.search(rf"Total \(Service Charges, Interchange Charges/Program Fees, and Fees\)\s+({AMT})", full_text)
    if m:
        fees['three_way_total'] = parse_amount(m.group(1))

    # Parse individual fee line items
    fees['fee_line_items'] = parse_fee_line_items(full_text)

    return fees


def parse_fee_line_items(full_text):
    """Parse individual fee line items from TRANSACTION FEES and ACCOUNT FEES sections."""
    items = []

    # Find the FEES sections (may span multiple pages)
    # We'll scan for lines that have a fee_type label and a dollar amount at the end
    fee_types = ['Interchange charges', 'Service charges', 'Fees', 'Program Fees']

    current_section = None  # 'transaction' or 'account'
    current_brand = None

    for line in full_text.split('\n'):
        line = line.strip()

        # Track section
        if 'TRANSACTION FEES' in line and 'TOTAL' not in line:
            current_section = 'transaction'
            continue
        if 'ACCOUNT FEES' in line and 'TOTAL' not in line:
            current_section = 'account'
            current_brand = 'account'
            continue

        # Track card brand headers within TRANSACTION FEES
        if current_section == 'transaction':
            if line in ('MASTERCARD', 'VISA', 'DISCOVER', 'AMERICAN EXPRESS', 'AMEX ACQ', 'Other'):
                current_brand = line
                continue

        # Skip headers, totals, and non-fee lines
        if not current_section:
            continue
        if line.startswith('TOTAL') or line.startswith('Total'):
            continue
        if not line or line.startswith('YOUR CARD') or line.startswith('Merchant Number'):
            continue
        if line.startswith('Page ') or line.startswith('Customer Service'):
            continue
        if line.startswith('Phone') or line.startswith('FEES ') or line.startswith('services.'):
            continue
        if 'Statement Period' in line:
            continue

        # Try to match a fee line — must end with a fee_type and amount
        for ft in fee_types:
            pattern = rf"^(.+?)\s+{re.escape(ft)}\s+({AMT})\s*$"
            m = re.match(pattern, line)
            if m:
                desc = m.group(1).strip()
                amount = parse_amount(m.group(2))
                items.append({
                    'section': current_section,
                    'card_brand': current_brand,
                    'description': desc,
                    'fee_type': ft,
                    'amount': amount,
                })
                break

    return items


# ---------------------------------------------------------------------------
# Interchange detail
# ---------------------------------------------------------------------------

def parse_interchange_detail(full_text):
    """Parse INTERCHANGE CHARGES/PROGRAM FEES detail section."""
    result = {
        'brand_totals': [],
        'grand_total': {'total_sales': Decimal("0"), 'total_count': 0, 'total_charges': Decimal("0")},
    }

    # Brand total lines: MASTERCARD TOTAL $6,492.35 53 -$122.47
    brand_total_pattern = re.compile(
        rf"(MASTERCARD|VISA|DISCOVER|AMEX ACQ)\s+TOTAL\s+({AMT})\s+([\d,]+)\s+({AMT})"
    )
    for m in brand_total_pattern.finditer(full_text):
        result['brand_totals'].append({
            'brand': m.group(1),
            'total_sales': parse_amount(m.group(2)),
            'total_count': int(m.group(3).replace(',', '')),
            'total_charges': parse_amount(m.group(4)),
        })

    # Grand total: TOTAL $446,986.19 3,447 -$6,893.72
    # Must find the TOTAL that's NOT a brand total and is in the interchange section
    # Look for it after the last brand total
    ic_section = re.search(r"INTERCHANGE CHARGES/PROGRAM FEES(.*)", full_text, re.DOTALL)
    if ic_section:
        ic_text = ic_section.group(1)
        # Find the last TOTAL line that's not a brand total
        totals = list(re.finditer(
            rf"^TOTAL\s+({AMT})\s+([\d,]+)\s+({AMT})\s*$",
            ic_text, re.MULTILINE
        ))
        if totals:
            last = totals[-1]
            result['grand_total'] = {
                'total_sales': parse_amount(last.group(1)),
                'total_count': int(last.group(2).replace(',', '')),
                'total_charges': parse_amount(last.group(3)),
            }

    return result


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def run_reconciliation(data):
    """Run all reconciliation checks. Returns list of {check, passed, expected, actual, note}."""
    results = []
    summary = data['summary']
    card_totals = data['card_type_totals']
    fees = data['fees']
    chargebacks = data['chargebacks']
    adjustments = data['adjustments']
    interchange = data['interchange_detail']
    tol = Decimal("0.02")

    # R1: Summary Math
    expected = summary['total_submitted'] + summary['chargebacks_reversals'] + summary['adjustments'] + summary['fees']
    actual = summary['total_processed']
    results.append({
        'check': 'R1',
        'name': 'Summary Math (Submitted + CB + Adj + Fees = Processed)',
        'passed': abs(expected - actual) <= tol,
        'expected': str(expected),
        'actual': str(actual),
    })

    # R2: Card Type Total = Total Submitted
    if card_totals:
        actual_ct = card_totals.get('total_amount', Decimal("0"))
        results.append({
            'check': 'R2',
            'name': 'Card Type Total = Total Submitted',
            'passed': abs(actual_ct - summary['total_submitted']) <= tol,
            'expected': str(summary['total_submitted']),
            'actual': str(actual_ct),
        })

    # R3: Card Type Internal Consistency
    for ct in data['card_types']:
        expected_amt = ct['gross_amount'] + ct['refund_amount']
        results.append({
            'check': 'R3',
            'name': f"Card Type {ct['card_type']}: gross + refund = total",
            'passed': abs(expected_amt - ct['total_amount']) <= tol,
            'expected': str(expected_amt),
            'actual': str(ct['total_amount']),
        })
        expected_items = ct['gross_items'] + ct['refund_items']
        results.append({
            'check': 'R3',
            'name': f"Card Type {ct['card_type']}: items gross + refund = total",
            'passed': expected_items == ct['total_items'],
            'expected': str(expected_items),
            'actual': str(ct['total_items']),
        })

    # R5: Grand Total = Transaction + Account
    if fees['total_transaction_fees'] != 0 or fees['total_account_fees'] != 0:
        expected_r5 = fees['total_transaction_fees'] + fees['total_account_fees']
        results.append({
            'check': 'R5',
            'name': 'Grand Total = Transaction Fees + Account Fees',
            'passed': abs(expected_r5 - fees['grand_total_fees']) <= tol,
            'expected': str(expected_r5),
            'actual': str(fees['grand_total_fees']),
        })

    # R6: Three-way breakdown = Grand Total
    if fees['total_interchange_program'] != 0 or fees['total_service_charges'] != 0 or fees['total_fees_bucket'] != 0:
        expected_r6 = fees['total_interchange_program'] + fees['total_service_charges'] + fees['total_fees_bucket']
        results.append({
            'check': 'R6',
            'name': 'Three-way breakdown = Grand Total',
            'passed': abs(expected_r6 - fees['grand_total_fees']) <= tol,
            'expected': str(expected_r6),
            'actual': str(fees['grand_total_fees']),
        })

    # R6b: Three-way total line matches grand total
    if fees['three_way_total'] != 0:
        results.append({
            'check': 'R6b',
            'name': 'Three-way total line = Grand Total',
            'passed': abs(fees['three_way_total'] - fees['grand_total_fees']) <= tol,
            'expected': str(fees['grand_total_fees']),
            'actual': str(fees['three_way_total']),
        })

    # R7: Fees = Summary Fees
    results.append({
        'check': 'R7',
        'name': 'Grand Total Fees = Summary Fees',
        'passed': abs(fees['grand_total_fees'] - summary['fees']) <= tol,
        'expected': str(summary['fees']),
        'actual': str(fees['grand_total_fees']),
    })

    # R8: Chargebacks Total = Summary Chargebacks
    if summary['chargebacks_reversals'] != 0 or chargebacks['total'] != 0:
        results.append({
            'check': 'R8',
            'name': 'Chargebacks Total = Summary Chargebacks',
            'passed': abs(chargebacks['total'] - summary['chargebacks_reversals']) <= tol,
            'expected': str(summary['chargebacks_reversals']),
            'actual': str(chargebacks['total']),
        })

    # R9: Adjustments Total = Summary Adjustments
    if summary['adjustments'] != 0 or adjustments['total'] != 0:
        results.append({
            'check': 'R9',
            'name': 'Adjustments Total = Summary Adjustments',
            'passed': abs(adjustments['total'] - summary['adjustments']) <= tol,
            'expected': str(summary['adjustments']),
            'actual': str(adjustments['total']),
        })

    # R10: Interchange Detail Total Sales = Total Submitted
    ic_gt = interchange['grand_total']
    if ic_gt['total_sales'] != 0:
        results.append({
            'check': 'R10',
            'name': 'Interchange Detail Sales = Total Submitted',
            'passed': abs(ic_gt['total_sales'] - summary['total_submitted']) <= tol,
            'expected': str(summary['total_submitted']),
            'actual': str(ic_gt['total_sales']),
        })

    return results


# ---------------------------------------------------------------------------
# Risk flags
# ---------------------------------------------------------------------------

def compute_risk_flags(data):
    """Compute risk flags based on extracted data."""
    flags = []
    summary = data['summary']
    fees = data['fees']
    card_totals = data['card_type_totals']
    chargebacks = data['chargebacks']

    total_sub = summary['total_submitted']
    if total_sub > 0:
        # Effective rate
        gross_rate = abs(fees['grand_total_fees']) / total_sub * 100
        if gross_rate > 5:
            flags.append({
                'flag': 'high_effective_rate',
                'severity': 'Warning',
                'detail': f"Gross effective rate: {gross_rate:.2f}%",
            })

        # Chargeback dollar ratio
        if summary['chargebacks_reversals'] != 0:
            cb_ratio = abs(summary['chargebacks_reversals']) / total_sub * 100
            if cb_ratio > 1.5:
                flags.append({
                    'flag': 'chargeback_dollar_ratio',
                    'severity': 'Critical',
                    'detail': f"Chargeback dollar ratio: {cb_ratio:.2f}%",
                })

        # Adjustment ratio
        if summary['adjustments'] != 0:
            adj_ratio = abs(summary['adjustments']) / total_sub * 100
            if adj_ratio > 1:
                flags.append({
                    'flag': 'high_adjustments',
                    'severity': 'Warning',
                    'detail': f"Adjustment ratio: {adj_ratio:.2f}%",
                })

        # Refund ratio
        if card_totals:
            gross_amt = card_totals.get('gross_amount', Decimal("0"))
            refund_amt = card_totals.get('refund_amount', Decimal("0"))
            if gross_amt > 0 and refund_amt != 0:
                refund_ratio = abs(refund_amt) / gross_amt * 100
                if refund_ratio > 10:
                    flags.append({
                        'flag': 'high_refund_ratio',
                        'severity': 'Warning',
                        'detail': f"Refund ratio: {refund_ratio:.2f}%",
                    })

    # High account fees
    if abs(fees['total_account_fees']) > 500:
        flags.append({
            'flag': 'high_account_fees',
            'severity': 'Review',
            'detail': f"Account fees: ${abs(fees['total_account_fees']):.2f}",
        })

    # Dispute fees
    fee_descs = [item['description'].upper() for item in fees['fee_line_items']]
    if any('CHARGEBACK' in d or 'DISPUTE' in d for d in fee_descs):
        flags.append({
            'flag': 'dispute_fees_present',
            'severity': 'Info',
            'detail': 'Dispute/chargeback fees detected in fee detail',
        })

    # International fees
    if any('INTL' in d or 'CROSS BORDER' in d for d in fee_descs):
        flags.append({
            'flag': 'intl_fees_present',
            'severity': 'Info',
            'detail': 'International/cross-border fees detected',
        })

    return flags


# ---------------------------------------------------------------------------
# Effective rates
# ---------------------------------------------------------------------------

def compute_rates(data):
    """Compute effective rates."""
    rates = {}
    total_sub = data['summary']['total_submitted']
    fees = data['fees']

    if total_sub > 0:
        rates['gross_effective_rate'] = float(abs(fees['grand_total_fees']) / total_sub * 100)
        rates['interchange_rate'] = float(abs(fees['total_interchange_program']) / total_sub * 100)
        rates['service_charge_rate'] = float(abs(fees['total_service_charges']) / total_sub * 100)
        rates['fee_rate'] = float(abs(fees['total_fees_bucket']) / total_sub * 100)
    else:
        rates['gross_effective_rate'] = 0.0
        rates['interchange_rate'] = 0.0
        rates['service_charge_rate'] = 0.0
        rates['fee_rate'] = 0.0

    # Per-brand interchange rates
    rates['brand_rates'] = {}
    for bt in data['interchange_detail']['brand_totals']:
        if bt['total_sales'] > 0:
            rates['brand_rates'][bt['brand']] = float(
                abs(bt['total_charges']) / bt['total_sales'] * 100
            )

    return rates


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

def parse_statement(pdf_path):
    """Parse a Fiserv statement PDF and return structured data."""
    pages, full_text = extract_full_text(pdf_path)

    if not is_fiserv_statement(full_text):
        return None

    header = parse_header(full_text, pages)
    summary = parse_summary(full_text)
    card_types, card_type_totals = parse_card_types(full_text)
    chargebacks = parse_chargebacks(full_text)
    adjustments = parse_adjustments(full_text)
    fees = parse_fees(full_text)
    interchange = parse_interchange_detail(full_text)

    data = {
        'header': header,
        'summary': summary,
        'card_types': card_types,
        'card_type_totals': card_type_totals,
        'chargebacks': chargebacks,
        'adjustments': adjustments,
        'fees': fees,
        'interchange_detail': interchange,
    }

    data['rates'] = compute_rates(data)
    data['risk_flags'] = compute_risk_flags(data)
    data['reconciliation'] = run_reconciliation(data)

    return data


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def print_summary(data, filename=""):
    """Print human-readable summary."""
    h = data['header']
    s = data['summary']
    f = data['fees']
    r = data['rates']

    print(f"\n{'='*60}")
    if filename:
        print(f"File: {filename}")
    print(f"Merchant: {h['merchant_name']} (MID {h['merchant_number']})")
    print(f"Period: {h['statement_period']} | Branding: {h['branding']} | Pages: {h['page_count']}")
    print(f"\nSUMMARY:")
    print(f"  Total Submitted:       ${s['total_submitted']:>12,.2f}")
    print(f"  Chargebacks/Reversals: ${s['chargebacks_reversals']:>12,.2f}")
    print(f"  Adjustments:           ${s['adjustments']:>12,.2f}")
    print(f"  Fees:                  ${s['fees']:>12,.2f}")
    print(f"  Total Processed:       ${s['total_processed']:>12,.2f}")

    print(f"\nCARD TYPES:")
    for ct in data['card_types']:
        print(f"  {ct['card_type']:<15} {ct['total_items']:>5} items  ${ct['total_amount']:>12,.2f}")

    print(f"\nFEE BREAKDOWN:")
    print(f"  Transaction Fees:      ${f['total_transaction_fees']:>12,.2f}")
    print(f"  Account Fees:          ${f['total_account_fees']:>12,.2f}")
    print(f"  Grand Total:           ${f['grand_total_fees']:>12,.2f}")
    print(f"\n  THREE-WAY:")
    print(f"  Interchange/Program:   ${f['total_interchange_program']:>12,.2f}")
    print(f"  Service Charges:       ${f['total_service_charges']:>12,.2f}")
    print(f"  Fees Bucket:           ${f['total_fees_bucket']:>12,.2f}")

    print(f"\nEFFECTIVE RATES:")
    print(f"  Gross:       {r['gross_effective_rate']:.2f}%")
    print(f"  Interchange: {r['interchange_rate']:.2f}%")
    print(f"  Service:     {r['service_charge_rate']:.2f}%")
    print(f"  Fee:         {r['fee_rate']:.2f}%")

    if data['risk_flags']:
        print(f"\nRISK FLAGS:")
        for flag in data['risk_flags']:
            print(f"  [{flag['severity']}] {flag['flag']}: {flag['detail']}")

    print(f"\nRECONCILIATION:")
    all_passed = True
    for check in data['reconciliation']:
        status = "PASS" if check['passed'] else "FAIL"
        if not check['passed']:
            all_passed = False
        print(f"  [{status}] {check['check']}: {check['name']}")
        if not check['passed']:
            print(f"         Expected: {check['expected']}, Got: {check['actual']}")

    print(f"\n{'='*60}")
    return all_passed


def print_validate(data, filename=""):
    """Print validation results only."""
    all_passed = True
    checks = data['reconciliation']
    for check in checks:
        status = "PASS" if check['passed'] else "FAIL"
        if not check['passed']:
            all_passed = False
    passed = sum(1 for c in checks if c['passed'])
    total = len(checks)
    tag = "OK" if all_passed else "FAIL"
    print(f"[{tag}] {filename}: {passed}/{total} checks passed")
    if not all_passed:
        for check in checks:
            if not check['passed']:
                print(f"  [{check['check']}] {check['name']}: expected {check['expected']}, got {check['actual']}")
    return all_passed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Parse Fiserv merchant statement PDFs")
    parser.add_argument("path", help="PDF file or directory of PDFs")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--validate", action="store_true", help="Run reconciliation checks only")
    args = parser.parse_args()

    if os.path.isdir(args.path):
        # Batch mode
        pdfs = sorted([f for f in os.listdir(args.path) if f.lower().endswith('.pdf')])
        total_pass = 0
        total_fail = 0
        total_skip = 0
        total_checks = 0
        passed_checks = 0

        for pdf_name in pdfs:
            pdf_path = os.path.join(args.path, pdf_name)
            try:
                data = parse_statement(pdf_path)
            except Exception as e:
                print(f"[SKIP] {pdf_name}: {e}")
                total_skip += 1
                continue

            if data is None:
                print(f"[SKIP] {pdf_name}: not a Fiserv statement")
                total_skip += 1
                continue

            if args.validate:
                ok = print_validate(data, pdf_name)
            elif args.json:
                print(json.dumps({pdf_name: data}, cls=DecimalEncoder, indent=2))
                ok = all(c['passed'] for c in data['reconciliation'])
            else:
                ok = print_summary(data, pdf_name)

            checks = data['reconciliation']
            total_checks += len(checks)
            passed_checks += sum(1 for c in checks if c['passed'])

            if ok:
                total_pass += 1
            else:
                total_fail += 1

        print(f"\n{'='*60}")
        print(f"BATCH RESULTS: {total_pass} passed, {total_fail} failed, {total_skip} skipped")
        print(f"RECONCILIATION: {passed_checks}/{total_checks} checks passed")
        sys.exit(0 if total_fail == 0 else 1)

    else:
        # Single file mode
        data = parse_statement(args.path)
        if data is None:
            print(f"ERROR: {args.path} is not a Fiserv statement")
            sys.exit(1)

        if args.json:
            print(json.dumps(data, cls=DecimalEncoder, indent=2))
        elif args.validate:
            ok = print_validate(data, os.path.basename(args.path))
            sys.exit(0 if ok else 1)
        else:
            ok = print_summary(data, os.path.basename(args.path))
            sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
