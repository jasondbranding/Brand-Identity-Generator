"""
Generator — uses Gemini to produce 3 separate raster PNGs per direction.

  background.png  — atmospheric mood scene, no text, no logos
  logo.png        — abstract logo mark on white, no text
  pattern.png     — seamless brand pattern/texture, no text

All images are pure visual — no copy, no UI. Text is added by the
compositor at assembly time.
"""

from __future__ import annotations

import base64
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np

from google import genai
from google.genai import types
from rich.console import Console

from .director import BrandDirection

console = Console()


@dataclass
class DirectionAssets:
    direction: BrandDirection
    background: Optional[Path]                                      # 1536x864 atmospheric scene
    logo: Optional[Path]                                            # 800x800 logo concept mark
    pattern: Optional[Path]                                         # 800x800 brand pattern tile
    mockups: Optional[List[Path]] = field(default=None)             # composited mockup images
    logo_white: Optional[Path] = field(default=None)                # white logo on transparent bg
    logo_black: Optional[Path] = field(default=None)                # dark logo on transparent bg
    logo_transparent: Optional[Path] = field(default=None)          # original logo, white removed


def generate_all_assets(
    directions: list,
    output_dir: Path,
    brief_keywords: Optional[list] = None,
) -> dict:
    """
    Generate bg + logo + pattern for every direction.

    Args:
        directions: List of BrandDirection objects
        output_dir: Directory to save assets
        brief_keywords: Optional brand keywords for reference image matching

    Returns:
        Dict mapping option_number → DirectionAssets
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    for direction in directions:
        console.print(
            f"\n[bold cyan]→ Generating assets for Option {direction.option_number}: "
            f"{direction.direction_name}[/bold cyan]"
        )
        assets = _generate_direction_assets(direction, output_dir, brief_keywords=brief_keywords)
        results[direction.option_number] = assets

    return results


def _generate_direction_assets(
    direction: BrandDirection,
    output_dir: Path,
    brief_keywords: Optional[list] = None,
) -> DirectionAssets:
    slug = _slugify(direction.direction_name)
    asset_dir = output_dir / f"option_{direction.option_number}_{slug}"
    asset_dir.mkdir(parents=True, exist_ok=True)

    background = _generate_image(
        prompt=direction.background_prompt,
        save_path=asset_dir / "background.png",
        label="background",
        size_hint="wide landscape, 16:9 aspect ratio",
    )

    logo = _generate_image(
        prompt=direction.logo_prompt,
        save_path=asset_dir / "logo.png",
        label="logo",
        size_hint="square format, centered mark, generous white space around it",
        brief_keywords=brief_keywords,
    )

    pattern = _generate_image(
        prompt=direction.pattern_prompt,
        save_path=asset_dir / "pattern.png",
        label="pattern",
        size_hint="square tile, seamlessly repeatable",
    )

    # Create white / black / transparent logo variants for compositor use
    variants: dict = {}
    if logo and logo.exists() and logo.stat().st_size > 100:
        variants = _create_logo_variants(logo, asset_dir)

    return DirectionAssets(
        direction=direction,
        background=background,
        logo=logo,
        pattern=pattern,
        logo_white=variants.get("logo_white"),
        logo_black=variants.get("logo_black"),
        logo_transparent=variants.get("logo_transparent"),
    )


def _try_imagen(
    prompt: str,
    api_key: str,
    aspect_ratio: str = "1:1",
) -> Optional[bytes]:
    """
    Try Imagen 3 image generation. Returns raw PNG bytes or None on any failure.
    Silent — callers decide whether to log.
    """
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio=aspect_ratio,
            ),
        )
        if response.generated_images:
            return response.generated_images[0].image.image_data
    except Exception:
        pass
    return None


def _generate_image(
    prompt: str,
    save_path: Path,
    label: str,
    size_hint: str,
    brief_keywords: Optional[list] = None,
) -> Optional[Path]:
    """
    Try Imagen 3 first, then Gemini 2.0 Flash as fallback.
    For logos: if reference images are available, use multi-modal style inspiration.
    Returns save_path on success; creates a placeholder on full failure.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print(f"  [yellow]⚠ GEMINI_API_KEY not set — skipping {label}[/yellow]")
        return None

    if label == "logo":
        full_prompt = (
            f"{prompt}\n\n"
            "Technical requirements:\n"
            "- Single iconic mark/symbol centered on pure white background\n"
            "- High contrast, clean crisp edges, professional vector quality\n"
            "- Suitable for brand identity at any scale (favicon to billboard)\n"
            "- Square format, generous padding (20%+ whitespace all sides)\n"
            "- Absolutely no text, words, letters, or typography anywhere in the image\n"
            "- Clean vector-like rendering, minimal complexity, bold and memorable\n"
            "- The mark must be immediately recognizable and reproducible at small sizes"
        )
    elif label == "pattern":
        full_prompt = (
            f"{prompt}\n\n"
            "Technical requirements:\n"
            "- Seamless tileable pattern — all 4 edges MUST align perfectly when tiled\n"
            "- Consistent density and spacing throughout the entire tile\n"
            "- Absolutely no text, words, or letters anywhere in the image\n"
            "- Square tile format, professional surface/textile design quality\n"
            "- Flat vector rendering, no noise or grain unless explicitly specified"
        )
    elif label == "background":
        full_prompt = (
            f"{prompt}\n\n"
            "Technical requirements:\n"
            "- Wide landscape 16:9 atmospheric image, fills frame edge-to-edge\n"
            "- Absolutely no text, UI elements, logos, watermarks, or typography\n"
            "- Professional photography or high-end digital art quality\n"
            "- Rich color depth and strong atmospheric mood\n"
            "- Suitable as hero image or presentation background"
        )
    else:
        full_prompt = (
            f"{prompt}\n\n"
            f"Composition: {size_hint}. "
            "Absolutely no text, no words, no letters anywhere in the image."
        )
    aspect_ratio = "16:9" if label == "background" else "1:1"

    # ── Try Imagen 3 first ─────────────────────────────────────────────────────
    img_bytes = _try_imagen(full_prompt, api_key, aspect_ratio)
    if img_bytes:
        save_path.write_bytes(img_bytes)
        console.print(f"  [green]✓ {label}[/green] (Imagen 3) → {save_path.name}")
        return save_path

    # ── Fallback: Gemini 2.0 Flash ─────────────────────────────────────────────
    try:
        client = genai.Client(api_key=api_key)

        # For logos, try to include reference images as style inspiration
        contents: object = full_prompt
        if label == "logo" and brief_keywords:
            ref_images = _get_reference_images(brief_keywords, "logos")
            if ref_images:
                parts = [types.Part.from_text(full_prompt)]
                for ref_path in ref_images[:3]:
                    try:
                        img_bytes = ref_path.read_bytes()
                        ext = ref_path.suffix.lower().lstrip(".")
                        mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext or 'png'}"
                        parts.append(types.Part.from_text(
                            "Style reference image (study the quality level and aesthetic approach, "
                            "do NOT copy this design — create something entirely original):"
                        ))
                        parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
                    except Exception:
                        pass
                if len(parts) > 1:
                    parts.append(types.Part.from_text(
                        "Now generate the new logo described above. "
                        "Create an entirely original design inspired by the quality level."
                    ))
                    contents = parts
                    console.print(
                        f"  [dim]Using {len(ref_images)} reference image(s) for logo inspiration[/dim]"
                    )

        response = client.models.generate_content(
            model="gemini-2.0-flash-exp-image-generation",
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )

        for candidate in response.candidates or []:
            for part in candidate.content.parts or []:
                if hasattr(part, "inline_data") and part.inline_data:
                    data = part.inline_data.data
                    if isinstance(data, str):
                        data = base64.b64decode(data)
                    save_path.write_bytes(data)
                    console.print(f"  [green]✓ {label}[/green] (Gemini) → {save_path.name}")
                    return save_path

        console.print(f"  [yellow]⚠ No image returned for {label} — using placeholder[/yellow]")

    except Exception as e:
        console.print(f"  [yellow]⚠ {label} generation failed ({e}) — using placeholder[/yellow]")

    # ── Final fallback: solid-colour placeholder ───────────────────────────────
    _write_placeholder(save_path, label)
    return save_path


