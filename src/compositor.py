"""
Compositor — assembles the final 4000×2800 stylescape PNG using Pillow.

14-cell grid layout (absolute positioning, dark #0a0a0a background):

  ┌────────┬────────┬────────┬──────────────┐  Row 1  h=660
  │ mock 0 │ mock 1 │ mock 2 │   mock 3     │  3 small + 1 large
  ├──────────────┬──────────────────┬────────┤  Row 2  h=740
  │   mock 4     │  ★ LOGO CENTER ★ │ mock 5 │  logo prominently centered
  ├────────┬─────┴─────┬────────────┤────────┤  Row 3  h=660
  │ mock 6 │  PALETTE  │  PATTERN   │ mock 7 │
  ├─────────────────────────────────┬────────┤  Row 4  h=642
  │    DIRECTION INFO (wide)        │  m8 m9 │
  └─────────────────────────────────┴────────┘

Canvas: 4000 × 2800  |  Margin: 28px  |  Gap: 14px  |  Border-radius: 16px
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .director import BrandDirection, ColorSwatch
from .generator import DirectionAssets
from .palette_renderer import render_palette_cell, swatches_to_dicts

# ── Canvas geometry ───────────────────────────────────────────────────────────

CANVAS_W  = 4000
CANVAS_H  = 2800
MARGIN    = 28
GAP       = 14
RADIUS    = 16
BG_COLOR  = (10, 10, 10)

# Row y-positions and heights  (verified: 28+660+14+740+14+660+14+642+28 = 2800)
_ROW_Y = [28, 702, 1456, 2130]
_ROW_H = [660, 740, 660, 642]

# Inner width: 4000 - 2*28 = 3944
_IW = CANVAS_W - 2 * MARGIN   # 3944


def _grid() -> List[Tuple[str, int, int, int, int, Optional[int]]]:
    """
    Return list of (cell_type, x, y, w, h, mockup_slot_or_None).

    Cell types: "mockup", "logo", "palette", "pattern", "info"
    mockup_slot: index 0-9 for mockup cells, None for content cells.
    """
    # Row 1: 3 small + 1 large
    # small = 867, large = 1301  →  3×867 + 3×14 + 1301 = 3944
    sm, lg = 867, 1301
    r1y, r1h = _ROW_Y[0], _ROW_H[0]
    row1 = [
        ("mockup", MARGIN,                  r1y, sm, r1h, 0),
        ("mockup", MARGIN + sm + GAP,       r1y, sm, r1h, 1),
        ("mockup", MARGIN + 2*(sm+GAP),     r1y, sm, r1h, 2),
        ("mockup", MARGIN + 3*sm + 3*GAP,   r1y, lg, r1h, 3),
    ]

    # Row 2: side=1158, logo=1600  →  1158+14+1600+14+1158 = 3944
    sd, lc = 1158, 1600
    r2y, r2h = _ROW_Y[1], _ROW_H[1]
    logo_x = MARGIN + sd + GAP
    row2 = [
        ("mockup", MARGIN,                       r2y, sd, r2h, 4),
        ("logo",   logo_x,                       r2y, lc, r2h, None),
        ("mockup", logo_x + lc + GAP,            r2y, sd, r2h, 5),
    ]

    # Row 3: 4 equal-ish  →  975+975+975+977 + 3×14 = 3944
    q0, q1, q2, q3 = 975, 975, 975, 977
    r3y, r3h = _ROW_Y[2], _ROW_H[2]
    row3 = [
        ("mockup",  MARGIN,                             r3y, q0, r3h, 6),
        ("palette", MARGIN + q0 + GAP,                 r3y, q1, r3h, None),
        ("pattern", MARGIN + q0 + q1 + 2*GAP,          r3y, q2, r3h, None),
        ("mockup",  MARGIN + q0 + q1 + q2 + 3*GAP,    r3y, q3, r3h, 7),
    ]

    # Row 4: info=2000, sm=800, md=1116  →  2000+14+800+14+1116 = 3944
    inf_w, sm2, md2 = 2000, 800, 1116
    r4y, r4h = _ROW_Y[3], _ROW_H[3]
    row4 = [
        ("info",   MARGIN,                       r4y, inf_w, r4h, None),
        ("mockup", MARGIN + inf_w + GAP,         r4y, sm2,   r4h, 8),
        ("mockup", MARGIN + inf_w + sm2 + 2*GAP, r4y, md2,  r4h, 9),
    ]

    return row1 + row2 + row3 + row4   # 4 + 3 + 4 + 3 = 14 cells


# ── Font helpers ─────────────────────────────────────────────────────────────

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Helvetica Neue.ttf",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/SFNSDisplay.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    h = hex_str.strip("#")
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return (128, 128, 128)


def _brightness(rgb: Tuple[int, int, int]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _contrasting_text(bg: Tuple[int, int, int]) -> Tuple[int, int, int]:
    return (255, 255, 255) if _brightness(bg) < 140 else (20, 20, 20)


def _wrap_pixels(
    text: str,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont,
    max_px: int,
) -> List[str]:
    """Word-wrap text to fit within max_px pixel width."""
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        try:
            tb = draw.textbbox((0, 0), test, font=font)
            tw = tb[2] - tb[0]
        except Exception:
            tw = len(test) * (font.size // 2)
        if tw <= max_px:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


# ── Image fitting ─────────────────────────────────────────────────────────────

def _fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Resize to cover (w×h), center-crop the excess."""
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    nw = math.ceil(iw * scale)
    nh = math.ceil(ih * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    cx = (nw - w) // 2
    cy = (nh - h) // 2
    return img.crop((cx, cy, cx + w, cy + h))


def _paste_rounded(
    canvas: Image.Image,
    cell_img: Image.Image,
    x: int,
    y: int,
    radius: int = RADIUS,
) -> None:
    """Paste cell_img onto canvas at (x,y) with rounded-corner mask."""
    w, h = cell_img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, w - 1, h - 1], radius=radius, fill=255
    )
    canvas.paste(cell_img.convert("RGB"), (x, y), mask)


