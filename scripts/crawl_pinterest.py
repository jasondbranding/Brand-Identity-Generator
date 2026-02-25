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
    "logos": [
        # By style
        {"query": "minimal geometric logo design",          "pages": 5},
        {"query": "abstract symbol logo mark",              "pages": 5},
        {"query": "monoline logo design branding",          "pages": 3},
        {"query": "negative space logo clever",             "pages": 3},
        {"query": "lettermark monogram logo",               "pages": 3},
        {"query": "flat vector logo icon modern",           "pages": 3},
        # By industry
        {"query": "fintech crypto logo design",             "pages": 3},
        {"query": "saas tech startup logo branding",        "pages": 3},
        {"query": "luxury premium brand identity logo",     "pages": 3},
        {"query": "healthcare medical logo minimal",        "pages": 2},
        {"query": "food beverage brand logo design",        "pages": 2},
        {"query": "fashion brand identity logo",            "pages": 2},
        # By mood
        {"query": "bold confident logo design",             "pages": 2},
        {"query": "elegant sophisticated logo mark",        "pages": 2},
        {"query": "playful friendly logo design",           "pages": 2},
    ],
    "patterns": [
        # By motif
        {"query": "geometric seamless pattern design",      "pages": 5},
        {"query": "minimal line pattern surface design",    "pages": 3},
        {"query": "abstract organic pattern texture",       "pages": 3},
        {"query": "hexagonal grid pattern modern",          "pages": 3},
        {"query": "dot grid pattern minimal",               "pages": 3},
        # By style
        {"query": "brand pattern identity system",          "pages": 3},
        {"query": "art deco pattern design",                "pages": 2},
        {"query": "isometric pattern vector",               "pages": 2},
        {"query": "textile surface pattern professional",   "pages": 3},
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

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl Pinterest for brand references, then auto-tag with Gemini Vision"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--preset", choices=["logos", "patterns"],
        help="Use curated search queries for logos or patterns",
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
        help="Reference type (default: logos)",
    )
    parser.add_argument(
        "--pages", type=int, default=5,
        help="Number of scroll pages to crawl (default: 5)",
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

    # Tag-only mode
    if args.tag_only:
        run_auto_tag(args.type)
        return

    # Build query list
    if args.preset:
        queries = PRESET_QUERIES[args.preset]
        ref_type = args.preset
    elif args.query:
        queries = [{"query": args.query, "pages": args.pages}]
        ref_type = args.type
    elif args.url:
        queries = [{"url": args.url, "pages": args.pages}]
        ref_type = args.type
    else:
        parser.print_help()
        return

    print(f"\n  Pinterest Crawler → {ref_type}")
    print(f"  Queries: {len(queries)}")
    print(f"  Target: references/{ref_type}/")

    if not args.email or not args.password:
        print("\n  ⚠ Pinterest credentials not set!")
        print("    Either pass --email/--password or set in .env:")
        print("    PINTEREST_EMAIL=your@email.com")
        print("    PINTEREST_PASSWORD=your_password")
        print("\n    Crawler may still work for public boards without login.")

    run_pipeline(
        queries=queries,
        ref_type=ref_type,
        email=args.email,
        password=args.password,
        skip_tag=args.skip_tag,
    )


if __name__ == "__main__":
    main()
