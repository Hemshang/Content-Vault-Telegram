import os
from dotenv import load_dotenv
import asyncio
import uuid
import re
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# ============================================================
# CONFIGURATION
# ============================================================
# Load variables from the .env file
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PRIVATE_CHANNEL_ID = int(os.getenv("PRIVATE_CHANNEL_ID"))
PUBLIC_CHANNEL_ID = int(os.getenv("PUBLIC_CHANNEL_ID"))
PUBLIC_CHANNEL_USERNAME = os.getenv("PUBLIC_CHANNEL_USERNAME")
ADMIN_ID = int(os.getenv("ADMIN_ID"))                

DELETE_DELAY = 300  # 5 minutes

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Memory strictly for handling uploads in progress
MEDIA_GROUPS = {}
PENDING_UPLOADS = {}

class QuickPostForm(StatesGroup):
    target_msg_ids = State() 
    title = State()
    language = State()
    imdb = State()
    ott = State()
    qualities_list = State()
    poster = State()

# ============================================================
# AUTO-DELETION HELPER
# ============================================================
async def delete_messages_after_delay(chat_id: int, message_ids: list[int], delay: int):
    await asyncio.sleep(delay)
    for msg_id in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except:
            pass

# ============================================================
# AUTOMATED UPLOAD LISTENER
# ============================================================
async def send_admin_notification(msg_ids: list):
    msg_ids.sort() # Ensure top-to-bottom order
    upload_id = str(uuid.uuid4())[:8]
    PENDING_UPLOADS[upload_id] = msg_ids  
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Create Public Post", callback_data=f"ap:{upload_id}")]
    ])
    
    text = (f"📥 **New Upload Detected!**\n\n"
            f"Files uploaded in this batch: **{len(msg_ids)}**\n\n"
            f"Tap below to publish:")
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=text, reply_markup=keyboard, parse_mode="Markdown")
    except Exception as e:
        print(f"Failed to PM admin: {e}")

@dp.channel_post()
async def auto_detect_private_upload(message: Message):
    if message.chat.id != PRIVATE_CHANNEL_ID:
        return

    # Handle albums/multiple files
    if message.media_group_id:
        mg_id = message.media_group_id
        if mg_id not in MEDIA_GROUPS:
            MEDIA_GROUPS[mg_id] = []
            async def process_media_group(m_id):
                await asyncio.sleep(2.0)
                if m_id in MEDIA_GROUPS:
                    msg_ids = MEDIA_GROUPS.pop(m_id)
                    await send_admin_notification(msg_ids)
            asyncio.create_task(process_media_group(mg_id))
        MEDIA_GROUPS[mg_id].append(message.message_id)
    else:
        # Handle single file
        await send_admin_notification([message.message_id])

# ============================================================
# ADMIN CONVERSATION HANDLERS
# ============================================================
@dp.callback_query(F.data.startswith("ap:"))
async def start_quick_post(callback: CallbackQuery, state: FSMContext):
    upload_id = callback.data.split(":")[1]
    msg_ids = PENDING_UPLOADS.get(upload_id)
    
    if not msg_ids:
        await callback.answer("⚠️ This upload notification has expired.", show_alert=True)
        return
        
    await state.update_data(target_msg_ids=msg_ids)
    await callback.message.answer("1️⃣ Movie Title? (e.g., `Spider-Man: No Way Home`)")
    await state.set_state(QuickPostForm.title)
    await callback.answer()

@dp.message(QuickPostForm.title)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("2️⃣ Language? (e.g., `English, Hindi`)")
    await state.set_state(QuickPostForm.language)

@dp.message(QuickPostForm.language)
async def process_language(message: Message, state: FSMContext):
    await state.update_data(language=message.text)
    await message.answer("3️⃣ IMDB Rating? (e.g., `7.5`)")
    await state.set_state(QuickPostForm.imdb)

@dp.message(QuickPostForm.imdb)
async def process_imdb(message: Message, state: FSMContext):
    await state.update_data(imdb=message.text)
    await message.answer("4️⃣ OTT Platform? (e.g., `Netflix`)")
    await state.set_state(QuickPostForm.ott)

@dp.message(QuickPostForm.ott)
async def process_ott(message: Message, state: FSMContext):
    await state.update_data(ott=message.text)
    data = await state.get_data()
    num_files = len(data['target_msg_ids'])
    
    if num_files == 1:
        await message.answer("5️⃣ What quality is this video? (e.g., `1080p`)")
    else:
        await message.answer(f"5️⃣ You uploaded an Album with **{num_files} videos**.\n\n"
                             f"Send me their qualities separated by commas, **matching their top-to-bottom order.**\n"
                             f"Example: `1080p, 720p`")
    await state.set_state(QuickPostForm.qualities_list)

