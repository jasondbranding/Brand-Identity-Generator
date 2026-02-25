"""
Director — uses Gemini API to analyze the brand brief and output
4 distinct brand identity directions as structured data.

Each direction includes:
  - Strategic rationale
  - Color palette (4–6 swatches with hex codes)
  - Typography recommendation
  - Graphic/illustration style
  - Logo concept
  - Detailed Gemini image prompt for stylescape generation
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path
from typing import List, Literal, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel

from .parser import BriefData, IMAGE_EXTS

console = Console()


# ── Pydantic schema for structured Claude output ─────────────────────────────

class ColorSwatch(BaseModel):
    name: str = Field(description="Descriptive color name, e.g. 'Midnight Slate'")
    hex: str = Field(description="Hex code, e.g. '#1A2B3C'")
    role: str = Field(description="One of: primary, secondary, accent, neutral, background")


# ── Structured image spec models (JSON → natural language in generator) ───────

class LogoSpec(BaseModel):
    """Structured render specification for the logo mark. Translated to a natural language prompt by the generator."""
    logo_type: Literal["symbol", "abstract_mark", "lettermark", "logotype", "combination"] = Field(
        description=(
            "Type of mark to generate. Choose based on what best serves the brand:\n"
            "  'symbol'       — recognizable icon form (leaf, wave, coffee bean, mountain). No text at all.\n"
            "  'abstract_mark'— non-representational geometric/organic form. No text at all.\n"
            "  'lettermark'   — single stylised letter, highly crafted. No full words.\n"
            "  'logotype'     — brand name as pure typographic treatment. The type IS the logo.\n"
            "                   Use when typography is the brand's primary visual identity.\n"
            "  'combination'  — symbol/mark PLUS brand name text, composed together as a unit.\n"
            "                   Use when name recognition is critical (new brand, complex name).\n"
            "⚠ For logotype and combination: text IS allowed — but ONLY the brand name, rendered as type."
        )
    )
    form: str = Field(
        description=(
            "Exact visual description of the mark. Be precise with geometry, dimensions, weight:\n"
            "  For symbol/abstract_mark: shape primitives, px dimensions, angles, stroke weights.\n"
            "    GOOD: 'two concentric arcs, outer 48px radius 5px stroke, inner 28px radius 3px stroke, open at 7 o'clock'\n"
            "    BAD:  'a circular mark suggesting infinity'\n"
            "  For lettermark: exact letter, weight, stylisation treatment.\n"
            "    GOOD: 'uppercase M, custom serif, 72pt, vertically mirrored at the baseline creating a reflection'\n"
            "  For logotype: typeface style, weight, any custom letterform treatment.\n"
            "    GOOD: 'brand name in condensed geometric sans-serif, all-caps, extra-bold, 5% tracked, baseline perfectly aligned'\n"
            "  For combination: describe symbol AND its spatial relationship to the type.\n"
            "    GOOD: 'small leaf symbol 24px to the left of the brand name, vertically centered, 8px gap between mark and type'"
        )
    )
    composition: str = Field(
        description="Canvas rules. E.g. 'centered, 20% padding all sides, 800×800px canvas, pure white #FFFFFF background'. For combination/logotype: specify horizontal or stacked layout."
    )
    color_hex: str = Field(
        description=(
            "EXACTLY ONE hex color code from the palette. "
            "⚠ MONOCHROME RULE: all logo types use ONE color only — symbol, type, and all elements "
            "share the same single color. No gradients, no second color, no tints."
        )
    )
    color_name: str = Field(
        description="Descriptive name for the chosen color, e.g. 'Deep Forest Green'."
    )
    fill_style: Literal["solid_fill", "outline_only", "fill_with_outline_detail"] = Field(
        description=(
            "'solid_fill' = entire mark/type is flat filled. "
            "'outline_only' = stroke only, transparent interior (works well for symbols). "
            "'fill_with_outline_detail' = solid fill with additional outline or cutout elements."
        )
    )
    stroke_weight: str = Field(
        description="Stroke weight if outline is involved. E.g. '3px', 'hairline 1px', 'bold 6px'. Use 'N/A' for pure solid fill."
    )
    typography_treatment: str = Field(
        description=(
            "REQUIRED for logotype and combination. Describe the typeface and any custom treatment:\n"
            "  GOOD: 'condensed geometric sans-serif similar to Futura, all-caps, extra-bold weight, "
            "5% letter-spacing, custom ink-trap detail on the corners'\n"
            "  For symbol/abstract_mark/lettermark: set to 'N/A'."
        )
    )
    render_style: str = Field(
        description="Visual rendering approach. E.g. 'clean flat vector', 'precise geometric construction', 'organic hand-crafted line'. Never gradient, never 3D unless specified."
    )
    metaphor: str = Field(
        description=(
            "For symbol/abstract_mark/combination: what the mark visually suggests or evokes. "
            "E.g. 'coffee bean cross-section revealing a mountain ridge — dual reading of origin and harvest'. "
            "For logotype: describe the typographic personality. "
            "Use 'abstract' if purely geometric with no representational intent."
        )
    )
    avoid: List[str] = Field(
        description=(
            "Explicit exclusion list. "
            "For symbol/abstract_mark/lettermark — always include: 'text', 'letterforms', 'words', 'gradient', 'drop shadow', 'multiple colors', 'photography'. "
            "For logotype — include: 'symbols', 'icons', 'decorative elements', 'gradient', 'drop shadow', 'multiple colors'. "
            "For combination — include: 'gradient', 'drop shadow', 'multiple colors', 'decorative frames'. "
            "Never include 'text' in the avoid list for logotype or combination."
        )
    )


class PatternSpec(BaseModel):
    """Structured render specification for the repeating brand pattern tile."""
    motif: str = Field(
        description="The repeating element. E.g. 'isometric dot grid', 'overlapping diamond lattice', 'flowing organic wave curves', 'botanical leaf outline repeats'."
    )
    density_scale: str = Field(
        description="Exact size and spacing. E.g. 'each diamond 16×10px, 8px gutters'. Be specific — vague density produces unusable patterns."
    )
    primary_color_hex: str = Field(description="Main motif color hex code from the palette.")
    secondary_color_hex: str = Field(description="Secondary or accent color hex. Use 'none' if single-color pattern.")
    background_color_hex: str = Field(description="Background / ground color hex code from the palette.")
    opacity_notes: str = Field(description="Layering or opacity effects. E.g. '60% opacity on overlapping zones'. Use 'solid' if no transparency.")
    render_style: str = Field(description="E.g. 'flat vector seamless tile', 'halftone print quality', 'botanical illustration line weight'.")
    mood: str = Field(description="Emotional quality the pattern should project. E.g. 'premium editorial restraint', 'organic artisan warmth', 'technical grid precision'.")
    avoid: List[str] = Field(description="Always include: 'text', 'logos', 'photographic elements', 'random noise'.")


class BackgroundSpec(BaseModel):
    """Structured render specification for the atmospheric brand background (16:9)."""
    scene_type: Literal["environmental_photo", "abstract_field", "macro_texture", "digital_art"] = Field(
        description=(
            "'environmental_photo' = real-world landscape or setting, photorealistic. "
            "'abstract_field' = non-representational color and light composition. "
            "'macro_texture' = extreme close-up of a material surface. "
            "'digital_art' = composed digital illustration or gradient artwork."
        )
    )
    description: str = Field(
        description="Specific scene or subject. E.g. 'misty Vietnamese highland coffee farm at dawn, rows of coffee trees descending a fog-filled valley'. Be cinematic and precise."
    )
    primary_color_hex: str = Field(description="Dominant color in the scene — hex from palette.")
    accent_color_hex: str = Field(description="Secondary / highlight color hex. Use 'none' if monochromatic scene.")
    lighting: str = Field(description="Lighting quality and direction. E.g. 'soft diffused morning fog light', 'dramatic golden hour rim light from upper left', 'flat overcast'.")
    composition: str = Field(description="Framing rule. E.g. 'wide 16:9, horizon at lower third, no dominant foreground subject', 'edge-to-edge texture fill, no horizon'.")
    texture: str = Field(description="Surface or film quality. E.g. 'subtle film grain', 'smooth digital', 'rough handmade paper', 'clean commercial photography'.")
    mood: str = Field(description="Emotional register. E.g. 'quiet contemplative premium', 'bold energetic kinetic', 'warm intimate heritage'.")
    avoid: List[str] = Field(description="Always include: 'text', 'logos', 'UI elements', 'watermarks', 'typography'. Add: 'people', 'faces' if not appropriate for brand.")


class BrandDirection(BaseModel):
    option_number: int = Field(description="1, 2, 3, or 4")
    option_type: Literal["Market-Aligned", "Designer-Led", "Hybrid", "Wild Card"]
    direction_name: str = Field(
        description="A short, evocative creative name for this direction, e.g. 'Signal & Silence'"
    )
    rationale: str = Field(
        description="2–3 sentences: the strategic and creative reasoning for this direction"
    )
    colors: List[ColorSwatch] = Field(description="4–6 colors defining the palette")
    typography_primary: str = Field(
        description="Primary typeface name + style rationale in one sentence"
    )
    typography_secondary: str = Field(
        description="Secondary/body typeface name + role in one sentence"
    )
    graphic_style: str = Field(
        description="2–3 sentences describing the visual language: illustration style, patterns, shapes, texture"
    )
    logo_concept: str = Field(
        description="2–3 sentences describing the logo form, shape language, and symbol concept"
    )
    background_spec: BackgroundSpec = Field(
        description=(
            "Structured render spec for the atmospheric background image (16:9). "
            "Fill every field with direction-specific values — this is translated into an image prompt by the generator. "
            "The background should feel like the emotional world of the brand."
        )
    )
    logo_spec: LogoSpec = Field(
        description=(
            "Structured render spec for the logo mark. "
            "⚠ MONOCHROME RULE: color_hex MUST be exactly ONE hex color — no gradients, no second color. "
            "⚠ NO TEXT RULE: logo_type must be 'symbol', 'abstract_mark', or 'lettermark' only — NEVER a wordmark or any text. "
            "Every field must be filled with precise, specific values — vague descriptions produce unusable logos."
        )
    )
    pattern_spec: PatternSpec = Field(
        description=(
            "Structured render spec for the seamless brand pattern tile. "
            "Fill density_scale with exact pixel measurements. "
            "Colors must use hex codes directly from this direction's palette."
        )
    )
    tagline: str = Field(
        description=(
            "Brand tagline — 5 to 10 words, memorable and on-brand. "
            "REQUIRED — must not be empty. "
            "If brief provides a locked tagline, use it verbatim. Otherwise generate one that captures "
            "this direction's core promise and personality. "
            "Example: 'Where every market tells a story.' or 'Built for those who move first.'"
        )
    )
    ad_slogan: str = Field(
        description=(
            "Short punchy ad slogan — 3 to 6 words, bold and action-oriented. "
            "REQUIRED — must not be empty. "
            "If brief provides a locked slogan, use it verbatim. Otherwise generate one that fits "
            "this direction's visual energy. Used as the large hero text on ad posts. "
            "Example: 'Trade smarter. Live bolder.' or 'Fresh finds. Bold moves.'"
        )
    )
    announcement_copy: str = Field(
        description=(
            "Announcement post body text — 10 to 18 words, brand voice tone. "
            "REQUIRED — must not be empty. "
            "If brief provides locked announcement copy, use it verbatim. Otherwise write something "
            "that sounds like an exciting brand announcement on X/Twitter — human, slightly cryptic, "
            "specific to this direction's concept. "
            "Example: 'Something new is here. Discover the market experience you've been waiting for.' "
            "or 'We're redefining what it means to build in public. Stay close.'"
        )
    )


class BrandDirectionsOutput(BaseModel):
    brand_summary: str = Field(
        description="3–4 sentence strategic analysis: market position, brand personality, key tension to resolve"
    )
    directions: List[BrandDirection] = Field(
        description="Exactly 4 brand identity directions (or 2 for Quick Mode)"
    )


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a world-class Creative Director with 20 years of brand identity experience.
You have created brand systems for leading tech companies, luxury brands, and startups.
You think like a strategist, design like a craftsman, and communicate like a writer.

Your task: Analyze the incoming brand brief and generate distinct brand identity directions.

For each direction type, follow this logic precisely:

**Option 1 — Market-Aligned**
Research the competitive landscape implied by the brief. What do successful players in this category look like visually? Design a direction that meets market expectations and signals category credibility — but executed with craft, not mediocrity.

**Option 2 — Designer-Led**
If a moodboard is provided, follow it faithfully. Map the references to color, typography, graphic style, and logo form. If no moodboard, create the most aesthetically elevated version of the brand based purely on design sensibility.

**Option 3 — Hybrid**
Propose a deliberate balance between market recognition and designer instinct. Be explicit about what you're borrowing from convention (for trust) and what you're differentiating (for personality). Make the reasoning transparent.

**Option 4 — Wild Card**
Surprise. Break from the brief's explicit direction. Use your understanding of the product, audience, and cultural moment to propose an unexpected direction that might be exactly right. No moodboard constraint.

**For image specs — 3 structured JSON specs per direction:**

Each spec has a strict schema. Fill every field with direction-specific, precise values.
The generator translates these specs into natural language prompts — so every field matters.

background_spec: Atmospheric brand world image (16:9 cinematic).
- scene_type: choose the most fitting type for this direction's mood
- description: cinematic, specific — name the setting, season, time of day if environmental
- Use hex codes from THIS direction's palette in primary_color_hex / accent_color_hex
- lighting: be exact — "soft diffused fog light" not "nice light"
- mood: 2–4 words that capture the emotional register

logo_spec: The brand mark — monochrome (1 color), specific form, strategic type choice.

⚠ CRITICAL: color_hex = EXACTLY ONE hex code. ALL logo types are monochrome.
   No gradients, no second color — this applies to symbol, logotype, AND combination.

LOGO TYPE SELECTION — choose based on what fits the brand strategy:
  'symbol' or 'abstract_mark' — when the visual mark can carry meaning alone.
    Use for: brands with short memorable names, brands in visual-heavy categories (food, fashion),
    brands wanting international recognition, or when moodboard shows icon-first identity.
    ⚠ No text anywhere — avoid list MUST include "text", "letterforms", "words"

  'lettermark' — when a single initial is enough to distinguish the brand.
    Use for: monogram-style identity, luxury/heritage positioning.
    ⚠ Single letter only — avoid list MUST include "text", "words"

  'logotype' — when the brand NAME is the primary visual asset.
    Use for: brands where name recognition is critical, short punchy brand names that look
    great as type (e.g. "MINH", "APEX"), typographically-led moodboards.
    ✓ Text IS the logo — describe typeface, weight, tracking, any custom letterform treatment.
    ⚠ avoid list must NOT include "text" — DO include "symbols", "decorative elements"

  'combination' — symbol + name text composed as a unit.
    Use for: new brands that need name recognition, brands in categories where combination
    marks are the norm (food/beverage, consumer brands, retail), complex or unfamiliar names.
    ✓ Text IS part of the mark — describe both the symbol and its spatial relationship to the type.
    ⚠ avoid list must NOT include "text" — DO include "gradient", "drop shadow"

typography_treatment field:
  REQUIRED for logotype and combination. Describe typeface character + any custom treatment.
  GOOD: "condensed geometric sans-serif, all-caps extra-bold, 6% letter-spacing, brand name only"
  BAD: "a nice clean font"
  Set to "N/A" for symbol/abstract_mark/lettermark.

Good logo_spec form examples by type:
  symbol:      "two concentric arcs, outer 48px radius 5px stroke, inner 28px radius 3px stroke, open at 7 o'clock position"
  logotype:    "brand name in condensed neo-grotesque sans-serif, all-caps, bold 700 weight, perfectly even baseline"
  combination: "24px rounded-square icon to the left, 8px gap, brand name in medium-weight humanist sans-serif beside it"
  BAD:         "a circular mark evoking the brand values"

pattern_spec: Repeating seamless surface tile.
- motif: name the element type precisely
- density_scale: give exact pixel measurements (e.g. "18px hexagons, 6px gaps")
- Use hex codes from THIS direction's palette
- mood: matches the direction's personality

**For social copy — 3 short copy fields per direction:**

tagline: The brand's core promise in 5–10 words.
- Memorable, on-brand, platform-agnostic
- Should work as a standalone sentence or subtitle

ad_slogan: A punchy 3–6 word hero line for ads.
- Bold, imperative or evocative
- Will appear large on a 16:9 ad post

announcement_copy: 10–18 words for a brand announcement post on X.
- Sounds exciting, human, slightly cryptic
- Written as if the brand is sharing news

⚠️ COPY OVERRIDE RULE — CRITICAL:
If the user prompt contains a "PRE-WRITTEN COPY" section, those values are LOCKED.
You MUST use them verbatim in tagline / ad_slogan / announcement_copy for EVERY direction.
Do NOT alter, improve, or paraphrase them. Copy them exactly as written.
Only generate copy freely if no pre-written values are provided.

## IMAGE SPEC QUALITY GUIDELINES — CRITICAL

The specs you fill in are translated into image generation prompts. Every field affects quality.
Vague values → generic output. Specific values → high-quality brand assets.

### LOGO SPEC — Field-by-field guidance:

form (MOST IMPORTANT field):
  ✓ GOOD: "two concentric arcs, outer radius 48px with 5px stroke, inner radius 28px with 3px stroke, both open at the 7 o'clock position, creating a C-like form suggesting a coffee bean cross-section"
  ✓ GOOD: "equilateral triangle 72px per side, 8px rounded corners, vertex pointing upward, 15° clockwise tilt"
  ✗ BAD:  "a circular mark representing the brand"
  ✗ BAD:  "an organic leaf shape"

metaphor:
  ✓ GOOD: "suggests a coffee bean split to reveal a mountain terrain — dual reading of origin and harvest"
  ✗ BAD:  "represents quality and craftsmanship"

⚠ MONOCHROME — color_hex is a SINGLE hex. The logo is black/one-color on white. Never two colors.
⚠ NO TEXT — logo_type is 'symbol', 'abstract_mark', or 'lettermark'. Never a wordmark.

### PATTERN SPEC — Field-by-field guidance:

motif:
  ✓ GOOD: "botanical coffee leaf outline silhouettes, alternating sizes (24px and 16px leaf length)"
  ✗ BAD:  "coffee-themed pattern"

density_scale:
  ✓ GOOD: "each leaf 24px long, 10px wide, 12px vertical gap, 8px horizontal gap, alternating row offset by 50%"
  ✗ BAD:  "medium density"

### BACKGROUND SPEC — Field-by-field guidance:

description:
  ✓ GOOD: "misty Vietnamese highland coffee farm at dawn — rows of coffee trees descend a fog-filled valley, terracotta soil visible between rows, soft morning light catching dew on leaves"
  ✗ BAD:  "a coffee farm scene"

lighting:
  ✓ GOOD: "soft diffused morning fog light, low contrast, slight warm golden tint at the horizon edge"
  ✗ BAD:  "natural lighting"

### COPY QUALITY GUIDELINES:
tagline — must feel like it belongs on a brand website hero section
✓ GOOD: "Where every market tells a story." / "Built for those who move first."
✗ BAD: "A great brand for everyone." / "Quality and innovation."

ad_slogan — punchy, could be a billboard
✓ GOOD: "Trade smarter. Live bolder." / "Fresh finds. Bold moves."
✗ BAD: "We are the best choice for you."

announcement_copy — reads like a real tweet, 10–18 words
✓ GOOD: "Something new is here. The market experience you've been waiting for — now live."
✗ BAD: "We are excited to announce our new brand identity is ready for everyone to see."
"""


