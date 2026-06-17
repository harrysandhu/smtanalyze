---
name: msa-processor-knowledge
description: "Merchant Statement Analysis (MSA) processor identification and fee analysis knowledge base. Use this skill whenever the user asks to read, analyze, or review merchant processing statements (.pdf), identify which processor a statement came from, perform rate/fee analysis, compare against manual reviews, or produce Gratify-branded rate review documents. Also trigger when the user mentions MSA, interchange analysis, processor markup, statement review, rate comparison, or fee audit. Read the relevant processor reference file after identifying the processor from the statement format."
---

# MSA Processor Knowledge Base

This skill contains accumulated knowledge about how to identify processors from statement formats, parse their fee structures, and avoid common pitfalls. It also contains the Gratify analysis document template spec.

## Workflow

1. **Ingest the statement** — Use pdfplumber for text extraction. If zero text layer (scanned/photographed), render pages to PNG at 300 DPI via `pdfplumber` `to_image()`, then OCR with `pytesseract --psm 6`. Verify OCR output against the image using Claude's multimodal vision.
2. **Identify the processor** — Use the identification markers below to determine which processor issued the statement. Then read the relevant reference file from `references/` for detailed parsing guidance.
3. **Extract data** — Pull all volume, transaction counts, interchange detail, fees, assessments, and processor markup. Separate interchange passthrough from processor markup from card brand assessments.
4. **Analyze** — Calculate effective rates, identify downgrades, check debit/credit split economics, flag hidden fees.
5. **Cross-validate** — If a manual analysis is available, compare every anchor number. Discrepancies reveal either OCR errors or analytical misses.
6. **Produce report** — Generate a Gratify-branded Word document. See the Document Template section below.

## Processor Identification Quick Reference

### Understanding the TSYS Platform Family

Many processors and banks run on the **TSYS platform** and produce statements with nearly identical layouts. The telltale signs of a TSYS-platform statement are:
- **"Plan Summary"** section with plan codes (VS, VD, VB, MC, MD, MB, DS, DD, AM, etc.)
- **Deposits** section with reference numbers and settlement detail
- **Fees** section with authorization fees, interchange fees, and miscellaneous fees
- Plan codes split by card type AND product (VS=Visa Credit, VD=Visa Debit, VB=Visa Business, MC=Mastercard Credit, MD=MC Debit, MB=MC Business)

The branding on the statement tells you the ISO/bank, but the underlying platform is TSYS. This matters because parsing logic is largely the same across all TSYS-platform processors — only the branding and MID format differ.

### Identification Table

Pricing model is deliberately excluded from this table. Any processor can offer IC+, flat, or tiered to different merchants — determine pricing model per-statement using the Pricing Model Detection section below.

