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
    moodboard_image_paths: List[Path] = field(default_factory=list)  # downloaded Telegram photos

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
        if self.core_promise:
            lines.append(f"💬 *Core promise:* _{self.core_promise}_")
        if self.geography:
            lines.append(f"🌍 *Geography:* {self.geography}")
        if self.competitors_direct:
            lines.append(f"🏢 *Competitors:* {', '.join(self.competitors_direct)}")
        if self.competitors_aspirational:
            lines.append(f"✨ *Aspirational:* {', '.join(self.competitors_aspirational)}")
        if self.keywords:
            lines.append(f"🔑 *Keywords:* {', '.join(self.keywords[:6])}")
        if self.color_preferences:
            lines.append(f"🎨 *Colors:* {self.color_preferences[:80]}{'...' if len(self.color_preferences) > 80 else ''}")
        if self.moodboard_notes:
            lines.append(f"🖼 *Moodboard:* {self.moodboard_notes[:80]}...")
        if self.moodboard_image_paths:
            lines.append(f"📸 *Images:* {len(self.moodboard_image_paths)} moodboard photo(s)")
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

        if self.core_promise:
            sections.append(f"## Core Promise\n\"{self.core_promise}\"\n")

        if self.geography:
            sections.append(f"## Geography\n{self.geography}\n")

        # Competitors section
        comp_lines = []
        if self.competitors_direct:
            comp_lines.append(f"Direct: {', '.join(self.competitors_direct)}")
        if self.competitors_aspirational:
            comp_lines.append(f"Aspirational: {', '.join(self.competitors_aspirational)}")
        if self.competitors_avoid:
            comp_lines.append(f"Avoid: {', '.join(self.competitors_avoid)}")
        if comp_lines:
            sections.append("## Competitors\n" + "\n".join(comp_lines) + "\n")

        if self.color_preferences:
            sections.append(f"## Color Preferences\n{self.color_preferences}\n")

        if self.moodboard_notes:
            sections.append(f"## Moodboard\n{self.moodboard_notes}\n")

        if self.keywords:
            kw_lines = "\n".join(f"- {kw}" for kw in self.keywords)
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

        # Copy moodboard images into temp dir so parser finds them
        for img_path in self.moodboard_image_paths:
            if img_path.exists():
                dest = tmp / img_path.name
                dest.write_bytes(img_path.read_bytes())

        return tmp
