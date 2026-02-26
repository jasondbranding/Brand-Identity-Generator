from telegram.constants import ParseMode
import asyncio
from telegram import Bot
import os

token = os.environ.get("TELEGRAM_BOT_TOKEN", "...")
bot = Bot(token) 

async def main():
    try:
        msg = "🔄 *Đang tạo lại hoạ tiết theo feedback\\.\\.\\.*\n\n_\"thêm chi tiết_\""
        print("Testing message:", repr(msg))
        await bot.send_message(chat_id="79383611", text=msg, parse_mode=ParseMode.MARKDOWN_V2) # 79383611 is likely Sondao's chat ID or I'll just look it up.
    except Exception as e:
        print("EXCEPTION:", e)

asyncio.run(main())
