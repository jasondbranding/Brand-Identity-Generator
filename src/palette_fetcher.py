"""
palette_fetcher.py — Fetch real curated color palettes from free online databases.

Sources (in priority order):
  1. Color Hunt  — community-curated, sorted by likes, tag-based search (unofficial API)
     POST https://colorhunt.co/php/feed.php
  2. ColorMind   — AI palette generation seeded from direction colors
     http://colormind.io/api/
  3. Fallback    — use the AI-generated palette from the direction as-is

Usage:
    from src.palette_fetcher import fetch_palette_for_direction
    enriched = fetch_palette_for_direction(
        keywords=["minimal", "tech", "navy"],
        direction_colors=[{"hex": "#2C3E50", "name": "Deep Navy", "role": "primary"}, ...]
    )
    # Returns list of color dicts: {hex, name, role, cmyk, source}
"""

from __future__ import annotations

import json
import math
import urllib.request
import urllib.parse
from typing import List, Dict, Optional, Tuple

from rich.console import Console

console = Console()

# ── API endpoints ──────────────────────────────────────────────────────────────

COLORHUNT_URL = "https://colorhunt.co/php/feed.php"
COLORMIND_URL = "http://colormind.io/api/"

# ── Color Hunt tag vocabulary ──────────────────────────────────────────────────
# Full list of valid Color Hunt tags (as of 2025)

COLORHUNT_TAGS = {
    # Palette colors
    "orange", "yellow", "green", "teal", "blue", "purple",
    "pink", "red", "beige", "brown", "black", "white", "grey", "gold",
    # Moods / aesthetics
    "pastel", "vintage", "retro", "neon", "light", "dark",
    "warm", "cold", "summer", "fall", "winter", "spring",
    "happy", "nature", "earth", "night", "space", "rainbow",
    "gradient", "sunset", "sky", "sea",
    # Use cases
    "kids", "skin", "food", "cream", "coffee",
    "wedding", "christmas", "halloween", "monochrome",
}

# ── Keyword → Color Hunt tag mapping ──────────────────────────────────────────
# Maps brand keywords (from brief / Gemini tags) → ranked list of Color Hunt tags.
# First tag in the list = highest priority for search.

