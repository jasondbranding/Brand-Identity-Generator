"""
brief_builder.py — Builds a BriefData from Telegram conversation state.

Collects fields incrementally as the user answers bot questions,
then writes a proper brief.md to a temp directory so the existing
pipeline can process it without modification.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Sentinel used when a user explicitly skips an optional field.
# The field is set to this value so _next_unfilled_state treats it as "filled"
# (truthy) and doesn't re-ask. The sentinel is filtered out before output.
SKIP_SENTINEL = "-"


def _real(value) -> bool:
    """Return True if value has real content (not empty and not the skip sentinel)."""
    if not value:
        return False
    if isinstance(value, list):
        return any(v != SKIP_SENTINEL for v in value)
    return value != SKIP_SENTINEL


def _clean_list(lst: List[str]) -> List[str]:
    """Return list without sentinel values."""
    return [v for v in lst if v != SKIP_SENTINEL]


# ── Conversation data model ───────────────────────────────────────────────────

@dataclass
class ConversationBrief:
    """Accumulates brief fields during a Telegram conversation."""

    # Required
    brand_name: str = ""
    product: str = ""
    audience: str = ""

    # Optional — gathered step by step
    tone: str = ""
    core_promise: str = ""
    competitors_direct: List[str] = field(default_factory=list)
    competitors_aspirational: List[str] = field(default_factory=list)
    competitors_avoid: List[str] = field(default_factory=list)
    geography: str = ""
    keywords: List[str] = field(default_factory=list)
    color_preferences: str = ""  # user-suggested colors / palette direction
    moodboard_notes: str = ""
    moodboard_image_paths: List[Path] = field(default_factory=list)    # general aesthetic refs
    logo_inspiration_paths: List[Path] = field(default_factory=list)   # logo inspiration images
    pattern_inspiration_paths: List[Path] = field(default_factory=list) # pattern/banner refs

    # Pattern description (from HITL pattern phase)
    pattern_description: str = ""

    # Pipeline settings
    mode: str = "full"  # "full" | "quick"

    def is_ready(self) -> bool:
        return bool(self.brand_name and self.product and self.audience)

    def summary_text(self) -> str:
        """Human-readable summary for Telegram confirmation message."""
        lines = [
            f"📛 *Brand:* {self.brand_name}",
            f"📦 *Product:* {self.product[:120]}{'...' if len(self.product) > 120 else ''}",
            f"🎯 *Audience:* {self.audience[:100]}{'...' if len(self.audience) > 100 else ''}",
        ]
        if self.tone:
            lines.append(f"🎨 *Tone:* {self.tone}")
        if _real(self.core_promise):
            lines.append(f"💬 *Core promise:* _{self.core_promise}_")
        if _real(self.geography):
            lines.append(f"🌍 *Geography:* {self.geography}")
        if _real(self.competitors_direct):
            lines.append(f"🏢 *Competitors:* {', '.join(_clean_list(self.competitors_direct))}")
        if _real(self.competitors_aspirational):
            lines.append(f"✨ *Aspirational:* {', '.join(_clean_list(self.competitors_aspirational))}")
        kws = _clean_list(self.keywords)
        if kws:
            lines.append(f"🔑 *Keywords:* {', '.join(kws[:6])}")
        if _real(self.color_preferences):
            lines.append(f"🎨 *Colors:* {self.color_preferences[:80]}{'...' if len(self.color_preferences) > 80 else ''}")
        if _real(self.moodboard_notes):
            lines.append(f"🖼 *Moodboard:* {self.moodboard_notes[:80]}...")
        total_imgs = len(self.moodboard_image_paths) + len(self.logo_inspiration_paths) + len(self.pattern_inspiration_paths)
        if total_imgs:
            parts = []
            if self.moodboard_image_paths:
                parts.append(f"{len(self.moodboard_image_paths)} moodboard")
            if self.logo_inspiration_paths:
                parts.append(f"{len(self.logo_inspiration_paths)} logo refs")
            if self.pattern_inspiration_paths:
                parts.append(f"{len(self.pattern_inspiration_paths)} pattern refs")
            lines.append(f"📸 *Images:* {', '.join(parts)}")
        lines.append(f"\n⚙️ *Mode:* {'🎨 Full (4 directions)' if self.mode == 'full' else '⚡ Quick (2 directions)'}")
        return "\n".join(lines)

    def to_brief_md(self) -> str:
        """Generate brief.md content from collected fields."""
        sections: List[str] = []

        sections.append(f"# Brand Brief — {self.brand_name}\n")

        sections.append(f"## Brand Name\n{self.brand_name}\n")

        sections.append(f"## Product\n{self.product}\n")

        sections.append(f"## Target Audience\n{self.audience}\n")

        if self.tone:
            sections.append(f"## Tone\n{self.tone}\n")

        if _real(self.core_promise):
            sections.append(f"## Core Promise\n\"{self.core_promise}\"\n")

        if _real(self.geography):
            sections.append(f"## Geography\n{self.geography}\n")

        # Competitors section
        comp_lines = []
        if _real(self.competitors_direct):
            comp_lines.append(f"Direct: {', '.join(_clean_list(self.competitors_direct))}")
        if _real(self.competitors_aspirational):
            comp_lines.append(f"Aspirational: {', '.join(_clean_list(self.competitors_aspirational))}")
        if _real(self.competitors_avoid):
            comp_lines.append(f"Avoid: {', '.join(_clean_list(self.competitors_avoid))}")
        if comp_lines:
            sections.append("## Competitors\n" + "\n".join(comp_lines) + "\n")

        if _real(self.color_preferences):
            sections.append(f"## Color Preferences\n{self.color_preferences}\n")

        if _real(self.moodboard_notes) or self.moodboard_image_paths or self.logo_inspiration_paths or self.pattern_inspiration_paths:
            moodboard_lines = []
            if _real(self.moodboard_notes):
                moodboard_lines.append(self.moodboard_notes)
            if self.logo_inspiration_paths:
                moodboard_lines.append(
                    f"\n### Logo Inspiration\n"
                    + "\n".join(f"- {p.name}" for p in self.logo_inspiration_paths)
                )
            if self.pattern_inspiration_paths:
                moodboard_lines.append(
                    f"\n### Pattern & Layout Inspiration\n"
                    + "\n".join(f"- {p.name}" for p in self.pattern_inspiration_paths)
                )
            sections.append(f"## Moodboard\n" + "\n".join(moodboard_lines) + "\n")

        kws = _clean_list(self.keywords)
        if kws:
            kw_lines = "\n".join(f"- {kw}" for kw in kws)
            sections.append(f"## Keywords\n{kw_lines}\n")

        return "\n".join(sections)

    def write_to_temp_dir(self) -> Path:
        """
        Write brief.md (and any moodboard images) to a temp directory.
        Returns the path to the temp directory.
        The caller is responsible for cleanup.
        """
        tmp = Path(tempfile.mkdtemp(prefix=f"brand_{self.brand_name.lower()[:12]}_"))

        brief_path = tmp / "brief.md"
        brief_path.write_text(self.to_brief_md(), encoding="utf-8")

        # Copy all inspiration images into temp dir, organised in subfolders
        for img_path in self.moodboard_image_paths:
            if img_path.exists():
                dest = tmp / img_path.name
                dest.write_bytes(img_path.read_bytes())

        logo_dir = tmp / "logo_inspiration"
        for img_path in self.logo_inspiration_paths:
            if img_path.exists():
                logo_dir.mkdir(exist_ok=True)
                dest = logo_dir / img_path.name
                dest.write_bytes(img_path.read_bytes())

        pattern_dir = tmp / "pattern_inspiration"
        for img_path in self.pattern_inspiration_paths:
            if img_path.exists():
                pattern_dir.mkdir(exist_ok=True)
                dest = pattern_dir / img_path.name
                dest.write_bytes(img_path.read_bytes())

        return tmp
