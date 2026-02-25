#!/usr/bin/env python3
"""
crawl_pinterest.py — Crawl Pinterest for brand design references, then auto-tag.

Full pipeline:
  1. Crawl Pinterest search/board URLs → download images
  2. Quality filter (size, aspect ratio)
  3. Auto-tag with Gemini Vision → update index.json

Prerequisites:
  pip install selenium requests beautifulsoup4 pyyaml
  Chrome browser installed
  ChromeDriver matching your Chrome version

Usage:
  # Crawl logos from curated search queries (preset)
  python scripts/crawl_pinterest.py --preset logos

  # Crawl patterns
  python scripts/crawl_pinterest.py --preset patterns

  # Custom search query → download to logos folder
  python scripts/crawl_pinterest.py --query "minimal geometric logo design" --type logos --pages 5

  # Custom Pinterest board URL
  python scripts/crawl_pinterest.py --url "https://www.pinterest.com/user/board-name/" --type logos --pages 10

  # Crawl only (skip auto-tagging)
  python scripts/crawl_pinterest.py --preset logos --skip-tag

  # Tag only (no crawling, just tag new un-indexed images)
  python scripts/crawl_pinterest.py --tag-only --type logos
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

# ── Resolve paths ────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
REFERENCES_DIR = PROJECT_ROOT / "references"
CRAWLER_DIR = PROJECT_ROOT / "tools" / "Pinterest-infinite-crawler"

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

# Minimum image size to keep (bytes) — filters out thumbnails and icons
MIN_FILE_SIZE = 5_000        # 5 KB
MIN_DIMENSION = 200          # px (either width or height)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


# ── Curated search queries ───────────────────────────────────────────────────
# These are design-focused queries that produce high-quality reference images

PRESET_QUERIES: Dict[str, List[dict]] = {

    # ── DESIGN STYLES ──────────────────────────────────────────────────────────

    "style_minimal_geometric": [
        {"query": "minimal geometric logo design vector 2024",         "pages": 3},
        {"query": "clean abstract symbol logo mark negative space",    "pages": 3},
        {"query": "flat geometric brand identity logo professional",   "pages": 2},
    ],
    "style_corporate_enterprise": [
        {"query": "corporate logo design professional enterprise",      "pages": 3},
        {"query": "B2B brand identity logo minimalist serious",         "pages": 3},
        {"query": "consulting firm logo design modern",                 "pages": 2},
    ],
    "style_luxury_premium": [
        {"query": "luxury brand logo design premium elegant",           "pages": 3},
        {"query": "high-end fashion logo mark serif gold",              "pages": 3},
        {"query": "exclusive brand identity logo sophisticated",        "pages": 2},
    ],
    "style_tech_futuristic": [
        {"query": "tech logo design futuristic modern AI",              "pages": 3},
        {"query": "futuristic brand identity logo abstract symbol",     "pages": 3},
        {"query": "startup tech logo geometric digital innovation",     "pages": 2},
    ],
    "style_organic_natural": [
        {"query": "organic logo design natural botanical",              "pages": 3},
        {"query": "eco brand identity logo hand-drawn nature",          "pages": 3},
        {"query": "sustainable brand logo leaf plant natural",          "pages": 2},
    ],
    "style_playful_mascot": [
        {"query": "playful mascot logo character design brand",         "pages": 3},
        {"query": "fun friendly mascot logo illustration",              "pages": 3},
        {"query": "character logo design cute bold colorful",           "pages": 2},
    ],
    "style_retro_vintage": [
        {"query": "retro vintage logo design badge emblem",             "pages": 3},
        {"query": "vintage brand identity logo classic typography",     "pages": 3},
        {"query": "retro logo stamp distressed 70s 80s style",         "pages": 2},
    ],
    "style_bold_brutalist": [
        {"query": "bold brutalist logo design heavy type",              "pages": 3},
        {"query": "strong graphic logo design bold geometric",          "pages": 3},
        {"query": "impact wordmark logo heavy contrast brand identity", "pages": 2},
    ],
    "style_elegant_editorial": [
        {"query": "elegant editorial logo design fashion typography",   "pages": 3},
        {"query": "serif wordmark logo design luxury fashion house",    "pages": 3},
        {"query": "typographic logo design editorial high fashion",     "pages": 2},
    ],

    # ── INDUSTRIES ─────────────────────────────────────────────────────────────

    "industry_technology_saas": [
        {"query": "technology SaaS logo design startup AI brand",       "pages": 3},
        {"query": "software tech company logo modern abstract",         "pages": 3},
        {"query": "AI startup brand identity logo minimal",             "pages": 2},
    ],
    "industry_finance_crypto": [
        {"query": "fintech logo design finance banking brand",          "pages": 3},
        {"query": "crypto blockchain logo design web3 brand identity",  "pages": 3},
        {"query": "investment fund logo premium financial brand",       "pages": 2},
    ],
    "industry_fashion_beauty": [
        {"query": "fashion brand logo design luxury beauty",           "pages": 3},
        {"query": "beauty cosmetics logo minimal elegant brand",        "pages": 3},
        {"query": "lifestyle brand identity logo script serif",         "pages": 2},
    ],
    "industry_food_beverage": [
        {"query": "food beverage brand logo design restaurant",         "pages": 3},
        {"query": "coffee shop cafe logo design minimal",               "pages": 3},
        {"query": "hospitality hotel restaurant brand identity logo",   "pages": 2},
    ],
    "industry_media_gaming": [
        {"query": "media entertainment logo design bold dynamic",       "pages": 3},
        {"query": "gaming esports logo design bold modern",             "pages": 3},
        {"query": "podcast streaming media brand identity logo",        "pages": 2},
    ],
    "industry_real_estate": [
        {"query": "real estate logo design architecture brand",         "pages": 3},
        {"query": "property development brand identity logo minimal",   "pages": 3},
        {"query": "architecture firm logo geometric abstract",          "pages": 2},
    ],
    "industry_healthcare_wellness": [
        {"query": "healthcare wellness logo design medical brand",      "pages": 3},
        {"query": "health wellness app logo minimal clean",             "pages": 3},
        {"query": "mental health wellness brand identity logo",         "pages": 2},
    ],
    "industry_education_edtech": [
        {"query": "education brand logo design edtech learning",        "pages": 3},
        {"query": "online learning platform logo modern minimal",       "pages": 3},
        {"query": "educational institution logo design clean",          "pages": 2},
    ],
    "industry_retail_ecommerce": [
        {"query": "retail ecommerce logo design brand identity",        "pages": 3},
        {"query": "online store shopping brand logo minimal bold",      "pages": 3},
        {"query": "D2C brand identity logo modern consumer",            "pages": 2},
    ],
}



# ── Crawler integration ──────────────────────────────────────────────────────

def _ensure_crawler() -> Path:
    """Clone Pinterest crawler if not present, return its directory."""
    if CRAWLER_DIR.exists() and (CRAWLER_DIR / "main.py").exists():
        return CRAWLER_DIR

    print(f"  Cloning Pinterest-infinite-crawler → {CRAWLER_DIR}")
    CRAWLER_DIR.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone",
         "https://github.com/mirusu400/Pinterest-infinite-crawler.git",
         str(CRAWLER_DIR)],
        check=True,
        capture_output=True,
    )

    # Install its dependencies
    req_file = CRAWLER_DIR / "requirements.txt"
    if req_file.exists():
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
            check=True,
            capture_output=True,
        )

    return CRAWLER_DIR


def _build_pinterest_url(query: str) -> str:
    """Convert a search query to a Pinterest search URL."""
    from urllib.parse import quote_plus
    return f"https://www.pinterest.com/search/pins/?q={quote_plus(query)}"


def crawl_pinterest(
    url: str,
    download_dir: Path,
    pages: int = 5,
    email: Optional[str] = None,
    password: Optional[str] = None,
) -> int:
    """
    Run the Pinterest crawler for a single URL.
    Returns number of images downloaded.
    """
    crawler_dir = _ensure_crawler()
    download_dir.mkdir(parents=True, exist_ok=True)

    before = set(download_dir.iterdir())

    cmd = [
        sys.executable,
        str(crawler_dir / "main.py"),
        "-l", url,
        "-d", str(download_dir),
        "-g", str(pages),
    ]

    if email:
        cmd.extend(["-e", email])
    if password:
        cmd.extend(["-p", password])

    try:
        result = subprocess.run(
            cmd,
            cwd=str(crawler_dir),
            capture_output=True,
            text=True,
            timeout=300,  # 5 min safety timeout
        )
        if result.returncode != 0:
            print(f"    ⚠ Crawler exited with code {result.returncode}")
            if result.stderr:
                print(f"    stderr: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print(f"    ⚠ Crawler timed out after 5 minutes")
    except Exception as e:
        print(f"    ⚠ Crawler error: {e}")

    after = set(download_dir.iterdir())
    new_files = after - before
    return len(new_files)


# ── Quality filter ────────────────────────────────────────────────────────────

def filter_and_move(
    download_dir: Path,
    target_dir: Path,
) -> dict:
    """
    Filter downloaded images by quality, rename with content hash, move to target.

    Returns {"kept": int, "rejected": int, "duplicates": int}
    """
    try:
        from PIL import Image
    except ImportError:
        print("  ⚠ Pillow not installed — skipping quality filter, moving all files")
        # Just move everything
        count = 0
        for f in download_dir.iterdir():
            if f.suffix.lower() in IMAGE_EXTS:
                shutil.move(str(f), str(target_dir / f.name))
                count += 1
        return {"kept": count, "rejected": 0, "duplicates": 0}

    target_dir.mkdir(parents=True, exist_ok=True)

    # Build set of existing hashes to detect duplicates
    existing_hashes = set()
    for f in target_dir.iterdir():
        if f.suffix.lower() in IMAGE_EXTS:
            # Use first 16 chars of filename as hash (our naming convention)
            existing_hashes.add(f.stem[:16])

    kept = rejected = duplicates = 0

    for f in sorted(download_dir.iterdir()):
        if f.suffix.lower() not in IMAGE_EXTS:
            continue

        # Size check
        if f.stat().st_size < MIN_FILE_SIZE:
            f.unlink()
            rejected += 1
            continue

        # Dimension check
        try:
            img = Image.open(f)
            w, h = img.size
            if w < MIN_DIMENSION or h < MIN_DIMENSION:
                f.unlink()
                rejected += 1
                continue
        except Exception:
            f.unlink()
            rejected += 1
            continue

        # Content hash for dedup + clean filename
        content_hash = hashlib.md5(f.read_bytes()).hexdigest()
        if content_hash[:16] in existing_hashes:
            f.unlink()
            duplicates += 1
            continue

        # Move with hash-based name
        ext = f.suffix.lower()
        new_name = f"{content_hash}{ext}"
        target_path = target_dir / new_name

        if target_path.exists():
            f.unlink()
            duplicates += 1
            continue

        shutil.move(str(f), str(target_path))
        existing_hashes.add(content_hash[:16])
        kept += 1

    return {"kept": kept, "rejected": rejected, "duplicates": duplicates}


# ── Auto-tag integration ─────────────────────────────────────────────────────

def run_auto_tag(ref_type: str) -> None:
    """Run build_reference_index.py for a specific type."""
    script = SCRIPT_DIR / "build_reference_index.py"
    if not script.exists():
        print(f"  ⚠ {script} not found — skipping auto-tag")
        return

    print(f"\n  Running auto-tag for {ref_type}...")
    subprocess.run(
        [sys.executable, str(script), "--type", ref_type],
        cwd=str(PROJECT_ROOT),
    )


# ── Main pipeline ────────────────────────────────────────────────────────────

def run_pipeline(
    queries: List[dict],
    ref_type: str,
    email: Optional[str] = None,
    password: Optional[str] = None,
    skip_tag: bool = False,
) -> None:
    """Full pipeline: crawl → filter → tag."""
    target_dir = REFERENCES_DIR / ref_type
    target_dir.mkdir(parents=True, exist_ok=True)

    total_kept = total_rejected = total_dupes = 0

    for i, q in enumerate(queries, 1):
        query = q.get("query", "")
        url = q.get("url", "")
        pages = q.get("pages", 5)

        if not url and query:
            url = _build_pinterest_url(query)

        label = query or url
        print(f"\n{'='*60}")
        print(f"  [{i}/{len(queries)}] {label}")
        print(f"  URL: {url}")
        print(f"  Pages: {pages}")
        print(f"{'='*60}")

        # Download to temp dir
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "download"
            tmp_path.mkdir()

            count = crawl_pinterest(url, tmp_path, pages, email, password)
            print(f"  Downloaded: {count} images")

            # Filter and move to target
            stats = filter_and_move(tmp_path, target_dir)
            total_kept += stats["kept"]
            total_rejected += stats["rejected"]
            total_dupes += stats["duplicates"]

            print(f"  Kept: {stats['kept']}  Rejected: {stats['rejected']}  "
                  f"Duplicates: {stats['duplicates']}")

    print(f"\n{'─'*60}")
    print(f"  TOTAL: {total_kept} new images added to {target_dir}")
    print(f"  Filtered: {total_rejected} rejected, {total_dupes} duplicates")
    print(f"{'─'*60}")

    # Now count total in folder
    total_in_folder = sum(
        1 for f in target_dir.iterdir()
        if f.suffix.lower() in IMAGE_EXTS and not f.name.startswith(".")
    )
    print(f"  Total in {ref_type}/: {total_in_folder} images")

    # Auto-tag new images
    if not skip_tag and total_kept > 0:
        run_auto_tag(ref_type)


# ── CLI ───────────────────────────────────────────────────────────────────────

ALL_CATEGORIES = list(PRESET_QUERIES.keys())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl Pinterest for brand references, then auto-tag with Gemini Vision"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--preset", choices=ALL_CATEGORIES,
        metavar="CATEGORY",
        help=(
            "Category to crawl. Styles: style_minimal_geometric, style_corporate_enterprise, "
            "style_luxury_premium, style_tech_futuristic, style_organic_natural, "
            "style_playful_mascot, style_retro_vintage, style_bold_brutalist, style_elegant_editorial. "
            "Industries: industry_technology_saas, industry_finance_crypto, industry_fashion_beauty, "
            "industry_food_beverage, industry_media_gaming, industry_real_estate, "
            "industry_healthcare_wellness, industry_education_edtech, industry_retail_ecommerce"
        ),
    )
    group.add_argument(
        "--all", action="store_true",
        help="Crawl ALL 18 categories (runs sequentially, takes ~30-60 min)",
    )
    group.add_argument(
        "--query", type=str,
        help="Custom Pinterest search query",
    )
    group.add_argument(
        "--url", type=str,
        help="Direct Pinterest URL (board, pin, search page)",
    )
    group.add_argument(
        "--tag-only", action="store_true",
        help="Skip crawling, just auto-tag new images in the folder",
    )

    parser.add_argument(
        "--type", choices=["logos", "patterns"], default="logos",
        help="Reference type for custom query (default: logos)",
    )
    parser.add_argument(
        "--pages", type=int, default=3,
        help="Number of scroll pages for custom query (default: 3)",
    )
    parser.add_argument(
        "--email", type=str, default=os.environ.get("PINTEREST_EMAIL"),
        help="Pinterest email (or set PINTEREST_EMAIL in .env)",
    )
    parser.add_argument(
        "--password", type=str, default=os.environ.get("PINTEREST_PASSWORD"),
        help="Pinterest password (or set PINTEREST_PASSWORD in .env)",
    )
    parser.add_argument(
        "--skip-tag", action="store_true",
        help="Skip auto-tagging after download",
    )
    args = parser.parse_args()

    if not args.email or not args.password:
        print("\n  ⚠ Pinterest credentials not set — set PINTEREST_EMAIL / PINTEREST_PASSWORD in .env")

    # Tag-only mode
    if args.tag_only:
        run_auto_tag(args.type)
        return

    # Determine which categories to run
    if getattr(args, "all", False):
        categories = ALL_CATEGORIES
    elif args.preset:
        categories = [args.preset]
    elif args.query or args.url:
        # Custom one-off crawl to a user-specified subfolder
        queries = [{"query": args.query, "pages": args.pages}] if args.query else \
                  [{"url": args.url, "pages": args.pages}]
        run_pipeline(
            queries=queries,
            ref_type=args.type,
            email=args.email,
            password=args.password,
            skip_tag=args.skip_tag,
        )
        return
    else:
        parser.print_help()
        return

    total = len(categories)
    for i, cat in enumerate(categories, 1):
        queries = PRESET_QUERIES[cat]
        # Each category gets its own subfolder under references/logos/
        ref_type = f"logos/{cat}"

        print(f"\n{'#'*60}")
        print(f"  [{i}/{total}] Category: {cat}")
        print(f"  Target:   references/{ref_type}/")
        print(f"  Queries:  {len(queries)}")
        print(f"{'#'*60}")

        run_pipeline(
            queries=queries,
            ref_type=ref_type,
            email=args.email,
            password=args.password,
            skip_tag=args.skip_tag,
        )

    print(f"\n✓ Crawled {total} categories → references/logos/{{category}}/")
    print("  Review images, delete bad ones, then run:")
    print("  python scripts/build_reference_library.py --skip-crawl --type logos")


if __name__ == "__main__":
    main()
