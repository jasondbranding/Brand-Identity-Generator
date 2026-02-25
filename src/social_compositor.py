"""
Social Post Compositor — generates 3 types of 16:9 social posts for X (Twitter)
using Gemini Nano Banana image editing, then assembles them into a social board.

Post types per direction:
  collab_post        — brand × partner collab layout (our logo + partner placeholder)
  announcement_post  — small logo top center, announcement copy in the middle
  ads_post           — large ad slogan hero text + small brand logo corner

Output layout:
  outputs/<direction>/social/collab_post.png
  outputs/<direction>/social/announcement_post.png
  outputs/<direction>/social/ads_post.png
  outputs/<direction>/social_board.png   ← all 3 arranged in 1 board
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Optional, Tuple

from rich.console import Console

from google import genai
from google.genai import types

console = Console()


# ── Copy fallback generator ────────────────────────────────────────────────────

def _generate_copy_from_brief(
    brand_name: str,
    brief_text: str,
    direction_name: str,
    direction_rationale: str,
    direction_style: str,
    primary_hex: str,
) -> Tuple[str, str, str]:
    """
    Call Gemini (text-only) to generate tagline / ad_slogan / announcement_copy
    grounded in the full brief context + this direction's concept.

    Returns (tagline, ad_slogan, announcement_copy) — all non-empty strings.
    Falls back to safe defaults on any error.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return (
            f"{brand_name} — built different.",
            "Built different.",
            f"{brand_name} is here. Something worth paying attention to.",
        )

    prompt = f"""You are a senior copywriter. Generate 3 copy assets for a brand.

BRAND: {brand_name}
DIRECTION: {direction_name}
RATIONALE: {direction_rationale}
VISUAL STYLE: {direction_style}
PRIMARY COLOR: {primary_hex}

BRIEF CONTEXT:
{brief_text.strip()[:1500]}

Output ONLY valid JSON with these 3 keys — no explanation, no markdown:
{{
  "tagline": "5–10 words. Memorable brand promise that fits this direction's personality.",
  "ad_slogan": "3–6 words. Punchy, bold, could be a billboard. Imperative or evocative.",
  "announcement_copy": "10–18 words. Sounds like a real tweet announcing this brand — exciting, human, specific."
}}"""

    try:
        client = genai.Client(api_key=api_key)
        for model in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash"]:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.8,
                        max_output_tokens=256,
                    ),
                )
                raw = response.text.strip()
                # Strip markdown code fences if present
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                data = json.loads(raw.strip())
                tagline           = str(data.get("tagline", "")).strip()
                ad_slogan         = str(data.get("ad_slogan", "")).strip()
                announcement_copy = str(data.get("announcement_copy", "")).strip()
                if tagline and ad_slogan and announcement_copy:
                    console.print(
                        f"  [dim]copy generated via {model} for '{direction_name}'[/dim]"
                    )
                    return tagline, ad_slogan, announcement_copy
                break
            except Exception as _me:
                if any(k in str(_me).lower() for k in ("not found", "invalid")):
                    continue
                raise
    except Exception as e:
        console.print(f"  [yellow]⚠ Copy generation failed ({e}) — using defaults[/yellow]")

    # Safe defaults
    return (
        f"{brand_name} — {direction_name.lower()}.",
        "Make it matter.",
        f"{brand_name} is live. A new direction worth following.",
    )

# ── Canvas spec ───────────────────────────────────────────────────────────────
POST_W, POST_H = 1920, 1080   # 16:9 at 1080p

# ── Model ladder (same as mockup_compositor) ──────────────────────────────────
MODELS = [
    "gemini-3-pro-image-preview",              # Nano Banana Pro — best editing
    "gemini-2.5-flash-image",                  # Nano Banana — fast fallback
    "gemini-2.0-flash-preview-image-generation",
    "gemini-2.0-flash-exp-image-generation",
]

# ── Post specs ─────────────────────────────────────────────────────────────────

