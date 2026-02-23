# Brand Identity Generator
> Become Creative Director — Cook Series | Đào Hải Sơn

---

> **"From a project spec + structured moodboard + brand personality keywords — the agent generates 4 distinct brand identity directions as stylescapes, ready for stakeholder review. One direction chosen → full asset kit built, vectorized, and uploaded to Figma automatically."**

---

## Problem

Creating a full brand identity is slow, expensive, and most AI-generated brand assets look generic. The missing ingredient isn't speed — it's **human creative context** and **visual knowledge depth**: the feeling, the references, the understanding of what great design looks like across industries.

This agent solves three problems:
1. **Generic output:** Structured moodboard + personality keywords + rich visual knowledge base force intentional, non-templated generation
2. **Limited creative range:** Agent continuously learns from high-quality design sources (Pinterest, Behance, agency portfolios) — like a junior designer enriching their visual library over time
3. **Production bottleneck:** Once a direction is chosen, all assets auto-build, vectorize, and upload to Figma

---

## Input

### 1. Project Brief
Auto-detected, either:
- **Logo file** (AI + PNG) — agent extracts colors, style, form language
- **spec.md** — brand name, product description, target audience, tone of voice

### 2. Structured Moodboard
Images organized into labeled folders — required for accurate interpretation:

```
/moodboard
  /logo-style       ← logo form, shape language, construction style
  /graphic-style    ← illustration style, graphic elements, visual texture
  /typography       ← typeface references, lettering style
  /color-mood       ← color palette, atmosphere, emotional tone
```
10–15+ images total. Labels are required — AI cannot reliably self-identify reference categories from unlabeled image dumps.

### 3. Brand Personality Keywords
Specific sensory and emotional descriptions — not generic adjectives:
- ❌ "Modern, clean, bold"
- ✅ "The feeling of opening a precision hardware device — weighty, satisfying, inevitable."
- ✅ "Controlled aggression — a boxer before a fight, not during. Tension without chaos."

Minimum 5 keywords, each with 2–3 sentence explanation.

### 4. Logo Symbol Direction
- Designer specifies what symbol/icon the logo should contain, OR
- Leave open → agent researches and proposes suitable symbols based on brand context

### 5. Mockup Library
A labeled collection of product mockups used to assemble stylescapes:
```
/mockups
  /social-media     ← phone screens, X/Twitter post mockups
  /print            ← business cards, letterhead, packaging
  /digital          ← laptop, tablet, dashboard UI frames
  /apparel          ← t-shirts, caps, merchandise
  /signage          ← outdoor, environmental
```
Quality mockups are critical for stylescapes that look professional, not AI-generated. This library is maintained and expanded over time.

---

## Agent Visual Knowledge Base

A core quality differentiator. The agent continuously learns from high-quality design sources — like a junior designer enriching their visual library:

**Automated learning pipeline:**
```
Agent periodically crawls:
  → Pinterest boards (curated design, branding, typography)
  → Behance (top brand identity projects, filtered by quality signals)
  → Design agency portfolios (Pentagram, Collins, DesignStudio, etc.)
  → Industry-specific visual references per product category

→ Extracted visuals tagged by: style, industry, color system, era, mood
→ Stored in visual knowledge base
→ Used to inform Option 1 (market research) and Option 4 (Wild)
```

This transforms the agent from "generating from prompt" to "generating from a deep, curated understanding of what great design looks like" — the same advantage a senior designer has over a junior one.

---

## 4 Brand Identity Options

Each spec produces **4 distinct identity directions** — genuinely different strategic and creative positions:

### Option 1 — Market-Aligned
Agent researches similar products and competitors → analyzes current design trends for this product category → synthesizes a direction that fits market expectations, done well.

*"What the market currently expects from a brand like this."*

### Option 2 — Designer-Led
Built entirely from the designer's moodboard. Agent maps structured references to design decisions — color, typography, graphic style, logo form.

*"What the designer sees when they imagine this brand."*

### Option 3 — Hybrid
A reasoned balance between market research and designer instinct. Agent proposes which elements should follow market norms (trust, recognition) and which should differentiate (memorability, personality). Includes a brief rationale for each decision.

*"Where to conform, where to stand out — and why."*

### Option 4 — Wild Card
Fully agent-driven. No moodboard constraint, no market following. Agent draws from its visual knowledge base and its own understanding of the product to propose a direction no one asked for — but might be exactly right.

