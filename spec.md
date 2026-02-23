# Brand Identity Generator
> Become Creative Director — Cook Series | Đào Hải Sơn

---

> **"From a project spec + structured moodboard + brand personality keywords — the agent generates 4 distinct brand identity directions as stylescapes, ready for stakeholder review. One direction chosen → full asset kit built, vectorized, and uploaded to Figma automatically."**

---

## Problem Statement

When a company needs a brand identity, there are two options — both are painful:

| | In-house | Agency |
|--|----------|--------|
| **Time** | Minimum 1 week | Minimum 1 month |
| **Cost** | Staff time + tools | $5,000–$50,000+ |
| **Problem** | Slow iteration, hard to test and validate quickly | Expensive, slow feedback loops, limited revisions |

For early-stage products and internal teams, this is a critical bottleneck. By the time the brand is ready, the market opportunity may have shifted. Teams can't move fast, can't test multiple brand directions, and can't afford to get it wrong.

Existing AI tools don't solve this — they generate visuals but produce generic, templated output because they lack the creative context that makes a brand distinctive: curated visual references, detailed personality descriptions, and deep knowledge of what great design looks like across industries.

**This agent reduces brand identity creation from weeks (or months) to hours — at near-zero cost — while maintaining the creative intentionality of a professional designer. Teams can test multiple directions, validate with their audience, and iterate fast.**

---

## Input

### 1. Project Brief (auto-detected)
- **Logo file** (AI + PNG) — agent extracts colors, style, form language, OR
- **spec.md** — brand name, product description, target audience, tone of voice

### 2. Structured Moodboard
Organized into labeled folders — labels required, AI cannot self-identify categories from unlabeled dumps:

```
/moodboard
  /logo-style       ← logo form, shape language, construction style
  /graphic-style    ← illustration, graphic elements, visual texture
  /typography       ← typeface references, lettering style
  /color-mood       ← color palette, atmosphere, emotional tone
```
10–15+ images total.

### 3. Brand Personality Keywords
Specific sensory and emotional descriptions — not generic adjectives:
- ❌ "Modern, clean, bold"
- ✅ "The feeling of opening a precision hardware device — weighty, satisfying, inevitable."
- ✅ "Controlled aggression — a boxer before a fight, not during. Tension without chaos."

Minimum 5 keywords, each with 2–3 sentence explanation.

### 4. Logo Symbol Direction
- Designer specifies symbol/icon the logo should contain, OR
- Leave open → agent proposes suitable symbols based on brand context and product category

### 5. Mockup Library
Labeled product mockups for stylescape assembly:
```
/mockups
  /social-media     ← phone screens, X/Twitter post mockups
  /print            ← business cards, letterhead, packaging
  /digital          ← laptop, tablet, dashboard UI frames
  /apparel          ← t-shirts, caps, merchandise
  /signage          ← outdoor, environmental
```

---

## Agent Visual Knowledge Base

The agent continuously learns from high-quality design sources — like a designer enriching their visual library:

```
Automated crawl pipeline:
  → Pinterest boards (branding, typography, identity design)
  → Behance (top brand identity projects)
  → Design agency portfolios (Pentagram, Collins, DesignStudio, etc.)
  → Industry-specific references per product category

→ Extracted visuals tagged by: style, industry, color system, mood
→ Stored in visual knowledge base
→ Used to inform Option 1 (market-aligned) and Option 4 (Wild Card)
```

---

## 4 Brand Identity Options

### Option 1 — Market-Aligned
Agent researches competitors and design trends for this product category → synthesizes a direction that fits market expectations, executed well.

### Option 2 — Designer-Led
Built entirely from the designer's structured moodboard. Agent maps references to color, typography, graphic style, and logo form decisions.

### Option 3 — Hybrid
Reasoned balance between market research and designer instinct. Agent proposes which elements follow market norms (trust/recognition) and which differentiate (memorability). Includes written rationale for each decision.

### Option 4 — Wild Card
Fully agent-driven. No moodboard constraint. Agent draws from its visual knowledge base and product understanding to propose a direction no one asked for — but might be exactly right.

---

## Human-in-the-Loop

Brand identity is a deeply subjective, high-stakes decision. The agent supports iterative refinement at every stage — the designer is always in control:

**After Phase 1 (Stylescape review):**
- Designer selects 1 of 4 directions, OR
- Requests a remix: *"Take the color system from Option 1 and the typography from Option 3"*
- Requests a specific adjustment: *"Option 2 but make it feel less corporate, more playful"*
- Agent regenerates based on feedback — as many rounds as needed before moving to Phase 2

**After Phase 2 (Asset review):**
- Designer reviews each asset category (logo, palette, templates)
- Can request targeted refinements: *"Logo icon feels too sharp — soften the geometry"*
- Each feedback loop triggers only the relevant part of the pipeline — no full regeneration needed

