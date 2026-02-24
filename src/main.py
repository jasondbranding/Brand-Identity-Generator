"""
Brand Identity Generator — Main Pipeline

Usage:
  python -m src.main --mode full  --brief briefs/full
  python -m src.main --mode quick --brief briefs/quick
  python -m src.main --mode full  --brief briefs/full --no-images
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from google import genai
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule

from .parser import parse_brief
from .director import BrandDirection, BrandDirectionsOutput, generate_directions, display_directions
from .generator import generate_all_assets
from .mockup_compositor import composite_all_mockups
from .compositor import build_all_stylescapes

load_dotenv()

console = Console()

OUTPUTS_ROOT = Path("outputs")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Brand Identity Generator — AI Creative Director"
    )
    parser.add_argument(
        "--mode",
        choices=["full", "quick"],
        default="full",
        help="full = 4 directions + moodboard; quick = 2 directions, no moodboard",
    )
    parser.add_argument(
        "--brief",
        default="briefs/full",
        help="Path to brief directory (containing brief.md)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: outputs/<timestamp>)",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Skip image generation (directions only)",
    )
    return parser.parse_args()


# ── Output helpers ────────────────────────────────────────────────────────────

def save_directions_md(output: BrandDirectionsOutput, output_dir: Path) -> Path:
    """Save directions as a formatted markdown summary."""
    lines = [
        "# Brand Identity Directions",
        f"\n_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n",
        "---\n",
        "## Brand Analysis",
        f"\n{output.brand_summary}\n",
        "---\n",
    ]

    for d in output.directions:
        palette = " | ".join(f"{c.name} `{c.hex}`" for c in d.colors)
        lines += [
            f"## Option {d.option_number} — {d.direction_name}",
            f"**Type:** {d.option_type}  \n",
            f"**Rationale:** {d.rationale}\n",
            f"**Color Palette:** {palette}  \n",
            f"**Typography:** {d.typography_primary} / {d.typography_secondary}  \n",
            f"**Graphic Style:** {d.graphic_style}\n",
            f"**Logo Concept:** {d.logo_concept}\n",
            "---\n",
        ]

    md_path = output_dir / "directions.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def save_directions_json(output: BrandDirectionsOutput, output_dir: Path) -> Path:
    """Save raw directions JSON for downstream processing."""
    json_path = output_dir / "directions.json"
    json_path.write_text(output.model_dump_json(indent=2), encoding="utf-8")
    return json_path


# ── Intent classifier ─────────────────────────────────────────────────────────

def _parse_classification(
    raw: str,
    directions: List[BrandDirection],
) -> Tuple[str, object]:
    """
    Parse a single-line Gemini classification response.
    Returns one of:
      ("SELECT", int)    — option number to confirm
      ("REMIX",  str)    — instructions to remix
      ("ADJUST", str)    — instructions to adjust
      ("QUIT",   None)
    """
    line = raw.strip().split("\n")[0].strip()
    upper = line.upper()

    if upper == "QUIT":
        return ("QUIT", None)

    if upper.startswith("SELECT:"):
        try:
            num = int(line.split(":", 1)[1].strip())
            valid = {d.option_number for d in directions}
            if num in valid:
                return ("SELECT", num)
        except (ValueError, IndexError):
            pass

    if upper.startswith("REMIX:"):
        instructions = line.split(":", 1)[1].strip()
        return ("REMIX", instructions or "Remix directions")

    if upper.startswith("ADJUST:"):
        instructions = line.split(":", 1)[1].strip()
        return ("ADJUST", instructions or "Adjust direction")

    # Gemini returned something unexpected — treat whole response as ADJUST
    return ("ADJUST", raw[:400])


def _gemini_classify(
    user_input: str,
    directions: List[BrandDirection],
) -> Tuple[str, object]:
    """Call gemini-2.5-flash to classify free-form user feedback."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return ("ADJUST", user_input)

    direction_list = "\n".join(
        f"  Option {d.option_number}: {d.direction_name}" for d in directions
    )

    prompt = f"""\
Classify this user feedback about brand identity directions into exactly one of these formats:

SELECT:<number>        — user wants to confirm/finalize a specific direction
REMIX:<instructions>   — user wants to combine elements from multiple directions
ADJUST:<instructions>  — user wants to modify or refine one direction
QUIT                   — user wants to exit without selecting

Available directions:
{direction_list}

User said: "{user_input}"

Rules:
- If the user is satisfied with one direction and wants to proceed → SELECT
- If the user mentions combining/mixing/taking from multiple options → REMIX
- If the user wants changes to a direction → ADJUST
- If the user says quit/exit/stop/no → QUIT
- For ADJUST/REMIX, rephrase the instruction clearly in English

Respond with ONLY the classification on a single line. Examples:
SELECT:2
ADJUST:Option 1 but with warmer colors and less blue in the palette
REMIX:Take the color palette from Option 1 and the typography from Option 3
QUIT"""

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = (response.text or "").strip()
        return _parse_classification(raw, directions)
    except Exception as exc:
        console.print(f"  [yellow]⚠ Gemini classify failed ({exc}) — treating as ADJUST[/yellow]")
        return ("ADJUST", user_input)


