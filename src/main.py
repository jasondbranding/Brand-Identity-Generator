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
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule

from .parser import parse_brief
from .director import BrandDirectionsOutput, generate_directions, display_directions
from .visualizer import generate_images

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


# ── Human-in-the-loop ─────────────────────────────────────────────────────────

def refinement_loop(
    brief,
    initial_output: BrandDirectionsOutput,
    output_dir: Path,
    generate_imgs: bool,
) -> BrandDirectionsOutput:
    """
    Interactive refinement loop after Phase 1 stylescape review.

    Options:
      s  — Select a direction (confirm it)
      r  — Remix (e.g. "Take color from Option 1, typography from Option 3")
      a  — Adjust (e.g. "Option 2 but less corporate")
      q  — Quit
    """
    current_output = initial_output
    iteration = 0

    while True:
        console.print(Rule("[bold]Human-in-the-Loop — Phase 1 Review[/bold]"))
        console.print(
            "\nWhat would you like to do?\n"
            "  [bold]s[/bold] — Select a direction\n"
            "  [bold]r[/bold] — Remix directions (combine elements)\n"
            "  [bold]a[/bold] — Adjust a direction\n"
            "  [bold]q[/bold] — Quit\n"
        )

        action = Prompt.ask("Action", choices=["s", "r", "a", "q"], default="s")

        if action == "q":
            console.print("[dim]Exiting without selection.[/dim]")
            break

        elif action == "s":
            nums = [str(d.option_number) for d in current_output.directions]
            choice = Prompt.ask(f"Select direction", choices=nums)
            selected = next(d for d in current_output.directions if str(d.option_number) == choice)
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

        elif action in ("r", "a"):
            label = "Remix instructions" if action == "r" else "Adjustment instructions"
            hint = (
                "e.g. 'Take the color palette from Option 1, typography from Option 3'"
                if action == "r"
                else "e.g. 'Option 2 but warmer and less corporate'"
            )
            console.print(f"[dim]{hint}[/dim]")
            feedback = Prompt.ask(label)

            if not feedback.strip():
                continue

            iteration += 1
            console.print(f"\n[bold cyan]→ Regenerating directions (iteration {iteration})...[/bold cyan]")

            start = time.time()
            current_output = generate_directions(brief, refinement_feedback=feedback)
            elapsed = time.time() - start

            console.print(f"  [green]✓ Done in {elapsed:.1f}s[/green]\n")
            display_directions(current_output)

            # Save updated outputs
            save_directions_md(current_output, output_dir)
            save_directions_json(current_output, output_dir)

            if generate_imgs:
                img_dir = output_dir / "images" / f"iteration_{iteration}"
                generate_images(current_output, output_dir=img_dir)

    return current_output


def _save_selection(selected, output_dir: Path) -> None:
    """Save the confirmed direction to a selection.json file."""
    selection_path = output_dir / "selection.json"
    import json
    selection_path.write_text(
        json.dumps(selected.model_dump(), indent=2), encoding="utf-8"
    )
    console.print(f"  [dim]Saved → {selection_path}[/dim]")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    _check_env()
    args = parse_args()

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
    console.print("\n[bold]Step 1/3 — Parsing brief[/bold]")
    brief = parse_brief(args.brief, mode=args.mode)
    console.print(f"  [green]✓[/green] Loaded brief ({args.mode} mode, {len(brief.keywords)} keywords)")

    # ── Step 2: Generate directions via Claude ───────────────────────────────
    console.print("\n[bold]Step 2/3 — Generating brand directions (Claude)[/bold]")
    start = time.time()
    directions_output = generate_directions(brief)
    elapsed = time.time() - start
    console.print(f"  [green]✓ Done in {elapsed:.1f}s[/green]")

    display_directions(directions_output)

    # Save Phase 1 outputs
    md_path = save_directions_md(directions_output, output_dir)
    json_path = save_directions_json(directions_output, output_dir)
    console.print(f"\n  [dim]Saved: {md_path}  |  {json_path}[/dim]")

    # ── Step 3: Generate images via Gemini ───────────────────────────────────
    if not args.no_images:
        console.print("\n[bold]Step 3/3 — Generating stylescape images (Gemini)[/bold]")
        img_start = time.time()
        image_paths = generate_images(directions_output, output_dir=output_dir / "images")
        img_elapsed = time.time() - img_start
        console.print(f"\n  [green]✓ {len(image_paths)} images generated in {img_elapsed:.1f}s[/green]")
        for num, path in image_paths.items():
            console.print(f"    Option {num}: {path}")
    else:
        console.print("\n  [dim]Image generation skipped (--no-images)[/dim]")
        image_paths = {}

    total_elapsed = time.time() - start
    console.print(
        Panel(
            f"4 directions generated in [bold]{total_elapsed:.0f}s[/bold]\n"
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