*"What the agent would do if given complete creative freedom."*

---

## Output Structure

### Phase 1 — Stylescape Presentation (4 Directions)

Each of the 4 directions is presented as a **stylescape** — not a slide deck, but a visual composition that shows the full feeling of the brand direction at a glance:

**Each stylescape contains:**
- Logo concept / symbol direction
- Color palette applied in context
- Typography in use (headlines, body, labels)
- Graphic elements / patterns
- Brand applied to mockups from the mockup library:
  - X banner mockup
  - Social post example
  - Product / merchandise mockup (if relevant)
- Direction name + 2–3 sentence strategic rationale

**Format:** High-resolution image (PNG) — like the NuRange / Behance examples — assembled in Illustrator, exported flat. Ready to share with stakeholders for direction sign-off.

---

### Phase 2 — Full Asset Build (After Direction is Chosen)

Once one direction is selected:

**Brand Foundation Files**
- Logo: all sizes and versions (primary, secondary, icon, dark/light variants)
- Color system: HEX, RGB, CMYK + usage rules
- Typography: font files + usage hierarchy
- Graphic elements / patterns: vector files

**Image → Vector Conversion**
- Gemini generates raster (PNG) → Illustrator auto-traces → exports AI + SVG
- All brand assets production-ready for print, web, large format

**Social Media Template System (X / Twitter)**
Built in Illustrator with chosen brand system pre-applied:

| Template | Purpose |
|----------|---------|
| Announcement | Launch, major news |
| Collab / Partnership | Co-branding posts |
| Advertising | Promotional, CTAs |
| Feature Introduction | Product features |
| Information-heavy | Data, stats, tables |

Each template: 4 layout options, vector, copy-swappable via Illustrator Variables

**Figma Auto-Upload**
- All assets uploaded via Figma API
- Color styles, text styles, logo components, template frames created automatically
- Team builds immediately from the component system

---

## Workflow

```
Input: brief + moodboard + keywords + symbol direction + mockup library
  │
  ├─ Option 1: web search → market/competitor research → trend synthesis
  ├─ Option 2: moodboard analysis → design decisions mapped
  ├─ Option 3: market + moodboard → reasoned balance with rationale
  └─ Option 4: visual knowledge base + product understanding → free direction
  │
  ↓
Gemini generates visual assets for all 4 directions
  │
  ↓
Illustrator: assembles 4 stylescapes using mockup library
  │
  ↓
Phase 1 Output: 4 stylescape images → stakeholder selects direction
  │
  ↓ [Direction selected]
  │
Gemini generates full asset set for chosen direction
Illustrator: raster → vector, social template system
Figma API: auto-upload complete brand library
  │
  ↓
Phase 2 Output: Complete brand kit + Figma library
New assets → saved to brand library + visual knowledge base
```

---

## Tool Stack

| Tool | Role |
|------|------|
| **Claude** | Market research, moodboard analysis, keyword interpretation, design brief, prompt engineering, workflow orchestration |
| **Gemini API (paid)** | Visual generation — no watermark |
| **Illustrator + JSX** | Stylescape assembly, image→vector, template system, batch export |
| **Figma API** | Auto-upload brand components, styles, templates |
| **Claude web search + Firecrawl** | Market research (Option 1) + visual knowledge base crawling (Behance, Pinterest, agency sites) |

---

## MVP Scope (4 Days)

**Priority 1**
- Input handling: brief + structured moodboard + keywords + mockup library
- All 4 identity directions generated
- Phase 1: 4 stylescapes assembled in Illustrator
- Phase 2: full asset build for selected direction
- Image → vector via Illustrator

**Priority 2 — if time allows**
- Visual knowledge base crawling pipeline
- Social template system (3 of 5 types)
- Figma API auto-upload

**Out of scope (roadmap)**
- Full Figma component library automation
- Landing page generation
- Real-time trend monitoring

---

## Why This Agent Matters

- **Non-generic:** Structured moodboard + rich visual knowledge base → intentional, brand-specific output
- **4 real directions:** Market, designer, hybrid, wild — genuine creative options, not variations
- **Stylescape format:** Stakeholders see the full brand feeling instantly, not abstract color swatches
- **Self-improving:** Visual knowledge base grows over time → output quality improves continuously
- **Zero handoff:** Chosen direction → Figma library automatically

---

*Spec v1.0 — Day 1 | Ready for Supervisor review*