**Design philosophy:** AI proposes, designer decides. The agent is a Creative Director's tool, not a replacement.

---

## Output Structure

### Phase 1 — Stylescape Presentation

4 stylescapes — one per direction. Each is a high-resolution visual composition (like the NuRange / Behance examples) assembled in Illustrator using the mockup library:

Each stylescape contains:
- Logo concept + symbol rationale
- Color palette in context
- Typography in use
- Graphic elements / patterns
- Brand applied to 2–3 mockups (X banner, social post, product)
- Direction name + strategic rationale (2–3 sentences)

**Format:** High-res PNG, assembled in Illustrator — ready to share for stakeholder sign-off.

### Phase 2 — Full Asset Build (After Direction Selected)

**Brand Foundation**
- Logo: all sizes and versions (primary, secondary, icon, dark/light)
- Color system: HEX, RGB, CMYK + usage rules
- Typography: font files + hierarchy
- Graphic elements / patterns: vector files (AI + SVG)

**Image → Vector Conversion**
- Gemini generates raster PNG → Illustrator auto-traces → exports AI + SVG
- All assets production-ready for print, web, large format

**Social Media Templates (X / Twitter)**
5 template types × 4 layout options each, vector, copy-swappable via Illustrator Variables:

| Template | Purpose |
|----------|---------|
| Announcement | Launch, major news |
| Collab / Partnership | Co-branding posts |
| Advertising | Promotional, CTAs |
| Feature Introduction | Product features |
| Information-heavy | Data, stats, tables |

**Figma Auto-Upload**
- All assets uploaded via Figma API
- Color styles, text styles, logo components, template frames auto-created
- Team builds immediately from the component system

---

## Technical Stack & Constraints

| Tool | Role | Constraint |
|------|------|------------|
| **Claude** | Orchestration, research, brief generation, prompt engineering | Cannot generate images directly — outputs text prompts and structured decisions |
| **Gemini API (paid)** | Visual generation — raster PNG, no watermark | Outputs raster only — cannot generate vector files directly |
| **Illustrator + JSX** | Raster → vector conversion, stylescape assembly, template system, export | Requires pre-built templates and scripts; JSX complexity = highest technical risk |
| **Figma API** | Auto-upload components, styles, templates | API write access requires Figma editor token; component structure must be predefined |
| **Claude web search + Firecrawl** | Market research, visual knowledge base crawling | X/Twitter may block scraping — manual input fallback available |

**Known constraints:**
- Logo vectorization quality depends on Gemini output resolution — complex logos may need manual cleanup
- Illustrator JSX scripting is the most technically challenging part — Arthur/Lucas review required Day 2
- Figma API upload is Priority 2 — deprioritized if JSX takes longer than expected

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
Phase 1 Output: 4 stylescapes → designer reviews → selects / requests refinement
  │
  ↓ [Direction confirmed]
  │
Gemini generates full asset set
Illustrator: raster → vector, social template system
Figma API: auto-upload complete brand library
  │
  ↓
Phase 2 Output: Complete brand kit + Figma library
New assets → saved to brand library + visual knowledge base
```

---

## MVP Scope (4 Days)

**Priority 1**
- Input handling: brief + moodboard + keywords + mockup library
- All 4 directions generated + 4 stylescapes assembled
- Human-in-the-loop refinement loop (Phase 1)
- Phase 2: full asset build for selected direction
- Image → vector via Illustrator

**Priority 2 — if time allows**
- Social template system (3 of 5 types)
- Figma API auto-upload
- Visual knowledge base crawling pipeline

**Out of scope (roadmap)**
- Landing page generation
- Real-time trend monitoring
- Multi-platform format export

---

## Success Metrics

| Metric | Target |
|--------|--------|
| **Time to Phase 1 output** | 4 stylescapes generated in < 30 minutes from brief input |
| **Direction approval rate** | At least 1 of 4 directions approved by designer without full regeneration |
| **Refinement rounds** | Designer reaches final direction in ≤ 3 feedback iterations |
| **Phase 2 completeness** | Full asset kit exported (logo versions, palette, 3+ templates) within 1 hour of direction selection |
| **Vector quality** | Logo vector output usable without manual cleanup in ≥ 70% of cases |
| **Designer satisfaction** | Output does not look "AI-generated" — passes designer's quality bar |

---

## Why This Agent Matters

- **Cost:** Reduces brand identity creation from $5k–$50k agency cost to near zero
- **Speed:** Weeks → hours, with multiple directions to choose from
- **Non-generic:** Structured input + growing visual knowledge base = intentional output
- **Collaborative:** Human-in-the-loop at every decision point — AI proposes, designer decides
- **Self-improving:** Visual knowledge base grows over time → output quality increases continuously

---

*Spec v1.0 — Day 1 | Ready for Supervisor review*
