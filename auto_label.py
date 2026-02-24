#!/usr/bin/env python3
"""
auto_label.py — Auto-detect placeholder zones in processed mockups.

Scans mockups/processed/ and detects bounding boxes for:
  Magenta  #FF00FF  → logo_area
  Cyan     #00FFFF  → text_area
  Yellow   #FFFF00  → surface_area

Merges results into mockups/metadata.json, preserving existing fields.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    import numpy as np
    from PIL import Image
except ImportError as e:
    print(f"Error: missing dependency — {e}")
    print("Run: pip install Pillow numpy")
    sys.exit(1)


# ── Config ────────────────────────────────────────────────────────────────────

PROCESSED_DIR = Path("mockups/processed")
METADATA_PATH = Path("mockups/metadata.json")

IMAGE_EXTS    = {".png", ".jpg", ".jpeg", ".webp"}
TOLERANCE     = 30   # ±30 per channel

# (metadata_key, label, target_rgb)
ZONES = [
    ("logo_area",    "LOGO",    (255,   0, 255)),
    ("text_area",    "TEXT",    (  0, 255, 255)),
    ("surface_area", "SURFACE", (255, 255,   0)),
]

# Minimum pixel area for a zone to be considered valid (avoids noise)
MIN_PIXEL_COUNT = 50


# ── Core detection ────────────────────────────────────────────────────────────

def detect_bbox(
    img_array: np.ndarray,
    target_rgb: Tuple[int, int, int],
    tolerance: int = TOLERANCE,
) -> Optional[Dict[str, int]]:
    """
    Find bounding box of pixels close to target_rgb.
    Returns {"x": int, "y": int, "w": int, "h": int} or None.
    """
    r, g, b = target_rgb
    arr = img_array[:, :, :3].astype(np.int16)   # ignore alpha
    mask = (
        (np.abs(arr[:, :, 0] - r) <= tolerance) &
        (np.abs(arr[:, :, 1] - g) <= tolerance) &
        (np.abs(arr[:, :, 2] - b) <= tolerance)
    )
    if mask.sum() < MIN_PIXEL_COUNT:
        return None
    coords = np.argwhere(mask)   # shape (N, 2) → (row, col)
    y1, x1 = coords.min(axis=0)
    y2, x2 = coords.max(axis=0)
    return {
        "x": int(x1),
        "y": int(y1),
        "w": int(x2 - x1),
        "h": int(y2 - y1),
    }


def label_image(img_path: Path) -> Dict[str, Dict[str, int]]:
    """
    Open an image and detect all zone colors.
    Returns dict of found zones (only those that matched).
    """
    img = Image.open(img_path).convert("RGBA")
    arr = np.array(img)
    zones_found: Dict[str, Dict[str, int]] = {}
    for key, label, rgb in ZONES:
        bbox = detect_bbox(arr, rgb)
        if bbox is not None:
            zones_found[key] = bbox
    return zones_found


# ── Metadata helpers ──────────────────────────────────────────────────────────

def load_metadata(path: Path) -> Dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_metadata(path: Path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\nMetadata saved → {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not PROCESSED_DIR.exists():
        print(f"Error: {PROCESSED_DIR} not found.")
        sys.exit(1)

    images = sorted(
        p for p in PROCESSED_DIR.iterdir()
        if p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")
    )
    if not images:
        print(f"No images found in {PROCESSED_DIR}/")
        sys.exit(0)

    metadata = load_metadata(METADATA_PATH)
    total_zones = 0
    print(f"Scanning {len(images)} image(s) in {PROCESSED_DIR}/\n")

    for img_path in images:
        name = img_path.name
        found = label_image(img_path)

        # Merge into existing entry (or create new one)
        entry = metadata.get(name, {})
        for key, bbox in found.items():
            entry[key] = bbox
        if found:
            metadata[name] = entry
        total_zones += len(found)

        # ── Print summary line ─────────────────────────────────────────────
        if found:
            parts = []
            for key, label, _ in ZONES:
                if key in found:
                    b = found[key]
                    parts.append(f"{label} ({b['w']}×{b['h']}  @{b['x']},{b['y']})")
            zones_str = "  +  ".join(parts)
        else:
            zones_str = "— no placeholder colors detected"
        print(f"  {name}")
        print(f"      {zones_str}")

    save_metadata(METADATA_PATH, metadata)
    print(f"\nTotal zones detected: {total_zones}  across {len(images)} image(s)")


if __name__ == "__main__":
    main()
