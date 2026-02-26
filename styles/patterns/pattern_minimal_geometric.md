name: Minimal Geometric Pattern Style
type: style_guide
version: 1.0
generated_from: patterns/pattern_minimal_geometric_collection_analysis
```

### For LOGOS:
1.  **Form Language**
    *   **Dominant Shapes:** Primarily composed of fundamental geometric primitives: perfect circles, squares, rectangles, triangles, and straight lines. Smooth, consistent arcs and rounded corners are permissible for softened geometry.
    *   **Geometry Rules:** Strict adherence to Euclidean geometry. All angles should be precise, often multiples of 45 or 90 degrees. Curves must be mathematically perfect, derived from circles or ellipses.
    *   **Construction Principles:** Employ modular construction, where elements are built from repeating or related sub-components. Utilize principles of proportional scaling, subtractive geometry (negative space defining forms), and additive geometry. Forms should suggest a foundational grid structure, even if implicit.
    *   **Avoid:** Organic, freehand, or illustrative shapes. Irregular, asymmetrical, or wobbly lines. Complex, multi-faceted polygons beyond simple primitives. Arbitrary curves without clear geometric derivation.

2.  **Style Constraints**
    *   **Rendering Style:** Flat design (2D), purely vector-based, with crisp, sharp edges and no anti-aliasing artifacts. No depth, perspective, or dimension implied through shadows, highlights, or gradients.
    *   **Fill vs Outline:** Logos can be composed of solid filled shapes, uniform outlines, or a combination. When outlines are used, they must have consistent stroke weights. Dashed lines are permissible if they maintain geometric precision and uniformity.
    *   **Complexity Level:** Minimalist and highly abstract. The logo should convey its meaning or aesthetic with the fewest possible elements, focusing on clarity and simplicity.
    *   **Avoid:** Skeuomorphism, photorealism, 3D rendering, drop shadows, inner shadows, bevels, embossing, gradients, textures, or intricate illustrations. Overly detailed or busy compositions.

3.  **Technical Specs**
    *   **Stroke Weights:** Maintain uniform stroke weights for all outline elements within a single logo. Suggested range: 1% to 3% of the logo's smallest bounding box dimension. If dashes are used, dash length should be 2-4 times the dash gap, with both proportional to stroke weight.
    *   **Proportions:** Elements should be proportioned according to simple mathematical ratios (e.g., 1:1, 1:2, 1:sqrt(2)) for visual harmony and precision. Grid-based alignment is paramount.
    *   **Spacing:** Ample, consistent negative space is critical. Clear space between adjacent elements should be a minimum of 1x the stroke weight (if outlines are present) or 1x the smallest linear dimension of the element.
    *   **Scalability:** Logos must be infinitely scalable without loss of detail or integrity, appearing sharp and clear at any size.
    *   **Avoid:** Inconsistent stroke weights. Arbitrary element sizing or spacing. Proportions that lack mathematical basis. Pixelation or blurriness at any scale.

4.  **Composition**
    *   **Centering:** The primary logo mark must be geometrically and optically centered within its designated clear space.
    *   **Padding:** A generous clear space (minimum exclusion zone) should surround the logo. This padding should be at least 1/2 of the logo's smallest overall dimension on all sides.
    *   **Figure-Ground Ratio:** A balanced interplay between positive and negative space. The negative space is an active design element, often defining implied forms as much as the positive shapes. High contrast is expected.
    *   **Avoid:** Off-center or unbalanced compositions. Insufficient clear space, allowing other elements to infringe upon the logo's boundaries. Ambiguous figure-ground relationships where forms are unclear. Cluttered compositions.

5.  **Avoid (LOGOS)**
    *   Organic, fluid, or calligraphic typography and forms.
    *   Illustrative or highly literal representations of objects or concepts.
    *   Complex visual metaphors that require detailed interpretation.
    *   Distorted, stretched, or pixelated graphic elements.
    *   Loud, clashing, or overly saturated color palettes (more than 3 distinct colors).
    *   Any element that introduces visual noise or disrupts the calm, orderly aesthetic.

### For PATTERNS:
1.  **Motif Rules**
    *   **Dominant Motif Types:** Abstract geometric primitives arranged into repeating units. Common motifs include:
        *   **Linear Elements:** Dashed or solid straight lines arranged in grids (e.g., hexagonal, triangular, square).
        *   **Curvilinear Elements:** Smooth arcs, circular segments, or full circles arranged in tessellations or overlapping patterns (e.g., starburst, quatrefoil, ogee).
        *   **Polygonal Elements:** Triangles, squares, or rounded rectangles arranged to create larger, repeating forms (e.g., hourglass, checkerboard).
        *   **Combined Elements:** Minimalist combinations of lines and dots or rounded corners with internal details.
    *   **Geometric Principles:** Strict adherence to precise geometry. All lines are perfectly straight or perfectly curved (from circles/ellipses). Angles are exact, often 45-degree, 60-degree, or 90-degree. Symmetry (translational, rotational, reflectional) is fundamental to motif construction.
    *   **Avoid:** Organic, biomorphic, or free-form motifs. Hand-drawn, imprecise, or asymmetric elements. Complex narrative or illustrative motifs. Abstract expressionist forms.

2.  **Emotional & Personality Impact**
    *   **Vibe**: The pattern should consistently evoke feelings of calm, order, minimalism, sophistication, and cleanliness. It should project a professional, precise, and analytical energy.
    *   **Psychological Brand Energy:** Conveys qualities such as structured thinking, innovative precision (tech), trustworthy clarity (consulting), and clinical elegance (healthcare). It promotes a sense of composed expertise and refined simplicity.
    *   **Avoid:** Chaotic, busy, playful, whimsical, aggressive, overtly decorative, or emotionally charged patterns. Anything that feels uncontrolled or visually unsettling.

3.  **Grid System**
    *   **Tiling Method:** Patterns must be constructed on an explicit or implicit grid system. Common tiling methods include rectilinear (square, rectangular) and hexagonal tessellations. Translational symmetry is mandatory across the entire pattern, often supplemented by rotational or reflectional symmetry within the individual repeating units.
    *   **Spacing:** Consistent, generous negative space is paramount, ensuring breathability and clarity. The space between individual pattern elements and between repeating units must be uniform and mathematically determined (e.g., based on a modular grid unit).
    *   **Density:** Maintain a low to medium density. The pattern should not appear cramped or cluttered. Elements should have sufficient separation to be distinctly recognized. The focus is on precision and visual quietness, not overwhelming detail.
    *   **Avoid:** Random or irregular element placement. Asymmetrical grid systems. Overly dense or sparse patterns that disrupt visual flow. Inconsistent spacing between elements or units.

4.  **Style Constraints**
    *   **Rendering:** Flat, 2D vector graphics with perfectly sharp edges. No implied depth, shadows (drop, inner), bevels, embossing, gradients, textures, or pseudo-3D effects. Rendering should appear as if from a technical drawing or a minimalist graphic design.
    *   **Color Usage:** Restricted to a highly limited palette. Typically monochromatic (one hue, varying tones/tints), duotone (two distinct hues), or tritone (three distinct hues). High contrast between pattern elements and the background is essential. Colors should be muted, desaturated, or neutral. White, off-white, light grey, or very light pastel are preferred for backgrounds.
    *   **Complexity:** The overall pattern can be intricate due to repetition, but individual motifs must remain minimalist and easily discernible. Avoid excessive detail within any single repeating unit.
    *   **Avoid:** Full-color palettes, vibrant or clashing color combinations (more than three distinct colors excluding background). Low contrast color schemes. Photorealistic or illustrative color rendering. Patterns with noisy textures or uneven fills.

5.  **Tiling Technical**
    *   **Edge Alignment:** All pattern elements must align perfectly at the edges of the repeating tile to ensure seamless continuation. There should be no abrupt cut-offs or misalignments when tiles are placed adjacently. Elements that appear to run off one edge must seamlessly re-enter from the opposing edge.
    *   **Seamless Requirements:** The pattern must be perfectly tileable horizontally and vertically, creating an uninterrupted, continuous design across an infinite plane. No visible seams, breaks, or disruptions in the pattern flow are permissible. The design should feel as if it continues endlessly without artificial boundaries.
    *   **Avoid:** Any visible seams, gaps, or discontinuities when tiled. Elements that are improperly truncated at tile edges. Patterns that do not perfectly loop or repeat.

6.  **Avoid (PATTERNS)**
    *   Organic forms, flora, fauna, or human figures.
    *   Patterns that resemble optical illusions or create visual discomfort.
    *   Hand-drawn, painterly, or impressionistic styles.
    *   Vibrant, primary, or overly saturated color palettes.
    *   Asymmetrical or unbalanced compositions that lack a clear, repeating structure.
    *   Gradients, textures, drop shadows, or any 3D rendering.
    *   Patterns that are difficult to discern or appear visually chaotic.
    *   Figurative elements or recognizable objects in the motifs.