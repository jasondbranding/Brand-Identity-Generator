"""
Generator — uses Gemini to produce 3 separate raster PNGs per direction.

  background.png  — atmospheric mood scene, no text, no logos
  logo.png        — abstract logo mark on white, no text
  pattern.png     — seamless brand pattern/texture, no text

All images are pure visual — no copy, no UI. Text is added by the
compositor at assembly time.
"""

from __future__ import annotations

import base64
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from google import genai
from google.genai import types
from rich.console import Console

from .director import BrandDirection

console = Console()


@dataclass
class DirectionAssets:
    direction: BrandDirection
    background: Optional[Path]                                      # 1536x864 atmospheric scene
    logo: Optional[Path]                                            # 800x800 logo concept mark
    pattern: Optional[Path]                                         # 800x800 brand pattern tile
    brand_name: str = ""                                            # actual brand name from brief
    mockups: Optional[List[Path]] = field(default=None)             # composited mockup images
    logo_white: Optional[Path] = field(default=None)                # white logo on transparent bg
    logo_black: Optional[Path] = field(default=None)                # dark logo on transparent bg
    logo_transparent: Optional[Path] = field(default=None)          # original logo, white removed

    # Pre-written copy from brief — override AI-generated copy if set
    brief_tagline: str = ""             # from "## Tagline" in brief.md
    brief_ad_slogan: str = ""           # from "## Slogan" / "## Ad Slogan" in brief.md
    brief_announcement_copy: str = ""   # from "## Announcement" in brief.md

    # Full brief text — used by copy fallback generator if direction copy fields are empty
    _brief_text: str = ""

    # Enriched color palette from palette_fetcher (hex, name, role, cmyk, source)
    enriched_colors: Optional[List[dict]] = field(default=None)
    palette_png: Optional[Path] = field(default=None)               # standalone palette strip PNG

    # 11-step shade scales per color: {color_name: {50: "#hex", ..., 950: "#hex"}}
    palette_shades: Optional[Dict[str, Dict[int, str]]] = field(default=None)
    shades_png: Optional[Path] = field(default=None)                # shade scale PNG


def generate_all_assets(
    directions: list,
    output_dir: Path,
    brief_keywords: Optional[list] = None,
    brand_name: str = "",
    brief_tagline: str = "",
    brief_ad_slogan: str = "",
    brief_announcement_copy: str = "",
    brief_text: str = "",
    moodboard_images: Optional[list] = None,
    style_ref_images: Optional[list] = None,
    logo_only: bool = False,
) -> dict:
    """
    Generate bg + logo + pattern for every direction.

    Args:
        directions:              List of BrandDirection objects
        output_dir:              Directory to save assets
        brief_keywords:          Optional brand keywords for reference image matching
        brand_name:              Actual brand name from the brief
        brief_tagline:           Pre-written tagline from brief (overrides AI-generated)
        brief_ad_slogan:         Pre-written ad slogan from brief (overrides AI-generated)
        brief_announcement_copy: Pre-written announcement copy from brief (overrides AI-generated)
        brief_text:              Full raw brief text — used for copy fallback generation
        moodboard_images:        Client-provided reference images from the brief folder
                                 Injected into logo/pattern generation as highest-priority refs
        style_ref_images:        User-chosen reference images as STYLE ANCHOR — ALL logos
                                 must match the visual rendering style of these images.
        logo_only:               If True, generate ONLY logo.png — skip background, pattern,
                                 palette fetch, and shade scales. Used for Phase 1 (fast preview).

    Returns:
        Dict mapping option_number → DirectionAssets
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    for direction in directions:
        console.print(
            f"\n[bold cyan]→ Generating assets for Option {direction.option_number}: "
            f"{direction.direction_name}[/bold cyan]"
            + (" [logo only]" if logo_only else "")
        )
        assets = _generate_direction_assets(
            direction, output_dir,
            brief_keywords=brief_keywords,
            brand_name=brand_name,
            brief_tagline=brief_tagline,
            brief_ad_slogan=brief_ad_slogan,
            brief_announcement_copy=brief_announcement_copy,
            brief_text=brief_text,
            moodboard_images=moodboard_images,
            style_ref_images=style_ref_images,
            logo_only=logo_only,
        )
        results[direction.option_number] = assets

    return results


def _resolve_direction_tags(
    brief_text: str,
    direction: "BrandDirection",
    user_keywords: Optional[list] = None,
) -> list:
    """
    Use Gemini to extract taxonomy-aligned tags from brief + direction context.

    Tags are drawn from the same vocabulary used in index.json so they can
    score against reference images and style guides.

    Returns a deduplicated list of lowercase tag strings.
    Falls back to user_keywords on any error.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return list(user_keywords or [])

    # Build a short but rich context block
    context = f"""Brand brief (excerpt):
{brief_text.strip()[:800]}

Direction concept: {direction.direction_name}
Rationale: {getattr(direction, 'rationale', '')[:300]}
Graphic style: {getattr(direction, 'graphic_style', '')[:200]}
Typography: {getattr(direction, 'typography_primary', '')}
Colors: {', '.join(c.hex + ' (' + c.role + ')' for c in direction.colors[:3])}
"""

    prompt = f"""{context}

Your job: Extract tags that describe this brand's visual identity so we can find the most relevant logo reference images and style guides.

Return ONLY a JSON array of 6–12 lowercase strings from these taxonomies — no explanation:

Industries: tech, saas, fintech, crypto, web3, healthcare, ecommerce, education, real-estate, food, beverage, fashion, automotive, media, consulting, startup, enterprise, creative, nonprofit, gaming

Visual styles: geometric, organic, monoline, filled, minimal, detailed, flat, gradient, sharp, rounded, retro, modern, classic, brutalist, elegant, playful

Moods: confident, calm, bold, playful, serious, premium, accessible, warm, cold, edgy, trustworthy, innovative, elegant, powerful, friendly, mysterious, dynamic, futuristic

Techniques: negative space, grid construction, symmetry, asymmetry, modularity

Example output: ["saas", "tech", "startup", "minimal", "geometric", "confident", "trustworthy", "modern", "negative space"]
"""

    try:
        client = genai.Client(api_key=api_key)
        for model in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash"]:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=128,
                    ),
                )
                raw = response.text.strip()
                # Strip markdown fences
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                    raw = raw.strip()
                tags = [str(t).lower().strip() for t in __import__("json").loads(raw) if t]
                if tags:
                    # Merge with user keywords (deduplicated)
                    merged = list(dict.fromkeys(tags + list(user_keywords or [])))
                    console.print(f"  [dim]auto-tags: {', '.join(merged[:8])}{'...' if len(merged) > 8 else ''}[/dim]")
                    return merged
                break
            except Exception as _me:
                if any(k in str(_me).lower() for k in ("not found", "invalid")):
                    continue
                raise
    except Exception as e:
        console.print(f"  [dim]tag extraction failed ({type(e).__name__}) — using brief keywords[/dim]")

    return list(user_keywords or [])


# ── Spec → natural language prompt translators ────────────────────────────────
# Order follows image-model best practice:
#   1. Subject + form  →  2. Composition  →  3. Color  →  4. Style  →  5. Render  →  6. Avoid