# ── Director function ─────────────────────────────────────────────────────────

def generate_directions(
    brief: BriefData,
    refinement_feedback: Optional[str] = None,
    research_context: str = "",
) -> BrandDirectionsOutput:
    """
    Call Gemini to analyze the brief and generate brand identity directions.

    Args:
        brief: Parsed brief data
        refinement_feedback: Optional human feedback for remix/adjust iterations
        research_context: Optional market research context from BrandResearcher

    Returns:
        Structured BrandDirectionsOutput with 4 directions
    """
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    user_message = brief.to_prompt_block()

    if research_context:
        user_message += f"\n\n---\n\n{research_context}"

    if refinement_feedback:
        user_message += (
            f"\n\n---\n\n## REFINEMENT REQUEST\n{refinement_feedback}\n\n"
            "Revise the directions accordingly. Keep what works, change what was requested."
        )

    console.print("\n[bold cyan]→ Gemini is analyzing the brief...[/bold cyan]")

    # ── Build contents: text + optional moodboard images ─────────────────────
    # If the brief folder contains images, send them as visual context
    moodboard_images = getattr(brief, "moodboard_images", [])
    if moodboard_images:
        parts = [types.Part.from_text(text=user_message)]
        loaded = 0
        for img_path in moodboard_images[:10]:   # cap at 10 images
            try:
                img_bytes = img_path.read_bytes()
                ext  = img_path.suffix.lower().lstrip(".")
                mime = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext or 'png'}"
                parts.append(types.Part.from_text(
                    text=f"Client moodboard reference #{loaded + 1} — "
                         "use this to inform the visual direction, especially Option 2 (Designer-Led):"
                ))
                parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
                loaded += 1
            except Exception:
                pass
        contents = parts
        console.print(f"  [dim]moodboard: {loaded} image(s) attached[/dim]")
    else:
        contents = user_message

    # Stream response — show dots for progress, accumulate full JSON
    max_retries = 3
    for attempt in range(max_retries):
        full_text = ""
        char_count = 0
        try:
            for chunk in client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=BrandDirectionsOutput,
                ),
            ):
                if chunk.text:
                    full_text += chunk.text
                    char_count += len(chunk.text)
                    # Print a dot every ~200 chars so the user sees progress
                    if char_count % 200 < len(chunk.text):
                        sys.stdout.write(".")
                        sys.stdout.flush()
        
            sys.stdout.write("\n")
            sys.stdout.flush()
        
            if not full_text:
                raise ValueError("Gemini returned no content")
        
            return BrandDirectionsOutput.model_validate_json(full_text)
            
        except Exception as e:
            sys.stdout.write("\n")
            err_str = str(e).lower()
            if "503" in err_str or "unavailable" in err_str or "overloaded" in err_str or "quota" in err_str:
                if attempt < max_retries - 1:
                    console.print(f"  [yellow]⚠ Gemini API extremely busy (503). Retrying in 5 seconds... ({attempt + 1}/{max_retries})[/yellow]")
                    import time
                    time.sleep(5)
                    continue
            raise e