KEYWORD_TAG_MAP: Dict[str, List[str]] = {
    # ── Tech / Digital ────────────────────────────────────────────────────────
    "tech":         ["blue", "dark", "night"],
    "saas":         ["blue", "gradient", "light"],
    "software":     ["blue", "dark", "gradient"],
    "startup":      ["gradient", "neon", "blue"],
    "digital":      ["blue", "dark", "gradient"],
    "app":          ["gradient", "blue", "neon"],
    "ai":           ["dark", "neon", "gradient"],
    "data":         ["blue", "dark", "teal"],
    "cloud":        ["blue", "sky", "light"],
    "crypto":       ["dark", "neon", "blue"],
    "web3":         ["dark", "neon", "purple"],
    "blockchain":   ["dark", "blue", "neon"],
    "cybersecurity":["dark", "blue", "neon"],

    # ── Minimal / Clean ────────────────────────────────────────────────────────
    "minimal":      ["monochrome", "light", "grey"],
    "minimalist":   ["monochrome", "light", "beige"],
    "clean":        ["light", "white", "grey"],
    "simple":       ["light", "pastel", "monochrome"],
    "modern":       ["gradient", "blue", "dark"],
    "flat":         ["light", "pastel", "monochrome"],
    "geometric":    ["monochrome", "dark", "blue"],

    # ── Finance / Corporate ────────────────────────────────────────────────────
    "finance":      ["blue", "dark", "gold"],
    "fintech":      ["blue", "dark", "teal"],
    "banking":      ["blue", "dark", "gold"],
    "corporate":    ["blue", "grey", "dark"],
    "enterprise":   ["blue", "dark", "monochrome"],
    "professional": ["blue", "dark", "monochrome"],
    "consulting":   ["blue", "dark", "gold"],
    "b2b":          ["blue", "dark", "grey"],
    "trust":        ["blue", "teal", "dark"],
    "serious":      ["dark", "monochrome", "blue"],

    # ── Luxury / Premium ──────────────────────────────────────────────────────
    "luxury":       ["gold", "black", "dark"],
    "premium":      ["gold", "dark", "monochrome"],
    "elegant":      ["gold", "dark", "beige"],
    "exclusive":    ["gold", "black", "dark"],
    "high-end":     ["gold", "dark", "monochrome"],
    "fashion":      ["pastel", "beige", "monochrome"],
    "editorial":    ["monochrome", "dark", "beige"],

    # ── Nature / Organic ──────────────────────────────────────────────────────
    "nature":       ["nature", "earth", "green"],
    "organic":      ["earth", "green", "nature"],
    "eco":          ["green", "earth", "nature"],
    "natural":      ["earth", "nature", "green"],
    "sustainable":  ["green", "earth", "nature"],
    "botanical":    ["green", "nature", "earth"],
    "plant":        ["green", "nature", "spring"],
    "wellness":     ["green", "pastel", "nature"],
    "health":       ["green", "teal", "light"],
    "medical":      ["blue", "teal", "light"],

    # ── Warm / Energetic ──────────────────────────────────────────────────────
    "warm":         ["warm", "orange", "yellow"],
    "energy":       ["neon", "orange", "yellow"],
    "vibrant":      ["neon", "rainbow", "gradient"],
    "bold":         ["orange", "red", "neon"],
    "dynamic":      ["gradient", "orange", "neon"],
    "powerful":     ["dark", "red", "orange"],
    "confident":    ["orange", "dark", "gold"],
    "playful":      ["rainbow", "pastel", "neon"],
    "fun":          ["rainbow", "pastel", "happy"],
    "kids":         ["kids", "rainbow", "pastel"],

    # ── Calm / Soft ───────────────────────────────────────────────────────────
    "calm":         ["pastel", "blue", "sky"],
    "soft":         ["pastel", "light", "pink"],
    "gentle":       ["pastel", "beige", "light"],
    "feminine":     ["pink", "pastel", "purple"],
    "accessible":   ["light", "pastel", "blue"],
    "friendly":     ["pastel", "happy", "warm"],
    "trustworthy":  ["blue", "teal", "light"],
    "innovative":   ["gradient", "neon", "blue"],

    # ── Food / Beverage ───────────────────────────────────────────────────────
    "food":         ["food", "warm", "orange"],
    "coffee":       ["coffee", "brown", "warm"],
    "restaurant":   ["warm", "brown", "food"],
    "beverage":     ["food", "orange", "warm"],
    "bakery":       ["beige", "cream", "warm"],
    "cream":        ["cream", "beige", "light"],

    # ── Lifestyle / Wellness ───────────────────────────────────────────────────
    "lifestyle":    ["pastel", "warm", "beige"],
    "beauty":       ["pink", "pastel", "beige"],
    "spa":          ["green", "pastel", "light"],
    "yoga":         ["earth", "pastel", "nature"],

    # ── Seasonal ──────────────────────────────────────────────────────────────
    "summer":       ["summer", "yellow", "orange"],
    "winter":       ["winter", "blue", "cold"],
    "spring":       ["spring", "pastel", "green"],
    "fall":         ["fall", "orange", "brown"],
    "autumn":       ["fall", "orange", "brown"],

    # ── Aesthetic keywords ─────────────────────────────────────────────────────
    "dark":         ["dark", "night", "black"],
    "light":        ["light", "white", "pastel"],
    "futuristic":   ["neon", "dark", "night"],
    "gradient":     ["gradient", "rainbow", "sunset"],
    "sky":          ["sky", "blue", "gradient"],
    "space":        ["space", "night", "dark"],
    "sunset":       ["sunset", "orange", "warm"],
    "ocean":        ["sea", "blue", "teal"],
    "sea":          ["sea", "blue", "teal"],
    "retro":        ["retro", "vintage", "warm"],
    "vintage":      ["vintage", "retro", "brown"],
    "neon":         ["neon", "dark", "rainbow"],
    "monochrome":   ["monochrome", "grey", "dark"],
    "wedding":      ["wedding", "beige", "pastel"],
    "rainbow":      ["rainbow", "gradient", "neon"],
    "night":        ["night", "dark", "space"],
    "gold":         ["gold", "dark", "warm"],
    "purple":       ["purple", "dark", "gradient"],
    "pink":         ["pink", "pastel", "happy"],
    "teal":         ["teal", "blue", "sea"],
    "earth":        ["earth", "nature", "brown"],
}


