# Brand Identity Generator
> Become Creative Director — Cook Series | Đào Hải Sơn

---

> **"From a logo or project brief + moodboard + brand keywords — the agent generates 4 distinct brand identity directions as stylescapes in under 30 minutes. Designer selects, remixes, and refines. Full asset kit exported on direction confirmed."**

---

## Problem Statement

When a company needs a brand identity, there are two options — both are painful:

| | In-house | Agency |
|--|----------|--------|
| **Time** | Minimum 1 week | Minimum 1 month |
| **Cost** | Staff time + tools | $5,000–$50,000+ |
| **Problem** | Slow iteration, hard to test quickly | Expensive, slow feedback loops, limited revisions |

For early-stage products and internal teams, this is a critical bottleneck. Teams can't move fast, can't test multiple brand directions, and can't afford to get it wrong.

Existing AI tools don't solve this — they generate visuals but produce generic, templated output because they lack creative context: curated references, personality depth, and design knowledge.

**This agent reduces brand identity creation from weeks to hours, at near-zero cost — so teams can test directions, validate fast, and iterate.**

---

## Input

### Full Mode (best output quality)
```
/brief              ← logo file OR spec.md (brand name, product, audience, tone)
/moodboard
  /logo-style       ← logo form, shape language
  /graphic-style    ← illustration, graphic elements
  /typography       ← typeface references
  /color-mood       ← color palette, emotional tone
/keywords           ← 5+ brand personality descriptions (specific, not generic)
/mockups            ← labeled product mockups for stylescape assembly
/symbol-direction   ← logo icon brief, or leave open for agent to propose
```

### Quick Mode (for fast demo / testing)
- Input: logo file OR brand name + **product spec** (how the product works, what it does, who it's for) + 3–5 keywords
- No moodboard required — agent uses product spec + keywords to self-determine creative direction
- Outputs **2 directions only** — agent analyzes context and proposes the 2 most suitable options
- Faster, lower input friction — BGK can test live with a new brief using this mode
- Output quality lower than Full Mode but pipeline fully functional

**Pre-built demo inputs:** 2–3 complete input sets prepared before Day 4 presentation to ensure smooth live demo.

---

## 4 Brand Identity Options

### Option 1 — Market-Aligned
Agent researches competitors and current design trends for this product category → synthesizes a direction that fits market expectations, executed well.

### Option 2 — Designer-Led
Built entirely from the designer's moodboard. Agent maps structured references to color, typography, graphic style, and logo form.

### Option 3 — Hybrid
Reasoned balance between market research and designer instinct. Agent proposes what to follow (recognition/trust) and what to differentiate (personality/memorability). Written rationale included.

### Option 4 — Wild Card
Fully agent-driven. No moodboard constraint. Agent draws from its own understanding of the product to propose an unexpected direction that might be exactly right.

---

## Human-in-the-Loop

Brand identity is subjective and high-stakes. The agent supports refinement at every step:

**After Phase 1 (Stylescape review):**
- Select 1 of 4 directions, OR
- Request remix: *"Take color from Option 1, typography from Option 3"*
- Request adjustment: *"Option 2 but less corporate, more playful"*
- Agent regenerates based on feedback — as many rounds as needed

**After Phase 2 (Asset review):**
- Targeted refinements per asset: *"Logo icon too sharp — soften the geometry"*
- Only the relevant part of pipeline re-runs — no full regeneration

*AI proposes. Designer decides.*

---

## Output

### Phase 1 — 4 Stylescapes ← Primary Demo Focus

Each direction presented as a **stylescape** — a high-resolution visual composition showing the full brand feeling at a glance (reference: NuRange, Behance brand identity projects):

Each stylescape contains:
- Logo concept + symbol rationale
- Color palette in context
- Typography in use
- Graphic elements / patterns
- Brand applied to 2–3 mockups (X banner, social post, product mockup)
- Direction name + strategic rationale (2–3 sentences)

**Format:** High-res PNG assembled in Illustrator (or AI-generated composition if JSX proves too complex) — ready for stakeholder sign-off.

---

### Phase 2 — Asset Kit (After Direction Confirmed)

*Build what's achievable in remaining time after Phase 1 is solid.*

**Core assets (Priority 1):**
- Logo: primary, icon, dark/light variants
- Color system: HEX, RGB values + usage rules
- Typography: font pairing + hierarchy

**Image → Vector:**
- Gemini generates raster PNG → Illustrator auto-trace → AI + SVG export
- Realistic expectation: ~70% usable without cleanup, ~30% may need manual refinement
- Both cases shown in demo — honest about limitations

**Social templates (Priority 2, if time allows):**
- 3 of 5 template types × 4 layout options
- Vector, copy-swappable via Illustrator Variables

**Figma:**
- Manual upload for MVP — export files, upload to Figma by hand
- Auto-upload via Figma API → Roadmap

---

## Technical Stack & Constraints

| Tool | Role | Constraint |
|------|------|------------|
| **Claude** | Orchestration, market research, brief analysis, prompt engineering | Cannot generate images — outputs decisions and prompts |
| **Gemini API (paid)** | Visual generation, no watermark | Raster output only — no native vector |
| **Illustrator + JSX** | Stylescape assembly, raster→vector, template system | JSX = highest technical risk — Arthur/Lucas review Day 2 |
| **Claude web search** | Market research for Option 1 | May be limited by paywalled sources |
| **Figma** | Manual upload MVP | API automation in roadmap only |

**Fallback if Illustrator JSX is too complex:**
Assemble stylescapes via Figma or AI-generated composition directly — stylescape quality maintained, just different tool.

---

## 4-Day Plan

| Day | Focus | Goal |
|-----|-------|------|
| **Day 1** | Spec ✓ | This document — approved by Supervisor |
| **Day 2** | Build core pipeline | Brief → Claude analysis → Gemini gen → 4 visual directions output as images |
| **Day 3** | Stylescape assembly + refinement loop | 4 stylescapes assembled, remix/refine working. Phase 2 basic assets if time allows |
| **Day 4** | Present | Phase 1 demo smooth, Phase 2 bonus |

---

## MVP Scope

**Must have (Days 2–3):**
- Full Mode + Quick Mode input handling
- 4 directions generated via Claude + Gemini
- 4 stylescapes assembled and export-ready
- Human-in-the-loop refinement (remix + adjust)
- Pre-built demo inputs ready

**Nice to have (Day 3 if ahead of schedule):**
- Logo versions + color system + typography export
- 3 social templates in Illustrator

**Roadmap (post-MVP):**
- Visual knowledge base: crawl Pinterest, Behance, agency portfolios — tag, store, and use to enrich generation quality (like a designer building their visual library over time)
- Figma API auto-upload + component library
- Landing page generation from brand kit
- Real-time trend monitoring

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Time to 4 stylescapes | < 30 minutes from brief input |
| Direction approval | ≥ 1 of 4 approved without full regeneration |
| Refinement rounds | Final direction reached in ≤ 3 iterations |
| Vector quality | ~70% usable without manual cleanup |
| Quick Mode | BGK can input new brief live and get output |
| Designer bar | Output does not look "AI-generated" |

---

*Spec v2.0 — Day 1 | Revised per Supervisor feedback | Ready for approval*
