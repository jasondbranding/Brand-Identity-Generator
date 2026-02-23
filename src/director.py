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
    image_prompt: str = Field(
        description=(
            "A detailed, art-director-quality prompt for Gemini image generation. "
            "Describe a stylescape layout: brand color swatches arranged visually, "
            "typography specimens, graphic element samples, logo concept sketched in, "
            "and 1–2 product/context mockups. Specify mood, lighting, and composition. "
            "Minimum 80 words."
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

**For image prompts:**
Write as if briefing a top motion designer on the stylescape composition. Describe:
- The overall color field and mood
- How typography is displayed (specimen, weights, pairings in use)
- Graphic element samples in the layout
- A gestural logo concept (not final, but directional)
- 1–2 product mockup contexts (social post, dashboard screen, packaging, etc.)
- Lighting, texture, and compositional energy

Be specific. Vague prompts produce generic images.
"""


# ── Director function ─────────────────────────────────────────────────────────

def generate_directions(
    brief: BriefData,
    refinement_feedback: Optional[str] = None,
) -> BrandDirectionsOutput:
    """
    Call Gemini to analyze the brief and generate brand identity directions.

    Args:
        brief: Parsed brief data
        refinement_feedback: Optional human feedback for remix/adjust iterations

    Returns:
        Structured BrandDirectionsOutput with 4 directions
    """
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    user_message = brief.to_prompt_block()

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