| Processor | Platform | Key Markers | MID Format | Currency |
|-----------|----------|-------------|------------|----------|
| **TSYS / Global Payments** | TSYS | "Merchant Services" branding, pie chart in Plan Summary, NABU fee, interchange names like Merit3/CPS Retail/PSL Retail/VFN/VTR | 16-digit (4-4-4-2: `1234-5678-9012-34`) | USD |
| **Worldpay / FIS** | Proprietary | MM-303 report format, "VISANET-VIRT NET" auth descriptors. **Information-only** — fees NOT deducted on this report, billed separately | Varies | USD |
| **Fiserv / First Data** | Proprietary | "YOUR CARD PROCESSING STATEMENT" header, "THIS IS NOT A BILL", Summary by Day format, may reference Newtek/Clover | 12-digit (`815204XXXXXX`) | USD |
| **Payroc / NCR** | Proprietary | "PAYROC ALOHA" or "AGENT OF NCR PAYMENT SOLUTIONS", COSMOS platform, Processing Summary with Interchange/Wholesale/Fees line, Card Type Summary table, Acquirer Process Fee line items (INTL CR/DB, US CR/DB) | 15-digit (`454045XXXXXXXXX`) | USD |
| **Paynuity** | TSYS | "MERCHANT STATEMENT" header, Plan Summary with plan codes and pie chart, Paynuity Corporation footer, Orlando FL address | 15-digit (`745300000XXXXXX`) | USD |
| **Paysafe / Merrco** | Proprietary | "Monthly Summary Report", "MERRCO Acquirer/Processor", effective MDR calculation shown, PCNO Core Fees terminology | 10-digit (`1002XXXXXX`) | CAD |
| **Worldline / Bambora** | Proprietary | "Bambora Inc. A Worldline Brand", Victoria BC address, simple "Summary of Fees" table, "Effective Rate Summary" section | 9-digit (`245XXXXXX`) | CAD |
| **PSiGate** | Proprietary | "PSiGate" branding, Concord ON address, "Merchant Statement (Settlement Period: MONTH YEAR)" format, per-category breakdown with Brand Fee + MDR columns, Effective MDR column | Named accounts (e.g., "GratifyCAD") | CAD |
| **ECS / US Alliance Group** | TSYS | "US ALLIANCE GROUP, INC" header, Rancho Santa Margarita CA address, TSYS Plan Summary format with plan codes, Reserve Funding section. **Likely white-label.** | 15-digit (`678800000XXXXXX`) | USD |
| **Cliq** | Proprietary | "MONTHLY BILLING STATEMENT" header, "Cliq" branding, Costa Mesa CA address, Card Summary + Summary of Card Fees table with per-category rates, detailed Card Brand fee breakdown (APF, NABU, DEF, Dues/Assess), Merchant Auths section, high misc fees (Persistent Merchant Monitoring $100). **Likely white-label.** | 12-digit (`840200XXXXXX`) | USD |
| **Paynetworx** | Proprietary | Van Alstyne TX address, UUID-style MID (`2ymFKj...`), simple Account Summary format (Gross Amount, Activity-Based Fees, Dispute Fees, Monthly Fees), minimal detail on page 1. **Likely white-label.** | UUID | USD |
| **Payarc** | TSYS | "PAYARC LLC" header, Greenwich CT address, TSYS Plan Summary format with plan codes, Deposits and Chargebacks sections. **Likely white-label.** | 15-digit (`567000000XXXXXX`) | USD |
| **Chesapeake Bank** | TSYS | "CHESAPEAKE BANK" header, Kilmarnock VA address, TSYS Plan Summary format with plan codes, shows per-item fee + disc % columns in plan summary. **Likely white-label bank sponsor.** | 14-digit (`5659XXXXXXXXXX`) | USD |

### Platform Parsing Logic

When you identify a statement as **TSYS-platform** (Paynuity, ECS/US Alliance, Payarc, Chesapeake Bank, or TSYS/GPN itself), use the parsing instructions in `references/tsys-gpn.md` — the section layout, plan codes, and fee structure are the same regardless of branding.

For **proprietary-format** processors (Worldpay, Fiserv, Payroc, Paysafe, Worldline/Bambora, PSiGate, Cliq, Paynetworx), each has its own layout. Read the relevant reference file if one exists, or extract data by analyzing the statement structure directly.

### White-Label Indicators

Folders prefixed with `x` in the statement library are suspected white-label processors. Signs of white-labeling:
- The same merchant (e.g., "Challenger Worldwide LLC") appears across multiple processors
- Very high flat rates (4.5%+) suggesting high-risk merchant pricing
- Reserve funding / holdback sections (common in high-risk processing)
- Generic branding or small bank names acting as sponsor banks

## Pricing Model Detection

Every statement must be evaluated fresh to determine what pricing model the merchant is on. The same processor can offer different models to different merchants — never assume a processor always uses the same model.

### Decision Tree (run on every statement)

```
Step 1: Look at the Plan Summary / fee summary section.
        Does every plan code / card type show the SAME discount %?
        ├── YES (e.g., 4.50% across VS, VD, MC, MD, etc.) → FLAT RATE. Done.
        │   Report: "Flat rate at X% [+ $X per item if shown]"
        └── NO or no disc % shown → Continue to Step 2.

Step 2: Is there an Interchange / Wholesale detail section listing
        individual IC categories with varying rates?
        ├── YES (20+ categories, rates like 0.05%, 1.51%, 2.65%) → IC+ PRICING.
        │   Proceed to IC+ Markup Detection below.
        └── NO → Continue to Step 3.

Step 3: Are transactions grouped into 2-3 rate buckets
        (Qualified / Mid-Qualified / Non-Qualified, or similar)?
        ├── YES → TIERED PRICING.
        │   Report: "Tiered pricing: Qual X%, Mid-Qual Y%, Non-Qual Z%"
        └── NO → Continue to Step 4.

Step 4: Is this an information-only report (like Worldpay MM-303)?
        ├── YES → PRICING MODEL CANNOT BE DETERMINED from this document.
        │   Report: "Information-only statement — need fee invoice to determine pricing model"
        └── NO → UNCLEAR. Flag for manual review.
```