def _keywords_to_colorhunt_tags(keywords: List[str]) -> List[str]:
    """
    Map brand keywords to the best-matching Color Hunt tag(s).
    Returns deduplicated list, most-confident tag first.
    """
    seen: Dict[str, int] = {}  # tag → score (higher = more confident)
    for kw in keywords:
        kw_lower = kw.strip().lower()
        # Direct tag match
        if kw_lower in COLORHUNT_TAGS:
            seen[kw_lower] = seen.get(kw_lower, 0) + 10
        # Mapped keyword
        mapped = KEYWORD_TAG_MAP.get(kw_lower, [])
        for i, tag in enumerate(mapped):
            score = 5 - i  # first tag = 5pts, second = 4pts, ...
            seen[tag] = seen.get(tag, 0) + score

    # Sort by score descending, return top tags
    sorted_tags = sorted(seen.items(), key=lambda x: -x[1])
    return [tag for tag, _ in sorted_tags[:6]]


# ── Color math ─────────────────────────────────────────────────────────────────

def hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_cmyk(r: int, g: int, b: int) -> Tuple[int, int, int, int]:
    if r == g == b == 0:
        return 0, 0, 0, 100
    rf, gf, bf = r / 255, g / 255, b / 255
    k = 1 - max(rf, gf, bf)
    if k >= 1:
        return 0, 0, 0, 100
    c = (1 - rf - k) / (1 - k)
    m = (1 - gf - k) / (1 - k)
    y = (1 - bf - k) / (1 - k)
    return round(c * 100), round(m * 100), round(y * 100), round(k * 100)


