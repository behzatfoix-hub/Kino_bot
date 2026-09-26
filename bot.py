"""
Kino bot — admin panel, kanaldan avtomatik olish, kinolar ro'yxati

IMKONIYATLAR
------------
1. Kanaldan avtomatik olish:
   Bot kanalga ADMIN qilib qo'shilsa, kanalga yangi video/kino
   joylanganda bot avtomatik uni ko'radi va adminlarga shaxsiy
   xabarda yuboradi — "Kod belgilash" tugmasi bilan.

2. Panel orqali qo'shish:
   /admin -> "➕ Kino qo'shish" -> video yuboriladi -> kod so'raladi
   -> saqlanadi.

3. Kinolar ro'yxati:
   /admin -> "📋 Kinolar ro'yxati" — sahifalab ko'rsatadi.

4. Kino o'chirish:
   /admin -> "🗑 Kino o'chirish" -> kod kiritiladi -> o'chiriladi.

5. Statistika:
   /admin -> "📊 Statistika" — jami kinolar soni.

6. Oddiy foydalanuvchi kodni yozsa -> kino jo'natiladi.

O'RNATISH
---------
    pip install aiogram --break-system-packages

ISHGA TUSHIRISH (environment variables)
----------------------------------------
    BOT_TOKEN   = BotFather'dan olingan token
    ADMIN_IDS   = "123456789,987654321"   (vergul bilan, bir nechta bo'lishi mumkin)
    CHANNEL_ID  = "-1001234567890"        (ixtiyoriy — kanaldan avtomatik olish uchun)

    python3 bot.py

CHANNEL_ID NI TOPISH
---------------------
    Botni kanalga ADMIN qilib qo'shing, keyin kanalga istalgan xabar
    yuboring va botga forward qiling — @userinfobot yoki @getidsbot
    orqali kanal ID'sini topishingiz mumkin (odatda -100 bilan boshlanadi).
"""

import asyncio
import logging
import os
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()
}
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip() or None
DB_PATH = os.environ.get("DB_PATH", "movies.db")
PAGE_SIZE = 10

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ---------- Holatlar (FSM) ----------

class AddMovie(StatesGroup):
    waiting_video = State()
    waiting_code = State()


class DeleteMovie(StatesGroup):
    waiting_code = State()


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


def delete_movie(code: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("DELETE FROM movies WHERE code = ?", (code,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def list_movies(offset: int, limit: int):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT code, file_type FROM movies ORDER BY code LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
    conn.close()
    return rows, total


# ---------- Yordamchi ----------

def is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


def extract_media(message: Message):
    if message.video:
        return message.video.file_id, "video"
    if message.animation:
        return message.animation.file_id, "animation"
    if message.document:
        return message.document.file_id, "document"
    return None, None


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Kino qo'shish", callback_data="panel_add")],
            [InlineKeyboardButton(text="📋 Kinolar ro'yxati", callback_data="panel_list:0")],
            [InlineKeyboardButton(text="🗑 Kino o'chirish", callback_data="panel_delete")],
            [InlineKeyboardButton(text="📊 Statistika", callback_data="panel_stats")],
        ]
    )


def list_keyboard(offset: int, total: int) -> InlineKeyboardMarkup:
    buttons = []
    nav = []
    if offset > 0:
        nav.append(
            InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"panel_list:{max(0, offset - PAGE_SIZE)}")
        )
    if offset + PAGE_SIZE < total:
        nav.append(
            InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"panel_list:{offset + PAGE_SIZE}")
        )
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🔙 Panelga qaytish", callback_data="panel_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Panelga qaytish", callback_data="panel_home")]]
    )


# ---------- Oddiy foydalanuvchi ----------

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🎬 Salom! Kino kodini yuboring, men sizga kinoni jo'nataman.\n"
        "Masalan: 12345"
    )


# ---------- Admin panel ----------

@dp.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    await message.answer("🔧 Admin panel:", reply_markup=admin_panel_keyboard())