def _logo_spec_to_prompt(spec, brand_name: str = "") -> str:
    """Translate a LogoSpec (Pydantic model or dict) to a natural language image prompt.

    All logo types use ONE color (monochrome rule).
    For logotype / combination: text IS part of the mark — no text-ban clause.
    For symbol / abstract_mark / lettermark: text is forbidden.

    Args:
        spec: LogoSpec pydantic model or dict
        brand_name: actual brand name — used to validate lettermark initial
    """
    d = spec.model_dump() if hasattr(spec, "model_dump") else (spec if isinstance(spec, dict) else {})
    if not d:
        return str(spec)

    logo_type_raw  = d.get("logo_type", "abstract_mark")
    logo_type      = logo_type_raw.replace("_", " ")
    form           = d.get("form", "")
    composition    = d.get("composition", "centered, 20% padding all sides, pure white background")
    color_hex      = d.get("color_hex", "#1A1A1A")
    color_name     = d.get("color_name", "")
    fill_style     = d.get("fill_style", "solid_fill")
    stroke_wt      = d.get("stroke_weight", "N/A")
    typo_treatment = d.get("typography_treatment", "")
    render_style   = d.get("render_style", "clean flat vector")
    metaphor       = d.get("metaphor", "")
    avoid          = d.get("avoid", [])

    color_label = f"{color_name} {color_hex}".strip()

    # ── Lettermark initial validation (Fix 1 defence) ─────────────────────
    if logo_type_raw == "lettermark" and brand_name:
        expected_initial = brand_name.strip()[0].upper() if brand_name.strip() else ""
        form_upper = form.upper()
        # Check if the expected letter is mentioned in the form description
        if expected_initial and expected_initial not in form_upper:
            console.print(
                f"  [yellow]⚠ Lettermark fix: form mentions wrong letter, "
                f"expected '{expected_initial}' (from brand '{brand_name}'). Auto-patching.[/yellow]"
            )
            # Replace the first single uppercase letter reference in form with the correct one
            import re
            # Find patterns like "uppercase X" or "letter X" and replace X with correct initial
            form = re.sub(
                r'((?:uppercase|letter|capital)\s+)[A-Z]\b',
                f'\\1{expected_initial}',
                form,
                count=1,
                flags=re.IGNORECASE,
            )
            # If no pattern found, prepend the correct letter
            if expected_initial not in form.upper():
                form = f"uppercase {expected_initial}, {form}"

    # ── Hard cliché avoids (Fix 3 defence) ────────────────────────────────
    # These pictorial clichés are injected into every logo prompt's avoid list
    # regardless of what the Director specified, as a last line of defence.
    HARD_CLICHE_AVOIDS = [
        "coffee cup", "mug", "teacup", "cup icon", "drinking vessel",
        "coffee bean", "steam wisps", "fork", "spoon", "chef hat",
        "lightbulb", "gear", "cog", "circuit board", "binary code",
        "upward arrow", "growth chart", "dollar sign", "scales",
        "stethoscope", "pill", "red cross", "heartbeat line",
        "hanger", "mannequin", "scissors",
        "house outline", "key silhouette", "location pin",
    ]

    fill_desc = {
        "solid_fill":               f"solid flat fill in {color_label}",
        "outline_only":             f"outline only in {color_label}, {stroke_wt} stroke weight, transparent interior",
        "fill_with_outline_detail": f"solid fill in {color_label} with fine {stroke_wt} outline detail elements",
    }.get(fill_style, f"filled in {color_label}")

    metaphor_clause = (
        f" The form evokes {metaphor}."
        if metaphor and metaphor.lower() not in ("", "abstract", "n/a") else ""
    )

    # ── Type-specific text handling ───────────────────────────────────────────
    TEXT_ALLOWED_TYPES = ("logotype", "combination")
    is_text_type = logo_type_raw in TEXT_ALLOWED_TYPES

    # Build avoid list — never put "text"/"letterforms" in avoid for logotype/combination
    avoid_items = [a for a in avoid if a]
    if not is_text_type:
        # Ensure icon-only types always ban text even if Director forgot
        text_bans = {"text", "letterforms", "words"}
        current_lower = " ".join(avoid_items).lower()
        for ban in text_bans:
            if ban not in current_lower:
                avoid_items.insert(0, ban)
    avoid_str = ", ".join(avoid_items) if avoid_items else "gradient, drop shadow, multiple colors"

    # ── Type-specific subject preamble ────────────────────────────────────────
    typo_clause = (
        f" Typography treatment: {typo_treatment}."
        if typo_treatment and typo_treatment.lower() not in ("", "n/a") else ""
    )

    if logo_type_raw == "logotype":
        subject = f"A brand logotype — the brand name rendered as pure typography: {form}.{typo_clause}"
    elif logo_type_raw == "combination":
        subject = f"A combination mark logo (symbol and brand name composed as one unit): {form}.{typo_clause}"
    else:
        subject = f"A single {logo_type} logo mark: {form}."

    # ── No-text enforcement (only for icon types) ────────────────────────────
    text_rule = (
        ""
        if is_text_type
        else " Absolutely no text, words, letterforms, or typography anywhere in the image."
    )

    return (
        # 1. Subject + form + typography
        f"{subject} "
        # 2. Composition
        f"Composition: {composition}, pure white (#FFFFFF) background. "
        # 3. Color — always monochrome regardless of logo type
        f"Color: {fill_desc}. Strictly monochrome — one color only, no gradients, no tints, no second color. "
        # 4. Style + metaphor
        f"Visual style: {render_style}.{metaphor_clause} "
        # 5. Render quality
        "Crisp vector-like edges, high contrast, professional logo quality, scalable from 16px favicon to billboard. "
        # 6. Text rule (icon types only)
        + text_rule
        # 7. Specific avoids
        + f" Avoid: {avoid_str}."
    )


def _pattern_spec_to_prompt(spec) -> str:
    """Translate a PatternSpec to a natural language image prompt."""
    d = spec.model_dump() if hasattr(spec, "model_dump") else (spec if isinstance(spec, dict) else {})
    if not d:
        return str(spec)

    motif        = d.get("motif", "geometric repeating pattern")
    density      = d.get("density_scale", "")
    primary_hex  = d.get("primary_color_hex", "#000000")
    secondary_hex = d.get("secondary_color_hex", "none")
    bg_hex       = d.get("background_color_hex", "#FFFFFF")
    opacity      = d.get("opacity_notes", "solid")
    render_style = d.get("render_style", "flat vector, seamless tile")
    mood         = d.get("mood", "professional")
    avoid        = d.get("avoid", ["text", "logos"])

    color_desc = f"primary motif color {primary_hex} on background {bg_hex}"
    if secondary_hex and secondary_hex.lower() not in ("none", ""):
        color_desc += f", secondary accent {secondary_hex}"
    if opacity and opacity.lower() not in ("solid", ""):
        color_desc += f" ({opacity})"

    density_clause = f" Scale and density: {density}." if density else ""
    avoid_str = ", ".join(avoid)

    return (
        # 1. Subject + motif
        f"A seamless repeating pattern tile featuring {motif}.{density_clause} "
        # 3. Color
        f"Colors: {color_desc}. "
        # 4. Style + mood
        f"Rendering: {render_style}. Mood: {mood}. "
        # 5. Technical quality
        "All 4 edges align perfectly for seamless tiling. Professional surface/textile design quality. "
        # 6. Avoids
        f"Absolutely no: {avoid_str}."
    )


def _bg_spec_to_prompt(spec) -> str:
    """Translate a BackgroundSpec to a natural language image prompt."""
    d = spec.model_dump() if hasattr(spec, "model_dump") else (spec if isinstance(spec, dict) else {})
    if not d:
        return str(spec)

    scene_type   = d.get("scene_type", "abstract_field")
    description  = d.get("description", "")
    primary_hex  = d.get("primary_color_hex", "#000000")
    accent_hex   = d.get("accent_color_hex", "none")
    lighting     = d.get("lighting", "")
    composition  = d.get("composition", "wide horizontal 16:9")
    texture      = d.get("texture", "")
    mood         = d.get("mood", "")
    avoid        = d.get("avoid", ["text", "logos", "UI elements", "watermarks"])

    quality_map = {
        "environmental_photo": "photorealistic cinematic photograph",
        "abstract_field":      "high-end abstract digital art",
        "macro_texture":       "close-up macro texture photograph",
        "digital_art":         "premium digital illustration",
    }
    quality_label = quality_map.get(scene_type, "high-quality image")

    color_desc = f"dominant color {primary_hex}"
    if accent_hex and accent_hex.lower() not in ("none", ""):
        color_desc += f", accent {accent_hex}"

    parts = [
        # 1. Subject + scene
        f"A {quality_label}: {description}.",
        # 2. Composition
        f"Composition: {composition}.",
        # 3. Color
        f"Color palette: {color_desc}.",
        # 4. Lighting + texture + mood
        (f"Lighting: {lighting}. " if lighting else "") +
        (f"Texture: {texture}. " if texture and texture.lower() not in ("smooth digital", "") else "") +
        (f"Mood: {mood}." if mood else ""),
        # 5. Render quality
        f"Wide cinematic format filling the entire frame edge-to-edge, {quality_label} rendering quality.",
        # 6. Avoids
        f"Absolutely no: {', '.join(avoid)}.",
    ]

    return " ".join(p for p in parts if p.strip())