def _get_reference_images(brief_keywords: list, ref_type: str = "logos") -> list:
    """
    Find locally cached reference images that match brand keywords.

    Loads references/{ref_type}/index.json and scores entries against keywords.
    Returns up to 3 matching Path objects.
    """
    try:
        # Project root is two levels up from src/
        project_root = Path(__file__).parent.parent
        index_dir = project_root / "references" / ref_type

        if not index_dir.exists():
            return []

        from .researcher import BrandResearcher
        # Use a dummy researcher just for the match_references method (no API needed)
        class _LocalMatcher:
            def match_references(self, keywords, index_dir, top_n=3):
                import json
                index_path = index_dir / "index.json"
                if not index_path.exists():
                    return []
                try:
                    index = json.loads(index_path.read_text())
                except Exception:
                    return []
                kw_set = {k.lower().strip() for k in keywords if k}
                scored = []
                for filename, entry in index.items():
                    tags = entry.get("tags", {})
                    all_tags: set = set()
                    for lst_key in ("style", "industry", "mood"):
                        for t in tags.get(lst_key, []):
                            all_tags.update(t.lower().split())
                    all_tags.add(tags.get("type", "").lower())
                    overlap = len(kw_set & all_tags)
                    quality = tags.get("quality", 5)
                    score = overlap + quality / 10.0
                    local_path = entry.get("local_path", "")
                    if local_path and Path(local_path).exists():
                        scored.append({"local_path": local_path, "score": score})
                scored.sort(key=lambda x: x["score"], reverse=True)
                return scored[:top_n]

        matcher = _LocalMatcher()
        results = matcher.match_references(brief_keywords, index_dir, top_n=3)
        return [Path(r["local_path"]) for r in results if Path(r["local_path"]).exists()]

    except Exception:
        return []


