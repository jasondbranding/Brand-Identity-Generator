# AGENT HANDOFF — Brand Identity Generator
> **Cook Series · Đào Hải Sơn** | Last updated: 2026-02-25
>
> This document is the single source of truth for any agent picking up this project.
> Read it fully before doing anything. It tells you exactly what is built, what works,
> what is broken/pending, and what to do next.

---

## ⚡ RESUME HERE — What to do first

```bash
# 1. Tag all reference images (MUST run on your Mac — google-genai not available in VM)
python scripts/build_reference_index.py
# May hit Gemini quota — just re-run; skips already-correct entries
# If an entry has "motif" field (wrong prompt), script auto-detects and re-tags it

# 2. Generate per-category style guides (run after all categories are indexed)
python scripts/generate_style_guide.py
# Output: styles/logos/industry_technology_saas.md, styles/logos/style_minimal_geometric.md …

# 3. Commit and push everything
git add references/logos/*/index.json styles/logos/*.md AGENT_HANDOFF.md
git commit -m "feat(references): complete reference index and style guides"
git push origin main
```

> ⚠️ **These scripts CANNOT run in the Cowork/VM sandbox** — they import `google.genai`
> which is not installed in that environment. Run them directly on your Mac terminal.

---

## 1. Project overview

A CLI tool that takes a brand brief (Markdown) and generates a full visual identity kit:
- 3 brand direction options (via Claude Sonnet)
- 3 images per direction: background, logo, pattern (via Gemini / Imagen 3)
- Logo variants: white / black / transparent (Pillow)
- AI-composited mockups (product photos with brand applied, via Gemini multimodal)
- Stylescape boards (14-cell grid, via Pillow compositor)
- 3 social post PNGs per direction + combined board (16:9, for X/Twitter)

**Stack:** Python · Anthropic Claude SDK · Google Gemini SDK · Pillow · Rich
**Repo:** https://github.com/jasondbranding/Brand-Identity-Generator
**Run:** `python -m src.main --brief briefs/full/brief.md --mode full`

---

## 2. Repository structure

```
brand-identity-generator/
│
├── src/
│   ├── main.py                  # Entry point — orchestrates 4 pipeline steps
│   ├── parser.py                # Parses brief.md → BriefData
│   ├── director.py              # Claude → 3 BrandDirection objects (JSON-structured)
│   ├── generator.py             # Gemini/Imagen3 → background.png, logo.png, pattern.png
│   ├── compositor.py            # Pillow → 14-cell stylescape board
│   ├── mockup_compositor.py     # Gemini multimodal → AI-composited mockup photos
│   ├── social_compositor.py     # Gemini → 3 social post PNGs + board (16:9)
│   ├── researcher.py            # Gemini Search Grounding → market research (optional)
│   ├── visualizer.py            # Rich terminal display helpers
│   └── design_system.py        # Design token helpers
│
├── scripts/
│   ├── build_reference_index.py # Auto-tag reference images with Gemini Vision → index.json
│   ├── generate_style_guide.py  # Gemini → per-category style guide .md in styles/logos/
│   ├── upscale_originals.py     # Nano Banana Pro re-render of original mockup photos
│   ├── crawl_pinterest.py       # Pinterest scraper (Selenium) — needs Mac
│   └── build_reference_library.py
│
├── references/
│   └── logos/                   # 21 category subfolders of logo reference JPGs
│       ├── abstract tech/               ← ❌ NOT INDEXED
│       ├── alphabet/                    ← ❌ NOT INDEXED
│       ├── animal_character/            ← ❌ NOT INDEXED
│       ├── industry_education_edtech/   ← ⚠️ 40 entries, WRONG PROMPT (motif not form)
│       ├── industry_fashion_beauty/     ← ⚠️ 41 entries, WRONG PROMPT (motif not form)
│       ├── industry_finance_crypto/     ← ⚠️ 44 entries, WRONG PROMPT (motif not form)
│       ├── industry_food_beverage/      ← ⚠️ 44 entries, WRONG PROMPT (motif not form)
│       ├── industry_healthcare_wellness/← ❌ NOT INDEXED
│       ├── industry_media_gaming/       ← ❌ NOT INDEXED
│       ├── industry_real_estate/        ← ❌ NOT INDEXED
│       ├── industry_retail_ecommerce/   ← ❌ NOT INDEXED
│       ├── industry_technology_saas/    ← ❌ NOT INDEXED
│       ├── style_bold_brutalist/        ← ❌ NOT INDEXED
│       ├── style_corporate_enterprise/  ← ❌ NOT INDEXED
│       ├── style_elegant_editorial/     ← ❌ NOT INDEXED
│       ├── style_luxury_premium/        ← ❌ NOT INDEXED
│       ├── style_minimal_geometric/     ← ❌ NOT INDEXED
│       ├── style_organic_natural/       ← ❌ NOT INDEXED
│       ├── style_playful_mascot/        ← ❌ NOT INDEXED
│       ├── style_retro_vintage/         ← ❌ NOT INDEXED
│       └── style_tech_futuristic/       ← ❌ NOT INDEXED
│
├── styles/
│   └── logos_style.md           # OLD flat style guide — no longer used by pipeline
│   # styles/logos/{category}.md — per-category guides DO NOT EXIST YET
│   # They are generated by generate_style_guide.py after indexing completes
│
├── briefs/
│   └── full/brief.md            # NuRange demo brief (shows brief format)
│
├── mockups/
│   └── originals/               # 10 upscaled product mockup photos
│
├── outputs/
│   └── {timestamp}/             # One folder per pipeline run
│       ├── directions.md / .json
│       ├── option_{N}_{slug}/
│       │   ├── background.png
│       │   ├── logo.png / logo_white.png / logo_black.png / logo_transparent.png
│       │   ├── pattern.png
│       │   ├── mockups/
│       │   └── social/
│       │       ├── collab_post.png
│       │       ├── announcement_post.png
│       │       ├── ads_post.png
│       │       └── social_board.png
│       └── stylescape_{N}_{slug}.png
│
├── .env                         # GEMINI_API_KEY + ANTHROPIC_API_KEY (gitignored)
├── .env.example                 # Safe template (committed)
└── AGENT_HANDOFF.md             # ← This file
```

