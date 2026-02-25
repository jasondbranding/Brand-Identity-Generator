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
import time
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
ORIGINALS_DIR = Path("mockups/originals")
IMAGE_EXTS    = {".png", ".jpg", ".jpeg", ".webp"}

MAGENTA   = (255,   0, 255)
CYAN      = (  0, 255, 255)
YELLOW    = (255, 255,   0)
TOLERANCE = 30
MIN_PX    = 50

# ── Retry config ───────────────────────────────────────────────────────────────
MAX_ATTEMPTS   = 3     # total attempts per mockup (across all prompt levels)
BACKOFF_BASE   = 30.0  # seconds to wait on first rate-limit hit (doubles each time)
RETRY_WAIT     = 5.0   # seconds to wait on non-rate-limit errors


class _RateLimitError(Exception):
    """Re-raised from _ai_reconstruct_mockup when Gemini returns 429 / RESOURCE_EXHAUSTED."""

Handler = Callable[
    [Image.Image, Image.Image, "DirectionAssets", np.ndarray], str
]


# ── Original-finder ────────────────────────────────────────────────────────────

def _find_original(processed_path: Path, originals_dir: Path = ORIGINALS_DIR) -> Optional[Path]:
    """
    Find the high-quality original image that corresponds to a processed mockup.

    Naming convention: processed files end with _processed (before extension),
    originals end with _original.

    Examples:
      wall_logo_processed.png     → originals/wall_logo_original.png
      tote_bag_processed.jpg      → originals/tote_bag_original.png
      app_Icon_phone_flat_processed.png → originals/app_Icon_phone_flat_original.png
    """
    if not originals_dir.exists():
        return None

    # Strip _processed suffix from stem
    stem = processed_path.stem
    if stem.endswith("_processed"):
        base = stem[: -len("_processed")]
    else:
        base = stem

    # Try {base}_original with any supported extension
    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        candidate = originals_dir / f"{base}_original{ext}"
        if candidate.exists():
            return candidate

    # Fallback: try exact base name with any extension (no _original suffix)
    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        candidate = originals_dir / f"{base}{ext}"
        if candidate.exists():
            return candidate

    return None


# ── Zone extraction from processed images ────────────────────────────────────
#
# Processed images are NEVER sent to Gemini as visual input.
# They are read locally by Pillow to extract zone bounding-box coordinates,
# which are then described to Gemini as plain text.  The AI only ever "sees"
# the original high-quality photo and the brand logo.

def _extract_zones(processed_path: Path) -> dict:
    """
    Programmatically extract zone bounding boxes from a processed guide image.

    Detects the three placeholder colours (magenta/yellow/cyan) using pixel
    masks and returns a dict of { zone_name → {bbox, img_size, pixel_count} }.

    The processed image is opened by Pillow only — it is NEVER forwarded to
    any AI model.
    """
    try:
        img = Image.open(processed_path).convert("RGBA")
        arr = np.array(img)
        w, h = img.size
        zones: dict = {}

        for name, color in [("logo", MAGENTA), ("surface", YELLOW), ("text", CYAN)]:
            mask = _make_mask(arr, color)
            if mask.sum() < MIN_PX:
                continue
            bbox = _mask_bbox(mask)
            if bbox:
                zones[name] = {
                    "bbox":        bbox,           # (x1, y1, x2, y2) in px
                    "img_size":    (w, h),
                    "pixel_count": int(mask.sum()),
                }
        return zones
    except Exception as exc:
        console.print(f"    [dim]Zone extraction failed: {exc}[/dim]")
        return {}


