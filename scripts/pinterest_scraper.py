#!/usr/bin/env python3
"""
pinterest_scraper.py — Selenium-based Pinterest board scraper with cookie injection.

Uses your existing Pinterest browser session. No email/password needed.

SETUP (one-time):
  1. Install "Cookie-Editor" Chrome extension
  2. Open pinterest.com in Chrome (make sure you're logged in)
  3. Click Cookie-Editor → Export → "Export as JSON to Clipboard"
  4. Run: pbpaste > references/pinterest_cookies.json

Usage:
  python scripts/pinterest_scraper.py --all           # all 18 categories
  python scripts/pinterest_scraper.py --preset style_minimal_geometric
  python scripts/pinterest_scraper.py --list          # show all boards
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Dict, List

try:
    import requests
    from PIL import Image
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
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

# ── Curated boards: 18 categories × 2 boards ──────────────────────────────────
CATEGORY_BOARDS: Dict[str, List[str]] = {
    "style_minimal_geometric": [
        "https://www.pinterest.com/2385kam/minimal-geometric-design/",
        "https://www.pinterest.com/doorpostdesigns/design-minimal-%2B-modern-logos/",
    ],
    "style_corporate_enterprise": [
        "https://www.pinterest.com/mineez012/corporate-logo-design/",
        "https://www.pinterest.com/steffybangbang/corporate-logo-design/",
    ],
    "style_luxury_premium": [
        "https://www.pinterest.com/Monroe_Creative/luxury-branding-logo-design/",
        "https://www.pinterest.com/pinkbeedle/luxury-brand-logo/",
    ],
    "style_tech_futuristic": [
        "https://www.pinterest.com/an_gorski/futuristic-cyberpunk-tech-design/",
        "https://www.pinterest.com/rumzzline/ai-tech-futuristic-logo/",
    ],
    "style_organic_natural": [
        "https://www.pinterest.com/wearezehn/coaching-logo-design-minimal-natural-organic/",
        "https://www.pinterest.com/elliebstudio/natural-%2B-organic-branding/",
    ],
    "style_playful_mascot": [
        "https://www.pinterest.com/ibasica/charactermascot-logo-and-illustration/",
        "https://www.pinterest.com/ymursyidi/vector-mascot/",
    ],
    "style_retro_vintage": [
        "https://www.pinterest.com/jexsiam/retro-vintage-logo-design/",
        "https://www.pinterest.com/e_suts/retrovintage-logos/",
    ],
    "style_bold_brutalist": [
        "https://www.pinterest.com/cdekoning0262/brutalist-logo/",
        "https://www.pinterest.com/doatekin/brutalist-logo/",
    ],
    "style_elegant_editorial": [
        "https://www.pinterest.com/wilddreamersstudio/logo-%2B-fonts/",
        "https://www.pinterest.com/Tupeface_Trinity/elegant-serif-fonts/",
    ],
    "industry_technology_saas": [
        "https://www.pinterest.com/redwanmunna_d/technology-logo-design/",
        "https://www.pinterest.com/faikarproject/technology-startup-modern-minimalist-logo-design/",
    ],
    "industry_finance_crypto": [
        "https://www.pinterest.com/ppliu688/finance-logo-design-idea/",
        "https://www.pinterest.com/AlZeleniuk/finance-logo-design/",
    ],
    "industry_fashion_beauty": [
        "https://www.pinterest.com/marimarkuletina/fashion-beauty-logo-ideas/",
        "https://www.pinterest.com/sabinabasic419/fashion-logos-beauty-logo-ideas/",
    ],
    "industry_food_beverage": [
        "https://www.pinterest.com/de_putera/coffee-logo-design/",
        "https://www.pinterest.com/de_putera/beans-coffee-logo-design/",
    ],
    "industry_media_gaming": [
        "https://www.pinterest.com/Alvazama/esport-logo-design/",
        "https://www.pinterest.com/thetoywonder/design-logo-sportesport/",
    ],
    "industry_real_estate": [
        "https://www.pinterest.com/paulreiss/identity-for-real-estate-architecture/",
        "https://www.pinterest.com/branddealer/real-estate-branding/",
    ],
    "industry_healthcare_wellness": [
        "https://www.pinterest.com/Sayemhajari/30-best-healthcaremedical-logo-designdesigner/",
        "https://www.pinterest.com/cwillisandco/holistic-wellness-branding/",
    ],
    "industry_education_edtech": [
        "https://www.pinterest.com/withfaithandlovedesign/branding-design-education-with-faith-love/",
        "https://www.pinterest.com/digitalmarketingalexa/education-institute-branding-logo-inspiration/",
    ],
    "industry_retail_ecommerce": [
        "https://www.pinterest.com/quixoticdesignco/editorial-luxe-logo-design-inspo/",
        "https://www.pinterest.com/brandcrowd/shop-logos/",
    ],
}

ALL_CATEGORIES = list(CATEGORY_BOARDS.keys())


# ── Cookies ────────────────────────────────────────────────────────────────────

def load_cookies(cookies_file: Path) -> dict:
    if not cookies_file.exists():
        print(f"\n  ✗ Cookie file not found: {cookies_file}")
        print("\n  HOW TO EXPORT COOKIES:")
        print("  1. Install Cookie-Editor Chrome extension")
        print("  2. Open pinterest.com (logged in with Facebook or any method)")
        print("  3. Click Cookie-Editor → Export → 'Export as JSON to Clipboard'")
        print(f"  4. Run: pbpaste > {cookies_file}")
        sys.exit(1)

    raw = json.loads(cookies_file.read_text())
    if isinstance(raw, list):
        cookies = {c["name"]: c["value"] for c in raw if "name" in c}
    else:
        cookies = raw

    if "_auth" in cookies:
        print(f"  ✓ Authenticated ({len(cookies)} cookies loaded)")
    else:
        print(f"  ⚠ {len(cookies)} cookies loaded (no _auth cookie — may not be logged in)")
    return cookies


# ── Selenium driver ────────────────────────────────────────────────────────────

def create_driver(headless: bool = True) -> webdriver.Chrome:
    """Create Chrome driver using webdriver-manager (auto-installs ChromeDriver)."""
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
    # Selenium v3 uses executable_path, v4+ uses Service
    chromedriver_path = ChromeDriverManager().install()
    try:
        from selenium.webdriver.chrome.service import Service
        driver = webdriver.Chrome(service=Service(chromedriver_path), options=opts)
    except TypeError:
        # Selenium v3 fallback
        driver = webdriver.Chrome(executable_path=chromedriver_path, options=opts)

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def inject_cookies(driver: webdriver.Chrome, cookies: dict) -> None:
    """Inject Pinterest session cookies. Must navigate to site first."""
    driver.get("https://www.pinterest.com")
    time.sleep(2)
    driver.delete_all_cookies()
    for name, value in cookies.items():
        try:
            driver.add_cookie({
                "name": name,
                "value": value,
                "domain": ".pinterest.com",
                "path": "/",
            })
        except Exception:
            pass
    # Reload with cookies
    driver.get("https://www.pinterest.com")
    time.sleep(2)
    print("  ✓ Cookies injected into browser")


# ── Board scraper ──────────────────────────────────────────────────────────────

def scrape_board(driver: webdriver.Chrome, board_url: str, max_imgs: int = 60) -> List[str]:
    """
    Navigate to a Pinterest board, scroll to load images, return unique pinimg URLs.
    Uses JS extraction to avoid StaleElementReferenceException.
    """
    print(f"    → {board_url}")
    driver.get(board_url)
    time.sleep(3)

    if "login" in driver.current_url or "accounts" in driver.current_url:
        print("    ⚠ Redirected to login — cookies expired")
        return []

    found = set()
    last_height = 0
    no_change = 0

    for _ in range(25):
        # Extract all pinimg URLs via JS (atomic, stale-safe)
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
        time.sleep(random.uniform(1.2, 2.2))

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            no_change += 1
            if no_change >= 4:
                break
        else:
            no_change = 0
        last_height = new_height

    urls = list(found)[:max_imgs]
    print(f"    Found {len(urls)} images")
    return urls


# ── Download & filter ──────────────────────────────────────────────────────────

def download_image(url: str, target_dir: Path, existing_hashes: set) -> bool:
    """Download, quality-filter, dedup, and save one image."""
    try:
        resp = requests.get(url, timeout=15,
                            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com"})
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

def crawl_category(driver: webdriver.Chrome, category: str, boards: List[str], target: int = 25) -> dict:
    target_dir = REFERENCES_DIR / "logos" / category
    target_dir.mkdir(parents=True, exist_ok=True)

    existing_hashes = {f.stem[:16] for f in target_dir.iterdir() if f.suffix.lower() in IMAGE_EXTS}
    already = len(existing_hashes)
    need = max(0, target - already)

    if need == 0:
        print(f"  ✓ Already {already} images — skipping")
        return {"kept": 0, "total": already}

    print(f"  Need {need} more (have {already})")
    kept = 0

    for board_url in boards:
        if kept >= need:
            break
        urls = scrape_board(driver, board_url, max_imgs=max(60, need * 3))
        for url in urls:
            if kept >= need:
                break
            if download_image(url, target_dir, existing_hashes):
                kept += 1
        print(f"  Kept so far: {kept}/{need}")
        time.sleep(random.uniform(2, 4))

    total = sum(1 for f in target_dir.iterdir() if f.suffix.lower() in IMAGE_EXTS)
    return {"kept": kept, "total": total}


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Pinterest board scraper for brand references")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="Crawl all 18 categories")
    group.add_argument("--preset", choices=ALL_CATEGORIES, metavar="CATEGORY",
                       help="Crawl a single category")
    group.add_argument("--list", action="store_true", help="List all categories and board URLs")
    parser.add_argument("--count", type=int, default=25, help="Target images per category")
    parser.add_argument("--cookies", type=str, default=str(COOKIES_FILE))
    parser.add_argument("--show-browser", action="store_true",
                        help="Show Chrome window (instead of headless)")
    args = parser.parse_args()

    if args.list:
        for cat, boards in CATEGORY_BOARDS.items():
            print(f"\n{cat}:")
            for b in boards:
                print(f"  {b}")
        return

    cookies = load_cookies(Path(args.cookies))

    categories = ALL_CATEGORIES if getattr(args, "all", False) else \
                 ([args.preset] if args.preset else None)
    if not categories:
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
            stats = crawl_category(driver, cat, CATEGORY_BOARDS[cat], target=args.count)
            grand_total += stats["kept"]
            if i < len(categories):
                time.sleep(random.uniform(2, 4))

    finally:
        driver.quit()

    print(f"\n✓ Done: {grand_total} new images across {len(categories)} categories")
    print("  Folder: references/logos/")
    print("  Next:   review images, then run:")
    print("          python scripts/build_reference_index.py")
    print("          python scripts/generate_style_guide.py")


if __name__ == "__main__":
    main()
