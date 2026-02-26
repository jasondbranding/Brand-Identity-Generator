import asyncio
import os
from telegram import Bot
from telegram.constants import ParseMode

async def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("No token")
        return
    bot = Bot(token)
    msg = "🔄 *Đang tạo lại hoạ tiết theo feedback\\.\\.\\.*\n\n_\"thêm chi tiết_\""
    print("Testing message:", repr(msg))
    
    # Try sending to 79383611 (Sơn's chat ID)
    try:
        await bot.send_message(chat_id="79383611", text=msg, parse_mode=ParseMode.MARKDOWN_V2)
        print("SUCCESS")
    except Exception as e:
        print("EXCEPTION:", repr(e))

if __name__ == "__main__":
    asyncio.run(main())
