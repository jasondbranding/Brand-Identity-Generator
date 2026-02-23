"""
Brief parser — reads brief.md, keywords.md, and moodboard notes
into a structured BriefData object for both Full and Quick modes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class BriefData:
    mode: str               # "full" or "quick"
    brief_text: str         # Raw content of brief.md
    keywords: List[str]     # Brand personality keywords
    moodboard_notes: str    # Moodboard/creative direction notes (full mode)

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

        if self.mode == "quick":
            parts += [
                "",
                "⚠️ Quick Mode: Generate only 2 directions (Market-Aligned and Wild Card). "
                "Infer creative direction from the brief and keywords — no moodboard provided.",
            ]

        return "\n".join(parts)


def parse_brief(brief_dir: str, mode: str = "full") -> BriefData:
    """
    Parse a brief directory into BriefData.

    Expected structure:
      full mode:  brief_dir/brief.md, brief_dir/keywords.md, brief_dir/moodboard/notes.md
      quick mode: brief_dir/brief.md  (keywords embedded in brief or separate keywords.md)
    """
    root = Path(brief_dir)

    if not root.exists():
        raise FileNotFoundError(f"Brief directory not found: {brief_dir}")

    brief_file = root / "brief.md"
    if not brief_file.exists():
        raise FileNotFoundError(f"brief.md not found in {brief_dir}")

    brief_text = brief_file.read_text(encoding="utf-8")

    # Keywords — optional file, also check inside brief for an inline ## Keywords section
    keywords: list[str] = []
    keywords_file = root / "keywords.md"
    if keywords_file.exists():
        for line in keywords_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                keywords.append(stripped.lstrip("- ").strip())
    else:
        # Try to extract from brief inline
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

    # Moodboard notes (full mode only)
    moodboard_notes = ""
    if mode == "full":
        moodboard_file = root / "moodboard" / "notes.md"
        if moodboard_file.exists():
            moodboard_notes = moodboard_file.read_text(encoding="utf-8")

    return BriefData(
        mode=mode,
        brief_text=brief_text,
        keywords=keywords,
        moodboard_notes=moodboard_notes,
    )
