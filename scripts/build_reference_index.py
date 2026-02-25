#!/usr/bin/env python3
"""
build_reference_index.py — Auto-label reference images using Gemini Vision.

Scans references/logos/ and references/patterns/ category subdirs,
sends each image to Gemini for structured tagging, writes index.json per folder.

Usage:
  python scripts/build_reference_index.py                                  # all categories
  python scripts/build_reference_index.py --type logos/industry_tech_saas  # one category
  python scripts/build_reference_index.py --dry-run                        # preview only
  python scripts/build_reference_index.py --force                          # re-tag everything
  python scripts/build_reference_index.py --stats-only                     # stats from existing index
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR    = Path(__file__).parent
PROJECT_ROOT  = SCRIPT_DIR.parent
REFERENCES_DIR = PROJECT_ROOT / "references"
IMAGE_EXTS    = {".png", ".jpg", ".jpeg", ".webp"}

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

# ── Gemini models for vision tagging (text+image) ────────────────────────────
VISION_MODELS = [
    "gemini-2.0-flash",       # fast, excellent vision
    "gemini-1.5-flash",       # reliable fallback
    "gemini-2.5-flash",       # newest, if available
]

# ── Taxonomy ─────────────────────────────────────────────────────────────────

LOGO_PROMPT = """\
You are a professional brand identity analyst. Analyze this logo/mark image.

Return ONLY a valid JSON object with EXACTLY these fields — no explanation, no markdown fences:

{
  "form": "<one of: wordmark, lettermark, monogram, symbol, combination, emblem, abstract>",
  "style": ["<2-4 from: geometric, organic, monoline, filled, 3d, minimal, detailed, flat, gradient, textured, sharp, rounded, hand-drawn, pixel, retro, modern, classic, brutalist, elegant, playful>"],
  "technique": ["<1-3 from: negative space, grid construction, golden ratio, symmetry, asymmetry, optical illusion, line weight, counter forms, modularity, overlap, fragmentation, rotation>"],
  "industry": ["<1-3 from: tech, saas, fintech, crypto, web3, healthcare, ecommerce, education, real-estate, food, beverage, fashion, automotive, media, consulting, startup, enterprise, creative, nonprofit, gaming>"],
  "mood": ["<2-4 from: confident, calm, bold, playful, serious, premium, accessible, warm, cold, edgy, trustworthy, innovative, elegant, minimal, powerful, friendly, mysterious, dynamic, stable, futuristic>"],
  "colors": ["<1-3 from: monochrome, duo-tone, multi-color, gradient, dark, light, vibrant, muted, warm, cool, neutral, neon, pastel, earth-tone, metallic, high-contrast>"],
  "quality": <int 1-10: 6=ok, 7=professional, 8=very good, 9=excellent, 10=iconic>
}

Be specific — don't tag everything as "modern minimal". Look for real distinguishing features.
Quality: consider originality, craft, scalability, and memorability.
"""

PATTERN_PROMPT = """\
You are a professional surface/textile design analyst and brand strategist. Analyze this pattern/texture image.

Return ONLY a valid JSON object with EXACTLY these fields — no explanation, no markdown fences:

{
  "motif": "<describe the primary motif in 2-4 words, e.g. 'hexagonal grid', 'flowing curves'>",
  "style": ["<2-4 from: geometric, organic, monoline, abstract, detailed, flat, gradient, textured, sharp, rounded, pixel, retro, modern, brutalist, elegant, playful>"],
  "technique": ["<1-3 from: grid construction, symmetry, asymmetry, optical illusion, line weight, overlap, repetition, tessellation>"],
  "mood": ["<3-6 visceral personality & emotional descriptors: e.g. fun, exciting, calm, chaotic, serene, energetic, sophisticated, mysterious, welcoming, aggressive, nostalgic, futuristic, clinical, warm>"],
  "industry": ["<1-3 from: tech, saas, fintech, crypto, web3, healthcare, ecommerce, education, real-estate, food, beverage, fashion, automotive, media, consulting, startup, enterprise, creative, nonprofit, gaming>"],
  "colors": ["<1-3 from: monochrome, duo-tone, multi-color, gradient, dark, light, vibrant, muted, warm, cool, neutral, neon, pastel, earth-tone, metallic>"],
  "quality": <int 1-10: 6=ok, 7=professional, 8=very good, 9=excellent, 10=iconic>
}

