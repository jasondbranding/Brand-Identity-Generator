"""
validate.py — Brief market context validator with Gemini inference.

Flow:
  1. Parse geography + competitors from brief (if present)
  2. If any key fields missing → Gemini infers them from brief text
  3. Display result to user with source labels (from brief / inferred)
  4. User confirms, edits, or skips
  5. Returns MarketContext for injection into researcher prompt

Usage:
  from .validate import BriefValidator
  market_ctx = BriefValidator(api_key).validate_and_confirm(brief)
  # market_ctx.to_research_prompt() → string for researcher
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from google import genai
from google.genai import types
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich import box

from .parser import BriefData

console = Console()


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class MarketContext:
    """Confirmed market context for competitive research."""
    geography: str = ""
    direct_competitors: List[str] = field(default_factory=list)
    aspirational_brands: List[str] = field(default_factory=list)
    avoid_brands: List[str] = field(default_factory=list)

    # Source tracking: "brief" | "inferred" | "user"
    _geography_src: str = field(default="", repr=False)
    _competitors_src: str = field(default="", repr=False)
    _aspirational_src: str = field(default="", repr=False)
    _avoid_src: str = field(default="", repr=False)

    confirmed: bool = False

    def is_complete(self) -> bool:
        """True if both geography and direct competitors are present."""
        return bool(self.geography and self.direct_competitors)

    def missing_fields(self) -> List[str]:
        missing = []
        if not self.geography:
            missing.append("geography")
        if not self.direct_competitors:
            missing.append("direct competitors")
        return missing

    def to_research_prompt(self) -> str:
        """Format as a confirmed context block for injection into researcher."""
        if not self.confirmed or (not self.geography and not self.direct_competitors):
            return ""

        lines = ["## CONFIRMED MARKET CONTEXT\n"]
        if self.geography:
            lines.append(f"Geography / Target Market: {self.geography}")
        if self.direct_competitors:
            lines.append(f"Direct Competitors: {', '.join(self.direct_competitors)}")
            lines.append(
                "→ Research each competitor's actual visual identity. "
                "Analyse their colour palette, typography, logo style, and overall tone."
            )
        if self.aspirational_brands:
            lines.append(
                f"Aspirational Visual References: {', '.join(self.aspirational_brands)} "
                "(Client admires these brands' design language)"
            )
        if self.avoid_brands:
            lines.append(
                f"Avoid resembling: {', '.join(self.avoid_brands)} "
                "(Client explicitly does NOT want to look like these)"
            )
        lines.append(
            "\n⚠️  The above context is CONFIRMED by the client. "
            "Use it as ground truth for Option 1 (Market-Aligned) direction."
        )
        return "\n".join(lines)


# ── Gemini inference prompt ───────────────────────────────────────────────────

INFERENCE_PROMPT = """\
You are a senior brand strategist. Analyze this brand brief and infer the missing market context.

## Brand Brief:
{brief_text}

## Keywords: {keywords}

## Already known (do NOT repeat these, only fill what's MISSING):
{known_context}

Please infer ONLY the missing fields:
- geography: Where does this brand primarily operate? (e.g. "Vietnam, targeting SEA mid-market" or "Global, English-speaking B2B")
- direct_competitors: 3–6 real company names that are direct competitors in this exact market
- aspirational_brands: Design/brand references the client likely admires (from brief clues)
- avoid_brands: Brands whose visual aesthetic the client likely wants to differentiate from

Be specific. Name real companies. Do not use generic placeholders.

