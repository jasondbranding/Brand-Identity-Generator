# INSTRUCT_STYLEGUIDE_FORMAT.md
# Hướng dẫn đồng bộ format 12 file styleguide `.md` trong `styles/patterns/`

---

## Mục đích

Code trong `src/pattern_matcher.py` → hàm `_condense_rules()` (line 263-331) dùng **4 regex patterns** để extract thông tin từ phần `### For PATTERNS:` của mỗi styleguide. Nếu format không đúng, regex miss → prompt thiếu context → pattern gen quality giảm.

**File phụ thuộc:**
- `src/pattern_matcher.py` → `extract_pattern_rules()`, `_condense_rules()`
- Gián tiếp: `src/generator.py` → injects extracted rules into pattern prompts

---

## Gold Standard Format

**File tham chiếu:** `pattern_geometric_repeat.md`

```markdown
### For PATTERNS:

1.  **Motif Rules**
    *   **Dominant Motif Types**: [Mô tả motif chính, single paragraph, không nested bullets]
    *   **Geometric Principles**: [...]

2.  **Emotional & Personality Impact**
    *   **Vibe**: [Single paragraph mô tả mood/personality]

3.  **Grid System**
    *   **Tiling Method**: [...]
    *   **Spacing**: [...]
    *   **Density**: [...]

4.  **Style Constraints**
    *   **Rendering**: [Flat vector, clean lines, etc. — single paragraph]
    *   **Color Usage**: [...]
    *   **Complexity**: [...]

5.  **Tiling Technical**
    *   **Edge Alignment**: [...]
    *   **Seamless Requirements**: [...]

6.  **Avoid**
    *   [Avoid item 1 — single line, no sub-bullets]
    *   [Avoid item 2]
    *   [Avoid item 3]
    ...
```

### Format anatomy:

| Element | Required Format | Example |
|---------|----------------|---------|
| Section header | `### For PATTERNS:` (exactly `###`, not `##` or `####`) | `### For PATTERNS:` |
| Numbered sections | `1.  **Section Name**` (2-space indent after dot) | `1.  **Motif Rules**` |
| Field names | `*   **Field Name**: Content` (star indent, bold name, colon inside bold or after) | `*   **Dominant Motif Types**: Exclusively geometric...` |
| Content | Single paragraph per field, no nested bullet lists | NOT: `- Sub-item 1\n- Sub-item 2` |
| Avoid section | Numbered `6.  **Avoid**` + star-bullet list below | `*   Organic, free-form elements...` |

---

## 6 Critical Rules (Code Regex Dependencies)

These rules directly correspond to regex patterns in `src/pattern_matcher.py:_condense_rules()`.

### Rule 1: Header must be `### For PATTERNS:`

```python
# pattern_matcher.py line 180-183
re.search(
    r"#{2,4}\s+For\s+PATTERNS:\s*\n(.*?)(?=\n#{2,4}\s+For\s|\Z)",
    content, re.DOTALL | re.IGNORECASE,
)
```

The regex accepts `##`, `###`, `####` — but `###` is the canonical depth. Using `##` risks capturing sibling sections. Using `####` may nest incorrectly inside the LOGOS section.

> **RULE: Always use exactly `### For PATTERNS:`**

### Rule 2: Field name `Dominant Motif Types` (exact wording)

```python
# pattern_matcher.py line 290-292
r"Dominant\s+Motif\s+Types\s*[:\*]*\s*(.+?)(?=\n\s*\*\s*\*\*|\n\d+\.\s|\Z)"
```

The regex requires exactly `Dominant Motif Types` (case-insensitive). Variations like "Motif Types", "Key Motifs", "Primary Motifs" will **not match**.

> **RULE: Use exactly `**Dominant Motif Types**:` or `**Dominant Motif Types:**`**

### Rule 3: Field name `Rendering` (with optional `Style` suffix)

```python
# pattern_matcher.py line 298-300
r"Rendering(?:\s+Style)?\s*[:\*]*\s*(.+?)(?=\n\s*\*\s*\*\*|\n\d+\.\s|\Z)"
```

Accepts: `Rendering`, `Rendering Style`, `Rendering:`, `**Rendering**:`, `**Rendering Style**:`

