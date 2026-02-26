"""
palette_fetcher.py — Generate brand color palettes using Gemini AI.

Replaces external APIs (ColorHunt, ColorMind) with Gemini for unlimited
color generation that understands brand context, industry, mood, and
creative direction.

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
import os
from typing import List, Dict, Optional, Tuple

from rich.console import Console

console = Console()


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


# ── Gemini palette generation ─────────────────────────────────────────────────

PALETTE_PROMPT = """\
You are an expert brand color palette designer. Generate a professional 6-color \
brand palette based on the following inputs.

BRAND KEYWORDS: {keywords}

DIRECTION COLORS (AI-suggested starting point — refine and improve these):
{direction_summary}

REQUIREMENTS:
1. Generate exactly 6 colors with clear hierarchy: primary, secondary, accent, background, text, surface
2. Colors must be harmonious and work together as a cohesive brand system
3. Ensure sufficient contrast between text and background (WCAG AA minimum)
4. Primary color should be the most distinctive and memorable
5. Background should be light enough for readability (or dark if brand is dark-themed)
6. Text color must have high contrast against background
7. Use the direction colors as inspiration but feel free to adjust hue, saturation, or lightness for better harmony
8. Consider the brand keywords to inform the emotional tone of the palette
9. Each color name should be evocative and brand-appropriate (e.g., "Midnight Teal" not just "Dark Blue")

Return ONLY a JSON array of exactly 6 objects. No explanation, no markdown fences.
Each object: {{"hex": "#RRGGBB", "name": "Evocative Name", "role": "primary|secondary|accent|background|text|surface"}}

Example:
[{{"hex": "#1E3A5F", "name": "Ocean Depth", "role": "primary"}}, {{"hex": "#4A90B8", "name": "Sky Current", "role": "secondary"}}, {{"hex": "#F2A922", "name": "Solar Flare", "role": "accent"}}, {{"hex": "#F8F6F2", "name": "Ivory Mist", "role": "background"}}, {{"hex": "#1A1A2E", "name": "Ink Night", "role": "text"}}, {{"hex": "#E8E4DF", "name": "Warm Stone", "role": "surface"}}]
"""

# Variant used when user explicitly provides color feedback — direction colors are IGNORED
PALETTE_FEEDBACK_PROMPT = """\
You are an expert brand color palette designer. The user has explicitly requested \
a palette change. You MUST follow their feedback exactly.

⭐ USER FEEDBACK (MANDATORY — override everything else): {feedback}

BRAND KEYWORDS (context only): {keywords}

REQUIREMENTS:
1. The user's feedback describes the MAIN COLOR TONES you must use — follow it literally.
2. Generate exactly 6 colors with hierarchy: primary, secondary, accent, background, text, surface
3. Primary and secondary colors MUST reflect the tones/colors the user requested
4. Colors must be harmonious and work together as a cohesive brand system
5. Ensure sufficient contrast between text and background (WCAG AA)
6. Background should be a light neutral; text should be dark with high contrast
7. Each color name should be evocative and brand-appropriate
8. Do NOT reuse or reference the old palette — generate a completely fresh palette

Return ONLY a JSON array of exactly 6 objects. No explanation, no markdown fences.
Each object: {{"hex": "#RRGGBB", "name": "Evocative Name", "role": "primary|secondary|accent|background|text|surface"}}

