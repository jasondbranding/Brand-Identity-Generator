"""
shade_generator.py — Generate 11-step tint/shade scales for each palette color.

Sources (in priority order):
  1. tints.dev API  — perceptually uniform OKLCH scales, Tailwind-compatible
     GET https://www.tints.dev/api/brand/{hex}
  2. HSL algorithm  — pure-Python fallback, same 11-step scale (50→950)

Output per color:
  {50: "#F0F4FF", 100: "#DCE5FF", ..., 900: "#0D1A66", 950: "#060D33"}

Usage:
    from src.shade_generator import generate_palette_shades, render_shade_image

    shades = generate_palette_shades(enriched_colors)
    # → {"Deep Navy": {50: "#hex", 100: "#hex", ...}, ...}

    img = render_shade_image(shades, enriched_colors)
    img.save("shades.png")
"""

from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from PIL import Image, ImageDraw, ImageFont

# ── Shade scale stops ─────────────────────────────────────────────────────────

SHADE_STOPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]

# ── OKLCH color space conversion ──────────────────────────────────────────────
# tints.dev returns colors in OKLCH (perceptually uniform).
# Pipeline: OKLCH → OKLab → Linear sRGB → sRGB → hex

def _oklch_to_hex(L: float, C: float, H_deg: float) -> str:
    """
    Convert OKLCH(L, C, H°) → sRGB hex string.

    L: lightness 0–1
    C: chroma 0–0.4 (typically)
    H_deg: hue angle in degrees
    """
    H = math.radians(H_deg)
    a = C * math.cos(H)
    b = C * math.sin(H)

    # OKLab → LMS (cube roots)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b

    l = l_ ** 3
    m = m_ ** 3
    s = s_ ** 3

    # LMS → Linear sRGB
    r =  4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    b_lin = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

    # Linear sRGB → gamma-corrected sRGB
    def _gamma(c: float) -> float:
        c = max(0.0, min(1.0, c))
        if c <= 0.0031308:
            return 12.92 * c
        return 1.055 * (c ** (1.0 / 2.4)) - 0.055

    r_s = _gamma(r)
    g_s = _gamma(g)
    b_s = _gamma(b_lin)

    return f"#{int(round(r_s * 255)):02X}{int(round(g_s * 255)):02X}{int(round(b_s * 255)):02X}"


def _parse_oklch(oklch_str: str) -> Optional[Tuple[float, float, float]]:
    """
    Parse 'oklch(0.949 0.025 285.95)' → (L, C, H).
    Returns None on parse failure.
    """
    s = oklch_str.strip()
    if not s.lower().startswith("oklch("):
        return None
    inner = s[6:].rstrip(")")
    parts = inner.split()
    if len(parts) < 3:
        return None
    try:
        return float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError:
        return None


# ── Source 1: tints.dev API ───────────────────────────────────────────────────

def _fetch_tints_dev(hex_color: str, timeout: int = 8) -> Optional[Dict[int, str]]:
    """
    Fetch 11-stop shade scale from tints.dev.

    Args:
        hex_color: Hex color string (with or without '#')
        timeout:   Request timeout in seconds

    Returns:
        Dict mapping shade stop (50, 100, ..., 950) → hex string, or None on failure.
    """
    h = hex_color.lstrip("#").upper()
    url = f"https://www.tints.dev/api/brand/{h}"

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; BrandBot/1.0)",
                "Accept":     "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # Response: {"brand": {"50": "oklch(...)", "100": "oklch(...)", ...}}
        palette_data = data.get("brand", data)  # handle both response shapes
        if not palette_data:
            return None

        result: Dict[int, str] = {}
        for stop_str, color_val in palette_data.items():
            try:
                stop = int(stop_str)
            except ValueError:
                continue

            # Convert OKLCH → hex
            parsed = _parse_oklch(str(color_val))
            if parsed:
                L, C, H = parsed
                result[stop] = _oklch_to_hex(L, C, H)
            elif str(color_val).startswith("#"):
                # Already a hex value
                result[stop] = str(color_val).upper()

        if len(result) >= 5:
            return result

    except Exception:
        pass

    return None


# ── Source 2: HSL algorithm ───────────────────────────────────────────────────

def _hex_to_hsl(hex_str: str) -> Tuple[float, float, float]:
    """hex → HSL (H: 0–360, S: 0–1, L: 0–1)"""
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    mx, mn = max(r, g, b), min(r, g, b)
    delta = mx - mn
    L = (mx + mn) / 2
    S = 0.0 if delta == 0 else delta / (1 - abs(2 * L - 1))
    if delta == 0:
        H = 0.0
    elif mx == r:
        H = 60 * (((g - b) / delta) % 6)
    elif mx == g:
        H = 60 * (((b - r) / delta) + 2)
    else:
        H = 60 * (((r - g) / delta) + 4)
    return H, S, L