def color_distance(hex_a: str, hex_b: str) -> float:
    ra, ga, ba = hex_to_rgb(hex_a)
    rb, gb, bb = hex_to_rgb(hex_b)
    return math.sqrt((ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2)


def luminance(r: int, g: int, b: int) -> float:
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def palette_similarity(fetched_hexes: List[str], direction_hexes: List[str]) -> float:
    """
    Nearest-neighbor average RGB distance between two palettes.
    Lower = more similar. Range ≈ 0–440.
    """
    if not fetched_hexes or not direction_hexes:
        return 999.0
    total = sum(
        min(color_distance(dh, fh) for fh in fetched_hexes)
        for dh in direction_hexes
    )
    return total / len(direction_hexes)


# ── Color name generation ──────────────────────────────────────────────────────

def _descriptive_name(hex_str: str, idx: int) -> str:
    r, g, b = hex_to_rgb(hex_str)
    lum = luminance(r, g, b)
    max_ch = max(r, g, b)

    if max_ch < 30:         return "Shadow"
    if lum > 0.88:          return "White" if max_ch > 240 else "Mist"
    if lum < 0.12:          return "Ink" if idx == 0 else "Deep"

    if r > g and r > b:
        names = ["Ember", "Rust", "Terra", "Crimson", "Blush"]
    elif g > r and g > b:
        names = ["Sage", "Forest", "Fern", "Jade", "Moss"]
    elif b > r and b > g:
        names = ["Cobalt", "Navy", "Slate", "Ice", "Dusk"]
    elif r > 180 and g > 150 and b < 100:
        names = ["Gold", "Amber", "Sand", "Wheat", "Honey"]
    elif r > 150 and b > 150 and g < 100:
        names = ["Mauve", "Plum", "Lilac", "Violet", "Orchid"]
    else:
        names = ["Stone", "Clay", "Dust", "Muted", "Tone"]

    return names[idx % len(names)]


ROLES = ["primary", "secondary", "accent", "background", "text", "surface"]


def _assign_roles(colors: List[Dict]) -> List[Dict]:
    """Assign roles by luminance: darkest=text, lightest=background, mid=primary etc."""
    sorted_by_lum = sorted(colors, key=lambda c: luminance(*hex_to_rgb(c["hex"])))
    role_order = ["text", "primary", "secondary", "accent", "surface", "background"]
    for i, c in enumerate(sorted_by_lum):
        c["role"] = role_order[i] if i < len(role_order) else "surface"
    return colors


# ── Source 1: Color Hunt ───────────────────────────────────────────────────────

def _parse_colorhunt_code(code: str) -> Optional[List[str]]:
    """
    Parse a Color Hunt palette code (24-char string) → list of 4 hex colors.
    e.g. "ffbe0bfb5607ff006cfbff12" → ["#FFBE0B", "#FB5607", "#FF006C", "#FBFF12"]
    """
    code = code.strip().lower()
    if len(code) != 24:
        return None
    try:
        return [f"#{code[i*6:(i+1)*6].upper()}" for i in range(4)]
    except Exception:
        return None


def _fetch_colorhunt(
    tags: List[str],
    sort: str = "popular",
    step: int = 0,
    timeout: int = 8,
) -> List[Dict]:
    """
    Fetch palettes from Color Hunt (unofficial API).

    Args:
        tags:    Color Hunt tags to filter by (one at a time — API supports single tag)
        sort:    "popular", "new", "random", "viewed"
        step:    Pagination step (0 = first 20, 1 = next 20, ...)
        timeout: Request timeout in seconds

    Returns:
        List of palette dicts: {hexes: List[str], likes: int, tags: str}
    """
    results: List[Dict] = []

    for tag in tags:
        tag = tag.strip().lower()
        if tag not in COLORHUNT_TAGS:
            continue
        try:
            payload = urllib.parse.urlencode({
                "step":   step,
                "sort":   sort,
                "tags":   tag,
                "period": "",
            }).encode("utf-8")

            req = urllib.request.Request(
                COLORHUNT_URL,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent":   "Mozilla/5.0 (compatible; BrandBot/1.0)",
                    "Referer":      "https://colorhunt.co/",
                    "Origin":       "https://colorhunt.co",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            tag_results = 0
            for item in data:
                code  = item.get("code", "")
                likes = int(item.get("likes", 0))
                hexes = _parse_colorhunt_code(code)
                if hexes:
                    results.append({
                        "hexes": hexes,
                        "likes": likes,
                        "tags":  item.get("tags", tag),
                    })
                    tag_results += 1

            if tag_results > 0:
                console.print(
                    f"  [dim]Color Hunt [{tag}]: {tag_results} palettes[/dim]"
                )
                # Got enough for this tag — try one more tag for variety
                if len(results) >= 30:
                    break

        except Exception as e:
            console.print(f"  [dim]Color Hunt [{tag}] failed: {type(e).__name__}[/dim]")
            continue

    return results


# ── Source 2: ColorMind ────────────────────────────────────────────────────────

def _fetch_colormind(seed_colors: List[str], timeout: int = 6) -> Optional[List[str]]:
    """Generate a 5-color palette from ColorMind, seeded from direction colors."""
    try:
        seeds = []
        for h in seed_colors[:2]:
            r, g, b = hex_to_rgb(h)
            seeds.append([r, g, b])

        input_list = seeds + ["N"] * (5 - len(seeds))
        payload = json.dumps({"model": "default", "input": input_list}).encode()

        req = urllib.request.Request(
            COLORMIND_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        rgb_list = data.get("result", [])
        if len(rgb_list) == 5:
            hexes = [f"#{r:02X}{g:02X}{b:02X}" for r, g, b in rgb_list]
            console.print(f"  [dim]ColorMind: generated {len(hexes)}-color palette[/dim]")
            return hexes

    except Exception as e:
        console.print(f"  [dim]ColorMind failed: {type(e).__name__}[/dim]")

    return None


# ── Main entry point ───────────────────────────────────────────────────────────

def fetch_palette_for_direction(
    keywords: List[str],
    direction_colors: List[Dict],
    top_n: int = 1,
) -> List[Dict]:
    """
    Fetch the best real-world color palette for a brand direction.

    Strategy:
      1. Map brand keywords → Color Hunt tags
      2. Fetch top palettes from Color Hunt (sorted by likes)
      3. Score each fetched palette by similarity to direction's AI colors
      4. Pick the highest-scored (most harmonious) palette
      5. Fallback: ColorMind seeded from direction colors
      6. Final fallback: enrich and return the original AI palette

    Args:
        keywords:         Brand keywords (from brief + Gemini auto-tags)
        direction_colors: AI-generated palette dicts (hex, name, role)
        top_n:            Number of palettes to return (almost always 1)

    Returns:
        List of enriched color dicts: {hex, name, role, cmyk, source}
    """
    direction_hexes = [c.get("hex", "#888888") for c in direction_colors if c.get("hex")]

    # ── Step 1: Map keywords → Color Hunt tags ─────────────────────────────────
    ch_tags = _keywords_to_colorhunt_tags(keywords)
    if ch_tags:
        console.print(
            f"  [dim]Color Hunt tags: {', '.join(ch_tags[:4])}[/dim]"
        )

    # ── Step 2: Fetch from Color Hunt ─────────────────────────────────────────
    best_palette: Optional[List[str]] = None
    best_score   = 999.0
    source       = "ai"

    if ch_tags:
        candidates = _fetch_colorhunt(ch_tags[:4], sort="popular")

        if candidates:
            # Sort by likes first, then filter by similarity
            candidates.sort(key=lambda x: -x["likes"])

            for candidate in candidates:
                hexes = candidate["hexes"]
                score = palette_similarity(hexes, direction_hexes)
                if score < best_score:
                    best_score    = score
                    best_palette  = hexes

            if best_palette:
                source = "colorhunt"
                console.print(
                    f"  [green]✓[/green] Color Hunt palette selected "
                    f"[dim](harmony score: {best_score:.0f})[/dim]"
                )

    # ── Step 3: Fallback → ColorMind ──────────────────────────────────────────
    if best_palette is None and direction_hexes:
        generated = _fetch_colormind(direction_hexes)
        if generated:
            best_palette = generated
            source       = "colormind"

    # ── Step 4: Final fallback → AI palette ───────────────────────────────────
    if best_palette is None:
        console.print("  [dim]Using AI-generated palette[/dim]")
        return _enrich_ai_palette(direction_colors)

    return _build_color_dicts(best_palette, source, direction_colors)


# ── Palette enrichment helpers ─────────────────────────────────────────────────

def _enrich_ai_palette(direction_colors: List[Dict]) -> List[Dict]:
    """Enrich the AI-generated direction palette with CMYK and source tag."""
    result = []
    for i, c in enumerate(direction_colors):
        hex_val = c.get("hex", "#888888")
        try:
            r, g, b = hex_to_rgb(hex_val)
            cmyk    = rgb_to_cmyk(r, g, b)
        except Exception:
            cmyk = (0, 0, 0, 50)
        result.append({
            "hex":    hex_val,
            "name":   c.get("name") or _descriptive_name(hex_val, i),
            "role":   c.get("role") or ROLES[min(i, len(ROLES) - 1)],
            "cmyk":   cmyk,
            "source": "ai",
        })
    return result


def _build_color_dicts(
    hexes: List[str],
    source: str,
    direction_colors: List[Dict],
) -> List[Dict]:
    """
    Build enriched color dicts from a list of hex values.
    Borrows names from direction_colors where colors are visually close.
    """
    dir_name_map = {
        dc.get("hex", "").upper(): dc.get("name", "")
        for dc in direction_colors
        if dc.get("hex")
    }

    result = []
    for i, hex_val in enumerate(hexes[:6]):
        hex_val = hex_val if hex_val.startswith("#") else f"#{hex_val}"
        hex_val = hex_val.upper()

        # Borrow name from direction if a close color exists (dist < 80)
        name = ""
        best_d = 80
        for dh, dname in dir_name_map.items():
            d = color_distance(hex_val, dh)
            if d < best_d and dname:
                best_d, name = d, dname

        if not name:
            name = _descriptive_name(hex_val, i)

        try:
            r, g, b = hex_to_rgb(hex_val)
            cmyk    = rgb_to_cmyk(r, g, b)
        except Exception:
            cmyk = (0, 0, 0, 50)

        result.append({
            "hex":    hex_val,
            "name":   name,
            "role":   ROLES[min(i, len(ROLES) - 1)],
            "cmyk":   cmyk,
            "source": source,
        })

    # Re-assign roles by luminance order for proper hierarchy
    return _assign_roles(result)