SOCIAL_SPECS = {
    "collab_post": {
        "label": "Collab Post",
        "description": "Brand collaboration announcement — our brand × partner brand, equal split",
        "layout": {
            "type": "split_horizontal",
            "left_zone": "our brand — logo centered on brand primary-color background (left 50%)",
            "center_zone": "thin 2px vertical separator line + '×' symbol centered vertically in neutral/white",
            "right_zone": "partner brand — minimal geometric placeholder logo centered on neutral light background (right 50%)",
        },
        "text_overlay": None,
        "constraints": [
            "strict 16:9 ratio, 1920×1080px",
            "exact equal split — left and right halves same width",
            "our brand logo: use the provided logo asset, centered, do not alter or distort",
            "partner logo: generate a clean minimal geometric mark as placeholder",
            "× symbol centered between the two halves, high contrast, readable",
            "no copy text anywhere — purely visual",
            "professional social media quality",
        ],
    },
    "announcement_post": {
        "label": "Announcement Post",
        "description": "Feature/update announcement — headline + subtext + logo, editorial layout",
        "layout": {
            "type": "feature_announcement",
            "background": "brand primary color as solid background, or dark background with subtle brand texture",
            "top_right": "brand logo — small, top-right corner, ~60px tall max",
            "label_zone": "small label text top-left: 'New in [brand name]' or 'Introducing' — small caps, accent color",
            "headline_zone": "feature headline — LARGE, left-aligned, 60-70% of canvas width, bold weight, high contrast",
            "subtext_zone": "1-line subtext below headline — smaller font, secondary/muted tone, max 8 words",
        },
        "text_overlay": "announcement_copy",
        "constraints": [
            "strict 16:9 ratio, 1920×1080px",
            "brand logo: top-right corner, small, do not alter",
            "headline is the hero — at least 3× larger than subtext",
            "label ('New in X') is visually distinct — small caps, accent color, above headline",
            "subtext below headline — 1 line only, restrained",
            "left-aligned layout feels editorial and modern",
            "strong contrast: text clearly readable against background",
            "no other decorative elements",
        ],
    },
    "ads_post": {
        "label": "Ads Post",
        "description": "Split ad — brand visual (pattern/background) left, ad slogan + logo right",
        "layout": {
            "type": "split_visual_copy",
            "left_zone": "brand visual — use the provided pattern/background asset, fills left 55% of canvas",
            "right_zone": "copy panel — solid brand color (primary or dark), fills right 45% of canvas",
            "right_top": "vertical whitespace",
            "right_center": "ad slogan — LARGE, bold, left-aligned within right panel, 2-3 lines max",
            "right_bottom": "brand logo — small, bottom-left of right panel",
        },
        "text_overlay": "ad_slogan",
        "constraints": [
            "strict 16:9 ratio, 1920×1080px",
            "left 55%: filled with the provided brand pattern or background asset — do not add text here",
            "right 45%: solid color panel (brand primary or complementary dark tone)",
            "slogan: bold, large, white or high-contrast text — dominant element on right panel",
            "logo: bottom of right panel, small, do not alter",
            "clean hard vertical edge between visual and copy panel",
            "no additional text or decorative elements",
            "ad-campaign quality — punchy and modern",
        ],
    },
}


# ── Prompt builder ─────────────────────────────────────────────────────────────

def build_social_prompt(
    post_type: str,
    brand_name: str,
    copy_text: str,
    primary_hex: str,
    secondary_hex: str,
    accent_hex: str,
    direction_name: str,
    graphic_style: str,
    subtext: str = "",
) -> str:
    """Build a JSON-structured IMAGE_GEN_V1 prompt for a social post."""
    spec = SOCIAL_SPECS[post_type]

    copy_block: dict = {}
    if post_type == "announcement_post":
        copy_block = {
            "label": f"New in {brand_name}",
            "headline": copy_text or "",
            "subtext": subtext or "",
        }
    elif post_type == "ads_post":
        copy_block = {"slogan": copy_text or ""}
    # collab_post: no copy

    prompt_dict = {
        "IMAGE_GEN_V1": {
            "task": "image_create",
            "format": "social_post_16_9",
            "canvas": {"width": POST_W, "height": POST_H, "ratio": "16:9"},
            "post_type": post_type,
            "goal": spec["description"],
            "brand": {
                "name": brand_name,
                "direction": direction_name,
                "primary_color": primary_hex,
                "secondary_color": secondary_hex,
                "accent_color": accent_hex,
                "graphic_style": graphic_style,
            },
            "layout": spec["layout"],
            "copy": copy_block if copy_block else None,
            "constraints": spec["constraints"],
            "output": {
                "resolution": "1920x1080",
                "format": "png",
                "quality": "social media ready, high production value",
            },
        }
    }
    return json.dumps(prompt_dict, indent=2, ensure_ascii=False)


