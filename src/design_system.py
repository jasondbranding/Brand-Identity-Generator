"""
design_system.py — Brand Pattern & Design System Generator

Takes a BrandDirection and generates a complete, structured design system:
  - Color tokens (semantic naming, HSL + HEX + RGB)
  - Typography scale (H1→caption, line-height, letter-spacing)
  - Spacing system (4pt base grid)
  - Pattern library (3 variants: hero, surface, accent)
  - Component shape language
  - Usage rules per element

Can be integrated into the main pipeline or run standalone:
  python -m src.design_system --output outputs/design_system/
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import colorsys
import re

from google import genai
from google.genai import types
from rich.console import Console

from .director import BrandDirection, ColorSwatch

console = Console()


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class ColorToken:
    """Semantic color token with all format values."""
    token: str            # e.g. "--color-primary"
    name: str             # e.g. "Midnight Slate"
    hex: str              # e.g. "#1A2B3C"
    role: str             # primary / secondary / accent / neutral / background
    hsl: str = ""         # computed
    rgb: str = ""         # computed
    usage: str = ""       # usage guidance

    def __post_init__(self):
        if not self.hsl:
            self.hsl = _hex_to_hsl(self.hex)
        if not self.rgb:
            self.rgb = _hex_to_rgb(self.hex)


@dataclass
class TypeScale:
    """One level of the typography scale."""
    level: str            # H1, H2, H3, Body-L, Body-M, Caption
    size_pt: int          # font size in pt (print)
    size_px: int          # font size in px (screen)
    line_height: float    # e.g. 1.2
    letter_spacing: str   # e.g. "-0.02em"
    font_family: str      # primary or secondary
    weight: str           # e.g. "700", "400"
    usage: str            # where to use this level


@dataclass
class PatternVariant:
    """A specific use-case of the brand pattern."""
    name: str             # "hero", "surface", "accent"
    description: str      # visual description
    colors: List[str]     # hex codes used
    opacity: float        # 0.0–1.0
    scale: str            # "large", "medium", "small"
    usage: str            # when/where to use


@dataclass
class DesignSystem:
    """Complete design system for one brand direction."""
    direction_name: str
    option_type: str
    option_number: int

    # Color system
    color_tokens: List[ColorToken] = field(default_factory=list)

    # Typography
    primary_font: str = ""
    secondary_font: str = ""
    google_fonts_url: str = ""
    type_scale: List[TypeScale] = field(default_factory=list)

    # Spacing & layout
    base_unit: int = 4    # 4pt grid
    spacing_scale: dict = field(default_factory=dict)  # xs→3xl
    border_radius: dict = field(default_factory=dict)
    max_width: int = 1280

    # Pattern system
    pattern_variants: List[PatternVariant] = field(default_factory=list)
    pattern_description: str = ""

    # Shape language
    shape_language: str = ""
    icon_style: str = ""

    # Generated file paths
    pattern_hero_path: Optional[Path] = None
    pattern_surface_path: Optional[Path] = None
    pattern_accent_path: Optional[Path] = None

    # Markdown rulebook
    rulebook_md: str = ""


# ── Color utilities ────────────────────────────────────────────────────────────

def _hex_to_hsl(hex_str: str) -> str:
    """Convert hex color to HSL string."""
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        return "hsl(0, 0%, 50%)"
    r, g, b = int(hex_str[0:2], 16) / 255, int(hex_str[2:4], 16) / 255, int(hex_str[4:6], 16) / 255
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return f"hsl({int(h*360)}, {int(s*100)}%, {int(l*100)}%)"


def _hex_to_rgb(hex_str: str) -> str:
    """Convert hex color to RGB string."""
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        return "rgb(0, 0, 0)"
    r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
    return f"rgb({r}, {g}, {b})"


def _is_dark(hex_str: str) -> bool:
    """Return True if the color is dark (luminance < 0.5)."""
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        return False
    r, g, b = int(hex_str[0:2], 16) / 255, int(hex_str[2:4], 16) / 255, int(hex_str[4:6], 16) / 255
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return luminance < 0.5


def _derive_tints_shades(hex_str: str) -> dict:
    """Derive 5 tints/shades for a color token."""
    hex_str = hex_str.lstrip("#")
    r, g, b = int(hex_str[0:2], 16) / 255, int(hex_str[2:4], 16) / 255, int(hex_str[4:6], 16) / 255
    h, l, s = colorsys.rgb_to_hls(r, g, b)

    results = {}
    for level, new_l in [("100", 0.95), ("300", 0.75), ("500", l), ("700", 0.35), ("900", 0.15)]:
        nr, ng, nb = colorsys.hls_to_rgb(h, new_l, s)
        hex_out = "#{:02X}{:02X}{:02X}".format(int(nr * 255), int(ng * 255), int(nb * 255))
        results[level] = hex_out
    return results


# ── Font recommendations ───────────────────────────────────────────────────────

FONT_PAIRINGS = {
    "minimal": ("Inter", "Inter", "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap"),
    "elegant": ("Playfair Display", "Lato", "https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;1,400&family=Lato:wght@300;400;700&display=swap"),
    "bold": ("Space Grotesk", "Space Grotesk", "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;700;800&display=swap"),
    "corporate": ("IBM Plex Sans", "IBM Plex Mono", "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap"),
    "playful": ("Nunito", "Quicksand", "https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&family=Quicksand:wght@400;500;600&display=swap"),
    "retro": ("Syne", "Syne Mono", "https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Syne+Mono&display=swap"),
    "tech": ("JetBrains Mono", "Inter", "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap"),
    "luxury": ("Cormorant Garamond", "Montserrat", "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300&family=Montserrat:wght@300;400;500&display=swap"),
    "organic": ("DM Serif Display", "DM Sans", "https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500&display=swap"),
}


def _pick_font_pairing(direction: BrandDirection) -> tuple[str, str, str]:
    """Pick the best Google Fonts pairing based on direction style cues."""
    style_text = f"{direction.graphic_style} {direction.direction_name} {direction.rationale}".lower()

    if any(k in style_text for k in ("luxury", "premium", "editorial", "couture", "haute")):
        return FONT_PAIRINGS["luxury"]
    if any(k in style_text for k in ("retro", "vintage", "classic", "nostalgic")):
        return FONT_PAIRINGS["retro"]
    if any(k in style_text for k in ("tech", "futuristic", "cyber", "digital", "code")):
        return FONT_PAIRINGS["tech"]
    if any(k in style_text for k in ("bold", "brutalist", "strong", "impact", "heavy")):
        return FONT_PAIRINGS["bold"]
    if any(k in style_text for k in ("playful", "mascot", "fun", "friendly", "cute")):
        return FONT_PAIRINGS["playful"]
    if any(k in style_text for k in ("organic", "natural", "botanical", "eco")):
        return FONT_PAIRINGS["organic"]
    if any(k in style_text for k in ("elegant", "serif", "typographic", "fashion")):
        return FONT_PAIRINGS["elegant"]
    if any(k in style_text for k in ("corporate", "enterprise", "professional", "b2b")):
        return FONT_PAIRINGS["corporate"]
    return FONT_PAIRINGS["minimal"]


# ── Type scale builder ─────────────────────────────────────────────────────────

def _build_type_scale(primary_font: str, secondary_font: str, style_cues: str) -> List[TypeScale]:
    """Build a complete typographic scale for this direction."""
    is_editorial = any(k in style_cues.lower() for k in ("editorial", "luxury", "elegant"))
    tight_spacing = any(k in style_cues.lower() for k in ("minimal", "geometric", "tech", "futuristic"))

    return [
        TypeScale("Display", 72, 96, 1.0, "-0.04em", primary_font, "700",
                  "Hero statements, brand moments, full-bleed typography"),
        TypeScale("H1", 48, 64, 1.1, "-0.03em", primary_font, "700",
                  "Page titles, section heroes"),
        TypeScale("H2", 32, 42, 1.15, "-0.02em", primary_font, "600",
                  "Major section headings"),
        TypeScale("H3", 24, 32, 1.2, "-0.01em", primary_font, "600",
                  "Subsection headings, card titles"),
        TypeScale("H4", 18, 24, 1.3, "0em", primary_font, "500",
                  "Minor headings, labels"),
        TypeScale("Body-L", 16, 18, 1.6 if not tight_spacing else 1.5, "0em", secondary_font, "400",
                  "Primary body copy, article text"),
        TypeScale("Body-M", 14, 16, 1.5, "0.01em", secondary_font, "400",
                  "Secondary body, captions, metadata"),
        TypeScale("Caption", 11, 12, 1.4, "0.04em", secondary_font, "400",
                  "Small labels, footnotes, legal"),
        TypeScale("Button", 13, 14, 1.0, "0.08em", primary_font, "600",
                  "CTA buttons, navigation items"),
    ]


# ── Spacing system ─────────────────────────────────────────────────────────────

def _build_spacing_system(base: int = 4) -> tuple[dict, dict]:
    """Build a 4pt grid spacing scale and border radius system."""
    spacing = {
        "xs":  base,        # 4px — tight spacing, icon padding
        "sm":  base * 2,    # 8px — component internal padding
        "md":  base * 4,    # 16px — standard gap
        "lg":  base * 6,    # 24px — section padding
        "xl":  base * 10,   # 40px — large section gaps
        "2xl": base * 16,   # 64px — hero sections
        "3xl": base * 24,   # 96px — full-section whitespace
    }

    border_radius = {
        "none": "0px",
        "sm":   "4px",
        "md":   "8px",
        "lg":   "16px",
        "xl":   "24px",
        "full": "9999px",
    }
    return spacing, border_radius


# ── Pattern variants ───────────────────────────────────────────────────────────

def _build_pattern_variants(direction: BrandDirection) -> List[PatternVariant]:
    """Define 3 pattern use cases from the direction's graphic style."""
    palette = direction.colors
    if not palette:
        return []

    primary_hex = palette[0].hex
    secondary_hex = palette[1].hex if len(palette) > 1 else palette[0].hex
    accent_hex = palette[2].hex if len(palette) > 2 else palette[0].hex

    style_cues = direction.graphic_style.lower()
    is_geometric = any(k in style_cues for k in ("geometric", "angular", "grid", "structured"))
    is_organic = any(k in style_cues for k in ("organic", "flowing", "curve", "natural", "fluid"))

    if is_geometric:
        hero_desc = f"Large-scale geometric grid pattern — repeat unit 120px, {primary_hex} strokes on {secondary_hex} fill"
        surface_desc = f"Fine dot grid — 4px dots every 24px on near-white, subtle depth for UI surfaces"
        accent_desc = f"Dense 45° hatching in {accent_hex} — 1px strokes, 8px gaps, used for emphasis zones"
    elif is_organic:
        hero_desc = f"Flowing botanical curves in {primary_hex} on {secondary_hex} — large scale, painterly quality"
        surface_desc = f"Soft watercolor texture wash in tints of {primary_hex} — subtle, non-distracting"
        accent_desc = f"Micro-leaf or petal repeat motif in {accent_hex} — 16px scale, tight repeat"
    else:
        hero_desc = f"Abstract mark repeat — logo symbol tiled at 80px scale in {primary_hex} on {secondary_hex}"
        surface_desc = f"Minimal rule pattern — 1px horizontal lines at 16px intervals in 12% opacity"
        accent_desc = f"Bold color block stripes in {primary_hex}/{accent_hex} — 20% pattern, 80% negative space"

    return [
        PatternVariant(
            name="hero",
            description=hero_desc,
            colors=[primary_hex, secondary_hex],
            opacity=1.0,
            scale="large",
            usage="Full-bleed backgrounds, hero sections, printed materials (covers, bags, boxes)"
        ),
        PatternVariant(
            name="surface",
            description=surface_desc,
            colors=[primary_hex],
            opacity=0.06,
            scale="small",
            usage="UI card backgrounds, subtle section dividers, email templates"
        ),
        PatternVariant(
            name="accent",
            description=accent_desc,
            colors=[accent_hex, secondary_hex],
            opacity=0.4,
            scale="medium",
            usage="Pull quotes, callout boxes, slide decks, social media accents"
        ),
    ]


