"""
pipeline_runner.py — Runs the brand identity pipeline programmatically.

Designed to be called from the Telegram bot. Runs in a thread pool
so the bot stays responsive. Reports progress via callbacks.

Usage:
    runner = PipelineRunner(api_key=os.environ["GEMINI_API_KEY"])
    result = await runner.run(
        brief_dir=tmp_dir,
        mode="full",
        on_progress=lambda msg: bot.edit_message_text(msg, ...),
        generate_images=True,
    )
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

# ── Result model ──────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """Output from a pipeline run."""
    success: bool
    output_dir: Path
    directions_md: Optional[Path] = None
    image_files: List[Path] = field(default_factory=list)  # logos, patterns, backgrounds
    error: str = ""
    elapsed_seconds: float = 0.0

    def get_images_by_direction(self) -> dict:
        """Group image files by direction number."""
        groups: dict = {}
        for p in self.image_files:
            # Filename convention: dir1_logo.png, dir2_pattern.png, etc.
            parts = p.stem.split("_")
            dir_key = parts[0] if parts else "misc"
            groups.setdefault(dir_key, []).append(p)
        return groups


# ── Progress callback type ────────────────────────────────────────────────────

ProgressCallback = Callable[[str], None]  # sync callback, called from thread


# ── Runner ────────────────────────────────────────────────────────────────────

class PipelineRunner:
    """Runs the brand identity pipeline programmatically (non-CLI)."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        os.environ["GEMINI_API_KEY"] = api_key  # ensure downstream modules see it

    async def run(
        self,
        brief_dir: Path,
        mode: str = "full",
        on_progress: Optional[ProgressCallback] = None,
        generate_images: bool = True,
    ) -> PipelineResult:
        """
        Run the full pipeline asynchronously.
        Calls on_progress(message) at each step.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._run_sync,
            brief_dir,
            mode,
            on_progress,
            generate_images,
        )

    def _progress(self, callback: Optional[ProgressCallback], msg: str) -> None:
        if callback:
            try:
                callback(msg)
            except Exception:
                pass  # never let progress callback crash the pipeline

    def _run_sync(
        self,
        brief_dir: Path,
        mode: str,
        on_progress: Optional[ProgressCallback],
        generate_images: bool,
    ) -> PipelineResult:
        """Synchronous pipeline execution (runs in thread pool)."""
        start = time.time()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("outputs") / f"bot_{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            # ── Step 1: Parse brief ──────────────────────────────────────────
            self._progress(on_progress, "📋 *Step 1/4* — Parsing brief...")
            from src.parser import parse_brief
            brief = parse_brief(str(brief_dir), mode=mode)

            # ── Step 2: Market context (non-interactive: auto-confirm) ────────
            self._progress(on_progress, "🌍 *Step 2/4* — Analysing market context...")
            market_context_str = ""
            try:
                from src.validate import BriefValidator
                validator = BriefValidator(self.api_key)
                # Extract from brief only (no interactive prompt)
                ctx = validator._extract_from_brief(brief)
                if not ctx.is_complete():
                    self._progress(
                        on_progress,
                        "🌍 *Step 2/4* — Market context incomplete, inferring with Gemini..."
                    )
                    ctx = validator._infer_missing(brief, ctx)
                ctx.confirmed = True
                market_context_str = ctx.to_research_prompt()
            except Exception as e:
                self._progress(on_progress, f"⚠️ Market context skipped: {e}")

            # ── Step 3: Market research ───────────────────────────────────────
            research_context = ""
            if generate_images:  # skip research in no-images mode to save time
                self._progress(on_progress, "🔍 *Step 3/4* — Researching competitive landscape...")
                try:
                    from src.researcher import BrandResearcher
                    researcher = BrandResearcher(self.api_key)
                    result = researcher.research(
                        brief.brief_text,
                        brief.keywords,
                        market_context=market_context_str or None,
                    )
                    research_context = result.to_director_context()
                except Exception as e:
                    self._progress(on_progress, f"⚠️ Research skipped: {e}")

            # ── Step 4: Generate directions ───────────────────────────────────
            self._progress(on_progress, "🎨 *Step 4a/4* — Generating brand directions...")
            from src.director import generate_directions
            directions_output = generate_directions(brief, research_context=research_context)

            # Save directions markdown
            directions_md = output_dir / "directions.md"
            _write_directions_md(directions_output, directions_md)

            if not generate_images:
                return PipelineResult(
                    success=True,
                    output_dir=output_dir,
                    directions_md=directions_md,
                    elapsed_seconds=time.time() - start,
                )

            # ── Step 5: Generate images ───────────────────────────────────────
            dir_count = len(directions_output.directions)
            self._progress(
                on_progress,
                f"🖼 *Step 4b/4* — Generating images for {dir_count} directions\\.\\.\\.\n"
                f"_(this takes 3–8 minutes — grab a coffee ☕)_"
            )
            from src.generator import generate_all_assets
            all_assets = generate_all_assets(
                directions_output.directions,
                output_dir=output_dir,
                brief_keywords=brief.keywords,
                moodboard_images=brief.moodboard_images or None,
            )

            # Collect all generated image files
            image_files = sorted(output_dir.glob("**/*.png")) + sorted(output_dir.glob("**/*.jpg"))
            # Exclude any non-image dirs
            image_files = [p for p in image_files if p.is_file()]

            return PipelineResult(
                success=True,
                output_dir=output_dir,
                directions_md=directions_md,
                image_files=image_files,
                elapsed_seconds=time.time() - start,
            )

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            return PipelineResult(
                success=False,
                output_dir=output_dir,
                error=f"{e}\n\n{tb}",
                elapsed_seconds=time.time() - start,
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_directions_md(directions_output, path: Path) -> None:
    """Write directions to a markdown file."""
    lines = ["# Brand Identity Directions\n"]
    for d in directions_output.directions:
        lines.append(f"## {d.option_type}\n")
        lines.append(f"**Concept:** {d.concept}\n")
        lines.append(f"**Strategy:** {d.strategy}\n")
        if d.color_palette:
            palette = " | ".join(
                f"{c.get('name', '')} {c.get('hex', '')}" for c in d.color_palette
            )
            lines.append(f"**Colors:** {palette}\n")
        if d.typography:
            lines.append(f"**Typography:** {d.typography}\n")
        if d.graphic_style:
            lines.append(f"**Style:** {d.graphic_style}\n")
        if d.tagline:
            lines.append(f"**Tagline:** _{d.tagline}_\n")
        if d.ad_slogan:
            lines.append(f"**Slogan:** _{d.ad_slogan}_\n")
        lines.append("---\n")
    path.write_text("\n".join(lines), encoding="utf-8")
