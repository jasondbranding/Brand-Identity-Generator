# Brand Identity Generator - System Workflow & Handoff

This document outlines the end-to-end architecture and workflow of the Brand Identity Generator pipeline. It serves as a handoff document for future developers or AI agents interacting with this codebase.

## 1. Reference Data Ingestion (Offline Processing)

Before any user interacts with the system, the reference database must be populated and indexed.

1. **Pinterest Scraper (`scripts/pinterest_scraper.py`)**
   - Scrapes high-quality images from Pinterest for specific categories across Logos, Patterns, and Backgrounds.
   - Organized into folders: `references/logos/<category>`, `references/patterns/<category>`, etc.
2. **Vision Tagging & Indexing (`scripts/build_reference_index.py`)**
   - Iterates through the downloaded images.
   - Sends each image to the Gemini Vision API (`gemini-1.5-flash` or newer) with a strict JSON prompt to analyze design attributes (motif, style, technique, mood, industry, colors, quality).
   - Generates an `index.json` in each category directory containing the tagged metadata.
3. **Style Guide Generation (`scripts/generate_style_guide.py`)**
   - Reads the `index.json` for a specific category.
   - Extracts the top-quality images and their statistical metadata distribution.
   - Sends this context to Gemini to write a comprehensive Markdown Style Guide (`styles/logos/<category>.md`, `styles/patterns/<category>.md`).
   - *Key AI Rules:* For patterns, it identifies the "Emotional & Personality Impact" based on the "mood" tags.

## 2. On-Demand Generation Pipeline (`src/main.py`)

When a user initiates the pipeline (e.g., `python -m src.main --brief briefs/full/brief.md --mode full`), the following sequence occurs:

### Phase 1: Planning & Setup
1. **Parse Brief:** Reads the user's Markdown brief, extracting `keywords`, `brand_name`, `target_audience`, and attached `moodboard_images`.
2. **Market Validation (`src/validator.py`):** Gemini analyzes the brief against the real world to suggest market positioning.
3. **Market Research (`src/researcher.py`):** Simulates web searches for context and competitor analysis (optional step).

### Phase 2: Direction Generation (`src/generator.py::generate_directions`)
1. **Brainstorming:** Gemini synthesizes the brief, market research, and moodboards to propose 3-5 distinct "Brand Identity Directions" (Options).
2. **Data Structure:** Each direction is serialized into a Pydantic `BrandDirection` object containing rules for logos, patterns, colors, and typography.
3. **Initial Output:** The directions are saved locally as `directions.md` and `directions.json`.

### Phase 3: Interactive Refinement (Human-in-the-Loop)
The generator enters a `while True` loop (`src/main.py::refinement_loop`) where the user interacts via natural language.

- **Fast Intent Parsing:** A local regex script checks for hard exits or fast reverts.
- **Gemini NLP Router (`_gemini_classify`):** If the intent string isn't obvious, Gemini classifies the text into:
  - `ADJUST <instructions>`: Generates a new Option Iteration incorporating the user's modifications.
  - `REMIX <instructions>`: Merges ideas across options to spawn a new Iteration.
  - `REVERT <number>`: Rolls the entire state backward to a previous Iteration.
  - `QUIT`: Aborts.
  - `SELECT <number>`: User confirms an option. Exits loop to Phase 4.
- **Proactive Consultation (`ADVICE`):**
  - If the user explicitly asks a question (e.g., "Which is best?"), or triggers the automatic offer on Iteration 4, the `ADVICE` intent fires.
  - An expert AI Brand Strategist persona parses the brief and current options to output 6 sentences of advice.
  - Triggers diagnostic questions to debug *Incomplete Strategy* or *Vague Aesthetics* by forcing the user to define their audience or reference real-world competitor styles.

### Phase 4: Asset Generation & Export (`src/generator.py`)
Once a specific direction is `SELECT`ed:

1. **Asset Rendering Engine (`_generate_image`):**
   - Gemini maps the selected direction's tags against `index.json` to find 2 reference images per asset type (Logo, Pattern, Background).
   - Generates the AI image prompt combining the direction's instructions, reference image embeddings, client moodboards, and the `.md` Style Guide rules.
2. **Image Generation:** The prompt is sent to Google's Imagen model via the Gemini API. Images are saved to the output directory.
3. **Post-Processing & Vectorization (`_create_logo_variants` & `_save_selection`):**
   - The primary logo PNG is split into transparent, black, and white PNG variants using `Pillow`.
   - **Performance Optimized Vectorizer:** To save CPU, vectorization ONLY runs on the final `SELECT`ed logo option.
   - The black and white PNG variants are traced locally into `.svg` files using `vtracer` (Rust-backed local library).
4. **Mockup Compositing (`src/mockups.py`):** Overlays the final transparent logo and patterns onto realistic physical background templates (e.g., billboards, phones, paper).
5. **Stylescape Assembly (`src/stylescapes.py`):** Combines the brand name, typography, color palette tokens, flat assets, and mockups into a single panoramic presentation board.
6. **Social Media & Design System Docs:** Outputs drafted brand guidelines and social media post copy.

## Key Technical Decisions
- **Avoided Third-Party APIs for Vectors:** Used `vtracer` library locally for `png->svg` conversion to eliminate usage limits and guarantee offline reliability.
- **Iterative Cost Management:** Reduced Image processing load by pushing image/mockup generation strictly when commanded or at the final confirmation step, avoiding generating all images for discarded iterations unless specified.
- **Asymmetric Vector Output:** The local tracer inherently produces black SVGs natively; white permutations are achieved via string replacement logic on the raw SVG XML to flip `#000000` to `#FFFFFF` without rerunning the tracer pipeline.
