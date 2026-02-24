#!/usr/bin/env python3
"""
build_reference_index.py — Auto-label reference images using Gemini Vision.

Scans references/logos/ and references/patterns/, sends each image to Gemini
for structured tagging, and writes index.json in each folder.

Usage:
  python scripts/build_reference_index.py                     # all
  python scripts/build_reference_index.py --type logos         # logos only
  python scripts/build_reference_index.py --type patterns      # patterns only
  python scripts/build_reference_index.py --dry-run            # preview, don't save
  python scripts/build_reference_index.py --force              # re-tag everything
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# ── Resolve project root ─────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
REFERENCES_DIR = PROJECT_ROOT / "references"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# Load .env from project root
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

# ── Tagging taxonomy ─────────────────────────────────────────────────────────

LOGO_FORM_VALUES = [
    "wordmark", "lettermark", "monogram", "symbol",
    "combination", "emblem", "abstract",
]

STYLE_VALUES = [
    "geometric", "organic", "monoline", "filled", "3d",
    "minimal", "detailed", "flat", "gradient", "textured",
    "sharp", "rounded", "hand-drawn", "pixel", "retro",
    "modern", "classic", "brutalist", "elegant", "playful",
]

TECHNIQUE_VALUES = [
    "negative space", "grid construction", "golden ratio",
    "symmetry", "asymmetry", "optical illusion",
    "line weight", "counter forms", "modularity",
    "overlap", "fragmentation", "rotation",
]

INDUSTRY_VALUES = [
    "tech", "saas", "fintech", "crypto", "web3", "healthcare",
    "ecommerce", "education", "real-estate", "food", "beverage",
    "fashion", "automotive", "media", "consulting",
    "startup", "enterprise", "creative", "nonprofit", "gaming",
]

MOOD_VALUES = [
    "confident", "calm", "bold", "playful", "serious",
    "premium", "accessible", "warm", "cold", "edgy",
    "trustworthy", "innovative", "elegant", "minimal", "powerful",
    "friendly", "mysterious", "dynamic", "stable", "futuristic",
]

COLOR_VALUES = [
    "monochrome", "duo-tone", "multi-color", "gradient",
    "dark", "light", "vibrant", "muted",
    "warm", "cool", "neutral", "neon",
    "pastel", "earth-tone", "metallic", "high-contrast",
]

# ── Gemini Vision prompt ─────────────────────────────────────────────────────

LOGO_PROMPT = """\
You are a professional brand identity analyst. Analyze this logo/mark image and return a JSON object with exactly these fields:

{
  "form": "<one of: wordmark, lettermark, monogram, symbol, combination, emblem, abstract>",
  "style": ["<2-4 values from: geometric, organic, monoline, filled, 3d, minimal, detailed, flat, gradient, textured, sharp, rounded, hand-drawn, pixel, retro, modern, classic, brutalist, elegant, playful>"],
  "technique": ["<1-3 values from: negative space, grid construction, golden ratio, symmetry, asymmetry, optical illusion, line weight, counter forms, modularity, overlap, fragmentation, rotation>"],
  "industry": ["<1-3 industries this logo style fits: tech, saas, fintech, crypto, web3, healthcare, ecommerce, education, real-estate, food, beverage, fashion, automotive, media, consulting, startup, enterprise, creative, nonprofit, gaming>"],
  "mood": ["<2-4 values from: confident, calm, bold, playful, serious, premium, accessible, warm, cold, edgy, trustworthy, innovative, elegant, minimal, powerful, friendly, mysterious, dynamic, stable, futuristic>"],
  "colors": ["<1-3 values from: monochrome, duo-tone, multi-color, gradient, dark, light, vibrant, muted, warm, cool, neutral, neon, pastel, earth-tone, metallic, high-contrast>"],
  "quality": <integer 1-10, how well-designed is this logo? 7=professional, 8=very good, 9=excellent, 10=iconic>
}

Rules:
- Return ONLY the JSON object, no explanation, no markdown fences.
- Use only the exact values listed above.
- Be specific: don't tag everything as "modern minimal" — look for real distinguishing features.
- Quality scoring: consider originality, craft, scalability, and memorability.
"""

PATTERN_PROMPT = """\
You are a professional surface/textile design analyst. Analyze this pattern/texture image and return a JSON object with exactly these fields:

{
  "motif": "<describe the primary motif in 2-3 words, e.g. 'hexagonal grid', 'flowing curves', 'dot matrix'>",
  "style": ["<2-4 values from: geometric, organic, monoline, filled, 3d, minimal, detailed, flat, gradient, textured, sharp, rounded, hand-drawn, pixel, retro, modern, classic, brutalist, elegant, playful>"],
  "technique": ["<1-3 values from: negative space, grid construction, golden ratio, symmetry, asymmetry, optical illusion, line weight, counter forms, modularity, overlap, fragmentation, rotation>"],
  "industry": ["<1-3 industries this pattern fits: tech, saas, fintech, crypto, web3, healthcare, ecommerce, education, real-estate, food, beverage, fashion, automotive, media, consulting, startup, enterprise, creative, nonprofit, gaming>"],
  "mood": ["<2-4 values from: confident, calm, bold, playful, serious, premium, accessible, warm, cold, edgy, trustworthy, innovative, elegant, minimal, powerful, friendly, mysterious, dynamic, stable, futuristic>"],
  "colors": ["<1-3 values from: monochrome, duo-tone, multi-color, gradient, dark, light, vibrant, muted, warm, cool, neutral, neon, pastel, earth-tone, metallic, high-contrast>"],
  "quality": <integer 1-10, how well-designed is this pattern? 7=professional, 8=very good, 9=excellent, 10=iconic>
}