def _classify_intent(
    user_input: str,
    directions: List[BrandDirection],
) -> Tuple[str, object]:
    """
    Classify free-form user input without always hitting the API.

    1. Fast string-matching for obvious patterns.
    2. Gemini fallback for everything else.
    """
    text = user_input.strip()
    lower = text.lower()

    # ── Hard exits ────────────────────────────────────────────────────────────
    if lower in {"q", "quit", "exit", "thoát", "thoat", "bye"}:
        return ("QUIT", None)

    # ── Explicit select patterns ───────────────────────────────────────────────
    select_pats = [
        r"(?:select|choose|confirm|go\s+with|finalize|pick|use|take|chọn|xác\s+nhận)\s+(?:option\s*)?(\d+)",
        r"(?:option|opt)\s*(\d+)\s+(?:is\s+)?(?:good|great|perfect|ok|fine|looks?\s+good|tốt|ổn)",
        r"^(?:option\s*)?(\d+)$",   # bare number "2" or "option 2"
        r"^done\s*(\d+)$",          # "done 3"
    ]
    valid_nums = {d.option_number for d in directions}
    for pat in select_pats:
        m = re.search(pat, lower)
        if m:
            try:
                num = int(m.group(1))
                if num in valid_nums:
                    return ("SELECT", num)
            except (ValueError, IndexError):
                pass

    # ── "done" / "perfect" with no number → Gemini to disambiguate ───────────
    # Fall through to Gemini for everything else
    return _gemini_classify(user_input, directions)


# ── Human-in-the-loop ─────────────────────────────────────────────────────────