### Format Quirks That Can Mislead Detection

Some statement formats have quirks that break the simple decision tree. Check for these before concluding:
- **Payarc** shows `$0.00` in the Plan Summary disc % column because fees are calculated in a separate Fees section — don't mistake this for flat rate at 0%
- **Payroc** separates "Acquirer Process Fee" (markup) from "Interchange/Wholesale" (passthrough) explicitly — both sections exist, which confirms IC+ even though the Plan Summary doesn't show a single disc %
- **TSYS-platform Plan Summary** shows a blended disc % that combines IC + markup — the existence of varying disc % per plan code hints at IC+ but isn't conclusive without checking for an interchange detail section
- **Cliq** shows per-category rates in the Card Fees section that look like IC+ but include enormous markups baked in — verify by checking if an interchange/wholesale section also exists

## IC+ Markup Detection

Once you've confirmed IC+ pricing from the detection tree above, determine the processor's markup using one of three methods. The goal is to extract two values: **markup basis points** (%) and **per-transaction fee** ($). See `references/icplus-detection.md` for implementation code.

### Method 1: Summary-Level (Quick Blended Check)
Use when you just need the blended markup. Most statements show Total Discount and Total Interchange separately.
`Markup $ = Discount Total − IC Total − Assessments`. Divide by volume for blended bps. Fast but doesn't reveal the pricing structure.

### Method 2: Anchor Category (Recommended Default)
Use regulated debit as a known-IC anchor (0.05% + $0.21, fixed by Durbin). Pick a second category with a well-known rate (e.g., Visa CPS Retail at 1.51% + $0.10). For each:
`Excess = Statement Fee − Known IC = (markup% × volume) + (per_txn × count)`
Two categories, two equations, two unknowns — solve algebraically. This works on any statement that shows per-category fees, without needing interchange tables.

### Method 3: Linear Regression (Most Precise)
On a true IC+ plan the markup is identical across all categories. For every line item:
`Fee − IC Amount = (markup% × volume) + (per_txn × count)`
Run a linear regression across all categories. Markup% = coefficient on volume, per_txn = coefficient on count. Outliers flag categories with different pricing (Amex, pin debit networks). Requires the statement to show IC amounts per category.

### When IC+ Markup Solve Fails
- **Information-only reports** (Worldpay MM-303) — shows IC but not total fees; need the separate fee invoice
- **Amex OptBlue** — often priced at a different markup than V/MC; treat as a separate solve
- **Mixed pricing** — some merchants have IC+ on credit and flat on debit, or different markup tiers by volume band

Always state confidence level in the report: "IC+ markup identified with high confidence from X categories" or "blended estimate only — per-category detail not available."

## Analysis Checklist

Every MSA analysis must cover these items:

### Fee Decomposition
- **Interchange passthrough**: The actual card brand interchange cost per transaction category
- **Card brand assessments**: Visa/MC/Discover/Amex network fees (NABU, APF, brand usage, etc.) — these are NOT interchange
- **Processor markup**: The acquirer/ISO margin above interchange and assessments
- **Hidden fees**: Settlement funding fees, PCI fees, statement fees, batch fees, monthly minimums

### Debit vs Credit Split
- Calculate the debit-to-total volume ratio
- On debit transactions, interchange is very low (often 0.05% + $0.21 for regulated). If the processor charges a flat % markup, that markup often EXCEEDS the interchange cost on debit — this is a major savings opportunity.
- Break out pin debit, signature debit, and prepaid debit separately when data is available.

### Interchange Category Detail
- List every interchange category with volume, transaction count, and effective rate
- Identify downgrades: any transaction that qualified at a higher tier than necessary (e.g., MC Commercial No Level 2, Visa Commercial Tax Exempt)
- Downgrades are preventable with Level 2/Level 3 data submission

### L2/L3 Data Optimization (MANDATORY CHECK)

**This check is required on every statement with commercial card volume.** Do not skip it. Commercial cards at base rates are NOT "downgrades" in the traditional sense — they are qualified at the correct tier for the data submitted. The opportunity is upgrading qualification by submitting enhanced data. This is easy to miss if you only look for fallback/EIRF categories.

See `references/l2l3-optimization.md` for the full detection and savings calculation methodology.