def _zones_to_text(zones: dict) -> str:
    """
    Convert extracted zone bboxes into a natural-language coordinate description
    for inclusion in the AI prompt.

    Example output:
      PLACEMENT ZONES (pixel coordinates):
      • LOGO zone  : top-left (412, 180) → bottom-right (860, 620),
                     center (636, 400), size 448×440 px (44%W × 55%H)
      • SURFACE zone: ...
    """
    if not zones:
        return ""

    label_map = {
        "logo":    "LOGO zone",
        "surface": "SURFACE / COLOR zone",
        "text":    "TEXT / BRAND NAME zone",
    }
    lines = ["PLACEMENT ZONES (pixel coordinates in the original photo):"]
    for name, info in zones.items():
        x1, y1, x2, y2 = info["bbox"]
        w, h = info["img_size"]
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        bw, bh = x2 - x1, y2 - y1
        pct_w  = round(bw / w * 100)
        pct_h  = round(bh / h * 100)
        label  = label_map.get(name, f"{name.upper()} zone")
        lines.append(
            f"  • {label}: top-left ({x1},{y1}) → bottom-right ({x2},{y2}), "
            f"center ({cx},{cy}), size {bw}×{bh}px ({pct_w}%W × {pct_h}%H)"
        )
    return "\n".join(lines)


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
    canvas  = high-quality original photo (modified in-place)
    original = zone_ref/processed (zone detection only — arr already extracted)
    """
    # Sample surrounding colour from the original photo, not the processed zones
    canvas_arr = np.array(canvas)

    mask = _make_mask(arr, MAGENTA)
    if mask.sum() < MIN_PX:
        return "no zones"
    bbox = _mask_bbox(mask)
    if not bbox:
        return "no zones"
    x1, y1, x2, y2 = bbox

    # Fill parallelogram with surrounding wall colour from original photo
    wall = _sample_surrounding(canvas_arr, mask)
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
    canvas  = high-quality original photo (modified in-place)
    original = zone_ref/processed (zone detection only — arr already extracted)
    """
    direction = assets.direction
    primary   = _hex_to_rgb(direction.colors[0].hex)
    brand     = direction.direction_name.upper()
    zones: List[str] = []

    # Array from original canvas for accurate surrounding-colour sampling
    canvas_arr = np.array(canvas)

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
            # Step 1: ERASE all magenta pixels with surrounding phone-screen colour.
            # Sample from the original photo so corners match the real screen background.
            sur = _sample_surrounding(canvas_arr, logo_mask)
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
    canvas  = high-quality original photo (modified in-place)
    original = zone_ref/processed (zone detection only — arr already extracted)
    """
    # Snapshot of the unmodified original photo — used for authentic fabric texture blend
    canvas_pristine = canvas.copy()

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
    # Blend original photo texture (not processed flat-color) through the logo
    _fabric_blend(canvas, canvas_pristine, mask, op=0.18)
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
    canvas  = high-quality original photo (modified in-place)
    original = zone_ref/processed (zone detection only — arr already extracted)
    """
    # Snapshot of the unmodified original photo for authentic fabric texture blend
    canvas_pristine = canvas.copy()
    # Array from original canvas for accurate surrounding-colour sampling
    canvas_arr = np.array(canvas_pristine)

    mask = _make_mask(arr, MAGENTA)
    if mask.sum() < MIN_PX:
        return "no zones"
    bbox = _mask_bbox(mask)
    if not bbox:
        return "no zones"
    x1, y1, x2, y2 = bbox

    # Sample bag material colour from the original photo (not the flat processed zones)
    bag_color = _sample_surrounding(canvas_arr, mask)
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
    # Blend original photo texture (not processed flat-color) through the logo
    _fabric_blend(canvas, canvas_pristine, mask, op=0.20)
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
    canvas  = high-quality original photo (modified in-place)
    original = zone_ref/processed (zone detection only — arr already extracted)
    """
    # Snapshot of the unmodified original photo for authentic cotton texture blend
    canvas_pristine = canvas.copy()

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
    # Blend original photo texture (not processed flat-color) through the logo
    _fabric_blend(canvas, canvas_pristine, mask, op=0.18)
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
    canvas  = high-quality original photo (modified in-place)
    original = zone_ref/processed (zone detection only — arr already extracted)
    """
    direction = assets.direction
    primary   = _hex_to_rgb(direction.colors[0].hex)
    brand     = direction.direction_name.upper()
    zones: List[str] = []

    # Array from original canvas for accurate surrounding-colour sampling
    canvas_arr = np.array(canvas)

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
            # Step 1: ERASE all magenta pixels with surrounding page-bg colour.
            # Sample from original photo so corners match the real page background.
            sur = _sample_surrounding(canvas_arr, logo_mask)
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
    """Fill all 3 placeholder colours using surrounding colour + logo + text.
    canvas  = high-quality original photo (modified in-place)
    original = zone_ref/processed (zone detection only — arr already extracted)
    """
    direction = assets.direction
    primary   = _hex_to_rgb(direction.colors[0].hex)
    brand     = direction.direction_name.upper()
    zones: List[str] = []

    # Array from original canvas for accurate surrounding-colour sampling
    canvas_arr = np.array(canvas)

    surf_mask = _make_mask(arr, YELLOW)
    if surf_mask.sum() >= MIN_PX:
        _fill_mask(canvas, surf_mask, primary)
        zones.append("SURFACE")

    logo_mask = _make_mask(arr, MAGENTA)
    if logo_mask.sum() >= MIN_PX:
        bbox = _mask_bbox(logo_mask)
        if bbox:
            x1, y1, x2, y2 = bbox
            sur = _sample_surrounding(canvas_arr, logo_mask)
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
            sur = _sample_surrounding(canvas_arr, text_mask)
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

