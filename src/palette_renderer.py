"""
palette_renderer.py — Render brand color palettes as vertical strip images.

Format (matching reference):
  ┌──────┬──────┬──────┬──────┬──────┐
  │      │      │      │      │      │
  │      │      │      │      │      │  ← tall color fill
  │      │      │      │      │      │
  │NAME  │NAME  │NAME  │NAME  │NAME  │  ← color name (top, inside strip)
  ├──────┼──────┼──────┼──────┼──────┤
  │#HEX  │#HEX  │#HEX  │#HEX  │#HEX  │  ← hex + CMYK (bottom footer)
  │C M Y K      ...                   │
  └──────┴──────┴──────┴──────┴──────┘

Usage:
    from src.palette_renderer import render_palette

    # Standalone export
    path = render_palette(colors, output_path="output/palette.png")

    # For compositor cell
    img = render_palette_image(colors, width=975, height=660)
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Union

from PIL import Image, ImageDraw, ImageFont

# ── Font helpers ────────────────────────────────────────────────────────────

_FONT_CANDIDATES = [
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]

_FONT_BOLD_CANDIDATES = [
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = _FONT_BOLD_CANDIDATES if bold else _FONT_CANDIDATES
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ── Color utilities ─────────────────────────────────────────────────────────

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


def _text_color(bg_rgb: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """Return white or near-black text for best contrast."""
    return (255, 255, 255) if _brightness(bg_rgb) < 145 else (20, 20, 20)


def _muted_text_color(bg_rgb: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """Return slightly muted version of contrasting text color."""
    if _brightness(bg_rgb) < 145:
        return (210, 210, 215)
    else:
        return (70, 70, 80)


def _footer_bg(bg_rgb: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """Slightly darker/lighter footer strip for contrast."""
    br = _brightness(bg_rgb)
    factor = 0.80 if br > 100 else 1.25
    return tuple(min(255, max(0, int(c * factor))) for c in bg_rgb)


# ── Core renderer ───────────────────────────────────────────────────────────

def render_palette_image(
    colors: List[Dict],
    width: int = 2400,
    height: int = 640,
    gap: int = 3,
    show_label: bool = True,
    label_text: str = "COLOR PALETTE",
) -> Image.Image:
    """
    Render a vertical-strip color palette as a PIL Image.

    Args:
        colors: List of color dicts with at least {'hex': '#RRGGBB', 'name': str}.
                Optional keys: 'cmyk' (tuple), 'role' (str), 'source' (str).
        width:  Total image width in pixels.
        height: Total image height in pixels.
        gap:    Pixel gap between strips.
        show_label: Show "COLOR PALETTE" header label.
        label_text: Override header label text.

    Returns:
        PIL Image in RGB mode.
    """
    if not colors:
        img = Image.new("RGB", (width, height), (20, 20, 24))
        return img

    n = min(len(colors), 8)
    colors = colors[:n]

    # ── Layout ──────────────────────────────────────────────────────────────
    HEADER_H  = 44 if show_label else 0
    FOOTER_H  = max(80, int(height * 0.20))   # bottom info band per strip
    NAME_PAD  = 18                             # horizontal padding inside each strip
    STRIP_H   = height - HEADER_H             # strips start below header

    total_gap  = gap * (n - 1)
    strip_w    = (width - total_gap) // n
    remainder  = width - total_gap - strip_w * n  # distribute last strip

    img  = Image.new("RGB", (width, height), (12, 12, 16))
    draw = ImageDraw.Draw(img)

    # ── Header label ────────────────────────────────────────────────────────
    if show_label and HEADER_H > 0:
        font_hdr = _load_font(max(14, HEADER_H - 18))
        draw.text((NAME_PAD, 10), label_text, fill=(80, 80, 95), font=font_hdr)

    # ── Strips ──────────────────────────────────────────────────────────────
    font_name = _load_font(max(12, min(28, int(strip_w * 0.11))), bold=True)
    font_hex  = _load_font(max(10, min(22, int(strip_w * 0.09))))
    font_cmyk = _load_font(max(9,  min(17, int(strip_w * 0.075))))
    font_role = _load_font(max(8,  min(14, int(strip_w * 0.06))))

    for i, color in enumerate(colors):
        hex_val = color.get("hex", "#888888")
        name    = color.get("name", "Color")
        cmyk    = color.get("cmyk")        # (C, M, Y, K) 0-100
        role    = color.get("role", "")

        rgb       = _hex_to_rgb(hex_val)
        text_col  = _text_color(rgb)
        muted_col = _muted_text_color(rgb)
        footer_bg = _footer_bg(rgb)

        sw = strip_w + (remainder if i == n - 1 else 0)
        sx = i * (strip_w + gap)
        sy = HEADER_H

        # Main color fill (above footer)
        draw.rectangle(
            [sx, sy, sx + sw - 1, sy + STRIP_H - FOOTER_H - 1],
            fill=rgb,
        )

        # Footer band (slightly offset tone)
        draw.rectangle(
            [sx, sy + STRIP_H - FOOTER_H, sx + sw - 1, sy + STRIP_H - 1],
            fill=footer_bg,
        )

        # ── Color name (inside main swatch, bottom area of fill) ───────────
        name_short = name[:15] if len(name) > 15 else name
        name_y = sy + STRIP_H - FOOTER_H - _text_height(draw, name_short, font_name) - 14
        draw.text(
            (sx + NAME_PAD, max(sy + 12, name_y)),
            name_short.upper(),
            fill=text_col,
            font=font_name,
        )

        # ── Role badge (very top of strip, small) ──────────────────────────
        if role:
            role_text = role.upper()
            role_y = sy + 10
            draw.text((sx + NAME_PAD, role_y), role_text, fill=muted_col, font=font_role)

        # ── Footer: hex + CMYK ─────────────────────────────────────────────
        footer_text_col = _text_color(footer_bg)
        footer_muted    = _muted_text_color(footer_bg)

        footer_y = sy + STRIP_H - FOOTER_H + 10

        # Hex value
        draw.text(
            (sx + NAME_PAD, footer_y),
            hex_val.upper(),
            fill=footer_text_col,
            font=font_hex,
        )
        footer_y += _text_height(draw, hex_val, font_hex) + 6

        # CMYK values
        if cmyk and len(cmyk) == 4:
            c, m, y, k = cmyk
            cmyk_line = f"C{c} M{m} Y{y} K{k}"
        else:
            # Compute on the fly
            r, g, b = rgb
            if r == g == b == 0:
                cmyk_line = "C0 M0 Y0 K100"
            else:
                rf, gf, bf = r / 255, g / 255, b / 255
                kk = 1 - max(rf, gf, bf)
                if kk >= 1:
                    cmyk_line = "C0 M0 Y0 K100"
                else:
                    cc = round((1 - rf - kk) / (1 - kk) * 100)
                    mm = round((1 - gf - kk) / (1 - kk) * 100)
                    yy = round((1 - bf - kk) / (1 - kk) * 100)
                    kk = round(kk * 100)
                    cmyk_line = f"C{cc} M{mm} Y{yy} K{kk}"

        draw.text(
            (sx + NAME_PAD, footer_y),
            cmyk_line,
            fill=footer_muted,
            font=font_cmyk,
        )

    return img


def _text_height(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    """Get text height in pixels."""
    try:
        bb = draw.textbbox((0, 0), text, font=font)
        return bb[3] - bb[1]
    except Exception:
        return getattr(font, "size", 16)


# ── Standalone export ───────────────────────────────────────────────────────

def render_palette(
    colors: List[Dict],
    output_path: Union[str, Path],
    width: int = 2400,
    height: int = 640,
    direction_name: str = "",
) -> Path:
    """
    Render a vertical-strip palette and save as PNG.

    Args:
        colors:         List of color dicts (hex, name, cmyk, role).
        output_path:    Where to save the PNG.
        width:          Image width (default 2400px for print-ready).
        height:         Image height (default 640px).
        direction_name: Optional direction name for the label.

    Returns:
        Path to the saved PNG.
    """
    label = f"COLOR PALETTE — {direction_name.upper()}" if direction_name else "COLOR PALETTE"
    img   = render_palette_image(
        colors,
        width=width,
        height=height,
        show_label=True,
        label_text=label,
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out), "PNG", optimize=False)
    return out


# ── Compositor helper (drop-in for _cell_palette) ──────────────────────────

def render_palette_cell(
    colors: List[Dict],
    width: int,
    height: int,
) -> Image.Image:
    """
    Render palette cell sized for the stylescape compositor grid.
    This is a drop-in replacement for compositor._cell_palette().

    Args:
        colors: Enriched color dicts from palette_fetcher or direction.
        width:  Cell width from compositor grid.
        height: Cell height from compositor grid.

    Returns:
        PIL Image (RGB) of exact size.
    """
    return render_palette_image(
        colors,
        width=width,
        height=height,
        gap=max(2, width // 500),
        show_label=True,
        label_text="COLOR PALETTE",
    )


# ── Convenience: convert ColorSwatch list → color dicts ────────────────────

def swatches_to_dicts(swatches) -> List[Dict]:
    """
    Convert a list of ColorSwatch objects (from BrandDirection) to color dicts
    compatible with the renderer.

    Also computes CMYK on the fly if not present.
    """
    result = []
    for i, sw in enumerate(swatches):
        hex_val = getattr(sw, "hex", "#888888")
        name    = getattr(sw, "name", "Color")
        role    = getattr(sw, "role", "")
        result.append({
            "hex":    hex_val,
            "name":   name,
            "role":   role,
            "cmyk":   None,   # renderer computes on the fly
            "source": "ai",
        })
    return result