def generate_single_direction_assets(
    direction: BrandDirection,
    output_dir: Path,
    brief_keywords: Optional[list] = None,
    brand_name: str = "",
    brief_tagline: str = "",
    brief_ad_slogan: str = "",
    brief_announcement_copy: str = "",
    brief_text: str = "",
    moodboard_images: Optional[list] = None,
    style_ref_images: Optional[list] = None,
) -> "DirectionAssets":
    """
    Generate full assets (bg + logo + pattern + palette + shades) for ONE direction.
    Used in Phase 2 after the user selects a logo direction.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    return _generate_direction_assets(
        direction, output_dir,
        brief_keywords=brief_keywords,
        brand_name=brand_name,
        brief_tagline=brief_tagline,
        brief_ad_slogan=brief_ad_slogan,
        brief_announcement_copy=brief_announcement_copy,
        brief_text=brief_text,
        moodboard_images=moodboard_images,
        style_ref_images=style_ref_images,
        logo_only=False,
    )


def _generate_direction_assets(
    direction: BrandDirection,
    output_dir: Path,
    brief_keywords: Optional[list] = None,
    brand_name: str = "",
    brief_tagline: str = "",
    brief_ad_slogan: str = "",
    brief_announcement_copy: str = "",
    brief_text: str = "",
    moodboard_images: Optional[list] = None,
    style_ref_images: Optional[list] = None,
    logo_only: bool = False,
) -> DirectionAssets:
    slug = _slugify(direction.direction_name)
    asset_dir = output_dir / f"option_{direction.option_number}_{slug}"
    asset_dir.mkdir(parents=True, exist_ok=True)

    # ── Resolve effective tags once for this direction ─────────────────────
    effective_keywords = _resolve_direction_tags(brief_text, direction, brief_keywords)

    # ── Translate structured JSON specs → natural language prompts ──────────
    # New schema: direction has logo_spec / pattern_spec / background_spec (Pydantic models)
    # Legacy fallback: direction has logo_prompt / pattern_prompt / background_prompt (str)
    def _get_prompt(spec_attr: str, prompt_attr: str, translator) -> str:
        spec = getattr(direction, spec_attr, None)
        if spec is not None:
            try:
                return translator(spec)
            except Exception as _te:
                console.print(f"  [yellow]⚠ spec→prompt failed for {spec_attr} ({_te}), using fallback[/yellow]")
        return getattr(direction, prompt_attr, "") or ""

    bg_prompt      = _get_prompt("background_spec", "background_prompt", _bg_spec_to_prompt)
    logo_prompt    = _get_prompt(
        "logo_spec", "logo_prompt",
        lambda spec: _logo_spec_to_prompt(spec, brand_name=brand_name),
    )
    pattern_prompt = _get_prompt("pattern_spec",     "pattern_prompt",    _pattern_spec_to_prompt)

    # Detect whether logo type allows text (logotype / combination)
    _logo_spec_obj = getattr(direction, "logo_spec", None)
    _logo_type_raw = (
        _logo_spec_obj.logo_type
        if _logo_spec_obj and hasattr(_logo_spec_obj, "logo_type")
        else ""
    )
    _logo_text_allowed = _logo_type_raw in ("logotype", "combination")

    # Log the translated prompt for debugging
    console.print(
        f"  [dim]logo ({_logo_type_raw or 'legacy'}, {'text OK' if _logo_text_allowed else 'no text'}) "
        f"prompt: {logo_prompt[:100]}…[/dim]"
    )

    # ── Background — removed (pattern serves as background) ──────────────────
    background = None

    logo = _generate_image(
        prompt=logo_prompt,
        save_path=asset_dir / "logo.png",
        label="logo",
        size_hint="square format, centered mark, generous white space around it",
        brief_keywords=effective_keywords,
        moodboard_images=moodboard_images,
        logo_text_allowed=_logo_text_allowed,
        style_ref_images=style_ref_images,
    )

    # ── Pattern (skipped in logo_only mode) ──────────────────────────────────
    pattern = None
    if not logo_only:
        pattern = _generate_image(
            prompt=pattern_prompt,
            save_path=asset_dir / "pattern.png",
            label="pattern",
            size_hint="square tile, seamlessly repeatable",
            brief_keywords=effective_keywords,
            moodboard_images=moodboard_images,
        )

    # Create white / black / transparent logo variants for compositor use
    variants: dict = {}
    if logo and logo.exists() and logo.stat().st_size > 100:
        variants = _create_logo_variants(logo, asset_dir)

    # ── Palette + shades (skipped in logo_only mode) ──────────────────────────
    enriched_colors: Optional[List[dict]] = None
    palette_png: Optional[Path] = None
    palette_shades: Optional[Dict[str, Dict[int, str]]] = None
    shades_png: Optional[Path] = None

    if not logo_only:
        try:
            from .palette_fetcher import fetch_palette_for_direction
            from .palette_renderer import render_palette

            console.print("  [dim]Fetching curated color palette…[/dim]")
            direction_color_dicts = [
                {"hex": c.hex, "name": c.name, "role": c.role}
                for c in direction.colors
            ]
            enriched_colors = fetch_palette_for_direction(
                keywords=effective_keywords or [],
                direction_colors=direction_color_dicts,
            )

            if enriched_colors:
                palette_path = asset_dir / "palette.png"
                render_palette(
                    colors=enriched_colors,
                    output_path=palette_path,
                    width=2400,
                    height=640,
                    direction_name=direction.direction_name,
                )
                if palette_path.exists() and palette_path.stat().st_size > 100:
                    palette_png = palette_path
                    console.print(
                        f"  [green]✓ palette[/green] → {palette_path.name} "
                        f"[dim]({len(enriched_colors)} colors, "
                        f"source: {enriched_colors[0].get('source', 'ai')})[/dim]"
                    )
        except Exception as _pe:
            console.print(f"  [dim]Palette fetch skipped: {_pe}[/dim]")

        try:
            from .shade_generator import generate_palette_shades, render_shade_scale

            console.print("  [dim]Generating shade scales…[/dim]")
            colors_for_shades = enriched_colors if enriched_colors else [
                {"hex": c.hex, "name": c.name, "role": c.role}
                for c in direction.colors
            ]
            palette_shades = generate_palette_shades(colors_for_shades, use_api=True)

            if palette_shades:
                shades_path = asset_dir / "shades.png"
                render_shade_scale(
                    palette_shades,
                    output_path=shades_path,
                    enriched_colors=colors_for_shades,
                    width=2400,
                )
                if shades_path.exists() and shades_path.stat().st_size > 100:
                    shades_png = shades_path
                    n_colors = len(palette_shades)
                    console.print(
                        f"  [green]✓ shades[/green] → {shades_path.name} "
                        f"[dim]({n_colors} colors × 11 stops)[/dim]"
                    )
        except Exception as _se:
            console.print(f"  [dim]Shade generation skipped: {_se}[/dim]")

    return DirectionAssets(
        direction=direction,
        brand_name=brand_name,
        background=background,
        logo=logo,
        pattern=pattern,
        logo_white=variants.get("logo_white"),
        logo_black=variants.get("logo_black"),
        logo_transparent=variants.get("logo_transparent"),
        brief_tagline=brief_tagline,
        brief_ad_slogan=brief_ad_slogan,
        brief_announcement_copy=brief_announcement_copy,
        _brief_text=brief_text,
        enriched_colors=enriched_colors,
        palette_png=palette_png,
        palette_shades=palette_shades,
        shades_png=shades_png,
    )


# ── Modular phase functions (called independently by HITL pipeline) ────────────


def _adjust_colors_with_gemini(
    current_colors: List[dict],
    feedback: str,
) -> Optional[List[dict]]:
    """
    Use Gemini to interpret user color feedback and return adjusted palette.
    Handles multilingual feedback (Vietnamese, English).
    Returns list of color dicts [{hex, name, role}, ...] or None on failure.
    """
    import json as _json

    hex_summary = ", ".join(
        f"{c.get('role','?')}: {c.get('hex','?')} ({c.get('name','?')})"
        for c in current_colors
    )

    prompt = (
        "You are a color palette expert. A user has the following brand color palette:\n\n"
        f"{hex_summary}\n\n"
        f"The user wants to adjust the palette with this feedback:\n"
        f'"{feedback}"\n\n'
        "Generate an adjusted palette with the same number of colors. "
        "Apply the user's feedback (which may be in Vietnamese or English). "
        "Keep colors that the user didn't mention. Change/add/adjust ONLY what the user asked for.\n\n"
        "Return ONLY a JSON array of objects with keys: hex, name, role.\n"
        "Example: [{\"hex\": \"#1E3A2F\", \"name\": \"Forest\", \"role\": \"primary\"}, ...]\n"
        "No explanation, no markdown fences — just the JSON array."
    )

    try:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            return None

        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = resp.text.strip()
        # Clean markdown fences if any
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        colors = _json.loads(text)
        if isinstance(colors, list) and len(colors) >= 2:
            # Validate each has hex
            for c in colors:
                if not c.get("hex", "").startswith("#"):
                    return None
            return colors
        return None
    except Exception:
        return None


def generate_palette_only(
    direction: BrandDirection,
    output_dir: Path,
    brief_keywords: Optional[list] = None,
    brief_text: str = "",
    refinement_feedback: Optional[str] = None,
) -> dict:
    """
    Generate palette + shade scales for one direction.
    Returns dict with keys: enriched_colors, palette_png, palette_shades, shades_png.
    """
    from .director import BrandDirection as _BD
    slug = _slugify(direction.direction_name)
    asset_dir = output_dir / f"option_{direction.option_number}_{slug}"
    asset_dir.mkdir(parents=True, exist_ok=True)

    effective_keywords = _resolve_direction_tags(brief_text, direction, brief_keywords)

    enriched_colors: Optional[List[dict]] = None
    palette_png: Optional[Path] = None
    palette_shades: Optional[Dict[str, Dict[int, str]]] = None
    shades_png: Optional[Path] = None

    try:
        from .palette_fetcher import fetch_palette_for_direction
        from .palette_renderer import render_palette

        console.print("  [dim]Fetching curated color palette…[/dim]")
        direction_color_dicts = [
            {"hex": c.hex, "name": c.name, "role": c.role}
            for c in direction.colors
        ]

        # If refinement feedback is given, use Gemini to adjust colors
        fetch_keywords = list(effective_keywords or [])
        if refinement_feedback:
            fetch_keywords.extend(refinement_feedback.lower().split())
            # Use Gemini to interpret feedback and generate adjusted color palette
            try:
                import json as _json
                adjusted = _adjust_colors_with_gemini(
                    direction_color_dicts, refinement_feedback
                )
                if adjusted:
                    direction_color_dicts = adjusted
                    console.print(
                        f"  [green]✓[/green] Palette adjusted by Gemini: "
                        f"{', '.join(c.get('hex','') for c in adjusted)}"
                    )
            except Exception as adj_err:
                console.print(f"  [yellow]⚠ Gemini color adjust: {adj_err}[/yellow]")

        enriched_colors = fetch_palette_for_direction(
            keywords=fetch_keywords,
            direction_colors=direction_color_dicts,
        )

        if enriched_colors:
            palette_path = asset_dir / "palette.png"
            render_palette(
                colors=enriched_colors,
                output_path=palette_path,
                width=2400,
                height=640,
                direction_name=direction.direction_name,
            )
            if palette_path.exists() and palette_path.stat().st_size > 100:
                palette_png = palette_path
                console.print(
                    f"  [green]✓ palette[/green] → {palette_path.name} "
                    f"[dim]({len(enriched_colors)} colors, "
                    f"source: {enriched_colors[0].get('source', 'ai')})[/dim]"
                )
    except Exception as _pe:
        console.print(f"  [dim]Palette fetch skipped: {_pe}[/dim]")

    try:
        from .shade_generator import generate_palette_shades, render_shade_scale

        console.print("  [dim]Generating shade scales…[/dim]")
        colors_for_shades = enriched_colors if enriched_colors else [
            {"hex": c.hex, "name": c.name, "role": c.role}
            for c in direction.colors
        ]
        palette_shades = generate_palette_shades(colors_for_shades, use_api=True)

        if palette_shades:
            shades_path = asset_dir / "shades.png"
            render_shade_scale(
                palette_shades,
                output_path=shades_path,
                enriched_colors=colors_for_shades,
                width=2400,
            )
            if shades_path.exists() and shades_path.stat().st_size > 100:
                shades_png = shades_path
                n_colors = len(palette_shades)
                console.print(
                    f"  [green]✓ shades[/green] → {shades_path.name} "
                    f"[dim]({n_colors} colors × 11 stops)[/dim]"
                )
    except Exception as _se:
        console.print(f"  [dim]Shade generation skipped: {_se}[/dim]")

    return {
        "enriched_colors": enriched_colors,
        "palette_png": palette_png,
        "palette_shades": palette_shades,
        "shades_png": shades_png,
    }


def generate_pattern_only(
    direction: BrandDirection,
    output_dir: Path,
    brief_keywords: Optional[list] = None,
    brief_text: str = "",
    moodboard_images: Optional[list] = None,
    style_ref_images: Optional[list] = None,
    custom_prompt: Optional[str] = None,
    palette_colors: Optional[List[dict]] = None,
) -> Optional[Path]:
    """
    Generate pattern for one direction. If custom_prompt is given, use it
    instead of deriving from direction.pattern_spec.
    Optionally injects palette colors into the prompt.
    Returns Path to pattern.png or None.
    """
    slug = _slugify(direction.direction_name)
    asset_dir = output_dir / f"option_{direction.option_number}_{slug}"
    asset_dir.mkdir(parents=True, exist_ok=True)

    effective_keywords = _resolve_direction_tags(brief_text, direction, brief_keywords)

    if custom_prompt:
        pattern_prompt = custom_prompt
    else:
        spec = getattr(direction, "pattern_spec", None)
        if spec is not None:
            try:
                pattern_prompt = _pattern_spec_to_prompt(spec)
            except Exception:
                pattern_prompt = getattr(direction, "pattern_prompt", "") or ""
        else:
            pattern_prompt = getattr(direction, "pattern_prompt", "") or ""

    # Inject palette color info if available
    if palette_colors:
        hex_list = [c.get("hex", "") for c in palette_colors if c.get("hex")]
        if hex_list:
            color_clause = f" Use EXACTLY these brand palette colors: {', '.join(hex_list)}."
            pattern_prompt += color_clause

    pattern = _generate_image(
        prompt=pattern_prompt,
        save_path=asset_dir / "pattern.png",
        label="pattern",
        size_hint="square tile, seamlessly repeatable",
        brief_keywords=effective_keywords,
        moodboard_images=moodboard_images,
        style_ref_images=style_ref_images,
    )
    return pattern


def create_logo_variants_and_svg(
    logo_path: Path,
    output_dir: Path,
) -> dict:
    """
    Create white / black / transparent variants + SVG from a logo PNG.
    Returns dict with keys: logo_white, logo_black, logo_transparent, logo_svg.
    """
    result = {}

    if not logo_path or not logo_path.exists() or logo_path.stat().st_size < 100:
        return result

    # PNG variants (white / black / transparent)
    variants = _create_logo_variants(logo_path, output_dir)
    result.update(variants)

    # SVG via vtracer — color version from original logo
    try:
        import vtracer
        svg_path = output_dir / "logo.svg"
        vtracer.convert_image_to_svg_py(
            str(logo_path),
            str(svg_path),
            colormode="color",
            hierarchical="stacked",
            mode="spline",
            filter_speckle=4,
            color_precision=6,
            layer_difference=16,
            corner_threshold=60,
            length_threshold=4.0,
            max_iterations=10,
            splice_threshold=45,
            path_precision=3,
        )
        if svg_path.exists() and svg_path.stat().st_size > 100:
            result["logo_svg"] = svg_path
            console.print(f"  [green]✓ SVG color[/green] → {svg_path.name}")
    except Exception as e:
        console.print(f"  [yellow]⚠ SVG conversion failed: {e}[/yellow]")

    # SVG white variant — from white logo variant
    white_variant = result.get("logo_white")
    if white_variant and white_variant.exists():
        try:
            import vtracer
            svg_white_path = output_dir / "logo_white.svg"
            vtracer.convert_image_to_svg_py(
                str(white_variant),
                str(svg_white_path),
                colormode="color",
                hierarchical="stacked",
                mode="spline",
                filter_speckle=4,
                color_precision=6,
                layer_difference=16,
                corner_threshold=60,
                length_threshold=4.0,
                max_iterations=10,
                splice_threshold=45,
                path_precision=3,
            )
            if svg_white_path.exists() and svg_white_path.stat().st_size > 100:
                result["logo_svg_white"] = svg_white_path
                console.print(f"  [green]✓ SVG white[/green] → {svg_white_path.name}")
        except Exception as e:
            console.print(f"  [yellow]⚠ SVG white failed: {e}[/yellow]")

    # SVG black variant — from black logo variant
    black_variant = result.get("logo_black")
    if black_variant and black_variant.exists():
        try:
            import vtracer
            svg_black_path = output_dir / "logo_black.svg"
            vtracer.convert_image_to_svg_py(
                str(black_variant),
                str(svg_black_path),
                colormode="color",
                hierarchical="stacked",
                mode="spline",
                filter_speckle=4,
                color_precision=6,
                layer_difference=16,
                corner_threshold=60,
                length_threshold=4.0,
                max_iterations=10,
                splice_threshold=45,
                path_precision=3,
            )
            if svg_black_path.exists() and svg_black_path.stat().st_size > 100:
                result["logo_svg_black"] = svg_black_path
                console.print(f"  [green]✓ SVG black[/green] → {svg_black_path.name}")
        except Exception as e:
            console.print(f"  [yellow]⚠ SVG black failed: {e}[/yellow]")

    return result


def _try_imagen(
    prompt: str,
    api_key: str,
    aspect_ratio: str = "1:1",
) -> Optional[bytes]:
    """
    Try Imagen 3 image generation. Returns raw PNG bytes or None on any failure.
    Silent — callers decide whether to log.
    """
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio=aspect_ratio,
            ),
        )
        if response.generated_images:
            return response.generated_images[0].image.image_data
    except Exception:
        pass
    return None


def _generate_image(
    prompt: str,
    save_path: Path,
    label: str,
    size_hint: str,
    brief_keywords: Optional[list] = None,
    moodboard_images: Optional[list] = None,
    logo_text_allowed: bool = False,
    style_ref_images: Optional[list] = None,
) -> Optional[Path]:
    """
    Try Imagen 3 first, then Gemini multimodal as fallback.

    For logos/patterns — injects 3 signal layers (in priority order):
      1. Client moodboard images  (from brief folder — highest fidelity signal)
      2. Library reference images (auto-tagged from references/logos/)
      3. Style guide text         (per-category .md from styles/logos/)

    All three are combined in a single multimodal call for maximum quality signal.
    Returns save_path on success; creates a placeholder on full failure.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print(f"  [yellow]⚠ GEMINI_API_KEY not set — skipping {label}[/yellow]")
        return None

    # ── Style guide injection ──────────────────────────────────────────────────
    style_guide_block = ""
    if label in ("logo", "pattern") and brief_keywords:
        guide = _get_style_guide(brief_keywords, label)
        if guide:
            # Extract only the actionable constraints (skip YAML frontmatter)
            guide_lines = [l for l in guide.splitlines() if not l.startswith("---") and l.strip()]
            guide_excerpt = "\n".join(guide_lines[:40])  # cap to avoid prompt bloat
            style_guide_block = (
                f"\n\n## STYLE GUIDE — apply these rules to this {label}:\n"
                f"{guide_excerpt}\n"
                f"## END STYLE GUIDE\n"
            )
            console.print(f"  [dim]style guide injected for {label}[/dim]")

    if label == "logo":
        # Text rule depends on logo type (logotype/combination = text allowed)
        text_req = (
            "- Brand name text is the intended output — render it with typographic precision\n"
            "- No decorative elements, frames, or abstract symbols unless specified in the prompt\n"
            if logo_text_allowed else
            "- Absolutely no text, words, letters, or typography anywhere in the image\n"
            "- Single iconic mark/symbol only — no letterforms of any kind\n"
        )
        full_prompt = (
            f"{prompt}{style_guide_block}\n\n"
            "Technical requirements:\n"
            + text_req +
            "- High contrast, clean crisp edges, professional vector quality\n"
            "- Suitable for brand identity at any scale (favicon to billboard)\n"
            "- Square format, generous padding (20%+ whitespace all sides)\n"
            "- Clean vector-like rendering, bold and memorable\n"
            "- The mark must be immediately recognizable and reproducible at small sizes"
        )
    elif label == "pattern":
        full_prompt = (
            f"{prompt}{style_guide_block}\n\n"
            "Technical requirements:\n"
            "- Seamless tileable pattern — all 4 edges MUST align perfectly when tiled\n"
            "- Consistent density and spacing throughout the entire tile\n"
            "- Absolutely no text, words, or letters anywhere in the image\n"
            "- Square tile format, professional surface/textile design quality\n"
            "- Flat vector rendering, no noise or grain unless explicitly specified"
        )
    elif label == "background":
        full_prompt = (
            f"{prompt}\n\n"
            "Technical requirements:\n"
            "- Wide landscape 16:9 atmospheric image, fills frame edge-to-edge\n"
            "- Absolutely no text, UI elements, logos, watermarks, or typography\n"
            "- Professional photography or high-end digital art quality\n"
            "- Rich color depth and strong atmospheric mood\n"
            "- Suitable as hero image or presentation background"
        )
    else:
        full_prompt = (
            f"{prompt}\n\n"
            f"Composition: {size_hint}. "
            "Absolutely no text, no words, no letters anywhere in the image."
        )
    aspect_ratio = "16:9" if label == "background" else "1:1"

    # ── Try Imagen 3 first ─────────────────────────────────────────────────────
    img_bytes = _try_imagen(full_prompt, api_key, aspect_ratio)
    if img_bytes:
        save_path.write_bytes(img_bytes)
        console.print(f"  [green]✓ {label}[/green] (Imagen 3) → {save_path.name}")
        return save_path

    # ── Fallback: Gemini 2.0 Flash ─────────────────────────────────────────────
    try:
        client = genai.Client(api_key=api_key)

        # ── Build multimodal content: moodboard + library refs + style guide ──
        # Signal priority:
        #   1. Client moodboard images  (brief folder)  → highest fidelity
        #   2. Library reference images (references/*)  → craft / category benchmarks
        #   3. Style guide text         (styles/*)      → already in full_prompt
        contents: object = full_prompt
        _ref_type_map = {"logo": "logos", "pattern": "patterns"}

        if label in _ref_type_map:
            label_noun  = "logo" if label == "logo" else "pattern"
            parts       = [types.Part.from_text(text=full_prompt)]
            total_loaded = 0

            # ── Layer 0: style reference images (visual rendering anchor) ───
            # These are user-chosen style refs — ALL logos must match their aesthetic.
            # Highest priority: they define HOW the mark looks (render style, stroke, detail).
            style_refs_loaded = 0
            if label == "logo" and style_ref_images:
                for i, img_path in enumerate(style_ref_images[:2]):  # max 2 style refs
                    try:
                        img_bytes = Path(img_path).read_bytes()
                        ext  = Path(img_path).suffix.lower().lstrip(".")
                        mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext or 'png'}"
                        parts.append(types.Part.from_text(
                            text=(
                                f"⭐ STYLE ANCHOR {i + 1} — MANDATORY RENDERING TEMPLATE\n\n"
                                "CRITICAL INSTRUCTION: Your generated logo MUST look like it was made by "
                                "THE SAME DESIGNER who made this reference image.\n\n"
                                "You MUST copy these properties EXACTLY from this reference:\n"
                                "  1. LINE QUALITY — if the ref uses hand-drawn/organic lines, your output "
                                "     MUST also use hand-drawn/organic lines. If the ref uses clean vectors, "
                                "     your output MUST also use clean vectors. NO EXCEPTIONS.\n"
                                "  2. STROKE WEIGHT — match the exact thickness and weight of strokes.\n"
                                "  3. FILL STYLE — if ref is outline-only, yours must be outline-only. "
                                "     If ref is solid fill, yours must be solid fill.\n"
                                "  4. DETAIL LEVEL — if ref is minimal/simple, yours must be minimal/simple. "
                                "     If ref is detailed/complex, yours must be detailed/complex.\n"
                                "  5. RENDERING MEDIUM — if ref looks hand-drawn/brush/ink, your output MUST "
                                "     look hand-drawn/brush/ink. If ref looks digital/vector, yours MUST too.\n\n"
                                "Your logo's CONCEPT and SUBJECT will be different from this reference, "
                                "but the VISUAL EXECUTION (how it is drawn/rendered) must be identical.\n\n"
                                "⛔ If this reference is hand-drawn/organic, DO NOT generate clean geometric "
                                "vectors. If this reference is clean vectors, DO NOT generate hand-drawn marks."
                            )
                        ))
                        parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
                        style_refs_loaded += 1
                        total_loaded += 1
                    except Exception:
                        pass
                if style_refs_loaded:
                    console.print(f"  [dim]style anchor injected: {style_refs_loaded} ref(s) — rendering technique locked[/dim]")

            # ── Layer 1: client moodboard images ──────────────────────────
            client_refs = list(moodboard_images or [])
            # Skip any paths already used as style refs
            style_ref_set = set(str(p) for p in (style_ref_images or []))
            client_refs = [p for p in client_refs if str(p) not in style_ref_set]
            for i, img_path in enumerate(client_refs[:8]):   # cap at 8 client images
                try:
                    img_bytes = Path(img_path).read_bytes()
                    ext  = Path(img_path).suffix.lower().lstrip(".")
                    mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext or 'png'}"
                    parts.append(types.Part.from_text(
                        text=(
                            f"CLIENT MOODBOARD #{i + 1} — "
                            "This is a direct reference provided by the client. "
                            "Study its aesthetic, colour mood, and visual language carefully. "
                            "Your output should feel like it belongs in the same world."
                        )
                    ))
                    parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
                    total_loaded += 1
                except Exception:
                    pass

            if client_refs:
                n_client = min(len(client_refs), 8)
                console.print(f"  [dim]moodboard refs injected: {n_client} client image(s)[/dim]")

            # ── Layer 2: library reference images ─────────────────────────
            if brief_keywords:
                ref_type_key = _ref_type_map[label]
                lib_images   = _get_reference_images(brief_keywords, ref_type_key)
                _cat_counter: dict = {}
                lib_loaded   = 0

                for ref_path in lib_images:
                    try:
                        img_bytes = ref_path.read_bytes()
                        ext  = ref_path.suffix.lower().lstrip(".")
                        mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext or 'png'}"

                        cat_name  = ref_path.parent.name
                        _cat_counter[cat_name] = _cat_counter.get(cat_name, 0) + 1
                        cat_label = cat_name.replace("_", " ").title()
                        cat_idx   = _cat_counter[cat_name]

                        parts.append(types.Part.from_text(
                            text=(
                                f"LIBRARY REFERENCE {label_noun} #{lib_loaded + 1} "
                                f"[source: {cat_label}, sample {cat_idx}] — "
                                "Study its craft and production quality. "
                                "Do NOT copy — use as a quality benchmark only."
                            )
                        ))
                        parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
                        lib_loaded  += 1
                        total_loaded += 1
                    except Exception:
                        pass

            # ── Closing synthesis instruction ─────────────────────────────
            if total_loaded > 0:
                n_client_loaded = min(len(client_refs), 8) if client_refs else 0
                n_lib_loaded    = total_loaded - n_client_loaded
                summary_parts   = []
                if n_client_loaded:
                    summary_parts.append(f"{n_client_loaded} client moodboard image(s)")
                if n_lib_loaded:
                    cats_seen = list(dict.fromkeys(
                        Path(p).parent.name for p in (lib_images if brief_keywords else [])
                    ))
                    blend_str = " + ".join(
                        c.replace("_", " ").title() for c in cats_seen[:4]
                    ) + (" + …" if len(cats_seen) > 4 else "")
                    summary_parts.append(
                        f"{n_lib_loaded} library reference(s) from: {blend_str}"
                    )
                style_anchor_note = (
                    f"⭐ CRITICAL: Match the STYLE ANCHOR aesthetic exactly — same rendering approach, stroke weight, detail level. "
                    if style_refs_loaded else ""
                )
                parts.append(types.Part.from_text(
                    text=(
                        f"You have studied {total_loaded} visual references: "
                        + " and ".join(summary_parts) + ". "
                        f"Now generate the new {label_noun} described at the top. "
                        + style_anchor_note +
                        "Honour the client moodboard's aesthetic. "
                        "Match the production quality of the library references. "
                        "The result must be entirely original."
                    )
                ))
                contents = parts

        # Model ladder: Nano Banana → Nano Banana Pro → legacy exp
        _gen_models = [
            "gemini-2.5-flash-image",               # Nano Banana — fast, great quality
            "gemini-3-pro-image-preview",           # Nano Banana Pro — best quality
            "gemini-2.0-flash-exp-image-generation", # legacy fallback
        ]
        response = None
        _used_model = _gen_models[0]
        for _gm in _gen_models:
            try:
                response = client.models.generate_content(
                    model=_gm,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"],
                    ),
                )
                _used_model = _gm
                break
            except Exception as _me:
                if any(k in str(_me).lower() for k in ("not found", "permission", "not supported", "invalid")):
                    continue
                raise

        if response is not None:
            for candidate in response.candidates or []:
                for part in candidate.content.parts or []:
                    if hasattr(part, "inline_data") and part.inline_data:
                        data = part.inline_data.data
                        if isinstance(data, str):
                            data = base64.b64decode(data)
                        save_path.write_bytes(data)
                        short = _used_model.replace("gemini-", "").replace("-image-generation", "").replace("-image", "")
                        console.print(f"  [green]✓ {label}[/green] ({short}) → {save_path.name}")
                        return save_path

        console.print(f"  [yellow]⚠ No image returned for {label} (attempt 1)[/yellow]")

    except Exception as e:
        console.print(f"  [yellow]⚠ {label} generation failed ({e}) (attempt 1)[/yellow]")

    # ── Second fallback: simpler prompt for pattern (common failure case) ──────
    if label == "pattern":
        simple_pattern_prompt = (
            "Abstract geometric repeating pattern. "
            "Minimalist shapes, evenly spaced, consistent color. "
            "Square tile. No text, no letters, no words."
        )
        try:
            client2 = genai.Client(api_key=api_key)
            for _gm2 in ["gemini-2.5-flash-image", "gemini-2.0-flash-exp-image-generation"]:
                try:
                    response2 = client2.models.generate_content(
                        model=_gm2,
                        contents=simple_pattern_prompt,
                        config=types.GenerateContentConfig(
                            response_modalities=["IMAGE", "TEXT"],
                        ),
                    )
                    for candidate in response2.candidates or []:
                        for part in candidate.content.parts or []:
                            if hasattr(part, "inline_data") and part.inline_data:
                                data = part.inline_data.data
                                if isinstance(data, str):
                                    data = base64.b64decode(data)
                                save_path.write_bytes(data)
                                console.print(f"  [green]✓ {label}[/green] (simple fallback) → {save_path.name}")
                                return save_path
                    break
                except Exception:
                    continue
        except Exception as e2:
            console.print(f"  [yellow]⚠ {label} simple fallback also failed ({e2})[/yellow]")

    # ── Final fallback: solid-colour placeholder ───────────────────────────────
    _write_placeholder(save_path, label)
    return save_path


