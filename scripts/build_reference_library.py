#!/usr/bin/env python3
"""
build_reference_library.py — Master pipeline: Crawl → Tag → Style Guide.

Chains all 3 steps of the reference data pipeline:
  1. Crawl Pinterest for design references (optional, skip with --skip-crawl)
  2. Auto-tag all images with Gemini Vision
  3. Generate style.md from tagged collection

Usage:
  # Full pipeline (crawl + tag + style guide)
  python scripts/build_reference_library.py --preset logos

  # Skip crawl (just re-tag + regenerate style guide)
  python scripts/build_reference_library.py --skip-crawl --type logos

  # Tag + style only (most common after manually adding images)
  python scripts/build_reference_library.py --skip-crawl --type logos --type patterns
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


def run_step(label: str, cmd: list, mandatory: bool = True) -> bool:
    """Run a pipeline step, return True if successful."""
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  STEP: {label}")
    print(f"{sep}\n")

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        if mandatory:
            print(f"\n  ✗ {label} failed (exit {result.returncode})")
            return False
        else:
            print(f"\n  ⚠ {label} had issues but continuing...")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Master pipeline: Crawl → Tag → Style Guide"
    )
    parser.add_argument(
        "--preset", choices=["logos", "patterns"],
        help="Pinterest crawl preset (step 1)",
    )
    parser.add_argument(
        "--type", choices=["logos", "patterns"], action="append",
        help="Reference types to process (repeatable, default: logos)",
    )
    parser.add_argument(
        "--skip-crawl", action="store_true",
        help="Skip Pinterest crawl (use for manually added images)",
    )
    parser.add_argument(
        "--force-retag", action="store_true",
        help="Force re-tag all images (ignore existing tags)",
    )
    parser.add_argument(
        "--top", type=int, default=5,
        help="Top N images for style guide generation (default: 5)",
    )
    args = parser.parse_args()

    types = args.type or (["logos"] if not args.preset else [args.preset])
    py = sys.executable

    # ── Step 1: Crawl ─────────────────────────────────────────────────────
    if not args.skip_crawl:
        preset = args.preset or types[0]
        ok = run_step(
            f"① Crawl Pinterest ({preset})",
            [py, str(SCRIPT_DIR / "crawl_pinterest.py"),
             "--preset", preset, "--skip-tag"],
            mandatory=False,  # crawl failure shouldn't stop pipeline
        )
    else:
        print("\n  ⏭ Skipping Pinterest crawl (--skip-crawl)")

    # ── Step 2: Tag ───────────────────────────────────────────────────────
    for ref_type in types:
        tag_cmd = [py, str(SCRIPT_DIR / "build_reference_index.py"),
                   "--type", ref_type]
        if args.force_retag:
            tag_cmd.append("--force")

        ok = run_step(
            f"② Auto-tag {ref_type}",
            tag_cmd,
            mandatory=True,
        )
        if not ok:
            print(f"  Stopping: tagging failed for {ref_type}")
            sys.exit(1)

    # ── Step 3: Style Guide ───────────────────────────────────────────────
    for ref_type in types:
        ok = run_step(
            f"③ Generate style guide ({ref_type})",
            [py, str(SCRIPT_DIR / "generate_style_guide.py"),
             "--type", ref_type, "--top", str(args.top)],
            mandatory=True,
        )

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  PIPELINE COMPLETE")
    print(f"{'─'*60}")

    styles_dir = PROJECT_ROOT / "styles"
    for ref_type in types:
        index_path = PROJECT_ROOT / "references" / ref_type / "index.json"
        style_path = styles_dir / f"{ref_type}_style.md"
        idx_count = "✓" if index_path.exists() else "✗"
        sty_count = "✓" if style_path.exists() else "✗"
        print(f"  {ref_type}: index.json {idx_count}  style.md {sty_count}")

    print(f"\n  Output: {styles_dir}/")
    print(f"  Next: review and refine the generated style.md files")
    print()


if __name__ == "__main__":
    main()