# ── Display helpers ───────────────────────────────────────────────────────────

def display_directions(output: BrandDirectionsOutput) -> None:
    """Pretty-print the 4 directions to the terminal."""
    console.print(
        Panel(
            f"[italic]{output.brand_summary}[/italic]",
            title="[bold]Brand Analysis[/bold]",
            border_style="blue",
        )
    )

    type_colors = {
        "Market-Aligned": "green",
        "Designer-Led": "magenta",
        "Hybrid": "yellow",
        "Wild Card": "red",
    }

    for d in output.directions:
        color = type_colors.get(d.option_type, "white")
        palette_str = "  ".join(
            f"[bold]{s.name}[/bold] {s.hex}" for s in d.colors
        )
        body = (
            f"[bold]Type:[/bold] [{color}]{d.option_type}[/{color}]\n"
            f"[bold]Rationale:[/bold] {d.rationale}\n\n"
            f"[bold]Colors:[/bold] {palette_str}\n"
            f"[bold]Type Primary:[/bold] {d.typography_primary}\n"
            f"[bold]Type Secondary:[/bold] {d.typography_secondary}\n"
            f"[bold]Graphic Style:[/bold] {d.graphic_style}\n"
            f"[bold]Logo Concept:[/bold] {d.logo_concept}"
        )
        console.print(
            Panel(
                body,
                title=f"[bold]Option {d.option_number} — {d.direction_name}[/bold]",
                border_style=color,
            )
        )