# Per-mockup JSON specs for structured AI prompt generation.
# Each entry drives build_mockup_prompt() which outputs a JSON structured prompt
# (same format proven to work with Gemini image editing).
#
# originals/ images should show the mockup WITH an existing placeholder logo so
# the AI task is "replace this logo shape" — not "invent placement from scratch".
MOCKUP_PROMPTS: Dict[str, Dict] = {
    "wall_logo": {
        "goal": (
            "Replace the existing logo/lettering on the architectural wall panel with the "
            "provided brand logo mark. Maintain the exact same 3D dimensional signage style, "
            "size, placement, lighting, and perspective. Only change the logo shape."
        ),
        "placeholder_description": "dimensional metal or acrylic letters/logo currently mounted on the wall",
        "logo_replacement": {
            "replace_existing_logo": True,
            "maintain_exact_position": True,
            "maintain_exact_size": True,
            "maintain_mounting_depth": True,
            "convert_style": {
                "type": "3D dimensional wall signage",
                "material": "matte painted metal or brushed aluminum",
                "edge_finish": "clean bevel",
                "depth": "same mounting depth as original signage",
                "shadow": "match original wall shadow exactly",
                "reflection": "subtle realistic metallic reflections",
                "color": "white or brand primary color",
            },
        },
        "environment": {
            "wall_surface": {"preserve_material": True, "preserve_texture": True, "preserve_color": True},
            "lighting": {"preserve_direction": True, "preserve_intensity": True, "preserve_shadows": True},
            "architecture": {"preserve_exactly": True},
        },
        "constraints": [
            "only replace the logo mark shape",
            "keep exact size and placement",
            "keep exact lighting and wall shadows",
            "no color change to wall or building",
            "no extra elements added",
            "no watermark",
        ],
        "style": "ultra photorealistic architectural signage, premium corporate quality, high-end commercial render",
    },
    "app_icon_phone": {
        "goal": (
            "Replace the existing app icon on the smartphone home screen with the provided "
            "brand logo. Keep the exact same rounded-square icon shape, size, position on screen, "
            "and the app name label below it. Only change the icon artwork."
        ),
        "placeholder_description": "existing app icon with placeholder logo on phone home screen",
        "logo_replacement": {
            "replace_existing_logo": True,
            "maintain_exact_position": True,
            "maintain_exact_size": True,
            "convert_style": {
                "type": "flat digital app icon",
                "background": "brand primary color as icon background",
                "logo_color": "white",
                "corner_radius": "iOS standard rounded square",
                "finish": "clean flat vector, app store quality",
            },
        },
        "environment": {
            "phone_screen": {"preserve_all_other_icons": True, "preserve_wallpaper": True},
            "device": {"preserve_exactly": True},
        },
        "constraints": [
            "only replace the single app icon",
            "keep all other icons unchanged",
            "keep phone device identical",
            "keep app name label below icon",
            "no watermark",
        ],
        "style": "crisp digital UI, iOS app icon, photorealistic smartphone screen",
    },
    "black_shirt": {
        "goal": (
            "Replace the existing logo printed on the black t-shirt chest area with the "
            "provided brand logo. Maintain the exact same screen-print look, size, position, "
            "and fabric texture interaction. Only change the logo artwork."
        ),
        "placeholder_description": "existing screen-printed logo on black cotton t-shirt chest",
        "logo_replacement": {
            "replace_existing_logo": True,
            "maintain_exact_position": True,
            "maintain_exact_size": True,
            "convert_style": {
                "type": "screen-print on cotton",
                "ink_color": "white",
                "fabric_texture": "cotton weave visible through ink",
                "ink_opacity": "slightly transparent, fabric shows through",
                "finish": "authentic apparel print quality",
            },
        },
        "environment": {
            "shirt": {"preserve_color": True, "preserve_fabric_folds": True, "preserve_texture": True},
            "background": {"preserve_exactly": True},
            "lighting": {"preserve_direction": True, "preserve_shadows": True},
        },
        "constraints": [
            "only replace the chest print artwork",
            "keep exact print size and position",
            "keep fabric texture visible through ink",
            "keep shirt color and all folds identical",
            "no watermark",
        ],
        "style": "premium apparel merchandise, streetwear, photorealistic fabric",
    },
    "employee_id": {
        "goal": (
            "Replace the existing logo and brand name on the employee ID card with the "
            "provided brand logo and the correct brand name. Keep the exact card layout, "
            "lanyard, card proportions, and print quality."
        ),
        "placeholder_description": "placeholder logo and name on corporate PVC ID card with lanyard",
        "logo_replacement": {
            "replace_existing_logo": True,
            "replace_brand_name_text": True,
            "maintain_card_layout": True,
            "convert_style": {
                "type": "dye-sublimation print on PVC card",
                "logo_color": "white on dark background",
                "text_rendering": "clean sans-serif, high contrast",
                "finish": "professional corporate ID quality",
            },
        },
        "environment": {
            "card_body": {"preserve_layout": True, "preserve_dimensions": True},
            "lanyard": {"preserve_color": True, "preserve_texture": True},
            "background": {"preserve_exactly": True},
        },
        "constraints": [
            "only replace logo and brand name",
            "keep card dimensions and layout identical",
            "keep lanyard color and texture",
            "no watermark",
        ],
        "style": "professional corporate ID card, dye-sublimation quality",
    },
    "billboard": {
        "goal": (
            "Replace the existing logo/brand mark on the outdoor billboard with the provided "
            "brand logo. Keep the exact same billboard composition, size, position, outdoor "
            "lighting, and vinyl print style. Only change the logo artwork."
        ),
        "placeholder_description": "existing brand logo on large outdoor billboard vinyl surface",
        "logo_replacement": {
            "replace_existing_logo": True,
            "maintain_exact_position": True,
            "maintain_exact_size": True,
            "convert_style": {
                "type": "large format vinyl print",
                "logo_color": "white on photographic/colored background",
                "finish": "outdoor billboard print quality, slight weather texture",
                "shadow": "match existing logo shadow and perspective warp",
            },
        },
        "environment": {
            "billboard_structure": {"preserve_frame": True, "preserve_material": True},
            "background_scene": {"preserve_sky": True, "preserve_environment": True},
            "lighting": {"preserve_direction": True, "preserve_intensity": True},
        },
        "constraints": [
            "only replace the logo mark",
            "keep billboard background imagery identical",
            "keep perspective warp on logo to match billboard plane",
            "keep outdoor lighting and environment",
            "no watermark",
        ],
        "style": "high-impact outdoor advertising, photorealistic, commercial billboard quality",
    },
    "disk": {
        "goal": (
            "Replace the existing logo etched or printed on the acrylic disk award with the "
            "provided brand logo. Maintain exact size, centering, material treatment, and "
            "transparent acrylic reflections. Only change the logo shape."
        ),
        "placeholder_description": "existing logo laser-etched or printed on transparent acrylic disk",
        "logo_replacement": {
            "replace_existing_logo": True,
            "maintain_exact_position": True,
            "maintain_exact_size": True,
            "convert_style": {
                "type": "laser-etched or printed on acrylic",
                "logo_color": "dark/frosted on clear acrylic",
                "finish": "premium etched quality, slight diffusion",
                "reflection": "maintain acrylic surface reflections around logo",
            },
        },
        "environment": {
            "disk_material": {"preserve_transparency": True, "preserve_reflections": True},
            "surface": {"preserve_exactly": True},
            "lighting": {"preserve_direction": True, "preserve_caustics": True},
        },
        "constraints": [
            "only replace the logo artwork",
            "keep acrylic transparency and reflections",
            "keep exact logo size and centering",
            "no watermark",
        ],
        "style": "premium minimal corporate award, ultra photorealistic acrylic material",
    },
    "name_card": {
        "goal": (
            "Replace the existing logo and brand name on the business card with the provided "
            "brand logo and correct brand name. Keep the exact card design, color scheme, "
            "paper texture, and print quality. Only change logo and name."
        ),
        "placeholder_description": "placeholder logo and brand name on luxury thick business card",
        "logo_replacement": {
            "replace_existing_logo": True,
            "replace_brand_name_text": True,
            "maintain_card_layout": True,
            "convert_style": {
                "type": "letterpress or offset print on thick card stock",
                "logo_color": "dark on white face; high-contrast on colored face",
                "text_rendering": "premium typography, brand name in large type on colored face",
                "finish": "luxury print quality, subtle emboss or deboss",
            },
        },
        "environment": {
            "card_surfaces": {"preserve_color": True, "preserve_texture": True, "preserve_layout": True},
            "background": {"preserve_exactly": True},
            "lighting": {"preserve_direction": True, "preserve_shadows": True},
        },
        "constraints": [
            "only replace logo mark and brand name text",
            "keep both card faces identical in design",
            "keep paper texture and print quality",
            "no watermark",
        ],
        "style": "luxury business card, premium letterpress quality, photorealistic paper texture",
    },
    "tote_bag": {
        "goal": (
            "Replace the existing logo screen-printed on the canvas tote bag with the provided "
            "brand logo. Maintain exact size, position, canvas fabric texture interaction, "
            "and print style. Only change the logo artwork."
        ),
        "placeholder_description": "existing screen-printed logo on natural canvas tote bag front panel",
        "logo_replacement": {
            "replace_existing_logo": True,
            "maintain_exact_position": True,
            "maintain_exact_size": True,
            "convert_style": {
                "type": "screen-print on canvas",
                "ink_color": "contrasting with natural canvas (dark ink on light canvas)",
                "fabric_texture": "canvas weave visible through ink",
                "ink_opacity": "semi-opaque, authentic screen-print look",
                "finish": "eco merchandise print quality",
            },
        },
        "environment": {
            "bag": {"preserve_fabric_texture": True, "preserve_color": True, "preserve_shape": True},
            "background": {"preserve_exactly": True},
            "lighting": {"preserve_direction": True, "preserve_shadows": True},
        },
        "constraints": [
            "only replace the logo print on the bag face",
            "keep canvas texture visible through the ink",
            "keep bag shape, color, handles identical",
            "no watermark",
        ],
        "style": "eco merchandise, casual lifestyle, photorealistic canvas fabric",
    },
    "tshirt": {
        "goal": (
            "Replace the existing logo printed on the light-colored t-shirt chest with the "
            "provided brand logo. Maintain exact print size, position, fabric texture "
            "interaction, and DTG/screen-print style. Only change the logo artwork."
        ),
        "placeholder_description": "existing printed logo on light-colored cotton t-shirt chest area",
        "logo_replacement": {
            "replace_existing_logo": True,
            "maintain_exact_position": True,
            "maintain_exact_size": True,
            "convert_style": {
                "type": "DTG or screen-print on cotton",
                "ink_color": "dark/black on light shirt",
                "fabric_texture": "cotton weave visible through ink",
                "ink_opacity": "solid or semi-transparent, authentic print look",
                "finish": "clean apparel print quality",
            },
        },
        "environment": {
            "shirt": {"preserve_color": True, "preserve_fabric_folds": True, "preserve_texture": True},
            "background": {"preserve_exactly": True},
            "lighting": {"preserve_direction": True, "preserve_shadows": True},
        },
        "constraints": [
            "only replace the chest print artwork",
            "keep exact print size and position",
            "keep fabric texture and shirt folds identical",
            "keep shirt color unchanged",
            "no watermark",
        ],
        "style": "clean apparel merchandise, photorealistic cotton fabric",
    },
    "x_account": {
        "goal": (
            "Replace the existing profile avatar logo and banner branding on the X (Twitter) "
            "profile page with the provided brand logo and brand name. Keep the exact same "
            "UI layout, screen composition, and digital rendering. Only change logo and name."
        ),
        "placeholder_description": "placeholder avatar and banner branding on X profile page screenshot",
        "logo_replacement": {
            "replace_avatar_logo": True,
            "replace_banner_branding": True,
            "replace_display_name": True,
            "convert_style": {
                "type": "flat digital UI",
                "avatar_background": "light background, rounded square crop",
                "logo_color": "dark logo on light avatar background",
                "banner": "brand primary color or brand imagery",
                "finish": "crisp digital render, screen pixel quality",
            },
        },
        "environment": {
            "profile_layout": {"preserve_ui_chrome": True, "preserve_all_other_elements": True},
            "screen": {"preserve_exactly": True},
        },
        "constraints": [
            "only replace avatar, banner branding, and display name",
            "keep all other UI elements identical",
            "keep exact layout and proportions",
            "no watermark",
        ],
        "style": "social media profile, digital platform UI, photorealistic screen render",
    },
}


