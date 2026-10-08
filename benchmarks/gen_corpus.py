"""Generate a reproducible synthetic corpus of commodity market reports.

Each document is a multi-page PDF that mimics the shape of a real market
report: a running masthead/footer, narrative paragraphs naming commodities,
ports, companies and prices, and a gridded price table. A configurable share
of pages is "scanned" - rendered to an image and re-embedded with no text
layer - so the OCR fallback path is genuinely exercised.

All content is synthetic (seeded RNG); no real report text is used.

Usage: python gen_corpus.py --out corpus --docs 60 --pages 8 --scanned-ratio 0.1
"""

import argparse
import io
import json
import random
from pathlib import Path

import fitz  # PyMuPDF
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

COMMODITIES = ["thermal coal", "Brent crude", "naphtha", "LNG", "iron ore", "copper",
               "wheat", "palm oil", "diesel", "jet fuel", "urea", "aluminium"]
PORTS = [("Mundra", "India"), ("Kandla", "India"), ("Paradip", "India"), ("Singapore", "Singapore"),
         ("Rotterdam", "Netherlands"), ("Fujairah", "UAE"), ("Qingdao", "China"),
         ("Port Hedland", "Australia"), ("Houston", "United States"), ("Santos", "Brazil")]
COMPANIES = ["Adani Ports SEZ", "Reliance Industries", "Vitol", "Trafigura", "Glencore",
             "Indian Oil Corporation", "Cargill", "BHP", "Rio Tinto", "Shell Trading"]
DRIVERS = ["refinery maintenance", "monsoon-related port congestion", "tighter Middle East supply",
           "stronger Chinese import demand", "freight rate volatility", "export quota changes",
           "lower inventory levels", "currency weakness", "new sanctions on shipments",
           "seasonal demand uplift"]
MOVES = ["strengthened", "weakened", "rose", "fell", "held steady", "rebounded", "softened"]
UNITS = {"thermal coal": "t", "Brent crude": "bbl", "naphtha": "t", "LNG": "MMBtu",
         "iron ore": "t", "copper": "t", "wheat": "t", "palm oil": "t", "diesel": "bbl",
         "jet fuel": "bbl", "urea": "t", "aluminium": "t"}


def paragraph(rng: random.Random) -> str:
    c = rng.choice(COMMODITIES)
    port, country = rng.choice(PORTS)
    co = rng.choice(COMPANIES)
    price = round(rng.uniform(40, 900), 2)
    qty = round(rng.uniform(0.2, 9.5), 1)
    sentences = [
        f"{c.capitalize()} prices {rng.choice(MOVES)} to USD {price}/{UNITS[c]} this week on "
        f"{rng.choice(DRIVERS)}.",
        f"{co} owns {port} Port in {country}, where loadings of {c} reached {qty} million tonnes "
        f"in {rng.choice(['January', 'February', 'March', 'April', 'May', 'June'])} 2026.",
        f"Cargoes of {c} shipped from {port} to {rng.choice(PORTS)[1]} were assessed under CIF "
        f"terms, with traders citing {rng.choice(DRIVERS)}.",
        f"Market participants expect {rng.choice(DRIVERS)} to keep {c} spreads volatile into "
        f"Q{rng.randint(1, 4)} 2026.",
    ]
    rng.shuffle(sentences)
    return " ".join(sentences[: rng.randint(2, 4)])


def price_table(rng: random.Random) -> Table:
    header = ["Commodity", "Basis", "Price (USD)", "Unit", "Change (%)"]
    rows = [header]
    for c in rng.sample(COMMODITIES, 6):
        rows.append([c, rng.choice(["FOB", "CIF", "CFR", "DES"]),
                     f"{rng.uniform(40, 900):.2f}", UNITS[c], f"{rng.uniform(-6, 6):+.1f}"])
    table = Table(rows)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))
    return table


def build_pdf(rng: random.Random, pages: int, title: str) -> bytes:
    buf = io.BytesIO()
    styles = getSampleStyleSheet()

    def masthead(canvas, doc):  # running header/footer like a real report
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(40, A4[1] - 25, "CMIP Synthetic Commodity Market Report - Confidential")
        canvas.drawString(40, 20, f"Page {doc.page}  |  (c) Synthetic Data 2026")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, title=title, author="CMIP benchmark generator")
    story = [Paragraph(title, styles["Title"])]
    for p in range(pages):
        for _ in range(rng.randint(4, 6)):
            story.append(Paragraph(paragraph(rng), styles["BodyText"]))
            story.append(Spacer(1, 6))
        if p % 2 == 0:
            story.append(price_table(rng))
        if p < pages - 1:
            story.append(PageBreak())
    doc.build(story, onFirstPage=masthead, onLaterPages=masthead)
    return buf.getvalue()


def scan_pages(pdf_bytes: bytes, page_indexes: set[int], dpi: int = 150) -> bytes:
    """Replace the chosen pages with image-only copies (no text layer),
    emulating a scanned page."""
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = fitz.open()
    for i, page in enumerate(src):
        if i in page_indexes:
            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
            new = out.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, stream=pix.tobytes("png"))
        else:
            out.insert_pdf(src, from_page=i, to_page=i)
    return out.tobytes()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="corpus")
    ap.add_argument("--docs", type=int, default=60)
    ap.add_argument("--pages", type=int, default=8)
    ap.add_argument("--scanned-ratio", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for d in range(args.docs):
        title = f"Weekly {rng.choice(COMMODITIES).title()} Market Review #{d + 1:03d}"
        pdf = build_pdf(rng, args.pages, title)
        n_pages = fitz.open(stream=pdf, filetype="pdf").page_count
        scanned = {i for i in range(n_pages) if rng.random() < args.scanned_ratio}
        # ground truth for OCR accuracy: the native text of each page before it is scanned
        src = fitz.open(stream=pdf, filetype="pdf")
        truth = {str(i + 1): src[i].get_text("text") for i in sorted(scanned)}
        if scanned:
            pdf = scan_pages(pdf, scanned)
        path = out / f"report_{d + 1:03d}.pdf"
        path.write_bytes(pdf)
        manifest.append({"file": path.name, "pages": n_pages, "scanned_pages": [i + 1 for i in sorted(scanned)],
                         "scanned_ground_truth": truth,
                         "bytes": len(pdf)})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    total_pages = sum(m["pages"] for m in manifest)
    total_scanned = sum(len(m["scanned_pages"]) for m in manifest)
    print(f"{len(manifest)} docs, {total_pages} pages ({total_scanned} scanned), "
          f"{sum(m['bytes'] for m in manifest) / 1e6:.1f} MB -> {out}")


if __name__ == "__main__":
    main()