# ── Cell builders ─────────────────────────────────────────────────────────────

def _cell_mockup(path: Optional[Path], w: int, h: int) -> Image.Image:
    """Mockup photo — cover-fit to fill cell."""
    dark = Image.new("RGB", (w, h), (22, 22, 22))
    if path is None or not path.exists():
        return dark
    try:
        return _fit_cover(Image.open(path).convert("RGB"), w, h)
    except Exception:
        return dark


def _cell_logo(assets: DirectionAssets, w: int, h: int) -> Image.Image:
    """Center cell — large logo + direction name, dark branded background."""
    primary_rgb = _hex_to_rgb(assets.direction.colors[0].hex)
    bg_rgb = tuple(max(0, int(c * 0.10)) for c in primary_rgb)
    img = Image.new("RGB", (w, h), bg_rgb)
    draw = ImageDraw.Draw(img)

    PAD = 44

    # Option badge (top center)
    font_opt = _load_font(22)
    opt_text = f"OPTION  {assets.direction.option_number}"
    try:
        tb = draw.textbbox((0, 0), opt_text, font=font_opt)
        tw = tb[2] - tb[0]
    except Exception:
        tw = len(opt_text) * 13
    draw.text(((w - tw) // 2, 34), opt_text, fill=primary_rgb, font=font_opt)

    # Logo zone: between opt badge and name label
    name_reserve = 130
    logo_zone_top = 88
    logo_zone_h = h - logo_zone_top - name_reserve

    if (
        assets.logo
        and assets.logo.exists()
        and assets.logo.stat().st_size > 100
    ):
        try:
            logo = Image.open(assets.logo).convert("RGBA")
            lw, lh = logo.size
            max_w = w - PAD * 2
            scale = min(max_w / lw, logo_zone_h / lh) * 0.92
            nw = max(1, int(lw * scale))
            nh = max(1, int(lh * scale))
            logo = logo.resize((nw, nh), Image.LANCZOS)
            lx = (w - nw) // 2
            ly = logo_zone_top + (logo_zone_h - nh) // 2
            img.paste(logo, (lx, ly), logo)
        except Exception:
            pass
    draw = ImageDraw.Draw(img)

    # Direction name (bottom)
    font_name = _load_font(36)
    name = assets.direction.direction_name.upper()
    lines = _wrap_pixels(name, draw, font_name, w - PAD * 2)
    ty = h - name_reserve + 16
    for line in lines[:2]:
        try:
            tb = draw.textbbox((0, 0), line, font=font_name)
            tw = tb[2] - tb[0]
        except Exception:
            tw = len(line) * 22
        draw.text(((w - tw) // 2, ty), line, fill=(228, 228, 228), font=font_name)
        ty += 50

    return img


def _cell_palette(
    direction: BrandDirection,
    w: int,
    h: int,
    enriched_colors: Optional[List[dict]] = None,
) -> Image.Image:
    """
    Color palette cell — vertical strip format.

    Uses enriched_colors (from palette_fetcher) if provided,
    otherwise falls back to direction.colors ColorSwatch objects.
    """
    colors = enriched_colors if enriched_colors else swatches_to_dicts(direction.colors)
    return render_palette_cell(colors, w, h)


def _cell_pattern(assets: DirectionAssets, w: int, h: int) -> Image.Image:
    """Brand pattern tile — fill cell, subtle label overlay."""
    primary_rgb = _hex_to_rgb(assets.direction.colors[0].hex)
    bg_rgb = tuple(max(0, int(c * 0.18)) for c in primary_rgb)
    img = Image.new("RGB", (w, h), bg_rgb)

    if (
        assets.pattern
        and assets.pattern.exists()
        and assets.pattern.stat().st_size > 100
    ):
        try:
            pat = Image.open(assets.pattern).convert("RGB")
            pat_filled = _fit_cover(pat, w, h)
            bg = Image.new("RGB", (w, h), bg_rgb)
            img = Image.blend(bg, pat_filled, alpha=0.82)
        except Exception:
            pass

    draw = ImageDraw.Draw(img)
    draw.text((24, 24), "PATTERN", fill=(210, 210, 210), font=_load_font(20))
    return img


def _cell_info(direction: BrandDirection, w: int, h: int) -> Image.Image:
    """Direction info — option badge, name, rationale, typography."""
    primary_rgb = _hex_to_rgb(direction.colors[0].hex)
    bg_rgb = tuple(max(0, int(c * 0.14)) for c in primary_rgb)
    img = Image.new("RGB", (w, h), bg_rgb)
    draw = ImageDraw.Draw(img)

    PAD = 48
    y = PAD

    # ── Option + type badge ───────────────────────────────────────────────────
    accent_rgb = (
        _hex_to_rgb(direction.colors[1].hex)
        if len(direction.colors) > 1
        else (130, 130, 145)
    )
    font_badge = _load_font(20)
    badge_text = f"  OPTION {direction.option_number}  ·  {direction.option_type.upper()}  "
    try:
        tb = draw.textbbox((PAD, y), badge_text, font=font_badge)
        bw = tb[2] - tb[0] + 22
        bh = tb[3] - tb[1] + 12
    except Exception:
        bw, bh = 300, 34
    draw.rounded_rectangle([PAD, y, PAD + bw, y + bh], radius=7, fill=accent_rgb)
    draw.text(
        (PAD + 11, y + 6),
        badge_text.strip(),
        fill=_contrasting_text(accent_rgb),
        font=font_badge,
    )
    y += bh + 30

    # ── Direction name ────────────────────────────────────────────────────────
    font_title = _load_font(58)
    name = direction.direction_name.upper()
    for line in _wrap_pixels(name, draw, font_title, w - PAD * 2):
        draw.text((PAD, y), line, fill=(238, 238, 238), font=font_title)
        y += 70
    y += 8

    # ── Separator ─────────────────────────────────────────────────────────────
    draw.line([(PAD, y), (w - PAD, y)], fill=(60, 60, 72), width=1)
    y += 22

    # ── Rationale ─────────────────────────────────────────────────────────────
    font_body = _load_font(22)
    max_body_w = w - PAD * 2
    for line in _wrap_pixels(direction.rationale, draw, font_body, max_body_w):
        if y + 30 > h - 90:
            break
        draw.text((PAD, y), line, fill=(155, 155, 168), font=font_body)
        y += 30
    y += 12

    # ── Typography footer ─────────────────────────────────────────────────────
    if y + 50 < h - PAD:
        draw.line([(PAD, y), (w // 3, y)], fill=(45, 45, 58), width=1)
        y += 16
        font_small = _load_font(18)
        primary_name = re.split(r"[,:—–]", direction.typography_primary)[0].strip()
        secondary_name = re.split(r"[,:—–]", direction.typography_secondary)[0].strip()
        draw.text(
            (PAD, y),
            f"TYPE  ·  {primary_name}  /  {secondary_name}",
            fill=(90, 90, 105),
            font=font_small,
        )

    return img


# ── Full stylescape assembly ──────────────────────────────────────────────────

def assemble_stylescape(
    assets: DirectionAssets,
    output_dir: Path,
    enriched_colors: Optional[List[dict]] = None,
) -> Path:
    """
    Compose 14-cell stylescape grid and save as PNG.

    Args:
        assets:          DirectionAssets including .mockups list (up to 10 paths).
        output_dir:      Where to save the final stylescape PNG.
        enriched_colors: Optional enriched color dicts from palette_fetcher
                         (with hex, name, role, cmyk, source). Falls back to
                         direction.colors ColorSwatch objects if not provided.

    Returns:
        Path to the saved stylescape PNG.
    """
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), BG_COLOR)

    mockups = assets.mockups or []   # list of composited mockup paths

    def _slot(idx: int) -> Optional[Path]:
        return mockups[idx] if idx < len(mockups) else None

    for cell in _grid():
        ctype, cx, cy, cw, ch, slot = cell

        if ctype == "mockup":
            cell_img = _cell_mockup(_slot(slot), cw, ch)

        elif ctype == "logo":
            cell_img = _cell_logo(assets, cw, ch)

        elif ctype == "palette":
            cell_img = _cell_palette(assets.direction, cw, ch, enriched_colors=enriched_colors)

        elif ctype == "pattern":
            cell_img = _cell_pattern(assets, cw, ch)

        elif ctype == "info":
            cell_img = _cell_info(assets.direction, cw, ch)

        else:
            cell_img = Image.new("RGB", (cw, ch), (30, 30, 30))

        _paste_rounded(canvas, cell_img, cx, cy)

    slug = re.sub(r"[^a-z0-9]+", "_", assets.direction.direction_name.lower()).strip("_")[:30]
    out_path = output_dir / f"stylescape_{assets.direction.option_number}_{slug}.png"
    canvas.save(str(out_path), format="PNG")
    return out_path


# ── Public entry point ────────────────────────────────────────────────────────

def build_all_stylescapes(
    all_assets: dict,
    output_dir: Path,
) -> dict:
    """
    Build stylescapes for all directions.

    Args:
        all_assets: Dict mapping option_number → DirectionAssets.
                    Each DirectionAssets.mockups should be populated before
                    calling this (by composite_all_mockups in mockup_compositor).
        output_dir: Where to save stylescape PNGs.

    Returns:
        Dict mapping option_number → stylescape Path.
    """
    from rich.console import Console
    console = Console()

    output_dir.mkdir(parents=True, exist_ok=True)
    stylescapes = {}

    for num, assets in all_assets.items():
        n_mockups = len(assets.mockups) if assets.mockups else 0
        console.print(
            f"  [cyan]Assembling stylescape  Option {num}: "
            f"{assets.direction.direction_name}  "
            f"({n_mockups} mockups)[/cyan]"
        )
        path = assemble_stylescape(
            assets,
            output_dir,
            enriched_colors=getattr(assets, "enriched_colors", None),
        )
        stylescapes[num] = path
        console.print(f"  [green]✓[/green] → {path.name}")

    return stylescapes