@dp.callback_query(F.data == "panel_home")
async def panel_home(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text("🔧 Admin panel:", reply_markup=admin_panel_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "panel_stats")
async def panel_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    _, total = list_movies(0, 1)
    await callback.message.edit_text(
        f"📊 Statistika\n\nJami saqlangan kinolar: {total} ta",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("panel_list:"))
async def panel_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    offset = int(callback.data.split(":")[1])
    rows, total = list_movies(offset, PAGE_SIZE)
    if total == 0:
        text = "📋 Hozircha hech qanday kino saqlanmagan."
    else:
        lines = [f"{offset + i + 1}. {code}  ({ftype})" for i, (code, ftype) in enumerate(rows)]
        text = f"📋 Kinolar ro'yxati ({offset + 1}-{offset + len(rows)} / {total}):\n\n" + "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=list_keyboard(offset, total))
    await callback.answer()


@dp.callback_query(F.data == "panel_add")
async def panel_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AddMovie.waiting_video)
    await callback.message.edit_text(
        "🎬 Kino faylini (video) yuboring.",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.message(StateFilter(AddMovie.waiting_video))
async def add_movie_receive_video(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    file_id, file_type = extract_media(message)
    if not file_id:
        await message.answer("Bu video emas. Iltimos kino faylini yuboring.")
        return
    await state.update_data(file_id=file_id, file_type=file_type, caption=message.caption)
    await state.set_state(AddMovie.waiting_code)
    await message.answer("✏️ Endi shu kino uchun kod yuboring (masalan: 12345).")


@dp.message(StateFilter(AddMovie.waiting_code))
async def add_movie_receive_code(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    code = (message.text or "").strip()
    if not code:
        await message.answer("Iltimos, matn ko'rinishida kod yuboring.")
        return
    data = await state.get_data()
    save_movie(code, data["file_id"], data["file_type"], data.get("caption"))
    await state.clear()
    await message.answer(f"✅ Kino \"{code}\" kodi bilan saqlandi.", reply_markup=admin_panel_keyboard())


@dp.callback_query(F.data == "panel_delete")
async def panel_delete(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(DeleteMovie.waiting_code)
    await callback.message.edit_text(
        "🗑 O'chirmoqchi bo'lgan kino kodini yuboring.",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.message(StateFilter(DeleteMovie.waiting_code))
async def delete_movie_receive_code(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    code = (message.text or "").strip()
    await state.clear()
    if delete_movie(code):
        await message.answer(f"✅ \"{code}\" kodli kino o'chirildi.", reply_markup=admin_panel_keyboard())
    else:
        await message.answer(f"❌ \"{code}\" kodli kino topilmadi.", reply_markup=admin_panel_keyboard())


# ---------- Kanaldan avtomatik olish ----------

@dp.channel_post()
async def on_channel_post(message: Message):
    if CHANNEL_ID is None or str(message.chat.id) != CHANNEL_ID:
        return
    file_id, file_type = extract_media(message)
    if not file_id:
        return
    for admin_id in ADMIN_IDS:
        try:
            sent = await bot.forward_message(admin_id, message.chat.id, message.message_id)
            await bot.send_message(
                admin_id,
                "☝️ Kanalda yangi kino. Kod belgilaysizmi?",
                reply_to_message_id=sent.message_id,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(
                        text="✏️ Kod belgilash",
                        callback_data=f"setcode:{file_type}:{file_id}",
                    )]]
                ),
            )
        except Exception as e:
            logging.warning(f"Admin {admin_id} ga yuborib bo'lmadi: {e}")


@dp.callback_query(F.data.startswith("setcode:"))
async def setcode_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    _, file_type, file_id = callback.data.split(":", 2)
    await state.set_state(AddMovie.waiting_code)
    await state.update_data(file_id=file_id, file_type=file_type, caption=None)
    await callback.message.answer("✏️ Bu kino uchun kod yuboring (masalan: 12345).")
    await callback.answer()


# ---------- Admin: video + reply orqali kod (eski usul, hali ham ishlaydi) ----------

@dp.message(F.reply_to_message, F.text, StateFilter(None))
async def admin_save_code_by_reply(message: Message):
    if not is_admin(message.from_user.id if message.from_user else None):
        return
    file_id, file_type = extract_media(message.reply_to_message)
    if not file_id:
        return
    code = message.text.strip()
    caption = message.reply_to_message.caption
    save_movie(code, file_id, file_type, caption)
    await message.answer(f"✅ Kino \"{code}\" kodi bilan saqlandi.")


# ---------- Oddiy foydalanuvchi: kod yuborsa kino jo'natiladi ----------

@dp.message(F.text, StateFilter(None))
async def user_get_movie(message: Message):
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