def _get_reference_images(brief_keywords: list, ref_type: str = "logos", top_n: int = 15) -> list:
    """
    Find reference images that match brand keywords — with guaranteed cross-category diversity.

    Strategy:
      1. Score every category subdir by keyword overlap with its folder name.
         Categories with ANY match are "relevant categories".
      2. Score each image within those categories by tag overlap + quality.
      3. Guarantee diversity: pick the best image from each relevant category first
         (up to top_n categories), then fill remaining slots from global top scorers.

    This means a brief for "premium fintech" can pull:
      industry_finance_crypto  → real-world fintech logo craft
      style_minimal_geometric  → visual geometry language
      style_elegant_editorial  → premium refinement cues
    ...and the model sees cross-category creative tension, producing richer originals.

    Handles both new relative_path and legacy local_path in index entries.
    """
    try:
        project_root = Path(__file__).parent.parent
        refs_dir = project_root / "references" / ref_type

        if not refs_dir.exists():
            return []

        import json as _json
        kw_set = {k.lower().strip() for k in brief_keywords if k}

        # ── Collect all indexed category dirs + their relevance score ──────
        index_dirs: list = []

        if (refs_dir / "index.json").exists():
            index_dirs.append((refs_dir, 0.0, "root"))

        for sub in sorted(refs_dir.iterdir()):
            if not sub.is_dir() or sub.name.startswith(".") or sub.name.startswith("_"):
                continue
            if not (sub / "index.json").exists():
                continue
            cat_words = set(sub.name.lower().replace("-", "_").split("_"))
            cat_score = len(kw_set & cat_words) * 2.0
            index_dirs.append((sub, cat_score, sub.name))

        if not index_dirs:
            return []

        # Sort: relevant categories first (score > 0), then the rest by name
        index_dirs.sort(key=lambda x: (-x[1], x[2]))

        # ── Score images per category, keep per-category best ──────────────
        # cat_best  → best (score, Path) per category for diversity guarantee
        # all_scored → global pool for fill-in slots
        cat_best: dict   = {}   # cat_name → (score, Path)
        all_scored: list = []   # (score, cat_name, Path)

        for cat_dir, cat_bonus, cat_name in index_dirs:
            try:
                index = _json.loads((cat_dir / "index.json").read_text())
            except Exception:
                continue

            for filename, entry in index.items():
                tags = entry.get("tags", {})
                all_tags: set = set()
                for lst_key in ("style", "industry", "mood", "technique"):
                    for t in tags.get(lst_key, []):
                        all_tags.update(t.lower().split())
                all_tags.add(str(tags.get("form", tags.get("motif", ""))).lower())

                tag_overlap = len(kw_set & all_tags)
                quality     = tags.get("quality", 5)
                score       = cat_bonus + tag_overlap + quality / 10.0

                rel      = entry.get("relative_path", "")
                abs_p    = entry.get("local_path", "")
                resolved = str(project_root / rel) if rel else abs_p

                if resolved and Path(resolved).exists():
                    p = Path(resolved)
                    all_scored.append((score, cat_name, p))
                    # Track best image per category
                    if cat_name not in cat_best or score > cat_best[cat_name][0]:
                        cat_best[cat_name] = (score, p)

        if not all_scored:
            return []

        # ── Tiered slot allocation ─────────────────────────────────────────
        #
        # Tier 1 PRIMARY   — score >= max_score * 0.5  (core industry + style match)
        #   → proportional slots (60% of budget), minimum 2 images each
        # Tier 2 SECONDARY — score >= 1.0 but below primary gate
        #   → 1-2 images each (up to 30% of budget)
        # Tier 3 FILL      — score = 0, but individual image has strong tag overlap
        #   → only fills remaining slots, minimum tag_overlap threshold
        #
        # This ensures e.g. "Coffee brand" → industry_food_beverage gets 5-6 images,
        # style_minimal_geometric gets 3-4, while industry_education_edtech gets 0.

        # cat_score lookup: category-level keyword match score (name → cat_score)
        cat_score_map = {cn: cs for _, cs, cn in index_dirs}

        max_cat_score = max(cat_score_map.values(), default=0.0)

        # Tiers based on CATEGORY keyword overlap (not individual image score)
        # PRIMARY   — folder name matches ≥50% of max category score (at least 2.0)
        # SECONDARY — folder name has any keyword match (cat_score >= 1.0)
        # EXCLUDED  — folder name has zero keyword overlap (cat_score = 0)
        PRIMARY_GATE   = max(2.0, max_cat_score * 0.5)
        SECONDARY_GATE = 1.0
        FILL_MIN_TAGS  = 2     # fill-in images must have ≥2 tag overlaps with brief

        primary_cats   = {n: (s, p) for n, (s, p) in cat_best.items()
                          if cat_score_map.get(n, 0) >= PRIMARY_GATE}
        secondary_cats = {n: (s, p) for n, (s, p) in cat_best.items()
                          if SECONDARY_GATE <= cat_score_map.get(n, 0) < PRIMARY_GATE}

        primary_budget   = round(top_n * 0.60)   # 9 of 15
        secondary_budget = round(top_n * 0.25)   # 3-4 of 15
        # fill_budget is whatever remains

        result:    list = []
        used_cats: set  = set()
        already:   set  = {str(p) for p in result}

        # ── Tier 1: primary categories, proportional slots ────────────────
        if primary_cats:
            total_ps = sum(s for s, _ in primary_cats.values())
            primary_sorted = sorted(primary_cats.items(), key=lambda x: -x[1][0])

            # Proportional allocation, min 2 per primary category
            raw_slots: dict = {}
            for name, (score, _) in primary_sorted:
                raw_slots[name] = max(2, round(primary_budget * score / total_ps))

            # Clamp total to primary_budget (reduce least-relevant first)
            while sum(raw_slots.values()) > primary_budget:
                worst = min(raw_slots, key=lambda n: primary_cats[n][0])
                if raw_slots[worst] > 1:
                    raw_slots[worst] -= 1
                else:
                    break

            # Pick top-N images per primary category (ranked by individual score)
            cat_image_pool: dict = {}
            for score, cat_name, p in all_scored:
                cat_image_pool.setdefault(cat_name, []).append((score, p))
            for cat_name in cat_image_pool:
                cat_image_pool[cat_name].sort(key=lambda x: -x[0])

            for name, slots in raw_slots.items():
                for _, p in (cat_image_pool.get(name, []))[:slots]:
                    if str(p) not in already:
                        result.append(p)
                        already.add(str(p))
                        used_cats.add(name)

        # ── Tier 2: secondary categories, 1-2 images each ────────────────
        secondary_sorted = sorted(secondary_cats.items(), key=lambda x: -x[1][0])
        sec_added = 0
        for name, (score, best_p) in secondary_sorted:
            if sec_added >= secondary_budget or len(result) >= top_n:
                break
            # Up to 2 images per secondary category (1 if budget is tight)
            slots_for_sec = 2 if sec_added + 2 <= secondary_budget else 1
            for _, p in (cat_image_pool.get(name, []))[:slots_for_sec]:
                if str(p) not in already and len(result) < top_n:
                    result.append(p)
                    already.add(str(p))
                    used_cats.add(name)
                    sec_added += 1

        # ── Tier 3: fill remaining slots with high tag-overlap images ─────
        # Only include if image has genuine brief relevance (≥ FILL_MIN_TAGS matches)
        if len(result) < top_n:
            all_scored.sort(key=lambda x: -x[0])
            for score, cat_name, p in all_scored:
                if len(result) >= top_n:
                    break
                if str(p) in already:
                    continue
                # Compute raw tag_overlap for this image (without cat_bonus)
                # score = cat_bonus + tag_overlap + quality/10 → tag_overlap ≈ score - cat_bonus
                cat_bonus_for_img = next(
                    (cs for _, cs, cn in index_dirs if cn == cat_name), 0.0
                )
                approx_tag_overlap = score - cat_bonus_for_img
                if approx_tag_overlap >= FILL_MIN_TAGS:
                    result.append(p)
                    already.add(str(p))
                    used_cats.add(cat_name)

        if result:
            cats_display = ", ".join(sorted(used_cats))
            blend_note   = " [blended]" if len(used_cats) > 1 else ""
            console.print(
                f"  [dim]ref images: {len(result)} from {cats_display}{blend_note}[/dim]"
            )
        return result

    except Exception:
        return []