---

## 3. Pipeline — step by step

```
brief.md
   │
   ▼ Step 1 — parser.py
   BriefData (brand_name, keywords, tone, tagline?, slogan?, announcement?)
   │
   ▼ Step 1b — researcher.py (optional, --no-research to skip)
   MarketResearch (competitor analysis via Gemini Search Grounding)
   │
   ▼ Step 2 — director.py  [Claude Sonnet 4.5]
   3× BrandDirection (direction_name, colors, logo_prompt, pattern_prompt,
                       background_prompt, tagline, ad_slogan, announcement_copy)
   │
   ▼ Step 3 — generator.py  [Imagen 3 → gemini-2.5-flash-image → gemini-3-pro-image-preview]
   Per direction:
     ├─ _resolve_direction_tags()  ← Gemini text: extracts 6-12 taxonomy tags
     │   └─ effective_keywords (AI tags merged with user keywords)
     ├─ background.png   (1536×864 16:9)
     ├─ logo.png         (800×800 white bg) + white / black / transparent variants
     │   ├─ _get_style_guide(effective_keywords)     → styles/logos/{category}.md
     │   └─ _get_reference_images(effective_keywords) → references/logos/{category}/
     └─ pattern.png      (800×800 seamless tile)
         ├─ _get_style_guide(effective_keywords)
         └─ _get_reference_images(effective_keywords)
   │
   ▼ Step 3b — mockup_compositor.py  [Gemini multimodal]
   Per direction: up to 10 AI-composited mockup photos
   │
   ▼ Step 3c — social_compositor.py  [Gemini image gen]
   Per direction: collab_post, announcement_post, ads_post PNGs + social_board.png
   │
   ▼ Step 4 — compositor.py  [Pillow]
   stylescape_{N}_{slug}.png — 14-cell grid board
   │
   ▼ Human-in-the-loop review
   Approve or give feedback → refinement loop back to Step 2
```

---

## 4. All modules — what was built / changed

### `src/parser.py`
- Parses brief Markdown into `BriefData` dataclass
- **NEW:** Extracts optional copy sections via `_extract_section()`:
  - `## Tagline` → `BriefData.tagline`
  - `## Slogan` or `## Ad Slogan` → `BriefData.ad_slogan`
  - `## Announcement` → `BriefData.announcement_copy`

### `src/director.py`
- Claude Sonnet generates 3 × `BrandDirection` (Pydantic JSON-structured output)
- **NEW:** `BrandDirection` has 3 required copy fields: `tagline`, `ad_slogan`, `announcement_copy`
- **NEW:** COPY OVERRIDE RULE injected into system prompt — if brief has locked copy, Claude must use it verbatim across all 3 directions

