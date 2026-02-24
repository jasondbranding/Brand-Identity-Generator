"""
Compositor — assembles the final stylescape PNG using Pillow.

Pipeline per direction:
  1. build_phone_mockup()   — logo + pattern applied onto a drawn phone frame
  2. build_card_mockup()    — logo applied onto a brand-colored card
  3. build_typo_panel()     — typography specimen panel
  4. assemble_stylescape()  — combines all zones into 2400×1440 final PNG

Canvas layout (2400 × 1440):
  ┌──────────────────────────┬─────────────────┐  ← row 1: 960px tall
  │  BACKGROUND (1500×960)   │  INFO (900×960) │
  │  Gemini scene            │  title          │
  │                          │  swatches       │
  │                          │  logo           │
  ├──────────────────────────┴─────────────────┤  ← row 2: 480px tall
  │ PHONE (800×480) │ CARD (800×480) │ TYPO (800×480) │
  └─────────────────┴────────────────┴───────────────┘
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .director import BrandDirection, ColorSwatch
from .generator import DirectionAssets

# ── Canvas dimensions ─────────────────────────────────────────────────────────
W, H         = 2400, 1440
ROW1_H       = 960
ROW2_H       = H - ROW1_H          # 480
BG_W         = 1500
INFO_W       = W - BG_W            # 900
ZONE_W       = W // 3              # 800 each

PAD          = 40   # general padding


# ── Font loading ──────────────────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Try macOS system fonts; fall back to Pillow default."""
    candidates = [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Helvetica Neue.ttf",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/SFNSDisplay.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    h = hex_str.strip("#")
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return (128, 128, 128)


def _brightness(rgb: Tuple[int, int, int]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _contrasting_text(bg_rgb: Tuple[int, int, int]) -> Tuple[int, int, int]:
    return (255, 255, 255) if _brightness(bg_rgb) < 128 else (20, 20, 20)


def _wrap_text(text: str, max_chars: int) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current = (current + " " + word).strip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ── Zone builders ─────────────────────────────────────────────────────────────

def _build_info_panel(direction: BrandDirection) -> Image.Image:
    """900×960: direction title, type badge, rationale, swatches, logo thumbnail."""
    # Background: brand primary color (darkened)
    primary_rgb = _hex_to_rgb(direction.colors[0].hex)
    # Darken significantly for panel bg
    bg_rgb = tuple(max(0, int(c * 0.25)) for c in primary_rgb)
    img = Image.new("RGB", (INFO_W, ROW1_H), bg_rgb)
    draw = ImageDraw.Draw(img)

    accent_rgb  = _hex_to_rgb(direction.colors[1].hex) if len(direction.colors) > 1 else (200, 200, 200)
    text_color  = (240, 240, 240)
    muted_color = (160, 160, 160)

    y = PAD

    # ── Direction name ────────────────────────────────────────────────────────
    font_title = _load_font(52)
    name = direction.direction_name.upper()
    for line in _wrap_text(name, 22):
        draw.text((PAD, y), line, fill=text_color, font=font_title)
        y += 62
    y += 8

    # ── Option type badge ─────────────────────────────────────────────────────
    font_badge = _load_font(22)
    badge_text = f"  {direction.option_type.upper()}  "
    bbox = draw.textbbox((PAD, y), badge_text, font=font_badge)
    bw = bbox[2] - bbox[0] + 16
    bh = bbox[3] - bbox[1] + 10
    draw.rounded_rectangle([PAD, y, PAD + bw, y + bh], radius=6, fill=accent_rgb)
    draw.text((PAD + 8, y + 5), badge_text.strip(), fill=_contrasting_text(accent_rgb), font=font_badge)
    y += bh + 24

    # ── Rationale ─────────────────────────────────────────────────────────────
    font_body = _load_font(22)
    for line in _wrap_text(direction.rationale, 46):
        draw.text((PAD, y), line, fill=muted_color, font=font_body)
        y += 28
    y += 20

    # ── Separator ─────────────────────────────────────────────────────────────
    draw.line([(PAD, y), (INFO_W - PAD, y)], fill=(80, 80, 80), width=1)
    y += 20

    # ── Color swatches ────────────────────────────────────────────────────────
    font_label = _load_font(18)
    draw.text((PAD, y), "COLOR PALETTE", fill=muted_color, font=font_label)
    y += 28

    swatch_size = 44
    swatch_gap  = 10
    x = PAD
    for swatch in direction.colors[:6]:
        rgb = _hex_to_rgb(swatch.hex)
        draw.rounded_rectangle([x, y, x + swatch_size, y + swatch_size], radius=6, fill=rgb)
        # hex label below swatch
        draw.text((x, y + swatch_size + 4), swatch.hex, fill=muted_color, font=_load_font(14))
        x += swatch_size + swatch_gap
    y += swatch_size + 28

    # ── Separator ─────────────────────────────────────────────────────────────
    draw.line([(PAD, y), (INFO_W - PAD, y)], fill=(80, 80, 80), width=1)
    y += 20

    # ── Logo concept text (no image in this panel — logo goes in main bg area) ─
    draw.text((PAD, y), "LOGO CONCEPT", fill=muted_color, font=font_label)
    y += 28
    font_small = _load_font(20)
    for line in _wrap_text(direction.logo_concept, 46):
        draw.text((PAD, y), line, fill=(180, 180, 180), font=font_small)
        y += 26

    return img


def _build_background_zone(assets: DirectionAssets) -> Image.Image:
    """1500×960: Gemini background scene, or gradient fallback."""
    if assets.background and assets.background.stat().st_size > 100:
        try:
            img = Image.open(assets.background).convert("RGB")
            return img.resize((BG_W, ROW1_H), Image.LANCZOS)
        except Exception:
            pass
    # Fallback gradient from palette
    return _make_gradient(BG_W, ROW1_H, assets.direction.colors)


def _make_gradient(w: int, h: int, colors: List[ColorSwatch]) -> Image.Image:
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    c1 = _hex_to_rgb(colors[0].hex)
    c2 = _hex_to_rgb(colors[1].hex) if len(colors) > 1 else (20, 20, 30)
    for x in range(w):
        t = x / w
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        draw.line([(x, 0), (x, h)], fill=(r, g, b))
    return img


def build_phone_mockup(assets: DirectionAssets) -> Image.Image:
    """
    800×480: phone frame with brand pattern on screen and logo centered.
    """
    W_Z, H_Z = ZONE_W, ROW2_H
    bg_rgb = (15, 15, 20)
    img = Image.new("RGB", (W_Z, H_Z), bg_rgb)
    draw = ImageDraw.Draw(img)

    # Phone body dimensions (centered in zone)
    ph_w, ph_h = 200, 380
    ph_x = (W_Z - ph_w) // 2
    ph_y = (H_Z - ph_h) // 2

    body_rgb = (40, 40, 48)
    draw.rounded_rectangle([ph_x, ph_y, ph_x + ph_w, ph_y + ph_h],
                            radius=28, fill=body_rgb)

    # Screen area
    scr_pad = 12
    scr_x  = ph_x + scr_pad
    scr_y  = ph_y + scr_pad + 18   # top notch offset
    scr_w  = ph_w - scr_pad * 2
    scr_h  = ph_h - scr_pad * 2 - 30

    # Fill screen with pattern (or brand color)
    primary_rgb = _hex_to_rgb(assets.direction.colors[0].hex)
    screen_img = Image.new("RGB", (scr_w, scr_h), primary_rgb)

    if assets.pattern and assets.pattern.stat().st_size > 100:
        try:
            pat = Image.open(assets.pattern).convert("RGB")
            pat = pat.resize((scr_w, scr_h), Image.LANCZOS)
            # Blend pattern over primary color at 40% opacity
            screen_img = Image.blend(screen_img, pat, alpha=0.4)
        except Exception:
            pass

    # Overlay logo centered on screen
    if assets.logo and assets.logo.stat().st_size > 100:
        try:
            logo = Image.open(assets.logo).convert("RGBA")
            logo_size = min(scr_w, scr_h) // 2
            logo = logo.resize((logo_size, logo_size), Image.LANCZOS)
            lx = (scr_w - logo_size) // 2
            ly = (scr_h - logo_size) // 2
            # White backing circle
            backing = Image.new("RGBA", (logo_size, logo_size), (255, 255, 255, 200))
            screen_img.paste(backing, (lx, ly), backing)
            screen_img.paste(logo, (lx, ly), logo)
        except Exception:
            pass

    img.paste(screen_img, (scr_x, scr_y))

    # Notch
    notch_rgb = (20, 20, 26)
    draw.rounded_rectangle([ph_x + ph_w//2 - 28, ph_y + 8, ph_x + ph_w//2 + 28, ph_y + 22],
                            radius=7, fill=notch_rgb)
    # Home indicator
    draw.rounded_rectangle([ph_x + ph_w//2 - 30, ph_y + ph_h - 18,
                             ph_x + ph_w//2 + 30, ph_y + ph_h - 10],
                            radius=4, fill=(80, 80, 88))
    # Label
    font = _load_font(18)
    draw.text((W_Z // 2 - 50, H_Z - 28), "APP MOCKUP", fill=(100, 100, 110), font=font)

    return img


def build_card_mockup(assets: DirectionAssets) -> Image.Image:
    """
    800×480: business card with brand colors and logo.
    """
    W_Z, H_Z = ZONE_W, ROW2_H
    bg_rgb = (20, 20, 26)
    img = Image.new("RGB", (W_Z, H_Z), bg_rgb)
    draw = ImageDraw.Draw(img)

    card_w, card_h = 440, 260
    card_x = (W_Z - card_w) // 2
    card_y = (H_Z - card_h) // 2

    primary_rgb = _hex_to_rgb(assets.direction.colors[0].hex)
    accent_rgb  = _hex_to_rgb(assets.direction.colors[1].hex) if len(assets.direction.colors) > 1 else (200, 200, 200)

    # Card body
    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                            radius=14, fill=primary_rgb)

    # Accent strip at bottom
    strip_h = 40
    draw.rounded_rectangle([card_x, card_y + card_h - strip_h,
                             card_x + card_w, card_y + card_h],
                            radius=14, fill=accent_rgb)
    # Mask off top corners of strip
    draw.rectangle([card_x, card_y + card_h - strip_h,
                    card_x + card_w, card_y + card_h - strip_h + 14],
                   fill=accent_rgb)

    # Pattern texture on card
    if assets.pattern and assets.pattern.stat().st_size > 100:
        try:
            pat = Image.open(assets.pattern).convert("RGBA")
            pat = pat.resize((card_w, card_h), Image.LANCZOS)
            pat.putalpha(30)  # very subtle
            card_canvas = Image.new("RGBA", img.size, (0, 0, 0, 0))
            card_canvas.paste(pat, (card_x, card_y))
            img = img.convert("RGBA")
            img.alpha_composite(card_canvas)
            img = img.convert("RGB")
            draw = ImageDraw.Draw(img)
        except Exception:
            pass

    # Logo on card
    if assets.logo and assets.logo.stat().st_size > 100:
        try:
            logo = Image.open(assets.logo).convert("RGBA")
            logo_size = 80
            logo = logo.resize((logo_size, logo_size), Image.LANCZOS)
            lx = card_x + 24
            ly = card_y + (card_h - strip_h - logo_size) // 2
            img.paste(logo, (lx, ly), logo)
        except Exception:
            pass

    # Brand name text on card
    text_color = _contrasting_text(primary_rgb)
    font_name = _load_font(26)
    font_small = _load_font(16)

    # Extract brand name from direction name (first word or two)
    brand_name = assets.direction.direction_name.upper()
    tx = card_x + 120
    ty = card_y + card_h // 2 - 28
    draw.text((tx, ty), brand_name[:20], fill=text_color, font=font_name)
    draw.text((tx, ty + 36), "Brand Identity", fill=_hex_to_rgb(
        assets.direction.colors[2].hex if len(assets.direction.colors) > 2 else "#999999"
    ), font=font_small)

    font_label = _load_font(18)
    draw.text((W_Z // 2 - 65, H_Z - 28), "BRAND CARD", fill=(100, 100, 110), font=font_label)

    return img


def build_typo_panel(direction: BrandDirection) -> Image.Image:
    """
    800×480: typography specimen showing primary + secondary type.
    """
    W_Z, H_Z = ZONE_W, ROW2_H

    # Dark background
    dark_rgb = (12, 12, 18)
    img = Image.new("RGB", (W_Z, H_Z), dark_rgb)
    draw = ImageDraw.Draw(img)

    accent_rgb   = _hex_to_rgb(direction.colors[1].hex) if len(direction.colors) > 1 else (180, 180, 180)
    primary_rgb  = _hex_to_rgb(direction.colors[0].hex)
    text_color   = (230, 230, 235)
    muted        = (120, 120, 130)

    y = PAD

    # ── Primary font specimen ─────────────────────────────────────────────────
    # Extract just the font name (before the colon/comma)
    primary_name = re.split(r"[,:—]", direction.typography_primary)[0].strip()
    font_label   = _load_font(16)
    draw.text((PAD, y), "PRIMARY", fill=accent_rgb, font=font_label)
    y += 24

    font_display = _load_font(64)
    draw.text((PAD, y), "Aa Gg 01", fill=text_color, font=font_display)
    y += 72

    font_name_disp = _load_font(22)
    draw.text((PAD, y), primary_name, fill=muted, font=font_name_disp)
    y += 32

    # Separator
    draw.line([(PAD, y), (W_Z - PAD, y)], fill=(50, 50, 60), width=1)
    y += 20

    # ── Secondary font specimen ────────────────────────────────────────────────
    secondary_name = re.split(r"[,:—]", direction.typography_secondary)[0].strip()
    draw.text((PAD, y), "SECONDARY", fill=primary_rgb, font=font_label)
    y += 24

    font_body = _load_font(28)
    draw.text((PAD, y), "The quick signal moves.", fill=(190, 190, 200), font=font_body)
    y += 36
    draw.text((PAD, y), "Human-first data design.", fill=(140, 140, 150), font=_load_font(22))
    y += 32

    font_sec_name = _load_font(20)
    draw.text((PAD, y), secondary_name, fill=muted, font=font_sec_name)

    # "TYPOGRAPHY" label at bottom
    font_footer = _load_font(18)
    draw.text((W_Z // 2 - 55, H_Z - 28), "TYPOGRAPHY", fill=(70, 70, 80), font=font_footer)

    return img


# ── Full stylescape assembly ──────────────────────────────────────────────────

def assemble_stylescape(
    assets: DirectionAssets,
    output_dir: Path,
) -> Path:
    """
    Compose all zones into the 2400×1440 stylescape PNG.
    Returns path to saved stylescape.
    """
    canvas = Image.new("RGB", (W, H), (8, 8, 12))

    # ── Row 1 ─────────────────────────────────────────────────────────────────
    bg_zone   = _build_background_zone(assets)
    info_zone = _build_info_panel(assets.direction)
    canvas.paste(bg_zone,   (0, 0))
    canvas.paste(info_zone, (BG_W, 0))

    # ── Row 2 ─────────────────────────────────────────────────────────────────
    phone_zone = build_phone_mockup(assets)
    card_zone  = build_card_mockup(assets)
    typo_zone  = build_typo_panel(assets.direction)

    canvas.paste(phone_zone, (0,          ROW1_H))
    canvas.paste(card_zone,  (ZONE_W,     ROW1_H))
    canvas.paste(typo_zone,  (ZONE_W * 2, ROW1_H))

    # ── Thin separators ───────────────────────────────────────────────────────
    draw = ImageDraw.Draw(canvas)
    sep = (40, 40, 48)
    draw.line([(BG_W, 0), (BG_W, ROW1_H)],           fill=sep, width=1)
    draw.line([(0, ROW1_H), (W, ROW1_H)],             fill=sep, width=1)
    draw.line([(ZONE_W, ROW1_H), (ZONE_W, H)],        fill=sep, width=1)
    draw.line([(ZONE_W * 2, ROW1_H), (ZONE_W * 2, H)], fill=sep, width=1)

    # ── Option logo image inset over background (top-right of bg zone) ────────
    if assets.logo and assets.logo.stat().st_size > 100:
        try:
            logo = Image.open(assets.logo).convert("RGBA")
            logo_size = 220
            logo = logo.resize((logo_size, logo_size), Image.LANCZOS)
            # Semi-transparent white pill behind logo for contrast
            pill = Image.new("RGBA", (logo_size + 40, logo_size + 40), (255, 255, 255, 180))
            lx = BG_W - logo_size - 60
            ly = ROW1_H - logo_size - 60
            canvas.paste(
                Image.new("RGB", (logo_size + 40, logo_size + 40), (255, 255, 255)),
                (lx - 20, ly - 20),
            )
            canvas.paste(logo, (lx, ly), logo)
        except Exception:
            pass

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
        all_assets: Dict mapping option_number → DirectionAssets
        output_dir: Where to save stylescape PNGs

    Returns:
        Dict mapping option_number → stylescape Path
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stylescapes = {}

    for num, assets in all_assets.items():
        from rich.console import Console
        console = Console()
        console.print(f"  [cyan]Compositing stylescape for Option {num}: {assets.direction.direction_name}...[/cyan]")
        path = assemble_stylescape(assets, output_dir)
        stylescapes[num] = path
        console.print(f"  [green]✓ Saved → {path.name}[/green]")

    return stylescapes