# ── Generate pattern images ────────────────────────────────────────────────────

def generate_pattern_images(
    direction: BrandDirection,
    output_dir: Path,
    api_key: str,
) -> dict[str, Optional[Path]]:
    """
    Generate 3 pattern PNG images for this direction using Gemini.
    Returns {'hero': Path, 'surface': Path, 'accent': Path}
    """
    results: dict[str, Optional[Path]] = {}
    output_dir.mkdir(parents=True, exist_ok=True)

    palette_str = ", ".join(f"{c.hex}" for c in direction.colors)
    slug = re.sub(r"\W+", "_", direction.direction_name.lower()).strip("_")
    base_prompt = (
        f"Brand palette: {palette_str}. "
        f"Style: {direction.graphic_style[:120]}. "
    )

    variants = {
        "hero": (
            f"Large-scale seamless repeating pattern. {base_prompt} "
            f"Geometric or organic motif at 100px repeat unit. Strong, recognizable. "
            f"Primary color {direction.colors[0].hex} dominant. "
            f"Square tile, flat vector, NO text, NO logos, NO letterforms.",
            1.0,
        ),
        "surface": (
            f"Ultra-subtle micro texture. {base_prompt} "
            f"Very fine pattern at 12px repeat — dots, lines, or crosshatch. "
            f"5% opacity effect on white background. Barely visible, adds texture not color. "
            f"Square tile, seamless, NO text.",
            0.4,
        ),
        "accent": (
            f"Medium-scale brand pattern. {base_prompt} "
            f"Mix of primary {direction.colors[0].hex} and accent "
            f"{direction.colors[-1].hex if len(direction.colors) > 1 else direction.colors[0].hex}. "
            f"Bold and graphic. Used as partial overlays on social posts. "
            f"Square tile, seamless, NO text, NO logos.",
            0.7,
        ),
    }

    for name, (prompt, _opacity) in variants.items():
        save_path = output_dir / f"pattern_{slug}_{name}.png"

        try:
            client = genai.Client(api_key=api_key)

            # Try Imagen 3 first
            response = client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio="1:1"),
            )
            if response.generated_images:
                save_path.write_bytes(response.generated_images[0].image.image_data)
                console.print(f"  [green]✓ pattern/{name}[/green] (Imagen 3) → {save_path.name}")
                results[name] = save_path
                continue
        except Exception:
            pass

        # Fallback: Gemini 2.0 Flash
        try:
            client = genai.Client(api_key=api_key)
            for model_id in ["gemini-2.5-flash-image", "gemini-2.0-flash-exp-image-generation"]:
                try:
                    resp = client.models.generate_content(
                        model=model_id,
                        contents=prompt,
                        config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
                    )
                    for candidate in resp.candidates or []:
                        for part in candidate.content.parts or []:
                            if hasattr(part, "inline_data") and part.inline_data:
                                import base64
                                data = part.inline_data.data
                                if isinstance(data, str):
                                    data = base64.b64decode(data)
                                save_path.write_bytes(data)
                                console.print(f"  [green]✓ pattern/{name}[/green] ({model_id.split('-')[1]}) → {save_path.name}")
                                results[name] = save_path
                                break
                        if name in results:
                            break
                    if name in results:
                        break
                except Exception:
                    continue
        except Exception as e:
            console.print(f"  [yellow]⚠ pattern/{name} failed: {e}[/yellow]")

        if name not in results:
            results[name] = None

    return results


