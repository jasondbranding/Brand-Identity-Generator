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

import os
import sys
from typing import List, Literal, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel

from .parser import BriefData

console = Console()


# ── Pydantic schema for structured Claude output ─────────────────────────────

class ColorSwatch(BaseModel):
    name: str = Field(description="Descriptive color name, e.g. 'Midnight Slate'")
    hex: str = Field(description="Hex code, e.g. '#1A2B3C'")
    role: str = Field(description="One of: primary, secondary, accent, neutral, background")


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
    background_prompt: str = Field(
        description=(
            "Gemini image generation prompt for the atmospheric background scene. "
            "MUST be 2-3 detailed sentences, minimum 40 words describing a specific scene or abstraction. "
            "NO text, NO logos, NO words of any kind in the image. "
            "Describe: exact mood, specific colors from the palette (use hex codes), texture, lighting quality "
            "(e.g. 'soft diffused light', 'dramatic side-lit'), and abstract or environmental composition. "
            "Should feel like the emotional world of the brand. "
            "Example: 'A misty mountain landscape at twilight in deep slate #2C3E50 and warm amber #F39C12, "
            "with soft volumetric light rays cutting through atmospheric haze, subtle grain texture, "
            "no focal point, horizontal panoramic composition evoking quiet confidence.'"
        )
    )
    logo_prompt: str = Field(
        description=(
            "Gemini image generation prompt for the logo concept mark. "
            "MUST be 3-4 detailed sentences, minimum 60 words describing exact visual forms. "
            "A single abstract symbol or geometric mark on a plain white background. "
            "NO text, NO letterforms, NO words — only the visual mark itself. "
            "Describe: exact shape geometry (e.g. 'equilateral triangle with rounded corners'), "
            "line weight (hairline/medium/bold), fill vs outline, visual metaphor, and color. "
            "Example: 'A single bold circular mark formed by two overlapping arcs in deep navy #1A2B4C, "
            "each arc 8px stroke weight, creating a subtle lens shape at their intersection in lighter blue #4A90D9. "
            "The form suggests a lens aperture and precision optics. Clean vector rendering, "
            "centered with 25% padding on all sides, pure white background, no shadow or gradient.'"
        )
    )
    pattern_prompt: str = Field(
        description=(
            "Gemini image generation prompt for a seamless brand pattern or texture tile. "
            "MUST be 2-3 detailed sentences, minimum 40 words with specific hex color codes from the palette. "
            "NO text, NO logos. "
            "Describe: exact motif type (e.g. 'isometric dot grid', 'overlapping hexagons', "
            "'flowing organic curves'), spacing/density (e.g. '20px gaps between elements'), "
            "colors with hex codes, scale, and mood. Should work as a background or surface texture. "
            "Example: 'A dense repeating pattern of small equilateral triangles in alternating "
            "deep navy #1A2B4C and warm white #F5F0E8, each triangle 12px per side with 2px gaps, "
            "creating a subtle optical vibration. Flat vector style, seamless tile, "
            "professional textile quality suggesting precision and structure.'"
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

**For image prompts — 3 separate prompts per direction:**

background_prompt: Write as if briefing a photographer or digital artist on the mood image.
- No text, no logos, no UI — pure atmosphere
- Specify exact colors from the palette, lighting quality (soft/dramatic/diffused), texture or surface
- Could be: abstract gradient field, macro texture, environmental scene, digital noise pattern
- Should feel like the emotional world of the brand at a glance

logo_prompt: Brief a graphic designer on a single abstract mark.
- White background, centered mark only — absolutely no text or letterforms
- Describe the exact geometric or organic form, line weight, whether it's filled/outlined
- Reference the visual metaphor (e.g. "a simplified wave form suggesting signal flow")
- Clean, scalable, distinctive

pattern_prompt: Brief a surface designer on a repeating tile.
- No text, no logos — pure pattern
- Specify the motif (chevron, dot grid, organic cells, flowing lines, etc.)
- Colors drawn directly from the palette, exact density and scale
- Mood should match the direction's personality

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

## IMAGE PROMPT QUALITY GUIDELINES — CRITICAL

The image prompts you generate are fed directly to an AI image generator. Vague prompts produce generic, unusable images. Specific, detailed prompts produce high-quality brand assets.

### LOGO PROMPT — Required elements:
✓ GOOD: "A single bold mark formed by three concentric circles in deep cobalt #0A3D91, each ring with increasing stroke weight (2px/4px/6px), creating a target-like form suggesting focus and precision. The outermost circle is 80% of the canvas width. Clean vector rendering on pure white background, centered with 20% padding, no shadow."
✗ BAD: "A circular logo representing technology and innovation"

✓ GOOD: "An asymmetric leaf form split diagonally — left half in forest green #2D6A4F solid fill, right half as an outline-only stroke in the same green, 3px weight. The leaf tilts 15° clockwise, suggesting dynamic growth. Minimalist botanical style, single element centered on white."
✗ BAD: "A nature-inspired logo with green colors"

### PATTERN PROMPT — Required elements:
✓ GOOD: "A seamless repeating grid of small diamond shapes in warm terracotta #C9614A on cream #F5EDE0, each diamond 16×10px with 8px gutters, rotated 45°. Every third diamond is hollow (outline only, 1.5px stroke). Creates a refined textile feel reminiscent of high-end stationery. Flat vector, zero noise."
✗ BAD: "A geometric pattern with warm colors"

✓ GOOD: "Overlapping circles of varying sizes (24px to 48px diameter) in translucent layers — midnight blue #0D1B2A at 60% opacity and electric cyan #00D4FF at 40% opacity. 6px gaps between circle edges. The overlapping intersections create darker accent zones. Seamless tile, contemporary tech aesthetic."
✗ BAD: "Abstract circles in brand colors"

### BACKGROUND PROMPT — Required elements:
✓ GOOD: "A wide cinematic landscape at golden hour: rolling desert dunes in warm ochre #C8972A fading to deep rust #8B2500 at the horizon, with a single shaft of amber light cutting diagonally across the frame. Soft atmospheric haze reduces contrast at distance. Ultra-wide 16:9 format, photorealistic rendering, no focal subjects."
✗ BAD: "A warm desert background with golden light"

✓ GOOD: "Abstract macro texture of brushed aluminum in cool silver #C0C0C0 and anthracite #2A2A2A, lit from the left with hard directional light creating deep parallel grooves and specular highlights. The texture fills the entire frame edge-to-edge. Photographic quality, slight depth of field blur at the far right."
✗ BAD: "A metallic texture background"

### Universal rules for ALL prompts:
1. Include exact hex color codes from the palette
2. Specify exact sizes, weights, proportions where applicable
3. Name the visual style explicitly (vector, photorealistic, digital painting, etc.)
4. Say "absolutely no text, no words, no letters, no typography anywhere"
5. Minimum word counts: logo_prompt ≥60 words, pattern_prompt ≥40 words, background_prompt ≥40 words

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

    # Stream response — show dots for progress, accumulate full JSON
    full_text = ""
    char_count = 0

    for chunk in client.models.generate_content_stream(
        model="gemini-2.5-flash",
        contents=user_message,
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
