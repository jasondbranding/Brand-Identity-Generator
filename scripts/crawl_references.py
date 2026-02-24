#!/usr/bin/env python3
"""
crawl_references.py — Scrape Dribbble + Pinterest reference images, auto-tag with Gemini Vision.

Usage:
    python scripts/crawl_references.py "minimalist tech logo" --count 25 --output references/logos
    python scripts/crawl_references.py "geometric seamless pattern dark" --count 15 --output references/patterns --source both
    python scripts/crawl_references.py "fintech brand identity" --count 20 --output references/logos --source pinterest

Sources:
    dribbble   — HTML scrape of cdn.dribbble.com images
    pinterest  — Internal BaseSearchResource JSON API (no Selenium needed)
    both       — Merge both, deduplicate, sort by popularity

Produces:
    references/{type}/{hash}.jpg     — downloaded images
    references/{type}/index.json     — Gemini Vision tags for each image
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode
from urllib.request import urlopen, Request as URLRequest
from urllib.error import URLError

try:
    import requests
except ImportError:
    print("Error: requests not installed. Run: pip install requests")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: beautifulsoup4 not installed. Run: pip install beautifulsoup4")
    sys.exit(1)

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Error: google-genai not installed. Run: pip install google-genai")
    sys.exit(1)


# ── Config ────────────────────────────────────────────────────────────────────

DRIBBBLE_SEARCH = "https://dribbble.com/search"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://dribbble.com/",
}
DOWNLOAD_WORKERS = 4
REQUEST_DELAY   = 0.5   # seconds between page requests


# ── Scraping ──────────────────────────────────────────────────────────────────

def _fetch_html(url: str, timeout: int = 15) -> Optional[str]:
    """Fetch URL with headers; return HTML string or None on error."""
    try:
        req = URLRequest(url, headers=HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (URLError, Exception) as e:
        print(f"  [warn] fetch failed: {url} — {e}")
        return None


def search_dribbble(query: str, count: int = 30) -> list:
    """
    Scrape Dribbble search results for cdn.dribbble.com image URLs.

    Returns list of dicts: {url: str, hd_url: str, page_url: str, title: str}
    """
    items = []
    page = 1
    per_page = 24  # Dribbble default

    print(f"Searching Dribbble for: '{query}' (target: {count} images)")

    while len(items) < count:
        params = urlencode({"q": query, "page": page, "per_page": per_page})
        url = f"{DRIBBBLE_SEARCH}?{params}"
        print(f"  Fetching page {page}...")

        html = _fetch_html(url)
        if not html:
            break

        soup = BeautifulSoup(html, "html.parser")

        # Find shot thumbnails — Dribbble uses <li> with data-thumbnail attributes
        # or <img> tags with cdn.dribbble.com src
        found_on_page = 0
        for img in soup.find_all("img"):
            src = img.get("src", "") or img.get("data-src", "")
            if "cdn.dribbble.com" not in src:
                continue

            # Upgrade mini thumbnail to normal size:
            # mini: /users/123/screenshots/456/media/abc_mini.png
            # normal: /users/123/screenshots/456/media/abc.png
            hd_url = src.replace("_mini.", ".").replace("_teaser.", ".")
            # Strip compression params
            hd_url = re.sub(r'\?compress=.*', '', hd_url)

            # Find parent link for page_url
            parent_a = img.find_parent("a")
            page_url = ""
            if parent_a and parent_a.get("href"):
                href = parent_a["href"]
                if href.startswith("/"):
                    page_url = "https://dribbble.com" + href
                elif href.startswith("http"):
                    page_url = href

            # Alt text as title
            title = img.get("alt", "").strip() or "Untitled"

            items.append({
                "url": src,
                "hd_url": hd_url,
                "page_url": page_url,
                "title": title,
            })
            found_on_page += 1

            if len(items) >= count:
                break

        print(f"  Found {found_on_page} images on page {page} (total: {len(items)})")

        if found_on_page == 0:
            print("  No more results.")
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    return items[:count]


# ── Behance deep crawl (fallback when Dribbble is WAF-blocked) ───────────────

def search_behance(query: str, count: int = 30) -> list:
    """
    Behance deep crawler:
    1. Search projects page → collect project URLs + appreciation counts
    2. Enter each top project page → extract full-size module images
    3. Quality filter: skip projects with too few images or low appreciations

    Behance project module images live at:
      https://mir-s3-cdn-cf.behance.net/project_modules/{size}/{hash}.jpg
    Size tiers: disp (small) < max_1200 < 1400 (good) < fs/max_3840 (huge)
    We target /1400/ as the practical best quality.

    Returns list of dicts: {url, hd_url, page_url, title, likes, source}
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.behance.net/",
    })

    print(f"  Behance deep crawl: '{query}'")

    # ── Step 1: Collect project URLs from search pages ────────────────────────
    project_urls: list = []
    for page in range(1, 4):
        search_url = (
            f"https://www.behance.net/search/projects"
            f"?q={query.replace(' ', '+')}&sort=appreciations&page={page}"
        )
        try:
            resp = session.get(search_url, timeout=15)
            if resp.status_code != 200:
                print(f"  Behance search page {page}: HTTP {resp.status_code}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.find_all("a", href=re.compile(r"/gallery/\d+/"))
            seen_proj_urls = {p["url"] for p in project_urls}

            added = 0
            for link in links:
                href = link.get("href", "")
                if not href:
                    continue
                full_url = href if href.startswith("http") else f"https://www.behance.net{href}"
                # Strip query params
                full_url = full_url.split("?")[0]
                if full_url in seen_proj_urls:
                    continue
                seen_proj_urls.add(full_url)

                # Try to find appreciation count near this link
                appreciations = 0
                parent = link.find_parent(["div", "li", "article"])
                if parent:
                    for stat_text in parent.find_all(string=re.compile(r'[\d,]+')):
                        num = stat_text.strip().replace(",", "").replace(".", "")
                        if num.isdigit() and 10 <= int(num) <= 999999:
                            appreciations = max(appreciations, int(num))

                project_urls.append({"url": full_url, "appreciations": appreciations})
                added += 1

            print(f"  Behance search page {page}: found {added} new projects")
            if added == 0:
                break
            time.sleep(1)

        except Exception as e:
            print(f"  Behance search page {page} error: {e}")
            break

    if not project_urls:
        # Fallback: regex scan for /gallery/ URLs (works even if BS4 misses them)
        try:
            resp = session.get(
                f"https://www.behance.net/search/projects?q={query.replace(' ', '+')}&sort=appreciations",
                timeout=15,
            )
            hits = re.findall(r'https://www\.behance\.net/gallery/(\d+)/([^\"\'\s?#]+)', resp.text)
            for pid, slug in dict.fromkeys(hits).keys() if hasattr(dict.fromkeys(hits), 'keys') else hits:
                url = f"https://www.behance.net/gallery/{pid}/{slug}"
                project_urls.append({"url": url, "appreciations": 0})
        except Exception:
            pass

    # Sort by appreciation count (quality signal)
    project_urls.sort(key=lambda x: x["appreciations"], reverse=True)

    # ── Step 2: Enter each project page and extract full-size images ──────────
    results: list = []
    max_projects = min(len(project_urls), 20)
    print(f"  Entering top {max_projects} projects for deep image extraction...")

    for i, proj in enumerate(project_urls[:max_projects]):
        if len(results) >= count:
            break
        try:
            resp = session.get(proj["url"], timeout=15)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Project title
            title_tag = soup.find("title")
            project_title = (title_tag.get_text(strip=True) if title_tag else "untitled")
            project_title = re.sub(r'\s*[|–-]\s*Behance.*$', '', project_title).strip() or "untitled"

            # Find all project-module images (actual content, not nav/avatar thumbnails)
            seen_bases: set = set()
            project_images: list = []

            for img in soup.find_all("img"):
                src = (
                    img.get("src", "")
                    or img.get("data-src", "")
                    or img.get("data-delayed-url", "")
                    or ""
                )
                if "project_modules" not in src:
                    continue
                # Skip tiny thumbnails
                if any(skip in src for skip in ("/disp/", "/115/", "/130/", "/202/", "/50/")):
                    continue

                # Upgrade to /1400/ if possible
                hd_url = src
                hd_url = re.sub(r'/max_1200/', '/1400/', hd_url)
                # Don't upgrade /fs/ or /max_3840/ — too large, keep as-is

                # Deduplicate by base path (same image different size tier)
                base = re.sub(r'/(?:disp|max_\d+|\d{3,4}x?|fs)/', '/KEY/', hd_url)
                if base in seen_bases:
                    continue
                seen_bases.add(base)
                project_images.append(hd_url)

            # Also try lazy-loaded data-src attributes (some Behance pages use these)
            for tag in soup.find_all(attrs={"data-src": re.compile(r"project_modules")}):
                src = tag.get("data-src", "")
                if any(skip in src for skip in ("/disp/", "/115/", "/130/", "/202/")):
                    continue
                hd_url = re.sub(r'/max_1200/', '/1400/', src)
                base = re.sub(r'/(?:disp|max_\d+|\d{3,4}x?|fs)/', '/KEY/', hd_url)
                if base not in seen_bases:
                    seen_bases.add(base)
                    project_images.append(hd_url)

            # Skip projects with too few real images
            if len(project_images) < 2:
                continue

            for img_url in project_images:
                if len(results) >= count:
                    break
                results.append({
                    "url": img_url,
                    "hd_url": img_url,      # already upgraded
                    "title": project_title,
                    "likes": proj["appreciations"],
                    "source": "behance",
                    "page_url": proj["url"],
                })

            print(
                f"  [{i+1}/{max_projects}] {project_title[:45]:45s}"
                f"  → {len(project_images)} imgs  ♥ {proj['appreciations']}"
            )
            time.sleep(1)

        except Exception as e:
            print(f"  [{i+1}] Error entering {proj['url']}: {e}")
            continue

    print(f"  Behance deep crawl total: {len(results)} images from {max_projects} projects")
    return results[:count]


# ── Pinterest scraping (curl_cffi — bypasses Akamai TLS fingerprinting) ──────

def search_pinterest(query: str, count: int = 30) -> list:
    """
    Pinterest crawler using curl_cffi to bypass Akamai/TLS fingerprint blocking.

    curl_cffi impersonates Chrome's TLS/JA3 handshake — Pinterest (and its
    Akamai CDN) sees a real browser connection.

    Requires: pip install curl_cffi
    Optional: ~/.pinterest_cookie  (exported from browser, improves success rate)

    Returns list of dicts: {url, hd_url, title, likes, source, page_url}
    Returns [] gracefully on any failure.
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        print("  ⚠ curl_cffi not installed. Run: pip install curl_cffi")
        print("  Skipping Pinterest.")
        return []

    # Load cookie if available
    cookie_str = ""
    cookie_path = Path.home() / ".pinterest_cookie"
    if cookie_path.exists():
        cookie_str = cookie_path.read_text().strip()
        if cookie_str:
            print(f"  Pinterest: loaded cookie ({len(cookie_str)} chars)")
        else:
            print(f"  Pinterest: cookie file empty at {cookie_path}")
    else:
        print(f"  Pinterest: no cookie at {cookie_path} (may still work via session)")

    session = cffi_requests.Session(impersonate="chrome120")

    # Step 1: Visit search page to bootstrap session cookies
    bootstrap_url = f"https://www.pinterest.com/search/pins/?q={query.replace(' ', '+')}"
    bootstrap_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if cookie_str:
        bootstrap_headers["Cookie"] = cookie_str

    results: list = []

    # Attempt A: Fetch multiple search result pages (HTML) and parse embedded JSON state
    # Pinterest SSR embeds pin data inside <script id="__PWS_INITIAL_STRING__"> or
    # window.__PWS_DATA__ — we extract image URLs directly from the HTML.
    for page in range(1, 4):
        page_url_fetch = (
            f"https://www.pinterest.com/search/pins/"
            f"?q={query.replace(' ', '+')}&rs=typed"
            + (f"&page={page}" if page > 1 else "")
        )
        fetch_headers = dict(bootstrap_headers)
        try:
            resp = session.get(page_url_fetch, headers=fetch_headers, timeout=20)
            if resp.status_code != 200:
                print(f"  Pinterest search page {page}: HTTP {resp.status_code}")
                if page == 1 and resp.status_code in (403, 429):
                    print("  Pinterest debug headers:")
                    for k, v in resp.headers.items():
                        print(f"    {k}: {v}")
                break
            html = resp.text
        except Exception as e:
            print(f"  Pinterest page {page} fetch error: {e}")
            break

        page_found = 0

        # Strategy 1: Extract from __PWS_INITIAL_STRING__ embedded JSON
        # Pinterest embeds Redux state as JSON in a <script> tag
        m = re.search(
            r'<script[^>]*id=["\']__PWS_INITIAL_STRING__["\'][^>]*>(.*?)</script>',
            html, re.DOTALL
        )
        if not m:
            # Try alternate: P.start(...) or __PWS_DATA__
            m = re.search(r'__PWS_DATA__\s*=\s*(\{.*?\})\s*;', html, re.DOTALL)

        if m:
            try:
                state_json = json.loads(m.group(1))
                # Walk the redux state to find pin objects with images
                state_str = json.dumps(state_json)
                # Find all image objects: "images":{"236x":{"url":"..."}, ...}
                img_blocks = re.findall(
                    r'"images"\s*:\s*(\{[^}]{20,500}\})',
                    state_str
                )
                for block in img_blocks:
                    try:
                        imgs = json.loads(block)
                        url = None
                        for size_key in ["orig", "1200x", "736x", "474x", "236x"]:
                            if size_key in imgs:
                                url = imgs[size_key].get("url")
                                if url:
                                    break
                        if not url:
                            continue
                        hd_url = url
                        for sz in ("/236x/", "/474x/", "/736x/", "/1200x/"):
                            hd_url = hd_url.replace(sz, "/originals/")
                        results.append({
                            "url": url, "hd_url": hd_url,
                            "title": "untitled", "likes": 0,
                            "source": "pinterest", "page_url": "",
                        })
                        page_found += 1
                        if len(results) >= count:
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        # Strategy 2: Regex scan for pinimg.com image URLs embedded anywhere in HTML
        if page_found == 0:
            pinimg_urls = re.findall(
                r'https://i\.pinimg\.com/(?:originals|[0-9]+x[0-9]*)/[^\s"\'\\>]+\.(?:jpg|png|webp)',
                html,
            )
            seen_in_page: set = set()
            for url in pinimg_urls:
                if url in seen_in_page:
                    continue
                seen_in_page.add(url)
                hd_url = re.sub(r'/\d+x\d*/', '/originals/', url)
                results.append({
                    "url": url, "hd_url": hd_url,
                    "title": "untitled", "likes": 0,
                    "source": "pinterest", "page_url": "",
                })
                page_found += 1
                if len(results) >= count:
                    break

        print(f"  Pinterest search page {page}: {page_found} pins found (total: {len(results)})")
        if page_found == 0:
            break
        if len(results) >= count:
            break
        time.sleep(2)

    # Deduplicate by URL
    seen_urls: set = set()
    deduped: list = []
    for r in results:
        k = r.get("hd_url") or r.get("url", "")
        if k and k not in seen_urls:
            seen_urls.add(k)
            deduped.append(r)

    deduped.sort(key=lambda x: x.get("likes", 0), reverse=True)
    return deduped[:count]


# ── Download ──────────────────────────────────────────────────────────────────

def _md5_filename(url: str, ext: str = "jpg") -> str:
    """Generate stable filename from URL hash."""
    return hashlib.md5(url.encode()).hexdigest()[:16] + f".{ext}"


def _download_single(item: dict, output_dir: Path) -> Optional[dict]:
    """
    Download one image. Try hd_url first; fall back to url on any error.
    Returns updated item dict with local_path, or None on failure.
    """
    # Build candidate URL list: hd_url first (higher res), then url as fallback
    candidates = []
    hd = item.get("hd_url", "")
    orig = item.get("url", "")
    if hd:
        candidates.append(hd)
    if orig and orig != hd:
        candidates.append(orig)
    if not candidates:
        return None

    # Use the first candidate to derive the stable filename (keyed to original URL)
    key_url = orig or hd
    ext = key_url.split(".")[-1].split("?")[0].lower()
    if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
        ext = "jpg"

    filename = _md5_filename(key_url, ext)
    dest = output_dir / filename

    if dest.exists() and dest.stat().st_size > 500:
        return {**item, "local_path": str(dest), "filename": filename}

    # Behance CDN requires Referer header; Pinterest/Dribbble use default HEADERS
    source = item.get("source", "")
    dl_headers = dict(HEADERS)
    if source == "behance":
        dl_headers["Referer"] = "https://www.behance.net/"
    elif source == "pinterest":
        dl_headers["Referer"] = "https://www.pinterest.com/"

    for attempt_url in candidates:
        try:
            req = URLRequest(attempt_url, headers=dl_headers)
            with urlopen(req, timeout=20) as resp:
                data = resp.read()
            if len(data) < 500:
                continue  # Too small — try next candidate
            dest.write_bytes(data)
            return {**item, "local_path": str(dest), "filename": filename}
        except Exception:
            pass  # Try next candidate

    print(f"  [warn] download failed for all candidates: {key_url[:80]}")
    return None


def download_image(items: list, output_dir: Path) -> list:
    """
    Download images in parallel using ThreadPoolExecutor.
    Returns list of successfully downloaded items with local_path added.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    print(f"\nDownloading {len(items)} images to {output_dir}/")

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        futures = {pool.submit(_download_single, item, output_dir): item for item in items}
        done = 0
        for future in as_completed(futures):
            result = future.result()
            done += 1
            if result:
                results.append(result)
                if done % 10 == 0 or done == len(items):
                    print(f"  {done}/{len(items)} — {len(results)} successful")

    print(f"Downloaded: {len(results)}/{len(items)} images")
    return results


# ── Gemini Vision Auto-Tagging ─────────────────────────────────────────────────

TAG_PROMPT = """\
Analyze this design image and return a JSON object with these fields:

{
  "type": "<one of: logo, pattern, background, illustration, branding, typography, mockup, other>",
  "style": ["<2-4 style tags, e.g.: minimalist, geometric, organic, luxury, playful, corporate, tech, vintage>"],
  "industry": ["<1-3 industry tags, e.g.: tech, finance, food, fashion, health, real_estate, education>"],
  "mood": ["<2-3 mood tags, e.g.: bold, calm, energetic, sophisticated, friendly, serious, creative>"],
  "colors": ["<2-4 dominant hex codes, e.g.: #1A2B3C>"],
  "quality": <integer 1-10, judging technical execution quality>,
  "description": "<one sentence describing what you see>"
}

Return ONLY valid JSON, no markdown, no explanation.
"""


def _tag_single(item: dict, client: genai.Client) -> Optional[dict]:
    """Tag one image with Gemini Vision. Returns item with 'tags' dict added."""
    local_path = item.get("local_path")
    if not local_path or not Path(local_path).exists():
        return None

    try:
        img_bytes = Path(local_path).read_bytes()
        ext = local_path.split(".")[-1].lower()
        mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type=mime),
                types.Part.from_text(TAG_PROMPT),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        raw = response.text or ""
        # Strip any markdown fences
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        tags = json.loads(raw)
        return {**item, "tags": tags}

    except Exception as e:
        print(f"  [warn] tagging failed for {local_path}: {e}")
        return {**item, "tags": {}}


