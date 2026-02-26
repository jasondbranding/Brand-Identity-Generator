"""
pipeline_runner.py — Runs the brand identity pipeline programmatically.

Designed to be called from the Telegram bot. Runs in a thread pool
so the bot stays responsive. Reports progress via callbacks.

Pipeline steps:
  1. Parse brief
  2. Market context validation (auto-confirm, no interactive prompt)
  3. Market research (Gemini Search Grounding)
  4. Generate brand directions
  5. Generate images (background / logo / pattern per direction)
     + palette fetch (Color Hunt → ColorMind)
     + shade scale generation (tints.dev → HSL fallback)
  6. Composite mockups (Pillow)
  7. Generate social posts (3 types × N directions)
  8. Assemble stylescapes (14-cell grid PNG per direction)
  9. Collect + return all output paths
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional


# ── Result model ──────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """Output from a full pipeline run."""
    success: bool
    output_dir: Path
    directions_md: Optional[Path] = None
    directions_json: Optional[Path] = None
    stylescape_paths: Dict[int, Path] = field(default_factory=dict)
    palette_pngs: List[Path] = field(default_factory=list)
    shades_pngs: List[Path] = field(default_factory=list)
    image_files: List[Path] = field(default_factory=list)
    error: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class LogosPhaseResult:
    """Output from Phase 1: concept ideation + director + logos only."""
    success: bool
    output_dir: Path
    directions_output: Optional[object] = None   # BrandDirectionsOutput
    all_assets: Dict[int, object] = field(default_factory=dict)  # option_num → DirectionAssets
    directions_json: Optional[Path] = None
    error: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class AssetsPhaseResult:
    """Output from Phase 2: full assets for ONE chosen direction."""
    success: bool
    output_dir: Path
    assets: Optional[object] = None              # DirectionAssets
    stylescape_path: Optional[Path] = None
    palette_png: Optional[Path] = None
    image_files: List[Path] = field(default_factory=list)
    error: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class PalettePhaseResult:
    """Output from palette generation phase."""
    success: bool
    output_dir: Path
    enriched_colors: Optional[List[dict]] = None
    palette_png: Optional[Path] = None
    shades_png: Optional[Path] = None
    palette_shades: Optional[dict] = None
    error: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class PatternPhaseResult:
    """Output from pattern generation phase."""
    success: bool
    output_dir: Path
    pattern_path: Optional[Path] = None
    error: str = ""
    elapsed_seconds: float = 0.0


# ── Progress callback type ────────────────────────────────────────────────────

ProgressCallback = Callable[[str], None]   # sync, called from worker thread


# ── Runner ────────────────────────────────────────────────────────────────────

class PipelineRunner:
    """Runs the full brand identity pipeline programmatically (non-CLI)."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        os.environ["GEMINI_API_KEY"] = api_key

    async def run(
        self,
        brief_dir: Path,
        mode: str = "full",
        on_progress: Optional[ProgressCallback] = None,
        generate_images: bool = True,
    ) -> PipelineResult:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._run_sync,
            brief_dir,
            mode,
            on_progress,
            generate_images,
        )

    # ── Phase 1: logos only ───────────────────────────────────────────────────

    async def run_logos_phase(
        self,
        brief_dir: Path,
        on_progress: Optional[ProgressCallback] = None,
        refinement_feedback: Optional[str] = None,
    ) -> LogosPhaseResult:
        """Phase 1: concept ideation + director + 4 logos only (fast ~2-3 min)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._run_logos_sync, brief_dir, on_progress, refinement_feedback
        )

    def _run_logos_sync(
        self,
        brief_dir: Path,
        on_progress: Optional[ProgressCallback],
        refinement_feedback: Optional[str] = None,
    ) -> LogosPhaseResult:
        start = time.time()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("outputs") / f"bot_{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._progress(on_progress, "📋 *Step 1/3* — Đang đọc brief\\.\\.\\.")
            from src.parser import parse_brief
            brief = parse_brief(str(brief_dir), mode="full")

            self._progress(on_progress, "🔍 *Step 2/3* — Research \\+ generating 4 brand directions\\.\\.\\.")

            # ── Parallelize research + direction generation ────────────────
            # Research uses Google Search Grounding (independent from Director).
            # Director now handles concept ideation internally (Phase 1 of system prompt).
            # Run both concurrently — research feeds into director if it finishes first.
            from concurrent.futures import ThreadPoolExecutor, as_completed

            research_context = ""
            style_ref_images = list(getattr(brief, "style_ref_images", None) or [])
            # Fallback: read from logo_inspiration/ subfolder written by ConversationBrief
            if not style_ref_images:
                logo_inspo_dir = brief_dir / "logo_inspiration"
                if logo_inspo_dir.is_dir():
                    _img_exts = {".png", ".jpg", ".jpeg", ".webp"}
                    style_ref_images = sorted(
                        p for p in logo_inspo_dir.iterdir()
                        if p.suffix.lower() in _img_exts
                    )

            def _do_research():
                nonlocal research_context
                try:
                    from src.validate import BriefValidator
                    validator = BriefValidator(self.api_key)
                    ctx = validator._extract_from_brief(brief)
                    if not ctx.is_complete():
                        ctx = validator._infer_missing(brief, ctx)
                    ctx.confirmed = True
                    market_context_str = ctx.to_research_prompt()
                except Exception:
                    market_context_str = ""
                try:
                    from src.researcher import BrandResearcher
                    researcher = BrandResearcher(self.api_key)
                    res = researcher.research(brief.brief_text, brief.keywords,
                                              market_context=market_context_str or None)
                    return res.to_director_context()
                except Exception:
                    return ""

            def _do_directions(res_context=""):
                from src.director import generate_directions
                return generate_directions(
                    brief,
                    research_context=res_context,
                    style_ref_paths=style_ref_images or None,
                    refinement_feedback=refinement_feedback or None,
                )

            # Run research first with short timeout, then directions with result
            with ThreadPoolExecutor(max_workers=2) as executor:
                research_future = executor.submit(_do_research)
                try:
                    research_context = research_future.result(timeout=30)
                except Exception:
                    research_context = ""

            self._progress(on_progress, "🎨 *Step 3/3* — Director \\+ generating 4 logos\\.\\.\\.")
            directions_output = _do_directions(research_context)

            directions_json = output_dir / "directions.json"
            _write_directions_json(directions_output, directions_json)

            from src.generator import generate_all_assets
            all_assets = generate_all_assets(
                directions_output.directions,
                output_dir=output_dir,
                brief_keywords=brief.keywords,
                brand_name=getattr(brief, "brand_name", ""),
                brief_text=getattr(brief, "brief_text", ""),
                moodboard_images=getattr(brief, "moodboard_images", None) or None,
                style_ref_images=style_ref_images or None,
                logo_only=True,
            )

            return LogosPhaseResult(
                success=True,
                output_dir=output_dir,
                directions_output=directions_output,
                all_assets=all_assets,
                directions_json=directions_json,
                elapsed_seconds=time.time() - start,
            )

        except Exception as e:
            import traceback
            return LogosPhaseResult(
                success=False,
                output_dir=output_dir,
                error=f"{e}\n\n{traceback.format_exc()}",
                elapsed_seconds=time.time() - start,
            )

    # ── Phase 2: full assets for one direction ────────────────────────────────

    async def run_assets_phase(
        self,
        direction: object,
        output_dir: Path,
        brief_dir: Path,
        on_progress: Optional[ProgressCallback] = None,
    ) -> AssetsPhaseResult:
        """Phase 2: bg + pattern + palette + mockup + stylescape for ONE chosen direction."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._run_assets_sync, direction, output_dir, brief_dir, on_progress
        )

    def _run_assets_sync(
        self,
        direction: object,
        output_dir: Path,
        brief_dir: Path,
        on_progress: Optional[ProgressCallback],
    ) -> AssetsPhaseResult:
        start = time.time()
        try:
            from src.parser import parse_brief
            brief = parse_brief(str(brief_dir), mode="full")
            style_ref_images = list(getattr(brief, "style_ref_images", None) or [])

            self._progress(on_progress,
                f"🖼 *Phase 2* — Generating pattern \\+ palette \\+ background\\.\\.\\.")
            from src.generator import generate_single_direction_assets
            assets = generate_single_direction_assets(
                direction=direction,
                output_dir=output_dir,
                brief_keywords=getattr(brief, "keywords", None),
                brand_name=getattr(brief, "brand_name", ""),
                brief_tagline=getattr(brief, "tagline", ""),
                brief_ad_slogan=getattr(brief, "ad_slogan", ""),
                brief_announcement_copy=getattr(brief, "announcement_copy", ""),
                brief_text=getattr(brief, "brief_text", ""),
                moodboard_images=getattr(brief, "moodboard_images", None) or None,
                style_ref_images=style_ref_images or None,
            )

            # Base assets (logo variants + background + pattern + palette) are now complete.
            # Mockup compositing is done progressively in telegram_bot._run_pipeline_phase2
            # so each mockup can be sent to Telegram as soon as it's ready.
            # Social posts and stylescape have been removed from this phase.

            return AssetsPhaseResult(
                success=True,
                output_dir=output_dir,
                assets=assets,
                stylescape_path=None,
                palette_png=getattr(assets, "palette_png", None),
                image_files=[],   # populated by telegram_bot during progressive send
                elapsed_seconds=time.time() - start,
            )

        except Exception as e:
            import traceback
            return AssetsPhaseResult(
                success=False,
                output_dir=output_dir,
                error=f"{e}\n\n{traceback.format_exc()}",
                elapsed_seconds=time.time() - start,
            )

    # ── Phase: palette only ──────────────────────────────────────────────────

    async def run_palette_phase(
        self,
        direction: object,
        output_dir: Path,
        brief_dir: Path,
        on_progress: Optional[ProgressCallback] = None,
        refinement_feedback: Optional[str] = None,
    ) -> "PalettePhaseResult":
        """Generate palette + shades for one direction."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._run_palette_sync, direction, output_dir, brief_dir,
            on_progress, refinement_feedback,
        )

    def _run_palette_sync(
        self,
        direction: object,
        output_dir: Path,
        brief_dir: Path,
        on_progress: Optional[ProgressCallback],
        refinement_feedback: Optional[str] = None,
    ) -> "PalettePhaseResult":
        start = time.time()
        try:
            from src.parser import parse_brief
            brief = parse_brief(str(brief_dir), mode="full")

            self._progress(on_progress, "🎨 Đang tạo bảng màu\\.\\.\\.")
            from src.generator import generate_palette_only
            result = generate_palette_only(
                direction=direction,
                output_dir=output_dir,
                brief_keywords=getattr(brief, "keywords", None),
                brief_text=getattr(brief, "brief_text", ""),
                refinement_feedback=refinement_feedback,
            )

            return PalettePhaseResult(
                success=True,
                output_dir=output_dir,
                enriched_colors=result.get("enriched_colors"),
                palette_png=result.get("palette_png"),
                shades_png=result.get("shades_png"),
                palette_shades=result.get("palette_shades"),
                elapsed_seconds=time.time() - start,
            )
        except Exception as e:
            import traceback
            return PalettePhaseResult(
                success=False,
                output_dir=output_dir,
                error=f"{e}\n\n{traceback.format_exc()}",
                elapsed_seconds=time.time() - start,
            )

    # ── Phase: pattern only ──────────────────────────────────────────────────

    async def run_pattern_phase(
        self,
        direction: object,
        output_dir: Path,
        brief_dir: Path,
        on_progress: Optional[ProgressCallback] = None,
        pattern_refs: Optional[list] = None,
        description: Optional[str] = None,
        palette_colors: Optional[List[dict]] = None,
        refinement_feedback: Optional[str] = None,
    ) -> "PatternPhaseResult":
        """Generate pattern for one direction, using styleguide matching + custom prompt."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._run_pattern_sync, direction, output_dir, brief_dir,
            on_progress, pattern_refs, description, palette_colors, refinement_feedback,
        )

    def _run_pattern_sync(
        self,
        direction: object,
        output_dir: Path,
        brief_dir: Path,
        on_progress: Optional[ProgressCallback],
        pattern_refs: Optional[list] = None,
        description: Optional[str] = None,
        palette_colors: Optional[List[dict]] = None,
        refinement_feedback: Optional[str] = None,
    ) -> "PatternPhaseResult":
        start = time.time()
        try:
            from src.parser import parse_brief
            brief = parse_brief(str(brief_dir), mode="full")
            style_ref_images = list(getattr(brief, "style_ref_images", None) or [])

            self._progress(on_progress, "🔲 Đang tạo hoạ tiết\\.\\.\\.")

            # Build enhanced prompt via pattern_matcher if refs are available
            custom_prompt = None
            try:
                from src.pattern_matcher import build_pattern_prompt
                custom_prompt = build_pattern_prompt(
                    direction=direction,
                    brief_keywords=getattr(brief, "keywords", None),
                    pattern_refs=pattern_refs,
                    user_description=description,
                    palette_colors=palette_colors,
                    refinement_feedback=refinement_feedback,
                )
            except ImportError:
                pass  # pattern_matcher not yet created — fall through to default
            except Exception as e:
                self._progress(on_progress, f"⚠️ Pattern prompt builder: {e}")

            from src.generator import generate_pattern_only
            pattern_path = generate_pattern_only(
                direction=direction,
                output_dir=output_dir,
                brief_keywords=getattr(brief, "keywords", None),
                brief_text=getattr(brief, "brief_text", ""),
                moodboard_images=getattr(brief, "moodboard_images", None) or None,
                style_ref_images=(pattern_refs or []) + (style_ref_images or []) or None,
                custom_prompt=custom_prompt,
                palette_colors=palette_colors,
            )

            return PatternPhaseResult(
                success=True,
                output_dir=output_dir,
                pattern_path=pattern_path,
                elapsed_seconds=time.time() - start,
            )
        except Exception as e:
            import traceback
            return PatternPhaseResult(
                success=False,
                output_dir=output_dir,
                error=f"{e}\n\n{traceback.format_exc()}",
                elapsed_seconds=time.time() - start,
            )

    # ── Phase: single logo edit (targeted HITL refinement) ───────────────────

    async def run_single_logo_edit(
        self,
        direction_num: int,
        logo_path: Path,
        edit_instruction: str,
        output_dir: Path,
    ) -> dict:
        """
        Edit one existing logo image using Gemini multimodal image editing.
        Used when user references a specific direction number in their feedback.
        Returns dict with success, path, direction_num, elapsed.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._run_single_logo_edit_sync,
            direction_num, logo_path, edit_instruction, output_dir,
        )

    def _run_single_logo_edit_sync(
        self,
        direction_num: int,
        logo_path: Path,
        edit_instruction: str,
        output_dir: Path,
    ) -> dict:
        import time as _time
        start = _time.time()
        try:
            from src.generator import edit_logo_image
            save_path = output_dir / f"option_{direction_num}_edited_logo.png"
            result_path = edit_logo_image(
                existing_logo_path=logo_path,
                edit_instruction=edit_instruction,
                save_path=save_path,
                api_key=self.api_key,
            )
            return {
                "success": result_path is not None,
                "path": result_path,
                "direction_num": direction_num,
                "elapsed": _time.time() - start,
            }
        except Exception as e:
            import traceback
            return {
                "success": False,
                "path": None,
                "direction_num": direction_num,
                "elapsed": _time.time() - start,
                "error": f"{e}\n{traceback.format_exc()}",
            }

    # ── Phase: logo variants + SVG ───────────────────────────────────────────

    async def run_logo_variants_phase(
        self,
        logo_path: Path,
        output_dir: Path,
    ) -> dict:
        """Create white / black / transparent + SVG variants from logo PNG."""
        loop = asyncio.get_event_loop()
        from src.generator import create_logo_variants_and_svg
        return await loop.run_in_executor(
            None, create_logo_variants_and_svg, logo_path, output_dir,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _progress(self, cb: Optional[ProgressCallback], msg: str) -> None:
        if cb:
            try:
                cb(msg)
            except Exception:
                pass

    def _run_sync(
        self,
        brief_dir: Path,
        mode: str,
        on_progress: Optional[ProgressCallback],
        generate_images: bool,
    ) -> PipelineResult:
        start = time.time()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("outputs") / f"bot_{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            # ── Step 1: Parse brief ──────────────────────────────────────────
            self._progress(on_progress, "📋 *Step 1/6* — Đang đọc brief\\.\\.\\.")
            from src.parser import parse_brief
            brief = parse_brief(str(brief_dir), mode=mode)

            # ── Step 2: Research + brand directions (parallel) ──────────────
            # Market context, research, and direction gen merged into fewer steps.
            # Research runs with 30s timeout; Director handles concept ideation internally.
            self._progress(on_progress, "🔍 *Step 2/5* — Research \\+ brand direction generation\\.\\.\\.")
            from concurrent.futures import ThreadPoolExecutor

            research_context = ""
            style_ref_images = list(getattr(brief, "style_ref_images", None) or [])

            def _do_research_hitl():
                market_context_str = ""
                try:
                    from src.validate import BriefValidator
                    validator = BriefValidator(self.api_key)
                    ctx = validator._extract_from_brief(brief)
                    if not ctx.is_complete():
                        ctx = validator._infer_missing(brief, ctx)
                    ctx.confirmed = True
                    market_context_str = ctx.to_research_prompt()
                except Exception:
                    pass
                if not generate_images:
                    return ""
                try:
                    from src.researcher import BrandResearcher
                    researcher = BrandResearcher(self.api_key)
                    res = researcher.research(
                        brief.brief_text,
                        brief.keywords,
                        market_context=market_context_str or None,
                    )
                    return res.to_director_context()
                except Exception:
                    return ""

            with ThreadPoolExecutor(max_workers=1) as executor:
                research_future = executor.submit(_do_research_hitl)
                try:
                    research_context = research_future.result(timeout=30)
                except Exception:
                    research_context = ""

            # ── Step 3: Generate brand directions ────────────────────────────
            self._progress(on_progress, "🎨 *Step 3/5* — Tạo brand directions\\.\\.\\.")
            from src.director import generate_directions
            directions_output = generate_directions(
                brief,
                research_context=research_context,
                style_ref_paths=style_ref_images or None,
            )

            # Save directions markdown + JSON
            directions_md   = output_dir / "directions.md"
            directions_json = output_dir / "directions.json"
            _write_directions_md(directions_output, directions_md)
            _write_directions_json(directions_output, directions_json)

            if not generate_images:
                return PipelineResult(
                    success=True,
                    output_dir=output_dir,
                    directions_md=directions_md,
                    directions_json=directions_json,
                    elapsed_seconds=time.time() - start,
                )

            # ── Step 4: Generate images + palette + shades ───────────────────
            n_dirs = len(directions_output.directions)
            self._progress(
                on_progress,
                f"🖼 *Step 4/5* — Generating images \\({n_dirs} directions\\)\\.\\.\\.\\n"
                f"_\\(logo \\+ pattern \\+ palette \\+ shades — ~1\\-2 min\\)_"
            )
            from src.generator import generate_all_assets
            all_assets = generate_all_assets(
                directions_output.directions,
                output_dir=output_dir,
                brief_keywords=brief.keywords,
                brand_name=getattr(brief, "brand_name", ""),
                brief_tagline=getattr(brief, "tagline", ""),
                brief_ad_slogan=getattr(brief, "ad_slogan", ""),
                brief_announcement_copy=getattr(brief, "announcement_copy", ""),
                brief_text=getattr(brief, "brief_text", ""),
                moodboard_images=getattr(brief, "moodboard_images", None) or None,
                style_ref_images=style_ref_images or None,
            )

            # ── Step 6a: Composite mockups ────────────────────────────────────
            self._progress(on_progress, "🧩 *Step 6a/6* — Compositing mockups\\.\\.\\.")
            try:
                from src.mockup_compositor import composite_all_mockups
                mockup_results = composite_all_mockups(all_assets)
                for num, composited in mockup_results.items():
                    all_assets[num].mockups = composited
            except Exception as e:
                self._progress(on_progress, f"⚠️ Mockups skipped: {e}")

            # ── Step 6b: Social posts ─────────────────────────────────────────
            self._progress(on_progress, "📱 *Step 6b/6* — Generating social posts\\.\\.\\.")
            try:
                from src.social_compositor import generate_social_posts
                generate_social_posts(all_assets)
            except Exception as e:
                self._progress(on_progress, f"⚠️ Social posts skipped: {e}")

            # ── Step 6c: Assemble stylescapes ─────────────────────────────────
            self._progress(on_progress, "🗂 *Step 6c/6* — Assembling stylescapes\\.\\.\\.")
            stylescape_paths: Dict[int, Path] = {}
            try:
                from src.compositor import build_all_stylescapes
                stylescape_paths = build_all_stylescapes(all_assets, output_dir=output_dir)
            except Exception as e:
                self._progress(on_progress, f"⚠️ Stylescapes skipped: {e}")

            # ── Collect special output files ──────────────────────────────────
            palette_pngs: List[Path] = [
                a.palette_png for a in all_assets.values()
                if getattr(a, "palette_png", None) and a.palette_png.exists()
            ]
            shades_pngs: List[Path] = [
                a.shades_png for a in all_assets.values()
                if getattr(a, "shades_png", None) and a.shades_png.exists()
            ]

            # All generated PNG/JPG files
            image_files = sorted(
                p for p in output_dir.glob("**/*.png")
                if p.is_file() and p.stat().st_size > 500
            )

            return PipelineResult(
                success=True,
                output_dir=output_dir,
                directions_md=directions_md,
                directions_json=directions_json,
                stylescape_paths=stylescape_paths,
                palette_pngs=palette_pngs,
                shades_pngs=shades_pngs,
                image_files=image_files,
                elapsed_seconds=time.time() - start,
            )

        except Exception as e:
            import traceback
            return PipelineResult(
                success=False,
                output_dir=output_dir,
                error=f"{e}\n\n{traceback.format_exc()}",
                elapsed_seconds=time.time() - start,
            )


# ── Markdown/JSON helpers ─────────────────────────────────────────────────────

def _write_directions_md(directions_output, path: Path) -> None:
    """Write brand directions to a human-readable markdown file."""
    lines = [
        "# Brand Identity Directions\n",
        f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n",
        "---\n",
    ]
    for d in directions_output.directions:
        palette = " | ".join(
            f"{c.name} `{c.hex}`" for c in getattr(d, "colors", [])
        )
        typo = f"{d.typography_primary} / {d.typography_secondary}"
        lines += [
            f"## Option {d.option_number} — {d.direction_name}",
            f"**Type:** {d.option_type}  ",
            f"**Rationale:** {d.rationale}  ",
            f"**Colors:** {palette}  ",
            f"**Typography:** {typo}  ",
            f"**Style:** {d.graphic_style}  ",
            f"**Logo:** {d.logo_concept}  ",
            "---\n",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_directions_json(directions_output, path: Path) -> None:
    """Serialize directions_output to JSON for downstream use (PDF, etc.)."""
    path.write_text(directions_output.model_dump_json(indent=2), encoding="utf-8")
