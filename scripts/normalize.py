#!/usr/bin/env python3
"""
Statement normalizer.

Takes the processor-specific output of a parse_<processor>.py module and
collapses it into a single, processor-agnostic NormalizedStatement. Every
downstream consumer (quote generator, trend analysis, Supabase) reads this
shape and nothing else.

The four universal fee buckets follow the MSA-46 taxonomy documented in the
msa-processor-knowledge skill:

    interchange        - card network passthrough (cost, not margin)
    network_assessment - Visa/MC/Amex brand assessments and access fees
    processor_markup   - the acquirer/ISO margin (the only lever in a quote)
    account_other      - fixed monthly / compliance / dispute fees

A quote keeps interchange + network_assessment as passthrough (identical in
the proposed column) and competes purely on processor_markup and the fixed
account fees.
"""

from decimal import Decimal


def _f(x):
    """Coerce Decimal/None to float for a clean JSON-friendly dict."""
    if x is None:
        return 0.0
    return float(x)


def normalize_fiserv(data, source_file):
    """Normalize Fiserv / CardPointe / Newtek parse output."""
    h, s, f = data["header"], data["summary"], data["fees"]
    ct = data["card_type_totals"]

    volume = _f(s["total_submitted"])
    txns = ct.get("total_items") or 0

    interchange = abs(_f(f["total_interchange_program"]))
    markup = abs(_f(f["total_service_charges"]))
    account_other = abs(_f(f["total_account_fees"]))
    # The "Fees" bucket spans both per-volume network assessments (inside
    # transaction fees) and the fixed account fees. The assessment portion is
    # whatever is left after removing the account fees.
    network_assessment = abs(_f(f["total_fees_bucket"])) - account_other
    if network_assessment < 0:
        network_assessment = 0.0

    card_mix = [
        {"brand": c["card_type"], "volume": _f(c["total_amount"]), "items": c["total_items"]}
        for c in data["card_types"]
    ]

    return _assemble(
        processor="Fiserv (CardPointe)",
        merchant_name=h.get("merchant_name"),
        mid=h.get("merchant_number"),
        period=h.get("statement_period"),
        volume=volume,
        txns=txns,
        interchange=interchange,
        network_assessment=network_assessment,
        processor_markup=markup,
        account_other=account_other,
        card_mix=card_mix,
        risk_flags=data.get("risk_flags", []),
        reconciliation=data.get("reconciliation", []),
        source_file=source_file,
    )


def normalize_paynuity(data, source_file):
    """Normalize Paynuity (TSYS white-label) parse output."""
    h = data["header"]
    totals = data["plan_summary"]["totals"]
    fc = data["fee_categories"]
    pay = data["payment_summary"]

    volume = _f(totals.get("sales_amount"))
    txns = totals.get("sales_count") or 0

    interchange = _f(fc.get("interchange"))
    network_assessment = _f(fc.get("card_brand"))
    account_other = _f(fc.get("other"))
    # Discount Due is the bundled processor rate; authorization + transaction
    # fee buckets are also processor margin.
    processor_markup = (
        _f(pay.get("discount_due"))
        + _f(fc.get("authorization"))
        + _f(fc.get("transaction"))
    )

    card_mix = [
        {"brand": b["card_brand"], "volume": _f(b["sales_amount"]), "items": b["sales_count"]}
        for b in data["plan_summary"].get("brands", [])
    ]

    recon = [
        {"check": c[0], "passed": c[1]} for c in data.get("reconciliation", [])
    ]
    flags = [
        {"flag": fl[0], "severity": fl[1], "detail": fl[2]}
        for fl in data.get("risk_flags", [])
    ]

    return _assemble(
        processor="Paynuity",
        merchant_name=h.get("merchant_name"),
        mid=h.get("merchant_number"),
        period=h.get("statement_date"),
        volume=volume,
        txns=txns,
        interchange=interchange,
        network_assessment=network_assessment,
        processor_markup=processor_markup,
        account_other=account_other,
        card_mix=card_mix,
        risk_flags=flags,
        reconciliation=recon,
        source_file=source_file,
    )


def _assemble(**kw):
    total_fees = (
        kw["interchange"]
        + kw["network_assessment"]
        + kw["processor_markup"]
        + kw["account_other"]
    )
    volume = kw["volume"]
    txns = kw["txns"] or 0
    eff_rate = (total_fees / volume) if volume else 0.0
    passthrough = kw["interchange"] + kw["network_assessment"]

    return {
        "processor": kw["processor"],
        "merchant_name": kw["merchant_name"],
        "mid": kw["mid"],
        "period": kw["period"],
        "source_file": kw["source_file"],
        "volume": round(volume, 2),
        "transactions": txns,
        "avg_ticket": round(volume / txns, 2) if txns else 0.0,
        "fees": {
            "interchange": round(kw["interchange"], 2),
            "network_assessment": round(kw["network_assessment"], 2),
            "processor_markup": round(kw["processor_markup"], 2),
            "account_other": round(kw["account_other"], 2),
            "total": round(total_fees, 2),
            "passthrough": round(passthrough, 2),
        },
        # Rates kept at full precision so rate x volume reproduces the dollar
        # figure to the penny (the reference template stores rates the same way).
        "rates": {
            "effective": eff_rate,
            "interchange": (kw["interchange"] / volume) if volume else 0.0,
            "network_assessment": (kw["network_assessment"] / volume) if volume else 0.0,
            "processor_markup": (kw["processor_markup"] / volume) if volume else 0.0,
        },
        "card_mix": kw["card_mix"],
        "risk_flags": kw["risk_flags"],
        "reconciliation": {
            "checks": len(kw["reconciliation"]),
            "passed": sum(1 for c in kw["reconciliation"] if (c.get("passed") if isinstance(c, dict) else c[1])),
            "all_passed": all((c.get("passed") if isinstance(c, dict) else c[1]) for c in kw["reconciliation"]) if kw["reconciliation"] else False,
        },
    }
