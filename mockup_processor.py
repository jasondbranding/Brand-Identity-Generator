#!/usr/bin/env python3
"""Batch mockup processor using Gemini API for placeholder generation and brand compositing."""

from __future__ import annotations

import base64
import io
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image
import numpy as np

load_dotenv()

RAW_DIR         = Path("mockups/raw")
TRANSPARENT_DIR = Path("mockups/transparent")
PROCESSED_DIR   = Path("mockups/processed")
COMPOSITED_DIR  = Path("mockups/composited")
METADATA_PATH   = Path("mockups/metadata.json")

IMAGE_MODEL = "gemini-2.5-flash"

PLACEHOLDER_PROMPT = (
    "Recreate this mockup exactly. Remove any existing logo, branding, app icon, or text. "
    "Replace logo/icon area with solid flat magenta #FF00FF rectangle (no rounded corners, pure solid color). "
    "Replace brand name/text area with solid flat cyan #00FFFF rectangle. "
    "Keep device, lighting, angle, background 100% identical."
)

BG_REMOVE_PROMPT = (
    "Remove the background from this image completely. "
    "Keep only the device/mockup object with full detail. "
    "Output a PNG with transparent background."
)

MAGENTA         = (255, 0, 255)
CYAN            = (0, 255, 255)
COLOR_TOLERANCE = 30
ALPHA_THRESHOLD = 240


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def has_transparency(img_path: Path) -> bool:
    """Check if a PNG already has meaningful transparency."""
    img = Image.open(img_path)
    if img.mode != "RGBA":
        return False
    alpha = np.array(img)[:, :, 3]
    transparent_ratio = np.sum(alpha < ALPHA_THRESHOLD) / alpha.size
    return transparent_ratio > 0.01  # >1% transparent pixels


def detect_bounding_box(
    img_array: np.ndarray,
    target_rgb: tuple,
    tolerance: int = COLOR_TOLERANCE,
) -> Optional[list]:
    """Detect bounding box of a solid color region in an image array."""
    r, g, b = target_rgb
    mask = (
        (np.abs(img_array[:, :, 0].astype(int) - r) <= tolerance)
        & (np.abs(img_array[:, :, 1].astype(int) - g) <= tolerance)
        & (np.abs(img_array[:, :, 2].astype(int) - b) <= tolerance)
    )
    coords = np.argwhere(mask)
    if coords.size == 0:
        return None
    y1, x1 = coords.min(axis=0)
    y2, x2 = coords.max(axis=0)
    return [int(x1), int(y1), int(x2), int(y2)]


def extract_image_from_response(response) -> Optional[bytes]:
    """Pull the first image blob out of a Gemini response."""
    for candidate in response.candidates or []:
        if not candidate.content:
            continue
        for part in candidate.content.parts or []:
            if hasattr(part, "inline_data") and part.inline_data:
                data = part.inline_data.data
                if isinstance(data, str):
                    data = base64.b64decode(data)
                return data
    return None