### `src/generator.py`
- Generates background / logo / pattern images per direction
- **NEW: `_resolve_direction_tags(brief_text, direction, user_keywords)`**
  - Gemini text call → extracts 6–12 taxonomy tags (industry / style / mood / technique)
  - Merges with user keywords → `effective_keywords`
  - Called ONCE per direction, reused for both logo and pattern
  - Falls back to user keywords on error
- **NEW: `_get_reference_images(effective_keywords, ref_type)`**
  - Searches ALL category subdirs (not just top-level index)
  - Scores by: category folder name overlap (2× bonus) + tag overlap + quality
  - Handles both `relative_path` (new) and `local_path` (legacy) in index entries
- **NEW: `_get_style_guide(effective_keywords, label)`**
  - Finds best matching `.md` in `styles/logos/` or `styles/patterns/`
  - Score by keyword overlap with filename
- Both ref images + style guide injected in same Gemini multimodal call for logo/pattern
- **Image model ladder:** Imagen 3 → `gemini-2.5-flash-image` → `gemini-3-pro-image-preview` → `gemini-2.0-flash-exp-image-generation`

### `src/social_compositor.py` ← NEW module
- 3 social post types per direction (16:9, for X/Twitter):
  - `collab_post` — brand × partner split
  - `announcement_post` — logo top + announcement copy center
  - `ads_post` — large slogan + small logo corner
- `social_board.png` — all 3 combined
- **3-level copy priority chain:**
  1. `brief_tagline` / `brief_slogan` / `brief_announcement` (locked from brief.md)
  2. `direction.tagline` / `ad_slogan` / `announcement_copy` (Claude-generated)
  3. `_generate_copy_from_brief()` — Gemini generates from full brief context
- Logs which source level each field came from

### `scripts/build_reference_index.py`
- Tags reference images with Gemini Vision → writes `index.json` per category
- **FIXED BUG:** Was using `PATTERN_PROMPT` for `logos/*` subdirs because check was
  `ref_type == "logos"` — missed paths like `logos/industry_fashion_beauty`
- **FIX:** `_is_logos_type(ref_type)` helper checks `startswith("logos/")`
- New entries stored as `relative_path` (portable) not absolute `local_path`
- Auto-detects wrong-prompt entries (have `motif` not `form`) and re-tags them
- Quota detection: saves progress and exits cleanly, lists remaining categories
- **IMPORTANT:** Requires `google-genai` — must run on Mac, not in VM

### `scripts/generate_style_guide.py`
- Generates per-category style guide `.md` from indexed images
- **FIXED:** Same `_is_logos_type()` fix + handles `relative_path`
- Output: `styles/logos/{category_name}.md`
- **IMPORTANT:** Must run AFTER `build_reference_index.py` completes all categories

---

## 5. Reference index status — MOST CRITICAL PENDING TASK

This is the #1 blocker. Until categories are indexed and style guides exist,
`_get_reference_images()` and `_get_style_guide()` return empty — logo/pattern
generation gets zero reference signal.

| Status | Category | Entries |
|--------|----------|---------|
| ⚠️ Wrong prompt | `industry_education_edtech` | 40 — has `motif` field, needs re-tag |
| ⚠️ Wrong prompt | `industry_fashion_beauty` | 41 — has `motif` field, needs re-tag |
| ⚠️ Wrong prompt | `industry_finance_crypto` | 44 — has `motif` field, needs re-tag |
| ⚠️ Wrong prompt | `industry_food_beverage` | 44 — has `motif` field, needs re-tag |
| ❌ Not indexed | `abstract tech` | — |
| ❌ Not indexed | `alphabet` | — |
| ❌ Not indexed | `animal_character` | — |
| ❌ Not indexed | `industry_healthcare_wellness` | — |
| ❌ Not indexed | `industry_media_gaming` | — |
| ❌ Not indexed | `industry_real_estate` | — |
| ❌ Not indexed | `industry_retail_ecommerce` | — |
| ❌ Not indexed | `industry_technology_saas` | — |
| ❌ Not indexed | `style_bold_brutalist` | — |
| ❌ Not indexed | `style_corporate_enterprise` | — |
| ❌ Not indexed | `style_elegant_editorial` | — |
| ❌ Not indexed | `style_luxury_premium` | — |
| ❌ Not indexed | `style_minimal_geometric` | — |
| ❌ Not indexed | `style_organic_natural` | — |
| ❌ Not indexed | `style_playful_mascot` | — |
| ❌ Not indexed | `style_retro_vintage` | — |
| ❌ Not indexed | `style_tech_futuristic` | — |