def build_mockup_prompt(
    mockup_key: str,
    assets: "DirectionAssets",
    brand_name: str,
    zone_text: str = "",
) -> str:
    """
    Build a structured JSON prompt for Gemini mockup logo replacement.

    The approach: originals/ images show the mockup WITH an existing placeholder
    logo (demonstrating the correct material/3D style). The AI task is to
    REPLACE that placeholder logo with the provided brand logo — keeping everything
    else identical (lighting, shadows, perspective, material treatment).

    Output is a JSON string (IMAGE_GEN_V1 format) which Gemini image editing
    handles with high precision compared to natural-language prompts.

    Zone coordinates from processed/ images are embedded as pixel hints.
    """
    direction   = assets.direction
    spec        = MOCKUP_PROMPTS.get(mockup_key, {})
    primary_hex = direction.colors[0].hex if direction.colors else "#333333"
    colors_desc = ", ".join(c.hex for c in direction.colors[:3]) if direction.colors else primary_hex

    # Build the logo_replacement block, injecting brand colors where needed
    logo_repl = dict(spec.get("logo_replacement", {
        "replace_existing_logo": True,
        "maintain_exact_position": True,
        "maintain_exact_size": True,
    }))
    # Inject brand primary color into convert_style if present
    if "convert_style" in logo_repl:
        cs = dict(logo_repl["convert_style"])
        if "color" in cs and cs["color"] in ("brand primary color", "white or brand primary color"):
            cs["color"] = f"{primary_hex} (brand primary) or white"
        logo_repl["convert_style"] = cs

    prompt_dict = {
        "IMAGE_GEN_V1": {
            "task": "image_edit",
            "goal": spec.get("goal", (
                "Replace the existing placeholder logo in the reference photo with the "
                "provided brand logo. Keep the exact same style, size, placement, "
                "lighting, and material treatment. Only change the logo shape."
            )),
            "brand": {
                "name": brand_name,
                "primary_color": primary_hex,
                "palette": colors_desc,
                "creative_direction": direction.direction_name,
            },
            "composition": {
                "aspect_ratio": "original image ratio",
                "preserve_layout": True,
                "preserve_scale": True,
                "preserve_perspective": True,
                "preserve_camera_angle": True,
                "preserve_spacing": True,
            },
            "logo_replacement": logo_repl,
            "environment": spec.get("environment", {"preserve_all_non_logo_elements": True}),
            "style": spec.get("style", "ultra photorealistic, premium commercial quality"),
            "constraints": spec.get("constraints", [
                "only replace the logo shape",
                "keep exact size and placement",
                "keep exact lighting and shadows",
                "no extra elements",
                "no watermark",
            ]),
            "output": {
                "resolution": "4K or highest available",
                "format": "png",
                "quality": "ultra high",
            },
        }
    }

    # Embed zone pixel coordinates as a placement hint (optional but helpful)
    if zone_text:
        prompt_dict["IMAGE_GEN_V1"]["placement_zone_hints"] = zone_text

    return json.dumps(prompt_dict, indent=2, ensure_ascii=False)


