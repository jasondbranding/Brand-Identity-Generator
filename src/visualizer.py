"""
Visualizer — generates one stylescape image per brand direction using Gemini.

Primary:  google-genai SDK → gemini-2.0-flash-exp-image-generation
Fallback: Pillow-generated color-palette card if Gemini image gen fails
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from rich.console import Console

from .director import BrandDirection, BrandDirectionsOutput

console = Console()

OUTPUTS_DIR = Path("outputs/images")


def generate_images(output: BrandDirectionsOutput, output_dir: Path = OUTPUTS_DIR) -> Dict[int, Path]:
    """
    Generate one image per direction.

    Returns:
        Dict mapping option_number → saved image path
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    image_paths: Dict[int, Path] = {}

    for direction in output.directions:
        console.print(
            f"\n[bold cyan]→ Generating image for Option {direction.option_number}: "
            f"{direction.direction_name}...[/bold cyan]"
        )

        save_path = output_dir / f"direction_{direction.option_number}_{_slugify(direction.direction_name)}.png"

        success = _try_gemini(direction, save_path)
        if not success:
            console.print(
                f"  [yellow]⚠ Gemini image gen unavailable — generating palette card instead[/yellow]"
            )
            _generate_palette_card(direction, save_path)

        image_paths[direction.option_number] = save_path
        console.print(f"  [green]✓ Saved → {save_path}[/green]")

    return image_paths


def _try_gemini(direction: BrandDirection, save_path: Path) -> bool:
    """
    Attempt to generate an image via Gemini. Returns True on success.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print("  [dim]GEMINI_API_KEY not set — skipping Gemini[/dim]")
        return False

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig

        client = genai.Client(api_key=api_key)

        # Enrich the image prompt with color context
        color_block = ", ".join(f"{c.name} ({c.hex})" for c in direction.colors)
        full_prompt = (
            f"{direction.image_prompt}\n\n"
            f"Brand palette: {color_block}.\n"
            f"Direction name: {direction.direction_name}.\n"
            f"Style: {direction.graphic_style}"
        )

        response = client.models.generate_content(
            model="gemini-2.0-flash-exp-image-generation",
            contents=full_prompt,
            config=GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )

        # Extract image bytes from response
        for candidate in response.candidates or []:
            for part in candidate.content.parts or []:
                if hasattr(part, "inline_data") and part.inline_data:
                    data = part.inline_data.data
                    # data may be bytes or base64 string
                    if isinstance(data, str):
                        import base64
                        data = base64.b64decode(data)
                    save_path.write_bytes(data)
                    return True

        console.print("  [dim]Gemini returned no image data[/dim]")
        return False

    except ImportError:
        console.print("  [dim]google-genai not installed — skipping Gemini[/dim]")
        return False
    except Exception as e:
        console.print(f"  [dim]Gemini error: {e}[/dim]")
        return False


def _generate_palette_card(direction: BrandDirection, save_path: Path) -> None:
    """
    Fallback: generate a branded palette card using Pillow.
    Shows the direction name, type, color swatches, and key typography notes.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        save_path.write_bytes(b"")  # empty placeholder
        return

    W, H = 1600, 900
    img = Image.new("RGB", (W, H), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    # Parse hex colors safely
    def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
        h = hex_str.strip("#")
        if len(h) == 3:
            h = h[0]*2 + h[1]*2 + h[2]*2
        try:
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            return (180, 180, 180)

    colors = direction.colors[:6]

    # Background: first color (primary)
    bg_rgb = hex_to_rgb(colors[0].hex) if colors else (30, 30, 40)
    img = Image.new("RGB", (W, H), bg_rgb)
    draw = ImageDraw.Draw(img)

    # Color swatches — bottom third
    swatch_h = 180
    swatch_y = H - swatch_h
    swatch_w = W // max(len(colors), 1)
    for i, swatch in enumerate(colors):
        rgb = hex_to_rgb(swatch.hex)
        x0 = i * swatch_w
        draw.rectangle([x0, swatch_y, x0 + swatch_w, H], fill=rgb)

    # Dark overlay for text legibility
    overlay = Image.new("RGBA", (W, swatch_y), (0, 0, 0, 120))
    img.paste(Image.new("RGB", (W, swatch_y), bg_rgb), (0, 0))
    img = img.convert("RGBA")
    img.alpha_composite(overlay, (0, 0))
    img = img.convert("RGB")
    draw = ImageDraw.Draw(img)

    # Try to load a system font; fall back to default
    try:
        font_title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 72)
        font_sub = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
    except Exception:
        font_title = font_sub = font_small = ImageFont.load_default()

    text_color = (255, 255, 255)
    accent_rgb = hex_to_rgb(colors[1].hex) if len(colors) > 1 else (200, 200, 200)

    # Direction name
    draw.text((80, 80), direction.direction_name.upper(), fill=text_color, font=font_title)

    # Option type badge
    draw.text((80, 170), f"Option {direction.option_number}  ·  {direction.option_type}", fill=accent_rgb, font=font_sub)

    # Rationale (wrapped at ~80 chars)
    rationale = _wrap_text(direction.rationale, 90)
    draw.text((80, 260), rationale, fill=(220, 220, 220), font=font_small)

    # Typography line
    draw.text((80, swatch_y - 100), f"Type: {direction.typography_primary}", fill=(200, 200, 200), font=font_small)

    # Swatch labels
    for i, swatch in enumerate(colors):
        x = i * swatch_w + 12
        draw.text((x, swatch_y + 12), swatch.name, fill=(255, 255, 255), font=font_small)
        draw.text((x, swatch_y + 44), swatch.hex, fill=(200, 200, 200), font=font_small)

    img.save(str(save_path), format="PNG")


def _wrap_text(text: str, width: int) -> str:
    """Wrap text to a max character width."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= width:
            current = (current + " " + word).strip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)


def _slugify(text: str) -> str:
    """Convert text to a safe filename slug."""
    import re
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]
