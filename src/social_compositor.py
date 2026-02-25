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
from typing import Optional

from rich.console import Console

from google import genai
from google.genai import types

console = Console()

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
        "description": "Brand collaboration announcement — our brand × partner brand",
        "layout": {
            "type": "split_horizontal",
            "left_zone": "our brand — logo centered on brand-colored background (left half)",
            "center_zone": "thin vertical separator line + '×' symbol in neutral color",
            "right_zone": "partner brand placeholder — minimal geometric mark on neutral background (right half)",
        },
        "text_overlay": None,
        "constraints": [
            "strict 16:9 ratio, 1920×1080px",
            "clean split layout, both halves equal width",
            "our brand logo stays exactly as provided — do not alter it",
            "right side: generate a minimal geometric placeholder logo for the partner brand",
            "no additional text, no copy — purely visual",
            "high production quality, suitable for social media",
        ],
    },
    "announcement_post": {
        "label": "Announcement Post",
        "description": "Brand announcement — small logo top + announcement copy center",
        "layout": {
            "type": "centered_text",
            "top_zone": "brand logo, small, centered horizontally, ~12% of height from top",
            "center_zone": "announcement copy text, large legible font, centered",
            "background": "use brand primary color as background, or background asset as subtle texture",
        },
        "text_overlay": "announcement_copy",   # field from BrandDirection
        "constraints": [
            "strict 16:9 ratio, 1920×1080px",
            "logo must be small (max 80px tall) centered at top",
            "announcement text is the hero — large, centered, high contrast against background",
            "use brand typography style (modern sans-serif or serif per direction)",
            "no other decorative elements — clean and minimal",
            "text must be clearly readable, strong contrast ratio",
        ],
    },
    "ads_post": {
        "label": "Ads Post",
        "description": "Brand advertisement — large slogan hero + small logo corner",
        "layout": {
            "type": "slogan_hero",
            "main_zone": "large bold slogan text, dominant, center or center-left",
            "logo_zone": "brand logo small, bottom-right corner, ~5% of canvas size",
            "background": "bold brand background — use brand color palette, pattern, or abstract shape",
        },
        "text_overlay": "ad_slogan",           # field from BrandDirection
        "constraints": [
            "strict 16:9 ratio, 1920×1080px",
            "slogan text is dominant — fills 50-70% of the canvas visually",
            "logo is intentionally small — brand whisper, not shout",
            "bold graphic background using brand primary + secondary colors",
            "can use pattern or geometric shapes from brand direction",
            "high contrast, punchy, ad-campaign quality",
            "no other copy or decorative text",
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
) -> str:
    """Build a JSON-structured IMAGE_GEN_V1 prompt for a social post."""
    spec = SOCIAL_SPECS[post_type]

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
            "copy": copy_text if copy_text else None,
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
) -> Optional[Path]:
    """Call Gemini with logo image + structured prompt to generate a social post."""
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
    )

    client = genai.Client(api_key=api_key)
    spec = SOCIAL_SPECS[post_type]
    post_label = spec["label"]

    # Build content parts — logo image (if available) + prompt
    parts = []

    if logo_path and logo_path.exists() and logo_path.stat().st_size > 100:
        try:
            img_bytes = logo_path.read_bytes()
            ext = logo_path.suffix.lower().lstrip(".")
            mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else 'png'}"
            parts.append(types.Part.from_text(
                text="BRAND LOGO — use this logo asset in the social post layout as specified:"
            ))
            parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
        except Exception as e:
            console.print(f"  [yellow]⚠ Could not load logo for {post_type}: {e}[/yellow]")

    parts.append(types.Part.from_text(text=prompt_str))
    parts.append(types.Part.from_text(
        text=f"Generate the {post_label} now. Output only the final 16:9 image."
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

        # Copy text map
        copy_map = {
            "collab_post":        "",                                       # no copy for collab
            "announcement_post":  getattr(direction, "announcement_copy", "") or f"Something new from {brand_name}.",
            "ads_post":           getattr(direction, "ad_slogan", "")       or brand_name,
        }

        # Logo to use (prefer transparent, fall back to regular logo)
        logo_path = assets.logo_transparent or assets.logo

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
            )
            post_paths[post_type] = result

        # Build board
        board_path = social_dir.parent / "social_board.png"
        _build_social_board(post_paths, board_path, brand_name)
        post_paths["board"] = board_path

        results[num] = post_paths
        console.print(f"  [dim]Social posts saved → {social_dir}[/dim]")

    return results