def _ai_reconstruct_mockup(
    original_path: Optional[Path],
    prompt: str,
    logo_path: Optional[Path],
    api_key: str,
    zones: Optional[dict] = None,
) -> Optional[bytes]:
    """
    Reconstruct a brand mockup using Gemini image generation.

    Visual inputs sent to Gemini (in order):
      1. Original high-quality mockup photo  ← PRIMARY visual base
      2. Brand logo mark                     ← asset to integrate

    The processed / zone-guide image is NEVER sent to Gemini.
    Zone positions are extracted by Pillow locally and forwarded as plain-text
    pixel coordinates inside the prompt, so the AI understands placement without
    being visually influenced by the flat colored placeholder image.

    Args:
        original_path: Path to the high-quality original mockup photo.
        prompt:        Art-direction prompt including zone coordinates.
        logo_path:     Path to the brand logo (transparent PNG preferred).
        api_key:       Gemini API key.
        zones:         Pre-extracted zone dict from _extract_zones() — already
                       embedded in prompt, kept here for logging only.

    Returns raw image bytes on success, None on any failure.
    """
    if not original_path or not original_path.exists():
        console.print("    [dim]AI skip — no original photo found[/dim]")
        return None

    try:
        client   = genai.Client(api_key=api_key, http_options={"timeout": 90})
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png",  ".webp": "image/webp"}

        original_bytes = original_path.read_bytes()
        original_mime  = mime_map.get(original_path.suffix.lower(), "image/png")

        # ── Content assembly ──────────────────────────────────────────────────
        # Order matters: text context → original photo → logo → closing directive
        parts: list = []

        # 1. Full art-direction prompt (includes zone coordinates as text)
        parts.append(genai_types.Part.from_text(text=prompt))

        # 2. Reference mockup photo — shows existing placeholder logo with correct material style
        parts.append(genai_types.Part.from_text(
            text=(
                "REFERENCE MOCKUP PHOTO — this photo shows an existing placeholder logo "
                "already rendered in the correct material style (3D signage, screen-print, "
                "etched acrylic, etc.). Your task: replace only that placeholder logo with "
                "the brand logo provided next. Keep every other pixel in this photo IDENTICAL — "
                "same lighting, same shadows, same perspective, same background, same material."
            )
        ))
        parts.append(genai_types.Part.from_bytes(
            data=original_bytes, mime_type=original_mime
        ))

        # 3. Brand logo — the flat mark to replace the placeholder
        if logo_path and logo_path.exists() and logo_path.stat().st_size > 100:
            logo_bytes = logo_path.read_bytes()
            parts.append(genai_types.Part.from_text(
                text=(
                    "NEW BRAND LOGO — this is the flat logo mark to use as replacement. "
                    "Swap out the existing placeholder logo in the reference photo with this shape. "
                    "Convert it to match the same material style as the original placeholder "
                    "(same 3D treatment, same surface finish, same lighting and shadows). "
                    "Remove any white or solid background from this logo before applying."
                )
            ))
            parts.append(genai_types.Part.from_bytes(
                data=logo_bytes, mime_type="image/png"
            ))

        # 4. Final directive
        parts.append(genai_types.Part.from_text(
            text=(
                "Execute the logo replacement now. "
                "Output the final photo with ONLY the placeholder logo swapped out "
                "for the new brand logo mark. "
                "Everything else — background, lighting, shadows, materials, perspective, "
                "camera angle, all other objects — must be pixel-perfect identical to the reference photo. "
                "Output the final image only. No captions, no borders, no watermarks."
            )
        ))

        # Model ladder: confirmed-working first, experimental last
        _models = [
            "gemini-2.5-flash-image",                    # confirmed working
            "gemini-2.0-flash-exp-image-generation",     # legacy fallback
            "gemini-3-pro-image-preview",                # may not exist yet
            "gemini-2.0-flash-preview-image-generation", # last resort
        ]
        response = None
        _model = _models[0]
        for _model in _models:
            try:
                response = client.models.generate_content(
                    model=_model,
                    contents=parts,
                    config=genai_types.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"],
                    ),
                )
                break  # success — stop trying
            except Exception as _me:
                err_str = str(_me).lower()
                # Try next model on: not found / permission / SSL / timeout / network errors
                if any(k in err_str for k in (
                    "not found", "permission", "not supported", "invalid",
                    "timed out", "timeout", "ssl", "handshake", "connection",
                )):
                    continue
                raise  # re-raise unexpected errors (rate limit, etc.)
        if response is None:
            return None

        for candidate in response.candidates or []:
            for part in candidate.content.parts or []:
                if hasattr(part, "inline_data") and part.inline_data:
                    data = part.inline_data.data
                    if isinstance(data, str):
                        data = base64.b64decode(data)
                    return data

    except Exception as e:
        err = str(e)
        # Rate-limit / quota errors need backoff — re-raise so the retry wrapper can wait
        if any(k in err for k in ("429", "RESOURCE_EXHAUSTED", "quota", "rateLimitExceeded")):
            raise _RateLimitError(err) from e
        # All other errors: log and return None (retry wrapper decides what to do next)
        console.print(f"    [dim]AI reconstruction failed: {e}[/dim]")

    return None