@dp.message(QuickPostForm.qualities_list)
async def process_quality(message: Message, state: FSMContext):
    data = await state.get_data()
    num_files = len(data['target_msg_ids'])
    
    qualities = [q.strip() for q in message.text.split(",")]
    
    if len(qualities) != num_files:
        await message.answer(f"⚠️ You provided {len(qualities)} qualities, but there are {num_files} videos. Try again:")
        return
        
    await state.update_data(qualities_list=qualities)
    await message.answer("6️⃣ Almost done! Send the **Poster Photo, GIF, or Video**.")
    await state.set_state(QuickPostForm.poster)

@dp.message(QuickPostForm.poster, F.photo | F.animation | F.video)
async def process_poster(message: Message, state: FSMContext):
    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.animation:
        file_id = message.animation.file_id
        media_type = "animation"
    elif message.video:
        file_id = message.video.file_id
        media_type = "video"
        
    data = await state.get_data()
    
    title = data["title"]
    language = data["language"]
    msg_ids = data["target_msg_ids"]
    qualities = data["qualities_list"]
    bot_info = await bot.get_me()

    buttons = []
    row = []
    
    for i in range(len(msg_ids)):
        quality_name = f"🗿 {qualities[i].upper()}"
        target_msg = msg_ids[i]
        
        deep_link = f"https://t.me/{bot_info.username}?start=dl-{target_msg}"
        row.append(InlineKeyboardButton(text=quality_name, url=deep_link))
        
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    caption = (
        f"<b>🎬 {title.upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🔈 Language: {language}\n"
        f"<blockquote>IMDB = {data['imdb']} ⭐</blockquote>\n"
        f"OTT = {data['ott']} 🍿\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🚨 First request may take 30–60s. Please wait ⏳."
    )

    try:
        if media_type == "photo":
            await bot.send_photo(chat_id=PUBLIC_CHANNEL_ID, photo=file_id, caption=caption, reply_markup=keyboard, parse_mode="HTML")
        elif media_type == "animation":
            await bot.send_animation(chat_id=PUBLIC_CHANNEL_ID, animation=file_id, caption=caption, reply_markup=keyboard, parse_mode="HTML")
        elif media_type == "video":
            await bot.send_video(chat_id=PUBLIC_CHANNEL_ID, video=file_id, caption=caption, reply_markup=keyboard, parse_mode="HTML")
            
        await message.answer("✅ **Published to Public Channel!** ")
    except Exception as e:
        await message.answer(f"❌ Could not post to Public Channel: {e}")

    await state.clear()

# ============================================================
# USER DELIVERY HANDLERS (Direct Fetching via URL Payload)
# ============================================================
@dp.message(CommandStart())
async def handle_start(message: Message, command: CommandObject):
    payload = command.args
    
    if not payload:
        text = (
            "🎬 Welcome to Content Vault!\n\n"
            "👀 Your next movie is waiting...\n"
            "🍿 Quality movies. One place.\n\n"
            "🔐 Join the Vault & discover more! 👇"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔐 Join Content Vault",
                        url=f"https://t.me/{PUBLIC_CHANNEL_USERNAME}"
                    )
                ]
            ]
        )

        await message.answer(text, reply_markup=keyboard)
        return

    if payload.startswith("dl-"):
        try:
            target_msg_id = int(payload.split("-")[1])
            
            await message.answer("Your request is loading… ⏳")
            media = await bot.copy_message(message.chat.id, PRIVATE_CHANNEL_ID, target_msg_id)
            
            join_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔐 Join Content Vault",
                            url=f"https://t.me/{PUBLIC_CHANNEL_USERNAME}"
                        )
                    ]
                ]
            )

            warn = await message.answer(
                "🚨🚨 **This media will 🛺 auto-delete in 5 minutes.** 🚨🚨", 
                parse_mode="Markdown",
                reply_markup=join_keyboard
            )
            
            asyncio.create_task(delete_messages_after_delay(message.chat.id, [media.message_id, warn.message_id], DELETE_DELAY))
        
        except Exception:
            await message.answer("❌ Could not deliver file. It may have been removed.")
        return

async def main():
    # Forces Telegram to clear any active webhooks stuck from Render or remote servers
    await bot.delete_webhook(drop_pending_updates=True)
    
    print("Bot is online :)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())