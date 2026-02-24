"""
researcher.py — Brand market researcher using Gemini Search Grounding.

Provides:
  BrandResearcher.research(brief_text, keywords) → ResearchResult
    - Uses Google Search Grounding to analyze competitors and trends
    - Generates reference image search queries

  BrandResearcher.match_references(keywords, index_dir) → list
    - Score-based matching against local reference index.json
    - Returns top-5 scored items
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from google import genai
from google.genai import types
from rich.console import Console

console = Console()


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class ResearchResult:
    """Output from BrandResearcher.research()."""
    market_context: str = ""
    reference_queries: List[str] = field(default_factory=list)
    matched_refs: List[dict] = field(default_factory=list)

    def to_director_context(self) -> str:
        """Format for injection into director's user message."""
        if not self.market_context:
            return ""

        parts = ["## MARKET RESEARCH CONTEXT (Google Search Grounding)\n"]
        parts.append(self.market_context)

        if self.reference_queries:
            parts.append("\n\n### Suggested Reference Image Searches:")
            for q in self.reference_queries[:5]:
                parts.append(f"  - {q}")

        return "\n".join(parts)


# ── Researcher ────────────────────────────────────────────────────────────────

RESEARCH_PROMPT_TEMPLATE = """\
You are a senior brand strategist. Analyze this brand brief and provide market research context.

## Brand Brief:
{brief_text}

## Keywords: {keywords}

Please research and provide:
1. **Competitive Landscape**: What are the key visual conventions in this market? Who are the main players and how do they look?
2. **Design Trends**: What are the current design trends in this industry/category?
3. **Differentiation Opportunities**: Where is there visual white space in the market?
4. **Reference Searches**: Suggest 5 specific search queries for finding visual inspiration images (for logos, patterns, backgrounds separately).

Format your response clearly with headers. Be specific and actionable.
"""

QUERIES_PROMPT = """\
Based on this brand brief, generate 5-8 specific visual reference search queries.
Each query should be suitable for searching a design portfolio site like Dribbble.

Brief: {brief_text}
Keywords: {keywords}

Return ONLY a JSON array of query strings, no explanation.
Example: ["minimalist fintech logo geometric", "abstract finance pattern blue", "corporate identity clean tech"]
"""


class BrandResearcher:
    """
    Researches market context and finds reference images for brand directions.
    """

    def __init__(self, api_key: str) -> None:
        self.client = genai.Client(api_key=api_key)

    def research(self, brief_text: str, keywords: list) -> ResearchResult:
        """
        Perform market research using Google Search Grounding + generate reference queries.

        Args:
            brief_text: The raw brief text
            keywords: List of brand keywords

        Returns:
            ResearchResult with market context and search queries
        """
        result = ResearchResult()
        kw_str = ", ".join(keywords[:10]) if keywords else "brand identity"

        # ── Step 1: Google Search Grounding for market context ─────────────────
        try:
            console.print("  [dim]Researching market context (Gemini + Search)...[/dim]")
            prompt = RESEARCH_PROMPT_TEMPLATE.format(
                brief_text=brief_text[:2000],
                keywords=kw_str,
            )

            search_tool = types.Tool(google_search=types.GoogleSearch())

            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[search_tool],
                ),
            )
            result.market_context = response.text or ""

            if result.market_context:
                # Truncate to reasonable length for director context
                if len(result.market_context) > 2000:
                    result.market_context = result.market_context[:2000] + "\n[...truncated]"
                console.print(
                    f"  [dim]Market research: {len(result.market_context)} chars[/dim]"
                )

        except Exception as e:
            console.print(f"  [yellow]⚠ Search grounding failed: {e}[/yellow]")

        # ── Step 2: Generate reference image search queries ────────────────────
        try:
            console.print("  [dim]Generating reference search queries...[/dim]")
            queries_prompt = QUERIES_PROMPT.format(
                brief_text=brief_text[:1000],
                keywords=kw_str,
            )

            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=queries_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )

            raw = (response.text or "").strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.rsplit("```", 1)[0]

            queries = json.loads(raw)
            if isinstance(queries, list):
                result.reference_queries = [str(q) for q in queries[:8]]
                console.print(
                    f"  [dim]Generated {len(result.reference_queries)} reference queries[/dim]"
                )

        except Exception as e:
            console.print(f"  [yellow]⚠ Query generation failed: {e}[/yellow]")

        return result

    def match_references(
        self,
        keywords: list,
        index_dir: Path,
        top_n: int = 5,
    ) -> list:
        """
        Score local reference images against brand keywords.

        Scoring: |kw_set ∩ all_tags| + quality/10

        Args:
            keywords: List of brand keywords to match
            index_dir: Directory containing index.json
            top_n: Max number of results to return

        Returns:
            List of top-scored index entries, sorted by score descending
        """
        index_path = index_dir / "index.json"
        if not index_path.exists():
            return []

        try:
            index = json.loads(index_path.read_text())
        except Exception:
            return []

        if not index:
            return []

        kw_set = {k.lower().strip() for k in keywords if k}
        scored = []

        for filename, entry in index.items():
            tags = entry.get("tags", {})
            if not tags:
                continue

            # Collect all tag words from the entry
            all_tags: set[str] = set()

            tag_type = tags.get("type", "")
            if tag_type:
                all_tags.add(tag_type.lower())

            for lst_key in ("style", "industry", "mood"):
                for t in tags.get(lst_key, []):
                    all_tags.update(t.lower().split())

            description = tags.get("description", "").lower()
            all_tags.update(description.split())

            # Score = keyword overlap + quality bonus
            overlap = len(kw_set & all_tags)
            quality = tags.get("quality", 5)
            score = overlap + (quality / 10.0)

            if score > 0 or overlap > 0:
                local_path = entry.get("local_path", "")
                if local_path and Path(local_path).exists():
                    scored.append({
                        "filename": filename,
                        "local_path": local_path,
                        "score": score,
                        "overlap": overlap,
                        "tags": tags,
                        "title": entry.get("title", ""),
                    })

        # Sort by score descending, return top_n
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_n]
