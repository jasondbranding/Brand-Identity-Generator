"""
pattern_matcher.py — Match pattern references to styleguide .md files,
extract pattern rules, and build enhanced prompts for pattern generation.

Used by the HITL pattern phase:
  1. User uploads / selects pattern references
  2. This module scores refs against 12 pattern categories
  3. Extracts "### For PATTERNS:" rules from the best-match styleguide
  4. Combines rules + palette colors + user description into a single prompt
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import logging

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
STYLES_DIR   = PROJECT_ROOT / "styles" / "patterns"
REFS_DIR     = PROJECT_ROOT / "references" / "patterns"

# Keyword → pattern category mapping (for scoring without vision)
KEYWORD_PATTERN_MAP: Dict[str, List[str]] = {
    # Aesthetic keywords (English)
    "geometric":    ["pattern_geometric_repeat", "pattern_minimal_geometric", "pattern_tech_grid_and_line"],
    "minimal":      ["pattern_minimal_geometric", "pattern_line_art_monoline"],
    "organic":      ["pattern_organic_fluid", "pattern_organic_natural"],
    "nature":       ["pattern_organic_natural", "pattern_organic_fluid"],
    "playful":      ["pattern_memphis_playful", "pattern_icon_based_repeating"],
    "memphis":      ["pattern_memphis_playful"],
    "cultural":     ["pattern_cultural_heritage", "pattern_textile_inspired"],
    "heritage":     ["pattern_cultural_heritage"],
    "textile":      ["pattern_textile_inspired", "pattern_cultural_heritage"],
    "tech":         ["pattern_tech_grid_and_line", "pattern_geometric_repeat"],
    "digital":      ["pattern_tech_grid_and_line", "pattern_abstract_gradient_mesh"],
    "gradient":     ["pattern_abstract_gradient_mesh"],
    "abstract":     ["pattern_abstract_gradient_mesh", "pattern_3d_abstract"],
    "3d":           ["pattern_3d_abstract"],
    "line":         ["pattern_line_art_monoline", "pattern_minimal_geometric"],
    "monoline":     ["pattern_line_art_monoline"],
    "icon":         ["pattern_icon_based_repeating", "pattern_memphis_playful"],
    "fluid":        ["pattern_organic_fluid", "pattern_abstract_gradient_mesh"],
    "bold":         ["pattern_geometric_repeat", "pattern_memphis_playful"],
    "elegant":      ["pattern_minimal_geometric", "pattern_line_art_monoline", "pattern_textile_inspired"],
    "modern":       ["pattern_tech_grid_and_line", "pattern_minimal_geometric", "pattern_geometric_repeat"],
    "vintage":      ["pattern_cultural_heritage", "pattern_textile_inspired"],
    "retro":        ["pattern_memphis_playful", "pattern_cultural_heritage"],
    "clean":        ["pattern_minimal_geometric", "pattern_line_art_monoline"],
    "warm":         ["pattern_organic_natural", "pattern_textile_inspired"],
    "professional": ["pattern_minimal_geometric", "pattern_geometric_repeat", "pattern_tech_grid_and_line"],
    # Industry keywords (English)
    "coffee":       ["pattern_organic_natural", "pattern_cultural_heritage", "pattern_textile_inspired"],
    "food":         ["pattern_organic_natural", "pattern_icon_based_repeating"],
    "fashion":      ["pattern_textile_inspired", "pattern_geometric_repeat", "pattern_line_art_monoline"],
    "beauty":       ["pattern_organic_fluid", "pattern_minimal_geometric"],
    "finance":      ["pattern_minimal_geometric", "pattern_geometric_repeat"],
    "health":       ["pattern_organic_fluid", "pattern_organic_natural"],
    "startup":      ["pattern_tech_grid_and_line", "pattern_minimal_geometric"],
    "luxury":       ["pattern_minimal_geometric", "pattern_line_art_monoline", "pattern_geometric_repeat"],
    "kids":         ["pattern_memphis_playful", "pattern_icon_based_repeating"],
    "gaming":       ["pattern_3d_abstract", "pattern_tech_grid_and_line"],
    "education":    ["pattern_icon_based_repeating", "pattern_minimal_geometric"],
    # Vietnamese aesthetic keywords
    "hình học":     ["pattern_geometric_repeat", "pattern_minimal_geometric"],
    "tối giản":     ["pattern_minimal_geometric", "pattern_line_art_monoline"],
    "tự nhiên":     ["pattern_organic_natural", "pattern_organic_fluid"],
    "thiên nhiên":  ["pattern_organic_natural", "pattern_organic_fluid"],
    "vui nhộn":     ["pattern_memphis_playful", "pattern_icon_based_repeating"],
    "truyền thống": ["pattern_cultural_heritage", "pattern_textile_inspired"],
    "dệt":         ["pattern_textile_inspired", "pattern_cultural_heritage"],
    "số":          ["pattern_tech_grid_and_line", "pattern_abstract_gradient_mesh"],
    "trừu tượng":  ["pattern_abstract_gradient_mesh", "pattern_3d_abstract"],
    "thanh lịch":  ["pattern_minimal_geometric", "pattern_line_art_monoline", "pattern_textile_inspired"],
    "hiện đại":    ["pattern_tech_grid_and_line", "pattern_minimal_geometric", "pattern_geometric_repeat"],
    "cổ điển":     ["pattern_cultural_heritage", "pattern_textile_inspired"],
    "sạch":        ["pattern_minimal_geometric", "pattern_line_art_monoline"],
    "ấm":          ["pattern_organic_natural", "pattern_textile_inspired"],
    "mạnh mẽ":     ["pattern_geometric_repeat", "pattern_memphis_playful"],
    "chuyên nghiệp": ["pattern_minimal_geometric", "pattern_geometric_repeat", "pattern_tech_grid_and_line"],
    # Vietnamese industry keywords
    "phê":         ["pattern_organic_natural", "pattern_cultural_heritage", "pattern_textile_inspired"],
    "cà phê":      ["pattern_organic_natural", "pattern_cultural_heritage", "pattern_textile_inspired"],
    "trà":         ["pattern_organic_natural", "pattern_cultural_heritage"],
    "thực phẩm":   ["pattern_organic_natural", "pattern_icon_based_repeating"],
    "ẩm thực":     ["pattern_organic_natural", "pattern_icon_based_repeating", "pattern_cultural_heritage"],
    "thời trang":  ["pattern_textile_inspired", "pattern_geometric_repeat", "pattern_line_art_monoline"],
    "mỹ phẩm":    ["pattern_organic_fluid", "pattern_minimal_geometric"],
    "làm đẹp":    ["pattern_organic_fluid", "pattern_minimal_geometric"],
    "tài chính":   ["pattern_minimal_geometric", "pattern_geometric_repeat"],
    "sức khỏe":   ["pattern_organic_fluid", "pattern_organic_natural"],
    "công nghệ":   ["pattern_tech_grid_and_line", "pattern_minimal_geometric"],
    "sang trọng":  ["pattern_minimal_geometric", "pattern_line_art_monoline", "pattern_geometric_repeat"],
    "cao cấp":     ["pattern_minimal_geometric", "pattern_line_art_monoline"],
    "trẻ em":      ["pattern_memphis_playful", "pattern_icon_based_repeating"],
    "giáo dục":    ["pattern_icon_based_repeating", "pattern_minimal_geometric"],
    "nông sản":    ["pattern_organic_natural", "pattern_cultural_heritage"],
    "hữu cơ":     ["pattern_organic_natural", "pattern_organic_fluid"],
    "đặc sản":    ["pattern_cultural_heritage", "pattern_organic_natural"],
}


# ── Public API ───────────────────────────────────────────────────────────────


def match_styleguide(
    brief_keywords: Optional[List[str]] = None,
    pattern_refs: Optional[List[Path]] = None,
) -> Optional[Path]:
    """
    Score 12 pattern styleguides against brief keywords and ref image tags.
    Returns the .md path of the best-matching styleguide, or None.
    """
    scores: Dict[str, float] = {}

    # ── Score from keywords ────────────────────────────────────────────────
    kw_set = {w.lower() for w in (brief_keywords or []) if len(w) > 2}
    for kw in kw_set:
        for cat in KEYWORD_PATTERN_MAP.get(kw, []):
            scores[cat] = scores.get(cat, 0) + 2.0

    # ── Score from pattern ref images (match against index.json tags) ──────
    if pattern_refs:
        for ref_path in pattern_refs:
            ref_name = Path(ref_path).name
            # Check which category folder contains this ref
            for cat_dir in sorted(REFS_DIR.iterdir()):
                if not cat_dir.is_dir():
                    continue
                index_path = cat_dir / "index.json"
                if not index_path.exists():
                    continue
                try:
                    index = json.loads(index_path.read_text())
                    if ref_name in index:
                        # Direct match — this ref belongs to this category
                        scores[cat_dir.name] = scores.get(cat_dir.name, 0) + 10.0
                        # Also score from ref tags
                        tags = index[ref_name].get("tags", {})
                        motif = tags.get("motif", "")
                        if motif:
                            for word in motif.lower().split():
                                if word in kw_set:
                                    scores[cat_dir.name] = scores.get(cat_dir.name, 0) + 1.0
                except Exception:
                    continue

    if not scores:
        # Fallback: pick geometric_repeat as safe default
        scores["pattern_geometric_repeat"] = 1.0

    # Find best match
    best_cat = max(scores, key=scores.get)
    styleguide_path = STYLES_DIR / f"{best_cat}.md"

    if styleguide_path.exists():
        logger.info(f"Pattern styleguide match: {best_cat} (score={scores[best_cat]:.1f})")
        return styleguide_path

    return None


def extract_pattern_rules(styleguide_path: Path) -> str:
    """
    Read a styleguide .md file and extract the "### For PATTERNS:" section.
    Returns the raw text of the pattern rules, or empty string.
    """
    if not styleguide_path or not styleguide_path.exists():
        return ""

    try:
        content = styleguide_path.read_text(encoding="utf-8")
        # Find "For PATTERNS:" section (##, ###, or ####)
        match = re.search(
            r"#{2,4}\s+For\s+PATTERNS:\s*\n(.*?)(?=\n#{2,4}\s+For\s|\Z)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
    except Exception as e:
        logger.warning(f"Failed to read styleguide: {e}")

    return ""


def build_pattern_prompt(
    direction: object,
    brief_keywords: Optional[List[str]] = None,
    pattern_refs: Optional[List[Path]] = None,
    user_description: Optional[str] = None,
    palette_colors: Optional[List[dict]] = None,
    refinement_feedback: Optional[str] = None,
) -> str:
    """
    Build an enhanced pattern generation prompt by combining:
      1. Styleguide rules (from best-matching .md)
      2. Direction pattern spec
      3. User description (natural language)
      4. Palette colors
      5. Refinement feedback

    Returns a complete prompt string for _generate_image().
    """
    parts: List[str] = []

    # ── 1. Base prompt from direction spec ─────────────────────────────────
    spec = getattr(direction, "pattern_spec", None)
    if spec is not None:
        try:
            from .generator import _pattern_spec_to_prompt
            base = _pattern_spec_to_prompt(spec)
            parts.append(base)
        except Exception:
            base = getattr(direction, "pattern_prompt", "") or ""
            if base:
                parts.append(base)
    else:
        base = getattr(direction, "pattern_prompt", "") or ""
        if base:
            parts.append(base)

    # ── 2. Styleguide rules ────────────────────────────────────────────────
    styleguide_path = match_styleguide(brief_keywords, pattern_refs)
    if styleguide_path:
        rules = extract_pattern_rules(styleguide_path)
        if rules:
            # Condense rules into key constraints
            condensed = _condense_rules(rules)
            if condensed:
                parts.append(f"STYLE GUIDE RULES: {condensed}")

    # ── 3. User description (HIGHEST PRIORITY — overrides base prompt) ─────
    if user_description and user_description.strip():
        parts.insert(0, f"CRITICAL USER REQUEST (MUST FOLLOW): {user_description.strip()}")

    # ── 4. Palette colors ──────────────────────────────────────────────────
    if palette_colors:
        hex_list = [c.get("hex", "") for c in palette_colors if c.get("hex")]
        if hex_list:
            parts.append(f"Use EXACTLY these brand palette colors: {', '.join(hex_list)}.")

    # ── 5. Refinement feedback (HIGH PRIORITY — apply these changes) ────────
    if refinement_feedback and refinement_feedback.strip():
        parts.insert(0, f"MANDATORY REFINEMENT (MUST APPLY): {refinement_feedback.strip()}")

    # ── 6. Technical quality anchors ───────────────────────────────────────
    parts.append(
        "All 4 edges must align perfectly for seamless tiling. "
        "Professional surface/textile design quality. "
        "Absolutely no text, no logos, no watermarks."
    )

    return " ".join(p for p in parts if p.strip())


def _condense_rules(rules_text: str) -> str:
    """
    Condense verbose styleguide rules into key prompt constraints.
    Extracts motif types, rendering style, vibe/mood, and avoid list.

    Regex patterns are intentionally broad to handle format variations
    across the 12 styleguide .md files (different heading levels,
    bold markers, naming conventions).
    """
    condensed_parts: List[str] = []

    def _extract_field(pattern: str, max_len: int = 200) -> str:
        """Extract first match, clean up markdown artifacts, trim to max_len."""
        m = re.search(pattern, rules_text, re.DOTALL | re.IGNORECASE)
        if not m:
            return ""
        text = m.group(1).strip()
        # Clean markdown bold/italic markers
        text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
        # Collapse multiple whitespace/newlines into single space
        text = re.sub(r"\s+", " ", text)
        if len(text) > max_len:
            text = text[:max_len].rsplit(".", 1)[0] + "."
        return text

    # Extract motif types — handles "Dominant Motif Types", with or without
    # bold markers, colons inside/outside bold, nested bullets
    motif = _extract_field(
        r"Dominant\s+Motif\s+Types\s*[:\*]*\s*(.+?)(?=\n\s*\*\s*\*\*|\n\d+\.\s|\Z)"
    )
    if motif:
        condensed_parts.append(f"Motifs: {motif}")

    # Extract rendering style — handles "Rendering", "Rendering Style",
    # "Rendering:" with various markdown formatting
    render = _extract_field(
        r"Rendering(?:\s+Style)?\s*[:\*]*\s*(.+?)(?=\n\s*\*\s*\*\*|\n\d+\.\s|\Z)",
        max_len=100,
    )
    if render:
        condensed_parts.append(f"Style: {render}")

    # Extract vibe/mood — handles "Vibe", "Overall Vibe", "Mood",
    # "Emotional Feel", "Personality impact"
    vibe = _extract_field(
        r"(?:Overall\s+)?(?:Vibe|Mood|Emotional\s+Feel|Personality\s+impact)\s*[:\*]*\s*(.+?)(?=\n\s*\*\s*\*\*|\n\d+\.\s|\Z)",
        max_len=100,
    )
    if vibe:
        condensed_parts.append(f"Mood: {vibe}")

    # Extract avoid list — handles various formats:
    # "6. **Avoid**", "#### 6. Avoid:", "### 6. Avoid (PATTERNS)"
    avoid_match = re.search(
        r"Avoid(?:\s*\([^)]*\))?\s*[:\*]*\s*\n(.*?)(?=\n#{2,4}\s|\n\d+\.\s+\*\*|\Z)",
        rules_text, re.DOTALL | re.IGNORECASE,
    )
    if avoid_match:
        avoid_lines = []
        for line in avoid_match.group(1).strip().split("\n"):
            line = line.strip().lstrip("*- ·•")
            # Clean markdown bold
            line = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", line).strip()
            if line and len(line) > 3:
                avoid_lines.append(line.rstrip("."))
        if avoid_lines:
            condensed_parts.append(f"Avoid: {'; '.join(avoid_lines[:5])}.")

    return " ".join(condensed_parts)
