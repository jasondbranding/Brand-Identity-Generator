# 🎨 Brand Identity Generator

> **From a brand brief → 4 complete brand identity directions in under 5 minutes.**
> An AI agent that acts as a Creative Director — researching the market, ideating visual concepts, generating production-ready brand assets, and compositing them onto real-world mockups.

[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![Gemini API](https://img.shields.io/badge/Gemini-2.5_Flash-4285F4.svg)](https://ai.google.dev/)
[![Imagen 3](https://img.shields.io/badge/Imagen-3-34A853.svg)](https://ai.google.dev/)
[![Telegram Bot](https://img.shields.io/badge/Interface-Telegram_Bot-26A5E4.svg)](https://core.telegram.org/bots)

---

## Problem

When a company needs a brand identity, both options are painful:

| | In-house | Agency |
|--|----------|--------|
| **Time** | Minimum 1 week | Minimum 1 month |
| **Cost** | Staff time + tools | $5,000–$50,000+ |
| **Problem** | Slow iteration, hard to test | Expensive, limited revisions |

Existing AI tools generate visuals but produce *generic, templated output* because they lack creative context: curated references, style anchoring, and multi-step design reasoning.

**This agent reduces brand identity creation from weeks to minutes, at near-zero cost — so teams can test directions, validate fast, and iterate.**

---

## How It Works

The system is a **multi-step AI agent pipeline** — not a single prompt. Each stage feeds structured output to the next, with human-in-the-loop checkpoints.

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐     ┌──────────────┐
│  Brand Brief │────▶│  Market      │────▶│  Creative      │────▶│  Asset       │
│  Parser      │     │  Researcher  │     │  Director      │     │  Generator   │
│              │     │              │     │                │     │              │
│ PDF/Markdown │     │ Google Search│     │ 4 brand        │     │ Logo, pattern│
│ → structured │     │ Grounding    │     │ directions as  │     │ palette,     │
│ BriefData    │     │ → competitor │     │ structured JSON│     │ shade scales │
│              │     │   analysis   │     │ w/ LogoSpec,   │     │              │
└─────────────┘     └──────────────┘     │ PatternSpec,   │     └──────┬───────┘
                                         │ ColorSwatch[]  │            │
                                         └────────────────┘            ▼
                                                              ┌──────────────┐
                    ┌──────────────┐     ┌──────────────┐     │  Mockup      │
                    │  ZIP Export  │◀────│  Social      │◀────│  Compositor  │
                    │              │     │  Compositor   │     │              │
                    │ All assets   │     │              │     │ AI places    │
                    │ packaged     │     │ IG, FB, X,   │     │ brand onto   │
                    │ for delivery │     │ LinkedIn,    │     │ 10+ real     │
                    │              │     │ Story posts  │     │ mockups      │
                    └──────────────┘     └──────────────┘     └──────────────┘
```

### The 4 Directions

Every run produces 4 strategically distinct brand identity options:

| # | Direction | Logic |
|---|-----------|-------|
| 1 | **Market-Aligned** | Researches competitors → designs to meet category expectations with craft |
| 2 | **Designer-Led** | Follows the moodboard faithfully, or pure design sensibility if no moodboard |
| 3 | **Hybrid** | Deliberate balance — borrows from convention (trust) + differentiates (personality) |
| 4 | **Wild Card** | Breaks from the brief. Unexpected direction that might be exactly right |

### Human-in-the-Loop

The Telegram bot supports iterative refinement at every step:

- **Phase 1 — Logo Review:** User sees 4 logo options, can pick one or request remix ("Take the color from Option 1, logo style from Option 3")
- **Phase 2 — Full Assets:** Pattern, palette, shade scales, social templates, mockups generated for the chosen direction
- **Refinement:** "Make the logo more geometric", "Soften the color palette" — only the affected asset re-generates

---

## AI Architecture — Multi-Model, Multi-Step

This is not a single-prompt wrapper. The pipeline orchestrates **6+ specialized AI calls** across different models, each with tailored prompt engineering, structured output schemas, and distinct capabilities.

### Models Used

| Model | Role | Why This Model |
|-------|------|----------------|
| **Gemini 2.5 Flash** | Market research, concept ideation, brand direction generation | Structured JSON output, Google Search Grounding, large context window |
| **Gemini 2.0 Flash** | Tag extraction, style DNA analysis, prompt translation | Fast, cost-effective for classification tasks |
| **Gemini Vision** | Style DNA extraction from reference images | Multimodal — reads logo images and extracts concrete visual attributes |
| **Imagen 3** | Logo, pattern, and background image generation | Highest quality image gen, text rendering capability |
| **Gemini 2.0 Flash** (image) | Mockup compositing — reconstructs mockup photos with brand applied | Multimodal generation — accepts image + text, outputs image |

### Pipeline Stages (in order)

```
Stage 1: Brief Parser          → BriefData (Pydantic)
Stage 2: Market Research        → Research context (Google Search Grounding)  ←─┐ parallel
Stage 3: Creative Director      → BrandDirectionsOutput (4× BrandDirection)  ←─┘
Stage 4: Batch Tag Extraction   → Tags for all 4 directions (1 call)
Stage 5: Style DNA Extraction   → Visual attributes from reference images (Gemini Vision)
Stage 6: Asset Generation       → Logo + Pattern per direction (parallel, 4 threads)
Stage 7: Palette + Shade Scales → Color system with 9 shades per color
Stage 8: Logo Variants          → White, black, transparent versions
Stage 9: Mockup Compositing     → 10+ mockups per direction (parallel, 10 threads)
Stage 10: Social Templates      → IG post, Story, Facebook, X, LinkedIn
Stage 11: ZIP Export             → Deliverable package
```

### Structured Output — Everything is JSON

The Director doesn't output free text. It outputs **Pydantic-validated structured JSON** with strict schemas:

```python
class BrandDirection(BaseModel):
    option_number: int                           # 1-4
    option_type: Literal["Market-Aligned", "Designer-Led", "Hybrid", "Wild Card"]
    direction_name: str                          # e.g. "Ember & Stone"
    rationale: str                               # Strategic reasoning
    colors: List[ColorSwatch]                    # 4-6 colors with hex + role
    typography_primary: str                      # e.g. "DM Sans, geometric sans-serif"
    graphic_style: str                           # Visual language description
    logo_spec: LogoSpec                          # ← Structured image gen spec
    pattern_spec: PatternSpec                    # ← Structured pattern spec
    background_spec: BackgroundSpec              # ← Structured background spec
    tagline: str                                 # Brand tagline
    ad_slogan: str                               # Campaign slogan
    announcement_copy: str                       # Launch copy
```

Each `LogoSpec` is a detailed render specification with 12 fields:

```python
class LogoSpec(BaseModel):
    logo_type: Literal["symbol", "abstract_mark", "lettermark", "logotype", "combination"]
    form: str              # "Two concentric arcs, negative space forms a mountain ridge"
    composition: str       # "centered, 20% padding, white background"
    color_hex: str         # "#1E3A2F"
    fill_style: str        # "solid_fill" | "outline_only" | "fill_with_outline_detail"
    stroke_weight: str     # "hairline" | "thin" | "medium" | "bold"
    typography_treatment: str
    render_style: str      # "clean flat vector"
    metaphor: str          # "Mountain ridge meets open book"
    avoid: List[str]       # ["coffee cup", "lightbulb", "gear"]
```

### Prompt Engineering — Structured Keywords, Not Prose

Logo prompts are **not** verbose paragraphs. They use a structured keyword format optimized for image generation models (~60-80 words):

```
Abstract mark logo mark, two concentric arcs negative space forms mountain ridge,
solid flat fill, Deep Forest Green #1E3A2F, monochrome single-color only,
clean flat vector, centered 20% padding white background,
MUST MATCH: medium stroke weight, sharp corners, geometric shapes,
clean digital vector rendering, solid fill, simple mark.
No text, no words, no letters.
AVOID: text, letterforms, coffee cup, gradient, drop shadow, 3D effect.
```

**Anti-cliché system:** The Director has hard-coded cliché avoids per industry (coffee → no coffee bean/mug/steam, tech → no circuit board/gear/lightbulb) and lateral territory exploration rules that force unexpected visual metaphors.

### Style DNA Extraction (Vision Pre-processing)

When the user provides a style reference image, the system doesn't just attach it and say "match this." Instead:

1. **Gemini Vision** analyzes the reference and extracts concrete visual attributes as JSON:
   ```json
   {
     "stroke_weight": "medium",
     "corner_treatment": "sharp",
     "shape_vocabulary": "geometric",
     "rendering_medium": "clean-digital-vector",
     "complexity": 2,
     "fill_style": "solid-fill",
     "not_present": ["gradients", "shadows", "3D effects"]
   }
   ```
2. These attributes become **hard constraints** injected into both the prompt text AND the multimodal image context
3. Results are **cached** — 4 directions share 1 Vision call per reference image

---

## Project Structure

```
brand-identity-generator/
├── bot/
│   ├── telegram_bot.py          # Telegram interface — conversation, HITL, media handling
│   ├── pipeline_runner.py       # Orchestrates the full pipeline, progress callbacks
│   ├── brief_builder.py         # Builds brief from Telegram conversation
│   └── pdf_report.py            # PDF export of brand directions
│
├── src/
│   ├── parser.py                # Brief parser — PDF/Markdown → BriefData
│   ├── validate.py              # Brief validator — extracts market context
│   ├── researcher.py            # Market research via Google Search Grounding
│   ├── director.py              # Creative Director — Pydantic schemas + Gemini call
│   ├── generator.py             # Image generation — Imagen 3 + Gemini multimodal
│   ├── design_system.py         # Design system generation (typography, spacing)
│   ├── palette_fetcher.py       # Curated color palette with naming + harmony
│   ├── palette_renderer.py      # Renders palette swatches as PNG
│   ├── shade_generator.py       # 9-step shade scales per color (100-900)
│   ├── pattern_matcher.py       # Matches directions to reference library
│   ├── mockup_compositor.py     # AI mockup compositing (Gemini multimodal)
│   ├── social_compositor.py     # Social media template generation
│   ├── compositor.py            # Stylescape assembly
│   └── zip_exporter.py          # ZIP packaging for delivery
│
├── scripts/
│   ├── crawl_pinterest.py       # Pinterest reference crawler
│   ├── build_reference_index.py # Index reference images with tags
│   ├── generate_style_guide.py  # Auto-generate style guides per reference
│   └── upscale_originals.py     # Upscale mockup originals
│
├── references/                  # 970+ curated reference images (indexed)
├── mockups/                     # 10+ mockup templates (originals + processed)
├── styles/                      # Style guides per reference category
├── briefs/                      # Example brand briefs
├── run_bot.py                   # Entry point — starts Telegram bot
└── requirements.txt             # Python dependencies
```

### Separation of Concerns

Each module has a single responsibility:

| Module | Input | Output | AI Model |
|--------|-------|--------|----------|
| `parser.py` | PDF/Markdown files | `BriefData` | None (local) |
| `validate.py` | `BriefData` | `MarketContext` | Gemini 2.0 Flash |
| `researcher.py` | Brief text + keywords | `ResearchResult` | Gemini 2.5 Flash + Search Grounding |
| `director.py` | Brief + research + refs | `BrandDirectionsOutput` | Gemini 2.5 Flash (structured JSON) |
| `generator.py` | Direction specs | Logo/pattern PNG files | Imagen 3 + Gemini 2.0 Flash |
| `palette_fetcher.py` | Direction colors | Enriched color list | Gemini 2.0 Flash |
| `shade_generator.py` | Color hex codes | 9-step shade scales | None (algorithmic) |
| `mockup_compositor.py` | Original photo + logo | Composited mockup | Gemini 2.0 Flash (multimodal) |
| `social_compositor.py` | Brand assets | Social media templates | Gemini 2.0 Flash (multimodal) |

---

## Performance Architecture

The pipeline is heavily parallelized to minimize wall-clock time:

| Stage | Before | After | Method |
|-------|--------|-------|--------|
| Market research + Direction gen | ~30-40s serial | ~15s parallel | `ThreadPoolExecutor` — research runs with 30s timeout while Director runs |
| Tag extraction (4 directions) | ~12s (4 calls) | ~3s (1 call) | Batched into single Gemini call returning JSON object |
| Asset generation (4 directions) | ~5 min serial | ~1 min parallel | `ThreadPoolExecutor(max_workers=4)` — all directions concurrent |
| Mockup compositing (10 mockups) | ~2.5-5 min serial | ~30-60s parallel | `ThreadPoolExecutor(max_workers=10)` — all mockups concurrent |

### Error Handling

- **Every AI call** is wrapped in try/except with graceful degradation
- **Image generation**: Imagen 3 → Gemini Flash multimodal fallback chain
- **Mockup compositing**: Exponential backoff on rate limits (`_ai_reconstruct_with_retry`)
- **Tag extraction**: Batch call fails → per-direction fallback → brief keywords fallback
- **Research**: Timeout after 30s → Director runs without research context
- **Style DNA**: Extraction fails → prompt runs without style constraints (still works)

---

## Setup

### Prerequisites

- Python 3.9+
- [Google AI Studio API Key](https://aistudio.google.com/apikey) (Gemini + Imagen access)
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### Installation

```bash
git clone https://github.com/jasondbranding/Brand-Identity-Generator.git
cd Brand-Identity-Generator

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
```

Edit `.env`:
```env
GEMINI_API_KEY=your-gemini-api-key
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_ALLOWED_CHAT_IDS=           # optional: restrict access
```

### Run

```bash
# Start the Telegram bot
python run_bot.py
```

Then message your bot on Telegram:
1. Send `/start` to begin
2. Upload a brand brief (PDF or text)
3. Optionally add moodboard images and style references
4. The agent generates 4 brand identity directions
5. Pick a direction, request refinements, get full asset kit

---

## Output Example

For each chosen direction, the agent produces:

```
outputs/bot_20260226_093000/
├── directions.json                    # Structured direction data
├── directions.md                      # Human-readable direction summary
├── option_1_ember_stone/
│   ├── logo.png                       # Primary logo mark
│   ├── logo_white.png                 # White variant
│   ├── logo_black.png                 # Black variant
│   ├── logo_transparent.png           # Transparent background
│   ├── pattern.png                    # Brand pattern tile
│   ├── palette.png                    # Color palette swatch
│   ├── shades.png                     # Shade scales (100-900)
│   ├── mockups/
│   │   ├── business_card_composite.png
│   │   ├── phone_mockup_composite.png
│   │   ├── tote_bag_composite.png
│   │   ├── tshirt_composite.png
│   │   ├── laptop_sticker_composite.png
│   │   └── ...                        # 10+ mockup types
│   └── social/
│       ├── ig_post.png
│       ├── ig_story.png
│       ├── fb_post.png
│       ├── x_post.png
│       └── linkedin_post.png
└── brand_report.pdf                   # PDF summary
```

---

## Extending

The modular architecture makes it straightforward to add:

- **New mockup types**: Add processed template to `mockups/processed/`, original to `mockups/originals/`, entry to `MOCKUP_KEY_MAP`
- **New social formats**: Add compositor function in `social_compositor.py`
- **New AI models**: Swap model strings in individual modules (each module is independent)
- **New reference images**: Drop into `references/`, run `scripts/build_reference_index.py`
- **New output formats**: Add exporter in `src/` (e.g., Figma API, Canva API)

---

## Tech Stack

| Technology | Purpose |
|------------|---------|
| **Python 3.9+** | Core language |
| **Google Gemini API** | Text generation, structured output, Vision, image gen |
| **Imagen 3** | High-quality image generation (logos, patterns, backgrounds) |
| **Pydantic v2** | Structured output validation + schema enforcement |
| **python-telegram-bot** | Telegram bot interface with conversation handlers |
| **Pillow** | Image processing (zone detection, logo variants, palette rendering) |
| **Rich** | Terminal output formatting and progress display |
| **fpdf2** | PDF report generation |

---

## License

MIT

---

*Built by [Đào Hải Sơn](https://github.com/jasondbranding) — Become Creative Director | Cook Series*