# ── Retry helpers ─────────────────────────────────────────────────────────────

def _build_fallback_prompts(full_prompt: str, zones: Optional[dict]) -> List[str]:
    """
    Return a list of 3 progressively simpler prompts for the retry ladder.

    Level 1 — full art-direction prompt (original, passed in as full_prompt).
    Level 2 — zone coordinates + minimal instruction (removes complex art direction
               that may trigger content filters or confuse the model).
    Level 3 — absolute minimum: "put logo on photo" (last resort).
    """
    zone_text = _zones_to_text(zones) if zones else ""

    # Level 2: zone coords + basic instruction only
    simplified = (
        "You are a photo editor. Integrate the brand logo into the photo.\n\n"
        + (zone_text + "\n\n" if zone_text else "")
        + "Instructions:\n"
        "• LOGO zone: place the logo (second image) centered in that area, "
        "rendered naturally on the material.\n"
        "• SURFACE zone (if any): apply the brand primary color.\n"
        "• TEXT zone (if any): render the brand name in clean typography.\n"
        "Keep all other parts of the photo pixel-perfect. Output the final image only."
    )

    # Level 3: absolute minimum — avoids any detail that could confuse the model
    minimal = (
        "Combine these two images: place the logo (second image) onto the photo "
        "(first image) in a natural, centered position. "
        "Preserve the photo's composition and surroundings. Output image only."
    )

    return [full_prompt, simplified, minimal]