# ── Markdown rulebook ──────────────────────────────────────────────────────────

def _build_rulebook(ds: DesignSystem) -> str:
    """Generate a complete Markdown design system rulebook."""

    # Color section
    color_lines = []
    for token in ds.color_tokens:
        tints = _derive_tints_shades(token.hex)
        tint_row = " | ".join(f"`{k}` {v}" for k, v in tints.items())
        color_lines.append(
            f"### {token.name} — `{token.token}`\n"
            f"- **HEX**: `{token.hex}`\n"
            f"- **HSL**: `{token.hsl}`\n"
            f"- **RGB**: `{token.rgb}`\n"
            f"- **Role**: {token.role}\n"
            f"- **Usage**: {token.usage}\n"
            f"- **Shades**: {tint_row}\n"
        )

    # Typography section
    type_lines = ["| Level | Size | Line-Height | Letter-Spacing | Weight | Font | Usage |",
                  "|-------|------|-------------|----------------|--------|------|-------|"]
    for ts in ds.type_scale:
        type_lines.append(
            f"| {ts.level} | {ts.size_px}px / {ts.size_pt}pt | {ts.line_height} | "
            f"`{ts.letter_spacing}` | {ts.weight} | {ts.font_family} | {ts.usage} |"
        )

    # Spacing section
    spacing_lines = ["| Token | Value | Usage |", "|-------|-------|-------|"]
    for tok, val in ds.spacing_scale.items():
        spacing_lines.append(f"| `spacing-{tok}` | {val}px | — |")

    # Pattern section
    pattern_lines = []
    for pv in ds.pattern_variants:
        pattern_lines.append(
            f"### Pattern: {pv.name.title()}\n"
            f"- **Scale**: {pv.scale}\n"
            f"- **Colors**: {', '.join(pv.colors)}\n"
            f"- **Opacity**: {int(pv.opacity * 100)}%\n"
            f"- **Description**: {pv.description}\n"
            f"- **Use when**: {pv.usage}\n"
        )

    return f"""# {ds.direction_name} — Brand Design System
*Option {ds.option_number} · {ds.option_type}*

---

## Color System

{chr(10).join(color_lines)}

### CSS Custom Properties
```css
:root {{
{chr(10).join(f'  {t.token}: {t.hex};' for t in ds.color_tokens)}
}}
```

---

## Typography

**Primary Font**: [{ds.primary_font}](https://fonts.google.com) — Display, headings, UI labels
**Secondary Font**: [{ds.secondary_font}](https://fonts.google.com) — Body copy, captions

**Google Fonts Import**:
```html
<link href="{ds.google_fonts_url}" rel="stylesheet">
```

### Type Scale

{chr(10).join(type_lines)}

### CSS Typography Tokens
```css
:root {{
{chr(10).join(f'  --font-primary: "{ds.primary_font}", sans-serif;')}
{chr(10).join(f'  --font-secondary: "{ds.secondary_font}", sans-serif;')}
}}
```

---

## Spacing & Layout

**Base unit**: {ds.base_unit}px grid

{chr(10).join(spacing_lines)}

**Max content width**: {ds.max_width}px
**Border radius system**:
{chr(10).join(f'- `radius-{k}`: {v}' for k, v in ds.border_radius.items())}

---

## Pattern System

{ds.pattern_description}

{chr(10).join(pattern_lines)}

---

## Shape Language

{ds.shape_language}

## Icon Style

{ds.icon_style}

---

## Usage Rules

### Do ✓
- Use the `{ds.color_tokens[0].token if ds.color_tokens else '--color-primary'}` color for all primary CTAs
- Maintain a minimum {ds.spacing_scale.get('md', 16)}px padding inside all interactive elements
- Always load `{ds.primary_font}` as the display typeface — never substitute
- Pattern opacity: Hero=100%, Surface=6%, Accent=40%

### Don't ✗
- Don't use more than 3 colors in a single component
- Don't stretch or distort the logo pattern tile
- Don't mix both font families at the same weight in adjacent elements
- Don't use the hero pattern at less than 80% of its designed scale

---

*Generated by Brand Identity Generator · Design System v1.0*
"""