Does NOT accept: `Rendering Approach`, `Visual Rendering`, `Render Style`

> **RULE: Use either `**Rendering**:` or `**Rendering Style**:`**

### Rule 4: Field name `Vibe` / `Mood` / `Emotional Feel` / `Personality impact`

```python
# pattern_matcher.py line 307-309
r"(?:Overall\s+)?(?:Vibe|Mood|Emotional\s+Feel|Personality\s+impact)\s*[:\*]*\s*(.+?)(?=\n\s*\*\s*\*\*|\n\d+\.\s|\Z)"
```

Accepts: `Vibe`, `Overall Vibe`, `Mood`, `Emotional Feel`, `Personality impact`

Does NOT accept: `Mood & Vibe` (the `&` breaks the alternation), `Emotional impact`, `Personality`

> **RULE: Use `**Vibe**:` as the canonical field name. If using compound, split into two separate fields: `**Mood**:` and `**Vibe**:`**

### Rule 5: `Avoid` section must be a header + bullet list below (not inline)

```python
# pattern_matcher.py line 316-318
r"Avoid(?:\s*\([^)]*\))?\s*[:\*]*\s*\n(.*?)(?=\n#{2,4}\s|\n\d+\.\s+\*\*|\Z)"
```

The regex captures everything **after the Avoid line** (note `\n` after `[:\*]*`). This means the Avoid content must be on **subsequent lines**, not inline.

**WORKS:**
```markdown
6.  **Avoid**
    *   Organic, free-form elements
    *   Complex gradients
```

**DOES NOT WORK (inline):**
```markdown
- **Avoid:** Gradients, drop shadows, bevels
```

> **RULE: Avoid must be a numbered section header (`6.  **Avoid**`) followed by bullet items on separate lines**

### Rule 6: Content after field name must be on the SAME line (single paragraph)

All field extraction regexes use `(.+?)` which captures text on the same line as the field name, stopping at the next bold field (`\n\s*\*\s*\*\*`) or next numbered section (`\n\d+\.\s`).

**WORKS:**
```markdown
*   **Vibe**: Energetic, bold, modern. Conveys precision and sophisticated rhythm.
```

**DOES NOT WORK (content on next line):**
```markdown
*   **Vibe**:
    Energetic, bold, modern. Conveys precision and sophisticated rhythm.
```

> **RULE: Field content must start on the same line as the field name, not on the next line**

---

## Per-File Issues Table

| # | File | Section Header | Dominant Motif | Rendering | Vibe/Mood | Avoid Format | Bullet Style | Priority |
|---|------|---------------|----------------|-----------|-----------|-------------|-------------|----------|
| 1 | `pattern_geometric_repeat.md` | ✅ `###` | ✅ | ✅ | ✅ `Vibe` | ✅ numbered + bullets | `*` indent | ✅ GOLD |
| 2 | `pattern_3d_abstract.md` | ✅ `###` | ✅ | ✅ | ✅ | ✅ | mixed | LOW |
| 3 | `pattern_abstract_gradient_mesh.md` | ✅ `###` | ✅ | ✅ | ✅ | ✅ | mixed | LOW |
| 4 | `pattern_cultural_heritage.md` | ✅ `###` | ✅ | ✅ `Rendering` | ✅ | ✅ `**6. Avoid**` | `*` indent | LOW |
| 5 | `pattern_icon_based_repeating.md` | ❌ `##` | ✅ | ✅ `Rendering` | ⚠️ check | ❌ `### 6. Avoid (Patterns)` | `-` dash | **HIGH** |
| 6 | `pattern_line_art_monoline.md` | ❌ `##` | ✅ | ✅ | ✅ `Vibe` | ✅ `### 6. Avoid` | `-` dash | **HIGH** |
| 7 | `pattern_memphis_playful.md` | ✅ `###` | ✅ | ✅ | ⚠️ check | ❌ inline `- **Avoid:**` per-line | `-` dash + `####` | **HIGH** |
| 8 | `pattern_minimal_geometric.md` | ✅ `###` | ✅ | ✅ | ❌ `Mood & Vibe` | ❌ inline `**Avoid:**` in bullets | `*` indent | **HIGH** |
| 9 | `pattern_organic_fluid.md` | ✅ `###` | ✅ | ✅ | ⚠️ check | ✅ `#### 6. Avoid (Patterns)` | `-` dash + `####` | **MEDIUM** |
| 10 | `pattern_organic_natural.md` | ❌ `##` | ✅ | ✅ | ✅ `Vibe` | ✅ `### 6. Avoid (PATTERNS)` | `*` indent | **HIGH** |
| 11 | `pattern_tech_grid_and_line.md` | ✅ `###` | ⚠️ check | ✅ | ✅ `Vibe it creates` | ✅ `6.  **Avoid**` | `*` indent | **MEDIUM** |
| 12 | `pattern_textile_inspired.md` | ✅ `###` | ⚠️ check | ✅ | ⚠️ `Emotional impact` + `Personality impact` | ✅ `6.  **Avoid**` | `*` indent | **MEDIUM** |