Example for "ocean blue & brown" feedback:
[{{"hex": "#1A4D6E", "name": "Deep Ocean", "role": "primary"}}, {{"hex": "#5C3A1E", "name": "Roasted Oak", "role": "secondary"}}, {{"hex": "#2E8BC0", "name": "Coastal Wave", "role": "accent"}}, {{"hex": "#F7F5F2", "name": "Sea Foam", "role": "background"}}, {{"hex": "#1C1C1C", "name": "Midnight", "role": "text"}}, {{"hex": "#E8E0D8", "name": "Driftwood", "role": "surface"}}]
"""


def _generate_palette_with_gemini(
    keywords: List[str],
    direction_colors: List[Dict],
    refinement_feedback: Optional[str] = None,
) -> Optional[List[Dict]]:
    """
    Use Gemini to generate a 6-color brand palette based on keywords
    and direction colors as context.

    If refinement_feedback is provided, uses the PALETTE_FEEDBACK_PROMPT which
    prioritises the user's explicit color request over the original direction colors.

    Returns list of color dicts [{hex, name, role}, ...] or None on failure.
    """
    try:
        from google import genai
    except ImportError:
        console.print("  [yellow]⚠ google-genai not installed[/yellow]")
        return None

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        console.print("  [yellow]⚠ GEMINI_API_KEY not set[/yellow]")
        return None

    keywords_str = ", ".join(keywords) if keywords else "modern, professional"

    if refinement_feedback:
        # User explicitly told us what colors they want — don't use direction colors
        prompt = PALETTE_FEEDBACK_PROMPT.format(
            feedback=refinement_feedback,
            keywords=keywords_str,
        )
    else:
        # Build direction color summary for the normal (no-feedback) case
        direction_summary = "\n".join(
            f"  - {c.get('role', 'unknown')}: {c.get('hex', '?')} ({c.get('name', '?')})"
            for c in direction_colors
        )
        if not direction_summary:
            direction_summary = "  (none provided)"

        prompt = PALETTE_PROMPT.format(
            keywords=keywords_str,
            direction_summary=direction_summary,
        )

    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = resp.text.strip()

        # Clean markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        colors = json.loads(text)
        if not isinstance(colors, list) or len(colors) < 4:
            console.print(f"  [yellow]⚠ Gemini returned {len(colors) if isinstance(colors, list) else 'non-list'}[/yellow]")
            return None

        # Validate each color has a valid hex
        validated = []
        for c in colors[:6]:
            hex_val = c.get("hex", "")
            if not hex_val.startswith("#") or len(hex_val) != 7:
                continue
            validated.append({
                "hex": hex_val.upper(),
                "name": c.get("name", ""),
                "role": c.get("role", "accent"),
            })

        if len(validated) >= 4:
            console.print(
                f"  [green]✓[/green] Gemini palette generated: "
                f"{', '.join(c['hex'] for c in validated)}"
            )
            return validated

        console.print(f"  [yellow]⚠ Gemini: only {len(validated)} valid colors[/yellow]")
        return None

    except Exception as e:
        console.print(f"  [yellow]⚠ Gemini palette failed: {type(e).__name__}: {e}[/yellow]")
        return None


# ── Main entry point ───────────────────────────────────────────────────────────

def fetch_palette_for_direction(
    keywords: List[str],
    direction_colors: List[Dict],
    top_n: int = 1,
    refinement_feedback: Optional[str] = None,
) -> List[Dict]:
    """
    Generate the best color palette for a brand direction using Gemini AI.

    Strategy:
      1. If refinement_feedback is given: use feedback-first prompt (ignores direction colors)
      2. Otherwise: use Gemini with direction colors as starting-point context
      3. Fallback: enrich and return the original AI palette from the direction

    Args:
        keywords:             Brand keywords (from brief + Gemini auto-tags)
        direction_colors:     AI-generated palette dicts (hex, name, role)
        top_n:                Number of palettes to return (kept for API compat)
        refinement_feedback:  Optional user feedback — overrides direction colors when set

    Returns:
        List of enriched color dicts: {hex, name, role, cmyk, source}
    """
    if refinement_feedback:
        console.print(
            f"  [dim]Generating palette with Gemini (feedback override: \"{refinement_feedback[:60]}\")…[/dim]"
        )
    else:
        console.print(
            f"  [dim]Generating palette with Gemini "
            f"(keywords: {', '.join(keywords[:5]) if keywords else 'none'})…[/dim]"
        )

    # ── Step 1: Gemini palette generation ────────────────────────────────────
    gemini_colors = _generate_palette_with_gemini(
        keywords, direction_colors, refinement_feedback=refinement_feedback
    )

    if gemini_colors:
        return _build_gemini_palette(gemini_colors)

    # ── Step 2: Fallback → enrich direction colors ──────────────────────────
    # NOTE: When feedback was given, this fallback uses original direction colors
    # because Gemini failed — log a warning so the issue is visible.
    if refinement_feedback:
        console.print(
            "  [yellow]⚠ Gemini feedback-palette failed — falling back to direction colors. "
            "Palette may not reflect user feedback.[/yellow]"
        )
    else:
        console.print("  [dim]Gemini unavailable, using direction palette[/dim]")
    return _enrich_ai_palette(direction_colors)


# ── Palette enrichment helpers ─────────────────────────────────────────────────

def _build_gemini_palette(gemini_colors: List[Dict]) -> List[Dict]:
    """
    Build enriched color dicts from Gemini-generated palette.
    Adds CMYK values and assigns roles by luminance.
    """
    result = []
    for i, c in enumerate(gemini_colors):
        hex_val = c.get("hex", "#888888").upper()
        name = c.get("name", "") or _descriptive_name(hex_val, i)

        try:
            r, g, b = hex_to_rgb(hex_val)
            cmyk = rgb_to_cmyk(r, g, b)
        except Exception:
            cmyk = (0, 0, 0, 50)

        result.append({
            "hex":    hex_val,
            "name":   name,
            "role":   c.get("role", ROLES[min(i, len(ROLES) - 1)]),
            "cmyk":   cmyk,
            "source": "gemini",
        })

    # Re-assign roles by luminance for proper hierarchy
    return _assign_roles(result)


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