def refinement_loop(
    brief,
    initial_output: BrandDirectionsOutput,
    output_dir: Path,
    generate_imgs: bool,
) -> BrandDirectionsOutput:
    """
    Interactive refinement loop with free-form natural language input.

    User can type anything in English or Vietnamese. Intent is classified
    by fast string matching first, then Gemini as fallback, into:
      SELECT — confirm a direction
      REMIX  — combine elements from multiple directions
      ADJUST — modify a direction
      QUIT   — exit
    """
    current_output = initial_output
    iteration = 0

    while True:
        console.print(Rule("[bold]Human-in-the-Loop — Phase 1 Review[/bold]"))

        opts = "  ".join(
            f"[bold cyan]{d.option_number}[/bold cyan] {d.direction_name}"
            for d in current_output.directions
        )
        console.print(f"\n  Directions: {opts}\n")
        console.print(
            "  [dim]Describe what you want, e.g.:\n"
            "    'Option 2 looks good but make the palette warmer'\n"
            "    'Mix the logo style from 1 with the colors from 3'\n"
            "    'go with option 2' / 'chọn option 1' / 'quit'[/dim]\n"
        )

        user_input = Prompt.ask("💬 Your feedback").strip()
        if not user_input:
            continue

        console.print("  [dim]→ Classifying...[/dim] ", end="")
        intent, payload = _classify_intent(user_input, current_output.directions)
        console.print(f"[bold]{intent}[/bold]" + (f": {payload}" if payload else ""))

        # ── QUIT ──────────────────────────────────────────────────────────────
        if intent == "QUIT":
            console.print("[dim]Exiting without selection.[/dim]")
            break

        # ── SELECT ────────────────────────────────────────────────────────────
        elif intent == "SELECT":
            option_number = int(payload)
            selected = next(
                (d for d in current_output.directions if d.option_number == option_number),
                None,
            )
            if selected is None:
                console.print(
                    f"  [yellow]⚠ Option {option_number} not found. "
                    f"Available: {[d.option_number for d in current_output.directions]}[/yellow]"
                )
                continue
            console.print(
                Panel(
                    f"[bold green]✓ Direction confirmed:[/bold green] "
                    f"Option {selected.option_number} — {selected.direction_name}\n\n"
                    f"{selected.rationale}",
                    title="Direction Selected",
                    border_style="green",
                )
            )
            _save_selection(selected, output_dir)
            break

        # ── REMIX / ADJUST ────────────────────────────────────────────────────
        elif intent in ("REMIX", "ADJUST"):
            instructions = str(payload)
            label = "Remix" if intent == "REMIX" else "Adjust"
            console.print(f"\n[bold cyan]→ {label}: {instructions}[/bold cyan]")

            iteration += 1
            console.print(
                f"[bold cyan]→ Regenerating directions (iteration {iteration})...[/bold cyan]"
            )

            t0 = time.time()
            current_output = generate_directions(brief, refinement_feedback=instructions)
            console.print(f"  [green]✓ Directions in {time.time() - t0:.1f}s[/green]\n")

            display_directions(current_output)
            save_directions_md(current_output, output_dir)
            save_directions_json(current_output, output_dir)

            if generate_imgs:
                iter_dir = output_dir / f"iteration_{iteration}"

                t1 = time.time()
                all_assets = generate_all_assets(
                    current_output.directions, output_dir=iter_dir
                )
                console.print(f"  [green]✓ Images in {time.time() - t1:.1f}s[/green]")

                t_mock = time.time()
                mockup_results = composite_all_mockups(all_assets)
                for num, composited in mockup_results.items():
                    all_assets[num].mockups = composited
                console.print(f"  [green]✓ Mockups in {time.time() - t_mock:.1f}s[/green]")

                t2 = time.time()
                stylescape_paths = build_all_stylescapes(all_assets, output_dir=iter_dir)
                console.print(f"  [green]✓ Stylescapes in {time.time() - t2:.1f}s[/green]")
                for num, path in stylescape_paths.items():
                    console.print(f"    Option {num}: {path}")

        # ── Unknown (shouldn't happen, but be safe) ───────────────────────────
        else:
            console.print("  [yellow]⚠ Could not understand intent — please rephrase.[/yellow]")

    return current_output