def _write_placeholder(save_path: Path, label: str) -> None:
    """Create a minimal placeholder PNG using Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont

        w, h = (1536, 864) if label == "background" else (800, 800)
        colors = {"background": "#1a1a2e", "logo": "#f0f0f0", "pattern": "#2d2d44"}
        bg = colors.get(label, "#222222")

        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)

        # Simple centered label
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
        except Exception:
            font = ImageFont.load_default()

        text = f"[{label}]"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((w - tw) // 2, (h - th) // 2), text, fill="#888888", font=font)
        img.save(str(save_path), format="PNG")

    except Exception:
        save_path.write_bytes(b"")


def _create_logo_variants(logo_path: Path, asset_dir: Path) -> dict:
    """
    Derive white / black / transparent logo variants from the generated logo PNG.

    Steps:
      1. Remove near-white background (brightness ≥ 240 → transparent) → logo_transparent.png
      2. Colorize all remaining opaque pixels white                     → logo_white.png
      3. Colorize all remaining opaque pixels near-black                → logo_black.png

    Returns {"logo_transparent": Path, "logo_white": Path, "logo_black": Path}
    or {} on any failure.
    """
    try:
        from PIL import Image as _PILImage

        img = _PILImage.open(logo_path).convert("RGBA")
        arr = np.array(img).astype(np.float32)

        # Step 1: Remove white background
        br = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        scale = np.clip((240 - br) / 30.0, 0.0, 1.0)
        arr[:, :, 3] = (arr[:, :, 3] * scale).clip(0, 255)
        transparent = _PILImage.fromarray(arr.astype(np.uint8), "RGBA")

        # Step 2: White logo
        white_arr = arr.copy()
        white_arr[:, :, :3] = 255
        white_logo = _PILImage.fromarray(white_arr.astype(np.uint8), "RGBA")

        # Step 3: Black logo
        black_arr = arr.copy()
        black_arr[:, :, 0] = 20
        black_arr[:, :, 1] = 20
        black_arr[:, :, 2] = 20
        black_logo = _PILImage.fromarray(black_arr.astype(np.uint8), "RGBA")

        trans_path = asset_dir / "logo_transparent.png"
        white_path = asset_dir / "logo_white.png"
        black_path = asset_dir / "logo_black.png"

        transparent.save(str(trans_path), format="PNG")
        white_logo.save(str(white_path), format="PNG")
        black_logo.save(str(black_path), format="PNG")

        console.print("  [dim]  logo variants → transparent / white / black[/dim]")
        return {
            "logo_transparent": trans_path,
            "logo_white":       white_path,
            "logo_black":       black_path,
        }
    except Exception as e:
        console.print(f"  [yellow]⚠ Logo variant creation failed: {e}[/yellow]")
        return {}


def _slugify(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:30]
