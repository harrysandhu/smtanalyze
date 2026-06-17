# OCR Guide for Scanned / Photographed Statements

Some merchant statements arrive as photographs or scans with zero text layer. This guide covers reliable extraction.

## Detection

```python
import pdfplumber
pdf = pdfplumber.open("statement.pdf")
text = pdf.pages[0].extract_text()
if not text or len(text.strip()) < 50:
    # Scanned PDF — needs OCR pipeline
```

## Extraction Pipeline

### Step 1: Render to High-Resolution PNG

```python
import pdfplumber
pdf = pdfplumber.open("statement.pdf")
for i, page in enumerate(pdf.pages):
    img = page.to_image(resolution=300)
    img.save(f"page_{i+1}.png")
```

300 DPI is the sweet spot — lower loses small text, higher wastes time without quality gain.

### Step 2: OCR with Tesseract

```python
import pytesseract
from PIL import Image

text = pytesseract.image_to_string(Image.open("page_1.png"), config='--psm 6')
```

PSM 6 (assume uniform block of text) works best for statement pages. PSM 4 (assume single column) is an alternative if 6 produces garbled output.

### Step 3: Visual Verification with Claude Multimodal

After OCR, read the PNG images directly with Claude's vision capability to verify anchor numbers. OCR frequently mis-reads:
- `$` as `S` or `5`
- `1` as `l` or `I`
- `,` as `.` (critical for dollar amounts)
- `0` as `O`

Compare OCR-extracted totals against what you can read from the image. The image is ground truth.

### Step 4: Structured Extraction

Once you have reliable text, parse line by line. Statement tables typically have fixed-width columns. Look for:
- Lines with dollar amounts (regex: `\$[\d,]+\.\d{2}`)
- Lines with percentages (regex: `\d+\.\d+%`)
- Section headers in ALL CAPS or bold (larger font renders differently in OCR)

## Common OCR Failures on Statements

| Problem | Symptom | Fix |
|---------|---------|-----|
| Skewed photo | Garbled text, lines overlap | Pre-process with deskew before OCR |
| Low contrast | Missing characters | Increase contrast on image before OCR |
| Table borders merge with text | Numbers stick together | Use `--psm 6` and parse carefully |
| Multi-column layout | Columns interleave | Process left/right halves separately |

## Validation Checklist

After OCR extraction, verify these anchor numbers match the image:
- [ ] Total monthly volume (largest dollar figure on the statement)
- [ ] Total transaction count
- [ ] Total fees / discount amount
- [ ] At least 2-3 individual interchange line items

If any anchor number is off, re-extract from the image visually rather than trusting OCR.