def _ai_reconstruct_with_retry(
    original_path: Optional[Path],
    full_prompt: str,
    logo_path: Optional[Path],
    api_key: str,
    zones: Optional[dict] = None,
    max_attempts: int = MAX_ATTEMPTS,
    backoff_base: float = BACKOFF_BASE,
    retry_wait: float = RETRY_WAIT,
) -> Optional[bytes]:
    """
    Call _ai_reconstruct_mockup with automatic retry and prompt fallback.

    Retry strategy (up to max_attempts total):
    ┌─────────────────────────────────────────────────────────────────────────┐
    │ Outcome            │ Action                                             │
    ├─────────────────────────────────────────────────────────────────────────┤
    │ Success            │ Return immediately                                 │
    │ _RateLimitError    │ Wait backoff_base × 2^(rate_hits-1) s, same prompt│
    │ None (no image)    │ Advance to next (simpler) prompt level             │
    │ Other exception    │ Wait retry_wait s, advance to next prompt level   │
    └─────────────────────────────────────────────────────────────────────────┘

    Rate-limit waits do NOT consume an attempt slot — they retry the same prompt.
    """
    if not original_path:
        return None

    prompts = _build_fallback_prompts(full_prompt, zones)
    prompt_idx = 0     # which prompt level we're on (0 = full, 1 = simplified, 2 = minimal)
    attempt    = 0     # total attempts consumed (rate-limit retries don't count)
    rate_hits  = 0     # how many rate-limit events so far (for exponential backoff)

    while attempt < max_attempts and prompt_idx < len(prompts):
        prompt  = prompts[prompt_idx]
        level   = ["full", "simplified", "minimal"][min(prompt_idx, 2)]
        attempt += 1

        try:
            result = _ai_reconstruct_mockup(
                original_path=original_path,
                prompt=prompt,
                logo_path=logo_path,
                api_key=api_key,
                zones=zones,
            )

            if result is not None:
                if prompt_idx > 0:
                    console.print(
                        f"      [dim]↳ succeeded on attempt {attempt} ({level} prompt)[/dim]"
                    )
                return result

            # API returned nothing (content filter or empty response)
            prompt_idx += 1
            if prompt_idx < len(prompts) and attempt < max_attempts:
                console.print(
                    f"      [dim]↳ attempt {attempt} ({level}): no image returned — "
                    f"retrying with {['full','simplified','minimal'][prompt_idx]} prompt…[/dim]"
                )

        except _RateLimitError:
            rate_hits += 1
            wait = backoff_base * (2 ** (rate_hits - 1))
            console.print(
                f"      [yellow]↳ attempt {attempt} ({level}): rate limit — "
                f"waiting {wait:.0f}s then retrying same prompt…[/yellow]"
            )
            time.sleep(wait)
            attempt -= 1  # rate-limit retry does not consume an attempt slot

        except Exception as exc:
            console.print(
                f"      [dim]↳ attempt {attempt} ({level}): error ({exc}) — "
                f"waiting {retry_wait:.0f}s…[/dim]"
            )
            time.sleep(retry_wait)
            prompt_idx += 1  # move to simpler prompt after a hard error

    return None