### Issue Details

#### HIGH Priority (regex will miss data)

**`pattern_icon_based_repeating.md`**
- `## For PATTERNS:` → change to `### For PATTERNS:`
- Verify Vibe field name matches regex
- `### 6. Avoid (Patterns)` → regex handles `(...)` OK, but header depth `###` inside `##` parent is inconsistent

**`pattern_line_art_monoline.md`**
- `## For PATTERNS:` → change to `### For PATTERNS:`
- Line uses `-` dash bullets → works with regex but inconsistent with gold standard

**`pattern_memphis_playful.md`**
- Uses `#### sub-headers` (11 of them) → regex handles depth 2-4 but adds noise
- Avoid section uses **inline format**: `- **Avoid:** Gradients, drop shadows...` per bullet → regex expects a single Avoid header + list below. **This will miss all avoid items.**
- Fix: restructure to single `6.  **Avoid**` header + bullet list

**`pattern_minimal_geometric.md`**
- `**Mood & Vibe:**` → regex cannot match `&` — use `**Vibe**:` instead
- Inline `**Avoid:**` inside regular bullet points (e.g., `*   **Avoid:** Chaotic, busy...`) → regex expects numbered Avoid section. **Misses avoid list.**
- Fix: collect all inline Avoid items → move to single `6.  **Avoid**` section

**`pattern_organic_natural.md`**
- `## For PATTERNS:` at line 41 → change to `### For PATTERNS:`

#### MEDIUM Priority (partial data extraction)

**`pattern_organic_fluid.md`**
- Uses `####` for all section headers within PATTERNS → regex handles but depth inconsistent
- `#### 6. Avoid (Patterns)` → regex handles but should be `6.  **Avoid**` for consistency

**`pattern_tech_grid_and_line.md`**
- `**Vibe it creates:**` → regex matches `Vibe` substring, but field name should be just `**Vibe**:` for consistency
- Verify `Dominant Motif Types` field exists (may use different name)

**`pattern_textile_inspired.md`**
- `**Emotional impact**:` and `**Personality impact**:` → regex matches `Personality impact` but misses `Emotional impact` (regex expects `Emotional Feel`). Change to `**Vibe**:` for consistency

---

## Validation Checklist

Run after fixing each file:

### 1. Header Check
```bash
grep -n "For PATTERNS" styles/patterns/*.md
```
**Expected:** All 12 files show `### For PATTERNS:` (exactly `###`)

### 2. Field Name Check
```bash
for f in styles/patterns/*.md; do
  echo "=== $(basename $f) ==="
  grep -c "Dominant Motif Types" "$f" | tr -d '\n'; echo -n " DMT | "
  grep -c "Rendering" "$f" | tr -d '\n'; echo -n " Render | "
  grep -E -c "\*\*Vibe\*\*" "$f" | tr -d '\n'; echo -n " Vibe | "
  grep -c "Avoid" "$f"
done
```
**Expected:** Every file has ≥1 match for each field in the PATTERNS section

### 3. Avoid Section Structure Check
```bash
# Should show numbered Avoid header, not inline
grep -n "Avoid" styles/patterns/*.md | grep -v "should\|must\|forms\|elements\|motifs"
```
**Expected:** Each file has one `6.  **Avoid**` (or `**6. Avoid**`) header line, followed by bullet items

