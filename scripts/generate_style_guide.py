#!/usr/bin/env python3
"""
generate_style_guide.py — Auto-generate style.md from tagged reference images.

Reads index.json, analyzes dominant patterns in the collection,
picks top-quality images as visual anchors, and asks Gemini to write
a structured style guide that can be fed back to the image generation pipeline.

Usage:
  python scripts/generate_style_guide.py                           # all types
  python scripts/generate_style_guide.py --type logos              # logos only
  python scripts/generate_style_guide.py --type patterns           # patterns only
  python scripts/generate_style_guide.py --output styles/my.md     # custom output
  python scripts/generate_style_guide.py --top 5                   # use top 5 refs
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
REFERENCES_DIR = PROJECT_ROOT / "references"
DEFAULT_OUTPUT = PROJECT_ROOT / "styles"

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


# ── Index analysis ────────────────────────────────────────────────────────────

def _is_logos_type(ref_type: str) -> bool:
    return ref_type == "logos" or ref_type.startswith("logos/")


def load_index(ref_type: str) -> dict:
    """Load index.json for a reference type."""
    path = REFERENCES_DIR / ref_type / "index.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def analyze_index(index: dict, ref_type: str) -> dict:
    """
    Analyze tag distribution and find dominant visual characteristics.
    Returns a structured analysis dict.
    """
    if not index:
        return {}

    counters: Dict[str, Counter] = {}
    quality_scores: List[int] = []
    top_images: List[dict] = []

    for filename, entry in index.items():
        tags = entry.get("tags", {})
        q = tags.get("quality", 5)
        quality_scores.append(q)

        # Resolve path: support both old absolute local_path and new relative_path
        rel = entry.get("relative_path", "")
        abs_path = entry.get("local_path", "")
        resolved = ""
        if rel:
            resolved = str(PROJECT_ROOT / rel)
        elif abs_path:
            resolved = abs_path

        # Collect for top images
        top_images.append({
            "filename": filename,
            "local_path": resolved,
            "quality": q,
            "tags": tags,
        })

        # Count tag values
        form_key = "form" if _is_logos_type(ref_type) else "motif"
        form_val = tags.get(form_key, "unknown")
        counters.setdefault(form_key, Counter())[form_val] += 1

        for field in ("style", "technique", "mood", "industry", "colors"):
            counters.setdefault(field, Counter())
            for v in tags.get(field, []):
                counters[field][v] += 1

    # Sort by quality
    top_images.sort(key=lambda x: x["quality"], reverse=True)

    # Dominant values (top 5 per field)
    dominant = {}
    for field, counter in counters.items():
        total = sum(counter.values())
        dominant[field] = [
            {"value": v, "count": c, "pct": round(c / total * 100)}
            for v, c in counter.most_common(5)
        ]

    return {
        "total": len(index),
        "quality_avg": round(sum(quality_scores) / len(quality_scores), 1),
        "quality_min": min(quality_scores),
        "quality_max": max(quality_scores),
        "dominant": dominant,
        "top_images": top_images,
    }


def get_top_images(analysis: dict, n: int = 5) -> List[dict]:
    """Get top N highest quality images from analysis."""
    return analysis.get("top_images", [])[:n]


# ── Style guide generation ───────────────────────────────────────────────────

STYLE_GUIDE_PROMPT = """\
You are a senior brand identity designer writing an internal style guide.

I'm giving you:
1. Statistical analysis of our reference image collection
2. The top {n} highest-quality reference images from our collection

Your task: Write a comprehensive `style.md` file that captures the dominant visual language of this collection. This file will be fed to an AI image generator (Gemini) to ensure all generated images match this style.

## Collection Analysis:
{analysis_text}

## Rules for writing the style guide:
- Write in ENGLISH
- Be extremely specific and technical — use exact design vocabulary
- Every rule must be actionable by an AI image generator
- Include negative rules (what to AVOID) for each section
- Use concrete measurements where possible (stroke weight, spacing, ratios)
- Reference specific techniques (negative space, grid construction, etc.)
- Include color descriptors (not hex codes — the guide should be palette-agnostic)
- The guide should work across ANY brand, not be specific to one brand

## Required sections:

### For LOGOS:
1. **Form Language** — dominant shapes, geometry rules, construction principles
2. **Style Constraints** — rendering style, fill vs outline, complexity level
3. **Technical Specs** — stroke weights, proportions, spacing, scalability
4. **Composition** — centering, padding, figure-ground ratio
5. **Avoid** — explicit list of visual anti-patterns

### For PATTERNS:
1. **Motif Rules** — dominant motif types, geometric principles
2. **Emotional & Personality Impact** — how the pattern feels (e.g. fun, clinical, calming), its psychological brand energy, and the vibe it creates
3. **Grid System** — tiling method, spacing, density
4. **Style Constraints** — rendering, color usage, complexity
5. **Tiling Technical** — edge alignment, seamless requirements
6. **Avoid** — visual anti-patterns