**How `build_reference_index.py` handles wrong-prompt entries:**
It auto-detects entries with `motif` field (instead of `form`) and re-tags them
automatically on the next run — no manual cleanup needed.

**Quota behaviour:**
Gemini free tier hits quota after ~50–80 images. The script saves progress after
each image and exits cleanly. Just re-run — it skips already-correct entries.
~5–6 runs across different days may be needed for all 21 categories.

---

## 6. Copy priority chain

```
Brief has ## Tagline section?
  YES → Use verbatim, LOCKED across all 3 directions
  NO  → Did Claude direction generate non-empty tagline?
          YES → Use Claude's tagline
          NO  → Gemini generates from full brief context
```
Same logic applies to `ad_slogan` and `announcement_copy`.

---

## 7. Brief format

```markdown
# Brand Brief — {Brand Name}

## Brand Name
{name}

## Product
{what it does}

## Target Audience
{who uses it}

## Tone
{voice / personality}

## Core Promise
{1-sentence value prop}

## Competitors
{who they compete with}

## What makes {Brand} different
{differentiation}

## Copy  ← OPTIONAL — remove entire section to let AI generate
## Tagline
{verbatim — will be used LOCKED across all directions}
## Slogan
{verbatim ad slogan}
## Announcement
{verbatim launch copy}
```

---

## 8. Environment variables

```bash
# .env (gitignored — create from .env.example)
ANTHROPIC_API_KEY=...   # Required — Claude Sonnet for brand directions
GEMINI_API_KEY=...      # Required — Gemini/Imagen for images, tagging, social posts
PINTEREST_EMAIL=...     # Optional — only for scripts/crawl_pinterest.py
PINTEREST_PASSWORD=...  # Optional
```

---

## 9. Commit history (all relevant)

| Commit | What |
|--------|------|
| `4393b1b` | `_resolve_direction_tags()` — AI auto-extracts taxonomy tags from brief+direction, no manual keywords needed |
| `0ecf6a8` | Fix: ref images + style guide both used for logo/pattern (was not wired) |
| `140c83b` | Fix: reference index tagging bug (wrong prompt for logos subdirs), model ladder, relative paths |
| `62e5b18` | Copy fallback: Gemini generates copy from brief if AI direction copy empty |
| `1d7cc87` | Brief copy override: pre-written tagline/slogan/announcement from brief.md |
| `2cd58c9` | Social posts: 3 × 16:9 posts + board for X/Twitter |
| `03a9dd2` | Security: Pinterest env vars in .env.example |
| `8f55fe2` | Reference logos library + secure .gitignore |

---

## 10. Priority task list

### 🔴 P0 — Do this first (on Mac terminal, not in Cowork)
1. `python scripts/build_reference_index.py` — tag all 21 categories
   - May need multiple runs (Gemini quota ~50–80 images/day on free tier)
   - Auto-retags the 4 wrong-prompt categories
2. `python scripts/generate_style_guide.py` — generate `styles/logos/*.md`
3. `git add references/logos/*/index.json styles/logos/*.md AGENT_HANDOFF.md && git push`

### 🟡 P1 — Test after references are complete
4. Run full pipeline: `python -m src.main --brief briefs/full/brief.md --mode full`
5. Verify social posts render correctly (`outputs/{ts}/option_*/social/*.png`)
6. Verify ref images and style guide are being injected (check console output for `auto-tags:`, `ref images:`, `style guide injected` lines)

### 🟢 P2 — Future improvements
7. `references/patterns/` folder doesn't exist — same indexing pipeline applies
8. More mockup originals (currently 10; could add packaging, apparel, digital)
9. Stylescape board layout polish
10. Social post typography improvements

---

## 11. Known issues / gotchas

- `google-genai` is not installed in the Cowork VM sandbox. All scripts that import it (`build_reference_index.py`, `generate_style_guide.py`, the full `src/` pipeline) must be run on your Mac locally.
- `styles/logos_style.md` in the `styles/` root is an OLD flat file from before the per-category refactor — it is not used by the pipeline. Per-category guides go in `styles/logos/{category}.md`.
- Logo white-removal (`_create_logo_variants`) uses brightness threshold 240. If a brand color is near-white, it may be partially removed — known trade-off.
- Gemini image model names (`gemini-2.5-flash-image`, `gemini-3-pro-image-preview`) may change — if you get 404 errors, check Google AI Studio for current model strings and update the `_gen_models` ladder in `generator.py`.
- `industry_education_edtech/index.json` uses absolute `local_path` keys for some entries (legacy format). The pipeline handles both `relative_path` and `local_path` — no action needed.