def _hsl_to_hex(H: float, S: float, L: float) -> str:
    """HSL (H: 0–360, S: 0–1, L: 0–1) → hex"""
    C = (1 - abs(2 * L - 1)) * S
    X = C * (1 - abs((H / 60) % 2 - 1))
    m = L - C / 2
    if   H < 60:  r, g, b = C, X, 0
    elif H < 120: r, g, b = X, C, 0
    elif H < 180: r, g, b = 0, C, X
    elif H < 240: r, g, b = 0, X, C
    elif H < 300: r, g, b = X, 0, C
    else:         r, g, b = C, 0, X
    return f"#{int((r+m)*255):02X}{int((g+m)*255):02X}{int((b+m)*255):02X}"


def _generate_shades_hsl(hex_color: str) -> Dict[int, str]:
    """
    Generate 11-stop shade scale using HSL interpolation.

    Maps each stop to a target lightness value (Tailwind-aligned):
      50  → ~96%   (almost white)
      500 → base color lightness
      950 → ~4%    (almost black)

    Slightly desaturates very light and dark stops for naturalness.
    """
    H, S, L_base = _hex_to_hsl(hex_color)

    # Target lightness for each stop
    target_L = {
        50:  0.960,
        100: 0.910,
        200: 0.820,
        300: 0.700,
        400: 0.580,
        500: L_base,          # anchor: base color
        600: L_base * 0.78,
        700: L_base * 0.58,
        800: L_base * 0.40,
        900: L_base * 0.24,
        950: L_base * 0.14,
    }

    # Saturation curve: reduce saturation at extremes for realism
    target_S = {
        50:  S * 0.20,
        100: S * 0.35,
        200: S * 0.55,
        300: S * 0.75,
        400: S * 0.90,
        500: S,
        600: S * 0.95,
        700: S * 0.90,
        800: S * 0.82,
        900: S * 0.70,
        950: S * 0.55,
    }

    result: Dict[int, str] = {}
    for stop in SHADE_STOPS:
        lum = max(0.02, min(0.98, target_L[stop]))
        sat = max(0.0,  min(1.0,  target_S[stop]))
        result[stop] = _hsl_to_hex(H, sat, lum)

    return result


# ── Public API ────────────────────────────────────────────────────────────────

def generate_shade_scale(
    hex_color: str,
    name: str = "",
    use_api: bool = True,
) -> Dict[int, str]:
    """
    Generate 11-stop shade scale for a single color.

    Tries tints.dev API first (OKLCH, perceptually uniform),
    falls back to HSL algorithm if the API is unavailable.

    Args:
        hex_color: Base hex color (e.g. '#2C3E50')
        name:      Color name (for logging)
        use_api:   If False, skip API and use HSL directly

    Returns:
        Dict: {50: "#hex", 100: "#hex", ..., 950: "#hex"}
    """
    if use_api:
        api_result = _fetch_tints_dev(hex_color)
        if api_result:
            # Fill any missing stops with HSL
            hsl_result = _generate_shades_hsl(hex_color)
            for stop in SHADE_STOPS:
                if stop not in api_result:
                    api_result[stop] = hsl_result[stop]
            return dict(sorted(api_result.items()))

    return dict(sorted(_generate_shades_hsl(hex_color).items()))


def generate_palette_shades(
    enriched_colors: List[Dict],
    use_api: bool = True,
) -> Dict[str, Dict[int, str]]:
    """
    Generate shade scales for every color in a palette.

    Args:
        enriched_colors: List of color dicts (hex, name, role, cmyk, source)
        use_api:         Whether to try tints.dev API

    Returns:
        Dict: {color_name: {50: "#hex", 100: "#hex", ..., 950: "#hex"}}
    """
    result: Dict[str, Dict[int, str]] = {}
    for color in enriched_colors:
        hex_val = color.get("hex", "#888888")
        name    = color.get("name", hex_val)
        role    = color.get("role", "")
        key     = f"{name} ({role})" if role else name

        shades = generate_shade_scale(hex_val, name=key, use_api=use_api)
        result[key] = shades

    return result