def _extract_guide_section(content: str, label: str) -> str:
    """
    Extract the relevant section from a style guide for the given label.

    Each guide file may contain both `### For LOGOS:` and `### For PATTERNS:` sections.
    This function strips frontmatter/code fences and returns only the label-relevant section.

    Falls back to the full (cleaned) content if no section marker is found.
    """
    # ── Strip YAML frontmatter (everything between leading `---` / ``` markers) ──
    lines = content.splitlines()
    start_idx = 0

    # Skip opening frontmatter: lines that are YAML keys or --- / ``` fences
    # Frontmatter ends when we see a line starting with `###` or `##` or `#`
    in_frontmatter = True
    for i, line in enumerate(lines):
        stripped = line.strip()
        # YAML frontmatter markers
        if stripped in ("---", "```", "~~~"):
            continue
        # YAML key-value pairs (key: value)
        if in_frontmatter and ":" in stripped and not stripped.startswith("#") and not stripped.startswith("*") and not stripped.startswith("-"):
            continue
        # First real content line
        in_frontmatter = False
        start_idx = i
        break

    body_lines = lines[start_idx:]

    # ── Find the section marker for this label ─────────────────────────────────
    # Guides use: `### For LOGOS:` and `### For PATTERNS:`
    section_header = "for logos:" if label == "logo" else "for patterns:"
    opposite_header = "for patterns:" if label == "logo" else "for logos:"

    section_start: int = -1
    section_end: int = len(body_lines)

    for i, line in enumerate(body_lines):
        low = line.lower().strip()
        if section_header in low and low.startswith("#"):
            section_start = i
        elif section_start >= 0 and opposite_header in low and low.startswith("#"):
            section_end = i
            break

    if section_start >= 0:
        # Found a dedicated section — use it (skip the section header line itself)
        relevant = body_lines[section_start + 1 : section_end]
    else:
        # No section marker — use the whole body (single-type guide)
        relevant = body_lines

    # ── Clean: remove empty lines at start/end, drop stray code fence markers ──
    cleaned = [
        l for l in relevant
        if l.strip() and l.strip() not in ("```", "~~~", "---")
    ]

    return "\n".join(cleaned)


