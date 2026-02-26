# Pipeline Refactor: 3-Phase HITL Flow

## Context

Project: `brand-identity-generator` — Telegram bot that generates brand identities using Gemini.

**Problem**: Current pipeline generates everything in one shot (4 logos + pattern + palette + mockup + stylescape per direction = ~10 min). This is wrong for demo day.

**New flow**:
```
Brief → REF_CHOICE → Phase 1: 4 logos only
                         ↓
                   User picks 1 OR refines with text (HITL loop)
                         ↓ (logo confirmed)
                   Phase 2: pattern + color palette for chosen direction
                         ↓ (palette confirmed)
                   Phase 3: mockups → stylescape
```

---

## What needs to change

### 1. `src/generator.py` — Add `logo_only` mode

Add `logo_only: bool = False` parameter to:
- `generate_all_assets()`
- `_generate_direction_assets()`

When `logo_only=True`:
- Generate **only** `logo.png` per direction
- Skip `background.png`, `pattern.png`, palette fetch, shade scales
- Return `DirectionAssets` with `background=None`, `pattern=None`, `enriched_colors=None`

Also add a new function:

```python
def generate_single_direction_assets(
    direction: BrandDirection,
    output_dir: Path,
    brief_keywords: list = None,
    brand_name: str = "",
    brief_text: str = "",
    moodboard_images: list = None,
    style_ref_images: list = None,
) -> DirectionAssets:
    """Generate full assets (bg + logo + pattern + palette + shades) for ONE direction only."""
    # Calls _generate_direction_assets() with all params
```

### 2. `bot/pipeline_runner.py` — Split into 2 phase methods

Add to `PipelineRunner` class:

#### `run_logos_phase(brief_dir, on_progress) -> LogosPhaseResult`

Runs Steps 1–5 (logos only):
1. Parse brief
2. Market context
3. Research
4. Concept ideation (generate_concept_cores)
5. Director (generate_directions)
6. Logo-only image generation (generate_all_assets with logo_only=True)

Returns new dataclass:
```python
@dataclass
class LogosPhaseResult:
    success: bool
    output_dir: Path
    directions_output: BrandDirectionsOutput   # all 4 directions
    all_assets: Dict[int, DirectionAssets]      # option_num → assets (logos only)
    directions_json: Path
    error: str = ""
    elapsed_seconds: float = 0.0
```

#### `run_assets_phase(direction, output_dir, brief, on_progress) -> AssetsPhaseResult`

Runs full asset generation for ONE chosen direction:
1. `generate_single_direction_assets()` — bg + pattern + palette + shades
2. `composite_all_mockups()` — mockups for this direction
3. `generate_social_posts()` — social posts
4. `build_all_stylescapes()` — stylescape
5. Collect and return all paths

```python
@dataclass
class AssetsPhaseResult:
    success: bool
    output_dir: Path
    assets: DirectionAssets
    stylescape_path: Optional[Path]
    palette_png: Optional[Path]
    image_files: List[Path]
    error: str = ""
    elapsed_seconds: float = 0.0
```

