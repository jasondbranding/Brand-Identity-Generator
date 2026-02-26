"""
telegram_bot.py — Brand Identity Generator Telegram Bot

Conversational brief collection → pipeline execution → results delivery.

Conversation flow:
  /start or /new
    → BRAND_NAME   → PRODUCT → AUDIENCE
    → TONE         (inline keyboard + custom)
    → CORE_PROMISE (optional)
    → GEOGRAPHY    (optional)
    → COMPETITORS  (optional, structured or freeform)
    → MOODBOARD    (optional, text notes + photo uploads)
    → KEYWORDS     (optional)
    → MODE_CHOICE  (inline keyboard: Quick / Full)
    → CONFIRM      (inline keyboard: Generate / Edit / Cancel)
    → GENERATING   (async pipeline, progress updates)
    → DONE         (send PDF + images)

Commands:
  /start  — start new brand project
  /new    — alias for /start
  /reset  — clear current brief and start over from the beginning
  /cancel — cancel current conversation
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from telegram import (
    Document,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    PhotoSize,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from .brief_builder import ConversationBrief
from .pipeline_runner import PipelineRunner
from .pdf_report import generate_pdf_report

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────

(
    BRAND_NAME,
    PRODUCT,
    AUDIENCE,
    TONE,
    CORE_PROMISE,
    GEOGRAPHY,
    COMPETITORS,
    LOGO_INSPIRATION,
    PATTERN_INSPIRATION,
    KEYWORDS,
    COLOR_PREFERENCES,
    MODE_CHOICE,
    CONFIRM,
    REF_CHOICE,
    REF_UPLOAD,
    LOGO_REVIEW,
) = range(16)

# context.user_data keys for HITL state
DIRECTIONS_KEY   = "directions_output"
ALL_ASSETS_KEY   = "all_assets"
OUTPUT_DIR_KEY   = "pipeline_output_dir"
CHOSEN_DIR_KEY   = "chosen_direction"
ENRICHED_COLORS_KEY = "enriched_colors"
PALETTE_SHADES_KEY  = "palette_shades"
PATTERN_REFS_KEY    = "pattern_ref_images"

# HITL flags — each phase sets its flag to True when awaiting user input
LOGO_REVIEW_FLAG    = "awaiting_logo_review"
PALETTE_REVIEW_FLAG = "awaiting_palette_review"
PATTERN_REF_FLAG    = "awaiting_pattern_ref"
PATTERN_DESC_FLAG   = "awaiting_pattern_desc"
PATTERN_REVIEW_FLAG = "awaiting_pattern_review"

# ── Keyboards ─────────────────────────────────────────────────────────────────

TONE_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("🔥 Confident & Bold", callback_data="tone_confident"),
        InlineKeyboardButton("🤍 Minimal & Clean", callback_data="tone_minimal"),
    ],
    [
        InlineKeyboardButton("🌱 Warm & Human", callback_data="tone_warm"),
        InlineKeyboardButton("⚡ Sharp & Technical", callback_data="tone_technical"),
    ],
    [
        InlineKeyboardButton("🎭 Playful & Creative", callback_data="tone_playful"),
        InlineKeyboardButton("✏️ Tự mô tả...", callback_data="tone_custom"),
    ],
    [InlineKeyboardButton("⏭ Bỏ qua", callback_data="tone_skip")],
])

MODE_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("⚡ Quick — 2 directions, ~3 phút", callback_data="mode_quick")],
    [InlineKeyboardButton("🎨 Full — 4 directions + research, ~8-12 phút", callback_data="mode_full")],
])

CONFIRM_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("✅ Generate ngay!", callback_data="confirm_go")],
    [InlineKeyboardButton("✏️ Chỉnh sửa brief", callback_data="confirm_edit")],
    [InlineKeyboardButton("❌ Huỷ", callback_data="confirm_cancel")],
])


# ── Context keys ──────────────────────────────────────────────────────────────

BRIEF_KEY = "brief"
MSG_ID_KEY = "progress_msg_id"
TEMP_DIR_KEY = "temp_dir"
TONE_CUSTOM_KEY = "awaiting_tone_custom"
RUNNER_KEY = "runner"
HISTORY_KEY = "state_history"


# ── Intent detection ──────────────────────────────────────────────────────────

SKIP_PHRASES = {
    "bỏ qua", "không có", "không biết", "thôi", "skip", "k có", "ko có",
    "không", "pass", "bỏ", "không cần", "k cần", "ko cần", "chưa có",
    "để sau", "nope", "n/a", "na", "no", "không điền", "bỏ trống",
    "để trống", "chưa", "chưa biết", "kh", "tạm bỏ", "bỏ qua đi",
    "không quan trọng", "chưa nghĩ ra",
    # "not yet" / "don't have one" variants (for slogan/tagline question)
    "chưa có sẵn", "không có sẵn", "chưa có gì", "chưa nghĩ", "chưa có slogan",
    "chưa có tagline", "chưa có câu", "không có câu", "không có slogan",
    "chưa", "chưa ạ", "chưa có ạ", "không có ạ", "chưa nghĩ ra ạ",
    # "let AI decide" variants
    "nghĩ hộ", "nghĩ giúp", "bạn nghĩ hộ", "nghĩ hộ được không",
    "nghĩ hộ đi", "để ai nghĩ", "ai tự nghĩ", "để bạn nghĩ",
    "tự nghĩ đi", "ai tự chọn", "để ai chọn", "để bạn chọn",
    "tự chọn đi", "bạn tự chọn", "ai quyết", "để ai quyết",
    "random", "tuỳ", "tùy", "tùy bạn", "tuỳ bạn", "tuỳ ai",
    "tùy ai", "không chắc", "ko chắc", "k chắc", "chưa chắc",
}

BACK_PHRASES = {
    "back", "quay lại", "back lại", "trở lại", "bước trước",
    "quay lại bước trước", "sửa lại", "làm lại", "undo", "lùi lại",
    "đổi lại", "sửa bước trước", "back bước trước", "cho sửa lại",
    "muốn sửa lại", "sửa câu trước",
}

DONE_PHRASES = {
    "xong", "done", "ok", "oke", "okay", "tiếp", "tiếp tục", "next",
    "xong rồi", "đã xong", "hoàn thành", "xong nhé", "xong rồi nhé",
    "kết thúc", "đủ rồi", "tạm đủ", "đủ", "vậy thôi", "thế thôi",
}

# Sentinel value: marks a field as explicitly skipped (so bot doesn't re-ask)
SKIP_SENTINEL = "-"


def detect_intent(text: str) -> Optional[str]:
    """Detect 'skip', 'done', or 'back' from natural language."""
    normalized = text.strip().lower()
    if normalized in BACK_PHRASES or any(p in normalized for p in BACK_PHRASES):
        return "back"
    if normalized in DONE_PHRASES:
        return "done"
    if normalized in SKIP_PHRASES:
        return "skip"
    # Fuzzy skip for short phrases containing skip keywords
    if len(normalized) < 40 and any(p in normalized for p in SKIP_PHRASES):
        return "skip"
    return None


# ── Bulk input parser ─────────────────────────────────────────────────────────

# Maps header patterns (lowercase) → brief field name
_BULK_FIELD_PATTERNS: list[tuple[str, str]] = [
    # product
    (r"s[aả]n ph[aẩ]m(?:\s*/\s*d[iị]ch\s*v[uụ])?", "product"),
    (r"product(?:\s*/\s*service)?", "product"),
    (r"d[iị]ch\s*v[uụ]", "product"),
    # audience
    (r"target\s*audience", "audience"),
    (r"audience", "audience"),
    (r"kh[aá]ch\s*h[aà]ng(?:\s*m[uụ]c\s*ti[eê]u)?", "audience"),
    (r"[đd][oố]i\s*t[uượ][oợ]ng", "audience"),
    # tone
    (r"tone(?:\s*[&/]\s*personality)?", "tone"),
    (r"c[aá]\s*t[ií]nh", "tone"),
    (r"personality", "tone"),
    # core promise / tagline
    (r"core\s*promise", "core_promise"),
    (r"tagline", "core_promise"),
    (r"promise", "core_promise"),
    (r"kh[aẩ]u\s*hi[eệ]u", "core_promise"),
    (r"[đd][iị]nh\s*h[uướ][oớ]ng", "core_promise"),
    # geography
    (r"geography", "geography"),
    (r"market", "geography"),
    (r"[đd][iị]a\s*l[yý]", "geography"),
    (r"th[iị]\s*tr[uướ][oờ]ng", "geography"),
    (r"v[uù]ng", "geography"),
    # competitors (handled separately — sub-sections)
    (r"competitors?", "competitors"),
    (r"[đd][oố]i\s*th[uủ]", "competitors"),
    # moodboard
    (r"moodboard(?:\s*notes?)?", "moodboard_notes"),
    (r"aesthetic", "moodboard_notes"),
    (r"visual\s*references?", "moodboard_notes"),
    (r"visual", "moodboard_notes"),
    # keywords
    (r"keywords?", "keywords"),
    (r"t[uừ]\s*kh[oó][aá]", "keywords"),
    # color preferences
    (r"colou?r(?:\s*preferences?)?", "color_preferences"),
    (r"m[àa]u(?:\s*s[ắa]c)?(?:\s*[uưù]u\s*ti[eê]n)?", "color_preferences"),
    (r"palette", "color_preferences"),
    (r"m[àa]u\s*ch[uủ]\s*[đd][aạ]o", "color_preferences"),
]

# Competitor sub-section patterns
_COMPETITOR_SUBS = [
    (r"direct", "direct"),
    (r"aspirational", "aspirational"),
    (r"avoid", "avoid"),
    (r"tr[uự]c\s*ti[eế]p", "direct"),
    (r"c[aạ]nh\s*tranh\s*tr[uự]c\s*ti[eế]p", "direct"),
    (r"h[uướ][oớ]ng\s*[đd][eế]n", "aspirational"),
    (r"tr[aá]nh", "avoid"),
]


def _parse_bulk_fields(text: str, brief: "ConversationBrief") -> int:
    """
    Detect 'Field: value' patterns in text, fill all matched brief fields.
    Returns number of distinct fields filled (≥2 means bulk input detected).
    """
    import re

    lines = text.splitlines()

    # Build a header regex for quick detection
    header_rx = re.compile(
        r"^(" + "|".join(p for p, _ in _BULK_FIELD_PATTERNS) + r")\s*[:：]\s*(.*)$",
        re.IGNORECASE,
    )

    # First pass: count matching header lines to decide if this is bulk input
    header_line_indices: list[tuple[int, str, str]] = []  # (line_idx, field, value_start)
    for i, line in enumerate(lines):
        m = header_rx.match(line.strip())
        if m:
            matched_header = m.group(1).lower().strip()
            value_start = m.group(2).strip()
            # Resolve which field
            for pattern, field in _BULK_FIELD_PATTERNS:
                if re.fullmatch(pattern, matched_header, re.IGNORECASE):
                    header_line_indices.append((i, field, value_start))
                    break

    # Deduplicate to unique fields in order of appearance
    seen: set[str] = set()
    unique_headers: list[tuple[int, str, str]] = []
    for idx, field, val in header_line_indices:
        if field not in seen:
            seen.add(field)
            unique_headers.append((idx, field, val))

    if len(unique_headers) < 2:
        return 0  # Not bulk input

    # Second pass: extract multi-line values between headers
    def _extract_value(start_line_idx: int, value_start: str, next_line_idx: int) -> str:
        """Collect lines from start to next header."""
        parts = [value_start] if value_start else []
        for li in range(start_line_idx + 1, next_line_idx):
            parts.append(lines[li])
        return "\n".join(parts).strip()

    filled = 0
    for i, (line_idx, field, value_start) in enumerate(unique_headers):
        next_idx = unique_headers[i + 1][0] if i + 1 < len(unique_headers) else len(lines)
        value = _extract_value(line_idx, value_start, next_idx)

        if not value or value.lower() in {"skip", "bỏ qua", "-", "n/a", ""}:
            continue

        if field == "product":
            brief.product = value
            filled += 1
        elif field == "audience":
            brief.audience = value
            filled += 1
        elif field == "tone":
            brief.tone = value
            filled += 1
        elif field == "core_promise":
            brief.core_promise = value
            filled += 1
        elif field == "geography":
            brief.geography = value
            filled += 1
        elif field == "competitors":
            _parse_competitors_block(value, brief)
            filled += 1
        elif field == "moodboard_notes":
            brief.moodboard_notes = value
            filled += 1
        elif field == "keywords":
            kws = re.split(r"[,\n]+", value)
            brief.keywords = [k.strip().lstrip("-• ") for k in kws if k.strip()]
            filled += 1
        elif field == "color_preferences":
            brief.color_preferences = value
            filled += 1

    return filled


def _parse_competitors_block(text: str, brief: "ConversationBrief") -> None:
    """Parse structured competitor block with Direct/Aspirational/Avoid sub-sections."""
    import re

    sub_rx = re.compile(
        r"^(" + "|".join(p for p, _ in _COMPETITOR_SUBS) + r")\s*[:：]\s*(.+)$",
        re.IGNORECASE,
    )
    lines = text.splitlines()
    has_structured = False
    for line in lines:
        m = sub_rx.match(line.strip())
        if m:
            has_structured = True
            sub_key = m.group(1).lower().strip()
            names = [n.strip() for n in m.group(2).split(",") if n.strip()]
            for pattern, label in _COMPETITOR_SUBS:
                if re.fullmatch(pattern, sub_key, re.IGNORECASE):
                    if label == "direct":
                        brief.competitors_direct = names
                    elif label == "aspirational":
                        brief.competitors_aspirational = names
                    elif label == "avoid":
                        brief.competitors_avoid = names
                    break

    if not has_structured:
        # Unstructured: treat whole text as direct
        names = [n.strip() for n in re.split(r"[,;\n]+", text) if n.strip()]
        if names:
            brief.competitors_direct = names


def _is_filled(value) -> bool:
    """True if field has real content (not empty and not the skip sentinel)."""
    if not value:
        return False
    if isinstance(value, list):
        # A list is "filled" if it has at least one non-sentinel item
        real = [v for v in value if v != SKIP_SENTINEL]
        return bool(real) or value == [SKIP_SENTINEL]  # sentinel list counts as filled
    return True  # any non-empty string (including SKIP_SENTINEL) counts as filled


def _next_unfilled_state(brief: "ConversationBrief") -> int:
    """Return the next conversation state that still needs user input."""
    if not brief.product:
        return PRODUCT
    if not brief.audience:
        return AUDIENCE
    if not brief.geography:
        return GEOGRAPHY
    if not (brief.competitors_direct or brief.competitors_aspirational or brief.competitors_avoid):
        return COMPETITORS
    if not brief.keywords:              # ["-"] is truthy → skips correctly
        return KEYWORDS
    if not brief.tone:
        return TONE
    return CONFIRM


def _state_question_text(state: int) -> str:
    """Return the question text for a given state (for use in callback-query follow-ups)."""
    return {
        PRODUCT:      "*Mô tả ngắn về sản phẩm/dịch vụ?*\n_\\(ví dụ: SaaS platform giúp logistics track shipments bằng AI\\)_",
        AUDIENCE:     "*Target audience là ai?*\n_\\(ví dụ: Ops managers tại mid\\-market e\\-commerce\\)_",
        TONE:         "*Tone/cá tính thương hiệu?*\n_Chọn một trong các hướng dưới đây, hoặc tự mô tả\\:_",
        CORE_PROMISE: "*Bạn đã có sẵn slogan hay tagline chưa?*\n_\\(Nếu có thì paste vào — chưa có thì nhắn 'chưa có' là được\\)_",
        GEOGRAPHY:    "*Geography / thị trường mục tiêu?*\n_\\(optional — nhắn 'bỏ qua' nếu chưa có\\)_",
        COMPETITORS:  "*Đối thủ cạnh tranh?*\n_\\(Direct/Aspirational/Avoid — hoặc nhắn 'bỏ qua'\\)_",
        KEYWORDS:     "*3 \\- 5 tính từ miêu tả tính cách thương hiệu?*\n_\\(optional — nhắn 'bỏ qua' nếu chưa có\\)_",
        COLOR_PREFERENCES: "🎨 *Màu sắc ưu tiên?*\n_\\(optional — nhắn 'bỏ qua' để AI tự chọn\\)_",
    }.get(state, "*Chọn chế độ generate:*")


async def _ask_for_state(
    update: Update, context: ContextTypes.DEFAULT_TYPE, state: int
) -> int:
    """Send the appropriate question message for a given state and return that state."""
    await send_typing(update)
    if state == PRODUCT:
        await update.message.reply_text(
            "*Mô tả ngắn về sản phẩm/dịch vụ?*\n"
            "_\\(ví dụ: SaaS platform giúp logistics track shipments bằng AI\\)_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return PRODUCT
    if state == AUDIENCE:
        await update.message.reply_text(
            "*Target audience là ai?*\n"
            "_\\(ví dụ: Ops managers tại mid\\-market e\\-commerce\\)_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return AUDIENCE
    if state == TONE:
        await update.message.reply_text(
            "*Tone/cá tính thương hiệu?*\n"
            "_Chọn một trong các hướng dưới đây, hoặc tự mô tả\\:_",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=TONE_KEYBOARD,
        )
        return TONE
    if state == CORE_PROMISE:
        await update.message.reply_text(
            "*Bạn đã có sẵn slogan hay tagline chưa?*\n"
            "_Nếu có thì paste vào — chưa có thì nhắn_ *chưa có* _là được_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return CORE_PROMISE
    if state == GEOGRAPHY:
        await update.message.reply_text(
            "*Geography / thị trường mục tiêu?*\n"
            "_\\(optional — nhắn_ *bỏ qua* _nếu chưa có\\)_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return GEOGRAPHY
    if state == COMPETITORS:
        await update.message.reply_text(
            "*Đối thủ cạnh tranh?*\n\n"
            "Format gợi ý:\n"
            "`Direct: CompanyA, CompanyB`\n"
            "`Aspirational: BrandX, BrandY`\n"
            "`Avoid: OldCorp`\n\n"
            "_Hoặc chỉ liệt kê tên, hoặc nhắn_ *bỏ qua*",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return COMPETITORS
    if state == KEYWORDS:
        await update.message.reply_text(
            "*3 \\- 5 tính từ miêu tả tính cách thương hiệu?*\n"
            "_\\(optional — mỗi keyword 1 dòng hoặc cách nhau bằng dấu phẩy\\)_\n"
            "_Nhắn_ *bỏ qua* _nếu chưa có_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return KEYWORDS
    if state == COLOR_PREFERENCES:
        await update.message.reply_text(
            "🎨 *Màu sắc ưu tiên?*\n\n"
            "_\\(optional — gợi ý màu bạn muốn dùng cho brand\\)_\n"
            "_Ví dụ: \"Xanh navy \\+ vàng gold\", \"Tone earthy: nâu đất, be, rêu\", \"Tối giản đen trắng\"_\n\n"
            "_Nhắn_ *bỏ qua* _để AI tự chọn palette_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return COLOR_PREFERENCES
    # CONFIRM → show brief summary + confirm keyboard
    return await _send_confirm(update, context, brief)


# ── History management ────────────────────────────────────────────────────────

def push_history(context: ContextTypes.DEFAULT_TYPE, state: int) -> None:
    """Push a state onto the back-navigation stack."""
    history = context.user_data.setdefault(HISTORY_KEY, [])
    # Don't push duplicates consecutively
    if not history or history[-1] != state:
        history.append(state)
    if len(history) > 8:
        history.pop(0)


def pop_history(context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Pop the most recent state from history."""
    history = context.user_data.get(HISTORY_KEY, [])
    return history.pop() if history else None


