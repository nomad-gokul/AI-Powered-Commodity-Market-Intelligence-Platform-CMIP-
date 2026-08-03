"""Header/footer detection heuristic.

This is deliberately simple, not real layout analysis: a text block is
treated as a header/footer candidate purely by its vertical position on the
page (top/bottom HEADER_FOOTER_MARGIN_RATIO of the page height). This
correctly catches the common commodity-report case (a running masthead like
"Platts Dated Brent Assessment" at the top, a page-number/copyright line at
the bottom), but it is a heuristic: a document whose body text starts very
close to the top margin will misclassify its first paragraph as a header.
Documented here rather than oversold as full layout analysis.
"""

from typing import Any

HEADER_FOOTER_MARGIN_RATIO = 0.08


def detect_header_footer(page: Any) -> tuple[str | None, str | None]:
    """`page` is a fitz.Page (typed Any to avoid a hard PyMuPDF stub
    dependency at the type-checking layer)."""
    page_height = page.rect.height
    header_boundary = page_height * HEADER_FOOTER_MARGIN_RATIO
    footer_boundary = page_height * (1 - HEADER_FOOTER_MARGIN_RATIO)

    header_lines: list[str] = []
    footer_lines: list[str] = []

    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:  # not a text block (e.g. an image block)
            continue
        text = "".join(
            span["text"] for line in block.get("lines", []) for span in line.get("spans", [])
        ).strip()
        if not text:
            continue
        _, top, _, bottom = block["bbox"]
        if bottom <= header_boundary:
            header_lines.append(text)
        elif top >= footer_boundary:
            footer_lines.append(text)

    return (" ".join(header_lines) or None, " ".join(footer_lines) or None)
