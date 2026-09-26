"""
Kino bot — kod orqali kino saqlash va yuborish

Ishlash tartibi:
1. Admin kanaldan kinoni (video/animatsiya/hujjat) botga forward qiladi
   (yoki to'g'ridan-to'g'ri botga video yuboradi).
2. Admin o'sha xabarga REPLY qilib, kino kodini yozadi (masalan: "12345").
   -> Bot shu kodni video bilan bog'lab bazaga saqlaydi.
3. Oddiy foydalanuvchi botga kodni (masalan "12345") yozib yuborsa,
   bot mos kinoni jo'natadi.

O'rnatish:
    pip install aiogram --break-system-packages

Ishga tushirish:
    export BOT_TOKEN="123456:ABC-your-token"
    export ADMIN_IDS="123456789,987654321"   # kod saqlashga ruxsati bor adminlar
    python3 kino_bot.py
"""

import asyncio
import logging
import os
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()
}
DB_PATH = os.environ.get("DB_PATH", "movies.db")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ---------- Baza ----------

def db_init():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS movies (
            code TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            file_type TEXT NOT NULL,
            caption TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def save_movie(code: str, file_id: str, file_type: str, caption: str | None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO movies (code, file_id, file_type, caption) VALUES (?, ?, ?, ?)",
        (code, file_id, file_type, caption),
    )
    conn.commit()
    conn.close()


def get_movie(code: str):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT file_id, file_type, caption FROM movies WHERE code = ?", (code,)
    ).fetchone()
    conn.close()
    return row


# ---------- Yordamchi ----------

def extract_media(message: Message):
    """Xabardan (video/animatsiya/hujjat) file_id va turini ajratib oladi."""
    if message.video:
        return message.video.file_id, "video"
    if message.animation:
        return message.animation.file_id, "animation"
    if message.document:
        return message.document.file_id, "document"
    return None, None


# ---------- Handlerlar ----------

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Salom! Kino kodini yuboring, men sizga kinoni jo'nataman.\n"
        "Masalan: 12345"
    )


@dp.message(F.reply_to_message, F.text)
async def admin_save_code(message: Message):
    """Admin video xabariga reply qilib kod yozganda -> saqlaydi."""
    if message.from_user is None or message.from_user.id not in ADMIN_IDS:
        return  # admin bo'lmasa, bu handlerni e'tiborsiz qoldiramiz

    file_id, file_type = extract_media(message.reply_to_message)
    if not file_id:
        await message.answer(
            "Bu xabarda video/kino topilmadi. Kino xabariga reply qiling."
        )
        return

    code = message.text.strip()
    caption = message.reply_to_message.caption
    save_movie(code, file_id, file_type, caption)
    await message.answer(f"✅ Kino \"{code}\" kodi bilan saqlandi.")


@dp.message(F.text)
async def user_get_movie(message: Message):
    """Oddiy foydalanuvchi kod yuborganda -> kino jo'natiladi."""
    code = message.text.strip()
    row = get_movie(code)
    if not row:
        await message.answer("❌ Bunday kodli kino topilmadi.")
        return

    file_id, file_type, caption = row
    if file_type == "video":
        await message.answer_video(file_id, caption=caption)
    elif file_type == "animation":
        await message.answer_animation(file_id, caption=caption)
    else:
        await message.answer_document(file_id, caption=caption)


# ---------- Ishga tushirish ----------

async def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN environment variable o'rnatilmagan.")
    db_init()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