def _pil_to_part(img: Image.Image) -> types.Part:
    """Convert a PIL image to a Gemini SDK Part (PNG bytes)."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png")


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def remove_background(client: genai.Client, img_path: Path) -> Optional[Path]:
    """Use Gemini to remove background and save as transparent PNG."""
    img = Image.open(img_path)
    response = client.models.generate_content(
        model=IMAGE_MODEL,
        contents=[BG_REMOVE_PROMPT, _pil_to_part(img)],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )
    img_data = extract_image_from_response(response)
    if img_data is None:
        return None
    out = TRANSPARENT_DIR / (img_path.stem + ".png")
    out.write_bytes(img_data)
    return out


def process_placeholders(
    client: genai.Client,
    img_path: Path,
) -> Tuple[Optional[Path], dict]:
    """Send image to Gemini for placeholder insertion and detect regions."""
    img = Image.open(img_path)
    response = client.models.generate_content(
        model=IMAGE_MODEL,
        contents=[PLACEHOLDER_PROMPT, _pil_to_part(img)],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )
    img_data = extract_image_from_response(response)
    if img_data is None:
        return None, {}

    output_path = PROCESSED_DIR / img_path.name
    output_path.write_bytes(img_data)

    result_img = np.array(Image.open(output_path).convert("RGB"))
    regions: dict = {}

    logo_box = detect_bounding_box(result_img, MAGENTA)
    if logo_box:
        regions["logo_area"] = logo_box

    text_box = detect_bounding_box(result_img, CYAN)
    if text_box:
        regions["text_area"] = text_box

    return output_path, regions


def composite_mockup(
    mockup_transparent: Union[str, Path],
    brand_color: str,
    logo_png: Union[str, Path],
    metadata: dict,
    client: Optional[genai.Client] = None,
    output_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Compose a final branded mockup.

    1. Generate a background via Gemini using the brand color/style.
    2. Paste the transparent mockup on top.
    3. Paste the logo into the detected logo_area coordinates.

    Args:
        mockup_transparent: Path to the transparent-background mockup PNG.
        brand_color: Hex color string (e.g. "#3B82F6") for the background.
        logo_png: Path to the brand logo PNG (transparent).
        metadata: Dict with "logo_area" [x1,y1,x2,y2] (and optionally "text_area").
        client: Configured Gemini Client (created from env if None).
        output_path: Where to save. Defaults to mockups/composited/<stem>_branded.png.

    Returns:
        Path to the composited output image.
    """
    mockup_transparent = Path(mockup_transparent)
    logo_png = Path(logo_png)

    if client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not found in .env")
        client = genai.Client(api_key=api_key)

    mockup_img = Image.open(mockup_transparent).convert("RGBA")
    w, h = mockup_img.size

    # --- 1. Generate branded background via Gemini ---
    bg_prompt = (
        f"Generate a clean, minimal gradient background image at {w}x{h} pixels. "
        f"Use {brand_color} as the primary color with subtle lighting and soft gradients. "
        f"No text, no objects, no patterns — just a smooth professional backdrop."
    )
    response = client.models.generate_content(
        model=IMAGE_MODEL,
        contents=[bg_prompt],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )
    bg_data = extract_image_from_response(response)
    if bg_data:
        bg_img = Image.open(io.BytesIO(bg_data)).convert("RGBA").resize((w, h))
    else:
        # Fallback: solid color background
        hex_clean = brand_color.lstrip("#")
        rgb = tuple(int(hex_clean[i: i + 2], 16) for i in (0, 2, 4))
        bg_img = Image.new("RGBA", (w, h), rgb + (255,))

    # --- 2. Paste transparent mockup onto background ---
    composite = Image.alpha_composite(bg_img, mockup_img)

    # --- 3. Paste logo into detected logo_area ---
    logo_area = metadata.get("logo_area")
    if logo_area:
        x1, y1, x2, y2 = logo_area
        box_w, box_h = x2 - x1, y2 - y1
        logo_img = Image.open(logo_png).convert("RGBA")
        logo_img = logo_img.resize((box_w, box_h), Image.LANCZOS)
        composite.paste(logo_img, (x1, y1), logo_img)

    # --- Save ---
    if output_path is None:
        COMPOSITED_DIR.mkdir(parents=True, exist_ok=True)
        output_path = COMPOSITED_DIR / f"{mockup_transparent.stem}_branded.png"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    composite.save(output_path, "PNG")
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in .env", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    for d in [RAW_DIR, TRANSPARENT_DIR, PROCESSED_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    image_extensions = {".png", ".jpg", ".jpeg", ".webp"}
    images = sorted(p for p in RAW_DIR.iterdir() if p.suffix.lower() in image_extensions)

    if not images:
        print(f"No images found in {RAW_DIR}/")
        print(f"Add mockup photos to {RAW_DIR}/ and re-run.")
        sys.exit(0)

    print(f"Found {len(images)} image(s) in {RAW_DIR}/\n")

    metadata: dict = {}
    if METADATA_PATH.exists():
        metadata = json.loads(METADATA_PATH.read_text())

    for i, img_path in enumerate(images, 1):
        name = img_path.name
        already_transparent = (
            img_path.suffix.lower() == ".png" and has_transparency(img_path)
        )
        tag = "transparent" if already_transparent else "has-bg"
        print(f"[{i}/{len(images)}] {name} ({tag})")

        # --- Step 1: Ensure transparent version exists ---
        if already_transparent:
            transparent_path = TRANSPARENT_DIR / (img_path.stem + ".png")
            Image.open(img_path).save(transparent_path, "PNG")
            print(f"  -> Copied to {transparent_path}")
        else:
            print(f"  -> Removing background...", end=" ", flush=True)
            try:
                transparent_path = remove_background(client, img_path)
                if transparent_path is None:
                    print("FAILED (no image in response)")
                    continue
                print(f"OK -> {transparent_path}")
            except Exception as e:
                print(f"ERROR: {e}")
                continue

        # --- Step 2: Placeholder detection ---
        print(f"  -> Detecting placeholders...", end=" ", flush=True)
        try:
            processed_path, regions = process_placeholders(client, img_path)
            if processed_path is None:
                print("FAILED (no image in response)")
                metadata[name] = {"has_transparent_bg": already_transparent}
                continue

            detected = []
            if "logo_area" in regions:
                detected.append(f"logo={regions['logo_area']}")
            if "text_area" in regions:
                detected.append(f"text={regions['text_area']}")
            det_str = ", ".join(detected) if detected else "no placeholders detected"
            print(f"OK ({det_str})")

            metadata[name] = {
                "has_transparent_bg": already_transparent,
                "transparent_path": str(transparent_path),
                "processed_path": str(processed_path),
                **regions,
            }
        except Exception as e:
            print(f"ERROR: {e}")
            metadata[name] = {"has_transparent_bg": already_transparent}

    METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    METADATA_PATH.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"\nMetadata saved to {METADATA_PATH}")
    print("Done.")


if __name__ == "__main__":
    main()