def _get_style_guide(brief_keywords: Optional[list], label: str, top_n: int = 3) -> str:
    """
    Find and blend the top-N most relevant style guides for this label type.

    Fixes vs old implementation:
      - Strips YAML frontmatter and code fences properly
      - Extracts only the label-relevant section (logos vs patterns)
      - Reduces top_n from 5 → 3 to keep blended guide focused
      - Per-guide cap reduced from 25 → 30 lines of actionable content (no meta)

    Returns "" if no guides match.
    """
    if not brief_keywords:
        return ""
    try:
        project_root = Path(__file__).parent.parent
        guide_type = "logos" if label == "logo" else "patterns" if label == "pattern" else None
        if not guide_type:
            return ""

        guides_dir = project_root / "styles" / guide_type
        if not guides_dir.exists():
            return ""

        kw_set = {k.lower().strip() for k in brief_keywords if k}
        scored_guides: list = []   # (score, stem_name, raw_content)

        for guide_path in sorted(guides_dir.glob("*.md")):
            cat_words = set(guide_path.stem.lower().replace("-", "_").replace("_", " ").split())
            score = len(kw_set & cat_words)
            if score > 0:
                try:
                    content = guide_path.read_text(encoding="utf-8")
                    scored_guides.append((score, guide_path.stem, content))
                except Exception:
                    pass

        if not scored_guides:
            return ""

        scored_guides.sort(key=lambda x: -x[0])
        top_guides = scored_guides[:top_n]

        # ── Extract and clean the relevant section from each guide ─────────────
        LINE_CAP = 30   # per-guide line cap (actionable content only)
        parts = []
        for _, stem_name, raw_content in top_guides:
            readable_name = stem_name.replace("_", " ").title()
            section = _extract_guide_section(raw_content, label)
            section_lines = section.splitlines()[:LINE_CAP]
            if section_lines:
                parts.append(f"### {readable_name}\n" + "\n".join(section_lines))

        if not parts:
            return ""

        blend_names = ", ".join(g[1] for g in top_guides)
        console.print(f"  [dim]style guides ({label}): {blend_names}[/dim]")

        if len(parts) == 1:
            return parts[0]

        return (
            "## STYLE REFERENCE\n"
            f"_(from: {blend_names})_\n\n"
            + "\n\n---\n\n".join(parts)
        )

    except Exception:
        return ""