def auto_tag_with_gemini(items: list, output_dir: Path) -> list:
    """
    Run Gemini Vision on each downloaded image to generate tags.
    Saves/updates index.json in output_dir.
    Returns items list with tags added.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  [warn] GEMINI_API_KEY not set — skipping auto-tagging")
        return items

    client = genai.Client(api_key=api_key)
    index_path = output_dir / "index.json"

    # Load existing index
    existing: dict = {}
    if index_path.exists():
        try:
            existing = json.loads(index_path.read_text())
        except Exception:
            pass

    tagged = []
    print(f"\nAuto-tagging {len(items)} images with Gemini Vision...")

    for i, item in enumerate(items):
        filename = item.get("filename", "")
        if filename in existing:
            # Already tagged — skip
            tagged.append({**item, "tags": existing[filename].get("tags", {})})
            continue

        result = _tag_single(item, client)
        if result:
            tagged.append(result)
            # Save to index
            existing[filename] = {
                "url": item.get("hd_url") or item.get("url", ""),
                "page_url": item.get("page_url", ""),
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "local_path": item.get("local_path", ""),
                "tags": result.get("tags", {}),
            }

        if (i + 1) % 5 == 0 or (i + 1) == len(items):
            print(f"  Tagged {i + 1}/{len(items)}")
            # Save incrementally
            index_path.write_text(json.dumps(existing, indent=2))
            time.sleep(0.3)  # Gentle rate limiting

    index_path.write_text(json.dumps(existing, indent=2))
    print(f"Index saved → {index_path}  ({len(existing)} entries)")
    return tagged


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl design references from Dribbble + Pinterest, auto-tag with Gemini Vision"
    )
    parser.add_argument("query", help="Search query, e.g. 'minimalist tech logo'")
    parser.add_argument("--count", type=int, default=25, help="Images per source (default: 25)")
    parser.add_argument(
        "--output", default="references/auto",
        help="Output directory (default: references/auto)"
    )
    parser.add_argument(
        "--source", choices=["dribbble", "pinterest", "both"], default="both",
        help="Image source (default: both)"
    )
    parser.add_argument(
        "--skip-tag", action="store_true",
        help="Skip Gemini Vision auto-tagging (just download)"
    )
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    all_results: list = []

    # ── Dribbble (→ auto-fallback to Behance if WAF-blocked) ─────────────────
    if args.source in ("dribbble", "both"):
        print(f"\n🔍 Dribbble: '{args.query}'...")
        try:
            dr = search_dribbble(args.query, args.count)
            if dr:
                print(f"  Found {len(dr)} shots")
                all_results.extend(dr)
            else:
                # Dribbble likely WAF-blocked — transparently use Behance instead
                print("  Dribbble returned 0 results (WAF blocked) → trying Behance...")
                bh = search_behance(args.query, args.count)
                print(f"  Behance found {len(bh)} projects")
                all_results.extend(bh)
        except Exception as e:
            print(f"  Dribbble error: {e} — trying Behance fallback...")
            try:
                bh = search_behance(args.query, args.count)
                all_results.extend(bh)
            except Exception as e2:
                print(f"  Behance also failed: {e2}")

    # ── Pinterest ─────────────────────────────────────────────────────────────
    if args.source in ("pinterest", "both"):
        print(f"\n📌 Pinterest: '{args.query}'...")
        try:
            pr = search_pinterest(args.query, args.count)
            if pr:
                print(f"  Found {len(pr)} pins")
                all_results.extend(pr)
            else:
                print("  Pinterest returned 0 results (may be blocked) — continuing with other sources")
        except Exception as e:
            print(f"  Pinterest error: {e} — skipping")

    # ── Deduplicate by URL ────────────────────────────────────────────────────
    seen: set = set()
    unique: list = []
    for r in all_results:
        img_url = r.get("hd_url") or r.get("url", "")
        if img_url and img_url not in seen:
            seen.add(img_url)
            unique.append(r)

    print(f"\n📋 Total unique: {len(unique)}")

    if not unique:
        print("❌ No results found. Try different keywords or --source dribbble.")
        sys.exit(0)

    # ── Download ──────────────────────────────────────────────────────────────
    print(f"\n⬇️  Downloading to {output}/...")
    downloaded: list = []
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        futures = {pool.submit(_download_single, item, output): item for item in unique}
        for future in as_completed(futures):
            result = future.result()
            if result:
                downloaded.append(result)

    print(f"✅ Downloaded {len(downloaded)}/{len(unique)}")

    if not downloaded:
        print("No images downloaded successfully.")
        sys.exit(1)

    # ── Auto-tag ──────────────────────────────────────────────────────────────
    if not args.skip_tag:
        print(f"\n🏷️  Auto-tagging with Gemini Vision...")
        auto_tag_with_gemini(downloaded, output)
    else:
        print("Skipping auto-tagging (--skip-tag)")

    print(f"\n🎉 Done! {len(downloaded)} references in {output}/")


if __name__ == "__main__":
    main()
