#!/usr/bin/env python3
"""
Paynuity Statement Parser
Extracts structured data from Paynuity merchant statement PDFs using pdfplumber.

Usage:
    python parse_paynuity.py <pdf_path>              # Human-readable output
    python parse_paynuity.py <pdf_path> --json        # JSON output
    python parse_paynuity.py <pdf_path> --validate    # Run reconciliation checks only
"""

import argparse
import json
import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber required. Install with: pip install pdfplumber", file=sys.stderr)
    sys.exit(1)


def parse_amount(s):
    """Parse a dollar amount string, handling commas, leading $, negatives, and bare decimals."""
    if s is None:
        return Decimal("0")
    s = s.strip().replace("$", "").replace(",", "")
    if not s or s == "-":
        return Decimal("0")
    # Handle negative with trailing or leading minus
    neg = False
    if s.startswith("-") or s.startswith("("):
        neg = True
        s = s.strip("-").strip("(").strip(")")
    if s.endswith("-"):
        neg = True
        s = s.rstrip("-")
    if not s:
        return Decimal("0")
    # Handle bare decimal like ".30"
    if s.startswith("."):
        s = "0" + s
    try:
        val = Decimal(s)
    except Exception:
        return Decimal("0")
    return -val if neg else val


def extract_full_text(pdf_path):
    """Extract text from all pages."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return pages


def parse_header(page1_text):
    """Parse header info from page 1."""
    result = {}

    # Statement date
    m = re.search(r"for\s*([A-Za-z]+)\s*(\d{1,2})\s*,\s*(\d{4})", page1_text)
    if m:
        result["statement_date"] = f"{m.group(1)} {m.group(2)}, {m.group(3)}"

    # Page count
    m = re.search(r"Page\s*1\s*of\s*(\d+)", page1_text)
    if m:
        result["page_count"] = int(m.group(1))

    # Merchant number
    m = re.search(r"MerchantNumber\s*(\d+)", page1_text)
    if m:
        result["merchant_number"] = m.group(1)

    # Association number
    m = re.search(r"AssociationNumber\s*(\d+)", page1_text)
    if m:
        result["association_number"] = m.group(1)

    # Merchant name: line(s) before MerchantNumber on page 1
    # It's the first non-Paynuity-address line after the header
    lines = page1_text.split("\n")
    for i, line in enumerate(lines):
        if "MerchantNumber" in line.replace(" ", ""):
            # Merchant name is the text before "MerchantNumber" on same line,
            # or the line above if MerchantNumber starts the line
            parts = re.split(r"MerchantNumber", line.replace(" ", ""))
            name_part = parts[0].strip() if parts[0].strip() else ""
            if not name_part and i > 0:
                # Check previous lines for merchant name (skip address/header lines)
                for j in range(i - 1, max(i - 4, -1), -1):
                    candidate = lines[j].strip()
                    if candidate and "Page" not in candidate and "Orlando" not in candidate and "Suite" not in candidate and "OrangeAve" not in candidate.replace(" ", ""):
                        name_part = candidate
                        break
            # Re-extract with spaces from original
            if name_part:
                # Try to get the original spaced version
                orig_match = re.search(r"^(.+?)\s*MerchantNumber", line)
                if orig_match and orig_match.group(1).strip():
                    result["merchant_name"] = orig_match.group(1).strip()
                else:
                    result["merchant_name"] = name_part
            break

    # If merchant_name not found from MerchantNumber line, try line-based approach
    if "merchant_name" not in result:
        for i, line in enumerate(lines):
            if "MerchantNumber" in line:
                # Look at previous non-empty lines
                for j in range(i - 1, -1, -1):
                    candidate = lines[j].strip()
                    if candidate and not any(x in candidate for x in ["OrangeAve", "Suite", "Orlando", "MERCHANT STATEMENT", "Page"]):
                        result["merchant_name"] = candidate
                        break
                break

    return result


def parse_payment_summary(page1_text):
    """Parse the PAYMENT SUMMARY section."""
    result = {}
    # Work on original text with spaces to find dollar amounts
    # The lines look like: "DiscountDue $2,524.59" or "DiscountDue $0.00"
    lines = page1_text.split("\n")
    all_nospace = page1_text.replace(" ", "")

    # Match with or without $, handle bare decimals
    AMT = r"\$?\s*(-?\.?\d[\d,]*\.?\d*)"

    m = re.search(rf"DiscountDue\s*{AMT}", all_nospace)
    if m:
        result["discount_due"] = parse_amount(m.group(1))

    # FeesDue can have trailing text ("or yourprocessing...")
    m = re.search(rf"FeesDue\s*{AMT}", all_nospace)
    if m:
        result["fees_due"] = parse_amount(m.group(1))

    m = re.search(rf"Totalamounttobededucted\s*{AMT}", all_nospace)
    if m:
        result["total_deducted"] = parse_amount(m.group(1))

    return result


def parse_plan_summary(page1_text):
    """Parse the PLAN SUMMARY card brand table."""
    brands = []
    totals = {}

    lines = page1_text.split("\n")
    in_plan = False
    header_seen = False

    # Known card brand prefixes (no spaces in extracted text)
    brand_patterns = [
        "Visa", "MasterCard", "Discover", "Amex", "AmericanExpress",
        "JCB", "DinersClub", "Debit", "EBT"
    ]

    for line in lines:
        stripped = line.strip()
        if "PLAN SUMMARY" in stripped:
            in_plan = True
            continue
        if in_plan and ("SALES" in stripped and "CREDITS" in stripped):
            header_seen = True
            continue
        if in_plan and "Number" in stripped and "Amount" in stripped:
            continue

        if in_plan and header_seen:
            # Check for TOTALS line
            if stripped.startswith("TOTALS"):
                nums = re.findall(r"[\d,]+\.?\d*", stripped)
                if len(nums) >= 6:
                    totals = {
                        "sales_count": int(nums[0].replace(",", "")),
                        "sales_amount": parse_amount(nums[1]),
                        "credits_count": int(nums[2].replace(",", "")),
                        "credits_amount": parse_amount(nums[3]),
                        "net_sales": parse_amount(nums[4]),
                        "discounts": parse_amount(nums[5]),
                    }
                elif len(nums) >= 4:
                    # Zero-activity: TOTALS 0 $0.00 0 $0.00 $0.00 $0.00
                    totals = {
                        "sales_count": int(nums[0].replace(",", "")),
                        "sales_amount": parse_amount(nums[1]),
                        "credits_count": int(nums[2].replace(",", "")),
                        "credits_amount": parse_amount(nums[3]),
                        "net_sales": parse_amount(nums[4]) if len(nums) > 4 else Decimal("0"),
                        "discounts": parse_amount(nums[5]) if len(nums) > 5 else Decimal("0"),
                    }
                in_plan = False
                continue

            # Try to parse a card brand line
            # Format: <BrandName> <SalesCount> $<SalesAmt> <CreditsCount> $<CreditsAmt> $<NetSales> $<Discounts>
            # Brand names: Visa, VisaDebit, VisaBusiness, MasterCard, MasterCardDebit, MasterCardBusiness
            # Amounts can be bare decimals (.00) or negative (-$299.98)
            A = r"-?\$?\.?\d[\d,]*\.?\d*"
            m = re.match(
                rf"^([A-Za-z]+(?:\s*[A-Za-z]*)*?)\s+"
                rf"([\d,]+)\s+({A})\s+"
                rf"(\d+)\s+({A})\s+"
                rf"({A})\s+({A})",
                stripped,
            )
            if m:
                brand = {
                    "card_brand": m.group(1).strip(),
                    "sales_count": int(m.group(2).replace(",", "")),
                    "sales_amount": parse_amount(m.group(3)),
                    "credits_count": int(m.group(4).replace(",", "")),
                    "credits_amount": parse_amount(m.group(5)),
                    "net_sales": parse_amount(m.group(6)),
                    "discounts": parse_amount(m.group(7)),
                }
                brands.append(brand)
                continue

            # Check if we've left the plan summary (hit pie chart percentages or footer)
            if "%" in stripped and not any(p in stripped for p in ["SALES", "CREDITS"]):
                continue  # Skip pie chart percentage lines
            if "©" in stripped or "Paynuity" in stripped:
                in_plan = False

    return {"brands": brands, "totals": totals}


def parse_deposits(all_text):
    """Parse DEPOSITS section and return totals."""
    result = {}
    m = re.search(
        r"DEPOSITTOTALS\s+([\d,]+)\s+([\d,]+\.?\d+)\s+([\d,]+\.?\d+)\s+([\d,]+\.?\d+)\s+(-?[\d,]+\.?\d+)",
        all_text,
    )
    if m:
        result = {
            "deposit_count": int(m.group(1).replace(",", "")),
            "deposit_sales": parse_amount(m.group(2)),
            "deposit_credits": parse_amount(m.group(3)),
            "deposit_fees_paid": parse_amount(m.group(4)),
            "deposit_net": parse_amount(m.group(5)),
        }
    return result


def parse_chargebacks(all_text):
    """Parse CHARGEBACKS section."""
    result = {}
    m = re.search(
        r"CHARGEBACKTOTALS\s+([\d,]+)\s+([\d,]+\.?\d+)\s+([\d,]+\.?\d+)\s+([\d,]+\.?\d+)\s+(-?[\d,]+\.?\d+)",
        all_text,
    )
    if m:
        result = {
            "chargeback_count": int(m.group(1).replace(",", "")),
            "chargeback_amount": parse_amount(m.group(2)),
            "chargeback_credits": parse_amount(m.group(3)),
            "chargeback_fees": parse_amount(m.group(4)),
            "chargeback_net": parse_amount(m.group(5)),
        }

    # Count chargeback reversals (B transaction code)
    reversal_count = len(re.findall(r"\d+\s+\d+\s+B\s+T\s+", all_text))
    result["chargeback_reversals"] = reversal_count

    return result


def parse_reserve(all_text):
    """Parse RESERVE FUNDING - SUMMARY."""
    result = {}
    # Look for TOTALS line after RESERVE FUNDING
    m = re.search(
        r"RESERVE FUNDING.*?TOTALS\s+([\d,]+\.?\d+)\s+([\d,]+\.?\d+)\s+([\d,]+\.?\d+)",
        all_text,
        re.DOTALL,
    )
    if m:
        result = {
            "reserve_amount": parse_amount(m.group(1)),
            "reserve_release": parse_amount(m.group(2)),
            "reserve_balance": parse_amount(m.group(3)),
        }
    return result


def parse_fees(all_text):
    """Parse the FEES section with all subcategories."""
    fee_categories = {}
    fee_line_items = []

    # Category markers and their regex patterns
    # Use \.?\d+ to handle bare decimals like .30
    AMT = r"\.?\d[\d,]*\.?\d*"
    categories = {
        "interchange": (r"^INTERCHANGE\b", rf"TOTALINTERCHANGEFEES\s*({AMT})"),
        "authorization": (r"^AUTHORIZATION\b", rf"TOTALAUTHORIZATIONFEES\s*({AMT})"),
        "transaction": (r"^TRANSACTION\b", rf"TOTALTRANSACTIONFEES\s*({AMT})"),
        "card_brand": (r"^CARDBRAND\b", rf"TOTALCARDBRANDFEES\s*({AMT})"),
        "other": (r"^OTHER\b", rf"TOTALOTHERFEES\s*({AMT})"),
    }

    # Find each category subtotal
    # We work on the no-space version for reliable matching
    nospace = all_text.replace(" ", "")
    for cat_name, (_, total_pattern) in categories.items():
        m = re.search(total_pattern, nospace)
        if m:
            fee_categories[cat_name] = parse_amount(m.group(1))

    # Get total fees
    m = re.search(rf"TOTALFEES\s*({AMT})", nospace)
    if m:
        fee_categories["total_fees"] = parse_amount(m.group(1))

    # Parse individual fee line items
    lines = all_text.split("\n")
    current_category = None
    in_fees = False

    for line in lines:
        stripped = line.strip()

        if stripped == "FEES" or stripped.startswith("FEES"):
            if "continued" not in stripped.lower() and "paid" not in stripped.lower():
                in_fees = True
            elif "continued" in stripped.lower():
                in_fees = True
            continue

        if not in_fees:
            continue

        # Detect category headers
        upper = stripped.upper().replace(" ", "")
        if upper == "INTERCHANGE":
            current_category = "interchange"
            continue
        elif upper == "AUTHORIZATION":
            current_category = "authorization"
            continue
        elif upper == "TRANSACTION":
            current_category = "transaction"
            continue
        elif upper == "CARDBRAND":
            current_category = "card_brand"
            continue
        elif upper == "OTHER":
            current_category = "other"
            continue

        # Skip total lines and headers
        if upper.startswith("TOTAL") or upper.startswith("COUNT") or upper.startswith("PLANCODES"):
            if upper.startswith("TOTALFEES"):
                in_fees = False
            continue

        if not current_category:
            continue

        # Amount pattern: handles bare decimals (.30) and normal (114.39)
        A = r"\.?\d[\d,]*\.?\d*"

        # Parse fee line items
        # Pattern 1: COUNT VOLUME DESCRIPTION AMOUNT
        m = re.match(
            rf"^(\d[\d,]*)\s+({A})\s+([A-Za-z][\w]+(?:\s+[\w]+)*?)\s+({A})$",
            stripped,
        )
        if m:
            fee_line_items.append({
                "category": current_category,
                "count": int(m.group(1).replace(",", "")),
                "volume": parse_amount(m.group(2)),
                "description": m.group(3).strip(),
                "amount": parse_amount(m.group(4)),
            })
            continue

        # Pattern 2: VOLUME DESCRIPTION AMOUNT (no count)
        m = re.match(
            rf"^({A})\s+([A-Za-z][\w]+(?:\s+[\w]+)*?)\s+({A})$",
            stripped,
        )
        if m:
            fee_line_items.append({
                "category": current_category,
                "count": None,
                "volume": parse_amount(m.group(1)),
                "description": m.group(2).strip(),
                "amount": parse_amount(m.group(3)),
            })
            continue

        # Pattern 3: DESCRIPTION AMOUNT (no count, no volume)
        m = re.match(
            rf"^([A-Za-z][\w]+(?:\s+[\w]+)*?)\s+({A})$",
            stripped,
        )
        if m:
            fee_line_items.append({
                "category": current_category,
                "count": None,
                "volume": None,
                "description": m.group(1).strip(),
                "amount": parse_amount(m.group(2)),
            })
            continue

        # Pattern 4: COUNT DESCRIPTION AMOUNT (e.g., "02 BatchFee 2.00")
        m = re.match(
            rf"^(\d[\d,]*)\s+([A-Za-z][\w]+(?:\s+[\w]+)*?)\s+({A})$",
            stripped,
        )
        if m:
            fee_line_items.append({
                "category": current_category,
                "count": int(m.group(1).replace(",", "")),
                "volume": None,
                "description": m.group(2).strip(),
                "amount": parse_amount(m.group(3)),
            })
            continue

    return fee_categories, fee_line_items


def parse_settlement(all_text):
    """Parse the settlement reconciliation on the last page."""
    result = {}
    nospace = all_text.replace(" ", "")

    # Amount pattern handles bare decimals (.00, .36) and negatives (-.01)
    AMT = r"-?\.?\d[\d,]*\.?\d*"
    # Use (?<![A-Za-z]) lookbehind to prevent substring matches
    # (e.g., "NetFeesDue" matching the "FeesDue" pattern)
    LB = r"(?<![A-Za-z])"
    fields = {
        "min_discount_due": rf"{LB}MinimumDiscountDue\s*({AMT})",
        "discount_paid": rf"{LB}DiscountPaid\s*({AMT})",
        "net_discount_due": rf"{LB}NetDiscountDue\s*({AMT})",
        "fees_due_settlement": rf"{LB}FeesDue\s*({AMT})",
        "fees_paid": rf"{LB}FeesPaid\s*({AMT})",
        "net_fees_due": rf"{LB}NetFeesDue\s*({AMT})",
        "amount_deducted": rf"{LB}AmountDeducted\s*({AMT})",
    }

    for field_name, pattern in fields.items():
        # Search from end of text backwards (settlement is on last page)
        matches = list(re.finditer(pattern, nospace))
        if matches:
            result[field_name] = parse_amount(matches[-1].group(1))

    return result


def run_reconciliation(data):
    """Run all reconciliation checks. Returns list of (name, passed, expected, actual, message)."""
    checks = []
    tolerance = Decimal("0.02")

    plan = data.get("plan_summary", {})
    totals = plan.get("totals", {})
    payment = data.get("payment_summary", {})
    fees = data.get("fee_categories", {})
    settlement = data.get("settlement", {})

    # R1: Discount Due = Sum of Plan Summary Discounts
    if totals and "discount_due" in payment:
        expected = payment["discount_due"]
        actual = totals.get("discounts", Decimal("0"))
        passed = abs(expected - actual) <= tolerance
        # Paynuity quirk: zero-activity accounts can have a minimum discount fee
        # where DiscountDue > 0 but Plan Summary discounts = 0
        if not passed and totals.get("sales_amount", Decimal("0")) == Decimal("0") and actual == Decimal("0"):
            checks.append(("R1: DiscountDue (minimum fee on zero-activity account)", True,
                           expected, actual, f"Minimum discount fee: ${expected}"))
        else:
            checks.append(("R1: DiscountDue == Plan Summary DISCOUNTS total", passed, expected, actual,
                           "" if passed else f"Off by ${abs(expected - actual)}"))

    # R2: Net Sales = Sales - Credits (per brand)
    for brand in plan.get("brands", []):
        expected_net = brand["sales_amount"] - brand["credits_amount"]
        actual_net = brand["net_sales"]
        passed = abs(expected_net - actual_net) <= tolerance
        checks.append((f"R2: {brand['card_brand']} NetSales == Sales - Credits", passed,
                       expected_net, actual_net, "" if passed else f"Off by ${abs(expected_net - actual_net)}"))

    # R3: TOTALS = Sum of brands
    brands = plan.get("brands", [])
    if brands and totals:
        for field in ["sales_count", "sales_amount", "credits_count", "credits_amount", "net_sales", "discounts"]:
            expected = totals.get(field, Decimal("0"))
            actual = sum(b.get(field, Decimal("0")) if not isinstance(b.get(field, 0), int) else Decimal(str(b.get(field, 0))) for b in brands)
            if isinstance(expected, int):
                expected = Decimal(str(expected))
            passed = abs(expected - actual) <= tolerance
            checks.append((f"R3: TOTALS.{field} == sum(brands)", passed, expected, actual,
                           "" if passed else f"Off by {abs(expected - actual)}"))

    # R4: Total Fees = Sum of category subtotals
    if "total_fees" in fees:
        cat_sum = Decimal("0")
        for cat in ["interchange", "authorization", "transaction", "card_brand", "other"]:
            cat_sum += fees.get(cat, Decimal("0"))
        expected = fees["total_fees"]
        passed = abs(expected - cat_sum) <= tolerance
        checks.append(("R4: TotalFees == sum(category subtotals)", passed, expected, cat_sum,
                       "" if passed else f"Off by ${abs(expected - cat_sum)}"))

    # R5: Fees Due == Total Fees
    if "fees_due" in payment and "total_fees" in fees:
        expected = payment["fees_due"]
        actual = fees["total_fees"]
        passed = abs(expected - actual) <= tolerance
        checks.append(("R5: FeesDue == TotalFees", passed, expected, actual,
                       "" if passed else f"Off by ${abs(expected - actual)}"))

    # R6: Settlement math
    if "min_discount_due" in settlement and "discount_paid" in settlement:
        expected_net = settlement["min_discount_due"] - settlement["discount_paid"]
        actual_net = settlement.get("net_discount_due", Decimal("0"))
        passed = abs(expected_net - actual_net) <= tolerance
        checks.append(("R6a: NetDiscountDue == MinDiscountDue - DiscountPaid", passed,
                       expected_net, actual_net, "" if passed else f"Off by ${abs(expected_net - actual_net)}"))

    if "fees_due_settlement" in settlement and "fees_paid" in settlement:
        expected_net = settlement["fees_due_settlement"] - settlement["fees_paid"]
        actual_net = settlement.get("net_fees_due", Decimal("0"))
        passed = abs(expected_net - actual_net) <= tolerance
        # Paynuity quirk: when FeesPaid=0, NetFeesDue=0 and fees collected via AmountDeducted
        if not passed and settlement.get("fees_paid", Decimal("0")) == Decimal("0"):
            # Check alternative: AmountDeducted = NetDiscountDue + FeesDue
            amt_deducted = settlement.get("amount_deducted", Decimal("0"))
            net_disc = settlement.get("net_discount_due", Decimal("0"))
            fees_due_s = settlement.get("fees_due_settlement", Decimal("0"))
            alt_expected = net_disc + fees_due_s
            alt_passed = abs(amt_deducted - alt_expected) <= tolerance
            if alt_passed:
                passed = True
                checks.append(("R6b: NetFeesDue (Paynuity direct-deduct pattern: AmountDeducted == NetDiscountDue + FeesDue)", passed,
                               alt_expected, amt_deducted, ""))
            else:
                checks.append(("R6b: NetFeesDue == FeesDue - FeesPaid", passed,
                               expected_net, actual_net, f"Off by ${abs(expected_net - actual_net)}"))
        else:
            checks.append(("R6b: NetFeesDue == FeesDue - FeesPaid", passed,
                           expected_net, actual_net, "" if passed else f"Off by ${abs(expected_net - actual_net)}"))

    # R7: Deposit totals cross-check
    deposits = data.get("deposits", {})
    if deposits and totals:
        if "deposit_sales" in deposits and "sales_amount" in totals:
            expected = totals["sales_amount"]
            actual = deposits["deposit_sales"]
            passed = abs(expected - actual) <= tolerance
            checks.append(("R7a: DepositTotals.sales == PlanSummary.sales", passed,
                           expected, actual, "" if passed else f"Off by ${abs(expected - actual)}"))
        if "deposit_count" in deposits and "sales_count" in totals:
            expected = Decimal(str(totals["sales_count"]))
            actual = Decimal(str(deposits["deposit_count"]))
            passed = expected == actual
            checks.append(("R7b: DepositTotals.count == PlanSummary.count", passed,
                           expected, actual, "" if passed else f"Off by {abs(expected - actual)}"))

    return checks


def compute_risk_flags(data):
    """Compute risk flags based on extracted data."""
    flags = []
    payment = data.get("payment_summary", {})
    plan_totals = data.get("plan_summary", {}).get("totals", {})
    chargebacks = data.get("chargebacks", {})
    reserve = data.get("reserve", {})
    fees = data.get("fee_categories", {})

    sales = plan_totals.get("sales_amount", Decimal("0"))
    sales_count = plan_totals.get("sales_count", 0)
    discount = payment.get("discount_due", Decimal("0"))
    fees_due = payment.get("fees_due", Decimal("0"))

    # Effective rate
    if sales > 0:
        gross_rate = (discount + fees_due) / sales * 100
        if gross_rate > 5:
            flags.append(("high_effective_rate", "WARNING", f"Gross effective rate: {gross_rate:.2f}%"))

    # Chargebacks
    cb_count = chargebacks.get("chargeback_count", 0)
    cb_amount = chargebacks.get("chargeback_amount", Decimal("0"))
    if sales_count and isinstance(sales_count, int) and sales_count > 0:
        cb_ratio = cb_count / sales_count * 100
        if cb_ratio > 1.0:
            flags.append(("excessive_chargebacks", "CRITICAL", f"Chargeback ratio: {cb_ratio:.2f}% ({cb_count}/{sales_count})"))
    if sales > 0 and cb_amount > 0:
        cb_dollar = cb_amount / sales * 100
        if cb_dollar > 1.5:
            flags.append(("chargeback_dollar_ratio", "CRITICAL", f"Chargeback $ ratio: {cb_dollar:.2f}%"))

    # Reserve
    if reserve.get("reserve_balance", Decimal("0")) > 0:
        flags.append(("reserve_held", "INFO", f"Reserve balance: ${reserve['reserve_balance']}"))
        if reserve.get("reserve_amount", Decimal("0")) > reserve.get("reserve_release", Decimal("0")):
            flags.append(("reserve_growing", "WARNING", "Reserve is growing (deposits > releases)"))

    # Zero activity with fees
    if sales == 0 and fees_due > 0:
        flags.append(("zero_activity_fees", "INFO", f"No sales but ${fees_due} in fees charged"))

    # Other/misc fees
    if fees.get("other", Decimal("0")) > 0:
        flags.append(("misc_charges_present", "REVIEW", f"Other/misc fees: ${fees['other']}"))

    # High credit ratio
    credits = plan_totals.get("credits_amount", Decimal("0"))
    if sales > 0 and credits > 0:
        credit_ratio = credits / sales * 100
        if credit_ratio > 10:
            flags.append(("high_credit_ratio", "WARNING", f"Credit ratio: {credit_ratio:.2f}%"))

    return flags


def parse_statement(pdf_path):
    """Main entry point: parse a Paynuity statement PDF."""
    pages = extract_full_text(pdf_path)
    if not pages:
        return {"error": "No pages extracted"}

    page1 = pages[0]
    all_text = "\n".join(pages)

    # Verify this is a Paynuity statement
    if "paynuity" not in all_text.lower() and "MERCHANT STATEMENT" not in all_text:
        return {"error": "Not a Paynuity statement"}

    data = {
        "source_file": os.path.basename(pdf_path),
        "header": parse_header(page1),
        "payment_summary": parse_payment_summary(page1),
        "plan_summary": parse_plan_summary(page1),
        "deposits": parse_deposits(all_text),
        "chargebacks": parse_chargebacks(all_text),
        "reserve": parse_reserve(all_text),
        "settlement": parse_settlement(all_text),
    }

    # Parse fees
    fee_categories, fee_line_items = parse_fees(all_text)
    data["fee_categories"] = fee_categories
    data["fee_line_items"] = fee_line_items

    # Compute effective rates
    sales = data["plan_summary"]["totals"].get("sales_amount", Decimal("0"))
    net_sales = data["plan_summary"]["totals"].get("net_sales", Decimal("0"))
    discount = data["payment_summary"].get("discount_due", Decimal("0"))
    fees_due = data["payment_summary"].get("fees_due", Decimal("0"))
    total_cost = discount + fees_due

    if sales > 0:
        data["gross_effective_rate"] = float((total_cost / sales * 100).quantize(Decimal("0.01"), ROUND_HALF_UP))
    else:
        data["gross_effective_rate"] = 0.0

    if net_sales > 0:
        data["net_effective_rate"] = float((total_cost / net_sales * 100).quantize(Decimal("0.01"), ROUND_HALF_UP))
    else:
        data["net_effective_rate"] = 0.0

    # Run reconciliation
    data["reconciliation"] = run_reconciliation(data)

    # Risk flags
    data["risk_flags"] = compute_risk_flags(data)

    return data


def decimal_serializer(obj):
    """JSON serializer for Decimal objects."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def print_human_readable(data):
    """Print a human-readable summary."""
    h = data.get("header", {})
    ps = data.get("payment_summary", {})
    plan = data.get("plan_summary", {})
    totals = plan.get("totals", {})
    fees = data.get("fee_categories", {})
    settlement = data.get("settlement", {})
    chargebacks = data.get("chargebacks", {})
    reserve = data.get("reserve", {})

    print(f"\n{'='*60}")
    print(f"PAYNUITY STATEMENT: {data.get('source_file', '?')}")
    print(f"{'='*60}")
    print(f"Merchant:     {h.get('merchant_name', '?')}")
    print(f"MID:          {h.get('merchant_number', '?')}")
    print(f"Date:         {h.get('statement_date', '?')}")
    print(f"Pages:        {h.get('page_count', '?')}")

    print(f"\n--- PAYMENT SUMMARY ---")
    print(f"Discount Due:   ${ps.get('discount_due', 0):>12,.2f}")
    print(f"Fees Due:       ${ps.get('fees_due', 0):>12,.2f}")
    print(f"Total Deducted: ${ps.get('total_deducted', 0):>12,.2f}")

    print(f"\n--- PLAN SUMMARY ---")
    for brand in plan.get("brands", []):
        print(f"  {brand['card_brand']:<22} Sales: {brand['sales_count']:>6} ${brand['sales_amount']:>12,.2f}  "
              f"Credits: {brand['credits_count']:>4} ${brand['credits_amount']:>10,.2f}  "
              f"Net: ${brand['net_sales']:>12,.2f}  Disc: ${brand['discounts']:>10,.2f}")
    if totals:
        print(f"  {'TOTALS':<22} Sales: {totals['sales_count']:>6} ${totals['sales_amount']:>12,.2f}  "
              f"Credits: {totals['credits_count']:>4} ${totals['credits_amount']:>10,.2f}  "
              f"Net: ${totals['net_sales']:>12,.2f}  Disc: ${totals['discounts']:>10,.2f}")

    print(f"\n--- FEE BREAKDOWN ---")
    for cat in ["interchange", "authorization", "transaction", "card_brand", "other"]:
        if cat in fees:
            print(f"  {cat.replace('_', ' ').title():<20} ${fees[cat]:>12,.2f}")
    if "total_fees" in fees:
        print(f"  {'Total Fees':<20} ${fees['total_fees']:>12,.2f}")

    print(f"\n--- EFFECTIVE RATES ---")
    print(f"  Gross: {data.get('gross_effective_rate', 0):.2f}%  (on ${totals.get('sales_amount', 0):,.2f} gross sales)")
    print(f"  Net:   {data.get('net_effective_rate', 0):.2f}%  (on ${totals.get('net_sales', 0):,.2f} net sales)")

    if chargebacks:
        print(f"\n--- CHARGEBACKS ---")
        print(f"  Count:     {chargebacks.get('chargeback_count', 0)}")
        print(f"  Amount:    ${chargebacks.get('chargeback_amount', 0):,.2f}")
        print(f"  Reversals: {chargebacks.get('chargeback_reversals', 0)}")

    if reserve:
        print(f"\n--- RESERVE ---")
        print(f"  Reserved:  ${reserve.get('reserve_amount', 0):>12,.2f}")
        print(f"  Released:  ${reserve.get('reserve_release', 0):>12,.2f}")
        print(f"  Balance:   ${reserve.get('reserve_balance', 0):>12,.2f}")

    print(f"\n--- SETTLEMENT ---")
    for field, label in [
        ("min_discount_due", "Min Discount Due"),
        ("discount_paid", "Discount Paid"),
        ("net_discount_due", "Net Discount Due"),
        ("fees_due_settlement", "Fees Due"),
        ("fees_paid", "Fees Paid"),
        ("net_fees_due", "Net Fees Due"),
        ("amount_deducted", "Amount Deducted"),
    ]:
        if field in settlement:
            print(f"  {label:<20} ${settlement[field]:>12,.2f}")

    # Reconciliation
    checks = data.get("reconciliation", [])
    print(f"\n--- RECONCILIATION ({sum(1 for c in checks if c[1])}/{len(checks)} passed) ---")
    for name, passed, expected, actual, msg in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            print(f"         Expected: {expected}, Got: {actual}  {msg}")

    # Risk flags
    flags = data.get("risk_flags", [])
    if flags:
        print(f"\n--- RISK FLAGS ---")
        for flag_name, severity, message in flags:
            print(f"  [{severity}] {flag_name}: {message}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Parse Paynuity merchant statement PDFs")
    parser.add_argument("pdf_path", help="Path to the Paynuity statement PDF")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--validate", action="store_true", help="Only run reconciliation checks")
    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"ERROR: File not found: {args.pdf_path}", file=sys.stderr)
        sys.exit(1)

    data = parse_statement(args.pdf_path)

    if "error" in data:
        print(f"ERROR: {data['error']}", file=sys.stderr)
        sys.exit(1)

    if args.validate:
        checks = data.get("reconciliation", [])
        passed = sum(1 for c in checks if c[1])
        total = len(checks)
        print(f"Reconciliation: {passed}/{total} passed")
        for name, ok, expected, actual, msg in checks:
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}] {name}")
            if not ok:
                print(f"         Expected: {expected}, Got: {actual}  {msg}")
        sys.exit(0 if passed == total else 1)

    if args.json:
        # Convert for JSON serialization
        output = json.loads(json.dumps(data, default=decimal_serializer))
        # Clean up reconciliation for JSON
        if "reconciliation" in output:
            output["reconciliation"] = [
                {"check": c[0], "passed": c[1], "expected": c[2], "actual": c[3], "message": c[4]}
                for c in data["reconciliation"]
            ]
        print(json.dumps(output, indent=2))
    else:
        print_human_readable(data)


if __name__ == "__main__":
    main()