CRITICAL: For the "mood" field, do NOT just describe the visual appearance. You must describe the PERSONALITY and EMOTIONAL IMPACT of the pattern. How does it make someone feel? What kind of brand energy does it project? (e.g. "fun", "calm", "exciting", "anxious", "luxurious", "playful").
Quality: consider seamless tiling, visual rhythm, and professional execution.
"""


def _is_logos_type(ref_type: str) -> bool:
    """True if this ref_type belongs to logos (not patterns)."""
    return ref_type == "logos" or ref_type.startswith("logos/")


def _tag_image(client, image_path: Path, ref_type: str) -> Optional[dict]:
    """
    Send image to Gemini Vision for structured tagging.
    Tries model ladder; retries once on transient errors.
    Returns parsed dict or None.
    """
    try:
        from google.genai import types

        prompt  = LOGO_PROMPT if _is_logos_type(ref_type) else PATTERN_PROMPT

        img_bytes = image_path.read_bytes()
        ext  = image_path.suffix.lower().lstrip(".")
        mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext or 'png'}"

        contents = [
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=img_bytes, mime_type=mime),
        ]

        raw = None
        for model in VISION_MODELS:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=512,
                    ),
                )
                raw = response.text.strip()
                break
            except Exception as me:
                err = str(me).lower()
                if any(k in err for k in ("not found", "invalid", "not supported")):
                    continue
                if "quota" in err or "rate" in err or "429" in err:
                    raise   # surface immediately — caller handles quota
                if model != VISION_MODELS[-1]:
                    continue
                raise

        if not raw:
            return None

        # Strip markdown fences
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw[3:]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        import json_repair
        tags = json_repair.loads(raw)
        if hasattr(tags, "get") and isinstance(tags, dict):
            tags["quality"] = max(1, min(10, int(tags.get("quality", 5))))
            return tags
        else:
            print(f"    ⚠ Invalid JSON structure returned: {type(tags)}")
            return None
        return None
    except Exception as e:
        raise   # propagate quota/rate errors to caller


def build_index(
    ref_type: str,
    api_key: str,
    dry_run: bool = False,
    force: bool = False,
    delay: float = 4.0,
) -> dict:
    """
    Build/update index.json for one category folder.
    Paths stored as relative to REFERENCES_DIR for portability.
    """
    ref_dir    = REFERENCES_DIR / ref_type
    index_path = ref_dir / "index.json"

    if not ref_dir.exists():
        print(f"  ⚠ {ref_dir} not found — skipping")
        return {}

    # Load existing
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

    # Detect incorrectly-tagged logos (tagged with PATTERN_PROMPT = have 'motif' not 'form')
    bad_logo_keys = set()
    if _is_logos_type(ref_type) and not force:
        for fname, entry in existing.items():
            tags = entry.get("tags", {})
            if "motif" in tags and "form" not in tags:
                bad_logo_keys.add(fname)
        if bad_logo_keys:
            print(f"  ⚠ {len(bad_logo_keys)} entries have wrong prompt (motif≠form) — will re-tag")

    to_tag = [
        img for img in images
        if img.name not in existing
        or img.name in bad_logo_keys
        or force
    ]

    skip = len(images) - len(to_tag)
    is_logos = _is_logos_type(ref_type)
    print(f"\n{'='*60}")
    print(f"  {'LOGOS' if is_logos else 'PATTERNS'}: {ref_type}")
    print(f"  {len(images)} images | {skip} already tagged | {len(to_tag)} to process")
    if bad_logo_keys:
        print(f"  {len(bad_logo_keys)} to re-tag (wrong prompt)")
    print(f"{'='*60}")

    if not to_tag:
        print("  ✓ All images correctly tagged")
        return existing

    tagged = 0
    failed = 0
    quota_hit = False

    from google import genai
    client = genai.Client(api_key=api_key)

    for i, img_path in enumerate(to_tag, 1):
        print(f"  [{i}/{len(to_tag)}] {img_path.name}", end="  ", flush=True)

        if dry_run:
            print("(dry-run)")
            continue

        retries = 2
        tags = None
        for attempt in range(retries):
            try:
                tags = _tag_image(client, img_path, ref_type)
                break
            except Exception as e:
                err = str(e).lower()
                if "quota" in err or "429" in err or "rate" in err:
                    print(f"\n  ⏸ Quota/rate limit hit — saving progress and stopping")
                    quota_hit = True
                    break
                if attempt < retries - 1:
                    time.sleep(8)
                else:
                    print(f"failed ({e})")
                    failed += 1
            if quota_hit:
                break

        if quota_hit:
            break

        if tags:
            # Store relative path for portability
            rel_path = str(img_path.relative_to(PROJECT_ROOT))
            existing[img_path.name] = {
                "relative_path": rel_path,
                "tags": tags,
            }
            form_key = "form" if _is_logos_type(ref_type) else "motif"
            form_val = tags.get(form_key, "?")
            styles   = ", ".join(tags.get("style", [])[:3])
            q        = tags.get("quality", "?")
            print(f"q={q}  {form_key}={form_val}  [{styles}]")
            tagged += 1
        else:
            print("failed (no data)")
            failed += 1

        if i < len(to_tag) and not quota_hit:
            time.sleep(delay)

    # Save progress (even if partial)
    if not dry_run and tagged > 0:
        index_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
        print(f"\n  → Saved {index_path.name}  ({len(existing)}/{len(images)} indexed)")

    print(f"  Summary: {tagged} tagged | {failed} failed | {skip} skipped", end="")
    if quota_hit:
        print(" | ⏸ STOPPED (quota)")
    else:
        print(" | ✓ complete")

    return existing, quota_hit


def print_stats(index: dict, ref_type: str) -> None:
    if not index:
        return
    from collections import Counter

    print(f"\n{'─'*60}")
    print(f"  {ref_type} ({len(index)} images)")
    print(f"{'─'*60}")

    is_logos = _is_logos_type(ref_type)
    counters: Dict[str, Counter] = {}
    quality_scores: list = []

    for entry in index.values():
        tags = entry.get("tags", {})
        quality_scores.append(tags.get("quality", 0))
        form_key = "form" if is_logos else "motif"
        counters.setdefault(form_key, Counter())[tags.get(form_key, "?")] += 1
        for field in ("style", "mood", "industry", "colors"):
            counters.setdefault(field, Counter())
            for v in tags.get(field, []):
                counters[field][v] += 1

    if quality_scores:
        avg = sum(quality_scores) / len(quality_scores)
        below7 = sum(1 for q in quality_scores if q < 7)
        print(f"\n  quality: avg={avg:.1f}  min={min(quality_scores)}  max={max(quality_scores)}", end="")
        if below7:
            print(f"  ⚠ {below7} below 7")
        else:
            print()

    for field, counter in counters.items():
        top = counter.most_common(6)
        vals = "  ".join(f"{v}({c})" for v, c in top)
        print(f"  {field}: {vals}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-label reference images using Gemini Vision")
    parser.add_argument("--type", help="Category path, e.g. logos/style_minimal_geometric")
    parser.add_argument("--dry-run", action="store_true", help="Preview without calling API")
    parser.add_argument("--force",   action="store_true", help="Re-tag all images")
    parser.add_argument("--stats-only", action="store_true", help="Print stats from existing index")
    parser.add_argument("--delay", type=float, default=4.0, help="Seconds between API calls (default: 4)")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and not args.dry_run and not args.stats_only:
        print("Error: GEMINI_API_KEY not set")
        sys.exit(1)

    # Discover categories
    if args.type:
        types_to_process = [args.type]
    else:
        types_to_process = []
        for top in ["logos", "patterns"]:
            top_dir = REFERENCES_DIR / top
            if not top_dir.exists():
                continue
            has_images = any(
                p.suffix.lower() in IMAGE_EXTS
                for p in top_dir.iterdir()
                if p.is_file() and not p.name.startswith(".")
            )
            if has_images:
                types_to_process.append(top)
            for sub in sorted(top_dir.iterdir()):
                if sub.is_dir() and not sub.name.startswith("."):
                    if any(f.suffix.lower() in IMAGE_EXTS for f in sub.iterdir()):
                        types_to_process.append(f"{top}/{sub.name}")

    total_categories = len(types_to_process)
    print(f"\n📂 Found {total_categories} categories to process")

    for idx, ref_type in enumerate(types_to_process, 1):
        ref_dir = REFERENCES_DIR / ref_type
        if not ref_dir.exists():
            print(f"  ⚠ {ref_dir} not found — skipping")
            continue

        print(f"\n[{idx}/{total_categories}]", end=" ")

        if args.stats_only:
            index_path = ref_dir / "index.json"
            if index_path.exists():
                index = json.loads(index_path.read_text())
                print_stats(index, ref_type)
            else:
                print(f"  ⚠ No index.json in {ref_dir}")
            continue

        result = build_index(
            ref_type, api_key or "",
            dry_run=args.dry_run,
            force=args.force,
            delay=args.delay,
        )
        # build_index returns (dict, quota_hit) or just dict in older call
        index = result[0] if isinstance(result, tuple) else result
        quota_hit = result[1] if isinstance(result, tuple) else False

        if not args.dry_run:
            print_stats(index, ref_type)

        if quota_hit:
            remaining = types_to_process[idx:]
            if remaining:
                print(f"\n  ⏸ Remaining categories (run again to continue):")
                for r in remaining:
                    print(f"    - {r}")
            print("\n  Tip: wait a minute and re-run — already-tagged images are skipped")
            sys.exit(1)

    print("\n✓ Done\n")


if __name__ == "__main__":
    main()