# ── Shade image renderer ───────────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        [
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ] if bold else [
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _brightness(hex_str: str) -> float:
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


def render_shade_image(
    palette_shades: Dict[str, Dict[int, str]],
    enriched_colors: Optional[List[Dict]] = None,
    width: int = 2400,
    row_height: int = 140,
    header_height: int = 56,
) -> Image.Image:
    """
    Render shade scales as a grid image.

    Layout:
      - One row per palette color
      - 11 columns (50 → 950) + 1 name column on the left
      - Stop number (50, 100...) above each swatch
      - Hex value below each swatch
      - Base color (500) highlighted with a bold border

    Args:
        palette_shades:  Output from generate_palette_shades()
        enriched_colors: Original palette for role labels (optional)
        width:           Total image width
        row_height:      Height of each shade row
        header_height:   Height of the stop-label header row

    Returns:
        PIL Image (RGB)
    """
    n_rows   = len(palette_shades)
    n_stops  = len(SHADE_STOPS)
    NAME_COL = 160    # width of the name column on the left
    GAP      = 2      # gap between swatches
    BG       = (12, 12, 16)
    total_h  = header_height + n_rows * (row_height + GAP)

    img  = Image.new("RGB", (width, total_h), BG)
    draw = ImageDraw.Draw(img)

    swatch_w = (width - NAME_COL - (n_stops - 1) * GAP) // n_stops
    remainder = width - NAME_COL - (n_stops - 1) * GAP - swatch_w * n_stops

    font_hdr   = _load_font(18, bold=True)
    font_stop  = _load_font(15)
    font_hex   = _load_font(13)
    font_name  = _load_font(15, bold=True)
    font_role  = _load_font(12)

    # ── Header row: stop labels ──────────────────────────────────────────────
    draw.text((8, 16), "SHADE SCALE", fill=(70, 70, 85), font=font_hdr)
    for si, stop in enumerate(SHADE_STOPS):
        sx = NAME_COL + si * (swatch_w + GAP) + (remainder if si == n_stops - 1 else 0)
        sw = swatch_w + (remainder if si == n_stops - 1 else 0)
        label = str(stop)
        try:
            bb = draw.textbbox((0, 0), label, font=font_stop)
            lw = bb[2] - bb[0]
        except Exception:
            lw = len(label) * 9
        draw.text(
            (sx + (sw - lw) // 2, (header_height - 20) // 2),
            label,
            fill=(80, 80, 95),
            font=font_stop,
        )

    # ── Role lookup ──────────────────────────────────────────────────────────
    role_map: Dict[str, str] = {}
    if enriched_colors:
        for c in enriched_colors:
            name = c.get("name", "")
            role = c.get("role", "")
            if name and role:
                role_map[name] = role

    # ── Shade rows ───────────────────────────────────────────────────────────
    for row_i, (color_key, shades) in enumerate(palette_shades.items()):
        row_y = header_height + row_i * (row_height + GAP)

        # Name column (dark bg)
        draw.rectangle([0, row_y, NAME_COL - 1, row_y + row_height - 1], fill=(20, 20, 26))
        name_display = color_key.split(" (")[0]   # strip role suffix
        role_display = ""
        if "(" in color_key:
            role_display = color_key.split("(")[1].rstrip(")")

        # Center the name vertically
        try:
            bb = draw.textbbox((0, 0), name_display, font=font_name)
            nh = bb[3] - bb[1]
        except Exception:
            nh = 16
        name_y = row_y + (row_height - nh) // 2 - (10 if role_display else 0)
        draw.text((10, name_y), name_display, fill=(200, 200, 210), font=font_name)
        if role_display:
            draw.text((10, name_y + nh + 4), role_display.upper(), fill=(80, 80, 95), font=font_role)

        # Swatch cells
        for si, stop in enumerate(SHADE_STOPS):
            hex_val = shades.get(stop, "#888888")
            sw      = swatch_w + (remainder if si == n_stops - 1 else 0)
            sx      = NAME_COL + si * (swatch_w + GAP)

            br    = _brightness(hex_val)
            h     = hex_val.lstrip("#")
            r_int = int(h[0:2], 16)
            g_int = int(h[2:4], 16)
            b_int = int(h[4:6], 16)

            # Swatch fill
            draw.rectangle([sx, row_y, sx + sw - 1, row_y + row_height - 1], fill=(r_int, g_int, b_int))

            # Highlight base stop (500) with inner border
            if stop == 500:
                border_col = (255, 255, 255) if br < 128 else (0, 0, 0)
                draw.rectangle(
                    [sx + 2, row_y + 2, sx + sw - 3, row_y + row_height - 3],
                    outline=border_col,
                    width=2,
                )

            # Hex label at bottom
            text_col = (255, 255, 255) if br < 145 else (20, 20, 20)
            hex_label = hex_val.upper()
            try:
                bb = draw.textbbox((0, 0), hex_label, font=font_hex)
                lw = bb[2] - bb[0]
            except Exception:
                lw = len(hex_label) * 8
            draw.text(
                (sx + (sw - lw) // 2, row_y + row_height - 22),
                hex_label,
                fill=text_col,
                font=font_hex,
            )

    return img


def render_shade_scale(
    palette_shades: Dict[str, Dict[int, str]],
    output_path: Union[str, Path],
    enriched_colors: Optional[List[Dict]] = None,
    width: int = 2400,
) -> Path:
    """
    Render shade scales and save as PNG.

    Args:
        palette_shades:  Output from generate_palette_shades()
        output_path:     Where to save the PNG
        enriched_colors: Original palette for role labels (optional)
        width:           Image width (default 2400px)

    Returns:
        Path to saved PNG.
    """
    img = render_shade_image(
        palette_shades,
        enriched_colors=enriched_colors,
        width=width,
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out), "PNG")
    return out