Keep the existing `run()` method as-is (don't break existing functionality).

### 3. `bot/telegram_bot.py` — Add LOGO_REVIEW state + HITL handlers

#### New state

```python
LOGO_REVIEW = 15   # already REF_UPLOAD = 14, so range(16)
```

#### New context keys
```python
DIRECTIONS_KEY   = "directions_output"     # stores LogosPhaseResult.directions_output
ALL_ASSETS_KEY   = "all_assets"            # stores dict of DirectionAssets (logos only)
OUTPUT_DIR_KEY   = "pipeline_output_dir"   # stores Path to output dir
```

#### Modify `_run_pipeline_and_respond()`

Replace the current function with a Phase 1 version:

```python
async def _run_pipeline_phase1(context, chat_id, progress_msg_id, brief, brief_dir, api_key):
    """Run Phase 1: concept ideation + director + 4 logos only. Then enter LOGO_REVIEW."""
    ...
    runner = PipelineRunner(api_key=api_key)
    result = await runner.run_logos_phase(brief_dir=brief_dir, on_progress=on_progress)

    if not result.success:
        # send error message

    # Store state for Phase 2
    context.user_data[DIRECTIONS_KEY] = result.directions_output
    context.user_data[ALL_ASSETS_KEY] = result.all_assets
    context.user_data[OUTPUT_DIR_KEY] = str(result.output_dir)

    # Send 4 logo images as media group (one per direction)
    media_group = []
    for opt_num in sorted(result.all_assets.keys()):
        assets = result.all_assets[opt_num]
        direction = next(d for d in result.directions_output.directions if d.option_number == opt_num)
        if assets.logo and assets.logo.exists():
            media_group.append(InputMediaPhoto(
                media=open(assets.logo, "rb"),
                caption=f"*{opt_num}. {direction.direction_name}*\n_{direction.rationale[:80]}..._",
                parse_mode=ParseMode.MARKDOWN_V2,
            ))

    if media_group:
        await context.bot.send_media_group(chat_id=chat_id, media=media_group)

    # Show selection keyboard
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Chọn {i}", callback_data=f"logo_select_{i}") for i in sorted(result.all_assets.keys())],
        [InlineKeyboardButton("✏️ Chỉnh sửa / Mô tả thêm", callback_data="logo_refine")],
    ])
    await context.bot.send_message(
        chat_id=chat_id,
        text="👆 *4 hướng logo — chọn 1 để tiếp tục, hoặc mô tả chỉnh sửa bằng ngôn ngữ tự nhiên\\.*",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )
    # NOTE: can't return a state here (this is called from asyncio.create_task)
    # Bot must accept text/callbacks without being in LOGO_REVIEW state
    # → use context.user_data["awaiting_logo_review"] = True flag
    context.user_data["awaiting_logo_review"] = True
```

#### New handler: `step_logo_review_callback()`

Handles `logo_select_1` through `logo_select_4`:
1. Get `chosen_direction` from `context.user_data[DIRECTIONS_KEY]`
2. Edit message to "✅ Chọn hướng N — đang gen palette + pattern..."
3. Start Phase 2: `asyncio.create_task(_run_pipeline_phase2(...))`

#### New handler: `step_logo_review_text()`

Handles free-text refinement when `context.user_data.get("awaiting_logo_review")`:
- Pass refinement text to `generate_directions(refinement_feedback=text)` → regenerate logos
- Show new 4 logos
- Stay in review mode

#### New function: `_run_pipeline_phase2(context, chat_id, chosen_option_num, ...)`

1. Get `directions_output` and `output_dir` from context
2. Find `chosen_direction = directions_output.directions[chosen_option_num - 1]`
3. Run `runner.run_assets_phase(direction=chosen_direction, ...)`
4. Send results: palette strip + pattern + mockups + stylescape

#### Register new handlers in `build_app()`

Add a global `MessageHandler` for logo review text (outside ConversationHandler, triggered by flag):
```python
app.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND,
    step_logo_review_text,
))
app.add_handler(CallbackQueryHandler(step_logo_review_callback, pattern="^logo_"))
```

Or alternatively, extend the ConversationHandler to include a `LOGO_REVIEW` state — but since the pipeline runs as `asyncio.create_task` (outside conversation flow), using a global handler with a flag in `user_data` is simpler.

---

## Files to change

| File | Change |
|------|--------|
| `src/generator.py` | Add `logo_only` param, add `generate_single_direction_assets()` |
| `bot/pipeline_runner.py` | Add `LogosPhaseResult`, `AssetsPhaseResult`, `run_logos_phase()`, `run_assets_phase()` |
| `bot/telegram_bot.py` | Add `LOGO_REVIEW` state, `_run_pipeline_phase1()`, `_run_pipeline_phase2()`, `step_logo_review_callback()`, `step_logo_review_text()` |

---

## Current pipeline call site in bot (to replace)

In `_launch_pipeline()` (around line 1560):
```python
asyncio.create_task(_run_pipeline_and_respond(
    context=context,
    chat_id=chat_id,
    progress_msg_id=progress_msg.message_id,
    brief=brief,
    brief_dir=brief_dir,
    api_key=api_key,
))
return ConversationHandler.END
```

Replace `_run_pipeline_and_respond` with `_run_pipeline_phase1`.

---

## Key constraints

- `_run_pipeline_phase1` is called via `asyncio.create_task` → it CANNOT return a conversation state
- Logo selection must work via global `CallbackQueryHandler` OR via `context.user_data` flag
- `ConversationBrief` object is stored in `context.user_data["brief"]` — pass `brief_dir` (a temp Path) to runner
- `style_ref_images` is stored as `brief.style_ref_images` (list of Path) — pass through to both phases
- All existing `PipelineRunner.run()` logic must be preserved (don't break CLI usage)

---

## Reference: current state enum (bot/telegram_bot.py line ~72)
```python
(
    BRAND_NAME, PRODUCT, AUDIENCE, TONE, CORE_PROMISE,
    GEOGRAPHY, COMPETITORS, LOGO_INSPIRATION, PATTERN_INSPIRATION,
    KEYWORDS, COLOR_PREFERENCES, MODE_CHOICE, CONFIRM,
    REF_CHOICE, REF_UPLOAD,
) = range(15)
```
Add `LOGO_REVIEW = 15` → `range(16)`.
