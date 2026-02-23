# On-Brand Asset Generator

## Become Creative Director — Cook Series | Đào Hải Sơn

> "Turn a 1–3 hour manual banner workflow into 15 minutes — the agent researches the partner brand, generates assets, composites the mascot, and exports the file. The designer just reviews and approves."
>
> ---
>
> ## Problem
>
> As an in-house graphic designer at a blockchain tech company, the majority of daily work consists of 3 repetitive task types:
>
> | Task | Description | Time Cost |
> |------|-------------|-----------|
> | Collab Banner | Research partner brand → source assets → composite mascot into scene | 1.5–3 hrs |
> | Template Swap | Replace logo, colors, background with partner brand inside existing template | 30–60 min |
> | Data Banner | Update data fields (price, FDV, token...) into fixed layout (e.g. Moonsheet) | 30–45 min |
>
> All three are mechanical, pattern-based, and ready to be automated.
>
> ---
>
> ## What the Agent Does
>
> **Input:** A brief (text or .md file) containing: Task Type + Partner (X handle) + Copy + Data (if needed) + Notes
>
> **Output:** A folder with at least 4 visual options, logo and text already placed, ready for review
>
> ---
>
> ## Workflow
>
> ### Branch A & B — Collab Banner / Template Swap
>
> ```
> Brief → Claude parses brief + researches partner brand (scrapes X)
>       → Claude decides: how should the mascot be composited?
>                         which pose/expression fits the scene?
>       → Check mascot library
>             ├─ Suitable pose found → Gemini composites that asset into background scene
>             └─ No match → Gemini generates new mascot + background in one pass
>       → Photoshop: remove Gemini watermark
>       → Illustrator: place logo, text, copy (all vector) → export PNG
>       → New asset → saved to library (used to train AI Agent in the future)
> ```
>
> > **Note:** If the partner brand has limited public assets → Claude analyzes available brand signals (logo, colors, style) → Gemini generates a new background in the same visual style and color system as the partner.
> >
> > ### Branch C — Data Banner (Illustrator Variables)
> >
> > ```
> > Brief + Data sheet → Claude converts data → Illustrator variable dataset (.xml)
> >                    → Illustrator Variables auto-swaps: text, coin logos, background
> >                    → JSX script batch exports all variants
> > ```
> >
> > ---
> >
> > ## Tool Stack
> >
> > | Tool | Role |
> > |------|------|
> > | Claude | Agent brain: brief analysis, brand research, creative decision-making, prompt engineering, workflow orchestration |
> > | Gemini (Imagen) | Generate background scenes + mascot (composite from library or generate new) |
> > | Photoshop | Only used to remove Gemini watermark |
> > | Illustrator | Everything else: logo, text, layout, Variables automation, vector export |
> > | Scraper | Scrape partner X profile, extract video keyframes for brand reference |
> >
> > ---
> >
> > ## MVP Scope (4 Days)
> >
> > **In scope:**
> >
> > - Brief parsing + task routing
> > - - Partner brand research (scrape X)
> >   - - Mascot library check + creative decision (Claude)
> >     - - Image generation: background + mascot (Gemini)
> >       - - Watermark removal (Photoshop JSX script)
> >         - - Asset assembly + export (Illustrator JSX)
> >           - - Illustrator Variables automation for data banner (Moonsheet template)
> >             - - Auto-save new assets to library
> >              
> >               - **Out of scope (roadmap):**
> >              
> >               - - Web UI for marketing team to self-serve briefs
> >                 - - Video/motion assets (Runway)
> >                   - - Google Sheet live sync
> >                    
> >                     - ---
> >
> > ## Why This Agent Matters
> >
> > - **Speed:** 1–3 hours → 15 minutes per banner
> > - - **Quality:** All exports are vector-based via Illustrator — maximum sharpness
> >   - - **Self-improving:** New assets → saved to library → agent gets smarter over time
> >     - - **Scalable:** More partnerships → more output, no additional headcount needed
> >      
> >       - ---
> >
> > *Spec v5.0 — Day 1 | Ready for Supervisor review*