def _write_placeholder(save_path: Path, label: str) -> None:
    """Create a minimal placeholder PNG using Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont

        w, h = (1536, 864) if label == "background" else (800, 800)
        colors = {"background": "#1a1a2e", "logo": "#f0f0f0", "pattern": "#2d2d44"}
        bg = colors.get(label, "#222222")

        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)

        # Simple centered label
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
        except Exception:
            font = ImageFont.load_default()

        text = f"[{label}]"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((w - tw) // 2, (h - th) // 2), text, fill="#888888", font=font)
        img.save(str(save_path), format="PNG")

    except Exception:
        save_path.write_bytes(b"")


def _create_logo_variants(logo_path: Path, asset_dir: Path) -> dict:
    """
    Derive white / black / transparent logo variants from the generated logo PNG.

    Steps:
      1. Remove near-white background (brightness ≥ 240 → transparent) → logo_transparent.png
      2. Colorize all remaining opaque pixels white, composite on BLACK bg → logo_white.png
      3. Colorize all remaining opaque pixels near-black, composite on WHITE bg → logo_black.png

    Returns {"logo_transparent": Path, "logo_white": Path, "logo_black": Path}
    or {} on any failure.
    """
    try:
        from PIL import Image as _PILImage

        img = _PILImage.open(logo_path).convert("RGBA")
        arr = np.array(img).astype(np.float32)

        # Step 1: Remove white background
        br = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        scale = np.clip((240 - br) / 30.0, 0.0, 1.0)
        arr[:, :, 3] = (arr[:, :, 3] * scale).clip(0, 255)
        transparent = _PILImage.fromarray(arr.astype(np.uint8), "RGBA")

        # Step 2: White logo on BLACK background (visible in Telegram)
        white_arr = arr.copy()
        white_arr[:, :, :3] = 255
        white_rgba = _PILImage.fromarray(white_arr.astype(np.uint8), "RGBA")
        black_canvas = _PILImage.new("RGB", white_rgba.size, (0, 0, 0))
        black_canvas.paste(white_rgba, mask=white_rgba.split()[3])
        white_logo = black_canvas

        # Step 3: Black logo on WHITE background
        black_arr = arr.copy()
        black_arr[:, :, 0] = 20
        black_arr[:, :, 1] = 20
        black_arr[:, :, 2] = 20
        black_rgba = _PILImage.fromarray(black_arr.astype(np.uint8), "RGBA")
        white_canvas = _PILImage.new("RGB", black_rgba.size, (255, 255, 255))
        white_canvas.paste(black_rgba, mask=black_rgba.split()[3])
        black_logo = white_canvas

        trans_path = asset_dir / "logo_transparent.png"
        white_path = asset_dir / "logo_white.png"
        black_path = asset_dir / "logo_black.png"

        transparent.save(str(trans_path), format="PNG")
        white_logo.save(str(white_path), format="PNG")
        black_logo.save(str(black_path), format="PNG")

        console.print("  [dim]  logo variants → transparent / white-on-black / black-on-white[/dim]")
        
        return {
            "logo_transparent": trans_path,
            "logo_white":       white_path,
            "logo_black":       black_path,
        }
    except Exception as e:
        console.print(f"  [yellow]⚠ Logo variant creation failed: {e}[/yellow]")
        return {}


def _slugify(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:30]