### 4. Regex Extraction Test
```python
# Run from project root:
from src.pattern_matcher import match_styleguide, extract_pattern_rules, _condense_rules
from pathlib import Path

STYLES_DIR = Path("styles/patterns")
for md in sorted(STYLES_DIR.glob("*.md")):
    rules = extract_pattern_rules(md)
    if not rules:
        print(f"❌ {md.name}: No PATTERNS section found")
        continue
    condensed = _condense_rules(rules)
    parts = condensed.split("  ")
    has_motif = any("Motifs:" in p for p in parts)
    has_style = any("Style:" in p for p in parts)
    has_mood  = any("Mood:" in p for p in parts)
    has_avoid = any("Avoid:" in p for p in parts)
    status = "✅" if all([has_motif, has_style, has_mood, has_avoid]) else "⚠️"
    missing = []
    if not has_motif: missing.append("Motifs")
    if not has_style: missing.append("Style")
    if not has_mood:  missing.append("Mood")
    if not has_avoid: missing.append("Avoid")
    print(f"{status} {md.name}: {condensed[:80]}...")
    if missing:
        print(f"   MISSING: {', '.join(missing)}")
```

### 5. Content Flatness Check
```bash
# Nested bullets under field names = BAD (regex won't capture sub-items)
grep -A2 "Dominant Motif Types" styles/patterns/*.md | grep "^.*-   \|^.*\*   " | grep -v "Dominant"
```
**Expected:** No output (no nested bullets directly after Dominant Motif Types line)

---

## Content Guidelines

### Flatten Nested Bullets → Single-Line Sentences

**❌ BAD — nested bullets (regex captures only first line):**
```markdown
*   **Dominant Motif Types:**
    -   Flowing organic lines
    -   Fluid abstract waves
    -   Layered curvilinear forms
    -   Stylized abstract animal spots
```

**✅ GOOD — single paragraph (regex captures everything):**
```markdown
*   **Dominant Motif Types**: Flowing organic lines, fluid abstract waves, layered curvilinear forms, stylized abstract animal spots, and interconnected organic capsules. All motifs must be inherently biomorphic and suggest natural, unconstrained movement.
```

### Keep Field Content Under 300 Characters

The `_extract_field()` function trims to `max_len=200` (or 100 for Rendering/Vibe). Write concise descriptions. If you need more detail, add it in the parent section description (e.g., under `1.  **Motif Rules**`) rather than in the field value.

### Avoid Section: One Concept Per Bullet

**❌ BAD — compound bullet:**
```markdown
*   Gradients, drop shadows, bevels, embossing, or other simulated 3D effects, along with any textures or photographic elements
```

**✅ GOOD — split:**
```markdown
*   Gradients, drop shadows, bevels, or 3D effects
*   Photographic textures or photorealistic rendering
```

### Bullet Style: Use `*` With 4-Space Indent

Gold standard uses `*   ` (star + 3 spaces). Some files use `-   ` (dash + 3 spaces). The regex doesn't care (`lstrip("*- ·•")`), but consistency helps maintainability.

> **Use `*   ` for all bullets in styles/patterns/ files**

---

## Fix Priority Order

1. **pattern_minimal_geometric.md** — HIGH — `Mood & Vibe` field name breaks regex + inline Avoid
2. **pattern_memphis_playful.md** — HIGH — inline Avoid format breaks extraction entirely
3. **pattern_icon_based_repeating.md** — HIGH — `## For PATTERNS:` wrong header depth
4. **pattern_organic_natural.md** — HIGH — `## For PATTERNS:` wrong header depth
5. **pattern_line_art_monoline.md** — HIGH — `## For PATTERNS:` wrong header depth
6. **pattern_textile_inspired.md** — MEDIUM — `Emotional impact` not in regex vocabulary
7. **pattern_organic_fluid.md** — MEDIUM — `####` headers, check Vibe field name
8. **pattern_tech_grid_and_line.md** — MEDIUM — `Vibe it creates` → standardize to `Vibe`
9. Remaining (3d_abstract, abstract_gradient_mesh, cultural_heritage) — LOW — minor consistency
