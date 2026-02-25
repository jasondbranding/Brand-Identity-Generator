"""
Brief parser — reads brief.md, keywords.md, and moodboard notes
into a structured BriefData object for both Full and Quick modes.

Optional copy overrides in brief.md:
  ## Tagline          → short brand tagline (5–10 words)
  ## Slogan           → punchy ad slogan (3–6 words)   [also: ## Ad Slogan]
  ## Announcement     → announcement post copy (10–18 words)

If provided, pipeline uses these verbatim instead of AI-generating copy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class BriefData:
    mode: str               # "full" or "quick"
    brief_text: str         # Raw content of brief.md
    brand_name: str         # Extracted from "## Brand Name" section
    keywords: List[str]     # Brand personality keywords
    moodboard_notes: str    # Moodboard/creative direction notes (full mode)

    # Optional copy overrides — if set, pipeline uses these verbatim instead of AI-generated copy
    tagline: str = ""           # Brand tagline (5–10 words)       — "## Tagline"
    ad_slogan: str = ""         # Punchy ad slogan (3–6 words)      — "## Slogan" / "## Ad Slogan"
    announcement_copy: str = "" # Announcement post copy (10–18 w)  — "## Announcement"

    def has_copy(self) -> bool:
        """True if brief contains any pre-written copy fields."""
        return bool(self.tagline or self.ad_slogan or self.announcement_copy)

    def to_prompt_block(self) -> str:
        """Format brief data for Claude's user message."""
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

        # Surface pre-written copy so Claude aligns tone and uses it verbatim
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
    """
    Extract first non-empty line from any matching ## Section heading in text.
    Returns empty string if not found.
    Accepts multiple heading aliases (e.g. "Slogan", "Ad Slogan").
    """
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


def parse_brief(brief_dir: str, mode: str = "full") -> BriefData:
    """
    Parse a brief directory into BriefData.

    Expected structure:
      full mode:  brief_dir/brief.md, brief_dir/keywords.md, brief_dir/moodboard/notes.md
      quick mode: brief_dir/brief.md  (keywords embedded in brief or separate keywords.md)

    Optional copy sections in brief.md (any order):
      ## Tagline
      ## Slogan  (or ## Ad Slogan)
      ## Announcement
    """
    root = Path(brief_dir)

    if not root.exists():
        raise FileNotFoundError(f"Brief directory not found: {brief_dir}")

    brief_file = root / "brief.md"
    if not brief_file.exists():
        raise FileNotFoundError(f"brief.md not found in {brief_dir}")

    brief_text = brief_file.read_text(encoding="utf-8")

    # ── Brand name ─────────────────────────────────────────────────────────────
    brand_name = _extract_section(brief_text, "Brand Name")

    # ── Copy fields (optional) ─────────────────────────────────────────────────
    tagline           = _extract_section(brief_text, "Tagline")
    ad_slogan         = _extract_section(brief_text, "Slogan", "Ad Slogan")
    announcement_copy = _extract_section(brief_text, "Announcement", "Announcement Copy")

    # ── Keywords ───────────────────────────────────────────────────────────────
    keywords: list[str] = []
    keywords_file = root / "keywords.md"
    if keywords_file.exists():
        for line in keywords_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                keywords.append(stripped.lstrip("- ").strip())
    else:
        in_kw_section = False
        for line in brief_text.splitlines():
            if line.lower().startswith("## keyword"):
                in_kw_section = True
                continue
            if in_kw_section:
                if line.startswith("##"):
                    break
                stripped = line.strip()
                if stripped:
                    keywords.append(stripped.lstrip("- ").strip())

    # ── Moodboard notes (full mode only) ───────────────────────────────────────
    moodboard_notes = ""
    if mode == "full":
        moodboard_file = root / "moodboard" / "notes.md"
        if moodboard_file.exists():
            moodboard_notes = moodboard_file.read_text(encoding="utf-8")

    return BriefData(
        mode=mode,
        brief_text=brief_text,
        brand_name=brand_name,
        keywords=keywords,
        moodboard_notes=moodboard_notes,
        tagline=tagline,
        ad_slogan=ad_slogan,
        announcement_copy=announcement_copy,
    )
