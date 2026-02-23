# Brand Identity Generator

## Become Creative Director — Cook Series | Đào Hải Sơn

> "From a logo (or project spec) + moodboard + brand personality keywords — the agent generates a complete, non-generic brand identity kit: visual system, social templates, and a Figma component library. Human creative direction in, production-ready assets out."

---

## Problem

Building a full brand identity from scratch is slow, expensive, and most AI-generated brand assets look generic. The missing ingredient isn't the logo or the brief — it's human creative context: the feeling, the personality, the visual references that make a brand distinctly itself.

This agent solves that by requiring the designer to input rich creative context upfront — moodboard + detailed brand personality keywords — so the AI generates assets that feel intentional, not templated.

**Key insight:** Professional brand designers differ from AI not in execution speed, but in the ability to deeply understand a brand's feeling and translate it into a consistent visual language. This agent encodes that context into every generation step.

---

## Input

The agent accepts one of two starting points and auto-detects which:

| Input Type | What to Provide |
|---|---|
| Logo file | Upload logo (AI + PNG) — agent extracts colors, style, form language |
| spec.md | Project spec with brand name, product description, target audience, tone |

**Required for both:**

### 1. Moodboard (10–15+ images)

- Visual references that capture the desired feeling of the brand
- Can be from any source: Dribbble, Pinterest, competitor brands, art, photography
- The more specific and curated, the better the output

### 2. Brand Personality Keywords + Explanations

Not generic adjectives ("modern", "clean", "professional")

Specific sensory and emotional descriptions — how should the brand feel?

**Examples:**

❌ "Bold and innovative"

✅ "The feeling of opening a new hardware device — precise, weighty, satisfying. Like a Bloomberg terminal but designed by someone who loves cinema."

✅ "Controlled aggression — a boxer before a fight, not during. Tension without chaos."

Minimum 5 keywords, each with a 2–3 sentence explanation

---

## What the Agent Generates

### Phase 1 — Visual Identity System

- **Color palette:** Primary, secondary, neutral + usage rules. 4 options with different mood directions
- **Typography:** Font pairing recommendations (headline + body) matching brand personality
- **Brand patterns / graphic elements:** Textures, shapes, motifs that extend the visual language beyond the logo — delivered as vector files (Illustrator)
- **Logo refinement (if input is spec.md):** Agent proposes logo concepts based on moodboard + keywords. If input is existing logo: agent extracts and documents the visual DNA

### Phase 2 — Social Media Template System (X / Twitter)

5 core post templates, each with 4 layout options:

| Template | Purpose |
|---|---|
| Announcement | New feature, product launch, major news |
| Collab / Partnership | Co-branding posts with partner brands |
| Advertising | Promotional posts, offers, CTAs |
| Feature Introduction | Explain a product feature or concept |
| Information-heavy | Data, stats, comparison tables (e.g. Moonsheet style) |

All templates: vector-based in Illustrator, copy-swappable via Variables or JSX script

### Phase 3 — Figma Component Library (auto-upload)

- All brand elements converted to Figma components
- Color styles, text styles, logo components, template frames
- Team can immediately use components to build new assets without starting from scratch
- Agent auto-uploads to Figma via Figma API

### Phase 4 — Landing Page Design Proposal (bonus if time allows)

- Agent proposes a landing page layout concept consistent with the brand identity
- Delivered as: Figma frame or HTML mockup
- Shows how the brand system extends from social → web

---

## How the 4 Options Differ

For every output, the agent generates 4 meaningfully different directions:

| Option | What's Different |
|---|---|
| Option 1 | Closest to moodboard references — safe, on-brief |
| Option 2 | Color mood shifted — same structure, different emotional temperature |
| Option 3 | Layout/composition approach — different visual hierarchy |
| Option 4 | Unexpected direction — agent takes creative risk, pushes brand personality further |

Designer reviews and selects direction. Selected direction becomes the master for all subsequent outputs.

---

## Workflow

```
Input (logo OR spec.md) + Moodboard + Brand Keywords
→ Claude analyzes: extracts visual DNA from moodboard, maps keywords to design decisions
→ Claude generates design brief: color direction, typography rationale, style language
→ Gemini generates visual assets per direction (4 options each phase)
→ Illustrator: assembles final vector files — patterns, templates, export
→ Figma API: auto-uploads components, color styles, text styles
→ Designer reviews → selects direction → agent refines remaining outputs
→ New assets → saved to brand library
```

---

## Tool Stack

| Tool | Role |
|---|---|
| Claude | Moodboard analysis, keyword interpretation, design brief generation, prompt engineering, workflow orchestration |
| Gemini API (paid) | Visual asset generation — no watermark |
| Illustrator + JSX | Vector assembly, template system, brand patterns, batch export |
| Figma API | Auto-upload components, styles, templates to Figma |
| Claude web search | Research brand space, competitor visual landscape, trend context |

---

## MVP Scope (4 Days)

**Priority 1 — Core identity + social templates**

- Input handling: logo file OR spec.md + moodboard + keywords
- Claude moodboard analysis + design brief generation
- Color palette generation (4 directions)
- Typography recommendations
- X post templates: 3 of 5 types (Announcement, Collab, Feature)
- Illustrator vector export

**Priority 2 — if time allows**

- Remaining 2 templates (Advertising, Information-heavy)
- Brand pattern / graphic element system
- Figma auto-upload via API

**Out of scope (roadmap):**

- Landing page proposal
- Full Figma component library automation
- Real-time trend monitoring

---

## Why This Agent Matters

- **Non-generic output:** Moodboard + detailed personality keywords force the AI to generate brand-specific assets, not templates
- **Speed:** Full brand kit in hours, not weeks
- **Figma-ready:** Team can immediately build with the system — no manual handoff
- **Scalable:** Same pipeline works for any new project — input changes, system stays

---

## Roadmap

**Phase 2 — Real-Time Trend Monitor**
Monitor top crypto/design accounts on X → detect visual trends as they emerge → alert team and generate trend-aligned assets before the moment passes.

**Phase 3 — Further Expansion**

- Full landing page generation from brand kit
- Brand kit → UI design system automation
- Multi-platform export (LinkedIn, Instagram, TikTok formats)

---

*Spec v1.0 (New Direction) — Day 1 | Ready for Supervisor review*