# Maps each state → (brief_field_to_clear, question_text, optional_keyboard)
# Used by handle_back() to re-ask the right question.
def _get_reask_map() -> dict:
    return {
        BRAND_NAME: (
            "brand_name",
            "*Tên thương hiệu là gì?*",
            None,
        ),
        PRODUCT: (
            "product",
            "*Mô tả ngắn về sản phẩm/dịch vụ?*\n"
            "_\\(ví dụ: SaaS platform giúp logistics track shipments bằng AI\\)_",
            None,
        ),
        AUDIENCE: (
            "audience",
            "*Target audience là ai?*\n"
            "_\\(ví dụ: Ops managers tại mid\\-market e\\-commerce\\)_",
            None,
        ),
        TONE: (
            "tone",
            "*Tone/cá tính thương hiệu?*",
            TONE_KEYBOARD,
        ),
        CORE_PROMISE: (
            "core_promise",
            "*Bạn đã có sẵn slogan hay tagline chưa?*\n_Nếu có thì paste vào — chưa có thì nhắn 'chưa có' là được_",
            None,
        ),
        GEOGRAPHY: (
            "geography",
            "*Geography / thị trường mục tiêu?*\n_Gõ /skip để bỏ qua_",
            None,
        ),
        COMPETITORS: (
            None,
            "*Đối thủ cạnh tranh?*\n_Gõ /skip để bỏ qua_",
            None,
        ),
        KEYWORDS: (
            "keywords",
            "*3 \- 5 tính từ miêu tả tính cách thương hiệu?*\n_\\(mỗi keyword 1 dòng hoặc cách nhau bằng dấu phẩy\\)_\n_Gõ /skip để bỏ qua_",
            None,
        ),
        COLOR_PREFERENCES: (
            "color_preferences",
            "🎨 *Màu sắc ưu tiên?*\n_\\(gõ /skip để AI tự chọn\\)_",
            None,
        ),
    }