**Quick scan**: Look for ANY of these patterns in the interchange detail:
- **Visa**: Categories ending in "Prod 1" or "Product 1" (e.g., "VS Business Tr3 Prod 1", "VS Purchasing CR Product 1") — these are commercial cards WITHOUT L2/L3 data
- **Mastercard**: Categories containing "Data Rate I" or "Data Rate 1" (e.g., "MC Business Level 5 Data Rate I", "Comm Data Rate 1 Large Market") — these are commercial cards WITHOUT L2 data
- **Any brand**: "Non Qual" commercial categories (e.g., "VS Non Qual Bus Cr") — worst qualification tier

**If found**: Calculate the savings opportunity using the methodology in the reference file and include an L2/L3 section in the report/quote template. Even 15–20bps on high commercial volume translates to thousands per month.

**Critical nuance by brand**:
- **Visa Business cards**: "Prod 1" vs "Level 2" often carry the SAME rate in each tier. Savings come mainly from Purchasing and Corporate cards.
- **Mastercard**: Data Rate I → Data Rate II typically saves 15–75bps depending on the commercial sub-program. This is usually where the big money is.
- **Amex**: Not applicable — Amex OptBlue doesn't use L2/L3 tiers the same way.

### Cross-Validation Rules
When comparing against a manual analysis:
- All volume figures should match to the penny
- Transaction counts should match exactly
- If interchange totals differ, check whether one analysis lumps assessments into interchange
- If markup % differs, check whether one analysis includes hidden fees (like settlement funding) and the other doesn't

## Gratify Rate Review Document Template

The report is a 2-page branded Word document generated with `python-docx`.

### Page 1 — Executive Summary
1. **Letterhead**: "GRATIFY" in Montserrat Bold 24pt, color #1A568E. Below: thin divider line.
2. **Title block**: "Rate Review Analysis" + merchant name + date (e.g., "MAY-2026")
3. **Prepared for / Prepared by** block
4. **Narrative findings**: 3-5 numbered findings in natural language, each 1-2 sentences. Lead with the most impactful insight.
5. **Summary table**: Dark header (#1A568E white text), alternating row shading. Columns: Metric | Current | Proposed. Rows: Monthly Volume, Effective Rate, Monthly Processing Cost, Monthly Savings, Annual Savings.
6. **Highlight boxes**: 2-3 key metrics in colored boxes (e.g., green for savings, blue for volume). Use a borderless table with background fills.

### Page 2 — Detailed Analysis
1. **Card mix table**: Visa/MC/Discover/Amex breakdown with volume, %, and effective rate per brand
2. **Interchange detail table** (if relevant): Top interchange categories by volume with effective rates
3. **Downgrade table** (if applicable): Red-themed (#C00000 header), showing downgrade categories and estimated annual cost
4. **Debit analysis table** (if high debit volume): Breakdown of debit interchange categories showing markup vs IC cost
5. **Proposal verification table** (if comparing against a competing proposal): Side-by-side of claimed vs actual figures
6. **Recommendation**: 2-3 sentence closing paragraph

### Document Generation Pattern

```python
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import nsdecls
from docx.oxml import parse_xml

def style_cell(cell, text, bold=False, bg=None, align='left', size=8, color=None):
    cell.text = ''
    p = cell.paragraphs[0]
    if align == 'right': p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    elif align == 'center': p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = 'Arial'
    if color: run.font.color.rgb = color
    elif bold and bg: run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    if bg:
        shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{bg}" w:val="clear"/>')
        cell._tc.get_or_add_tcPr().append(shading)

def add_divider(doc):
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pBdr = parse_xml(f'<w:pBdr {nsdecls("w")}><w:bottom w:val="single" w:sz="6" w:space="1" w:color="1A568E"/></w:pBdr>')
    pPr.append(pBdr)

def remove_borders(table):
    for row in table.rows:
        for cell in row.cells:
            tcPr = cell._tc.get_or_add_tcPr()
            borders = parse_xml(f'<w:tcBorders {nsdecls("w")}>'
                '<w:top w:val="none"/><w:left w:val="none"/>'
                '<w:bottom w:val="none"/><w:right w:val="none"/></w:tcBorders>')
            tcPr.append(borders)
```

Brand color: `#1A568E` (Gratify blue). Accent for warnings/downgrades: `#C00000` (dark red). Highlight fills: green `#E2EFDA`, blue `#D6E4F0`, amber `#FFF2CC`.
