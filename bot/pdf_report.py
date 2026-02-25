"""
pdf_report.py — Generate a PDF brand report from pipeline output.

Uses fpdf2 for zero-dependency PDF generation.
Produces a clean, single-column report with all 4 directions,
colour swatches, and embedded images.

Usage:
    from bot.pdf_report import generate_pdf_report
    pdf_path = generate_pdf_report(directions_output, output_dir, image_files)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    pass


def generate_pdf_report(
    directions_output,
    output_dir: Path,
    image_files: List[Path],
    brand_name: str = "Brand Identity",
) -> Optional[Path]:
    """
    Generate a PDF report. Returns path to PDF, or None on failure.

    Requires fpdf2: pip install fpdf2
    """
    try:
        from fpdf import FPDF, XPos, YPos
    except ImportError:
        return None

    class BrandPDF(FPDF):
        def header(self):
            self.set_font("Helvetica", "B", 10)
            self.set_text_color(120, 120, 120)
            self.cell(0, 8, f"{brand_name} — Brand Identity Report", align="R")
            self.ln(4)
            self.set_draw_color(220, 220, 220)
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(4)

        def footer(self):
            self.set_y(-15)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(160, 160, 160)
            self.cell(0, 10, f"Page {self.page_no()}", align="C")

    pdf = BrandPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(15, 15, 15)

    # ── Cover page ────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(20, 20, 20)
    pdf.ln(30)
    pdf.cell(0, 12, brand_name, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 14)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, "Brand Identity Directions", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(160, 160, 160)
    from datetime import datetime
    pdf.cell(
        0, 6,
        f"Generated {datetime.now().strftime('%B %d, %Y')}",
        align="C",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )

    # ── Direction pages ───────────────────────────────────────────────────────
    direction_images: dict = {}
    for img in image_files:
        stem = img.stem.lower()
        for i, direction in enumerate(directions_output.directions):
            dir_key = f"dir{i + 1}"
            if dir_key in stem or direction.option_type.lower().replace(" ", "_") in stem:
                direction_images.setdefault(i, []).append(img)

    for i, direction in enumerate(directions_output.directions):
        pdf.add_page()

        # Direction header
        colour_map = {
            "Market-Aligned": (34, 139, 34),    # green
            "Designer-Led":   (70, 130, 180),   # steel blue
            "Hybrid":         (184, 134, 11),   # dark goldenrod
            "Wild Card":      (178, 34, 34),    # firebrick
        }
        r, g, b = colour_map.get(direction.option_type, (60, 60, 60))

        pdf.set_fill_color(r, g, b)
        pdf.rect(15, pdf.get_y(), 180, 1, "F")
        pdf.ln(4)

        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(r, g, b)
        pdf.cell(0, 10, f"Option {i + 1} — {direction.option_type}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # Concept
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(60, 60, 60)
        pdf.ln(2)
        pdf.cell(30, 6, "Concept:", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, direction.concept or "—", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)

        # Strategy
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(30, 6, "Strategy:", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, direction.strategy or "—", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)

        # Colour palette swatches
        if direction.color_palette:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(0, 6, "Colour Palette", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1)

            swatch_w = 28
            swatch_h = 12
            x_start = 15
            x = x_start
            y = pdf.get_y()

            for colour in direction.color_palette[:6]:
                hex_val = colour.get("hex", "#888888").lstrip("#")
                try:
                    cr = int(hex_val[0:2], 16)
                    cg = int(hex_val[2:4], 16)
                    cb = int(hex_val[4:6], 16)
                except ValueError:
                    cr, cg, cb = 136, 136, 136

                pdf.set_fill_color(cr, cg, cb)
                pdf.rect(x, y, swatch_w - 2, swatch_h, "F")

                # Label
                pdf.set_font("Helvetica", "", 6)
                pdf.set_text_color(80, 80, 80)
                pdf.set_xy(x, y + swatch_h + 1)
                pdf.cell(swatch_w - 2, 4, f"#{hex_val.upper()}", align="C")

                x += swatch_w
                if x > 170:
                    x = x_start
                    y += swatch_h + 8

            pdf.set_xy(15, y + swatch_h + 8)
            pdf.ln(2)

        # Typography + Style
        if direction.typography:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(35, 6, "Typography:", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 6, direction.typography, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        if direction.graphic_style:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(35, 6, "Visual Style:", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 6, direction.graphic_style, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.ln(3)

        # Copy
        if direction.tagline or direction.ad_slogan:
            pdf.set_fill_color(245, 245, 245)
            pdf.rect(15, pdf.get_y(), 180, 0.5, "F")
            pdf.ln(4)
            pdf.set_font("Helvetica", "BI", 11)
            pdf.set_text_color(40, 40, 40)
            if direction.tagline:
                pdf.multi_cell(0, 7, f'"{direction.tagline}"', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if direction.ad_slogan:
                pdf.set_font("Helvetica", "I", 10)
                pdf.set_text_color(100, 100, 100)
                pdf.multi_cell(0, 6, direction.ad_slogan, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(3)

        # Images for this direction
        imgs = direction_images.get(i, [])
        if imgs:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(r, g, b)
            pdf.cell(0, 8, f"Option {i + 1} — Visual Assets", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(3)

            x, y = 15, pdf.get_y()
            img_w = 85
            col = 0

            for img_path in imgs[:6]:  # max 6 images per direction
                try:
                    if col == 2:
                        col = 0
                        x = 15
                        y += 70

                    pdf.image(str(img_path), x=x, y=y, w=img_w)
                    # Caption
                    pdf.set_font("Helvetica", "", 7)
                    pdf.set_text_color(140, 140, 140)
                    pdf.set_xy(x, y + 63)
                    pdf.cell(img_w, 4, img_path.stem.replace("_", " ").title(), align="C")

                    x += img_w + 5
                    col += 1
                except Exception:
                    pass  # skip unreadable images

    # ── Save ──────────────────────────────────────────────────────────────────
    pdf_path = output_dir / f"{brand_name.lower().replace(' ', '_')}_brand_report.pdf"
    pdf.output(str(pdf_path))
    return pdf_path