async def handle_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 'back' intent — pop history and re-ask previous question."""
    prev_state = pop_history(context)
    if prev_state is None:
        await update.message.reply_text(
            "↩️ Đã ở bước đầu tiên rồi, không thể quay lại thêm\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        # Re-ask brand name as the earliest possible step
        await update.message.reply_text("*Tên thương hiệu là gì?*", parse_mode=ParseMode.MARKDOWN_V2)
        return BRAND_NAME

    reask_map = _get_reask_map()
    info = reask_map.get(prev_state)
    if not info:
        await update.message.reply_text("⚠️ Không thể quay lại bước này\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return prev_state

    field_name, question, keyboard = info

    # Clear that field from brief
    brief = get_brief(context)
    if field_name and hasattr(brief, field_name):
        attr = getattr(brief, field_name)
        setattr(brief, field_name, [] if isinstance(attr, list) else "")

    await send_typing(update)
    kwargs: dict = {"parse_mode": ParseMode.MARKDOWN_V2}
    if keyboard:
        kwargs["reply_markup"] = keyboard

    await update.message.reply_text(f"↩️ Quay lại\\.\n\n{question}", **kwargs)
    return prev_state


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_brief(context: ContextTypes.DEFAULT_TYPE) -> ConversationBrief:
    if BRIEF_KEY not in context.user_data:
        context.user_data[BRIEF_KEY] = ConversationBrief()
    return context.user_data[BRIEF_KEY]


def reset_brief(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[BRIEF_KEY] = ConversationBrief()
    
    # Core brief keys
    for k in [TEMP_DIR_KEY, TONE_CUSTOM_KEY, MSG_ID_KEY]:
        context.user_data.pop(k, None)
        
    # Clear all HITL state flags to prevent state leakage into new sessions
    for k in [
        LOGO_REVIEW_FLAG, "logo_refine_mode", "logo_force_regenerate",
        PALETTE_REVIEW_FLAG, "palette_refine_mode",
        PATTERN_REF_FLAG, PATTERN_DESC_FLAG,
        PATTERN_REVIEW_FLAG, "pattern_refine_mode",
        DIRECTIONS_KEY, ALL_ASSETS_KEY, OUTPUT_DIR_KEY, CHOSEN_DIR_KEY,
        "selected_refs", "ref_uploads", "preview_refs"
    ]:
        context.user_data.pop(k, None)


async def send_typing(update: Update) -> None:
    await update.effective_chat.send_action(ChatAction.TYPING)


async def safe_edit(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_id: int, text: str) -> None:
    """Edit a message, ignoring 'message not modified' errors."""
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception:
        pass


def escape_md(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)


def _extract_direction_number(text: str) -> Optional[int]:
    """
    Detect if user feedback references a specific direction number (1-4).
    Supports: "hướng 1", "hướng một", "direction 2", "số 3",
              digit at start of sentence "1, thêm...", "4 nhưng..."
    Returns int 1-4 or None.
    """
    import re as _re2
    t = text.lower().strip()
    viet_words = {"một": 1, "hai": 2, "ba": 3, "bốn": 4}
    patterns = [
        r'hướng\s*([1-4])\b',
        r'hướng\s*(một|hai|ba|bốn)\b',
        r'direction\s*([1-4])\b',
        r'số\s*([1-4])\b',
        r'^([1-4])[,\.\s]',       # "1, thêm..." at start
    ]
    for pat in patterns:
        m = _re2.search(pat, t)
        if m:
            val = m.group(1)
            if val in viet_words:
                return viet_words[val]
            try:
                n = int(val)
                if 1 <= n <= 4:
                    return n
            except ValueError:
                pass
    return None


# ── Image helpers ─────────────────────────────────────────────────────────────

def _has_any_images(brief: "ConversationBrief") -> bool:
    """Return True if the user has uploaded any inspiration images."""
    return bool(
        brief.moodboard_image_paths
        or brief.logo_inspiration_paths
        or brief.pattern_inspiration_paths
    )


async def _download_image(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prefix: str,
    idx: int,
) -> Optional[Path]:
    """
    Download a photo or document-image from the current message.
    Returns the saved Path, or None if no image found.
    """
    tmp_dir = context.user_data.get(TEMP_DIR_KEY)
    if not tmp_dir:
        tmp_dir = Path(tempfile.mkdtemp(prefix="moodboard_"))
        context.user_data[TEMP_DIR_KEY] = tmp_dir
    else:
        tmp_dir = Path(tmp_dir)

    if update.message.photo:
        photo: PhotoSize = update.message.photo[-1]
        img_path = tmp_dir / f"{prefix}_{idx:02d}.jpg"
        file = await context.bot.get_file(photo.file_id)
        await file.download_to_drive(str(img_path))
        return img_path

    if update.message.document:
        doc: Document = update.message.document
        ext = Path(doc.file_name or "image.jpg").suffix.lower() or ".jpg"
        img_path = tmp_dir / f"{prefix}_{idx:02d}{ext}"
        file = await context.bot.get_file(doc.file_id)
        await file.download_to_drive(str(img_path))
        return img_path

    return None


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reset_brief(context)
    await update.message.reply_text(
        "👋 Chào mừng đến với *Brand Identity Generator*\\!\n\n"
        "Tôi sẽ hỏi bạn một vài câu để xây dựng brief, sau đó AI sẽ generate "
        "brand directions \\+ hình ảnh cho bạn\\.\n\n"
        "Bắt đầu nhé\\! 👇\n\n"
        "*Tên thương hiệu là gì?*",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return BRAND_NAME


# ── /reset ────────────────────────────────────────────────────────────────────

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reset_brief(context)
    await update.message.reply_text(
        "🔄 Brief đã được xoá\\. Bắt đầu lại từ đầu\\!\n\n"
        "*Tên thương hiệu là gì?*",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return BRAND_NAME


# ── /cancel ───────────────────────────────────────────────────────────────────

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reset_brief(context)
    await update.message.reply_text(
        "👋 Đã huỷ\\. Gõ /start để bắt đầu lại nhé\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return ConversationHandler.END


# ── Step 1: Brand Name ────────────────────────────────────────────────────────

async def step_brand_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    intent = detect_intent(update.message.text or "")
    if intent == "back":
        return await handle_back(update, context)
    brief = get_brief(context)
    push_history(context, BRAND_NAME)

    text = update.message.text.strip()

    # Check for bulk input — user may paste brand name + other fields together.
    # Brand name is the first non-blank line (or "Brand: <name>" pattern).
    import re as _re
    brand_line_match = _re.match(
        r"^(?:brand(?:\s*name)?\s*[:：]\s*)?(.+?)$",
        text.splitlines()[0] if text else text,
        _re.IGNORECASE,
    )
    brief.brand_name = (brand_line_match.group(1).strip() if brand_line_match else text.splitlines()[0].strip()) or text

    # Try to parse remaining lines as bulk field input
    remaining = "\n".join(text.splitlines()[1:]).strip() if "\n" in text else ""
    filled = _parse_bulk_fields(remaining, brief) if remaining else 0

    await send_typing(update)

    if filled >= 1:
        # Jump ahead past already-filled fields
        next_state = _next_unfilled_state(brief)
        filled_summary = f"✅ Đã điền {filled} field từ input của bạn\\.\n\n"
        if next_state == CONFIRM:
            return await _send_confirm(update, context, brief)
        await update.message.reply_text(
            f"Tuyệt\\! *{escape_md(brief.brand_name)}* 🎯\n\n{filled_summary}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    await update.message.reply_text(
        f"Tuyệt\\! *{escape_md(brief.brand_name)}* — nghe hay đấy\\! 🎯\n\n"
        f"*Mô tả ngắn về sản phẩm/dịch vụ?*\n"
        f"_\\(ví dụ: SaaS platform giúp logistics track shipments bằng AI\\)_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return PRODUCT


# ── Step 2: Product ───────────────────────────────────────────────────────────

async def step_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    intent = detect_intent(update.message.text or "")
    if intent == "back":
        return await handle_back(update, context)
    brief = get_brief(context)
    push_history(context, PRODUCT)
    text = update.message.text.strip()

    # Try bulk parse first — user may paste multiple fields at once
    filled = _parse_bulk_fields(text, brief)
    if filled >= 2:
        # Multiple fields detected & filled; jump to next unfilled
        next_state = _next_unfilled_state(brief)
        if next_state == CONFIRM:
            return await _send_confirm(update, context, brief)
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Đã điền {filled} fields\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    # Single-field input — use normally
    brief.product = text
    await send_typing(update)
    await update.message.reply_text(
        "*Target audience là ai?*\n"
        "_\\(ví dụ: Ops managers tại mid\\-market e\\-commerce companies, 50\\-500 nhân viên\\)_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return AUDIENCE


# ── Step 3: Audience ──────────────────────────────────────────────────────────

async def step_audience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    intent = detect_intent(update.message.text or "")
    if intent == "back":
        return await handle_back(update, context)
    brief = get_brief(context)
    push_history(context, AUDIENCE)
    text = update.message.text.strip()

    filled = _parse_bulk_fields(text, brief)
    if filled >= 2:
        next_state = _next_unfilled_state(brief)
        if next_state == CONFIRM:
            return await _send_confirm(update, context, brief)
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Đã điền {filled} fields\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    brief.audience = text
    await send_typing(update)
    await update.message.reply_text(
        "*Tone/cá tính thương hiệu?*\n"
        "_Chọn một trong các hướng dưới đây, hoặc tự mô tả\\:_",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=TONE_KEYBOARD,
    )
    return TONE


# ── Step 4: Tone (inline keyboard) ───────────────────────────────────────────

TONE_MAP = {
    "tone_confident": "Confident, bold, authoritative — projects strength and clarity",
    "tone_minimal": "Minimal, clean, restrained — lets the product speak for itself",
    "tone_warm": "Warm, human, approachable — feels like a trusted friend",
    "tone_technical": "Sharp, technical, precise — built for experts who value accuracy",
    "tone_playful": "Playful, creative, energetic — memorable and expressive",
}


async def step_tone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    brief = get_brief(context)
    data = query.data

    if data == "tone_skip":
        brief = get_brief(context)
        next_state = _next_unfilled_state(brief)
        if next_state == CONFIRM:
            return await _send_confirm(update, context, brief)
        await query.edit_message_text(
            f"⏭ Tone bỏ qua — AI sẽ tự chọn\\.\n\n{_state_question_text(next_state)}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return next_state

    if data == "tone_custom":
        context.user_data[TONE_CUSTOM_KEY] = True
        await query.edit_message_text(
            "✏️ *Mô tả tone của bạn:*\n"
            "_\\(ví dụ: \"Tự tin nhưng không kiêu ngạo, như một người bạn thông minh\"\\)_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return TONE

    brief.tone = TONE_MAP.get(data, "")
    label = data.replace("tone_", "").replace("_", " ").title()
    next_state = _next_unfilled_state(brief)

    if next_state == CONFIRM:
            return await _send_confirm(update, context, brief)

    # Show tone confirmation then ask next unfilled field in a follow-up message
    await query.edit_message_text(
        f"✅ Tone: *{escape_md(label)}*",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    # Send the next question as a new message (can't use reply_text on a callback query edit)
    await query.message.reply_text(
        _state_question_text(next_state),
        parse_mode=ParseMode.MARKDOWN_V2,
        **({"reply_markup": TONE_KEYBOARD} if next_state == TONE else {}),
    )
    return next_state


async def step_tone_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom tone text input or natural language intents."""
    intent = detect_intent(update.message.text or "")
    if intent == "back":
        return await handle_back(update, context)
    if intent == "skip":
        push_history(context, TONE)
        brief = get_brief(context)
        next_state = _next_unfilled_state(brief)
        await send_typing(update)
        return await _ask_for_state(update, context, next_state)

    brief = get_brief(context)
    text = update.message.text.strip()

    # Check for bulk input regardless of whether we're in custom-tone mode
    filled = _parse_bulk_fields(text, brief)
    if filled >= 2:
        context.user_data.pop(TONE_CUSTOM_KEY, None)
        next_state = _next_unfilled_state(brief)
        if next_state == CONFIRM:
            return await _send_confirm(update, context, brief)
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Đã điền {filled} fields\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    if context.user_data.pop(TONE_CUSTOM_KEY, False):
        brief.tone = text
        await send_typing(update)
        next_state = _next_unfilled_state(brief)
        await update.message.reply_text(
            f"✅ Tone: _{escape_md(brief.tone)}_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)
    # Fallback: treat as brand name re-entry (shouldn't happen)
    return TONE


# ── Step 5: Core Promise ──────────────────────────────────────────────────────

async def step_core_promise(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    intent = detect_intent(update.message.text or "")
    if intent == "back":
        return await handle_back(update, context)
    brief = get_brief(context)
    push_history(context, CORE_PROMISE)
    text = update.message.text.strip()

    # Check for bulk input
    filled = _parse_bulk_fields(text, brief)
    if filled >= 2:
        next_state = _next_unfilled_state(brief)
        if next_state == CONFIRM:
            return await _send_confirm(update, context, brief)
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Đã điền {filled} fields\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    if intent == "skip" or text.lower() == "/skip":
        brief.core_promise = SKIP_SENTINEL  # mark as explicitly skipped
    else:
        brief.core_promise = text
    await send_typing(update)
    # Jump to the actual next unfilled state (geography may already be filled from bulk input)
    next_state = _next_unfilled_state(brief)
    return await _ask_for_state(update, context, next_state)


# ── Step 6: Geography ─────────────────────────────────────────────────────────

async def step_geography(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    intent = detect_intent(update.message.text or "")
    if intent == "back":
        return await handle_back(update, context)
    brief = get_brief(context)
    push_history(context, GEOGRAPHY)
    text = update.message.text.strip()

    # Check for bulk input
    filled = _parse_bulk_fields(text, brief)
    if filled >= 2:
        next_state = _next_unfilled_state(brief)
        if next_state == CONFIRM:
            return await _send_confirm(update, context, brief)
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Đã điền {filled} fields\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    if intent == "skip" or text.lower() == "/skip":
        brief.geography = SKIP_SENTINEL  # mark as explicitly skipped
    else:
        brief.geography = text
    await send_typing(update)
    # Jump to the actual next unfilled state (competitors may already be filled)
    next_state = _next_unfilled_state(brief)
    return await _ask_for_state(update, context, next_state)


# ── Step 7: Competitors ───────────────────────────────────────────────────────

async def step_competitors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    intent = detect_intent(update.message.text or "")
    if intent == "back":
        return await handle_back(update, context)
    brief = get_brief(context)
    push_history(context, COMPETITORS)
    text = update.message.text.strip()

    # Check for bulk input (e.g. user pastes competitors + moodboard + keywords)
    filled = _parse_bulk_fields(text, brief)
    if filled >= 2:
        next_state = _next_unfilled_state(brief)
        if next_state == CONFIRM:
            return await _send_confirm(update, context, brief)
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Đã điền {filled} fields\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    if intent == "skip" or text.lower() == "/skip":
        brief.competitors_direct = [SKIP_SENTINEL]  # mark as explicitly skipped
    elif text:
        import re
        lines = text.splitlines()
        for line in lines:
            m = re.match(r"^(Direct|Aspirational|Avoid)\s*:\s*(.+)", line, re.IGNORECASE)
            if m:
                label = m.group(1).lower()
                names = [n.strip() for n in m.group(2).split(",") if n.strip()]
                if label == "direct":
                    brief.competitors_direct = names
                elif label == "aspirational":
                    brief.competitors_aspirational = names
                else:
                    brief.competitors_avoid = names
            else:
                # Unstructured: treat as direct
                names = [n.strip() for n in re.split(r"[,;]", text) if n.strip()]
                brief.competitors_direct = names
    await send_typing(update)
    # Jump to LOGO_INSPIRATION or next state
    await update.message.reply_text(
        "🔤 *Bạn có ảnh logo nào muốn tham khảo không?*\n"
        "_\\(logo của brand khác mà bạn thích về phong cách, font, biểu tượng\\.\\.\\.\\)_\n\n"
        "_Gửi ảnh trực tiếp \\(hoặc dạng file\\) — có thể gửi nhiều_\n"
        "_Nhắn_ *xong* _khi đã gửi hết \\|_ *bỏ qua* _nếu không có_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return LOGO_INSPIRATION





# ── Step 9b: Logo Inspiration ─────────────────────────────────────────────────

async def step_logo_inspiration_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle a logo inspiration image."""
    brief = get_brief(context)
    idx = len(brief.logo_inspiration_paths) + 1
    img_path = await _download_image(update, context, "logo_ref", idx)
    if not img_path:
        return LOGO_INSPIRATION
    brief.logo_inspiration_paths.append(img_path)
    await update.message.reply_text(
        f"🔤 Đã nhận logo ref \\#{idx}\\! Gửi tiếp, hoặc nhắn *xong* khi đã gửi hết\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return LOGO_INSPIRATION


async def step_logo_inspiration_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text messages in LOGO_INSPIRATION state (e.g. 'xong', 'bỏ qua')."""
    intent = detect_intent(update.message.text or "")
    if intent == "done":
        return await step_logo_inspiration_done(update, context)
    if intent == "skip":
        return await step_logo_inspiration_skip(update, context)
    await update.message.reply_text(
        "🔤 Gửi ảnh logo mẫu bạn muốn tham khảo\\.\n"
        "Nhắn *xong* khi đã gửi hết, hoặc *bỏ qua* nếu không có\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return LOGO_INSPIRATION


async def step_logo_inspiration_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Done with logo inspirations → ask for pattern/banner inspirations."""
    brief = get_brief(context)
    n = len(brief.logo_inspiration_paths)
    note = f"✅ Nhận {n} logo ref\\!" if n else "⏭ Bỏ qua logo refs\\."
    await update.message.reply_text(
        f"{note}\n\n"
        "🌿 *Bạn có ảnh hoa văn, hoạ tiết, hoặc banner mẫu nào không?*\n"
        "_\\(pattern, texture, social media banner, bao bì sản phẩm\\.\\.\\. bất kỳ thứ gì định hướng visual layout\\)_\n\n"
        "_Gửi ảnh hoặc file — có thể gửi nhiều_\n"
        "_Nhắn_ *xong* _khi đã gửi hết \\|_ *bỏ qua* _nếu không có_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return PATTERN_INSPIRATION


async def step_logo_inspiration_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Skip logo inspirations → ask for pattern/banner."""
    await update.message.reply_text(
        "⏭ Bỏ qua logo refs\\.\n\n"
        "🌿 *Bạn có ảnh hoa văn, hoạ tiết, hoặc banner mẫu nào không?*\n"
        "_\\(pattern, texture, social banner, bao bì sản phẩm — bất kỳ thứ gì định hướng visual layout\\)_\n\n"
        "_Gửi ảnh hoặc file — có thể gửi nhiều_\n"
        "_Nhắn_ *xong* _khi đã gửi hết \\|_ *bỏ qua* _nếu không có_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return PATTERN_INSPIRATION


# ── Step 9c: Pattern / Banner Inspiration ─────────────────────────────────────

async def step_pattern_inspiration_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle a pattern / banner inspiration image."""
    brief = get_brief(context)
    idx = len(brief.pattern_inspiration_paths) + 1
    img_path = await _download_image(update, context, "pattern_ref", idx)
    if not img_path:
        return PATTERN_INSPIRATION
    brief.pattern_inspiration_paths.append(img_path)
    await update.message.reply_text(
        f"🌿 Đã nhận pattern ref \\#{idx}\\! Gửi tiếp, hoặc nhắn *xong* khi đã gửi hết\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return PATTERN_INSPIRATION


async def step_pattern_inspiration_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text messages in PATTERN_INSPIRATION state (e.g. 'xong', 'bỏ qua')."""
    intent = detect_intent(update.message.text or "")
    if intent == "done":
        return await step_pattern_inspiration_done(update, context)
    if intent == "skip":
        return await step_pattern_inspiration_skip(update, context)
    await update.message.reply_text(
        "🌿 Gửi ảnh hoa văn, pattern hoặc banner mẫu bạn muốn tham khảo\\.\n"
        "Nhắn *xong* khi đã gửi hết, hoặc *bỏ qua* nếu không có\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return PATTERN_INSPIRATION


async def step_pattern_inspiration_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Done with pattern inspirations → continue to KEYWORDS. Auto-set full mode if images."""
    brief = get_brief(context)
    n = len(brief.pattern_inspiration_paths)
    note = f"✅ Nhận {n} pattern ref\\!" if n else "⏭ Bỏ qua pattern refs\\."

    # Auto-switch to full mode if any inspiration images were uploaded
    auto_full_note = ""
    if _has_any_images(brief) and brief.mode != "full":
        brief.mode = "full"
    if _has_any_images(brief):
        auto_full_note = "\n\n🎨 _Bạn đã có visual references — tự động chọn *Full mode* để AI phân tích sâu hơn\\._"

    await update.message.reply_text(
        f"{note}{auto_full_note}\n\n"
        "*3 \\- 5 tính từ miêu tả tính cách thương hiệu?*\n"
        "_\\(optional — mỗi keyword 1 dòng hoặc cách nhau bằng dấu phẩy\\)_\n"
        "_ví dụ: minimal, trustworthy, precision_\n"
        "_Nhắn_ *bỏ qua* _nếu chưa có_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return KEYWORDS


async def step_pattern_inspiration_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Skip pattern inspirations → continue to KEYWORDS."""
    brief = get_brief(context)

    auto_full_note = ""
    if _has_any_images(brief) and brief.mode != "full":
        brief.mode = "full"
    if _has_any_images(brief):
        auto_full_note = "\n\n🎨 _Bạn đã có visual references — tự động chọn *Full mode* để AI phân tích sâu hơn\\._"

    await update.message.reply_text(
        f"⏭ Bỏ qua pattern refs\\.{auto_full_note}\n\n"
        "*3 \\- 5 tính từ miêu tả tính cách thương hiệu?*\n"
        "_\\(optional — mỗi keyword 1 dòng hoặc cách nhau bằng dấu phẩy\\)_\n"
        "_Nhắn_ *bỏ qua* _nếu chưa có_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return KEYWORDS


# ── Step 10: Keywords ─────────────────────────────────────────────────────────

async def step_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    intent = detect_intent(update.message.text or "")
    if intent == "back":
        return await handle_back(update, context)
    brief = get_brief(context)
    push_history(context, KEYWORDS)
    text = update.message.text.strip()

    # Check for bulk input (keywords + color preferences in same paste)
    filled = _parse_bulk_fields(text, brief)
    if filled >= 2:
        next_state = _next_unfilled_state(brief)
        if next_state == CONFIRM:
            return await _send_confirm(update, context, brief)
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Đã điền {filled} fields\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    if intent == "skip" or text.lower() == "/skip":
        brief.keywords = [SKIP_SENTINEL]  # mark as explicitly skipped
    elif text:
        import re
        kws = re.split(r"[,\n]+", text)
        brief.keywords = [k.strip().lstrip("-• ") for k in kws if k.strip()]
    await send_typing(update)
    # Use _next_unfilled_state in case color_preferences was already filled via bulk input
    next_state = _next_unfilled_state(brief)
    return await _ask_for_state(update, context, next_state)


# ── Step 10b: Color Preferences ───────────────────────────────────────────────

async def step_color_preferences(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    intent = detect_intent(update.message.text or "")
    if intent == "back":
        return await handle_back(update, context)
    brief = get_brief(context)
    push_history(context, COLOR_PREFERENCES)
    text = update.message.text.strip()

    if intent == "skip" or text.lower() == "/skip":
        brief.color_preferences = SKIP_SENTINEL  # mark as explicitly skipped
    elif text:
        brief.color_preferences = text
    await send_typing(update)
    return await _send_confirm(update, context, brief)


# ── _send_confirm helper — skip Mode, go directly to confirm screen ───────────

async def _send_confirm(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    brief,
) -> int:
    """
    Auto-set mode to full and show the brief summary + confirm keyboard.
    Replaces the old MODE_CHOICE step — mode is always 'full'.
    """
    brief.mode = "full"
    summary = brief.summary_text()
    safe_summary = escape_md(summary).replace("\\*", "*").replace("\\_", "_")
    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📋 *Tóm tắt brief:*\n\n{safe_summary}\n\nBạn muốn làm gì?"
        ),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=CONFIRM_KEYBOARD,
    )
    return CONFIRM


# ── Step 11: Mode Choice (kept for legacy compatibility) ──────────────────────

async def step_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    brief = get_brief(context)
    brief.mode = "quick" if query.data == "mode_quick" else "full"

    # If user chose quick but has images, warn them (images are best used with full)
    if brief.mode == "quick" and _has_any_images(brief):
        await query.message.reply_text(
            "⚠️ _Bạn đã upload visual references nhưng chọn Quick mode\\._\n"
            "_Quick mode sẽ vẫn dùng ảnh, nhưng Full mode phân tích sâu hơn\\. Tiếp tục\\?_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    summary = brief.summary_text()
    # Escape for markdown
    safe_summary = escape_md(summary).replace("\\*", "*").replace("\\_", "_")

    await query.edit_message_text(
        f"📋 *Tóm tắt brief:*\n\n{safe_summary}\n\n"
        f"Bạn muốn làm gì?",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=CONFIRM_KEYBOARD,
    )
    return CONFIRM


# ── Step 12: Confirm ──────────────────────────────────────────────────────────

def _fetch_preview_refs(brief, n: int = 4) -> list:
    """
    Pull n diverse high-quality logo reference images for the preview step.
    Returns list of Path objects. Falls back to empty list on any error.
    """
    try:
        import json as _json
        from pathlib import Path as _Path
        project_root = _Path(__file__).parent.parent
        refs_dir = project_root / "references" / "logos"
        if not refs_dir.exists():
            return []

        kw = list(getattr(brief, "keywords", []) or [])
        # ConversationBrief uses .product (not .product_service / .industry)
        product = getattr(brief, "product", "") or ""
        audience = getattr(brief, "audience", "") or ""
        tone = getattr(brief, "tone", "") or ""
        # Build keyword set from all brief fields — include individual words AND
        # 2-word bigrams so Vietnamese compound terms like "cà phê" can match
        all_words = kw + product.split() + audience.split() + tone.split()
        kw_set = {w.lower() for w in all_words if len(w) > 1}
        # Add bigrams for compound Vietnamese terms
        for field_text in [product, audience, tone]:
            words = field_text.lower().split()
            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i+1]}"
                kw_set.add(bigram)

        # Explicit keyword → industry folder mapping for better scoring
        # Includes Vietnamese keywords so Vietnamese briefs match correctly
        INDUSTRY_MAP: dict = {
            "industry_food_beverage":    ["coffee", "cafe", "cafе", "drink", "beverage", "tea",
                                          "beer", "wine", "food", "restaurant", "bakery", "juice",
                                          "milk", "water", "snack", "bar", "brew", "roast", "latte",
                                          # Vietnamese
                                          "phê", "cà phê", "trà", "bia", "rượu", "đồ uống",
                                          "thực phẩm", "nhà hàng", "bánh", "nước", "ăn",
                                          "quán", "rang", "đặc sản", "ẩm thực", "thức uống",
                                          "sinh tố", "nông sản", "hữu cơ", "organic"],
            "industry_fashion_beauty":   ["fashion", "beauty", "clothing", "apparel", "cosmetic",
                                          "makeup", "skincare", "hair", "luxury", "style", "wear",
                                          "shoe", "bag", "jewelry", "perfume", "fragrance",
                                          # Vietnamese
                                          "thời trang", "đẹp", "mỹ phẩm", "quần áo", "trang sức",
                                          "nước hoa", "da", "chăm sóc", "làm đẹp", "phụ kiện",
                                          "giày", "túi", "sang trọng", "cao cấp"],
            "industry_finance_crypto":   ["finance", "fintech", "crypto", "bank", "invest", "fund",
                                          "insurance", "payment", "wallet", "trading", "money",
                                          # Vietnamese
                                          "tài chính", "ngân hàng", "đầu tư", "tiền",
                                          "bảo hiểm", "thanh toán", "ví", "giao dịch"],
            "industry_healthcare_wellness": ["health", "wellness", "medical", "pharma", "clinic",
                                             "fitness", "yoga", "sport", "gym", "supplement", "care",
                                             # Vietnamese
                                             "sức khỏe", "y tế", "dược", "phòng khám",
                                             "thể dục", "gym", "thể thao", "chăm sóc",
                                             "bệnh viện", "thuốc", "dinh dưỡng"],
            "industry_technology_saas":  ["tech", "software", "saas", "app", "digital", "ai",
                                          "cloud", "data", "platform", "startup", "code", "developer",
                                          # Vietnamese
                                          "công nghệ", "phần mềm", "ứng dụng", "số",
                                          "dữ liệu", "nền tảng", "lập trình", "kỹ thuật số"],
            "industry_education_edtech": ["education", "learn", "school", "course", "training",
                                          "university", "academy", "edtech", "tutor", "study",
                                          # Vietnamese
                                          "giáo dục", "học", "trường", "đào tạo",
                                          "khóa học", "dạy", "sinh viên", "đại học"],
            "industry_media_gaming":     ["media", "gaming", "game", "entertainment", "music",
                                          "video", "stream", "podcast", "creative", "art", "studio",
                                          # Vietnamese
                                          "truyền thông", "trò chơi", "giải trí", "âm nhạc",
                                          "sáng tạo", "nghệ thuật", "phim", "nội dung"],
            "industry_retail_ecommerce": ["retail", "shop", "store", "ecommerce", "brand",
                                          "product", "market", "sell", "commerce",
                                          # Vietnamese
                                          "bán lẻ", "cửa hàng", "thương mại", "sản phẩm",
                                          "chợ", "mua bán", "thương hiệu"],
            "industry_real_estate":      ["real estate", "property", "home", "house", "architect",
                                          "interior", "construction", "living", "space",
                                          # Vietnamese
                                          "bất động sản", "nhà", "xây dựng", "kiến trúc",
                                          "nội thất", "căn hộ", "không gian"],
        }
        # Boost score for folders matching product/keyword industry
        industry_boosts: dict = {}
        for folder, markers in INDUSTRY_MAP.items():
            for marker in markers:
                if marker in kw_set or any(marker in w for w in kw_set):
                    industry_boosts[folder] = industry_boosts.get(folder, 0) + 3

        # Score every category dir
        scored: list = []
        for sub in sorted(refs_dir.iterdir()):
            if not sub.is_dir() or not (sub / "index.json").exists():
                continue
            cat_words = set(sub.name.lower().replace("-", "_").split("_"))
            # Remove generic stop words that appear in every industry folder name
            cat_words.discard("industry")
            cat_score = len(kw_set & cat_words)
            folder_boost = industry_boosts.get(sub.name, 0)
            try:
                index = _json.loads((sub / "index.json").read_text())
                for fname, entry in index.items():
                    tags = entry.get("tags", {})
                    all_tags: set = set()
                    for lst_key in ("style", "industry", "mood", "technique"):
                        val = tags.get(lst_key, [])
                        if isinstance(val, list):
                            for t in val:
                                all_tags.update(t.lower().split())
                        elif isinstance(val, str):
                            all_tags.update(val.lower().split())
                    tag_overlap = len(kw_set & all_tags)
                    quality     = tags.get("quality", 5) if isinstance(tags.get("quality"), (int, float)) else 5
                    score       = folder_boost + cat_score * 2 + tag_overlap + quality / 10.0
                    rel  = entry.get("relative_path", "")
                    absp = entry.get("local_path", "")
                    resolved = str(project_root / rel) if rel else absp
                    if resolved and _Path(resolved).exists():
                        scored.append((score, sub.name, _Path(resolved)))
            except Exception:
                continue

        if not scored:
            return []

        scored.sort(key=lambda x: -x[0])

        # ── Industry-first filter ─────────────────────────────────────────────
        # If we have strong industry matches, ONLY show those — never mix in
        # random style refs (mascot, brutalist, etc.) for a coffee brand.
        has_industry_match = any(boost >= 3 for boost in industry_boosts.values())
        if has_industry_match:
            industry_only = [(s, c, p) for s, c, p in scored if c.startswith("industry_")]
            if len(industry_only) >= n:
                scored = industry_only

        # Pick n diverse images (one per category as much as possible)
        result: list = []
        seen_cats: set = set()
        # First pass: best per category
        for score, cat, p in scored:
            if cat not in seen_cats and len(result) < n:
                result.append(p)
                seen_cats.add(cat)
        # Second pass: fill remaining slots with top scorers
        for score, cat, p in scored:
            if p not in result and len(result) < n:
                result.append(p)

        return result[:n]
    except Exception:
        return []


def _build_ref_keyboard(n_refs: int, selected: list) -> InlineKeyboardMarkup:
    """
    Build the ref selection keyboard.
    selected = list of 0-based indices already chosen (max 2).
    Buttons show ✅ if selected, number if not.
    """
    ref_row = []
    for i in range(1, n_refs + 1):
        label = f"✅ {i}" if (i - 1) in selected else f"🖼 {i}"
        ref_row.append(InlineKeyboardButton(label, callback_data=f"ref_toggle_{i}"))

    action_row = []
    if selected:
        n = len(selected)
        action_row.append(InlineKeyboardButton(
            f"✅ Xác nhận ({n} ref đã chọn)",
            callback_data="ref_confirm",
        ))
    action_row.append(InlineKeyboardButton("📁 Upload ref của bạn", callback_data="ref_upload"))
    action_row.append(InlineKeyboardButton("⚡ Bỏ qua", callback_data="ref_skip"))

    rows = [ref_row, action_row]
    return InlineKeyboardMarkup(rows)


async def step_ref_choice_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    After brief confirm → show 4 reference logo images, let user pick 1 or 2
    as visual style anchor, upload their own ref, or skip.
    """
    brief = get_brief(context)
    refs  = _fetch_preview_refs(brief, n=4)

    if not refs:
        return await _launch_pipeline(update, context)

    context.user_data["preview_refs"]    = [str(p) for p in refs]
    context.user_data["selected_refs"]   = []   # list of 0-based indices

    from telegram import InputMediaPhoto
    media_group = []
    for i, p in enumerate(refs, 1):
        try:
            media_group.append(
                InputMediaPhoto(
                    media=p.read_bytes(),
                    caption=str(i),
                )
            )
        except Exception:
            pass

    if media_group:
        await context.bot.send_media_group(
            chat_id=update.effective_chat.id,
            media=media_group,
        )

    kb = _build_ref_keyboard(len(media_group), [])
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "👆 *Chọn style ref cho toàn bộ 4 hướng logo\\.*\n\n"
            "Bấm để chọn 1 hoặc 2 ảnh — AI sẽ dùng làm style anchor \\(concept khác nhau, "
            "nhưng cùng render aesthetic\\)\\.\n"
            "Hoặc upload ảnh ref của chính bạn\\."
        ),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )
    return REF_CHOICE


async def step_ref_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle ref toggle / confirm / upload / skip."""
    query = update.callback_query
    await query.answer()
    data = query.data

    refs     = context.user_data.get("preview_refs", [])
    selected = context.user_data.get("selected_refs", [])

    if data.startswith("ref_toggle_"):
        idx = int(data.split("_")[2]) - 1   # 0-based
        if idx in selected:
            selected.remove(idx)             # deselect
        elif len(selected) < 2:
            selected.append(idx)             # add (max 2)
        context.user_data["selected_refs"] = selected
        kb = _build_ref_keyboard(len(refs), selected)
        try:
            await query.edit_message_reply_markup(reply_markup=kb)
        except Exception:
            pass
        return REF_CHOICE

    if data == "ref_upload":
        await query.edit_message_text(
            "📁 *Upload ảnh ref của bạn\\.*\n\n"
            "Gửi 1–2 ảnh logo theo style bạn muốn\\. AI sẽ học render style từ đó\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return REF_UPLOAD

    # ref_confirm or ref_skip
    from pathlib import Path as _Path
    if data == "ref_confirm" and selected:
        chosen_paths = [_Path(refs[i]) for i in selected if 0 <= i < len(refs)]
        brief = get_brief(context)
        # Store as style_ref_images (separate from general moodboard)
        brief.style_ref_images = chosen_paths
        # ALSO store in logo_inspiration_paths (dataclass field) so write_to_temp_dir()
        # writes them to the logo_inspiration/ subfolder for the pipeline to read
        brief.logo_inspiration_paths = list(chosen_paths)
        # Also prepend to moodboard_image_paths so Director gets them as visual context
        for p in reversed(chosen_paths):
            if p not in brief.moodboard_image_paths:
                brief.moodboard_image_paths.insert(0, p)
        await query.edit_message_text(
            f"✅ Đã chọn {len(chosen_paths)} style ref\\. Bắt đầu generate\\!",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    else:
        await query.edit_message_text("⚡ Bắt đầu generate\\!", parse_mode=ParseMode.MARKDOWN_V2)

    return await _launch_pipeline(update, context)


async def step_ref_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    REF_UPLOAD state: user sends 1-2 photos as their own style refs.
    Saves them to temp dir, stores as style_ref_images on the brief.
    After receiving, proceed to pipeline.
    """
    from pathlib import Path as _Path
    import tempfile

    message = update.message
    if not message:
        return REF_UPLOAD

    # Resolve file_id + filename regardless of whether user sends photo or document
    file_id: str = ""
    save_name: str = "user_ref.jpg"
    if message.photo:
        # Compressed photo — take highest resolution
        photo = message.photo[-1]
        file_id = photo.file_id
        save_name = f"user_ref_{file_id}.jpg"
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        # Image sent as file (uncompressed)
        file_id = message.document.file_id
        save_name = message.document.file_name or f"user_ref_{file_id}.jpg"
    else:
        await message.reply_text(
            "⚠️ Vui lòng gửi ảnh\\. Hoặc gõ /skip để bỏ qua\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return REF_UPLOAD

    file_obj = await context.bot.get_file(file_id)

    # Save to temp dir
    tmp_dir = _Path(tempfile.mkdtemp(prefix="ref_upload_"))
    save_path = tmp_dir / save_name
    await file_obj.download_to_drive(str(save_path))

    # Accumulate uploads (user may send 2)
    uploads = context.user_data.get("ref_uploads", [])
    uploads.append(str(save_path))
    context.user_data["ref_uploads"] = uploads

    brief = get_brief(context)
    chosen_paths = [_Path(p) for p in uploads]
    brief.style_ref_images = chosen_paths
    # ALSO store in logo_inspiration_paths (dataclass field) so write_to_temp_dir()
    # writes them to the logo_inspiration/ subfolder for the pipeline to read
    brief.logo_inspiration_paths = list(chosen_paths)
    # Also prepend to moodboard_image_paths so Director gets visual context
    for p in reversed(chosen_paths):
        if p not in brief.moodboard_image_paths:
            brief.moodboard_image_paths.insert(0, p)

    if len(uploads) < 2:
        await message.reply_text(
            f"✅ Đã nhận ref {len(uploads)}\\. Gửi thêm 1 ảnh nữa hoặc bấm /done để bắt đầu\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return REF_UPLOAD
    else:
        await message.reply_text(
            "✅ Đã nhận 2 style ref\\. Bắt đầu generate\\!",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _launch_pipeline(update, context)


async def step_ref_upload_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User sends /done after uploading refs — launch pipeline with what we have."""
    uploads = context.user_data.get("ref_uploads", [])
    if uploads:
        await update.message.reply_text(
            f"✅ Dùng {len(uploads)} style ref\\. Bắt đầu generate\\!",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    else:
        await update.message.reply_text("⚡ Bắt đầu generate\\!", parse_mode=ParseMode.MARKDOWN_V2)
    return await _launch_pipeline(update, context)


async def _launch_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Common pipeline launch logic (extracted from step_confirm_callback)."""
    brief   = get_brief(context)
    chat_id = update.effective_chat.id
    api_key = os.environ.get("GEMINI_API_KEY", "")

    if not api_key:
        await context.bot.send_message(chat_id, "❌ GEMINI\\_API\\_KEY chưa được set\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return ConversationHandler.END

    mode_label = "Full \\(4 directions\\)" if brief.mode == "full" else "Quick \\(2 directions\\)"
    progress_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏳ *Đang khởi động pipeline\\.\\.\\.*\n\n"
            f"Mode: {mode_label}\n"
            f"Brand: *{escape_md(brief.brand_name)}*\n\n"
            f"_Quá trình mất 3–12 phút tùy mode\\._"
        ),
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    context.user_data[MSG_ID_KEY] = progress_msg.message_id
    brief_dir = brief.write_to_temp_dir()
    context.user_data[TEMP_DIR_KEY] = str(brief_dir)

    asyncio.create_task(
        _run_pipeline_phase1(
            context=context,
            chat_id=chat_id,
            progress_msg_id=progress_msg.message_id,
            brief=brief,
            brief_dir=brief_dir,
            api_key=api_key,
        )
    )
    return ConversationHandler.END


async def step_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "confirm_cancel":
        reset_brief(context)
        await query.edit_message_text("❌ Đã huỷ\\. Gõ /start để bắt đầu lại\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return ConversationHandler.END

    if data == "confirm_edit":
        await query.edit_message_text(
            "✏️ Gõ /start để bắt đầu lại với brief mới\\.\n"
            "_\\(Chưa hỗ trợ chỉnh sửa từng field — coming soon\\)_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ConversationHandler.END

    # confirm_go → ask user for their own ref (REF_UPLOAD state)
    await query.edit_message_text(
        "📁 *Upload ảnh ref của bạn \\(tuỳ chọn\\)\\.*\n\n"
        "Gửi 1–2 ảnh logo theo style bạn muốn\\. AI sẽ học render style từ đó\\.\n\n"
        "👉 _Hoặc gõ /skip để bỏ qua phần này và bắt đầu cấu trúc logo\\._",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return REF_UPLOAD


# ── Pipeline Phase 1: concept ideation + 4 logos ──────────────────────────────

async def _run_pipeline_phase1(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    progress_msg_id: int,
    brief: ConversationBrief,
    brief_dir: Path,
    api_key: str,
    refinement_feedback: Optional[str] = None,
) -> None:
    """Run Phase 1: concept ideation + director + 4 logos only. Then enter HITL selection."""
    import traceback as _tb
    try:
        await _run_pipeline_phase1_inner(
            context=context,
            chat_id=chat_id,
            progress_msg_id=progress_msg_id,
            brief=brief,
            brief_dir=brief_dir,
            api_key=api_key,
            refinement_feedback=refinement_feedback,
        )
    except Exception as _top_err:
        logger.error("_run_pipeline_phase1 crashed", exc_info=True)
        tb_lines = _tb.format_exception(type(_top_err), _top_err, _top_err.__traceback__)
        tb_last = "".join(tb_lines[-3:])[:400]
        err_type = type(_top_err).__name__
        err_msg = str(_top_err)[:200]
        debug_text = (
            f"❌ *Lỗi pipeline phase 1* \\(`{escape_md(err_type)}`\\)\n\n"
            f"`{escape_md(err_msg)}`\n\n"
            f"_Traceback \\(last 3 frames\\):_\n```\n{escape_md(tb_last)}\n```"
        )
        try:
            await context.bot.send_message(chat_id=chat_id, text=debug_text, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Pipeline lỗi: {err_type}: {err_msg}\n\nGõ /cancel rồi /start để thử lại.",
            )


async def _run_pipeline_phase1_inner(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    progress_msg_id: int,
    brief: ConversationBrief,
    brief_dir: Path,
    api_key: str,
    refinement_feedback: Optional[str] = None,
) -> None:
    """Inner implementation of Phase 1 (called by _run_pipeline_phase1)."""

    def on_progress(msg: str) -> None:
        asyncio.create_task(safe_edit(context, chat_id, progress_msg_id, msg))

    runner = PipelineRunner(api_key=api_key)
    result = await runner.run_logos_phase(
        brief_dir=brief_dir,
        on_progress=on_progress,
        refinement_feedback=refinement_feedback,
    )

    if not result.success:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Pipeline thất bại\\:\n```\n{escape_md(result.error[:500])}\n```",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        _cleanup(brief_dir)
        return

    elapsed = result.elapsed_seconds
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)
    await safe_edit(
        context, chat_id, progress_msg_id,
        f"✅ *4 logo hoàn thành\\!* {mins}m {secs}s\n\nĐang gửi\\.\\.\\."
    )

    # Store state for Phase 2 / HITL
    context.user_data[DIRECTIONS_KEY] = result.directions_output
    context.user_data[ALL_ASSETS_KEY] = result.all_assets
    context.user_data[OUTPUT_DIR_KEY] = str(result.output_dir)

    # ── Send 4 logos as media group ───────────────────────────────────────────
    from telegram import InputMediaPhoto
    media_group = []
    for opt_num in sorted(result.all_assets.keys()):
        assets = result.all_assets[opt_num]
        direction = next(
            (d for d in result.directions_output.directions if d.option_number == opt_num),
            None,
        )
        if direction and assets.logo and assets.logo.exists():
            caption = (
                f"*{opt_num}\\. {escape_md(direction.direction_name)}*\n"
                f"_{escape_md(direction.rationale[:100])}_"
            )
            media_group.append(
                InputMediaPhoto(
                    media=assets.logo.read_bytes(),
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            )

    if media_group:
        try:
            await context.bot.send_media_group(chat_id=chat_id, media=media_group)
        except Exception as e:
            logger.warning(f"Media group send failed, sending individually: {e}")
            for item in media_group:
                try:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=item.media,
                        caption=item.caption,
                        parse_mode=ParseMode.MARKDOWN_V2,
                    )
                except Exception:
                    pass

    # ── Show HITL selection keyboard ──────────────────────────────────────────
    option_nums = sorted(result.all_assets.keys())
    select_row = [
        InlineKeyboardButton(f"✅ Chọn {i}", callback_data=f"logo_select_{i}")
        for i in option_nums
    ]
    kb = InlineKeyboardMarkup([
        select_row,
        [InlineKeyboardButton("✏️ Chỉnh sửa / Mô tả thêm", callback_data="logo_refine")],
    ])
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "👆 *4 hướng logo — chọn 1 để tiếp tục, hoặc mô tả chỉnh sửa bằng ngôn ngữ tự nhiên\\.*"
        ),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )

    # Set flag so global text handler knows to intercept
    context.user_data[LOGO_REVIEW_FLAG] = True


# ── HITL: logo selection callback ─────────────────────────────────────────────

async def step_logo_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle logo_select_N and logo_refine inline button callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id

    if data == "logo_refine":
        await query.edit_message_text(
            "✏️ Mô tả điều chỉnh bạn muốn \\(vd: _\"thêm yếu tố nature, bớt corporate\"_\\)\\:\n\n"
            "_Bot sẽ tái tạo 4 hướng logo mới theo feedback của bạn\\._",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        # Keep LOGO_REVIEW_FLAG so the text handler picks up the next message
        context.user_data[LOGO_REVIEW_FLAG] = True
        context.user_data["logo_refine_mode"] = True
        context.user_data.pop("logo_force_regenerate", None)
        return

    if data == "logo_refine_all":
        await query.edit_message_text(
            "🔄 *Tạo lại 4 hướng hoàn toàn mới\\.*\n\n"
            "Mô tả điều bạn muốn thay đổi \\(hoặc gõ _tạo lại_ để gen ngẫu nhiên\\)\\:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        # Set force-regenerate flag so step_logo_review_text skips direction detection
        context.user_data[LOGO_REVIEW_FLAG] = True
        context.user_data["logo_refine_mode"] = True
        context.user_data["logo_force_regenerate"] = True
        return

    # logo_select_N
    if data.startswith("logo_select_"):
        try:
            chosen_num = int(data.split("_")[-1])
        except (ValueError, IndexError):
            await query.edit_message_text("❌ Lựa chọn không hợp lệ\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return

        directions_output = context.user_data.get(DIRECTIONS_KEY)
        if not directions_output:
            await query.edit_message_text(
                "❌ Không tìm thấy dữ liệu directions\\. Gõ /start để bắt đầu lại\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        chosen_direction = next(
            (d for d in directions_output.directions if d.option_number == chosen_num),
            None,
        )
        if not chosen_direction:
            await query.edit_message_text(
                f"❌ Không tìm thấy hướng {chosen_num}\\.", parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        # Clear HITL flag
        context.user_data[LOGO_REVIEW_FLAG] = False
        context.user_data.pop("logo_refine_mode", None)

        # Store chosen direction for downstream phases
        context.user_data[CHOSEN_DIR_KEY] = chosen_direction

        await query.edit_message_text(
            f"✅ *Chốt hướng {chosen_num}\\: {escape_md(chosen_direction.direction_name)}*\n\n"
            f"⏳ Đang gen logo variants \\+ bảng màu\\.\\.\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

        output_dir = Path(context.user_data.get(OUTPUT_DIR_KEY, "outputs/bot_unknown"))
        brief_dir_str = context.user_data.get(TEMP_DIR_KEY)
        brief_dir = Path(brief_dir_str) if brief_dir_str else None
        api_key = os.environ.get("GEMINI_API_KEY", "")
        brief = get_brief(context)
        all_assets = context.user_data.get(ALL_ASSETS_KEY, {})
        chosen_assets = all_assets.get(chosen_num)

        # Launch logo variants + palette phase as background task
        asyncio.create_task(
            _run_logo_variants_and_palette_phase(
                context=context,
                chat_id=chat_id,
                chosen_direction=chosen_direction,
                chosen_assets=chosen_assets,
                output_dir=output_dir,
                brief_dir=brief_dir,
                brief=brief,
                api_key=api_key,
            )
        )


# ── HITL: free-text logo refinement ───────────────────────────────────────────

async def step_logo_review_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text refinement when LOGO_REVIEW_FLAG is set."""
    if not context.user_data.get(LOGO_REVIEW_FLAG):
        return  # Not in logo review mode — ignore

    text = update.message.text.strip()
    if not text:
        return

    chat_id = update.effective_chat.id
    brief_dir_str = context.user_data.get(TEMP_DIR_KEY)
    brief_dir = Path(brief_dir_str) if brief_dir_str else None
    api_key = os.environ.get("GEMINI_API_KEY", "")
    brief = get_brief(context)

    # ── Recover brief_dir if missing or deleted ────────────────────────────
    if not brief_dir or not brief_dir.exists():
        if brief and brief.brand_name:
            brief_dir = brief.write_to_temp_dir()
            context.user_data[TEMP_DIR_KEY] = str(brief_dir)
            logger.info(f"Recovered brief_dir for logo refinement → {brief_dir}")

    if not brief_dir or not brief_dir.exists():
        await update.message.reply_text(
            "❌ Session đã hết hạn\\. Gõ /start để bắt đầu lại\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        context.user_data[LOGO_REVIEW_FLAG] = False
        return

    # Read and clear refine/force-regenerate flags
    force_regenerate = context.user_data.pop("logo_force_regenerate", False)
    context.user_data.pop("logo_refine_mode", None)
    context.user_data[LOGO_REVIEW_FLAG] = False

    # ── Build enriched feedback: include previous 4 directions as context ──
    # Without this, Director has no idea what "hướng 4" or "direction 2" means.
    enriched_feedback = text
    directions_output = context.user_data.get(DIRECTIONS_KEY)
    if directions_output and hasattr(directions_output, "directions"):
        try:
            prev_lines = []
            for d in directions_output.directions:
                name  = getattr(d, "direction_name", "")
                num   = getattr(d, "option_number", "?")
                concept = getattr(d, "logo_concept", "") or getattr(d, "rationale", "")
                # First sentence of logo_concept is enough
                concept_short = concept.split(".")[0] if concept else ""
                prev_lines.append(f"Direction {num} — \"{name}\": {concept_short}")
            prev_summary = "\n".join(prev_lines)
            enriched_feedback = (
                f"USER FEEDBACK: {text}\n\n"
                f"PREVIOUS 4 DIRECTIONS (for reference — user may reference them by number or name):\n"
                f"{prev_summary}"
            )
            logger.info(f"Logo refine: enriched feedback built with {len(prev_lines)} previous directions")
        except Exception as e:
            logger.warning(f"Could not build enriched feedback: {e}")
            enriched_feedback = text

    # ── Route: single-direction edit vs full regenerate ───────────────────────
    # If user clicked "Tạo lại 4 hướng" button, skip direction detection entirely
    direction_num = None
    try:
        if not force_regenerate:
            direction_num = _extract_direction_number(text)
    except Exception as _dir_err:
        logger.warning(f"_extract_direction_number failed: {_dir_err} — falling back to full regenerate")
        direction_num = None

    all_assets = context.user_data.get(ALL_ASSETS_KEY) or {}
    logo_path_for_edit: Optional[Path] = None

    if direction_num:
        try:
            direction_assets = all_assets.get(direction_num)
            raw_logo = getattr(direction_assets, "logo", None) if direction_assets else None
            if raw_logo and Path(raw_logo).exists():
                logo_path_for_edit = Path(raw_logo)
                logger.info(f"Targeted edit mode: direction {direction_num}, logo={logo_path_for_edit.name}")
            else:
                logger.warning(f"Direction {direction_num} referenced but logo path not found — falling back to full regenerate")
        except Exception as _asset_err:
            logger.warning(f"Error resolving logo asset for direction {direction_num}: {_asset_err} — falling back to full regenerate")
            logo_path_for_edit = None

    if logo_path_for_edit:
        # ── TARGETED EDIT: keep design, apply only the requested change ──────
        progress_msg = await update.message.reply_text(
            f"✏️ *Đang chỉnh sửa hướng {direction_num}\\.\\.\\.*\n\n"
            f"_\"{escape_md(text[:100])}\"_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        asyncio.create_task(
            _run_single_logo_edit_phase(
                context=context,
                chat_id=chat_id,
                progress_msg_id=progress_msg.message_id,
                direction_num=direction_num,
                logo_path=logo_path_for_edit,
                feedback_text=text,
                api_key=api_key,
            )
        )
    else:
        # ── FULL REGENERATE: no specific direction → gen 4 new directions ────
        try:
            progress_msg = await update.message.reply_text(
                f"🔄 *Đang tái tạo logos theo feedback\\.\\.\\.*\n\n"
                f"_\"{escape_md(text[:100])}\"_",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception as _md_err:
            logger.error(f"MarkdownV2 reply failed in logo refine: {_md_err!r}")
            progress_msg = await update.message.reply_text(
                f"🔄 Đang tái tạo logos theo feedback...\n\n\"{text[:100]}\"",
            )
        asyncio.create_task(
            _run_pipeline_phase1(
                context=context,
                chat_id=chat_id,
                progress_msg_id=progress_msg.message_id,
                brief=brief,
                brief_dir=brief_dir,
                api_key=api_key,
                refinement_feedback=enriched_feedback,
            )
        )


# ── Sub-phase: targeted single-logo edit ──────────────────────────────────────

async def _run_single_logo_edit_phase(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    progress_msg_id: int,
    direction_num: int,
    logo_path: Path,
    feedback_text: str,
    api_key: str,
) -> None:
    """
    Edit ONE existing logo image using Gemini multimodal (image + text → edited image).
    Triggered when user's feedback explicitly references a direction number.
    Preserves the design of that direction, only applies the requested change.
    """
    output_dir = Path(context.user_data.get(OUTPUT_DIR_KEY, "outputs/bot_unknown"))

    await safe_edit(
        context, chat_id, progress_msg_id,
        f"✏️ *Đang chỉnh sửa hướng {direction_num}\\.\\.\\.*\n\n"
        f"_\"{escape_md(feedback_text[:80])}\"_",
    )

    runner = PipelineRunner(api_key=api_key)
    result = await runner.run_single_logo_edit(
        direction_num=direction_num,
        logo_path=logo_path,
        edit_instruction=feedback_text,
        output_dir=output_dir,
    )

    if not result["success"]:
        err = escape_md(result.get("error", "unknown error")[:300])
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Không thể chỉnh sửa logo\\.\n```\n{err}\n```",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        # Re-enable logo review so user can try again
        context.user_data[LOGO_REVIEW_FLAG] = True
        return

    edited_path = result["path"]
    elapsed = result.get("elapsed", 0)
    secs = int(elapsed)

    await safe_edit(
        context, chat_id, progress_msg_id,
        f"✅ *Hướng {direction_num} đã được chỉnh sửa\\!* {secs}s",
    )

    # Update the logo path in ALL_ASSETS_KEY so logo_select uses the edited version
    all_assets = context.user_data.get(ALL_ASSETS_KEY, {})
    direction_assets = all_assets.get(direction_num)
    if direction_assets:
        direction_assets.logo = edited_path
        context.user_data[ALL_ASSETS_KEY] = all_assets

    # Send edited logo
    try:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=edited_path.read_bytes(),
            caption=f"✏️ Hướng {direction_num} — đã chỉnh sửa",
        )
    except Exception:
        await context.bot.send_document(
            chat_id=chat_id,
            document=edited_path.read_bytes(),
            filename=edited_path.name,
        )

    # Show action keyboard: select this direction / refine more / regenerate all
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✅ Chọn hướng {direction_num} này",
            callback_data=f"logo_select_{direction_num}",
        )],
        [InlineKeyboardButton("✏️ Chỉnh sửa tiếp hướng này", callback_data="logo_refine")],
        [InlineKeyboardButton("🔄 Tạo lại 4 hướng hoàn toàn mới", callback_data="logo_refine_all")],
    ])
    await context.bot.send_message(
        chat_id=chat_id,
        text="👆 *Bạn muốn làm gì tiếp theo?*",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )
    # Keep LOGO_REVIEW_FLAG active so user can keep refining
    context.user_data[LOGO_REVIEW_FLAG] = True


# ── Sub-phase: logo variants + palette generation ─────────────────────────────

async def _run_mockup_background(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    chosen_assets: object,
    output_dir: Path,
    api_key: str,
) -> List[Path]:
    """
    Background mockup compositing — fired right after logo variants are ready.
    Runs ALL mockups in PARALLEL with palette + pattern HITL phases.

    Returns list of composited mockup Paths.
    """
    loop = asyncio.get_event_loop()
    from src.mockup_compositor import get_processed_mockup_files, composite_single_mockup

    processed_files = get_processed_mockup_files()
    mockup_paths: List[Path] = []

    if not processed_files or not chosen_assets:
        return mockup_paths

    mockup_dir = output_dir / "mockups"
    mockup_dir.mkdir(parents=True, exist_ok=True)

    # Fire ALL mockups in parallel using asyncio.gather + run_in_executor
    async def _do_one(pf):
        try:
            return await loop.run_in_executor(
                None,
                lambda: composite_single_mockup(
                    processed_file=pf,
                    assets=chosen_assets,
                    api_key=api_key,
                    mockup_dir=mockup_dir,
                ),
            )
        except Exception as e:
            logger.warning(f"Background mockup failed {pf.name}: {e}")
            return None

    results = await asyncio.gather(*[_do_one(pf) for pf in processed_files])

    for composited in results:
        if composited and composited.exists():
            mockup_paths.append(composited)

    logger.info(f"Background mockup done: {len(mockup_paths)}/{len(processed_files)}")
    return mockup_paths


async def _run_logo_variants_and_palette_phase(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    chosen_direction: object,
    chosen_assets: object,
    output_dir: Path,
    brief_dir: Optional[Path],
    brief: ConversationBrief,
    api_key: str,
    refinement_feedback: Optional[str] = None,
) -> None:
    """
    After logo is locked:
      1. Create logo variants (white/black/transparent + SVG) in background
      1b. Fire mockup compositing in background (parallel with palette + pattern HITL)
      2. Generate palette
      3. Send both to user
      4. Enter palette HITL
    """
    runner = PipelineRunner(api_key=api_key)
    direction_name = escape_md(getattr(chosen_direction, "direction_name", ""))

    # ── Recover brief_dir if missing or deleted (e.g. bot restart) ─────────
    if not brief_dir or not brief_dir.exists():
        if brief and brief.brand_name:
            brief_dir = brief.write_to_temp_dir()
            context.user_data[TEMP_DIR_KEY] = str(brief_dir)
            logger.info(f"Recovered brief_dir for logo+palette phase → {brief_dir}")

    # ── Step 1: Logo variants ─────────────────────────────────────────────────
    logo_path = getattr(chosen_assets, "logo", None) if chosen_assets else None
    logo_variant_paths = {}
    svg_path = None

    if logo_path and Path(logo_path).exists():
        try:
            slug = Path(logo_path).parent.name  # e.g. option_1_bold
            variant_dir = output_dir / slug
            variant_dir.mkdir(parents=True, exist_ok=True)
            logo_variant_paths = await runner.run_logo_variants_phase(
                logo_path=Path(logo_path),
                output_dir=variant_dir,
            )
            svg_path = logo_variant_paths.pop("logo_svg", None)
        except Exception as e:
            logger.warning(f"Logo variants failed: {e}")

    # Send logo variants
    from telegram import InputMediaPhoto
    variants_to_send = []
    for attr, label in [
        ("logo_white",       "Logo trắng"),
        ("logo_black",       "Logo đen"),
        ("logo_transparent", "Logo transparent"),
    ]:
        p = logo_variant_paths.get(attr) or (getattr(chosen_assets, attr, None) if chosen_assets else None)
        if p and Path(p).exists() and Path(p).stat().st_size > 100:
            variants_to_send.append((Path(p), label))

    if variants_to_send:
        await context.bot.send_message(
            chat_id=chat_id, text="🔤 *Logo variants*\\:", parse_mode=ParseMode.MARKDOWN_V2
        )
        media = [InputMediaPhoto(media=p.read_bytes(), caption=lbl) for p, lbl in variants_to_send]
        try:
            await context.bot.send_media_group(chat_id=chat_id, media=media)
        except Exception:
            for p, lbl in variants_to_send:
                try:
                    await context.bot.send_document(chat_id=chat_id, document=p.read_bytes(), filename=p.name, caption=lbl)
                except Exception:
                    pass

    if svg_path and svg_path.exists():
        try:
            await context.bot.send_document(
                chat_id=chat_id, document=svg_path.read_bytes(),
                filename=svg_path.name, caption="📐 Logo SVG (color)",
            )
        except Exception as e:
            logger.warning(f"SVG send failed: {e}")

    # Send white and black SVG variants
    svg_white = logo_variant_paths.get("logo_svg_white")
    svg_black = logo_variant_paths.get("logo_svg_black")
    for svg_p, label in [(svg_white, "📐 Logo SVG (white)"), (svg_black, "📐 Logo SVG (black)")]:
        if svg_p and Path(svg_p).exists():
            try:
                await context.bot.send_document(
                    chat_id=chat_id, document=Path(svg_p).read_bytes(),
                    filename=Path(svg_p).name, caption=label,
                )
            except Exception as e:
                logger.warning(f"SVG variant send failed: {e}")

    # Store variant paths for ZIP export later
    context.user_data["logo_variant_paths"] = logo_variant_paths
    context.user_data["logo_svg_path"] = str(svg_path) if svg_path else None
    context.user_data["logo_svg_white_path"] = str(svg_white) if svg_white else None
    context.user_data["logo_svg_black_path"] = str(svg_black) if svg_black else None

    # ── Step 1b: Fire mockup compositing in background ─────────────────────
    # Mockups only need logo + direction colors (not HITL palette/pattern),
    # so we can start them now and let them run parallel with palette + pattern HITL.
    if chosen_assets:
        # Patch logo variants into assets so mockup compositor can use them
        for attr in ("logo_white", "logo_black", "logo_transparent"):
            p = logo_variant_paths.get(attr)
            if p and Path(p).exists():
                setattr(chosen_assets, attr, Path(p))

        mockup_task = asyncio.create_task(
            _run_mockup_background(
                context=context,
                chat_id=chat_id,
                chosen_assets=chosen_assets,
                output_dir=output_dir,
                api_key=api_key,
            )
        )
        context.user_data["mockup_background_task"] = mockup_task
        logger.info("Mockup background task fired — running parallel with palette + pattern HITL")

    # ── Step 2: Generate palette ──────────────────────────────────────────────
    progress_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🎨 *Đang tạo bảng màu\\.\\.\\.*",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    def on_progress(msg: str) -> None:
        asyncio.create_task(safe_edit(context, chat_id, progress_msg.message_id, msg))

    palette_result = await runner.run_palette_phase(
        direction=chosen_direction,
        output_dir=output_dir,
        brief_dir=brief_dir,
        on_progress=on_progress,
        refinement_feedback=refinement_feedback,
    )

    if not palette_result.success:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Palette thất bại\\:\n```\n{escape_md(palette_result.error[:400])}\n```",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # Store palette data
    context.user_data[ENRICHED_COLORS_KEY] = palette_result.enriched_colors
    context.user_data[PALETTE_SHADES_KEY] = palette_result.palette_shades
    context.user_data["palette_png"] = str(palette_result.palette_png) if palette_result.palette_png else None
    context.user_data["shades_png"] = str(palette_result.shades_png) if palette_result.shades_png else None

    # Send palette
    if palette_result.palette_png and palette_result.palette_png.exists():
        await safe_edit(context, chat_id, progress_msg.message_id, "✅ *Bảng màu hoàn thành\\!*")
        try:
            await context.bot.send_document(
                chat_id=chat_id,
                document=palette_result.palette_png.read_bytes(),
                filename=palette_result.palette_png.name,
            )
        except Exception as e:
            logger.warning(f"Palette send failed: {e}")

    if palette_result.shades_png and palette_result.shades_png.exists():
        try:
            await context.bot.send_document(
                chat_id=chat_id,
                document=palette_result.shades_png.read_bytes(),
                filename=palette_result.shades_png.name,
                caption="🌈 Shade scales",
            )
        except Exception as e:
            logger.warning(f"Shades send failed: {e}")

    # ── Palette HITL keyboard ─────────────────────────────────────────────────
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Chốt bảng màu", callback_data="palette_accept")],
        [InlineKeyboardButton("✏️ Chỉnh sửa", callback_data="palette_refine")],
        [InlineKeyboardButton("🔄 Tạo lại", callback_data="palette_reroll")],
    ])
    await context.bot.send_message(
        chat_id=chat_id,
        text="👆 *Bạn muốn giữ bảng màu này hay chỉnh sửa?*",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )
    context.user_data[PALETTE_REVIEW_FLAG] = True


# ── Palette HITL handlers ─────────────────────────────────────────────────────

async def step_palette_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle palette_accept / palette_refine / palette_reroll callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id

    if data == "palette_accept":
        context.user_data[PALETTE_REVIEW_FLAG] = False
        await query.edit_message_text(
            "✅ *Bảng màu đã được chốt\\!*\n\n🔲 Tiếp theo\\: tạo hoạ tiết \\(pattern\\)\\.\\.\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        # Move to pattern phase — ask for refs
        await _start_pattern_ref_phase(context, chat_id)
        return

    if data == "palette_refine":
        context.user_data[PALETTE_REVIEW_FLAG] = True
        context.user_data["palette_refine_mode"] = True
        await query.edit_message_text(
            "✏️ Mô tả điều chỉnh bảng màu \\(vd: _\"ấm hơn\"_, _\"thêm xanh lá\"_, _\"bớt tím\"_\\)\\:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    if data == "palette_reroll":
        context.user_data[PALETTE_REVIEW_FLAG] = False
        await query.edit_message_text(
            "🔄 *Đang tạo lại bảng màu\\.\\.\\.*",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        # Re-run palette phase with no specific feedback
        _launch_palette_rerun(context, chat_id, refinement_feedback=None)
        return


async def step_palette_review_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text palette refinement when palette_refine_mode is set."""
    if not context.user_data.get(PALETTE_REVIEW_FLAG):
        return
    # Only process text if user clicked "✏️ Chỉnh sửa" (palette_refine_mode)
    if not context.user_data.get("palette_refine_mode"):
        return

    text = update.message.text.strip()
    if not text:
        return

    chat_id = update.effective_chat.id
    context.user_data[PALETTE_REVIEW_FLAG] = False
    context.user_data.pop("palette_refine_mode", None)

    progress_msg = await update.message.reply_text(
        f"🔄 *Đang tạo lại bảng màu theo feedback\\.\\.\\.*\n\n"
        f"_\"{escape_md(text[:100])}\"_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    _launch_palette_rerun(context, chat_id, refinement_feedback=text)


def _launch_palette_rerun(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    refinement_feedback: Optional[str],
) -> None:
    """Re-run palette generation only (skip logo variants — already done)."""
    asyncio.create_task(
        _run_palette_only_phase(context, chat_id, refinement_feedback)
    )


async def _run_palette_only_phase(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    refinement_feedback: Optional[str] = None,
) -> None:
    """Re-generate palette only — used for palette reroll/refine without re-running logo variants."""
    chosen_direction = context.user_data.get(CHOSEN_DIR_KEY)
    output_dir = Path(context.user_data.get(OUTPUT_DIR_KEY, "outputs/bot_unknown"))
    brief_dir_str = context.user_data.get(TEMP_DIR_KEY)
    brief_dir = Path(brief_dir_str) if brief_dir_str else None

    # ── Recover brief_dir if missing or deleted (e.g. bot restart) ─────────
    if not brief_dir or not brief_dir.exists():
        brief = get_brief(context)
        if brief and brief.brand_name:
            brief_dir = brief.write_to_temp_dir()
            context.user_data[TEMP_DIR_KEY] = str(brief_dir)
            logger.info(f"Recovered brief_dir → {brief_dir}")

    api_key = os.environ.get("GEMINI_API_KEY", "")

    progress_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🎨 *Đang tạo lại bảng màu\\.\\.\\.*",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    def on_progress(msg: str) -> None:
        asyncio.create_task(safe_edit(context, chat_id, progress_msg.message_id, msg))

    runner = PipelineRunner(api_key=api_key)
    palette_result = await runner.run_palette_phase(
        direction=chosen_direction,
        output_dir=output_dir,
        brief_dir=brief_dir,
        on_progress=on_progress,
        refinement_feedback=refinement_feedback,
    )

    if not palette_result.success:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Palette thất bại\\:\n```\n{escape_md(palette_result.error[:400])}\n```",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # Store updated palette data
    context.user_data[ENRICHED_COLORS_KEY] = palette_result.enriched_colors
    context.user_data[PALETTE_SHADES_KEY] = palette_result.palette_shades
    context.user_data["palette_png"] = str(palette_result.palette_png) if palette_result.palette_png else None
    context.user_data["shades_png"] = str(palette_result.shades_png) if palette_result.shades_png else None

    # Send palette
    if palette_result.palette_png and palette_result.palette_png.exists():
        await safe_edit(context, chat_id, progress_msg.message_id, "✅ *Bảng màu mới hoàn thành\\!*")
        try:
            with open(palette_result.palette_png, "rb") as f:
                await context.bot.send_document(
                    chat_id=chat_id, document=f, filename=palette_result.palette_png.name,
                )
        except Exception as e:
            logger.warning(f"Palette send failed: {e}")

    if palette_result.shades_png and palette_result.shades_png.exists():
        try:
            with open(palette_result.shades_png, "rb") as f:
                await context.bot.send_document(
                    chat_id=chat_id, document=f, filename=palette_result.shades_png.name,
                    caption="🌈 Shade scales",
                )
        except Exception as e:
            logger.warning(f"Shades send failed: {e}")

    # Palette HITL keyboard
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Chốt bảng màu", callback_data="palette_accept")],
        [InlineKeyboardButton("✏️ Chỉnh sửa", callback_data="palette_refine")],
        [InlineKeyboardButton("🔄 Tạo lại", callback_data="palette_reroll")],
    ])
    await context.bot.send_message(
        chat_id=chat_id,
        text="👆 *Bạn muốn giữ bảng màu này hay chỉnh sửa?*",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )
    context.user_data[PALETTE_REVIEW_FLAG] = True


# ── Pattern ref phase ─────────────────────────────────────────────────────────


async def _start_pattern_ref_phase(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Ask user to upload pattern refs or skip — no bot suggestions."""
    rows = [
        [InlineKeyboardButton("📷 Upload ref riêng", callback_data="patref_upload")],
        [InlineKeyboardButton("⏭ Bỏ qua, tạo luôn", callback_data="patref_skip")],
    ]
    kb = InlineKeyboardMarkup(rows)
    text_msg = (
        "🔲 *Bước tiếp theo\\: Hoạ tiết \\(Pattern\\)*\n\n"
        "Bạn có ảnh pattern ref muốn dùng không?\n\n"
        "• Upload ảnh pattern ref của riêng bạn\n"
        "• Hoặc bỏ qua — bot sẽ tự tạo style phù hợp nhất\n\n"
        "_Gửi ảnh xong gõ /done\\._"
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=text_msg,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )
    context.user_data[PATTERN_REF_FLAG] = True
    context.user_data[PATTERN_REFS_KEY] = []


async def step_pattern_ref_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle patref_select_N / patref_upload / patref_skip callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id
    logger.info(f"Pattern ref callback: {data}, flag={context.user_data.get(PATTERN_REF_FLAG)}")

    if data == "patref_upload":
        # Ensure flag is set so image handler picks up uploads
        context.user_data[PATTERN_REF_FLAG] = True
        context.user_data[PATTERN_REFS_KEY] = context.user_data.get(PATTERN_REFS_KEY, [])
        await query.edit_message_text(
            "📷 *Gửi ảnh pattern ref của bạn\\.*\n"
            "Gõ /done khi xong, hoặc /skip để bỏ qua\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    if data == "patref_skip":
        context.user_data[PATTERN_REF_FLAG] = False
        await query.edit_message_text(
            "⏭ *Bỏ qua pattern ref\\.*",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        # Ask for description
        await _ask_pattern_description(context, chat_id)
        return


async def step_pattern_ref_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pattern ref image uploads (global handler, group=1)."""
    if not context.user_data.get(PATTERN_REF_FLAG):
        return

    img_path = await _download_image(update, context, "patref", len(context.user_data.get(PATTERN_REFS_KEY, [])))
    if img_path:
        refs = context.user_data.get(PATTERN_REFS_KEY, [])
        refs.append(img_path)
        context.user_data[PATTERN_REFS_KEY] = refs
        await update.message.reply_text(
            f"✅ Đã nhận {len(refs)} ảnh ref\\. Gửi thêm hoặc gõ /done\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


async def step_pattern_ref_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /done or /skip during pattern ref upload."""
    if not context.user_data.get(PATTERN_REF_FLAG):
        return

    context.user_data[PATTERN_REF_FLAG] = False
    chat_id = update.effective_chat.id
    refs = context.user_data.get(PATTERN_REFS_KEY, [])
    if refs:
        await update.message.reply_text(
            f"✅ Đã nhận {len(refs)} ảnh pattern ref\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    await _ask_pattern_description(context, chat_id)


async def _ask_pattern_description(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Ask user for optional text description of desired pattern."""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Bỏ qua, tạo luôn", callback_data="patdesc_skip")],
    ])
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "✏️ *Mô tả pattern mong muốn \\(tùy chọn\\)*\n\n"
            "Ví dụ\\:\n"
            "• _\"Hình lá cà phê xen kẽ với hạt cà phê, phong cách line art\"_\n"
            "• _\"Geometric pattern tối giản, lấy cảm hứng từ kiến trúc\"_\n"
            "• _\"Hoạ tiết organic mềm mại, phù hợp ngành mỹ phẩm\"_\n\n"
            "Gõ mô tả hoặc nhấn bỏ qua\\."
        ),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )
    context.user_data[PATTERN_DESC_FLAG] = True


async def step_pattern_desc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle patdesc_skip callback."""
    if not context.user_data.get(PATTERN_DESC_FLAG):
        return
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    if query.data == "patdesc_skip":
        context.user_data[PATTERN_DESC_FLAG] = False
        await query.edit_message_text(
            "⏭ *Bỏ qua mô tả — bot sẽ tự tạo pattern phù hợp nhất\\.*",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        # Launch pattern generation
        asyncio.create_task(_run_pattern_generation(context, chat_id))
        return


async def step_pattern_desc_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text pattern description when PATTERN_DESC_FLAG is set."""
    if not context.user_data.get(PATTERN_DESC_FLAG):
        return

    text = update.message.text.strip()
    if not text:
        return

    chat_id = update.effective_chat.id
    context.user_data[PATTERN_DESC_FLAG] = False

    # Store description
    brief = get_brief(context)
    brief.pattern_description = text

    await update.message.reply_text(
        f"✅ Đã ghi nhận mô tả\\: _\"{escape_md(text[:80])}\"_\n\n"
        f"🔲 Đang tạo hoạ tiết\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    asyncio.create_task(_run_pattern_generation(context, chat_id))


async def _run_pattern_generation(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    refinement_feedback: Optional[str] = None,
) -> None:
    """Generate pattern using refs + description + styleguide matching."""
    import traceback as _tb
    try:
        await _run_pattern_generation_inner(context, chat_id, refinement_feedback)
    except Exception as _top_err:
        logger.error("_run_pattern_generation crashed", exc_info=True)
        tb_lines = _tb.format_exception(type(_top_err), _top_err, _top_err.__traceback__)
        tb_last = "".join(tb_lines[-3:])[:400]
        err_type = type(_top_err).__name__
        err_msg = str(_top_err)[:200]
        debug_text = (
            f"❌ *Lỗi tạo pattern* \\(`{escape_md(err_type)}`\\)\n\n"
            f"`{escape_md(err_msg)}`\n\n"
            f"_Traceback \\(last 3 frames\\):_\n```\n{escape_md(tb_last)}\n```"
        )
        try:
            await context.bot.send_message(chat_id=chat_id, text=debug_text, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Pattern lỗi: {err_type}: {err_msg}\n\nGõ /cancel rồi /start để thử lại.",
            )


async def _run_pattern_generation_inner(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    refinement_feedback: Optional[str] = None,
) -> None:
    """Inner implementation of pattern generation (called by _run_pattern_generation)."""
    chosen_direction = context.user_data.get(CHOSEN_DIR_KEY)
    output_dir = Path(context.user_data.get(OUTPUT_DIR_KEY, "outputs/bot_unknown"))
    brief_dir_str = context.user_data.get(TEMP_DIR_KEY)
    brief_dir = Path(brief_dir_str) if brief_dir_str else None
    api_key = os.environ.get("GEMINI_API_KEY", "")
    brief = get_brief(context)

    logger.info(f"[pattern] starting generation — chat={chat_id} direction={getattr(chosen_direction, 'option_number', '?')} feedback={refinement_feedback!r}")

    # ── Recover brief_dir if missing or deleted ────────────────────────────
    if not brief_dir or not brief_dir.exists():
        if brief and brief.brand_name:
            brief_dir = brief.write_to_temp_dir()
            context.user_data[TEMP_DIR_KEY] = str(brief_dir)
            logger.info(f"Recovered brief_dir for pattern phase → {brief_dir}")

    if not brief_dir or not brief_dir.exists():
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Không tìm thấy brief\\_dir — thử lại từ đầu \\(/cancel → /start\\)\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    if not chosen_direction:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Chưa có direction được chọn — thử lại từ đầu \\(/cancel → /start\\)\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    pattern_refs = [Path(p) for p in context.user_data.get(PATTERN_REFS_KEY, []) if Path(p).exists()]
    description = brief.pattern_description or None
    palette_colors = context.user_data.get(ENRICHED_COLORS_KEY)

    logger.info(f"[pattern] refs={len(pattern_refs)} desc={description!r} palette={bool(palette_colors)}")

    progress_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🔲 *Đang render hoạ tiết\\.\\.\\.*",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    runner = PipelineRunner(api_key=api_key)

    def on_progress(msg: str) -> None:
        asyncio.create_task(safe_edit(context, chat_id, progress_msg.message_id, msg))

    result = await runner.run_pattern_phase(
        direction=chosen_direction,
        output_dir=output_dir,
        brief_dir=brief_dir,
        on_progress=on_progress,
        pattern_refs=pattern_refs or None,
        description=description,
        palette_colors=palette_colors,
        refinement_feedback=refinement_feedback,
    )

    logger.info(f"[pattern] run_pattern_phase done — success={result.success} path={result.pattern_path}")

    if not result.success:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Pattern thất bại\\:\n```\n{escape_md(result.error[:400])}\n```",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # Store pattern path
    context.user_data["pattern_path"] = str(result.pattern_path) if result.pattern_path else None

    # Send pattern
    if result.pattern_path and result.pattern_path.exists():
        await safe_edit(context, chat_id, progress_msg.message_id, "✅ *Hoạ tiết hoàn thành\\!*")
        try:
            await context.bot.send_document(
                chat_id=chat_id,
                document=result.pattern_path.read_bytes(),
                filename=result.pattern_path.name,
            )
        except Exception as e:
            logger.warning(f"Pattern send failed: {e}")
    else:
        logger.warning(f"[pattern] pattern_path missing or does not exist: {result.pattern_path}")
        await safe_edit(context, chat_id, progress_msg.message_id, "⚠️ *Hoạ tiết không có ảnh — sẽ hiển thị placeholder\\.*")

    # Pattern HITL keyboard
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Chốt hoạ tiết", callback_data="pattern_accept")],
        [InlineKeyboardButton("✏️ Chỉnh sửa", callback_data="pattern_refine")],
        [InlineKeyboardButton("🔄 Tạo lại", callback_data="pattern_reroll")],
    ])
    await context.bot.send_message(
        chat_id=chat_id,
        text="👆 *Bạn muốn giữ hoạ tiết này hay chỉnh sửa?*",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )
    context.user_data[PATTERN_REVIEW_FLAG] = True


# ── Pattern HITL handlers ─────────────────────────────────────────────────────

async def step_pattern_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pattern_accept / pattern_refine / pattern_reroll callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id

    if data == "pattern_accept":
        context.user_data[PATTERN_REVIEW_FLAG] = False
        await query.edit_message_text(
            "✅ *Hoạ tiết đã được chốt\\!*\n\n🧩 Đang composite mockups\\.\\.\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        # Move to mockup + ZIP phase
        asyncio.create_task(_run_mockup_and_zip_phase(context, chat_id))
        return

    if data == "pattern_refine":
        context.user_data[PATTERN_REVIEW_FLAG] = True
        context.user_data["pattern_refine_mode"] = True
        await query.edit_message_text(
            "✏️ Mô tả điều chỉnh hoạ tiết \\(vd: _\"thêm chi tiết\"_, _\"đơn giản hơn\"_, _\"đậm màu hơn\"_\\)\\:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    if data == "pattern_reroll":
        context.user_data[PATTERN_REVIEW_FLAG] = False
        await query.edit_message_text(
            "🔄 *Đang tạo lại hoạ tiết\\.\\.\\.*",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        asyncio.create_task(_run_pattern_generation(context, chat_id, refinement_feedback=None))
        return


async def step_pattern_review_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text pattern refinement when pattern_refine_mode is set."""
    if not context.user_data.get(PATTERN_REVIEW_FLAG):
        return
    # Only process text if user clicked "✏️ Chỉnh sửa" (pattern_refine_mode)
    if not context.user_data.get("pattern_refine_mode"):
        return

    text = update.message.text.strip()
    if not text:
        return

    chat_id = update.effective_chat.id
    context.user_data[PATTERN_REVIEW_FLAG] = False
    context.user_data.pop("pattern_refine_mode", None)

    await update.message.reply_text(
        f"🔄 *Đang tạo lại hoạ tiết theo feedback\\.\\.\\.*\n\n"
        f"_\"{escape_md(text[:100])}\"_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    asyncio.create_task(_run_pattern_generation(context, chat_id, refinement_feedback=text))


# ── Mockup + ZIP export phase ─────────────────────────────────────────────────

async def _run_mockup_and_zip_phase(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    """
    Final phase: await background mockup task (fired at logo lock),
    send results, then export ZIP.

    Mockups were started in parallel with palette + pattern HITL phases.
    By the time user finishes reviewing palette + pattern, mockups should
    already be done (or nearly done).
    """
    loop = asyncio.get_event_loop()
    chosen_direction = context.user_data.get(CHOSEN_DIR_KEY)
    output_dir = Path(context.user_data.get(OUTPUT_DIR_KEY, "outputs/bot_unknown"))
    brief_dir_str = context.user_data.get(TEMP_DIR_KEY)
    brief_dir = Path(brief_dir_str) if brief_dir_str else None
    api_key = os.environ.get("GEMINI_API_KEY", "")
    brief = get_brief(context)
    all_assets = context.user_data.get(ALL_ASSETS_KEY, {})
    chosen_num = getattr(chosen_direction, "option_number", 1) if chosen_direction else 1
    chosen_assets = all_assets.get(chosen_num)

    direction_name = escape_md(getattr(chosen_direction, "direction_name", ""))

    # Patch chosen_assets with locked palette + pattern from HITL
    if chosen_assets:
        enriched_colors = context.user_data.get(ENRICHED_COLORS_KEY)
        if enriched_colors:
            chosen_assets.enriched_colors = enriched_colors
        palette_png = context.user_data.get("palette_png")
        if palette_png and Path(palette_png).exists():
            chosen_assets.palette_png = Path(palette_png)
        shades_png = context.user_data.get("shades_png")
        if shades_png and Path(shades_png).exists():
            chosen_assets.shades_png = Path(shades_png)
        pattern_path = context.user_data.get("pattern_path")
        if pattern_path and Path(pattern_path).exists():
            chosen_assets.pattern = Path(pattern_path)
        # Patch logo variants from HITL
        logo_variants = context.user_data.get("logo_variant_paths", {})
        for attr in ("logo_white", "logo_black", "logo_transparent"):
            p = logo_variants.get(attr)
            if p and Path(p).exists():
                setattr(chosen_assets, attr, Path(p))

    # ── Mockups — await background task or run fresh if needed ────────────────
    mockup_paths: List[Path] = []
    mockup_task = context.user_data.pop("mockup_background_task", None)

    if mockup_task and not mockup_task.done():
        # Background task still running — show progress and wait
        await context.bot.send_message(
            chat_id=chat_id,
            text="🧩 *Mockups* — đang hoàn tất \\(đã chạy song song từ lúc chốt logo\\)\\.\\.\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        try:
            mockup_paths = await mockup_task
        except Exception as e:
            logger.warning(f"Background mockup task failed: {e}")

    elif mockup_task and mockup_task.done():
        # Background task already finished — grab results instantly
        try:
            mockup_paths = mockup_task.result()
            logger.info(f"Mockup background task was already done: {len(mockup_paths)} mockups")
        except Exception as e:
            logger.warning(f"Background mockup task had error: {e}")

    else:
        # No background task (edge case: session restored, etc.) — run fresh parallel
        logger.info("No background mockup task found — running mockups now (parallel)")
        from src.mockup_compositor import get_processed_mockup_files, composite_single_mockup

        processed_files = get_processed_mockup_files()
        if processed_files and chosen_assets:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🧩 *Mockups* — đang composite {len(processed_files)} ảnh\\.\\.\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            mockup_dir = output_dir / "mockups"
            mockup_dir.mkdir(parents=True, exist_ok=True)

            async def _do_one_fallback(pf):
                try:
                    return await loop.run_in_executor(
                        None,
                        lambda: composite_single_mockup(
                            processed_file=pf,
                            assets=chosen_assets,
                            api_key=api_key,
                            mockup_dir=mockup_dir,
                        ),
                    )
                except Exception as e:
                    logger.warning(f"Mockup composite failed {pf.name}: {e}")
                    return None

            results = await asyncio.gather(*[_do_one_fallback(pf) for pf in processed_files])
            for composited in results:
                if composited and composited.exists():
                    mockup_paths.append(composited)

    # ── Send mockup results to user ──────────────────────────────────────────
    if mockup_paths:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🧩 *{len(mockup_paths)} mockups hoàn thành\\!*",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        for mp in mockup_paths:
            try:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=mp.read_bytes(),
                    filename=mp.name,
                    caption=f"🖼 Mockup: {mp.stem}",
                )
            except Exception as e:
                logger.warning(f"Mockup send failed {mp.name}: {e}")
    else:
        logger.info("No mockup results to send")

    # ── ZIP export ────────────────────────────────────────────────────────────
    try:
        from src.zip_exporter import create_brand_identity_zip

        logo_paths_for_zip = {}
        if chosen_assets:
            for attr in ("logo", "logo_white", "logo_black", "logo_transparent"):
                p = getattr(chosen_assets, attr, None)
                if p and Path(p).exists():
                    logo_paths_for_zip[attr] = Path(p)

        palette_png_path = context.user_data.get("palette_png")
        shades_png_path = context.user_data.get("shades_png")
        pattern_path = context.user_data.get("pattern_path")
        svg_path_str = context.user_data.get("logo_svg_path")
        svg_path = Path(svg_path_str) if svg_path_str and Path(svg_path_str).exists() else None

        zip_path = await loop.run_in_executor(
            None,
            lambda: create_brand_identity_zip(
                brand_name=brief.brand_name,
                output_dir=output_dir,
                logo_paths=logo_paths_for_zip or None,
                palette_png=Path(palette_png_path) if palette_png_path else None,
                shades_png=Path(shades_png_path) if shades_png_path else None,
                pattern_path=Path(pattern_path) if pattern_path else None,
                mockup_paths=mockup_paths or None,
                svg_path=svg_path,
            ),
        )

        if zip_path and zip_path.exists():
            await context.bot.send_document(
                chat_id=chat_id,
                document=zip_path.read_bytes(),
                filename=zip_path.name,
                caption=f"📦 Brand Identity Package — {brief.brand_name}",
            )
    except Exception as e:
        logger.warning(f"ZIP export failed: {e}")

    # ── Done! ─────────────────────────────────────────────────────────────────
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🎉 *{escape_md(brief.brand_name)}* — *{direction_name}* hoàn thành\\!\n\n"
            f"📦 Tất cả assets đã được đóng gói trong file ZIP\\.\n"
            f"Gõ /start để bắt đầu project mới\\."
        ),
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    if brief_dir:
        _cleanup(brief_dir)


def _cleanup(brief_dir: Path) -> None:
    try:
        shutil.rmtree(brief_dir, ignore_errors=True)
    except Exception:
        pass


# ── Error handler ─────────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    import traceback as _tb
    logger.error("Exception while handling update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        # Include exception type/message so it's visible without server log access
        err = context.error
        err_type = type(err).__name__ if err else "Unknown"
        err_msg  = str(err)[:200] if err else ""
        tb_lines = _tb.format_exception(type(err), err, err.__traceback__) if err else []
        tb_last  = "".join(tb_lines[-3:])[:400] if tb_lines else ""
        debug_text = (
            f"⚠️ *Lỗi kỹ thuật* \\(`{escape_md(err_type)}`\\)\n\n"
            f"`{escape_md(err_msg)}`\n\n"
            f"_Traceback \\(last 3 frames\\):_\n```\n{escape_md(tb_last)}\n```"
        )
        try:
            await update.effective_message.reply_text(
                debug_text,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            # Fallback to plain text if debug_text itself has formatting issues
            await update.effective_message.reply_text(
                f"⚠️ Lỗi: {err_type}: {err_msg}\n\nGõ /cancel rồi /start để thử lại."
            )


# ── App builder ───────────────────────────────────────────────────────────────

def build_app(token: str) -> Application:
    app = Application.builder().token(token).build()

    # Conversation handler
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CommandHandler("new", cmd_start),
            CommandHandler("reset", cmd_reset),
        ],
        states={
            BRAND_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_brand_name)],
            PRODUCT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, step_product)],
            AUDIENCE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, step_audience)],
            TONE: [
                CallbackQueryHandler(step_tone_callback, pattern="^tone_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_tone_text),
            ],
            CORE_PROMISE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_core_promise),
                CommandHandler("skip", step_core_promise),
            ],
            COLOR_PREFERENCES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_color_preferences),
                CommandHandler("skip", step_color_preferences),
            ],
            GEOGRAPHY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_geography),
                CommandHandler("skip", step_geography),
            ],
            COMPETITORS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_competitors),
                CommandHandler("skip", step_competitors),
            ],

            LOGO_INSPIRATION: [
                MessageHandler(filters.PHOTO, step_logo_inspiration_image),
                MessageHandler(filters.Document.IMAGE, step_logo_inspiration_image),
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_logo_inspiration_text),
                CommandHandler("done", step_logo_inspiration_done),
                CommandHandler("skip", step_logo_inspiration_skip),
            ],
            PATTERN_INSPIRATION: [
                MessageHandler(filters.PHOTO, step_pattern_inspiration_image),
                MessageHandler(filters.Document.IMAGE, step_pattern_inspiration_image),
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_pattern_inspiration_text),
                CommandHandler("done", step_pattern_inspiration_done),
                CommandHandler("skip", step_pattern_inspiration_skip),
            ],
            KEYWORDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_keywords),
                CommandHandler("skip", step_keywords),
            ],
            CONFIRM:     [CallbackQueryHandler(step_confirm_callback, pattern="^confirm_")],
            REF_CHOICE:  [CallbackQueryHandler(step_ref_choice_callback, pattern="^ref_")],
            REF_UPLOAD:  [
                MessageHandler(filters.PHOTO, step_ref_upload_handler),
                MessageHandler(filters.Document.IMAGE, step_ref_upload_handler),
                CommandHandler("done", step_ref_upload_done),
                CommandHandler("skip", step_ref_upload_done),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("reset", cmd_reset),
        ],
        allow_reentry=True,
        conversation_timeout=1800,  # 30 min timeout
    )

    app.add_handler(conv)

    # ── Global HITL handlers (outside ConversationHandler) ────────────────────
    # These fire when pipeline phases set their respective *_FLAG.
    # They must be registered AFTER the ConversationHandler so they don't
    # interfere with brief collection. All in group=1.

    # Logo HITL
    app.add_handler(
        CallbackQueryHandler(step_logo_review_callback, pattern="^logo_"),
        group=1,
    )

    # Palette HITL
    app.add_handler(
        CallbackQueryHandler(step_palette_review_callback, pattern="^palette_"),
        group=1,
    )

    # Pattern ref selection
    app.add_handler(
        CallbackQueryHandler(step_pattern_ref_callback, pattern="^patref_"),
        group=1,
    )

    # Pattern description skip
    app.add_handler(
        CallbackQueryHandler(step_pattern_desc_callback, pattern="^patdesc_"),
        group=1,
    )

    # Pattern review
    app.add_handler(
        CallbackQueryHandler(step_pattern_review_callback, pattern="^pattern_"),
        group=1,
    )

    # Global text handler — dispatches to whichever HITL flag is active
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _global_hitl_text_handler),
        group=1,
    )

    # Global image handler for pattern ref uploads
    app.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.IMAGE, _global_hitl_image_handler),
        group=1,
    )

    # Global /done and /skip commands for pattern ref phase
    app.add_handler(
        CommandHandler("done", _global_hitl_done_handler),
        group=1,
    )
    app.add_handler(
        CommandHandler("skip", _global_hitl_done_handler),
        group=1,
    )

    app.add_error_handler(error_handler)
    return app


# ── Global HITL dispatcher handlers ──────────────────────────────────────────

async def _global_hitl_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatch text messages to the appropriate HITL text handler based on active flags."""
    if context.user_data.get(LOGO_REVIEW_FLAG):
        await step_logo_review_text(update, context)
    elif context.user_data.get(PALETTE_REVIEW_FLAG):
        await step_palette_review_text(update, context)
    elif context.user_data.get(PATTERN_DESC_FLAG):
        await step_pattern_desc_text(update, context)
    elif context.user_data.get(PATTERN_REVIEW_FLAG):
        await step_pattern_review_text(update, context)
    # else: ignore — not in any HITL mode


async def _global_hitl_image_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatch image uploads to pattern ref handler if active."""
    if context.user_data.get(PATTERN_REF_FLAG):
        await step_pattern_ref_image(update, context)


async def _global_hitl_done_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatch /done and /skip commands to pattern ref handler if active."""
    if context.user_data.get(PATTERN_REF_FLAG):
        await step_pattern_ref_done(update, context)