def _save_selection(selected, output_dir: Path) -> None:
    """Save the confirmed direction to a selection.json file."""
    selection_path = output_dir / "selection.json"
    selection_path.write_text(
        json.dumps(selected.model_dump(), indent=2), encoding="utf-8"
    )
    console.print(f"  [dim]Saved → {selection_path}[/dim]")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    _check_env()
    args = parse_args()
    pipeline_start = time.time()

    # Set up output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output) if args.output else OUTPUTS_ROOT / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    console.print(Rule("[bold magenta]Brand Identity Generator[/bold magenta]"))
    console.print(
        f"  Mode: [bold]{args.mode.upper()}[/bold]  |  "
        f"Brief: [bold]{args.brief}[/bold]  |  "
        f"Output: [bold]{output_dir}[/bold]"
    )

    # ── Step 1: Parse brief ──────────────────────────────────────────────────
    console.print("\n[bold]Step 1/4 — Parsing brief[/bold]")
    brief = parse_brief(args.brief, mode=args.mode)
    console.print(f"  [green]✓[/green] Loaded brief ({args.mode} mode, {len(brief.keywords)} keywords)")

    # ── Step 2: Generate directions via Gemini ───────────────────────────────
    console.print("\n[bold]Step 2/4 — Generating brand directions (Gemini)[/bold]")
    t0 = time.time()
    directions_output = generate_directions(brief)
    console.print(f"  [green]✓ Done in {time.time() - t0:.1f}s[/green]")

    display_directions(directions_output)

    md_path = save_directions_md(directions_output, output_dir)
    json_path = save_directions_json(directions_output, output_dir)
    console.print(f"\n  [dim]Saved: {md_path}  |  {json_path}[/dim]")

    # ── Step 3: Generate images ───────────────────────────────────────────────
    stylescape_paths: dict = {}
    if not args.no_images:
        console.print("\n[bold]Step 3/4 — Generating images (Gemini)[/bold]")

        t1 = time.time()
        all_assets = generate_all_assets(
            directions_output.directions, output_dir=output_dir
        )
        console.print(f"\n  [green]✓ {sum(1 for a in all_assets.values() if a.background)} background(s), "
                      f"{sum(1 for a in all_assets.values() if a.logo)} logo(s), "
                      f"{sum(1 for a in all_assets.values() if a.pattern)} pattern(s) — "
                      f"{time.time() - t1:.1f}s[/green]")

        # ── Step 3b: Composite mockups ────────────────────────────────────────
        console.print("\n[bold]Step 3b/4 — Compositing mockups (Pillow)[/bold]")
        t_mock = time.time()
        mockup_results = composite_all_mockups(all_assets)
        for num, composited in mockup_results.items():
            all_assets[num].mockups = composited
        n_mockups = sum(len(v) for v in mockup_results.values())
        console.print(
            f"  [green]✓ {n_mockups} composited mockup(s) across "
            f"{len(mockup_results)} direction(s) — {time.time() - t_mock:.1f}s[/green]"
        )

        # ── Step 4: Assemble stylescapes ──────────────────────────────────────
        console.print("\n[bold]Step 4/4 — Assembling stylescapes (Pillow)[/bold]")
        t2 = time.time()
        stylescape_paths = build_all_stylescapes(all_assets, output_dir=output_dir)
        console.print(f"  [green]✓ {len(stylescape_paths)} stylescape(s) assembled — {time.time() - t2:.1f}s[/green]")
        for num, path in stylescape_paths.items():
            console.print(f"    Option {num}: {path}")
    else:
        console.print("\n  [dim]Image generation skipped (--no-images)[/dim]")

    n_directions = len(directions_output.directions)
    total_elapsed = time.time() - pipeline_start
    console.print(
        Panel(
            f"{n_directions} direction(s) generated in [bold]{total_elapsed:.0f}s[/bold]\n"
            f"Outputs saved to: [bold]{output_dir}[/bold]",
            title="[bold green]Phase 1 Complete[/bold green]",
            border_style="green",
        )
    )

    # ── Human-in-the-loop refinement ─────────────────────────────────────────
    refinement_loop(
        brief=brief,
        initial_output=directions_output,
        output_dir=output_dir,
        generate_imgs=not args.no_images,
    )


def _check_env() -> None:
    """Check required environment variables."""
    if not os.environ.get("GEMINI_API_KEY"):
        console.print("[bold red]Error:[/bold red] GEMINI_API_KEY not set.")
        console.print("Create a .env file from .env.example and add your keys.")
        sys.exit(1)


if __name__ == "__main__":
    main()