# ── Public API ────────────────────────────────────────────────────────────────

def composite_all_mockups(
    all_assets: Dict[int, "DirectionAssets"],
    metadata_path: Path = METADATA_PATH,
    processed_dir: Path = PROCESSED_DIR,
) -> Dict[int, List[Path]]:
    """
    Composite brand assets onto every processed mockup for every direction.

    Pipeline (always AI — no Pillow fallback):
      1. Read processed image with Pillow → extract zone bounding boxes (local, never sent to AI).
      2. Find matching high-quality original photo from originals/.
      3. Build prompt embedding zone coordinates as plain text.
      4. Call Gemini with: original photo + brand logo (NO processed image).
         Gemini reconstructs the original photo with brand identity integrated at
         the specified zone coordinates.

    The processed image is used ONLY for programmatic zone detection.
    It is never forwarded to any AI model as a visual input.

    Args:
        all_assets:    Dict mapping option_number → DirectionAssets.
        metadata_path: Path to metadata.json (unused — zones read from processed images).
        processed_dir: Directory containing processed guide images.

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
    if not api_key:
        console.print("  [yellow]⚠ GEMINI_API_KEY not set — cannot run AI reconstruction[/yellow]")
        return {}

    results: Dict[int, List[Path]] = {}

    for num, assets in all_assets.items():
        if assets.background and assets.background.parent.exists():
            mockup_dir = assets.background.parent / "mockups"
        else:
            slug = _slugify(assets.direction.direction_name)
            mockup_dir = Path("outputs") / f"option_{num}_{slug}" / "mockups"
        mockup_dir.mkdir(parents=True, exist_ok=True)

        composited: List[Path] = []
        ok_count   = 0
        fail_count = 0
        brand_name = getattr(assets, "brand_name", "") or assets.direction.direction_name

        total_mp = len(processed_files)
        console.print(f"\n  Option {num} — AI compositing {total_mp} mockup(s)…")

        for mp_idx, mp in enumerate(processed_files, 1):
            out_path = mockup_dir / (mp.stem + "_composite.png")
            console.print(f"    → [{mp_idx}/{total_mp}] {mp.stem}…", end=" ")
            try:
                # ── Step 1: Extract zones programmatically (Pillow only) ───────
                zones     = _extract_zones(mp)
                zone_text = _zones_to_text(zones)
                n_zones   = len(zones)

                # ── Step 2: Find high-quality original ────────────────────────
                original_path = _find_original(mp)
                if not original_path:
                    console.print(
                        f"    [yellow]⚠ {mp.name}: original not found — skipping[/yellow]"
                    )
                    fail_count += 1
                    continue

                # ── Step 3: Build prompt with embedded zone coords ─────────────
                mockup_key = MOCKUP_KEY_MAP.get(mp.name, "")
                prompt     = build_mockup_prompt(
                    mockup_key, assets, brand_name, zone_text=zone_text
                )

                # ── Step 4: AI reconstruction — original + logo only ──────────
                # Prefer transparent logo (cleaner integration)
                logo_for_ai = (
                    assets.logo_transparent
                    if (assets.logo_transparent
                        and assets.logo_transparent.exists()
                        and assets.logo_transparent.stat().st_size > 100)
                    else assets.logo
                )

                ai_bytes = _ai_reconstruct_with_retry(
                    original_path=original_path,
                    full_prompt=prompt,
                    logo_path=logo_for_ai,
                    api_key=api_key,
                    zones=zones,
                )

                if ai_bytes:
                    out_path.write_bytes(ai_bytes)
                    composited.append(out_path)
                    console.print(
                        f"[green]✓[/green]  [dim]zones:{n_zones}  orig:{original_path.name}[/dim]"
                    )
                    ok_count += 1
                else:
                    console.print(f"[yellow]⚠ all {MAX_ATTEMPTS} attempts failed — skipped[/yellow]")
                    fail_count += 1

            except Exception as exc:
                console.print(f"[yellow]✗ ERROR: {exc}[/yellow]")
                fail_count += 1

        results[num] = composited
        console.print(
            f"    [dim]→ {mockup_dir}  "
            f"({ok_count} ok  {fail_count} failed  of {len(processed_files)})[/dim]"
        )

    return results