# ── Single post generation ─────────────────────────────────────────────────────

def _generate_one_post(
    post_type: str,
    brand_name: str,
    copy_text: str,
    primary_hex: str,
    secondary_hex: str,
    accent_hex: str,
    direction_name: str,
    graphic_style: str,
    logo_path: Optional[Path],
    save_path: Path,
    subtext: str = "",
    pattern_path: Optional[Path] = None,
) -> Optional[Path]:
    """Call Gemini with logo/pattern images + structured prompt to generate a social post."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print(f"  [yellow]⚠ GEMINI_API_KEY not set — skipping {post_type}[/yellow]")
        return None

    prompt_str = build_social_prompt(
        post_type=post_type,
        brand_name=brand_name,
        copy_text=copy_text,
        primary_hex=primary_hex,
        secondary_hex=secondary_hex,
        accent_hex=accent_hex,
        direction_name=direction_name,
        graphic_style=graphic_style,
        subtext=subtext,
    )

    client = genai.Client(api_key=api_key)
    spec = SOCIAL_SPECS[post_type]
    post_label = spec["label"]

    # Build content parts — inject visual assets + prompt
    parts = []

    # 1. Brand logo (all post types)
    if logo_path and logo_path.exists() and logo_path.stat().st_size > 100:
        try:
            img_bytes = logo_path.read_bytes()
            ext = logo_path.suffix.lower().lstrip(".")
            mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else 'png'}"
            parts.append(types.Part.from_text(
                text="BRAND LOGO — place this logo in the layout as specified (do not alter or distort):"
            ))
            parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
        except Exception as e:
            console.print(f"  [yellow]⚠ Could not load logo for {post_type}: {e}[/yellow]")

    # 2. Brand pattern/background — injected for ads_post as the visual side
    if post_type == "ads_post" and pattern_path and pattern_path.exists() and pattern_path.stat().st_size > 100:
        try:
            pat_bytes = pattern_path.read_bytes()
            ext = pattern_path.suffix.lower().lstrip(".")
            mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else 'png'}"
            parts.append(types.Part.from_text(
                text=(
                    "BRAND VISUAL ASSET — use this pattern/background as the visual panel "
                    "on the LEFT side of the split layout (left 55%). Do not add any text to this side:"
                )
            ))
            parts.append(types.Part.from_bytes(data=pat_bytes, mime_type=mime))
        except Exception as e:
            console.print(f"  [yellow]⚠ Could not load pattern for ads_post: {e}[/yellow]")

    parts.append(types.Part.from_text(text=prompt_str))
    parts.append(types.Part.from_text(
        text=f"Generate the {post_label} now. Output only the final 16:9 image at 1920×1080px."
    ))

    contents = parts if len(parts) > 1 else prompt_str

    for model in MODELS:
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )
            for candidate in response.candidates or []:
                for part in candidate.content.parts or []:
                    if hasattr(part, "inline_data") and part.inline_data:
                        data = part.inline_data.data
                        if isinstance(data, str):
                            data = base64.b64decode(data)
                        save_path.parent.mkdir(parents=True, exist_ok=True)
                        save_path.write_bytes(data)
                        short = model.replace("gemini-", "").replace("-image-generation", "").replace("-image", "")
                        console.print(f"  [green]✓ {post_label}[/green] ({short}) → {save_path.name}")
                        return save_path
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in ("not found", "permission", "not supported", "invalid")):
                continue
            # Rate limit / content errors — surface immediately
            raise

    console.print(f"  [yellow]⚠ {post_label} — all models failed[/yellow]")
    return None


# ── Board builder ──────────────────────────────────────────────────────────────

def _build_social_board(post_paths: dict, board_path: Path, brand_name: str) -> Optional[Path]:
    """
    Assemble 3 social post PNGs into a single horizontal board image.

    Layout:
      ┌──────────────────────────────────────────────────────────────────┐
      │  SOCIAL POSTS — Brand Name                                       │
      │  [collab_post]    [announcement_post]    [ads_post]              │
      │  Collab Post       Announcement Post      Ads Post               │
      └──────────────────────────────────────────────────────────────────┘
    """
    try:
        from PIL import Image, ImageDraw, ImageFont

        THUMB_W = 640
        THUMB_H = 360   # 16:9
        PADDING = 48
        GAP = 32
        LABEL_H = 40
        HEADER_H = 72

        total_w = PADDING * 2 + THUMB_W * 3 + GAP * 2
        total_h = HEADER_H + PADDING + THUMB_H + LABEL_H + PADDING

        board = Image.new("RGB", (total_w, total_h), "#111111")
        draw = ImageDraw.Draw(board)

        # ── Header ─────────────────────────────────────────────────────────────
        try:
            font_header = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
            font_label  = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
        except Exception:
            font_header = ImageFont.load_default()
            font_label  = ImageFont.load_default()

        header_text = f"SOCIAL POSTS — {brand_name.upper()}"
        draw.text((PADDING, HEADER_H // 2 - 14), header_text, fill="#ffffff", font=font_header)

        # ── Thumbnails ─────────────────────────────────────────────────────────
        ordered = ["collab_post", "announcement_post", "ads_post"]
        for i, key in enumerate(ordered):
            x = PADDING + i * (THUMB_W + GAP)
            y = HEADER_H + PADDING

            path = post_paths.get(key)
            if path and Path(path).exists() and Path(path).stat().st_size > 100:
                try:
                    thumb = Image.open(str(path)).convert("RGB").resize(
                        (THUMB_W, THUMB_H), Image.LANCZOS
                    )
                    board.paste(thumb, (x, y))
                except Exception:
                    draw.rectangle([x, y, x + THUMB_W, y + THUMB_H], fill="#333333")
                    draw.text((x + THUMB_W // 2 - 30, y + THUMB_H // 2), "[error]", fill="#888888", font=font_label)
            else:
                # Placeholder slot
                draw.rectangle([x, y, x + THUMB_W, y + THUMB_H], fill="#222222")
                draw.text((x + THUMB_W // 2 - 40, y + THUMB_H // 2 - 10), "[pending]", fill="#555555", font=font_label)

            # Label below thumbnail
            label = SOCIAL_SPECS.get(key, {}).get("label", key)
            lx = x + THUMB_W // 2
            ly = y + THUMB_H + 10
            bbox = draw.textbbox((0, 0), label, font=font_label)
            lw = bbox[2] - bbox[0]
            draw.text((lx - lw // 2, ly), label, fill="#aaaaaa", font=font_label)

        board_path.parent.mkdir(parents=True, exist_ok=True)
        board.save(str(board_path), format="PNG")
        console.print(f"  [green]✓ Social board[/green] → {board_path.name}")
        return board_path

    except Exception as e:
        console.print(f"  [yellow]⚠ Social board assembly failed: {e}[/yellow]")
        return None


# ── Public entry point ─────────────────────────────────────────────────────────

def generate_social_posts(assets_map: dict) -> dict:
    """
    Generate 3 social posts + board for every direction in assets_map.

    Args:
        assets_map: Dict[option_number → DirectionAssets]  (from generate_all_assets)

    Returns:
        Dict[option_number → {"collab_post": Path, "announcement_post": Path,
                               "ads_post": Path, "board": Path}]
    """
    results = {}

    for num, assets in assets_map.items():
        direction = assets.direction
        brand_name = assets.brand_name or direction.direction_name

        console.print(
            f"\n[bold cyan]→ Social posts for Option {direction.option_number}: "
            f"{direction.direction_name}[/bold cyan]"
        )

        # Resolve save directory
        from .generator import _slugify
        slug = _slugify(direction.direction_name)
        social_dir = assets.background.parent / "social" if assets.background else (
            Path(f"outputs/option_{direction.option_number}_{slug}/social")
        )
        social_dir.mkdir(parents=True, exist_ok=True)

        # Extract palette
        primary_hex   = next((c.hex for c in direction.colors if c.role == "primary"),   "#333333")
        secondary_hex = next((c.hex for c in direction.colors if c.role == "secondary"), "#666666")
        accent_hex    = next((c.hex for c in direction.colors if c.role == "accent"),    "#999999")

        # ── Resolve copy — 3-level priority ──────────────────────────────────
        # 1. Brief copy (locked by client) — verbatim, same across all directions
        # 2. AI-generated copy from BrandDirection (direction-specific, by Claude)
        # 3. Fallback: generate fresh from brief context via Gemini text call
        _brief_tagline      = getattr(assets, "brief_tagline", "")
        _brief_slogan       = getattr(assets, "brief_ad_slogan", "")
        _brief_announcement = getattr(assets, "brief_announcement_copy", "")

        _dir_tagline      = getattr(direction, "tagline", "")
        _dir_slogan       = getattr(direction, "ad_slogan", "")
        _dir_announcement = getattr(direction, "announcement_copy", "")

        # Resolve each field
        _tagline      = _brief_tagline      or _dir_tagline
        _slogan       = _brief_slogan       or _dir_slogan
        _announcement = _brief_announcement or _dir_announcement

        # Level 3 fallback: if any field still empty, generate from brief context
        if not (_tagline and _slogan and _announcement):
            console.print(f"  [dim]copy fields missing — generating from brief context...[/dim]")
            brief_text  = getattr(assets, "_brief_text", "")          # set below if available
            _gen_tag, _gen_slo, _gen_ann = _generate_copy_from_brief(
                brand_name=brand_name,
                brief_text=brief_text,
                direction_name=direction.direction_name,
                direction_rationale=getattr(direction, "rationale", ""),
                direction_style=getattr(direction, "graphic_style", ""),
                primary_hex=primary_hex,
            )
            _tagline      = _tagline      or _gen_tag
            _slogan       = _slogan       or _gen_slo
            _announcement = _announcement or _gen_ann

        # Log copy source
        if _brief_tagline:
            console.print(f"  [dim]tagline: brief (locked) → \"{_tagline}\"[/dim]")
        elif _dir_tagline:
            console.print(f"  [dim]tagline: AI direction → \"{_tagline}\"[/dim]")
        else:
            console.print(f"  [dim]tagline: generated → \"{_tagline}\"[/dim]")

        if _brief_slogan:
            console.print(f"  [dim]slogan: brief (locked) → \"{_slogan}\"[/dim]")
        elif _dir_slogan:
            console.print(f"  [dim]slogan: AI direction → \"{_slogan}\"[/dim]")
        else:
            console.print(f"  [dim]slogan: generated → \"{_slogan}\"[/dim]")

        if _brief_announcement:
            console.print(f"  [dim]announcement: brief (locked)[/dim]")
        elif _dir_announcement:
            console.print(f"  [dim]announcement: AI direction[/dim]")
        else:
            console.print(f"  [dim]announcement: generated[/dim]")

        copy_map = {
            "collab_post":        "",             # no copy for collab — visual only
            "announcement_post":  _announcement,  # headline (large)
            "ads_post":           _slogan,         # slogan on right panel
        }
        # Subtext for announcement_post = tagline (1 short line below headline)
        subtext_map = {
            "announcement_post": _tagline,
        }

        # Logo to use (prefer transparent, fall back to regular logo)
        logo_path = assets.logo_transparent or assets.logo

        # Pattern/background asset for ads_post visual panel
        pattern_path = assets.pattern or assets.background

        post_paths: dict = {}
        for post_type in ["collab_post", "announcement_post", "ads_post"]:
            save_path = social_dir / f"{post_type}.png"
            result = _generate_one_post(
                post_type=post_type,
                brand_name=brand_name,
                copy_text=copy_map[post_type],
                primary_hex=primary_hex,
                secondary_hex=secondary_hex,
                accent_hex=accent_hex,
                direction_name=direction.direction_name,
                graphic_style=direction.graphic_style,
                logo_path=logo_path,
                save_path=save_path,
                subtext=subtext_map.get(post_type, ""),
                pattern_path=pattern_path if post_type == "ads_post" else None,
            )
            post_paths[post_type] = result

        # Build board
        board_path = social_dir.parent / "social_board.png"
        _build_social_board(post_paths, board_path, brand_name)
        post_paths["board"] = board_path

        results[num] = post_paths
        console.print(f"  [dim]Social posts saved → {social_dir}[/dim]")

    return results