Rules:
- Return ONLY the JSON object, no explanation, no markdown fences.
- Use only the exact values listed above.
- Quality scoring: consider seamless tiling ability, visual rhythm, and professional execution.
"""


# ── Gemini API client ────────────────────────────────────────────────────────

def _tag_image(
    image_path: Path,
    ref_type: str,
    api_key: str,
) -> Optional[dict]:
    """Send image to Gemini Vision, return parsed tag dict or None."""
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        img_bytes = image_path.read_bytes()
        ext = image_path.suffix.lower().lstrip(".")
        mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext or 'png'}"

        prompt = LOGO_PROMPT if ref_type == "logos" else PATTERN_PROMPT

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=img_bytes, mime_type=mime),
            ],
        )

        raw = response.text.strip()
        # Strip markdown fences if model wraps in ```json ... ```
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        tags = json.loads(raw)

        # Validate quality is int 1-10
        q = tags.get("quality", 5)
        tags["quality"] = max(1, min(10, int(q)))

        return tags

    except json.JSONDecodeError as e:
        print(f"    ⚠ JSON parse error for {image_path.name}: {e}")
        return None
    except Exception as e:
        print(f"    ⚠ Gemini error for {image_path.name}: {e}")
        return None


# ── Index builder ─────────────────────────────────────────────────────────────

def build_index(
    ref_type: str,
    api_key: str,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """Build or update index.json for a reference type."""
    ref_dir = REFERENCES_DIR / ref_type
    if not ref_dir.exists():
        print(f"  ⚠ {ref_dir} not found — skipping")
        return {}

    index_path = ref_dir / "index.json"
    existing: dict = {}
    if index_path.exists() and not force:
        try:
            existing = json.loads(index_path.read_text())
        except Exception:
            pass

    images = sorted(
        p for p in ref_dir.iterdir()
        if p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")
    )

    if not images:
        print(f"  ⚠ No images in {ref_dir}")
        return existing

    # Filter out already-tagged (unless --force)
    to_tag = []
    for img in images:
        if img.name in existing and not force:
            continue
        to_tag.append(img)

    total = len(images)
    skip = total - len(to_tag)
    print(f"\n{'='*60}")
    print(f"  {ref_type.upper()}: {total} images, {skip} already tagged, {len(to_tag)} to process")
    print(f"{'='*60}")

    if not to_tag:
        print("  ✓ All images already tagged")
        return existing

    tagged = 0
    failed = 0

    for i, img_path in enumerate(to_tag, 1):
        print(f"\n  [{i}/{len(to_tag)}] {img_path.name}")

        if dry_run:
            print(f"    → (dry run) would tag with Gemini Vision")
            continue

        tags = _tag_image(img_path, ref_type, api_key)

        if tags:
            existing[img_path.name] = {
                "local_path": str(img_path),
                "tags": tags,
            }
            # Print compact summary
            q = tags.get("quality", "?")
            form = tags.get("form", tags.get("motif", "?"))
            styles = ", ".join(tags.get("style", [])[:3])
            moods = ", ".join(tags.get("mood", [])[:3])
            print(f"    ✓ q={q}  form={form}  style=[{styles}]  mood=[{moods}]")
            tagged += 1
        else:
            failed += 1

        # Rate limiting — Gemini free tier: ~15 RPM
        if i < len(to_tag):
            time.sleep(4)

    # Save
    if not dry_run and tagged > 0:
        index_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
        print(f"\n  → Saved {index_path}  ({len(existing)} total entries)")

    print(f"\n  Summary: {tagged} tagged, {failed} failed, {skip} skipped")
    return existing


# ── Stats ─────────────────────────────────────────────────────────────────────

def print_stats(index: dict, ref_type: str) -> None:
    """Print distribution stats for an index."""
    if not index:
        return

    print(f"\n{'─'*60}")
    print(f"  {ref_type.upper()} DISTRIBUTION ({len(index)} images)")
    print(f"{'─'*60}")

    # Collect all tag values
    counters: Dict[str, Dict[str, int]] = {}
    quality_scores: List[int] = []

    for entry in index.values():
        tags = entry.get("tags", {})
        q = tags.get("quality", 0)
        quality_scores.append(q)

        # Count form/motif
        form_key = "form" if ref_type == "logos" else "motif"
        form = tags.get(form_key, "unknown")
        counters.setdefault(form_key, {})
        counters[form_key][form] = counters[form_key].get(form, 0) + 1

        # Count list fields
        for field in ("style", "mood", "industry", "colors"):
            counters.setdefault(field, {})
            for v in tags.get(field, []):
                counters[field][v] = counters[field].get(v, 0) + 1

    # Quality summary
    if quality_scores:
        avg = sum(quality_scores) / len(quality_scores)
        below7 = sum(1 for q in quality_scores if q < 7)
        print(f"\n  Quality: avg={avg:.1f}  min={min(quality_scores)}  max={max(quality_scores)}")
        if below7:
            print(f"  ⚠ {below7} images scored below 7 — consider removing")

    # Top values per field
    for field, counts in counters.items():
        sorted_items = sorted(counts.items(), key=lambda x: -x[1])[:8]
        items_str = "  ".join(f"{v}({c})" for v, c in sorted_items)
        print(f"\n  {field}: {items_str}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-label reference images using Gemini Vision"
    )
    parser.add_argument(
        "--type", choices=["logos", "patterns"],
        help="Process only this reference type (default: both)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview which images would be tagged without calling API",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-tag all images even if already in index.json",
    )
    parser.add_argument(
        "--stats-only", action="store_true",
        help="Print distribution stats from existing index.json without tagging",
    )
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and not args.dry_run and not args.stats_only:
        print("Error: GEMINI_API_KEY not set")
        print("  export GEMINI_API_KEY=your-key-here")
        sys.exit(1)

    types_to_process = [args.type] if args.type else ["logos", "patterns"]

    for ref_type in types_to_process:
        ref_dir = REFERENCES_DIR / ref_type
        if not ref_dir.exists():
            print(f"  ⚠ {ref_dir} not found — skipping")
            continue

        if args.stats_only:
            index_path = ref_dir / "index.json"
            if index_path.exists():
                index = json.loads(index_path.read_text())
                print_stats(index, ref_type)
            else:
                print(f"  ⚠ No index.json in {ref_dir}")
            continue

        index = build_index(
            ref_type,
            api_key or "",
            dry_run=args.dry_run,
            force=args.force,
        )
        print_stats(index, ref_type)

    print("\n✓ Done\n")


if __name__ == "__main__":
    main()
