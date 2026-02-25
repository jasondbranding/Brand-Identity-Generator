"""
Brief parser — reads brief.md (and optionally keywords.md, moodboard/notes.md)
into a structured BriefData object for both Full and Quick modes.

SIMPLIFIED FORMAT (recommended):
  Drop everything into one folder:
    briefs/my_brand/
      brief.md          ← all sections in one file
      ref1.jpg          ← moodboard images (any amount, any name)
      ref2.png

FULL FORMAT (backward-compatible):
    briefs/full/
      brief.md
      keywords.md       ← optional separate keywords file
      moodboard/
        notes.md        ← optional separate moodboard notes
        ref1.jpg        ← moodboard images

ALL SUPPORTED SECTIONS IN brief.md:
  ## Brand Name         → brand_name
  ## Keywords           → keywords (fallback if no keywords.md)
  ## Moodboard          → moodboard notes (fallback if no moodboard/notes.md)
  ## Tagline            → locked tagline copy
  ## Slogan / ## Ad Slogan → locked ad slogan
  ## Announcement       → locked announcement copy
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass
class BriefData:
    mode: str               # "full" or "quick"
    brief_text: str         # Raw content of brief.md
    brand_name: str         # Extracted from "## Brand Name" section
    keywords: List[str]     # Brand personality keywords
    moodboard_notes: str    # Moodboard/creative direction notes (full mode)

    # Moodboard images — paths to image files found in the brief folder
    # Passed to Gemini as visual context alongside the text brief
    moodboard_images: List[Path] = field(default_factory=list)

    # Optional copy overrides — pipeline uses these verbatim if set
    tagline: str = ""           # "## Tagline"
    ad_slogan: str = ""         # "## Slogan" / "## Ad Slogan"
    announcement_copy: str = "" # "## Announcement"

    def has_copy(self) -> bool:
        return bool(self.tagline or self.ad_slogan or self.announcement_copy)

    def to_prompt_block(self) -> str:
        """Format brief data for the director model's user message."""
        parts: List[str] = [
            f"## MODE: {self.mode.upper()} MODE",
            "",
            "## BRAND BRIEF",
            self.brief_text.strip(),
        ]

        if self.keywords:
            parts += [
                "",
                "## BRAND KEYWORDS",
                "\n".join(f"- {kw}" for kw in self.keywords),
            ]

        if self.moodboard_notes:
            parts += [
                "",
                "## MOODBOARD / CREATIVE DIRECTION NOTES",
                self.moodboard_notes.strip(),
            ]

        if self.moodboard_images:
            parts += [
                "",
                f"## VISUAL REFERENCES ({len(self.moodboard_images)} image(s) attached)",
                "The client has provided visual reference images alongside this brief.",
                "Study them carefully — they inform Option 2 (Designer-Led) most directly,",
                "but all directions should acknowledge the visual language they suggest.",
            ]

        if self.has_copy():
            parts += ["", "## PRE-WRITTEN COPY (use these exactly — do not rewrite)"]
            if self.tagline:
                parts.append(f"Tagline: {self.tagline}")
            if self.ad_slogan:
                parts.append(f"Ad slogan: {self.ad_slogan}")
            if self.announcement_copy:
                parts.append(f"Announcement copy: {self.announcement_copy}")
            parts += [
                "",
                "⚠️  The copy fields above are LOCKED. "
                "Use them verbatim in tagline / ad_slogan / announcement_copy for ALL directions. "
                "Do not paraphrase, improve, or alter them.",
            ]

        if self.mode == "quick":
            parts += [
                "",
                "⚠️ Quick Mode: Generate only 2 directions (Market-Aligned and Wild Card). "
                "Infer creative direction from the brief and keywords — no moodboard provided.",
            ]

        return "\n".join(parts)


def _extract_section(text: str, *section_names: str) -> str:
    """Extract first non-empty line from any matching ## Section heading."""
    pattern = "|".join(re.escape(n) for n in section_names)
    in_section = False
    for line in text.splitlines():
        if re.match(rf"##\s*({pattern})\s*$", line.strip(), re.IGNORECASE):
            in_section = True
            continue
        if in_section:
            if line.startswith("#"):
                break
            stripped = line.strip()
            if stripped:
                return stripped
    return ""


def _extract_multiline_section(text: str, *section_names: str) -> str:
    """Extract all lines from any matching ## Section until the next ## heading."""
    pattern = "|".join(re.escape(n) for n in section_names)
    in_section = False
    collected: List[str] = []
    for line in text.splitlines():
        if re.match(rf"##\s*({pattern})\s*$", line.strip(), re.IGNORECASE):
            in_section = True
            continue
        if in_section:
            if re.match(r"^#{1,3}\s", line):
                break
            collected.append(line)
    return "\n".join(collected).strip()


def parse_brief(brief_dir: str, mode: str = "full") -> BriefData:
    """
    Parse a brief directory into BriefData.

    Accepts both simplified (single-folder, all-in-one) and legacy
    multi-file full formats. See module docstring for details.
    """
    root = Path(brief_dir)
    if not root.exists():
        raise FileNotFoundError(f"Brief directory not found: {brief_dir}")

    brief_file = root / "brief.md"
    if not brief_file.exists():
        raise FileNotFoundError(f"brief.md not found in {brief_dir}")

    brief_text = brief_file.read_text(encoding="utf-8")

    # ── Brand name ────────────────────────────────────────────────────────────
    brand_name = _extract_section(brief_text, "Brand Name")

    # ── Copy fields (optional) ────────────────────────────────────────────────
    tagline           = _extract_section(brief_text, "Tagline")
    ad_slogan         = _extract_section(brief_text, "Slogan", "Ad Slogan")
    announcement_copy = _extract_section(brief_text, "Announcement", "Announcement Copy")

    # ── Keywords ──────────────────────────────────────────────────────────────
    keywords: List[str] = []
    keywords_file = root / "keywords.md"
    if keywords_file.exists():
        for line in keywords_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                keywords.append(stripped.lstrip("- ").strip())
    else:
        # Fallback: ## Keywords section embedded in brief.md
        kw_block = _extract_multiline_section(brief_text, "Keywords")
        for line in kw_block.splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped:
                keywords.append(stripped)

    # ── Moodboard notes ───────────────────────────────────────────────────────
    moodboard_notes = ""
    if mode == "full":
        moodboard_file = root / "moodboard" / "notes.md"
        if moodboard_file.exists():
            moodboard_notes = moodboard_file.read_text(encoding="utf-8")
        else:
            # Fallback: ## Moodboard section embedded in brief.md
            moodboard_notes = _extract_multiline_section(
                brief_text, "Moodboard", "Moodboard Notes", "Creative Direction"
            )

    # ── Moodboard images ──────────────────────────────────────────────────────
    # Scan root folder first, then moodboard/ subdir (both supported)
    moodboard_images: List[Path] = []
    if mode == "full":
        for p in sorted(root.iterdir()):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                moodboard_images.append(p)
        moodboard_subdir = root / "moodboard"
        if moodboard_subdir.exists():
            for p in sorted(moodboard_subdir.iterdir()):
                if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                    moodboard_images.append(p)

    return BriefData(
        mode=mode,
        brief_text=brief_text,
        brand_name=brand_name,
        keywords=keywords,
        moodboard_notes=moodboard_notes,
        moodboard_images=moodboard_images,
        tagline=tagline,
        ad_slogan=ad_slogan,
        announcement_copy=announcement_copy,
    )
