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
    KEYWORDS,
    MODE_CHOICE,
    CONFIRM,
) = range(12)

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
    brief = get_brief(context)
    brief.brand_name = update.message.text.strip()
    await send_typing(update)
    await update.message.reply_text(
        f"Tuyệt\\! *{escape_md(brief.brand_name)}* — nghe hay đấy\\! 🎯\n\n"
        f"*Mô tả ngắn về sản phẩm/dịch vụ?*\n"
        f"_\\(ví dụ: SaaS platform giúp logistics track shipments bằng AI\\)_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return PRODUCT


# ── Step 2: Product ───────────────────────────────────────────────────────────

async def step_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    brief = get_brief(context)
    brief.product = update.message.text.strip()
    await send_typing(update)
    await update.message.reply_text(
        "*Target audience là ai?*\n"
        "_\\(ví dụ: Ops managers tại mid\\-market e\\-commerce companies, 50\\-500 nhân viên\\)_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return AUDIENCE


# ── Step 3: Audience ──────────────────────────────────────────────────────────

async def step_audience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    brief = get_brief(context)
    brief.audience = update.message.text.strip()
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
    """Handle custom tone text input."""
    brief = get_brief(context)
    if context.user_data.pop(TONE_CUSTOM_KEY, False):
        brief.tone = update.message.text.strip()
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
    brief = get_brief(context)
    text = update.message.text.strip()
    if text.lower() != "/skip":
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
    brief = get_brief(context)
    text = update.message.text.strip()
    if text.lower() != "/skip":
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
    brief = get_brief(context)
    text = update.message.text.strip()
    if text.lower() != "/skip" and text:
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
    brief = get_brief(context)
    text = update.message.text.strip()
    if text.lower() != "/skip":
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
    """Handle a single moodboard photo upload."""
    brief = get_brief(context)
    photo: PhotoSize = update.message.photo[-1]  # largest size

    # Download to temp dir
    tmp_dir = context.user_data.get(TEMP_DIR_KEY)
    if not tmp_dir:
        tmp_dir = Path(tempfile.mkdtemp(prefix="moodboard_"))
        context.user_data[TEMP_DIR_KEY] = tmp_dir
    else:
        tmp_dir = Path(tmp_dir)

    idx = len(brief.moodboard_image_paths) + 1
    img_path = tmp_dir / f"moodboard_{idx:02d}.jpg"
    file = await context.bot.get_file(photo.file_id)
    await file.download_to_drive(str(img_path))
    brief.moodboard_image_paths.append(img_path)

    await update.message.reply_text(
        f"📸 Đã nhận ảnh #{idx}\\! "
        f"Gửi tiếp hoặc gõ /done khi xong\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return MOODBOARD_IMAGES


async def step_moodboard_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User signals they're done uploading images."""
    brief = get_brief(context)
    img_count = len(brief.moodboard_image_paths)
    note = f"✅ Nhận {img_count} ảnh\\!" if img_count else "⏭ Bỏ qua ảnh moodboard\\."
    await update.message.reply_text(
        f"{note}\n\n"
        "*Keywords thương hiệu?*\n"
        "_\\(optional — mỗi keyword 1 dòng hoặc cách nhau bằng dấu phẩy\\)_\n"
        "_ví dụ: minimal, trustworthy, precision_\n"
        "_/skip để bỏ qua_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return KEYWORDS


async def step_moodboard_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "⏭ Bỏ qua ảnh moodboard\\.\n\n"
        "*Keywords thương hiệu?*\n"
        "_\\(optional — mỗi keyword 1 dòng hoặc cách nhau bằng dấu phẩy\\)_\n"
        "_/skip để bỏ qua_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return KEYWORDS


# ── Step 10: Keywords ─────────────────────────────────────────────────────────

async def step_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    brief = get_brief(context)
    text = update.message.text.strip()
    if text.lower() != "/skip" and text:
        import re
        kws = re.split(r"[,\n]+", text)
        brief.keywords = [k.strip().lstrip("-• ") for k in kws if k.strip()]
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

    # ── Send images ───────────────────────────────────────────────────────────
    if result.image_files:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🖼 *Visual assets* \\({len(result.image_files)} files\\)\\:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

        # Group by direction and send in batches
        images_by_dir = result.get_images_by_direction()
        for dir_key, imgs in images_by_dir.items():
            # Send as media group (max 10 per group)
            for chunk_start in range(0, len(imgs), 9):
                chunk = imgs[chunk_start:chunk_start + 9]
                media = []
                from telegram import InputMediaPhoto
                for img in chunk:
                    try:
                        with open(img, "rb") as f:
                            media.append(InputMediaPhoto(media=f.read()))
                    except Exception:
                        pass
                if media:
                    try:
                        await context.bot.send_media_group(chat_id=chat_id, media=media)
                    except Exception:
                        # Fallback: send individually
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
                MessageHandler(filters.PHOTO, step_moodboard_image),
                CommandHandler("done", step_moodboard_done),
                CommandHandler("skip", step_moodboard_skip),
            ],
            KEYWORDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_keywords),
                CommandHandler("skip", step_keywords),
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
