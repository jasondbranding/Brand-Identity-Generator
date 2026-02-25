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
    MOODBOARD_NOTES,
    MOODBOARD_IMAGES,
    LOGO_INSPIRATION,
    PATTERN_INSPIRATION,
    KEYWORDS,
    COLOR_PREFERENCES,
    MODE_CHOICE,
    CONFIRM,
) = range(15)

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
}

BACK_PHRASES = {
    "back", "quay lại", "back lại", "trở lại", "bước trước",
    "quay lại bước trước", "sửa lại", "làm lại", "undo", "lùi lại",
    "đổi lại", "sửa bước trước", "back bước trước", "cho sửa lại",
    "muốn sửa lại", "sửa câu trước",
}


def detect_intent(text: str) -> Optional[str]:
    """Detect 'skip' or 'back' from natural language. Returns 'skip', 'back', or None."""
    normalized = text.strip().lower()
    if normalized in BACK_PHRASES or any(p in normalized for p in BACK_PHRASES):
        return "back"
    if normalized in SKIP_PHRASES:
        return "skip"
    # Fuzzy skip for short phrases containing skip keywords
    if len(normalized) < 25 and any(p in normalized for p in SKIP_PHRASES):
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


def _next_unfilled_state(brief: "ConversationBrief") -> int:
    """Return the next conversation state that still needs user input."""
    if not brief.product:
        return PRODUCT
    if not brief.audience:
        return AUDIENCE
    if not brief.tone:
        return TONE
    if not brief.core_promise:
        return CORE_PROMISE
    if not brief.geography:
        return GEOGRAPHY
    if not (brief.competitors_direct or brief.competitors_aspirational or brief.competitors_avoid):
        return COMPETITORS
    if not brief.moodboard_notes:
        return MOODBOARD_NOTES
    if not brief.keywords:
        return KEYWORDS
    if not brief.color_preferences:
        return COLOR_PREFERENCES
    return MODE_CHOICE


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
            "*Core promise / câu tagline định hướng?*\n"
            "_\\(optional — gõ /skip để bỏ qua\\)_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return CORE_PROMISE
    if state == GEOGRAPHY:
        await update.message.reply_text(
            "*Geography / thị trường mục tiêu?*\n"
            "_\\(optional — gõ /skip để bỏ qua\\)_",
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
            "_Hoặc chỉ liệt kê tên, hoặc /skip_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return COMPETITORS
    if state == MOODBOARD_NOTES:
        await update.message.reply_text(
            "*Moodboard notes?*\n"
            "_\\(optional — mô tả aesthetic bạn muốn, ví dụ: \"Minimal như Linear, accent màu navy\"\\)_\n"
            "_Gõ /skip để bỏ qua_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return MOODBOARD_NOTES
    if state == KEYWORDS:
        await update.message.reply_text(
            "*Keywords thương hiệu?*\n"
            "_\\(optional — mỗi keyword 1 dòng hoặc cách nhau bằng dấu phẩy\\)_\n"
            "_/skip để bỏ qua_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return KEYWORDS
    if state == COLOR_PREFERENCES:
        await update.message.reply_text(
            "🎨 *Màu sắc ưu tiên?*\n\n"
            "_\\(optional — gợi ý màu bạn muốn dùng cho brand\\)_\n"
            "_Ví dụ: \"Xanh navy \\+ vàng gold\", \"Tone earthy: nâu đất, be, rêu\", \"Tối giản đen trắng\"_\n\n"
            "_/skip để AI tự chọn palette_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return COLOR_PREFERENCES
    # MODE_CHOICE or anything beyond → show mode picker
    await update.message.reply_text(
        "*Chọn chế độ generate:*",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=MODE_KEYBOARD,
    )
    return MODE_CHOICE


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
            "*Core promise / câu tagline định hướng?*\n_Gõ /skip để bỏ qua_",
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
        MOODBOARD_NOTES: (
            "moodboard_notes",
            "*Moodboard notes?*\n_Gõ /skip để bỏ qua_",
            None,
        ),
        KEYWORDS: (
            "keywords",
            "*Keywords thương hiệu?*\n_\\(mỗi keyword 1 dòng hoặc cách nhau bằng dấu phẩy\\)_\n_Gõ /skip để bỏ qua_",
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
        if next_state == MODE_CHOICE:
            await update.message.reply_text(
                f"Tuyệt\\! *{escape_md(brief.brand_name)}* 🎯\n\n"
                f"{filled_summary}"
                f"*Chọn chế độ generate:*",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=MODE_KEYBOARD,
            )
            return MODE_CHOICE
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
        if next_state == MODE_CHOICE:
            await send_typing(update)
            await update.message.reply_text(
                f"✅ Đã điền {filled} fields\\. *Chọn chế độ generate:*",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=MODE_KEYBOARD,
            )
            return MODE_CHOICE
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
        if next_state == MODE_CHOICE:
            await send_typing(update)
            await update.message.reply_text(
                f"✅ Đã điền {filled} fields\\. *Chọn chế độ generate:*",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=MODE_KEYBOARD,
            )
            return MODE_CHOICE
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
        await query.edit_message_text(
            "⏭ Tone bỏ qua — AI sẽ tự chọn\\.\n\n"
            "*Core promise / câu tagline định hướng?*\n"
            "_\\(optional — ví dụ: \"You'll always know before your customers do\\.\"\\)_\n"
            "_Gõ /skip để bỏ qua_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return CORE_PROMISE

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
    await query.edit_message_text(
        f"✅ Tone: *{escape_md(label)}*\n\n"
        f"*Core promise / câu định hướng?*\n"
        f"_\\(optional — ví dụ: \"You'll always know before your customers do\\.\"\\)_\n"
        f"_Gõ /skip để bỏ qua_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return CORE_PROMISE


async def step_tone_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom tone text input or natural language intents."""
    intent = detect_intent(update.message.text or "")
    if intent == "back":
        return await handle_back(update, context)
    if intent == "skip":
        push_history(context, TONE)
        await update.message.reply_text(
            "⏭ Tone bỏ qua\\.\n\n"
            "*Core promise / câu tagline định hướng?*\n"
            "_Gõ /skip để bỏ qua_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return CORE_PROMISE
    brief = get_brief(context)
    text = update.message.text.strip()

    # Check for bulk input regardless of whether we're in custom-tone mode
    filled = _parse_bulk_fields(text, brief)
    if filled >= 2:
        context.user_data.pop(TONE_CUSTOM_KEY, None)
        next_state = _next_unfilled_state(brief)
        if next_state == MODE_CHOICE:
            await send_typing(update)
            await update.message.reply_text(
                f"✅ Đã điền {filled} fields\\. *Chọn chế độ generate:*",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=MODE_KEYBOARD,
            )
            return MODE_CHOICE
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Đã điền {filled} fields\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    if context.user_data.pop(TONE_CUSTOM_KEY, False):
        brief.tone = text
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Tone: _{escape_md(brief.tone)}_\n\n"
            f"*Core promise / câu định hướng?*\n"
            f"_\\(optional — gõ /skip để bỏ qua\\)_",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return CORE_PROMISE
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
        if next_state == MODE_CHOICE:
            await send_typing(update)
            await update.message.reply_text(
                f"✅ Đã điền {filled} fields\\. *Chọn chế độ generate:*",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=MODE_KEYBOARD,
            )
            return MODE_CHOICE
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Đã điền {filled} fields\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    if text.lower() != "/skip" and intent != "skip":
        brief.core_promise = text
    await send_typing(update)
    await update.message.reply_text(
        "*Geography / thị trường mục tiêu?*\n"
        "_\\(optional — ví dụ: \"Vietnam, SEA B2B\" hoặc \"Global English\\-speaking\"\\)_\n"
        "_Gõ /skip để bỏ qua_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return GEOGRAPHY


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
        if next_state == MODE_CHOICE:
            await send_typing(update)
            await update.message.reply_text(
                f"✅ Đã điền {filled} fields\\. *Chọn chế độ generate:*",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=MODE_KEYBOARD,
            )
            return MODE_CHOICE
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Đã điền {filled} fields\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    if text.lower() != "/skip" and intent != "skip":
        brief.geography = text
    await send_typing(update)
    await update.message.reply_text(
        "*Đối thủ cạnh tranh?*\n\n"
        "Bạn có thể nhập theo format:\n"
        "`Direct: CompanyA, CompanyB`\n"
        "`Aspirational: BrandX, BrandY`\n"
        "`Avoid: OldCorp`\n\n"
        "_Hoặc chỉ liệt kê tên, hoặc /skip_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return COMPETITORS


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
        if next_state == MODE_CHOICE:
            await send_typing(update)
            await update.message.reply_text(
                f"✅ Đã điền {filled} fields\\. *Chọn chế độ generate:*",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=MODE_KEYBOARD,
            )
            return MODE_CHOICE
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Đã điền {filled} fields\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    if text.lower() != "/skip" and intent != "skip" and text:
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
                break

    await send_typing(update)
    await update.message.reply_text(
        "*Moodboard notes?*\n"
        "_\\(optional — mô tả aesthetic bạn muốn, ví dụ: \"Minimal như Linear, accent màu navy\"\\)_\n"
        "_Gõ /skip để bỏ qua_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return MOODBOARD_NOTES


# ── Step 8: Moodboard Notes ───────────────────────────────────────────────────

async def step_moodboard_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    intent = detect_intent(update.message.text or "")
    if intent == "back":
        return await handle_back(update, context)
    brief = get_brief(context)
    push_history(context, MOODBOARD_NOTES)
    text = update.message.text.strip()

    # Check for bulk input (e.g. user pastes moodboard + keywords together)
    filled = _parse_bulk_fields(text, brief)
    if filled >= 2:
        next_state = _next_unfilled_state(brief)
        if next_state == MODE_CHOICE:
            await send_typing(update)
            await update.message.reply_text(
                f"✅ Đã điền {filled} fields\\. *Chọn chế độ generate:*",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=MODE_KEYBOARD,
            )
            return MODE_CHOICE
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Đã điền {filled} fields\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    if text.lower() != "/skip" and intent != "skip":
        brief.moodboard_notes = text
    await send_typing(update)
    await update.message.reply_text(
        "📸 *Muốn upload ảnh moodboard không?*\n\n"
        "Gửi ảnh trực tiếp \\(có thể gửi nhiều\\) — AI sẽ học từ visual references của bạn\\.\n\n"
        "_Khi xong, gõ /done_  \\|  _/skip để bỏ qua_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return MOODBOARD_IMAGES


# ── Step 9: Moodboard Images ──────────────────────────────────────────────────

async def step_moodboard_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle a general moodboard / aesthetic reference image."""
    brief = get_brief(context)
    idx = len(brief.moodboard_image_paths) + 1
    img_path = await _download_image(update, context, "moodboard", idx)
    if not img_path:
        return MOODBOARD_IMAGES
    brief.moodboard_image_paths.append(img_path)
    await update.message.reply_text(
        f"📸 Đã nhận ảnh \\#{idx}\\! Gửi tiếp hoặc gõ /done khi xong\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return MOODBOARD_IMAGES


async def step_moodboard_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User signals done uploading general moodboard images → ask for logo inspirations."""
    brief = get_brief(context)
    img_count = len(brief.moodboard_image_paths)
    note = f"✅ Nhận {img_count} ảnh moodboard\\!" if img_count else "⏭ Bỏ qua ảnh moodboard\\."
    await update.message.reply_text(
        f"{note}\n\n"
        "🔤 *Bạn có ảnh logo nào muốn tham khảo không?*\n"
        "_\\(logo của brand khác mà bạn thích về phong cách, font, biểu tượng\\.\\.\\.\\)_\n\n"
        "_Gửi ảnh trực tiếp \\(hoặc dạng file\\) — có thể gửi nhiều_\n"
        "_/done để tiếp tục \\| /skip để bỏ qua_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return LOGO_INSPIRATION


async def step_moodboard_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User skips general moodboard images → still ask for logo inspirations."""
    await update.message.reply_text(
        "⏭ Bỏ qua ảnh moodboard\\.\n\n"
        "🔤 *Bạn có ảnh logo nào muốn tham khảo không?*\n"
        "_\\(logo của brand khác mà bạn thích về phong cách, font, biểu tượng\\.\\.\\.\\)_\n\n"
        "_Gửi ảnh trực tiếp \\(hoặc dạng file\\) — có thể gửi nhiều_\n"
        "_/done để tiếp tục \\| /skip để bỏ qua_",
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
        f"🔤 Đã nhận logo ref \\#{idx}\\! Gửi tiếp hoặc /done khi xong\\.",
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
        "_/done để tiếp tục \\| /skip để bỏ qua_",
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
        "_/done để tiếp tục \\| /skip để bỏ qua_",
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
        f"🌿 Đã nhận pattern ref \\#{idx}\\! Gửi tiếp hoặc /done khi xong\\.",
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
        "*Keywords thương hiệu?*\n"
        "_\\(optional — mỗi keyword 1 dòng hoặc cách nhau bằng dấu phẩy\\)_\n"
        "_ví dụ: minimal, trustworthy, precision_\n"
        "_/skip để bỏ qua_",
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
        "*Keywords thương hiệu?*\n"
        "_\\(optional — mỗi keyword 1 dòng hoặc cách nhau bằng dấu phẩy\\)_\n"
        "_/skip để bỏ qua_",
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
        if next_state == MODE_CHOICE:
            await send_typing(update)
            await update.message.reply_text(
                f"✅ Đã điền {filled} fields\\. *Chọn chế độ generate:*",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=MODE_KEYBOARD,
            )
            return MODE_CHOICE
        await send_typing(update)
        await update.message.reply_text(
            f"✅ Đã điền {filled} fields\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return await _ask_for_state(update, context, next_state)

    if text.lower() != "/skip" and intent != "skip" and text:
        import re
        kws = re.split(r"[,\n]+", text)
        brief.keywords = [k.strip().lstrip("-• ") for k in kws if k.strip()]
    await send_typing(update)
    await update.message.reply_text(
        "🎨 *Màu sắc ưu tiên?*\n\n"
        "_\\(optional — gợi ý màu bạn muốn dùng cho brand\\)_\n"
        "_Ví dụ: \"Xanh navy \\+ vàng gold\", \"Tone earthy: nâu đất, be, rêu\", \"Tối giản đen trắng\"_\n\n"
        "_/skip để AI tự chọn palette_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return COLOR_PREFERENCES


# ── Step 10b: Color Preferences ───────────────────────────────────────────────

async def step_color_preferences(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    intent = detect_intent(update.message.text or "")
    if intent == "back":
        return await handle_back(update, context)
    brief = get_brief(context)
    push_history(context, COLOR_PREFERENCES)
    text = update.message.text.strip()

    if text.lower() != "/skip" and intent != "skip" and text:
        brief.color_preferences = text
    await send_typing(update)
    await update.message.reply_text(
        "*Chọn chế độ generate:*",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=MODE_KEYBOARD,
    )
    return MODE_CHOICE


# ── Step 11: Mode Choice ──────────────────────────────────────────────────────

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

    # confirm_go → start pipeline
    brief = get_brief(context)
    chat_id = update.effective_chat.id
    api_key = os.environ.get("GEMINI_API_KEY", "")

    if not api_key:
        await query.edit_message_text("❌ GEMINI_API_KEY chưa được set\\. Pipeline không thể chạy\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return ConversationHandler.END

    # Send progress message
    mode_label = "Full \\(4 directions\\)" if brief.mode == "full" else "Quick \\(2 directions\\)"
    progress_msg = await query.edit_message_text(
        f"⏳ *Đang khởi động pipeline\\.\\.\\.*\n\n"
        f"Mode: {mode_label}\n"
        f"Brand: *{escape_md(brief.brand_name)}*\n\n"
        f"_Quá trình mất 3–12 phút tùy mode\\._",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    context.user_data[MSG_ID_KEY] = progress_msg.message_id

    # Write brief to temp dir
    brief_dir = brief.write_to_temp_dir()
    context.user_data[TEMP_DIR_KEY] = str(brief_dir)

    # Kick off pipeline in background
    asyncio.create_task(
        _run_pipeline_and_respond(
            context=context,
            chat_id=chat_id,
            progress_msg_id=progress_msg.message_id,
            brief=brief,
            brief_dir=brief_dir,
            api_key=api_key,
        )
    )

    return ConversationHandler.END


# ── Pipeline execution + result delivery ──────────────────────────────────────

async def _run_pipeline_and_respond(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    progress_msg_id: int,
    brief: ConversationBrief,
    brief_dir: Path,
    api_key: str,
) -> None:
    """Run pipeline, send progress updates, deliver results."""

    def on_progress(msg: str) -> None:
        """Sync callback from pipeline thread → schedule async edit."""
        asyncio.run_coroutine_threadsafe(
            safe_edit(context, chat_id, progress_msg_id, msg),
            asyncio.get_event_loop(),
        )

    runner = PipelineRunner(api_key=api_key)
    result = await runner.run(
        brief_dir=brief_dir,
        mode=brief.mode,
        on_progress=on_progress,
        generate_images=True,
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

    # Update progress to done
    await safe_edit(
        context, chat_id, progress_msg_id,
        f"✅ *Done\\!* {mins}m {secs}s\n\nĐang gửi kết quả\\.\\.\\."
    )

    # ── Send text summary (directions.md) ─────────────────────────────────────
    if result.directions_md and result.directions_md.exists():
        await context.bot.send_document(
            chat_id=chat_id,
            document=open(result.directions_md, "rb"),
            filename=f"{brief.brand_name.lower()}_directions.md",
            caption="📄 Brand directions summary",
        )

    # ── Generate + send PDF ───────────────────────────────────────────────────
    try:
        from src.parser import parse_brief as _parse
        from src.director import generate_directions as _gen_dir

        # Re-load directions output from saved JSON if available
        json_path = result.output_dir / "directions.json"
        if json_path.exists():
            import json
            from src.director import BrandDirectionsOutput, BrandDirection
            data = json.loads(json_path.read_text())
            directions_output = BrandDirectionsOutput(
                directions=[BrandDirection(**d) for d in data.get("directions", [])]
            )
        else:
            directions_output = None

        if directions_output:
            pdf_path = generate_pdf_report(
                directions_output,
                result.output_dir,
                result.image_files,
                brand_name=brief.brand_name,
            )
            if pdf_path and pdf_path.exists():
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=open(pdf_path, "rb"),
                    filename=pdf_path.name,
                    caption=f"📊 {brief.brand_name} — Brand Identity Report",
                )
    except Exception as e:
        logger.warning(f"PDF generation failed: {e}")

    # ── Send stylescapes first (highest value output) ─────────────────────────
    if result.stylescape_paths:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🗂 *Stylescapes* \\({len(result.stylescape_paths)} directions\\)\\:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        for opt_num, ss_path in sorted(result.stylescape_paths.items()):
            if ss_path.exists():
                try:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=open(ss_path, "rb"),
                        filename=ss_path.name,
                        caption=f"Option {opt_num} stylescape",
                    )
                except Exception:
                    pass

    # ── Send palette strips ────────────────────────────────────────────────────
    if result.palette_pngs:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎨 *Color Palettes*\\:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        for p in result.palette_pngs:
            try:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=open(p, "rb"),
                    filename=p.name,
                )
            except Exception:
                pass

    # ── Send shade scales ──────────────────────────────────────────────────────
    if result.shades_pngs:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🌈 *Shade Scales \\(50→950\\)*\\:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        for p in result.shades_pngs:
            try:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=open(p, "rb"),
                    filename=p.name,
                )
            except Exception:
                pass

    # ── Send remaining image files (logos, backgrounds, patterns) ─────────────
    # Exclude already-sent files to avoid duplication
    sent_paths = (
        set(str(p) for p in result.stylescape_paths.values())
        | set(str(p) for p in result.palette_pngs)
        | set(str(p) for p in result.shades_pngs)
    )
    raw_imgs = [
        p for p in result.image_files
        if str(p) not in sent_paths
        and p.name not in {"background.png"}     # skip large bg images to save bandwidth
    ]
    if raw_imgs:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🖼 *Logos, Patterns \\& Assets* \\({len(raw_imgs)} files\\)\\:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        from telegram import InputMediaDocument
        for chunk_start in range(0, len(raw_imgs), 9):
            chunk = raw_imgs[chunk_start:chunk_start + 9]
            media = []
            for img in chunk:
                try:
                    with open(img, "rb") as f:
                        media.append(InputMediaDocument(media=f.read(), filename=img.name))
                except Exception:
                    pass
            if media:
                try:
                    await context.bot.send_media_group(chat_id=chat_id, media=media)
                except Exception:
                    for img in chunk:
                        try:
                            await context.bot.send_document(
                                chat_id=chat_id,
                                document=open(img, "rb"),
                                filename=img.name,
                            )
                        except Exception:
                            pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🎉 *{escape_md(brief.brand_name)}* brand identity hoàn thành\\!\n\n"
            f"Gõ /start để bắt đầu project mới\\."
        ),
        parse_mode=ParseMode.MARKDOWN_V2,
    )

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
            CORE_PROMISE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_core_promise),
                CommandHandler("skip", step_core_promise),
            ],
            GEOGRAPHY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_geography),
                CommandHandler("skip", step_geography),
            ],
            COMPETITORS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_competitors),
                CommandHandler("skip", step_competitors),
            ],
            MOODBOARD_NOTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_moodboard_notes),
                CommandHandler("skip", step_moodboard_notes),
            ],
            MOODBOARD_IMAGES: [
                # Accept compressed photos AND images sent as files
                MessageHandler(filters.PHOTO, step_moodboard_image),
                MessageHandler(filters.Document.IMAGE, step_moodboard_image),
                CommandHandler("done", step_moodboard_done),
                CommandHandler("skip", step_moodboard_skip),
            ],
            LOGO_INSPIRATION: [
                MessageHandler(filters.PHOTO, step_logo_inspiration_image),
                MessageHandler(filters.Document.IMAGE, step_logo_inspiration_image),
                CommandHandler("done", step_logo_inspiration_done),
                CommandHandler("skip", step_logo_inspiration_skip),
            ],
            PATTERN_INSPIRATION: [
                MessageHandler(filters.PHOTO, step_pattern_inspiration_image),
                MessageHandler(filters.Document.IMAGE, step_pattern_inspiration_image),
                CommandHandler("done", step_pattern_inspiration_done),
                CommandHandler("skip", step_pattern_inspiration_skip),
            ],
            KEYWORDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_keywords),
                CommandHandler("skip", step_keywords),
            ],
            COLOR_PREFERENCES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_color_preferences),
                CommandHandler("skip", step_color_preferences),
            ],
            MODE_CHOICE: [CallbackQueryHandler(step_mode_callback, pattern="^mode_")],
            CONFIRM:     [CallbackQueryHandler(step_confirm_callback, pattern="^confirm_")],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("reset", cmd_reset),
        ],
        allow_reentry=True,
        conversation_timeout=1800,  # 30 min timeout
    )

    app.add_handler(conv)
    app.add_error_handler(error_handler)
    return app