Write ONLY the markdown content. No explanations, no preamble.
Start with a YAML frontmatter block containing: name, type, version, generated_from.
"""


def format_analysis_for_prompt(analysis: dict, ref_type: str) -> str:
    """Format analysis dict into human-readable text for the prompt."""
    lines = []
    lines.append(f"Type: {ref_type}")
    lines.append(f"Total images: {analysis['total']}")
    lines.append(f"Quality: avg={analysis['quality_avg']}, "
                 f"min={analysis['quality_min']}, max={analysis['quality_max']}")
    lines.append("")

    for field, items in analysis.get("dominant", {}).items():
        vals = ", ".join(f"{d['value']}({d['pct']}%)" for d in items)
        lines.append(f"{field}: {vals}")

    return "\n".join(lines)


def generate_style_guide(
    ref_type: str,
    api_key: str,
    top_n: int = 5,
) -> Optional[str]:
    """
    Generate style.md content using Gemini Vision.

    Sends analysis + top N reference images → Gemini writes the guide.
    """
    index = load_index(ref_type)
    if not index:
        print(f"  ⚠ No index.json found for {ref_type}")
        return None

    analysis = analyze_index(index, ref_type)
    if not analysis:
        print(f"  ⚠ Empty analysis for {ref_type}")
        return None

    top_images = get_top_images(analysis, top_n)
    analysis_text = format_analysis_for_prompt(analysis, ref_type)

    print(f"\n  Collection: {analysis['total']} images, quality avg={analysis['quality_avg']}")
    print(f"  Using top {len(top_images)} as visual anchors")

    # Build dominant summary for user
    for field, items in analysis.get("dominant", {}).items():
        vals = ", ".join(f"{d['value']}({d['pct']}%)" for d in items[:3])
        print(f"  {field}: {vals}")

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        prompt = STYLE_GUIDE_PROMPT.format(
            n=len(top_images),
            analysis_text=analysis_text,
        )

        # Build parts: prompt + reference images
        parts = [types.Part.from_text(text=prompt)]

        loaded = 0
        for img_info in top_images:
            # Try multiple paths: stored path, then filename in refs dir
            img_path = Path(img_info["local_path"])
            if not img_path.exists():
                img_path = REFERENCES_DIR / ref_type / img_info["filename"]
            if not img_path.exists():
                # Try scanning all subdirs of references/ref_type/
                ref_base = REFERENCES_DIR / ref_type
                found = list(ref_base.rglob(img_info["filename"]))
                if found:
                    img_path = found[0]
                else:
                    continue

            img_bytes = img_path.read_bytes()
            ext = img_path.suffix.lower().lstrip(".")
            mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext or 'png'}"

            # Add label
            tags = img_info.get("tags", {})
            label = (
                f"Reference #{loaded+1} (quality={tags.get('quality', '?')}, "
                f"form={tags.get('form', tags.get('motif', '?'))}, "
                f"style={tags.get('style', [])})"
            )
            parts.append(types.Part.from_text(text=label))
            parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
            loaded += 1

        if loaded == 0:
            print("  ⚠ No reference images could be loaded")
            return None

        print(f"  Sending {loaded} images + analysis to Gemini...")

        # Model ladder for vision+text generation
        _models = ["gemini-2.5-flash", "gemini-1.5-flash"]
        response = None
        for _m in _models:
            try:
                response = client.models.generate_content(model=_m, contents=parts)
                break
            except Exception as _me:
                if any(k in str(_me).lower() for k in ("not found", "invalid", "not supported")):
                    continue
                raise

        if response is None:
            print("  ⚠ All models failed")
            return None

        result = response.text.strip()

        # Clean markdown fences if present
        if result.startswith("```"):
            lines = result.split("\n")
            result = "\n".join(lines[1:])  # skip first ```markdown
            if result.endswith("```"):
                result = result[:-3].rstrip()

        return result

    except Exception as e:
        print(f"  ⚠ Gemini error: {e}")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-generate style.md from tagged reference images"
    )
    parser.add_argument(
        "--type", type=str,
        help="Reference type or category path, e.g. logos, patterns, logos/style_minimal_geometric",
    )
    parser.add_argument(
        "--output", type=str,
        help="Custom output directory (default: styles/)",
    )
    parser.add_argument(
        "--top", type=int, default=5,
        help="Number of top-quality images to use as visual anchors (default: 5)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set")
        sys.exit(1)

    output_dir = Path(args.output) if args.output else DEFAULT_OUTPUT
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.type:
        types_to_process = [args.type]
    else:
        # Auto-discover: logos, patterns, and all category subdirs
        types_to_process = []
        for top in ["logos", "patterns"]:
            top_dir = REFERENCES_DIR / top
            if not top_dir.exists():
                continue
            has_images = any(
                p.suffix.lower() in {'.png','.jpg','.jpeg','.webp'}
                for p in top_dir.iterdir()
                if not p.name.startswith(".")
            )
            if has_images:
                types_to_process.append(top)
            for sub in sorted(top_dir.iterdir()):
                if sub.is_dir() and not sub.name.startswith(".") and \
                   any(f.suffix.lower() in {'.png','.jpg','.jpeg','.webp'} for f in sub.iterdir()):
                    types_to_process.append(f"{top}/{sub.name}")

    for ref_type in types_to_process:
        print(f"\n{'='*60}")
        print(f"  Generating style guide for: {ref_type}")
        print(f"{'='*60}")

        content = generate_style_guide(ref_type, api_key, top_n=args.top)

        if content:
            # Mirror refs folder structure:
            #   logos/style_minimal_geometric → styles/logos/style_minimal_geometric.md
            #   logos                         → styles/logos.md
            if "/" in ref_type:
                top, leaf = ref_type.split("/", 1)
                cat_out_dir = (output_dir if args.output else DEFAULT_OUTPUT) / top
            else:
                cat_out_dir = output_dir if args.output else DEFAULT_OUTPUT
                leaf = ref_type
            cat_out_dir.mkdir(parents=True, exist_ok=True)
            out_path = cat_out_dir / f"{leaf}.md"
            out_path.write_text(content, encoding="utf-8")
            print(f"\n  ✓ Saved → {out_path}")
            print(f"  Length: {len(content)} chars, {content.count(chr(10))} lines")
        else:
            print(f"\n  ✗ Failed to generate style guide for {ref_type}")

    print("\n✓ Done\n")


if __name__ == "__main__":
    main()