# ── Main builder ───────────────────────────────────────────────────────────────

def build_design_system(
    direction: BrandDirection,
    output_dir: Path,
    generate_patterns: bool = True,
) -> DesignSystem:
    """
    Build a complete design system for one brand direction.

    Args:
        direction:           BrandDirection from director.py
        output_dir:          Directory to save pattern images and rulebook
        generate_patterns:   Whether to call Gemini to generate pattern PNGs

    Returns:
        DesignSystem dataclass with all tokens, specs, and file paths
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"\W+", "_", direction.direction_name.lower()).strip("_")
    patterns_dir = output_dir / "patterns"
    patterns_dir.mkdir(exist_ok=True)

    console.print(f"\n  [bold blue]Design System: {direction.direction_name}[/bold blue]")

    # ── 1. Color tokens ──────────────────────────────────────────────────────
    role_usage = {
        "primary":    "Main brand actions, headlines, primary buttons",
        "secondary":  "Supporting elements, hover states, secondary buttons",
        "accent":     "Highlights, badges, active indicators, links",
        "neutral":    "Body text, borders, dividers, disabled states",
        "background": "Page backgrounds, card fills, section backgrounds",
    }
    color_tokens = []
    for i, swatch in enumerate(direction.colors):
        role = swatch.role if swatch.role else (
            "primary" if i == 0 else "secondary" if i == 1 else
            "accent" if i == 2 else "neutral" if i == 3 else "background"
        )
        token = ColorToken(
            token=f"--color-{role}",
            name=swatch.name,
            hex=swatch.hex,
            role=role,
            usage=role_usage.get(role, "Supplementary color element"),
        )
        color_tokens.append(token)

    # Always ensure a neutral and background token exist
    hex_values = [t.hex for t in color_tokens]
    if not any(t.role == "neutral" for t in color_tokens) and len(color_tokens) >= 2:
        color_tokens.append(ColorToken(
            token="--color-neutral",
            name="Neutral",
            hex="#6B7280",
            role="neutral",
            usage="Body text, borders, disabled states",
        ))
    if not any(t.role == "background" for t in color_tokens):
        bg_hex = "#F9FAFB" if not _is_dark(color_tokens[0].hex) else "#111827"
        color_tokens.append(ColorToken(
            token="--color-background",
            name="Background",
            hex=bg_hex,
            role="background",
            usage="Page and section backgrounds",
        ))

    # ── 2. Typography ─────────────────────────────────────────────────────────
    primary_font, secondary_font, gfonts_url = _pick_font_pairing(direction)
    style_cues = direction.graphic_style
    type_scale = _build_type_scale(primary_font, secondary_font, style_cues)

    # ── 3. Spacing ────────────────────────────────────────────────────────────
    spacing, border_radius = _build_spacing_system(base=4)

    # ── 4. Pattern metadata ───────────────────────────────────────────────────
    pattern_variants = _build_pattern_variants(direction)

    is_dark_brand = _is_dark(color_tokens[0].hex)
    shape_cues = direction.graphic_style
    if any(k in shape_cues.lower() for k in ("round", "soft", "organic", "curve")):
        shape_lang = "Rounded, soft geometry. Prefer `border-radius: 16px` for cards, `border-radius: 999px` for pills and badges."
        icon_style = "Outlined icons with rounded caps and joins. Stroke weight: 1.5px. Prefer Lucide or Heroicons (rounded variant)."
    elif any(k in shape_cues.lower() for k in ("sharp", "angular", "geometric", "brutalist")):
        shape_lang = "Hard-edged, zero-radius geometry. Cards and containers use `border-radius: 0` or max `4px`. Angular cuts welcome."
        icon_style = "Sharp-edged icons, no rounded corners. Stroke weight: 2px. Prefer Material Icons (sharp variant) or Phosphor Icons."
    else:
        shape_lang = "Subtle geometric softness. Use `border-radius: 8px` for cards, `4px` for inputs and buttons. Consistent across all components."
        icon_style = "Clean, consistent icons with 1.5px stroke weight. Prefer Phosphor Icons or Feather Icons for clarity at small sizes."

    # ── 5. Assemble DesignSystem ──────────────────────────────────────────────
    ds = DesignSystem(
        direction_name=direction.direction_name,
        option_type=direction.option_type,
        option_number=direction.option_number,
        color_tokens=color_tokens,
        primary_font=primary_font,
        secondary_font=secondary_font,
        google_fonts_url=gfonts_url,
        type_scale=type_scale,
        base_unit=4,
        spacing_scale=spacing,
        border_radius=border_radius,
        max_width=1280,
        pattern_variants=pattern_variants,
        pattern_description=f"Brand pattern system derived from: {direction.graphic_style[:120]}",
        shape_language=shape_lang,
        icon_style=icon_style,
    )

    # ── 6. Generate pattern images ────────────────────────────────────────────
    if generate_patterns and api_key:
        console.print("  Generating pattern images...")
        pattern_paths = generate_pattern_images(direction, patterns_dir, api_key)
        ds.pattern_hero_path = pattern_paths.get("hero")
        ds.pattern_surface_path = pattern_paths.get("surface")
        ds.pattern_accent_path = pattern_paths.get("accent")
    else:
        console.print("  [dim]Skipping pattern generation (no API key or disabled)[/dim]")

    # ── 7. Build rulebook ─────────────────────────────────────────────────────
    ds.rulebook_md = _build_rulebook(ds)
    rulebook_path = output_dir / f"design_system_{slug}.md"
    rulebook_path.write_text(ds.rulebook_md, encoding="utf-8")
    console.print(f"  [green]✓ Rulebook saved[/green] → {rulebook_path.name}")

    # ── 8. Save tokens as JSON (for Figma/dev handoff) ────────────────────────
    tokens_data = {
        "colors": {t.token.lstrip("--"): {"hex": t.hex, "hsl": t.hsl, "rgb": t.rgb, "role": t.role} for t in ds.color_tokens},
        "typography": {
            "primary_font": ds.primary_font,
            "secondary_font": ds.secondary_font,
            "google_fonts_url": ds.google_fonts_url,
            "scale": [
                {"level": ts.level, "size_px": ts.size_px, "size_pt": ts.size_pt,
                 "line_height": ts.line_height, "letter_spacing": ts.letter_spacing,
                 "weight": ts.weight, "font": ts.font_family}
                for ts in ds.type_scale
            ],
        },
        "spacing": {f"spacing-{k}": f"{v}px" for k, v in ds.spacing_scale.items()},
        "border_radius": {f"radius-{k}": v for k, v in ds.border_radius.items()},
        "patterns": {
            "hero": str(ds.pattern_hero_path) if ds.pattern_hero_path else None,
            "surface": str(ds.pattern_surface_path) if ds.pattern_surface_path else None,
            "accent": str(ds.pattern_accent_path) if ds.pattern_accent_path else None,
        },
    }
    tokens_path = output_dir / f"tokens_{slug}.json"
    tokens_path.write_text(json.dumps(tokens_data, indent=2), encoding="utf-8")
    console.print(f"  [green]✓ Tokens JSON saved[/green] → {tokens_path.name}")

    return ds


# ── Batch builder ──────────────────────────────────────────────────────────────

def build_all_design_systems(
    directions: list,
    base_output_dir: Path,
    generate_patterns: bool = True,
) -> List[DesignSystem]:
    """
    Build design systems for all brand directions.
    Called from main pipeline after generate_all_assets().
    """
    systems = []
    for direction in directions:
        dir_output = base_output_dir / f"direction_{direction.option_number}"
        ds = build_design_system(direction, dir_output, generate_patterns=generate_patterns)
        systems.append(ds)
    return systems
