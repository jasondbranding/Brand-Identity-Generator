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
from typing import List, Optional

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


def generate_all_assets(
    directions: list,
    output_dir: Path,
    brief_keywords: Optional[list] = None,
    brand_name: str = "",
    brief_tagline: str = "",
    brief_ad_slogan: str = "",
    brief_announcement_copy: str = "",
    brief_text: str = "",
) -> dict:
    """
    Generate bg + logo + pattern for every direction.

    Args:
        directions:              List of BrandDirection objects
        output_dir:              Directory to save assets
        brief_keywords:          Optional brand keywords for reference image matching
        brand_name:              Actual brand name from the brief (e.g. "Whales Market")
        brief_tagline:           Pre-written tagline from brief (overrides AI-generated)
        brief_ad_slogan:         Pre-written ad slogan from brief (overrides AI-generated)
        brief_announcement_copy: Pre-written announcement copy from brief (overrides AI-generated)
        brief_text:              Full raw brief text — used for copy fallback generation

    Returns:
        Dict mapping option_number → DirectionAssets
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    for direction in directions:
        console.print(
            f"\n[bold cyan]→ Generating assets for Option {direction.option_number}: "
            f"{direction.direction_name}[/bold cyan]"
        )
        assets = _generate_direction_assets(
            direction, output_dir,
            brief_keywords=brief_keywords,
            brand_name=brand_name,
            brief_tagline=brief_tagline,
            brief_ad_slogan=brief_ad_slogan,
            brief_announcement_copy=brief_announcement_copy,
            brief_text=brief_text,
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


def _generate_direction_assets(
    direction: BrandDirection,
    output_dir: Path,
    brief_keywords: Optional[list] = None,
    brand_name: str = "",
    brief_tagline: str = "",
    brief_ad_slogan: str = "",
    brief_announcement_copy: str = "",
    brief_text: str = "",
) -> DirectionAssets:
    slug = _slugify(direction.direction_name)
    asset_dir = output_dir / f"option_{direction.option_number}_{slug}"
    asset_dir.mkdir(parents=True, exist_ok=True)

    # ── Resolve effective tags once for this direction ─────────────────────
    # Combines user-provided keywords + AI-extracted taxonomy tags from brief+direction
    # Used for both ref image matching AND style guide matching
    effective_keywords = _resolve_direction_tags(brief_text, direction, brief_keywords)

    background = _generate_image(
        prompt=direction.background_prompt,
        save_path=asset_dir / "background.png",
        label="background",
        size_hint="wide landscape, 16:9 aspect ratio",
    )

    logo = _generate_image(
        prompt=direction.logo_prompt,
        save_path=asset_dir / "logo.png",
        label="logo",
        size_hint="square format, centered mark, generous white space around it",
        brief_keywords=effective_keywords,
    )

    pattern = _generate_image(
        prompt=direction.pattern_prompt,
        save_path=asset_dir / "pattern.png",
        label="pattern",
        size_hint="square tile, seamlessly repeatable",
        brief_keywords=effective_keywords,
    )

    # Create white / black / transparent logo variants for compositor use
    variants: dict = {}
    if logo and logo.exists() and logo.stat().st_size > 100:
        variants = _create_logo_variants(logo, asset_dir)

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
    )


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
) -> Optional[Path]:
    """
    Try Imagen 3 first, then Gemini 2.0 Flash as fallback.
    For logos/patterns: injects relevant style guide from styles/ if available.
    For logos: if reference images are available, use multi-modal style inspiration.
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
        full_prompt = (
            f"{prompt}{style_guide_block}\n\n"
            "Technical requirements:\n"
            "- Single iconic mark/symbol centered on pure white background\n"
            "- High contrast, clean crisp edges, professional vector quality\n"
            "- Suitable for brand identity at any scale (favicon to billboard)\n"
            "- Square format, generous padding (20%+ whitespace all sides)\n"
            "- Absolutely no text, words, letters, or typography anywhere in the image\n"
            "- Clean vector-like rendering, minimal complexity, bold and memorable\n"
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

        # For logos and patterns: inject reference images as visual quality anchors
        # Combined with the style guide text already in full_prompt → uses BOTH sources
        contents: object = full_prompt
        _ref_type_map = {"logo": "logos", "pattern": "patterns"}
        if label in _ref_type_map and brief_keywords:
            ref_type_key = _ref_type_map[label]
            ref_images = _get_reference_images(brief_keywords, ref_type_key)   # up to 15
            if ref_images:
                label_noun = "logo" if label == "logo" else "pattern"
                parts = [types.Part.from_text(text=full_prompt)]

                # Group refs by category so model understands cross-category blend intent
                # e.g. "From industry_finance_crypto (#1/#2) … From style_minimal_geometric (#3/#4)"
                _cat_counter: dict = {}   # cat_name → count within that cat
                loaded = 0
                for ref_path in ref_images:
                    try:
                        img_bytes = ref_path.read_bytes()
                        ext  = ref_path.suffix.lower().lstrip(".")
                        mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext or 'png'}"

                        cat_name = ref_path.parent.name
                        _cat_counter[cat_name] = _cat_counter.get(cat_name, 0) + 1
                        cat_label = cat_name.replace("_", " ").title()
                        cat_idx   = _cat_counter[cat_name]

                        parts.append(types.Part.from_text(
                            text=(
                                f"Reference {label_noun} #{loaded + 1} "
                                f"[source: {cat_label}, sample {cat_idx}] — "
                                "Study its craft, production quality, and aesthetic approach. "
                                "Do NOT copy — use as inspiration only."
                            )
                        ))
                        parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
                        loaded += 1
                    except Exception:
                        pass

                if loaded > 0:
                    cats_seen = list(dict.fromkeys(p.parent.name for p in ref_images))
                    blend_summary = " + ".join(
                        c.replace("_", " ").title() for c in cats_seen[:4]
                    ) + (" + …" if len(cats_seen) > 4 else "")
                    parts.append(types.Part.from_text(
                        text=(
                            f"You have studied {loaded} reference {label_noun}s "
                            f"drawn from {len(cats_seen)} visual categories: {blend_summary}. "
                            f"Now generate the new {label_noun} described at the top. "
                            "Synthesise the craft level and aesthetic sensibility across ALL references. "
                            "The result must be entirely original — not a copy of any single reference."
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

        # ── Build result with cross-category diversity guarantee ───────────
        # Step 1: one best image from each relevant category (score > 0), up to top_n
        relevant_cats = [
            (score, name) for name, (score, _) in cat_best.items() if score > 0
        ]
        relevant_cats.sort(key=lambda x: -x[0])

        result: list   = []
        used_cats: set = set()

        for _, cat_name in relevant_cats[:top_n]:
            _, p = cat_best[cat_name]
            result.append(p)
            used_cats.add(cat_name)
            if len(result) >= top_n:
                break

        # Step 2: fill remaining slots from global top scorers (any category)
        if len(result) < top_n:
            all_scored.sort(key=lambda x: -x[0])
            already = {str(p) for p in result}
            for score, cat_name, p in all_scored:
                if str(p) not in already:
                    result.append(p)
                    already.add(str(p))
                    used_cats.add(cat_name)
                if len(result) >= top_n:
                    break

        if result:
            cats_display = ", ".join(sorted(used_cats))
            blend_note   = " [blended]" if len(used_cats) > 1 else ""
            console.print(
                f"  [dim]ref images: {len(result)} from {cats_display}{blend_note}[/dim]"
            )
        return result

    except Exception:
        return []


def _get_style_guide(brief_keywords: Optional[list], label: str, top_n: int = 5) -> str:
    """
    Find and COMBINE the top-N most relevant style guides for this label type.

    Instead of returning a single best-match guide, blends multiple relevant
    guides so the model works at the intersection of several visual languages.

    Example: "premium fintech minimal" could blend:
      industry_finance_crypto  → domain-specific rules (precision, trust)
      style_minimal_geometric  → formal geometry constraints
      style_elegant_editorial  → refinement / luxury cues
    → Combined, the model has richer, more specific constraints than any single guide.

    Each contributing guide is capped at 25 lines to prevent prompt bloat.
    Total output is capped at ~100 lines.
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
        scored_guides: list = []   # (score, stem_name, content)

        for guide_path in sorted(guides_dir.glob("*.md")):
            cat_words = set(guide_path.stem.lower().replace("_", " ").split())
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

        if len(top_guides) == 1:
            # Single match — return as-is (no blending needed)
            return top_guides[0][2]

        # ── Blend multiple guides ──────────────────────────────────────────
        # Cap each guide to 25 actionable lines (skip YAML frontmatter)
        LINE_CAP = 25
        parts = []
        for _, stem_name, content in top_guides:
            readable_name = stem_name.replace("_", " ").title()
            lines = [
                l for l in content.splitlines()
                if not l.startswith("---") and l.strip()
            ][:LINE_CAP]
            parts.append(
                f"### {readable_name}\n" + "\n".join(lines)
            )

        blend_names = ", ".join(g[1] for g in top_guides)
        console.print(f"  [dim]style guides blended: {blend_names}[/dim]")

        return (
            "## BLENDED STYLE REFERENCE\n"
            f"_(synthesised from: {blend_names})_\n\n"
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
      2. Colorize all remaining opaque pixels white                     → logo_white.png
      3. Colorize all remaining opaque pixels near-black                → logo_black.png

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

        # Step 2: White logo
        white_arr = arr.copy()
        white_arr[:, :, :3] = 255
        white_logo = _PILImage.fromarray(white_arr.astype(np.uint8), "RGBA")

        # Step 3: Black logo
        black_arr = arr.copy()
        black_arr[:, :, 0] = 20
        black_arr[:, :, 1] = 20
        black_arr[:, :, 2] = 20
        black_logo = _PILImage.fromarray(black_arr.astype(np.uint8), "RGBA")

        trans_path = asset_dir / "logo_transparent.png"
        white_path = asset_dir / "logo_white.png"
        black_path = asset_dir / "logo_black.png"

        transparent.save(str(trans_path), format="PNG")
        white_logo.save(str(white_path), format="PNG")
        black_logo.save(str(black_path), format="PNG")

        console.print("  [dim]  logo variants → transparent / white / black[/dim]")
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
