#!/usr/bin/env python3
"""
Enrich pattern reference index.json files with mood/industry/technique tags.

Adds category-level keyword sets so the scoring function in _fetch_pattern_refs()
can match brief keywords (product, tone, audience) against tag-level content.
"""

import json
from pathlib import Path

REFS_DIR = Path(__file__).parent.parent / "references" / "patterns"

# ── Category-level enrichment maps ─────────────────────────────────────────────
# Each category gets shared mood, industry, and technique tags.
# These supplement per-image motif/style tags that already exist.

CATEGORY_ENRICHMENT = {
    "pattern_3d_abstract": {
        "mood": ["futuristic", "dynamic", "sophisticated", "energetic", "mysterious", "premium", "bold"],
        "technique": ["gradient", "3d rendering", "layering", "reflection", "iridescent"],
        "industry": ["tech", "gaming", "crypto", "fintech", "entertainment", "luxury", "automotive"],
    },
    "pattern_abstract_gradient_mesh": {
        "mood": ["calm", "serene", "dreamy", "ethereal", "soft", "welcoming", "futuristic", "clean", "modern"],
        "technique": ["gradient", "blur", "mesh", "overlap", "translucent"],
        "industry": ["tech", "wellness", "beauty", "skincare", "meditation", "spa", "saas", "startup"],
    },
    "pattern_cultural_heritage": {
        "mood": ["warm", "energetic", "authentic", "traditional", "vibrant", "inviting", "playful", "bold"],
        "technique": ["repetition", "tessellation", "line weight", "symmetry", "interlocking"],
        "industry": ["coffee", "food", "craft", "artisan", "cultural", "heritage", "textile", "fashion",
                      "restaurant", "hotel", "travel", "handmade"],
    },
    "pattern_geometric_repeat": {
        "mood": ["calm", "elegant", "refined", "sophisticated", "luxurious", "classic", "timeless"],
        "technique": ["repetition", "tessellation", "symmetry", "grid", "interlocking", "rotation"],
        "industry": ["luxury", "fashion", "interior", "architecture", "hospitality", "jewelry",
                      "real estate", "finance"],
    },
    "pattern_icon_based_repeating": {
        "mood": ["structured", "precise", "friendly", "approachable", "playful", "modern", "clean"],
        "technique": ["repetition", "grid", "symmetry", "flat", "modular"],
        "industry": ["tech", "saas", "startup", "education", "healthcare", "branding", "enterprise"],
    },
    "pattern_line_art_monoline": {
        "mood": ["sophisticated", "calm", "elegant", "refined", "serene", "premium", "minimal", "thoughtful"],
        "technique": ["monoline", "line art", "grid", "repetition", "arc", "parallel"],
        "industry": ["luxury", "stationery", "publishing", "wellness", "spa", "cosmetics",
                      "architecture", "interior", "boutique"],
    },
    "pattern_memphis_playful": {
        "mood": ["playful", "energetic", "fun", "nostalgic", "vibrant", "cheerful", "bold", "youthful"],
        "technique": ["repetition", "scatter", "flat", "modular", "grid"],
        "industry": ["kids", "education", "toy", "snack", "candy", "party", "gaming",
                      "creative agency", "social media", "startup"],
    },
    "pattern_minimal_geometric": {
        "mood": ["calm", "clean", "minimal", "professional", "sophisticated", "precise", "orderly"],
        "technique": ["repetition", "grid", "symmetry", "flat", "dashed"],
        "industry": ["tech", "saas", "consulting", "finance", "corporate", "healthcare",
                      "architecture", "legal", "startup"],
    },
    "pattern_organic_fluid": {
        "mood": ["dynamic", "sophisticated", "artistic", "fluid", "expressive", "modern", "energetic"],
        "technique": ["organic", "fluid", "marble", "swirl", "asymmetry", "overlap"],
        "industry": ["beauty", "skincare", "cosmetics", "fashion", "art", "gallery",
                      "fragrance", "luxury", "yoga"],
    },
    "pattern_organic_natural": {
        "mood": ["calm", "serene", "natural", "earthy", "warm", "welcoming", "gentle", "organic"],
        "technique": ["repetition", "overlap", "asymmetry", "stylized", "botanical", "flat"],
        "industry": ["coffee", "tea", "food", "organic", "wellness", "beauty", "skincare",
                      "artisan", "farm", "bakery", "restaurant", "natural", "eco", "sustainable"],
    },
    "pattern_tech_grid_and_line": {
        "mood": ["futuristic", "analytical", "sophisticated", "mysterious", "complex", "serious", "innovative"],
        "technique": ["grid", "pixel", "segmented", "halftone", "digital", "modular"],
        "industry": ["tech", "ai", "data", "cyber", "fintech", "saas", "cloud",
                      "blockchain", "engineering", "robotics"],
    },
    "pattern_textile_inspired": {
        "mood": ["warm", "authentic", "grounded", "natural", "artisanal", "earthy", "soft", "handcrafted"],
        "technique": ["repetition", "weave", "zigzag", "organic", "curvilinear", "grid"],
        "industry": ["coffee", "tea", "food", "fashion", "textile", "craft", "artisan",
                      "home decor", "interior", "bakery", "restaurant", "organic", "handmade"],
    },
}


def enrich_all():
    """Inject category-level tags into every entry in every index.json."""
    total_updated = 0
    for cat_dir in sorted(REFS_DIR.iterdir()):
        if not cat_dir.is_dir():
            continue
        idx_path = cat_dir / "index.json"
        if not idx_path.exists():
            continue

        cat_name = cat_dir.name
        enrichment = CATEGORY_ENRICHMENT.get(cat_name)
        if not enrichment:
            print(f"⚠️  No enrichment defined for {cat_name}, skipping")
            continue

        data = json.loads(idx_path.read_text())
        count = 0
        for fname, entry in data.items():
            tags = entry.setdefault("tags", {})
            # Only add fields that don't already exist (preserve existing per-image tags)
            for field in ("mood", "industry", "technique"):
                if field not in tags or not tags[field]:
                    tags[field] = enrichment.get(field, [])
                    count += 1

        idx_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        total_updated += count
        n_entries = len(data)
        print(f"✅ {cat_name}: enriched {n_entries} entries ({count} new fields added)")

    print(f"\nTotal fields added: {total_updated}")


if __name__ == "__main__":
    enrich_all()
