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
from typing import Optional

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
LOGO_REVIEW_FLAG = "awaiting_logo_review"

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
    context.user_data.pop(TEMP_DIR_KEY, None)
    context.user_data.pop(TONE_CUSTOM_KEY, None)


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
        kw_set = {w.lower() for w in kw + product.split() + audience.split() + tone.split() if len(w) > 2}

        # Explicit keyword → industry folder mapping for better scoring
        INDUSTRY_MAP: dict = {
            "industry_food_beverage":    ["coffee", "cafe", "cafе", "drink", "beverage", "tea",
                                          "beer", "wine", "food", "restaurant", "bakery", "juice",
                                          "milk", "water", "snack", "bar", "brew", "roast", "latte"],
            "industry_fashion_beauty":   ["fashion", "beauty", "clothing", "apparel", "cosmetic",
                                          "makeup", "skincare", "hair", "luxury", "style", "wear",
                                          "shoe", "bag", "jewelry", "perfume", "fragrance"],
            "industry_finance_crypto":   ["finance", "fintech", "crypto", "bank", "invest", "fund",
                                          "insurance", "payment", "wallet", "trading", "money"],
            "industry_healthcare_wellness": ["health", "wellness", "medical", "pharma", "clinic",
                                             "fitness", "yoga", "sport", "gym", "supplement", "care"],
            "industry_technology_saas":  ["tech", "software", "saas", "app", "digital", "ai",
                                          "cloud", "data", "platform", "startup", "code", "developer"],
            "industry_education_edtech": ["education", "learn", "school", "course", "training",
                                          "university", "academy", "edtech", "tutor", "study"],
            "industry_media_gaming":     ["media", "gaming", "game", "entertainment", "music",
                                          "video", "stream", "podcast", "creative", "art", "studio"],
            "industry_retail_ecommerce": ["retail", "shop", "store", "ecommerce", "brand",
                                          "product", "market", "sell", "commerce"],
            "industry_real_estate":      ["real estate", "property", "home", "house", "architect",
                                          "interior", "construction", "living", "space"],
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
                    media=open(p, "rb"),
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
        # Also prepend to moodboard_images so Director gets them as visual context
        existing = list(getattr(brief, "moodboard_images", []) or [])
        for p in reversed(chosen_paths):
            if p not in existing:
                existing.insert(0, p)
        brief.moodboard_images = existing
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
    existing = list(getattr(brief, "moodboard_images", []) or [])
    for p in reversed(chosen_paths):
        if p not in existing:
            existing.insert(0, p)
    brief.moodboard_images = existing

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

    # confirm_go → show reference preview first
    await query.edit_message_text("🔍 Đang tìm visual references\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
    return await step_ref_choice_show(update, context)


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
                    media=open(assets.logo, "rb"),
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

        await query.edit_message_text(
            f"✅ *Chọn hướng {chosen_num}\\: {escape_md(chosen_direction.direction_name)}*\n\n"
            f"⏳ Đang gen palette \\+ pattern \\+ mockups\\.\\.\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

        output_dir = Path(context.user_data.get(OUTPUT_DIR_KEY, "outputs/bot_unknown"))
        brief_dir_str = context.user_data.get(TEMP_DIR_KEY)
        brief_dir = Path(brief_dir_str) if brief_dir_str else None
        api_key = os.environ.get("GEMINI_API_KEY", "")
        brief = get_brief(context)

        # Launch Phase 2 as a background task
        asyncio.create_task(
            _run_pipeline_phase2(
                context=context,
                chat_id=chat_id,
                chosen_direction=chosen_direction,
                output_dir=output_dir,
                brief_dir=brief_dir,
                brief=brief,
                api_key=api_key,
                directions_output=directions_output,
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

    if not brief_dir or not brief_dir.exists():
        await update.message.reply_text(
            "❌ Session đã hết hạn\\. Gõ /start để bắt đầu lại\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        context.user_data[LOGO_REVIEW_FLAG] = False
        return

    # Clear refine mode flag
    context.user_data.pop("logo_refine_mode", None)
    context.user_data[LOGO_REVIEW_FLAG] = False

    progress_msg = await update.message.reply_text(
        f"🔄 *Đang tái tạo logos theo feedback\\.\\.\\.*\n\n"
        f"_\"{escape_md(text[:100])}_\"",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    asyncio.create_task(
        _run_pipeline_phase1(
            context=context,
            chat_id=chat_id,
            progress_msg_id=progress_msg.message_id,
            brief=brief,
            brief_dir=brief_dir,
            api_key=api_key,
            refinement_feedback=text,
        )
    )


# ── Pipeline Phase 2: progressive delivery ────────────────────────────────────

async def _run_pipeline_phase2(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    chosen_direction: object,
    output_dir: Path,
    brief_dir: Optional[Path],
    brief: ConversationBrief,
    api_key: str,
    directions_output: object,
) -> None:
    """
    Phase 2: generate base assets then composite mockups.
    Each step sends results to Telegram immediately when ready — no waiting for everything.

    Order of delivery:
      1. Logo variants (white / black / transparent) → send immediately
      2. Background → send immediately
      3. Color palette + shades → send immediately
      4. Pattern → send immediately
      5. Each mockup composited → send immediately
    """
    loop = asyncio.get_event_loop()
    direction_name = escape_md(getattr(chosen_direction, "direction_name", ""))

    progress_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏳ *Phase 2 — {direction_name}*\n\n🖌 Đang render logo variants, background, palette, pattern\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    progress_msg_id = progress_msg.message_id

    # ── Step 1: Generate base assets in thread ────────────────────────────────
    runner = PipelineRunner(api_key=api_key)
    def on_progress(msg: str) -> None:
        asyncio.create_task(safe_edit(context, chat_id, progress_msg_id, msg))

    result = await runner.run_assets_phase(
        direction=chosen_direction,
        output_dir=output_dir,
        brief_dir=brief_dir,
        on_progress=on_progress,
    )

    if not result.success:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Phase 2 thất bại\\:\n```\n{escape_md(result.error[:500])}\n```",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        if brief_dir:
            _cleanup(brief_dir)
        return

    assets = result.assets
    elapsed = result.elapsed_seconds
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)
    await safe_edit(
        context, chat_id, progress_msg_id,
        f"✅ *Base assets xong\\!* {mins}m {secs}s — đang gửi\\.\\.\\."
    )

    # ── Step 2: Send logo variants immediately ────────────────────────────────
    from telegram import InputMediaPhoto
    logo_variants = []
    for attr, label in [
        ("logo",             "Logo chính"),
        ("logo_white",       "Logo trắng"),
        ("logo_black",       "Logo đen"),
        ("logo_transparent", "Logo transparent"),
    ]:
        p = getattr(assets, attr, None) if assets else None
        if p and Path(p).exists() and Path(p).stat().st_size > 100:
            logo_variants.append((Path(p), label))

    if logo_variants:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔤 *Logo versions*\\:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        media = []
        for p, label in logo_variants:
            try:
                media.append(InputMediaPhoto(media=open(p, "rb"), caption=label))
            except Exception:
                pass
        if media:
            try:
                await context.bot.send_media_group(chat_id=chat_id, media=media)
            except Exception:
                for p, label in logo_variants:
                    try:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=open(p, "rb"),
                            filename=p.name,
                            caption=label,
                        )
                    except Exception:
                        pass

    # ── Step 3: Send background ───────────────────────────────────────────────
    bg = getattr(assets, "background", None) if assets else None
    if bg and Path(bg).exists():
        await context.bot.send_message(
            chat_id=chat_id, text="🌄 *Background*\\:", parse_mode=ParseMode.MARKDOWN_V2
        )
        try:
            await context.bot.send_document(
                chat_id=chat_id, document=open(bg, "rb"), filename=Path(bg).name
            )
        except Exception as e:
            logger.warning(f"Background send failed: {e}")

    # ── Step 4: Send palette + shades ─────────────────────────────────────────
    palette_png = result.palette_png or (getattr(assets, "palette_png", None) if assets else None)
    shades_png  = getattr(assets, "shades_png", None) if assets else None

    if palette_png and Path(palette_png).exists():
        await context.bot.send_message(
            chat_id=chat_id, text="🎨 *Color Palette*\\:", parse_mode=ParseMode.MARKDOWN_V2
        )
        try:
            await context.bot.send_document(
                chat_id=chat_id,
                document=open(palette_png, "rb"),
                filename=Path(palette_png).name,
            )
        except Exception as e:
            logger.warning(f"Palette send failed: {e}")

    if shades_png and Path(shades_png).exists():
        try:
            await context.bot.send_document(
                chat_id=chat_id,
                document=open(shades_png, "rb"),
                filename=Path(shades_png).name,
                caption="🌈 Shade scales",
            )
        except Exception as e:
            logger.warning(f"Shades send failed: {e}")

    # ── Step 5: Send pattern ──────────────────────────────────────────────────
    pattern = getattr(assets, "pattern", None) if assets else None
    if pattern and Path(pattern).exists():
        await context.bot.send_message(
            chat_id=chat_id, text="🔲 *Pattern tile*\\:", parse_mode=ParseMode.MARKDOWN_V2
        )
        try:
            await context.bot.send_document(
                chat_id=chat_id,
                document=open(pattern, "rb"),
                filename=Path(pattern).name,
            )
        except Exception as e:
            logger.warning(f"Pattern send failed: {e}")

    # ── Step 6: Mockups — composite each one and send immediately ─────────────
    from src.mockup_compositor import get_processed_mockup_files, composite_single_mockup

    processed_files = get_processed_mockup_files()
    if processed_files and assets:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🧩 *Mockups* — đang composite {len(processed_files)} ảnh\\.\\.\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        mockup_dir = (
            Path(assets.background).parent / "mockups"
            if assets.background and Path(assets.background).parent.exists()
            else output_dir / "mockups"
        )
        mockup_count = 0
        for pf in processed_files:
            try:
                composited = await loop.run_in_executor(
                    None,
                    lambda pf=pf: composite_single_mockup(
                        processed_file=pf,
                        assets=assets,
                        api_key=api_key,
                        mockup_dir=mockup_dir,
                    ),
                )
                if composited and composited.exists():
                    try:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=open(composited, "rb"),
                            filename=composited.name,
                            caption=f"🖼 Mockup: {pf.stem}",
                        )
                        mockup_count += 1
                    except Exception as e:
                        logger.warning(f"Mockup send failed {pf.stem}: {e}")
            except Exception as e:
                logger.warning(f"Mockup composite failed {pf.name}: {e}")
    else:
        logger.info("No processed mockup files found — skipping mockup step")

    # ── Done! ─────────────────────────────────────────────────────────────────
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🎉 *{escape_md(brief.brand_name)}* — *{direction_name}* hoàn thành\\!\n\n"
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
    logger.error("Exception while handling update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Có lỗi xảy ra\\. Gõ /cancel rồi /start để thử lại\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
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
    # These fire when the pipeline has finished Phase 1 and set LOGO_REVIEW_FLAG.
    # They must be registered AFTER the ConversationHandler so they don't
    # interfere with brief collection.
    app.add_handler(
        CallbackQueryHandler(step_logo_review_callback, pattern="^logo_"),
        group=1,
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, step_logo_review_text),
        group=1,
    )

    app.add_error_handler(error_handler)
    return app
