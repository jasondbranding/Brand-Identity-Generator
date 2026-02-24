"""
mockup_compositor.py — Per-mockup art direction with pixel-mask compositing.

Placeholder color system:
  Magenta  #FF00FF  → logo_area
  Cyan     #00FFFF  → text_area
  Yellow   #FFFF00  → surface_area

Processing uses pixel masks (exact shape) rather than bounding boxes, so
perspective shapes, parallelograms, and rounded corners are preserved.

Per-mockup handlers dispatch on filename and apply specific art direction.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from google import genai
from google.genai import types as genai_types

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
from rich.console import Console

from .director import BrandDirection
from .generator import DirectionAssets

console = Console()

# ── Constants ─────────────────────────────────────────────────────────────────

METADATA_PATH = Path("mockups/metadata.json")
PROCESSED_DIR = Path("mockups/processed")
IMAGE_EXTS    = {".png", ".jpg", ".jpeg", ".webp"}

MAGENTA   = (255,   0, 255)
CYAN      = (  0, 255, 255)
YELLOW    = (255, 255,   0)
TOLERANCE = 30
MIN_PX    = 50

Handler = Callable[
    [Image.Image, Image.Image, "DirectionAssets", np.ndarray], str
]


# ── Basic colour helpers ───────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.strip("#")
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _brightness(rgb: Tuple[int, int, int]) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _is_dark(rgb: Tuple[int, int, int]) -> bool:
    return _brightness(rgb) < 128


def _contrasting(bg: Tuple[int, int, int]) -> Tuple[int, int, int]:
    return (255, 255, 255) if _is_dark(bg) else (20, 20, 20)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:30]


# ── Pixel-mask utilities ───────────────────────────────────────────────────────

def _make_mask(
    arr: np.ndarray,
    color: Tuple[int, int, int],
    tol: int = TOLERANCE,
) -> np.ndarray:
    """Boolean (H, W) mask: True where pixels match color ± tol per channel."""
    rgb = arr[:, :, :3].astype(np.int16)
    r, g, b = color
    return (
        (np.abs(rgb[:, :, 0] - r) <= tol) &
        (np.abs(rgb[:, :, 1] - g) <= tol) &
        (np.abs(rgb[:, :, 2] - b) <= tol)
    )


def _mask_bbox(mask: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """(x1, y1, x2, y2) bounding box of True pixels, or None."""
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any():
        return None
    y1 = int(np.argmax(rows))
    y2 = int(len(rows) - 1 - np.argmax(rows[::-1]))
    x1 = int(np.argmax(cols))
    x2 = int(len(cols) - 1 - np.argmax(cols[::-1]))
    return (x1, y1, x2, y2)


def _sample_surrounding(
    arr: np.ndarray,
    mask: np.ndarray,
    border: int = 8,
) -> Tuple[int, int, int]:
    """Median colour of pixels adjacent to (but not inside) mask."""
    mimg    = Image.fromarray((mask * 255).astype(np.uint8), "L")
    dilated = np.array(mimg.filter(ImageFilter.MaxFilter(border * 2 + 1))) > 128
    pixels  = arr[:, :, :3][dilated & ~mask]
    if len(pixels) < 5:
        return (80, 80, 80)
    med = np.median(pixels, axis=0).astype(int)
    return (int(med[0]), int(med[1]), int(med[2]))


def _fill_mask(
    canvas: Image.Image,
    mask: np.ndarray,
    fill: Tuple[int, int, int],
) -> None:
    """Fill all mask-True pixels with solid colour in-place."""
    arr = np.array(canvas)
    arr[mask, 0] = fill[0]
    arr[mask, 1] = fill[1]
    arr[mask, 2] = fill[2]
    arr[mask, 3] = 255
    canvas.paste(Image.fromarray(arr, "RGBA"), (0, 0))


def _cover_fill(
    canvas: Image.Image,
    src: Image.Image,
    mask: np.ndarray,
    bbox: Tuple[int, int, int, int],
) -> None:
    """Cover-fit src into bbox, then paste only where mask is True."""
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return
    iw, ih = src.size
    scale = max(w / iw, h / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    resized = src.resize((nw, nh), Image.LANCZOS)
    ox, oy = (nw - w) // 2, (nh - h) // 2
    crop = resized.crop((ox, oy, ox + w, oy + h)).convert("RGBA")
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(crop, (x1, y1))
    mp = Image.fromarray((mask * 255).astype(np.uint8), "L")
    canvas.paste(layer, (0, 0), mp)


def _replace_placeholder_zone(
    canvas: Image.Image,
    arr: np.ndarray,
    color: Tuple[int, int, int],
    tol: int = TOLERANCE,
) -> Tuple[np.ndarray, Optional[Tuple[int, int, int, int]]]:
    """
    Canonical placeholder eraser — MUST be called before placing any content.

    Steps:
      1. Scan entire image for pixels near *color* (±tol per channel).
      2. Build boolean pixel mask (True = placeholder pixel).
      3. Sample median colour of border pixels OUTSIDE the mask (5-px dilation)
         to find the natural surrounding fill colour.
      4. Overwrite ALL masked pixels with that surrounding colour.
      5. Return (mask, bbox) so the caller can composite logos / text / images
         on top of the now-clean surface.

    Guarantees placeholder pixels are replaced at pixel level — not bounding-box
    rectangle — so perspective strips, parallelograms, and rounded corners are
    all erased exactly.
    """
    mask = _make_mask(arr, color, tol)
    if mask.sum() < MIN_PX:
        return mask, None
    fill = _sample_surrounding(arr, mask)
    _fill_mask(canvas, mask, fill)
    return mask, _mask_bbox(mask)


# ── Logo processing utilities ─────────────────────────────────────────────────

def _remove_white(logo: Image.Image, thresh: int = 240) -> Image.Image:
    """Near-white pixels → transparent, anti-aliasing edges preserved."""
    logo = logo.convert("RGBA")
    arr  = np.array(logo).astype(np.float32)
    br   = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    scale = np.clip((thresh - br) / 30.0, 0.0, 1.0)
    arr[:, :, 3] = (arr[:, :, 3] * scale).clip(0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def _colorize(logo: Image.Image, color: Tuple[int, int, int]) -> Image.Image:
    """Set all opaque pixels to a solid colour, keeping original alpha."""
    arr = np.array(logo.convert("RGBA"))
    result = arr.copy()
    result[:, :, 0] = color[0]
    result[:, :, 1] = color[1]
    result[:, :, 2] = color[2]
    return Image.fromarray(result, "RGBA")


def _fit(
    logo: Image.Image,
    bw: int,
    bh: int,
    ratio: float = 0.65,
) -> Image.Image:
    """Resize logo to fit in (bw*ratio) × (bh*ratio), aspect-ratio preserved."""
    tw = max(1, int(bw * ratio))
    th = max(1, int(bh * ratio))
    logo = logo.copy()
    logo.thumbnail((tw, th), Image.LANCZOS)
    return logo


def _opacity(img: Image.Image, op: float) -> Image.Image:
    """Scale alpha by op (0–1)."""
    img = img.convert("RGBA")
    arr = np.array(img).astype(np.float32)
    arr[:, :, 3] *= op
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def _paste_center(
    canvas: Image.Image,
    img: Image.Image,
    cx: int,
    cy: int,
) -> Tuple[int, int]:
    """Paste img centred on (cx, cy). Returns top-left corner."""
    x = cx - img.width // 2
    y = cy - img.height // 2
    canvas.paste(img, (x, y), img)
    return x, y


def _paste_bbox_center(
    canvas: Image.Image,
    img: Image.Image,
    x1: int, y1: int, x2: int, y2: int,
) -> None:
    """Paste img centred within bounding box."""
    _paste_center(canvas, img, (x1 + x2) // 2, (y1 + y2) // 2)


def _draw_shadow(
    canvas: Image.Image,
    logo: Image.Image,
    lx: int,
    ly: int,
    off: Tuple[int, int] = (4, 6),
    blur: int = 8,
    alpha: int = 100,
) -> None:
    """Paint blurred black shadow behind logo position on canvas."""
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    logo_arr = np.array(logo)
    sh = np.zeros_like(logo_arr)
    sh[:, :, 3] = (logo_arr[:, :, 3].astype(np.float32) * (alpha / 255.0)).astype(np.uint8)
    sh_img = Image.fromarray(sh, "RGBA")
    shadow.paste(sh_img, (lx + off[0], ly + off[1]), sh_img)
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(shadow)


def _fabric_blend(
    canvas: Image.Image,
    original: Image.Image,
    mask: np.ndarray,
    op: float = 0.18,
) -> None:
    """Multiply-blend original fabric texture over masked region (silk-screen effect)."""
    crgb = canvas.convert("RGB")
    orgb = original.convert("RGB").resize(canvas.size, Image.LANCZOS)
    mul  = ImageChops.multiply(crgb, orgb)
    blended = Image.blend(crgb, mul, op)
    mp = Image.fromarray((mask * 255).astype(np.uint8), "L")
    crgb.paste(blended, (0, 0), mp)
    if canvas.mode == "RGBA":
        r, g, b = crgb.split()
        a = canvas.split()[3]
        canvas.paste(Image.merge("RGBA", (r, g, b, a)), (0, 0))
    else:
        canvas.paste(crgb, (0, 0))


def _draw_text_auto(
    draw: ImageDraw.Draw,
    text: str,
    x1: int, y1: int, x2: int, y2: int,
    fill: Tuple,
    max_size: int = 300,
) -> None:
    """Auto-size font to fit text within bbox, then draw centred."""
    w, h = x2 - x1, y2 - y1
    for fs in range(min(h - 4, max_size), 6, -2):
        font = _load_font(fs)
        tb = draw.textbbox((0, 0), text, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        if tw <= w - 8 and th <= h - 4:
            draw.text(
                ((x1 + x2 - tw) // 2, (y1 + y2 - th) // 2),
                text, fill=fill, font=font,
            )
            return


def _rounded_icon(base: Image.Image, radius_ratio: float = 0.22) -> Image.Image:
    """Apply iOS-style rounded corners (radius = min(w,h) * ratio)."""
    w, h = base.size
    r = int(min(w, h) * radius_ratio)
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    out = base.copy().convert("RGBA")
    out.putalpha(mask)
    return out


# ── Per-mockup art-direction handlers ────────────────────────────────────────
#
# Signature: (canvas, original, assets, arr) -> zones_applied_str
#   canvas   — RGBA working image (modified in-place)
#   original — RGBA source image (read-only reference)
#   assets   — DirectionAssets for this brand direction
#   arr      — np.array(original) uint8 RGBA, shape (H, W, 4)


def _handle_wall_logo(
    canvas: Image.Image,
    original: Image.Image,
    assets: DirectionAssets,
    arr: np.ndarray,
) -> str:
    """
    wall_logo_processed.png
    Magenta parallelogram → surrounding wall colour fill + white logo + drop shadow.
    The parallelogram shape is preserved via pixel mask clipping.
    """
    mask = _make_mask(arr, MAGENTA)
    if mask.sum() < MIN_PX:
        return "no zones"
    bbox = _mask_bbox(mask)
    if not bbox:
        return "no zones"
    x1, y1, x2, y2 = bbox

    # Fill parallelogram with surrounding wall colour
    wall = _sample_surrounding(arr, mask)
    _fill_mask(canvas, mask, wall)

    if not (assets.logo and assets.logo.exists() and assets.logo.stat().st_size > 100):
        return "LOGO (filled)"

    # Prepare white logo
    logo = Image.open(assets.logo).convert("RGBA")
    logo = _remove_white(logo)
    logo = _colorize(logo, (255, 255, 255))
    logo = _fit(logo, x2 - x1, y2 - y1, 0.65)

    # Draw shadow + logo into a layer, then clip to parallelogram mask
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    lx = (x1 + x2) // 2 - logo.width // 2
    ly = (y1 + y2) // 2 - logo.height // 2
    _draw_shadow(layer, logo, lx, ly, off=(4, 6), blur=8, alpha=100)
    layer.paste(logo, (lx, ly), logo)

    # Clip to exact mask shape, then composite onto canvas
    mp = Image.fromarray((mask * 255).astype(np.uint8), "L")
    clipped = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    clipped.paste(layer, (0, 0), mp)
    canvas.alpha_composite(clipped)
    return "LOGO"


def _handle_app_icon(
    canvas: Image.Image,
    original: Image.Image,
    assets: DirectionAssets,
    arr: np.ndarray,
) -> str:
    """
    app_Icon_phone_flat_processed.png
    Magenta → primary colour bg + rounded corners + white logo (iOS icon style).
    Cyan    → black bg + small white brand label.
    """
    direction = assets.direction
    primary   = _hex_to_rgb(direction.colors[0].hex)
    brand     = direction.direction_name.upper()
    zones: List[str] = []

    # ── LOGO (icon) ───────────────────────────────────────────────────────────
    logo_mask = _make_mask(arr, MAGENTA)
    if logo_mask.sum() >= MIN_PX:
        bbox = _mask_bbox(logo_mask)
        if bbox:
            x1, y1, x2, y2 = bbox
            w, h = x2 - x1, y2 - y1
            patch = Image.new("RGBA", (w, h), primary + (255,))
            if assets.logo and assets.logo.exists() and assets.logo.stat().st_size > 100:
                logo = Image.open(assets.logo).convert("RGBA")
                logo = _remove_white(logo)
                logo = _colorize(logo, (255, 255, 255))
                logo = _fit(logo, w, h, 0.65)
                lx = (w - logo.width) // 2
                ly = (h - logo.height) // 2
                patch.paste(logo, (lx, ly), logo)
            patch = _rounded_icon(patch, 0.22)
            # Step 1: ERASE all magenta pixels with surrounding colour.
            # Restoring `original` here would re-introduce magenta at the
            # transparent corners of the rounded patch — wrong.
            sur = _sample_surrounding(arr, logo_mask)
            _fill_mask(canvas, logo_mask, sur)
            # Step 2: Paste rounded patch — transparent corners now show the
            # clean surrounding phone-screen colour, not magenta.
            canvas.paste(patch, (x1, y1), patch)
            zones.append("LOGO")

    # ── TEXT (iOS label below icon) ───────────────────────────────────────────
    text_mask = _make_mask(arr, CYAN)
    if text_mask.sum() >= MIN_PX:
        bbox = _mask_bbox(text_mask)
        if bbox:
            x1, y1, x2, y2 = bbox
            _fill_mask(canvas, text_mask, (0, 0, 0))
            draw = ImageDraw.Draw(canvas)
            _draw_text_auto(
                draw, brand, x1, y1, x2, y2,
                fill=(255, 255, 255),
                max_size=max(8, (y2 - y1) - 4),
            )
            zones.append("TEXT")

    return " + ".join(zones) if zones else "no zones"


def _handle_black_shirt(
    canvas: Image.Image,
    original: Image.Image,
    assets: DirectionAssets,
    arr: np.ndarray,
) -> str:
    """
    black_shirt_logo_processed.png
    Magenta → black fill + small white logo at 90% opacity + fabric multiply blend.
    """
    mask = _make_mask(arr, MAGENTA)
    if mask.sum() < MIN_PX:
        return "no zones"
    bbox = _mask_bbox(mask)
    if not bbox:
        return "no zones"
    x1, y1, x2, y2 = bbox

    _fill_mask(canvas, mask, (0, 0, 0))

    if not (assets.logo and assets.logo.exists() and assets.logo.stat().st_size > 100):
        return "LOGO (filled)"

    logo = Image.open(assets.logo).convert("RGBA")
    logo = _remove_white(logo)
    logo = _colorize(logo, (255, 255, 255))
    logo = _fit(logo, x2 - x1, y2 - y1, 0.45)
    logo = _opacity(logo, 0.90)
    _paste_bbox_center(canvas, logo, x1, y1, x2, y2)
    _fabric_blend(canvas, original, mask, op=0.18)
    return "LOGO"


def _handle_employee_id(
    canvas: Image.Image,
    original: Image.Image,
    assets: DirectionAssets,
    arr: np.ndarray,
) -> str:
    """
    employee_id_card_processed.png
    Magenta → black fill + white logo; if bbox is wide, add brand name to the right.
    Yellow  → brand primary colour (lanyard — pixel mask preserves perspective shape).
    """
    direction = assets.direction
    primary   = _hex_to_rgb(direction.colors[0].hex)
    brand     = direction.direction_name.upper()
    zones: List[str] = []

    # ── LOGO zone ─────────────────────────────────────────────────────────────
    logo_mask = _make_mask(arr, MAGENTA)
    if logo_mask.sum() >= MIN_PX:
        bbox = _mask_bbox(logo_mask)
        if bbox:
            x1, y1, x2, y2 = bbox
            _fill_mask(canvas, logo_mask, (0, 0, 0))
            if assets.logo and assets.logo.exists() and assets.logo.stat().st_size > 100:
                logo = Image.open(assets.logo).convert("RGBA")
                logo = _remove_white(logo)
                logo = _colorize(logo, (255, 255, 255))
                bw, bh = x2 - x1, y2 - y1
                if bw > bh * 3:
                    # Wide bbox → logo left, brand name right
                    logo = _fit(logo, bh, bh, 0.80)
                    lx = x1 + (bh - logo.width) // 2
                    ly = (y1 + y2) // 2 - logo.height // 2
                    canvas.paste(logo, (lx, ly), logo)
                    draw = ImageDraw.Draw(canvas)
                    _draw_text_auto(
                        draw, brand,
                        x1 + bh + 4, y1, x2, y2,
                        fill=(255, 255, 255),
                        max_size=bh - 4,
                    )
                else:
                    logo = _fit(logo, bw, bh, 0.50)
                    _paste_bbox_center(canvas, logo, x1, y1, x2, y2)
            zones.append("LOGO")

    # ── SURFACE zone (lanyard — perspective strip) ────────────────────────────
    surf_mask = _make_mask(arr, YELLOW)
    if surf_mask.sum() >= MIN_PX:
        _fill_mask(canvas, surf_mask, primary)
        zones.append("SURFACE")

    return " + ".join(zones) if zones else "no zones"


def _handle_billboard(
    canvas: Image.Image,
    original: Image.Image,
    assets: DirectionAssets,
    arr: np.ndarray,
) -> str:
    """
    horizontal_billboard_processed.png  — highest visual impact mockup.
    Yellow  → background.png cover-filled; fallback primary colour.
    Magenta → ERASED first (same cover-fill as surface), then logo on top.
    """
    direction = assets.direction
    primary   = _hex_to_rgb(direction.colors[0].hex)
    zones: List[str] = []

    # Load background image once — shared by surface AND logo zones.
    bg_src = None
    if (assets.background and assets.background.exists()
            and assets.background.stat().st_size > 100):
        bg_src = Image.open(assets.background).convert("RGBA")

    # ── SURFACE → background image ────────────────────────────────────────────
    surf_mask = _make_mask(arr, YELLOW)
    if surf_mask.sum() >= MIN_PX:
        bbox = _mask_bbox(surf_mask)
        if bbox:
            if bg_src:
                _cover_fill(canvas, bg_src, surf_mask, bbox)
            else:
                _fill_mask(canvas, surf_mask, primary)
            zones.append("SURFACE")

    # ── LOGO → Step 1: erase ALL magenta pixels; Step 2: paste logo ───────────
    logo_mask = _make_mask(arr, MAGENTA)
    if logo_mask.sum() >= MIN_PX:
        bbox = _mask_bbox(logo_mask)
        if bbox:
            x1, y1, x2, y2 = bbox

            # Step 1: ERASE — cover-fill logo zone with the same background image
            # so the billboard face is seamless (no magenta leaking around logo).
            if bg_src:
                _cover_fill(canvas, bg_src, logo_mask, bbox)
            else:
                _fill_mask(canvas, logo_mask, primary)

            # Step 2: Paste logo — sample post-fill brightness to pick colour.
            if assets.logo and assets.logo.exists() and assets.logo.stat().st_size > 100:
                c_arr   = np.array(canvas)
                area_px = c_arr[logo_mask, :3]
                avg_br  = _brightness(tuple(np.mean(area_px, axis=0).astype(int)))
                logo_color = (255, 255, 255) if avg_br < 128 else (20, 20, 20)

                logo = Image.open(assets.logo).convert("RGBA")
                logo = _remove_white(logo)
                logo = _colorize(logo, logo_color)
                logo = _fit(logo, x2 - x1, y2 - y1, 0.55)
                _paste_bbox_center(canvas, logo, x1, y1, x2, y2)
            zones.append("LOGO")

    return " + ".join(zones) if zones else "no zones"


def _handle_disk(
    canvas: Image.Image,
    original: Image.Image,
    assets: DirectionAssets,
    arr: np.ndarray,
) -> str:
    """
    logo_transparent_disk_processed.png
    Magenta → white fill (acrylic transparent feel) + black logo, clean minimal, no shadow.
    """
    mask = _make_mask(arr, MAGENTA)
    if mask.sum() < MIN_PX:
        return "no zones"
    bbox = _mask_bbox(mask)
    if not bbox:
        return "no zones"
    x1, y1, x2, y2 = bbox

    _fill_mask(canvas, mask, (255, 255, 255))

    if not (assets.logo and assets.logo.exists() and assets.logo.stat().st_size > 100):
        return "LOGO (filled)"

    logo = Image.open(assets.logo).convert("RGBA")
    logo = _remove_white(logo)
    logo = _colorize(logo, (20, 20, 20))
    logo = _fit(logo, x2 - x1, y2 - y1, 0.55)
    _paste_bbox_center(canvas, logo, x1, y1, x2, y2)
    return "LOGO"


def _handle_name_card(
    canvas: Image.Image,
    original: Image.Image,
    assets: DirectionAssets,
    arr: np.ndarray,
) -> str:
    """
    name_card_processed.png
    Yellow  → primary colour fill + large brand name text (high contrast).
    Magenta → white fill + small dark logo on white card face.
    """
    direction = assets.direction
    primary   = _hex_to_rgb(direction.colors[0].hex)
    brand     = direction.direction_name.upper()
    zones: List[str] = []

    # ── SURFACE (coloured card face) → primary + brand name ───────────────────
    surf_mask = _make_mask(arr, YELLOW)
    if surf_mask.sum() >= MIN_PX:
        bbox = _mask_bbox(surf_mask)
        _fill_mask(canvas, surf_mask, primary)
        if bbox:
            x1, y1, x2, y2 = bbox
            draw = ImageDraw.Draw(canvas)
            _draw_text_auto(
                draw, brand, x1, y1, x2, y2,
                fill=_contrasting(primary),
                max_size=200,
            )
        zones.append("SURFACE")

    # ── LOGO (white card face) → white fill + small dark logo ─────────────────
    logo_mask = _make_mask(arr, MAGENTA)
    if logo_mask.sum() >= MIN_PX:
        bbox = _mask_bbox(logo_mask)
        if bbox:
            x1, y1, x2, y2 = bbox
            _fill_mask(canvas, logo_mask, (255, 255, 255))
            if assets.logo and assets.logo.exists() and assets.logo.stat().st_size > 100:
                logo = Image.open(assets.logo).convert("RGBA")
                logo = _remove_white(logo)
                logo = _colorize(logo, (20, 20, 20))
                logo = _fit(logo, x2 - x1, y2 - y1, 0.40)
                _paste_bbox_center(canvas, logo, x1, y1, x2, y2)
            zones.append("LOGO")

    return " + ".join(zones) if zones else "no zones"


def _handle_tote_bag(
    canvas: Image.Image,
    original: Image.Image,
    assets: DirectionAssets,
    arr: np.ndarray,
) -> str:
    """
    tote_bag_processed.jpg
    Magenta → dark fill + large white logo at 88% opacity + fabric multiply blend.
    """
    mask = _make_mask(arr, MAGENTA)
    if mask.sum() < MIN_PX:
        return "no zones"
    bbox = _mask_bbox(mask)
    if not bbox:
        return "no zones"
    x1, y1, x2, y2 = bbox

    # Sample surrounding canvas colour (the bag material)
    bag_color = _sample_surrounding(arr, mask)
    _fill_mask(canvas, mask, bag_color)

    if not (assets.logo and assets.logo.exists() and assets.logo.stat().st_size > 100):
        return "LOGO (filled)"

    logo = Image.open(assets.logo).convert("RGBA")
    logo = _remove_white(logo)
    # Invert logo for contrast against the bag material
    logo_color = _contrasting(bag_color)
    logo = _colorize(logo, logo_color)
    logo = _fit(logo, x2 - x1, y2 - y1, 0.75)
    logo = _opacity(logo, 0.88)
    _paste_bbox_center(canvas, logo, x1, y1, x2, y2)
    _fabric_blend(canvas, original, mask, op=0.20)
    return "LOGO"


def _handle_tshirt(
    canvas: Image.Image,
    original: Image.Image,
    assets: DirectionAssets,
    arr: np.ndarray,
) -> str:
    """
    tshirt_processed.png
    Magenta → black fill + medium white logo, positioned slightly up-centre,
    at 88% opacity + fabric multiply blend (cotton texture).
    """
    mask = _make_mask(arr, MAGENTA)
    if mask.sum() < MIN_PX:
        return "no zones"
    bbox = _mask_bbox(mask)
    if not bbox:
        return "no zones"
    x1, y1, x2, y2 = bbox

    _fill_mask(canvas, mask, (0, 0, 0))

    if not (assets.logo and assets.logo.exists() and assets.logo.stat().st_size > 100):
        return "LOGO (filled)"

    logo = Image.open(assets.logo).convert("RGBA")
    logo = _remove_white(logo)
    logo = _colorize(logo, (255, 255, 255))
    logo = _fit(logo, x2 - x1, y2 - y1, 0.45)
    logo = _opacity(logo, 0.88)
    # Slightly above centre (chest print position)
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2 - logo.height // 6
    _paste_center(canvas, logo, cx, cy)
    _fabric_blend(canvas, original, mask, op=0.18)
    return "LOGO"


def _handle_x_account(
    canvas: Image.Image,
    original: Image.Image,
    assets: DirectionAssets,
    arr: np.ndarray,
) -> str:
    """
    x_account_processed.png
    Yellow  → background.png or pattern.png cover-fill (banner zone).
    Magenta → light grey bg + black logo, rounded avatar style.
    Cyan    → white fill + black bold brand name.
    """
    direction = assets.direction
    primary   = _hex_to_rgb(direction.colors[0].hex)
    brand     = direction.direction_name.upper()
    zones: List[str] = []

    # ── SURFACE (profile banner) → background or pattern, not solid colour ────
    surf_mask = _make_mask(arr, YELLOW)
    if surf_mask.sum() >= MIN_PX:
        bbox = _mask_bbox(surf_mask)
        if bbox:
            src = None
            if assets.background and assets.background.exists() and assets.background.stat().st_size > 100:
                src = Image.open(assets.background).convert("RGBA")
            elif assets.pattern and assets.pattern.exists() and assets.pattern.stat().st_size > 100:
                src = Image.open(assets.pattern).convert("RGBA")
            if src:
                _cover_fill(canvas, src, surf_mask, bbox)
            else:
                _fill_mask(canvas, surf_mask, primary)
            zones.append("SURFACE")

    # ── LOGO (avatar) → light bg + black logo, rounded ────────────────────────
    logo_mask = _make_mask(arr, MAGENTA)
    if logo_mask.sum() >= MIN_PX:
        bbox = _mask_bbox(logo_mask)
        if bbox:
            x1, y1, x2, y2 = bbox
            w, h = x2 - x1, y2 - y1
            avatar_bg = (240, 240, 245)
            patch = Image.new("RGBA", (w, h), avatar_bg + (255,))
            if assets.logo and assets.logo.exists() and assets.logo.stat().st_size > 100:
                logo = Image.open(assets.logo).convert("RGBA")
                logo = _remove_white(logo)
                logo = _colorize(logo, (20, 20, 20))
                logo = _fit(logo, w, h, 0.70)
                lx = (w - logo.width) // 2
                ly = (h - logo.height) // 2
                patch.paste(logo, (lx, ly), logo)
            patch = _rounded_icon(patch, 0.22)
            # Step 1: ERASE all magenta pixels with surrounding colour.
            # Restoring `original` would re-introduce magenta at the transparent
            # corners of the rounded avatar patch — wrong.
            sur = _sample_surrounding(arr, logo_mask)
            _fill_mask(canvas, logo_mask, sur)
            # Step 2: Paste rounded avatar patch — corners show page bg, not magenta.
            canvas.paste(patch, (x1, y1), patch)
            zones.append("LOGO")

    # ── TEXT (brand name handle) → white fill + dark bold text ────────────────
    text_mask = _make_mask(arr, CYAN)
    if text_mask.sum() >= MIN_PX:
        bbox = _mask_bbox(text_mask)
        if bbox:
            x1, y1, x2, y2 = bbox
            _fill_mask(canvas, text_mask, (255, 255, 255))
            draw = ImageDraw.Draw(canvas)
            _draw_text_auto(draw, brand, x1, y1, x2, y2, fill=(20, 20, 20), max_size=200)
            zones.append("TEXT")

    return " + ".join(zones) if zones else "no zones"


# ── Generic fallback for unrecognised mockups ─────────────────────────────────

def _handle_generic(
    canvas: Image.Image,
    original: Image.Image,
    assets: DirectionAssets,
    arr: np.ndarray,
) -> str:
    """Fill all 3 placeholder colours using surrounding colour + logo + text."""
    direction = assets.direction
    primary   = _hex_to_rgb(direction.colors[0].hex)
    brand     = direction.direction_name.upper()
    zones: List[str] = []

    surf_mask = _make_mask(arr, YELLOW)
    if surf_mask.sum() >= MIN_PX:
        _fill_mask(canvas, surf_mask, primary)
        zones.append("SURFACE")

    logo_mask = _make_mask(arr, MAGENTA)
    if logo_mask.sum() >= MIN_PX:
        bbox = _mask_bbox(logo_mask)
        if bbox:
            x1, y1, x2, y2 = bbox
            sur = _sample_surrounding(arr, logo_mask)
            _fill_mask(canvas, logo_mask, sur)
            if assets.logo and assets.logo.exists() and assets.logo.stat().st_size > 100:
                logo = Image.open(assets.logo).convert("RGBA")
                logo = _remove_white(logo)
                logo = _colorize(logo, _contrasting(sur))
                logo = _fit(logo, x2 - x1, y2 - y1, 0.65)
                _paste_bbox_center(canvas, logo, x1, y1, x2, y2)
        zones.append("LOGO")

    text_mask = _make_mask(arr, CYAN)
    if text_mask.sum() >= MIN_PX:
        bbox = _mask_bbox(text_mask)
        if bbox:
            x1, y1, x2, y2 = bbox
            sur = _sample_surrounding(arr, text_mask)
            _fill_mask(canvas, text_mask, sur)
            draw = ImageDraw.Draw(canvas)
            _draw_text_auto(draw, brand, x1, y1, x2, y2, fill=_contrasting(sur))
        zones.append("TEXT")

    return " + ".join(zones) if zones else "no zones"


# ── Dispatcher ────────────────────────────────────────────────────────────────

HANDLER_MAP: Dict[str, Handler] = {
    "wall_logo_processed.png":              _handle_wall_logo,
    "app_Icon_phone_flat_processed.png":    _handle_app_icon,
    "black_shirt_logo_processed.png":       _handle_black_shirt,
    "employee_id_card_processed.png":       _handle_employee_id,
    "horizontal_billboard_processed.png":   _handle_billboard,
    "logo_transparent_disk_processed.png":  _handle_disk,
    "name_card_processed.png":              _handle_name_card,
    "tote_bag_processed.jpg":               _handle_tote_bag,
    "tshirt_processed.png":                 _handle_tshirt,
    "x_account_processed.png":              _handle_x_account,
}


# ── AI reconstruction layer ────────────────────────────────────────────────────

# Maps processed filename → key used in MOCKUP_PROMPTS
MOCKUP_KEY_MAP: Dict[str, str] = {
    "wall_logo_processed.png":              "wall_logo",
    "app_Icon_phone_flat_processed.png":    "app_icon_phone",
    "black_shirt_logo_processed.png":       "black_shirt",
    "employee_id_card_processed.png":       "employee_id",
    "horizontal_billboard_processed.png":   "billboard",
    "logo_transparent_disk_processed.png":  "disk",
    "name_card_processed.png":              "name_card",
    "tote_bag_processed.jpg":               "tote_bag",
    "tshirt_processed.png":                 "tshirt",
    "x_account_processed.png":              "x_account",
}

# Per-mockup scene specs used to build AI reconstruction prompts
MOCKUP_PROMPTS: Dict[str, Dict[str, str]] = {
    "wall_logo": {
        "scene": (
            "Architectural interior wall with dimensional brand signage. "
            "The logo appears as mounted letters or a logo mark on the wall surface, "
            "casting realistic drop shadows."
        ),
        "logo_placement": "centered on the parallelogram-shaped architectural panel",
        "logo_color": "white or off-white",
        "logo_size": "large, spanning 65% of the panel width",
        "material": "painted metal or dimensional acrylic letters",
        "style": "premium corporate architectural signage, photorealistic",
    },
    "app_icon_phone": {
        "scene": (
            "Smartphone home screen showing a branded iOS app icon "
            "with rounded corners and an app name label directly below."
        ),
        "logo_placement": "centered inside a rounded-square icon with brand primary color as background",
        "logo_color": "white",
        "logo_size": "filling 65% of the icon area",
        "material": "flat vector, digital",
        "style": "iOS app icon, clean, modern, app store quality",
    },
    "black_shirt": {
        "scene": (
            "Black t-shirt laid flat. Brand logo screen-printed on the chest area "
            "with authentic cotton fabric texture showing through the ink."
        ),
        "logo_placement": "center chest",
        "logo_color": "white",
        "logo_size": "medium, 45% of the print zone",
        "material": "screen-print on cotton, fabric texture overlay",
        "style": "premium apparel merchandise, streetwear",
    },
    "employee_id": {
        "scene": (
            "Corporate employee ID card with a colorful lanyard. "
            "Card face shows the company logo and name; lanyard stripe uses brand primary color."
        ),
        "logo_placement": "logo on the left of the card face, brand name to the right",
        "logo_color": "white on dark background",
        "logo_size": "natural, fitting the card logo area",
        "material": "PVC card, dye-sublimation print quality",
        "style": "professional corporate, clean",
    },
    "billboard": {
        "scene": (
            "Large outdoor horizontal billboard. The billboard surface shows brand photography "
            "and a prominent logo mark on the right side of the board face."
        ),
        "logo_placement": "right side of the billboard face",
        "logo_color": "white (on photographic background)",
        "logo_size": "large, 55% of the logo zone width",
        "material": "vinyl print, outdoor advertising",
        "style": "high-impact outdoor advertising, photorealistic",
    },
    "disk": {
        "scene": (
            "Acrylic or glass transparent disk/puck award with brand logo. "
            "Clean reflections, premium material, minimal aesthetic."
        ),
        "logo_placement": "centered on the disk face",
        "logo_color": "dark/near-black on white or clear surface",
        "logo_size": "55% of the disk zone",
        "material": "laser-etched acrylic",
        "style": "premium minimal, transparent, corporate award",
    },
    "name_card": {
        "scene": (
            "Luxury two-sided business card. One face uses brand primary color with "
            "the brand name in large typography. The other face is white with a small dark logo."
        ),
        "logo_placement": "centered on white card face; name fills the colored face",
        "logo_color": "dark on white face; high-contrast on colored face",
        "logo_size": "40% of the white face logo zone",
        "material": "letterpress or offset print on thick card stock",
        "style": "luxury business card, premium print quality",
    },
    "tote_bag": {
        "scene": (
            "Natural canvas tote bag with brand logo screen-printed on the front panel. "
            "Woven fabric texture is visible through the ink."
        ),
        "logo_placement": "centered on the bag face",
        "logo_color": "contrasting with bag material color",
        "logo_size": "large, 75% of the logo zone",
        "material": "screen-print on canvas, fabric texture",
        "style": "eco merchandise, casual lifestyle",
    },
    "tshirt": {
        "scene": (
            "Light-colored t-shirt with brand logo printed on the chest area. "
            "Cotton fabric texture visible through the print."
        ),
        "logo_placement": "center chest, slightly above mid-point",
        "logo_color": "dark/black on light shirt",
        "logo_size": "medium, 45% of the print zone",
        "material": "screen-print on cotton",
        "style": "clean apparel merchandise",
    },
    "x_account": {
        "scene": (
            "X (Twitter) profile page screenshot. Profile banner shows brand imagery. "
            "Avatar is a rounded-square with light background and dark logo. "
            "Username display shows the brand name."
        ),
        "logo_placement": "rounded avatar on light background; banner shows brand imagery",
        "logo_color": "dark on light avatar background; any color on banner",
        "logo_size": "70% of the avatar zone",
        "material": "digital, flat design",
        "style": "social media profile, digital platform UI",
    },
}


def build_mockup_prompt(
    mockup_key: str,
    assets: "DirectionAssets",
    brand_name: str,
) -> str:
    """
    Build a structured natural-language prompt for Gemini AI mockup reconstruction.

    Combines per-mockup scene specs (from MOCKUP_PROMPTS) with live brand data
    (colors, direction name) to guide the model's output.
    """
    direction = assets.direction
    spec = MOCKUP_PROMPTS.get(mockup_key, {})

    # Brand color summary
    primary_hex = direction.colors[0].hex if direction.colors else "#333333"
    colors_desc = ", ".join(c.hex for c in direction.colors[:3]) if direction.colors else primary_hex

    system_context = (
        "You are a professional brand identity mockup renderer.\n"
        "Your task: take a reference mockup image that has colored placeholder zones "
        "and reconstruct it with a real brand identity applied.\n\n"
        "Placeholder color legend:\n"
        "  • Magenta/pink (#FF00FF) = logo placement zone\n"
        "  • Yellow (#FFFF00)       = brand color surface / imagery zone\n"
        "  • Cyan (#00FFFF)         = brand name / text zone\n\n"
        "Rules:\n"
        "  - Replace ALL placeholder zones with the brand identity shown.\n"
        "  - Keep all non-placeholder areas IDENTICAL: surroundings, shadows, materials, "
        "lighting, perspective, and scene composition must not change.\n"
        "  - Output a single photorealistic image with the same dimensions and crop as the reference.\n"
        "  - No additional text or words except in designated cyan text zones.\n\n"
    )

    brand_brief = (
        f"Brand name: {brand_name}\n"
        f"Primary color: {primary_hex}\n"
        f"Color palette: {colors_desc}\n"
        f"Brand mood / direction: {direction.direction_name}\n\n"
    )

    mockup_spec = ""
    if spec:
        mockup_spec = (
            f"Mockup scene: {spec.get('scene', '')}\n"
            f"Logo placement: {spec.get('logo_placement', 'centered in the placeholder zone')}\n"
            f"Logo color: {spec.get('logo_color', 'contrasting with background')}\n"
            f"Logo size: {spec.get('logo_size', '60% of the zone')}\n"
            f"Material / rendering: {spec.get('material', 'standard print')}\n"
            f"Visual style: {spec.get('style', 'professional, clean')}\n\n"
        )

    instructions = (
        "Step-by-step instructions:\n"
        "1. Analyse the reference mockup image (first image) — identify all placeholder zones.\n"
        "2. Apply the brand primary color to all YELLOW zones.\n"
        "3. Place the logo (second image) in all MAGENTA zones — render it naturally on the "
        "material (screen-print texture on fabric, etched look on acrylic, etc.).\n"
        "4. Render the brand name text in all CYAN zones with appropriate typography.\n"
        "5. Output the final photorealistic mockup image."
    )

    return system_context + brand_brief + mockup_spec + instructions


def _ai_reconstruct_mockup(
    mockup_path: Path,
    prompt: str,
    logo_path: Optional[Path],
    api_key: str,
) -> Optional[bytes]:
    """
    Use Gemini multi-modal image generation to reconstruct a mockup with brand identity.

    Content sent to Gemini:
      [text: system + brand brief + instructions]
      [image: reference mockup with placeholder zones]
      [text: logo introduction]
      [image: brand logo (transparent version preferred)]
      [text: closing instruction]

    Returns raw image bytes on success, None on any failure.
    """
    try:
        client = genai.Client(api_key=api_key)

        # Read mockup
        mockup_bytes = mockup_path.read_bytes()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp"}
        mockup_mime = mime_map.get(mockup_path.suffix.lower(), "image/png")

        # Build content parts
        parts = [
            genai_types.Part.from_text(prompt),
            genai_types.Part.from_bytes(data=mockup_bytes, mime_type=mockup_mime),
        ]

        # Add logo
        if logo_path and logo_path.exists() and logo_path.stat().st_size > 100:
            logo_bytes = logo_path.read_bytes()
            parts.append(genai_types.Part.from_text(
                "Brand logo mark (integrate this into all magenta zones, "
                "render naturally on the material):"
            ))
            parts.append(genai_types.Part.from_bytes(
                data=logo_bytes, mime_type="image/png"
            ))

        parts.append(genai_types.Part.from_text(
            "Output the reconstructed mockup image with brand identity fully applied. "
            "Image only — no captions."
        ))

        response = client.models.generate_content(
            model="gemini-2.0-flash-exp-image-generation",
            contents=parts,
            config=genai_types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )

        for candidate in response.candidates or []:
            for part in candidate.content.parts or []:
                if hasattr(part, "inline_data") and part.inline_data:
                    data = part.inline_data.data
                    if isinstance(data, str):
                        data = base64.b64decode(data)
                    return data

    except Exception as e:
        console.print(f"    [dim]AI reconstruction failed: {e}[/dim]")

    return None


# ── Public API ────────────────────────────────────────────────────────────────

def composite_all_mockups(
    all_assets: Dict[int, "DirectionAssets"],
    metadata_path: Path = METADATA_PATH,
    processed_dir: Path = PROCESSED_DIR,
) -> Dict[int, List[Path]]:
    """
    Composite brand assets onto every processed mockup for every direction.

    Strategy (per mockup):
      1. Try AI reconstruction (Gemini multi-modal) for natural brand integration.
      2. If AI fails or GEMINI_API_KEY is not set → Pillow pixel-mask fallback.

    Args:
        all_assets:    Dict mapping option_number → DirectionAssets.
        metadata_path: Path to metadata.json (zone presence info, currently unused).
        processed_dir: Directory containing processed mockup images.

    Returns:
        Dict mapping option_number → [composited_mockup_path, ...].
    """
    if not processed_dir.exists():
        console.print(f"  [yellow]⚠ {processed_dir} not found — skipping mockups[/yellow]")
        return {}

    processed_files = sorted(
        p for p in processed_dir.iterdir()
        if p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")
    )
    if not processed_files:
        console.print(f"  [yellow]⚠ No images found in {processed_dir}[/yellow]")
        return {}

    api_key = os.environ.get("GEMINI_API_KEY")
    results: Dict[int, List[Path]] = {}

    for num, assets in all_assets.items():
        if assets.background and assets.background.parent.exists():
            mockup_dir = assets.background.parent / "mockups"
        else:
            slug = _slugify(assets.direction.direction_name)
            mockup_dir = Path("outputs") / f"option_{num}_{slug}" / "mockups"
        mockup_dir.mkdir(parents=True, exist_ok=True)

        composited: List[Path] = []
        ai_count = pillow_count = 0
        brand_name = assets.direction.direction_name

        console.print(f"\n  Option {num} — compositing {len(processed_files)} mockup(s)…")

        for mp in processed_files:
            out_path = mockup_dir / (mp.stem + "_composite.png")
            try:
                ai_ok = False

                # ── Try AI reconstruction ──────────────────────────────────────
                if api_key:
                    mockup_key = MOCKUP_KEY_MAP.get(mp.name)
                    if mockup_key:
                        prompt = build_mockup_prompt(mockup_key, assets, brand_name)
                        # Prefer transparent logo — cleaner AI integration
                        logo_for_ai = (
                            assets.logo_transparent
                            if (assets.logo_transparent
                                and assets.logo_transparent.exists()
                                and assets.logo_transparent.stat().st_size > 100)
                            else assets.logo
                        )
                        ai_bytes = _ai_reconstruct_mockup(mp, prompt, logo_for_ai, api_key)
                        if ai_bytes:
                            out_path.write_bytes(ai_bytes)
                            composited.append(out_path)
                            console.print(f"    [green]✓ AI [/green] {mp.name}")
                            ai_count += 1
                            ai_ok = True

                # ── Pillow pixel-mask fallback ─────────────────────────────────
                if not ai_ok:
                    original = Image.open(mp).convert("RGBA")
                    canvas   = original.copy()
                    arr      = np.array(original)

                    handler   = HANDLER_MAP.get(mp.name, _handle_generic)
                    zones_str = handler(canvas, original, assets, arr)

                    canvas.convert("RGB").save(str(out_path), format="PNG")
                    composited.append(out_path)
                    console.print(f"    [blue]✓ PIL[/blue] {mp.name}  [{zones_str}]")
                    pillow_count += 1

            except Exception as exc:
                console.print(f"    [yellow]⚠ {mp.name}: {exc}[/yellow]")
                composited.append(mp)   # fallback: original unmodified file

        results[num] = composited
        summary = f"AI:{ai_count}  PIL:{pillow_count}"
        console.print(
            f"    [dim]→ {mockup_dir}  ({len(composited)} files  {summary})[/dim]"
        )

    return results
