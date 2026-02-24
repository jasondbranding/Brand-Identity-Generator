"""
Visualizer — Phase 2: Illustrator auto-trace export.

Called ONLY after the user has selected a final brand direction.
Takes the confirmed raster assets and produces:

  - SVG logo (via Illustrator auto-trace JSX script)
  - Vector pattern tile
  - Brand guidelines PDF export

Phase 1 stylescape generation is handled by generator.py + compositor.py.
This module is a stub — Illustrator integration is not yet implemented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console

from .director import BrandDirection

console = Console()


def export_to_illustrator(
    direction: BrandDirection,
    assets_dir: Path,
    output_dir: Optional[Path] = None,
) -> None:
    """
    Phase 2 entry point: auto-trace raster logo → SVG via Illustrator JSX.

    Args:
        direction:  The confirmed brand direction.
        assets_dir: Directory containing background.png, logo.png, pattern.png.
        output_dir: Where to write vector outputs (defaults to assets_dir/vector).
    """
    if output_dir is None:
        output_dir = assets_dir / "vector"
    output_dir.mkdir(parents=True, exist_ok=True)

    console.print(
        f"\n[bold yellow]Phase 2 — Illustrator export (stub)[/bold yellow]\n"
        f"  Direction: Option {direction.option_number} — {direction.direction_name}\n"
        f"  Assets:    {assets_dir}\n"
        f"  Output:    {output_dir}\n"
    )
    console.print(
        "[dim]Illustrator auto-trace integration not yet implemented.\n"
        "To complete Phase 2, add a JSX script runner here that:\n"
        "  1. Opens logo.png in Illustrator\n"
        "  2. Runs Image Trace → Expand\n"
        "  3. Exports as SVG + EPS\n"
        "  4. Repeats for pattern.png[/dim]"
    )
