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

from google import genai
from google.genai import types
from rich.console import Console

from .director import BrandDirection

console = Console()


@dataclass
class DirectionAssets:
    direction: BrandDirection
    background: Optional[Path]            # 1536x864 atmospheric scene
    logo: Optional[Path]                  # 800x800 logo concept mark
    pattern: Optional[Path]               # 800x800 brand pattern tile
    mockups: Optional[List[Path]] = field(default=None)  # composited mockup images


def generate_all_assets(
    directions: list,
    output_dir: Path,
) -> dict:
    """
    Generate bg + logo + pattern for every direction.

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
        assets = _generate_direction_assets(direction, output_dir)
        results[direction.option_number] = assets

    return results


def _generate_direction_assets(
    direction: BrandDirection,
    output_dir: Path,
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
    )

    pattern = _generate_image(
        prompt=direction.pattern_prompt,
        save_path=asset_dir / "pattern.png",
        label="pattern",
        size_hint="square tile, seamlessly repeatable",
    )

    return DirectionAssets(
        direction=direction,
        background=background,
        logo=logo,
        pattern=pattern,
    )


def _generate_image(
    prompt: str,
    save_path: Path,
    label: str,
    size_hint: str,
) -> Optional[Path]:
    """
    Call Gemini image generation. Returns save_path on success, None on failure.
    Falls back to creating a placeholder if Gemini fails.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print(f"  [yellow]⚠ GEMINI_API_KEY not set — skipping {label}[/yellow]")
        return None

    full_prompt = (
        f"{prompt}\n\n"
        f"Composition: {size_hint}. "
        f"Important: absolutely no text, no words, no letters anywhere in the image."
    )

    try:
        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model="gemini-2.0-flash-exp-image-generation",
            contents=full_prompt,
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
                    console.print(f"  [green]✓ {label}[/green] → {save_path.name}")
                    return save_path

        console.print(f"  [yellow]⚠ Gemini returned no image for {label} — using placeholder[/yellow]")

    except Exception as e:
        console.print(f"  [yellow]⚠ Gemini {label} failed ({e}) — using placeholder[/yellow]")

    # Fallback: solid color placeholder
    _write_placeholder(save_path, label)
    return save_path


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


def _slugify(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:30]
