#!/usr/bin/env python3
"""
pinterest_scraper.py — Search-based Pinterest scraper using your logged-in account.

Your account's search results are personalized to YOUR aesthetic taste.
Uses Selenium + cookie injection (no password needed).

SETUP (one-time):
  1. Install "Cookie-Editor" Chrome extension
  2. Open pinterest.com (logged in)
  3. Cookie-Editor → Export → "Export as JSON to Clipboard"
  4. Run: pbpaste > references/pinterest_cookies.json

Usage:
  python scripts/pinterest_scraper.py --all           # all 18 categories
  python scripts/pinterest_scraper.py --preset style_luxury_premium
  python scripts/pinterest_scraper.py --recrawl style_minimal_geometric  # delete + redo
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List
from urllib.parse import quote_plus

try:
    import requests
    from PIL import Image
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
except ImportError as e:
    print(f"Missing: {e}")
    print("Run: pip install requests Pillow selenium webdriver-manager")
    sys.exit(1)

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
REFERENCES_DIR = PROJECT_ROOT / "references"
COOKIES_FILE = REFERENCES_DIR / "pinterest_cookies.json"

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

MIN_FILE_SIZE = 8_000
MIN_DIMENSION = 300
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


# ── Search queries per category ────────────────────────────────────────────────
# These are used as Pinterest search queries — personalized by YOUR account
CATEGORY_QUERIES: Dict[str, List[str]] = {
    # Design Styles
    "style_minimal_geometric": [
        "minimal geometric logo design",
        "abstract symbol logo mark negative space",
        "flat geometric brand identity logo",
    ],
    "style_corporate_enterprise": [
        "corporate logo design professional enterprise",
        "B2B brand identity logo minimalist",
        "consulting firm logo design modern",
    ],
    "style_luxury_premium": [
        "luxury brand logo design premium elegant",
        "high end fashion logo serif elegant",
        "exclusive brand identity sophisticated",
    ],
    "style_tech_futuristic": [
        "tech logo design futuristic AI startup",
        "futuristic brand identity abstract symbol",
        "startup tech logo geometric digital",
    ],
    "style_organic_natural": [
        "organic logo design natural botanical",
        "eco brand identity hand-drawn nature",
        "sustainable brand logo leaf plant natural",
    ],
    "style_playful_mascot": [
        "playful mascot logo character design brand",
        "fun friendly mascot logo illustration",
        "character logo cute bold colorful",
    ],
    "style_retro_vintage": [
        "retro vintage logo design badge emblem",
        "vintage brand logo classic typography",
        "retro logo stamp distressed 70s 80s",
    ],
    "style_bold_brutalist": [
        "bold brutalist logo design heavy type",
        "strong graphic logo bold geometric",
        "impact wordmark logo heavy contrast brand",
    ],
    "style_elegant_editorial": [
        "elegant editorial logo design typography fashion",
        "serif wordmark logo luxury fashion house",
        "typographic logo editorial high fashion",
    ],
    # Industries
    "industry_technology_saas": [
        "technology SaaS logo design startup AI",
        "software tech company logo modern abstract",
        "AI startup brand identity minimal",
    ],
    "industry_finance_crypto": [
        "fintech logo design finance banking brand",
        "crypto blockchain logo web3 brand identity",
        "investment fund logo premium financial",
    ],
    "industry_fashion_beauty": [
        "fashion brand logo design luxury beauty",
        "beauty cosmetics logo minimal elegant brand",
        "lifestyle brand logo script serif",
    ],
    "industry_food_beverage": [
        "food beverage brand logo restaurant design",
        "coffee shop cafe logo minimal modern",
        "hospitality hotel restaurant brand logo",
    ],
    "industry_media_gaming": [
        "media entertainment logo design bold dynamic",
        "gaming esports logo design bold modern",
        "podcast streaming media brand identity logo",
    ],
    "industry_real_estate": [
        "real estate logo design architecture brand",
        "property development brand identity logo minimal",
        "architecture firm logo geometric abstract",
    ],
    "industry_healthcare_wellness": [
        "healthcare wellness logo design medical brand",
        "health wellness app logo minimal clean",
        "mental health wellness brand identity logo",
    ],
    "industry_education_edtech": [
        "education brand logo edtech learning design",
        "online learning platform logo modern minimal",
        "educational institution logo design clean",
    ],
    "industry_retail_ecommerce": [
        "retail ecommerce logo brand identity design",
        "online store shopping brand logo minimal",
        "D2C brand logo modern consumer direct",
    ],

    # Patterns
    "pattern_geometric_repeat": [
        "geometric repeat seamless pattern design",
        "abstract geometric brand pattern tileable",
        "simple shape grid pattern minimal",
    ],
    "pattern_organic_fluid": [
        "organic fluid seamless pattern design",
        "flowing lines brand pattern waves",
        "soft organic shape background tileable",
    ],
    "pattern_abstract_gradient_mesh": [
        "abstract gradient mesh brand background",
        "soft blurred gradient mesh design tileable",
        "colorful fluid gradient background pattern",
    ],
    "pattern_line_art_monoline": [
        "line art monoline seamless pattern design",
        "thin line grid pattern sophisticated tileable",
        "minimalist line art brand pattern tile",
    ],
    "pattern_icon_based_repeating": [
        "icon based repeating seamless pattern",
        "pictogram brand pattern tileable",
        "small symbol repeating background pattern",
    ],
    "pattern_textile_inspired": [
        "textile inspired seamless pattern design",
        "fabric weave texture background brand",
        "woven textile brand pattern tileable",
    ],
    "pattern_tech_grid_circuit": [
        "tech grid circuit seamless pattern design",
        "cyber technology background pattern",
        "digital grid tech pattern tileable",
    ],
    "pattern_memphis_playful": [
        "memphis playful seamless pattern design",
        "colorful 80s memphis brand pattern",
        "bold fun pop art texture graphic",
    ],
    "pattern_cultural_heritage": [
        "cultural heritage inspired seamless pattern",
        "traditional folk art brand pattern tileable",
        "heritage motif repeating pattern background",
    ],
}

ALL_CATEGORIES = list(CATEGORY_QUERIES.keys())


# ── Cookies ────────────────────────────────────────────────────────────────────

def load_cookies(cookies_file: Path) -> dict:
    if not cookies_file.exists():
        print(f"\n  ✗ Cookie file not found: {cookies_file}")
        print("  Run: pbpaste > references/pinterest_cookies.json")
        print("  (after doing Export → Copy to Clipboard in Cookie-Editor)")
        sys.exit(1)

    raw = json.loads(cookies_file.read_text())
    cookies = {c["name"]: c["value"] for c in raw if "name" in c} \
              if isinstance(raw, list) else raw

    status = "✓ Authenticated" if "_auth" in cookies else "⚠ No _auth cookie"
    print(f"  {status} ({len(cookies)} cookies)")
    return cookies


# ── Selenium driver ────────────────────────────────────────────────────────────

def create_driver(headless: bool = True) -> webdriver.Chrome:
    from webdriver_manager.chrome import ChromeDriverManager
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    )
    chromedriver_path = ChromeDriverManager().install()
    try:
        from selenium.webdriver.chrome.service import Service
        driver = webdriver.Chrome(service=Service(chromedriver_path), options=opts)
    except TypeError:
        driver = webdriver.Chrome(executable_path=chromedriver_path, options=opts)

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def inject_cookies(driver: webdriver.Chrome, cookies: dict) -> None:
    driver.get("https://www.pinterest.com")
    time.sleep(2)
    driver.delete_all_cookies()
    for name, value in cookies.items():
        try:
            driver.add_cookie({
                "name": name, "value": value,
                "domain": ".pinterest.com", "path": "/",
            })
        except Exception:
            pass
    driver.get("https://www.pinterest.com")
    time.sleep(2)
    print("  ✓ Session injected into browser")


# ── Pinterest search scraper ───────────────────────────────────────────────────

def search_and_scrape(
    driver: webdriver.Chrome,
    query: str,
    max_imgs: int = 60,
) -> List[str]:
    """
    Run a Pinterest search query with the logged-in account,
    scroll to load results, extract image URLs.
    """
    search_url = f"https://www.pinterest.com/search/pins/?q={quote_plus(query)}"
    print(f"    🔍 '{query}'")
    driver.get(search_url)
    time.sleep(3)

    if "login" in driver.current_url:
        print("    ⚠ Redirected to login — cookies expired")
        return []

    found = set()
    last_height = 0
    no_change = 0

    for _ in range(20):
        try:
            # JS-based extraction (stale-element safe)
            urls_js: list = driver.execute_script("""
                var imgs = document.querySelectorAll('img[src*="pinimg.com"]');
                var urls = [];
                for (var i = 0; i < imgs.length; i++) {
                    var src = imgs[i].src || imgs[i].getAttribute('src') || '';
                    if (src && (src.endsWith('.jpg') || src.endsWith('.png') || src.endsWith('.webp'))) {
                        urls.push(src);
                    }
                }
                return urls;
            """) or []

            for src in urls_js:
                src = re.sub(r"/(?:236x|474x|564x)/", "/736x/", src)
                found.add(src)

            if len(found) >= max_imgs:
                break

            driver.execute_script("window.scrollBy(0, 900);")
            time.sleep(random.uniform(1.2, 2.0))

            new_height = driver.execute_script(
                "return document.body ? document.body.scrollHeight : 0"
            ) or 0
            if new_height == last_height:
                no_change += 1
                if no_change >= 4:
                    break
            else:
                no_change = 0
            last_height = new_height

        except Exception:
            time.sleep(2)
            continue

    return list(found)[:max_imgs]


# ── Download & quality filter ──────────────────────────────────────────────────

def download_image(url: str, target_dir: Path, existing_hashes: set) -> bool:
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.pinterest.com",
        })
        resp.raise_for_status()
        content = resp.content

        if len(content) < MIN_FILE_SIZE:
            return False

        img = Image.open(io.BytesIO(content))
        w, h = img.size
        if w < MIN_DIMENSION or h < MIN_DIMENSION:
            return False

        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=92)
            content = buf.getvalue()

        h_ = hashlib.md5(content).hexdigest()
        if h_[:16] in existing_hashes:
            return False
        existing_hashes.add(h_[:16])

        (target_dir / f"{h_}.jpg").write_bytes(content)
        return True
    except Exception:
        return False


# ── Category crawl ─────────────────────────────────────────────────────────────

def crawl_category(
    driver: webdriver.Chrome,
    category: str,
    queries: List[str],
    target: int = 25,
    force: bool = False,
) -> dict:
    folder_type = "logos"
    if category.startswith("pattern_"):
        folder_type = "patterns"
    elif category.startswith("design_system_"):
        folder_type = "design_systems"

    target_dir = REFERENCES_DIR / folder_type / category
    target_dir.mkdir(parents=True, exist_ok=True)

    if force and target_dir.exists():
        print(f"  ♻ Deleting existing images for re-crawl...")
        for f in target_dir.iterdir():
            if f.suffix.lower() in IMAGE_EXTS:
                f.unlink()

    existing_hashes = {f.stem[:16] for f in target_dir.iterdir()
                       if f.suffix.lower() in IMAGE_EXTS}
    already = len(existing_hashes)
    need = max(0, target - already)

    if need == 0:
        print(f"  ✓ Already {already} images — skipping (use --recrawl to redo)")
        return {"kept": 0, "total": already}

    print(f"  Need {need} more (have {already})")
    kept = 0
    per_query = max(60, need * 3 // len(queries))

    for query in queries:
        if kept >= need:
            break
        urls = search_and_scrape(driver, query, max_imgs=per_query)
        print(f"    → {len(urls)} images found")
        for url in urls:
            if kept >= need:
                break
            if download_image(url, target_dir, existing_hashes):
                kept += 1

        time.sleep(random.uniform(1.5, 3.0))

    total = sum(1 for f in target_dir.iterdir() if f.suffix.lower() in IMAGE_EXTS)
    print(f"  → Kept {kept} new, total {total} images")
    return {"kept": kept, "total": total}


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Pinterest search scraper — uses YOUR account's personalized results"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="Crawl all 18 categories")
    group.add_argument("--preset", choices=ALL_CATEGORIES, metavar="CATEGORY",
                       help="Crawl a single category")
    group.add_argument("--recrawl", choices=ALL_CATEGORIES, metavar="CATEGORY",
                       help="Delete existing images and re-crawl a category")
    group.add_argument("--list", action="store_true", help="List all categories and queries")
    parser.add_argument("--count", type=int, default=25, help="Target images per category")
    parser.add_argument("--cookies", type=str, default=str(COOKIES_FILE))
    parser.add_argument("--show-browser", action="store_true", help="Show Chrome window")
    args = parser.parse_args()

    if args.list:
        for cat, queries in CATEGORY_QUERIES.items():
            print(f"\n{cat}:")
            for q in queries:
                print(f"  → \"{q}\"")
        return

    cookies = load_cookies(Path(args.cookies))

    if args.recrawl:
        categories = [args.recrawl]
        force = True
    elif getattr(args, "all", False):
        categories = ALL_CATEGORIES
        force = False
    elif args.preset:
        categories = [args.preset]
        force = False
    else:
        parser.print_help()
        return

    print(f"\n  Starting Chrome (headless={not args.show_browser})...")
    driver = create_driver(headless=not args.show_browser)

    try:
        inject_cookies(driver, cookies)

        grand_total = 0
        for i, cat in enumerate(categories, 1):
            print(f"\n{'='*60}")
            print(f"  [{i}/{len(categories)}] {cat}")
            print(f"{'='*60}")
            stats = crawl_category(
                driver, cat, CATEGORY_QUERIES[cat],
                target=args.count,
                force=(force if args.recrawl else False),
            )
            grand_total += stats["kept"]
            if i < len(categories):
                time.sleep(random.uniform(2, 4))

    finally:
        driver.quit()

    print(f"\n{'='*60}")
    print(f"  ✓ Done: {grand_total} new images across {len(categories)} categories")
    print(f"  Folder: references/logos/")
    print(f"\n  Next steps:")
    print(f"  1. Review images in Finder → delete bad ones")
    print(f"  2. python scripts/build_reference_index.py")
    print(f"  3. python scripts/generate_style_guide.py")


if __name__ == "__main__":
    main()
