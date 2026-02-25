"""
palette_fetcher.py — Fetch real curated color palettes from free online databases.

Sources (in priority order):
  1. ColourLovers API — largest community palette DB, keyword search, no auth needed
     https://www.colourlovers.com/api/palettes?format=json&keywords=...
  2. ColorMind API — AI-generated palettes based on reference colors
     http://colormind.io/api/
  3. Fallback — use the AI-generated palette from the direction

Usage:
    from src.palette_fetcher import fetch_palette_for_direction
    enriched = fetch_palette_for_direction(
        keywords=["minimal", "tech", "navy"],
        direction_colors=[{"hex": "#2C3E50", "name": "Deep Navy", "role": "primary"}, ...]
    )
    # Returns list of color dicts with hex, name, role, source
"""

from __future__ import annotations

import json
import math
import re
import urllib.request
import urllib.parse
from typing import List, Dict, Optional, Tuple

from rich.console import Console

console = Console()

# ── API endpoints ─────────────────────────────────────────────────────────────

COLOURLOVERS_URL = "http://www.colourlovers.com/api/palettes"
COLORMIND_URL    = "http://colormind.io/api/"

# ── Color math ────────────────────────────────────────────────────────────────

def hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_cmyk(r: int, g: int, b: int) -> Tuple[int, int, int, int]:
    """Convert RGB (0-255) → CMYK (0-100 percent)."""
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
    """Euclidean distance between two hex colors in RGB space."""
    ra, ga, ba = hex_to_rgb(hex_a)
    rb, gb, bb = hex_to_rgb(hex_b)
    return math.sqrt((ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2)


def luminance(r: int, g: int, b: int) -> float:
    """Perceived luminance (0–1). > 0.5 → light color."""
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def palette_similarity(fetched_hexes: List[str], direction_hexes: List[str]) -> float:
    """
    Score how similar a fetched palette is to the direction's palette.
    Uses nearest-neighbor average distance (lower = more similar).
    """
    if not fetched_hexes or not direction_hexes:
        return 999.0
    total = 0.0
    for dh in direction_hexes:
        min_dist = min(color_distance(dh, fh) for fh in fetched_hexes)
        total += min_dist
    return total / len(direction_hexes)


# ── Color name lookup ─────────────────────────────────────────────────────────

# Compact named-color dictionary for descriptive naming
_NAMED_COLORS: Dict[str, str] = {
    "000000": "Black", "ffffff": "White", "ff0000": "Red",
    "00ff00": "Green", "0000ff": "Blue", "ffff00": "Yellow",
    "ff00ff": "Magenta", "00ffff": "Cyan", "808080": "Gray",
    "c0c0c0": "Silver", "800000": "Maroon", "008000": "Forest",
    "000080": "Navy", "808000": "Olive", "800080": "Purple",
    "008080": "Teal", "ffa500": "Orange", "ffc0cb": "Pink",
    "a52a2a": "Brown", "f5f5dc": "Beige", "ffe4c4": "Bisque",
    "2c3e50": "Slate", "1a1a2e": "Midnight", "16213e": "Abyss",
    "0f3460": "Cobalt", "533483": "Violet", "e94560": "Crimson",
}

def _closest_named_color(hex_str: str) -> str:
    """Return the name of the closest named color by RGB distance."""
    h = hex_str.lstrip("#").lower()
    if h in _NAMED_COLORS:
        return _NAMED_COLORS[h]
    r, g, b = hex_to_rgb(hex_str)
    best_name, best_dist = "Color", 999999.0
    for named_hex, name in _NAMED_COLORS.items():
        nr, ng, nb = hex_to_rgb(named_hex)
        d = (r - nr) ** 2 + (g - ng) ** 2 + (b - nb) ** 2
        if d < best_dist:
            best_dist, best_name = d, name
    return best_name


def _descriptive_name(hex_str: str, idx: int) -> str:
    """Generate a short descriptive color name from hex + position."""
    r, g, b = hex_to_rgb(hex_str)
    lum = luminance(r, g, b)

    # Dominant channel
    max_ch = max(r, g, b)
    if max_ch < 30:
        return "Shadow"
    if lum > 0.88:
        return "White" if max_ch > 240 else "Mist"
    if lum < 0.12:
        return "Ink" if idx == 0 else "Deep"

    hue_names = []
    if r > g and r > b:
        hue_names = ["Ember", "Rust", "Terra", "Crimson", "Blush"]
    elif g > r and g > b:
        hue_names = ["Sage", "Forest", "Fern", "Jade", "Moss"]
    elif b > r and b > g:
        hue_names = ["Cobalt", "Navy", "Slate", "Ice", "Dusk"]
    elif r > 180 and g > 150 and b < 100:
        hue_names = ["Gold", "Amber", "Sand", "Wheat", "Honey"]
    elif r > 150 and b > 150 and g < 100:
        hue_names = ["Mauve", "Plum", "Lilac", "Violet", "Orchid"]
    else:
        hue_names = ["Stone", "Clay", "Dust", "Muted", "Tone"]

    return hue_names[idx % len(hue_names)]


ROLES = ["primary", "secondary", "accent", "background", "text", "surface"]


def _assign_roles(colors: List[Dict]) -> List[Dict]:
    """Assign primary/secondary/accent/background/text roles by luminance order."""
    sorted_by_lum = sorted(
        colors,
        key=lambda c: luminance(*hex_to_rgb(c["hex"])),
    )
    role_order = ["background", "text", "primary", "secondary", "accent", "surface"]
    for i, c in enumerate(sorted_by_lum):
        c["role"] = role_order[i] if i < len(role_order) else "surface"
    return colors


# ── Source 1: ColourLovers ────────────────────────────────────────────────────

def _fetch_colourlovers(
    keywords: List[str],
    num_per_keyword: int = 5,
    timeout: int = 8,
) -> List[List[str]]:
    """
    Search ColourLovers for palettes matching each keyword.
    Returns list of hex-list palettes (no '#' prefix — add when using).
    """
    results: List[List[str]] = []

    for kw in keywords[:4]:
        try:
            params = urllib.parse.urlencode({
                "format": "json",
                "keywords": kw,
                "numResults": num_per_keyword,
                "sortBy": "rating",
            })
            url = f"{COLOURLOVERS_URL}?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "BrandIdentityBot/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for palette in data:
                hexes = [f"#{h}" for h in palette.get("colors", []) if h]
                if len(hexes) >= 3:
                    results.append(hexes)

            if results:
                console.print(
                    f"  [dim]ColourLovers: {len(results)} palettes for '{kw}'[/dim]"
                )
                break  # Stop after first keyword with results

        except Exception as e:
            console.print(f"  [dim]ColourLovers '{kw}' failed: {e}[/dim]")
            continue

    return results


# ── Source 2: ColorMind ───────────────────────────────────────────────────────

def _fetch_colormind(seed_colors: List[str], timeout: int = 6) -> Optional[List[str]]:
    """
    Use ColorMind to generate a 5-color palette seeded from existing colors.
    Sends the 2 most contrasting seed colors, lets ColorMind fill the rest.
    """
    try:
        # Pick first 2 seed colors, rest are "N" (fill in)
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
        hexes = [f"#{r:02X}{g:02X}{b:02X}" for r, g, b in rgb_list if len(rgb_list) == 5]
        if hexes:
            console.print(f"  [dim]ColorMind: generated {len(hexes)}-color palette[/dim]")
            return hexes

    except Exception as e:
        console.print(f"  [dim]ColorMind failed: {e}[/dim]")

    return None


# ── Main entry point ──────────────────────────────────────────────────────────

def fetch_palette_for_direction(
    keywords: List[str],
    direction_colors: List[Dict],
    prefer_fetched: bool = True,
) -> List[Dict]:
    """
    Fetch the best real-world color palette for a brand direction.

    Strategy:
      1. Search ColourLovers with brand keywords → get candidate palettes
      2. Score each candidate by similarity to direction's AI colors
      3. Pick the best match (or use AI palette if fetch fails / no close match)
      4. Optionally enrich with ColorMind for variations

    Args:
        keywords: Brand keywords from brief
        direction_colors: AI-generated palette from BrandDirection.color_palette
        prefer_fetched: If True, prefer fetched palette when similarity is decent

    Returns:
        List of color dicts: {hex, name, role, cmyk, source}
        Source is "colourlovers", "colormind", or "ai"
    """
    direction_hexes = [c.get("hex", "#888888") for c in direction_colors if c.get("hex")]

    # ── Step 1: Try ColourLovers ───────────────────────────────────────────────
    candidate_palettes = _fetch_colourlovers(keywords)

    # ── Step 2: Score + pick best match ───────────────────────────────────────
    best_palette: Optional[List[str]] = None
    best_score = 999.0
    source = "ai"

    if candidate_palettes:
        for candidate in candidate_palettes:
            score = palette_similarity(candidate, direction_hexes)
            if score < best_score:
                best_score = score
                best_palette = candidate

        # Accept fetched palette if reasonably similar (distance < 120 avg per color)
        # or if prefer_fetched is True and we got anything
        if best_palette and (prefer_fetched or best_score < 120):
            source = "colourlovers"
            console.print(
                f"  [green]✓[/green] Using ColourLovers palette "
                f"[dim](similarity score: {best_score:.0f})[/dim]"
            )

    # ── Step 3: Fallback to ColorMind ─────────────────────────────────────────
    if best_palette is None and direction_hexes:
        generated = _fetch_colormind(direction_hexes)
        if generated:
            best_palette = generated
            source = "colormind"

    # ── Step 4: Final fallback — use AI palette ────────────────────────────────
    if best_palette is None:
        console.print("  [dim]Using AI-generated palette (no fetch results)[/dim]")
        return _enrich_ai_palette(direction_colors)

    # ── Step 5: Build enriched color dicts ────────────────────────────────────
    return _build_color_dicts(best_palette, source, direction_colors)


def _enrich_ai_palette(direction_colors: List[Dict]) -> List[Dict]:
    """Enrich the AI-generated palette with CMYK values and source tag."""
    result = []
    for c in direction_colors:
        hex_val = c.get("hex", "#888888")
        try:
            r, g, b = hex_to_rgb(hex_val)
            cmyk = rgb_to_cmyk(r, g, b)
        except Exception:
            cmyk = (0, 0, 0, 50)
        result.append({
            "hex": hex_val,
            "name": c.get("name", _descriptive_name(hex_val, len(result))),
            "role": c.get("role", ROLES[min(len(result), len(ROLES) - 1)]),
            "cmyk": cmyk,
            "source": "ai",
        })
    return result


def _build_color_dicts(
    hexes: List[str],
    source: str,
    direction_colors: List[Dict],
) -> List[Dict]:
    """
    Build enriched color dicts from a list of hex strings.
    Names and roles are assigned intelligently.
    """
    # Try to borrow names from direction_colors if hex is similar
    dir_name_map = {}
    for dc in direction_colors:
        dh = dc.get("hex", "")
        if dh:
            dir_name_map[dh.upper()] = dc.get("name", "")

    result = []
    for i, hex_val in enumerate(hexes[:6]):
        hex_val = hex_val.upper() if hex_val.startswith("#") else f"#{hex_val.upper()}"

        # Try to find a matching name from direction
        name = ""
        best_dist = 80  # threshold for "close enough to borrow name"
        for dh, dname in dir_name_map.items():
            d = color_distance(hex_val, dh)
            if d < best_dist:
                best_dist = d
                name = dname

        if not name:
            name = _descriptive_name(hex_val, i)

        try:
            r, g, b = hex_to_rgb(hex_val)
            cmyk = rgb_to_cmyk(r, g, b)
        except Exception:
            cmyk = (0, 0, 0, 50)

        result.append({
            "hex": hex_val,
            "name": name,
            "role": ROLES[min(i, len(ROLES) - 1)],
            "cmyk": cmyk,
            "source": source,
        })

    # Re-assign roles by luminance
    result = _assign_roles(result)
    return result