Return ONLY valid JSON — no markdown fences, no explanation:
{{
  "geography": "...",
  "direct_competitors": ["...", "..."],
  "aspirational_brands": ["...", "..."],
  "avoid_brands": ["...", "..."],
  "confidence": "high|medium|low",
  "reasoning": "1-2 sentences explaining your inferences"
}}
"""


# ── Parser helpers ────────────────────────────────────────────────────────────

def _parse_competitors_section(raw: str) -> Tuple[List[str], List[str], List[str]]:
    """
    Parse a competitors section into (direct, aspirational, avoid) lists.

    Supports two formats:
      Structured:
        Direct: project44, Flexport
        Aspirational: Linear, Stripe
        Avoid: Oracle, SAP

      Unstructured (single line / paragraph):
        FedEx Logistics, Project44, Flexport — all heavy enterprise-feeling
    """
    direct: List[str] = []
    aspirational: List[str] = []
    avoid: List[str] = []

    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    has_labels = any(
        re.match(r"^(Direct|Aspirational|Avoid|Do not|Don.t)\s*:", line, re.IGNORECASE)
        for line in lines
    )

    if has_labels:
        for line in lines:
            m = re.match(r"^(Direct|Aspirational|Avoid|Do not|Don.t)\s*:\s*(.+)", line, re.IGNORECASE)
            if m:
                label = m.group(1).lower()
                # Strip trailing commentary after first em-dash BEFORE splitting by comma
                raw_value = re.split(r"\s*[—–]", m.group(2))[0]
                names = [n.strip() for n in re.split(r"[,;]", raw_value) if n.strip()]
                # Also strip anything in parens from individual names
                names = [re.split(r"\s*\(", n)[0].strip() for n in names if n]
                if label == "direct":
                    direct = names
                elif label == "aspirational":
                    aspirational = names
                else:
                    avoid = names
    else:
        # Unstructured: treat first sentence/line as direct competitors
        first_line = lines[0] if lines else ""
        # Split on commas, stop at em-dash or long description
        parts = re.split(r"[,;]", re.split(r"\s*[—–]", first_line)[0])
        direct = [p.strip() for p in parts if p.strip()]

    return direct, aspirational, avoid


# ── Validator ─────────────────────────────────────────────────────────────────

class BriefValidator:
    """
    Validates brief for market context completeness.
    Infers missing fields via Gemini, then asks user to confirm.
    """

    def __init__(self, api_key: str) -> None:
        self.client = genai.Client(api_key=api_key)

    # ── Step 1: Extract from brief ─────────────────────────────────────────

    def _extract_from_brief(self, brief: BriefData) -> MarketContext:
        """Pull geography and competitors from parsed brief sections."""
        ctx = MarketContext()
        text = brief.brief_text

        # Geography: ## Geography or ## Market Context
        geo_pattern = r"##\s*(Geography|Market Context|Target Market|Market)\s*\n(.*?)(?=\n##|\Z)"
        m = re.search(geo_pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            geo_text = m.group(2).strip()
            # Take first meaningful line
            for line in geo_text.splitlines():
                line = line.strip().lstrip("-• ")
                if line and not line.startswith("#"):
                    ctx.geography = line
                    ctx._geography_src = "brief"
                    break

        # Competitors: ## Competitors
        comp_pattern = r"##\s*(Competitors|Competition|Competitive Landscape)\s*\n(.*?)(?=\n##|\Z)"
        m = re.search(comp_pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            raw = m.group(2).strip()
            if raw:
                direct, aspirational, avoid = _parse_competitors_section(raw)
                ctx.direct_competitors = direct
                ctx.aspirational_brands = aspirational
                ctx.avoid_brands = avoid
                if direct:
                    ctx._competitors_src = "brief"
                if aspirational:
                    ctx._aspirational_src = "brief"
                if avoid:
                    ctx._avoid_src = "brief"

        # Also check ## Moodboard for aspirational / avoid clues if not found
        if not ctx.aspirational_brands and brief.moodboard_notes:
            # e.g. "Think Linear, Stripe, Vercel" → extract brand names
            brands = re.findall(r"\b(Linear|Stripe|Vercel|Notion|Figma|Loom|"
                                r"Apple|Google|Airbnb|Spotify|Slack|Intercom|"
                                r"Airtable|Superhuman|Craft|Framer)\b",
                                brief.moodboard_notes, re.IGNORECASE)
            if brands:
                ctx.aspirational_brands = list(dict.fromkeys(brands))  # dedupe, preserve order
                ctx._aspirational_src = "brief (moodboard)"

        return ctx

    # ── Step 2: Gemini inference ───────────────────────────────────────────

    def _infer_missing(self, brief: BriefData, partial: MarketContext) -> MarketContext:
        """Use Gemini to fill in missing fields from partial context."""

        known_parts = []
        if partial.geography:
            known_parts.append(f"Geography: {partial.geography}")
        if partial.direct_competitors:
            known_parts.append(f"Direct Competitors: {', '.join(partial.direct_competitors)}")
        if partial.aspirational_brands:
            known_parts.append(f"Aspirational: {', '.join(partial.aspirational_brands)}")
        if partial.avoid_brands:
            known_parts.append(f"Avoid: {', '.join(partial.avoid_brands)}")
        known_context = "\n".join(known_parts) if known_parts else "Nothing known yet"

        prompt = INFERENCE_PROMPT.format(
            brief_text=brief.brief_text[:2500],
            keywords=", ".join(brief.keywords[:15]),
            known_context=known_context,
        )

        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            raw = (response.text or "").strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.rsplit("```", 1)[0]

            data = json.loads(raw)

            result = MarketContext(
                geography=partial.geography,
                direct_competitors=list(partial.direct_competitors),
                aspirational_brands=list(partial.aspirational_brands),
                avoid_brands=list(partial.avoid_brands),
                _geography_src=partial._geography_src,
                _competitors_src=partial._competitors_src,
                _aspirational_src=partial._aspirational_src,
                _avoid_src=partial._avoid_src,
            )

            if not result.geography and data.get("geography"):
                result.geography = data["geography"]
                result._geography_src = "inferred"

            if not result.direct_competitors and data.get("direct_competitors"):
                result.direct_competitors = [
                    str(c) for c in data["direct_competitors"] if c
                ]
                result._competitors_src = "inferred"

            if not result.aspirational_brands and data.get("aspirational_brands"):
                result.aspirational_brands = [
                    str(b) for b in data["aspirational_brands"] if b
                ]
                result._aspirational_src = "inferred"

            if not result.avoid_brands and data.get("avoid_brands"):
                result.avoid_brands = [str(b) for b in data["avoid_brands"] if b]
                result._avoid_src = "inferred"

            # Log reasoning for transparency
            if data.get("reasoning"):
                console.print(f"  [dim]Gemini reasoning: {data['reasoning']}[/dim]")

            return result

        except Exception as e:
            console.print(f"  [yellow]⚠ Inference failed: {e}[/yellow]")
            return partial

    # ── Step 3: Display + interactive confirmation ─────────────────────────

    def _display_context(self, ctx: MarketContext) -> None:
        """Render market context table with source labels."""

        def src_badge(src: str) -> str:
            if src == "brief":
                return "[green]from brief[/green]"
            elif src == "brief (moodboard)":
                return "[green]from moodboard[/green]"
            elif src == "inferred":
                return "[yellow]Gemini inferred[/yellow]"
            elif src == "user":
                return "[cyan]you entered[/cyan]"
            return "[dim]—[/dim]"

        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("Field", style="bold", width=18)
        table.add_column("Value", width=52)
        table.add_column("Source", width=20)

        geo_val = ctx.geography or "[dim](not found)[/dim]"
        table.add_row("🌍 Geography", geo_val, src_badge(ctx._geography_src))

        comp_val = ", ".join(ctx.direct_competitors) if ctx.direct_competitors else "[dim](not found)[/dim]"
        table.add_row("🏢 Direct competitors", comp_val, src_badge(ctx._competitors_src))

        asp_val = ", ".join(ctx.aspirational_brands) if ctx.aspirational_brands else "[dim]none[/dim]"
        table.add_row("✨ Aspirational", asp_val, src_badge(ctx._aspirational_src))

        avoid_val = ", ".join(ctx.avoid_brands) if ctx.avoid_brands else "[dim]none[/dim]"
        table.add_row("🚫 Avoid", avoid_val, src_badge(ctx._avoid_src))

        console.print(Panel(
            table,
            title="[bold cyan]Market Context[/bold cyan]",
            subtitle="[dim]used to guide competitive research[/dim]",
            border_style="cyan",
        ))

    def _edit_field(self, label: str, current: str) -> str:
        """Prompt user to enter a new value for a single field."""
        console.print(f"  Current {label}: [dim]{current or '(empty)'}[/dim]")
        val = Prompt.ask(f"  New {label} (Enter to keep)", default=current)
        return val.strip()

    def _edit_list_field(self, label: str, current: List[str]) -> List[str]:
        """Prompt user to enter a comma-separated list."""
        current_str = ", ".join(current) if current else ""
        console.print(f"  Current {label}: [dim]{current_str or '(empty)'}[/dim]")
        val = Prompt.ask(f"  New {label} — comma-separated (Enter to keep)", default=current_str)
        val = val.strip()
        if not val:
            return current
        return [v.strip() for v in val.split(",") if v.strip()]

    def _interactive_edit(self, ctx: MarketContext) -> MarketContext:
        """Allow user to edit any field interactively."""
        console.print("\n  [bold]Edit fields[/bold] (press Enter to keep current value)\n")

        ctx.geography = self._edit_field("geography", ctx.geography)
        ctx._geography_src = "user"

        ctx.direct_competitors = self._edit_list_field("direct competitors", ctx.direct_competitors)
        ctx._competitors_src = "user"

        ctx.aspirational_brands = self._edit_list_field("aspirational brands", ctx.aspirational_brands)
        ctx._aspirational_src = "user"

        ctx.avoid_brands = self._edit_list_field("avoid brands (visual)", ctx.avoid_brands)
        ctx._avoid_src = "user"

        return ctx

    # ── Public API ─────────────────────────────────────────────────────────

    def validate_and_confirm(self, brief: BriefData) -> MarketContext:
        """
        Full validation flow:
          1. Extract from brief
          2. Infer missing fields with Gemini (if needed)
          3. Display to user + ask confirm/edit/skip
          4. Return confirmed MarketContext

        Returns an empty (unconfirmed) MarketContext if user skips.
        """
        console.print("\n[bold cyan]Step 1c — Market Context Validation[/bold cyan]")

        # Step 1: Extract from brief
        ctx = self._extract_from_brief(brief)
        missing = ctx.missing_fields()

        if missing:
            console.print(
                f"  [dim]Brief missing: {', '.join(missing)} — "
                f"asking Gemini to infer...[/dim]"
            )
            ctx = self._infer_missing(brief, ctx)
        else:
            console.print("  [dim]All key fields found in brief[/dim]")

        # Step 2: Display
        self._display_context(ctx)

        # Step 3: Interactive confirmation (only when running in a real terminal)
        if not sys.stdin.isatty():
            # Non-interactive (CI / piped): auto-confirm
            console.print("  [dim]Non-interactive mode — auto-confirming context[/dim]")
            ctx.confirmed = True
            return ctx

        choice = Prompt.ask(
            "\n  [C] Confirm  /  [E] Edit fields  /  [S] Skip research",
            choices=["c", "e", "s", "C", "E", "S"],
            default="c",
            show_choices=False,
        ).lower()

        if choice == "s":
            console.print("  [dim]Market context skipped — research will use brief text only[/dim]")
            return MarketContext(confirmed=False)

        if choice == "e":
            ctx = self._interactive_edit(ctx)
            console.print()
            self._display_context(ctx)

        ctx.confirmed = True
        console.print("  [green]✓[/green] Market context confirmed\n")
        return ctx
