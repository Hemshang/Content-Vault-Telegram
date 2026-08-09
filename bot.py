import os
import asyncio
import uuid
import re
from dotenv import load_dotenv
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# ============================================================
# CONFIGURATION
# ============================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PRIVATE_CHANNEL_ID = int(os.getenv("PRIVATE_CHANNEL_ID"))
PUBLIC_CHANNEL_ID = int(os.getenv("PUBLIC_CHANNEL_ID"))
PUBLIC_CHANNEL_USERNAME = os.getenv("PUBLIC_CHANNEL_USERNAME")
ADMIN_ID = int(os.getenv("ADMIN_ID"))                

# Render Environment Variables
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://content-vault-telegram.onrender.com")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"

PORT = int(os.getenv("PORT", 10000))
DELETE_DELAY = 260  # 5 minutes

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Memory strictly for handling uploads in progress
MEDIA_GROUPS = {}
PENDING_UPLOADS = {}

class QuickPostForm(StatesGroup):
    target_msg_ids = State() 
    title = State()
    language = State()
    subtitle = State()
    imdb = State()
    genre = State()
    ott = State()
    qualities_list = State()
    poster = State()

# Quick Selection Keyboards
LANGUAGE_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="Telugu", callback_data="lang:Telugu"),
        InlineKeyboardButton(text="English", callback_data="lang:English"),
        InlineKeyboardButton(text="Hindi", callback_data="lang:Hindi")
    ],
    [
        InlineKeyboardButton(text="Tamil", callback_data="lang:Tamil"),
        InlineKeyboardButton(text="Kannada", callback_data="lang:Kannada"),
        InlineKeyboardButton(text="Malayalam", callback_data="lang:Malayalam")
    ],
    [
        InlineKeyboardButton(text="🔊 Tel + Hin + Tam", callback_data="lang:Telugu, Hindi, Tamil"),
        InlineKeyboardButton(text="🔊 Tel + Tam + Mal", callback_data="lang:Telugu, Tamil, Malayalam")
    ],
    [
        InlineKeyboardButton(text="🎧 Telugu + English", callback_data="lang:Telugu, English"),
        InlineKeyboardButton(text="🎧 Hindi + English", callback_data="lang:Hindi, English")
    ],
    [
        InlineKeyboardButton(text="🎙️ Dual Audio (Tel + Hin)", callback_data="lang:Dual Audio [Telugu + Hindi]"),
        InlineKeyboardButton(text="🌐 Multi Audio (Org + Dub)", callback_data="lang:Multi Audio [Org + Dub]")
    ],
    [InlineKeyboardButton(text="✏️ Type Custom Language", callback_data="lang:custom")]
])

SUBTITLE_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="🇬🇧 English", callback_data="sub:English"),
        InlineKeyboardButton(text="🪔 Telugu", callback_data="sub:Telugu"),
        InlineKeyboardButton(text="🛕 Hindi", callback_data="sub:Hindi")
    ],
    [
        InlineKeyboardButton(text="🌺 Tamil", callback_data="sub:Tamil"),
        InlineKeyboardButton(text="🚫 None / No Subs", callback_data="sub:None"),
        InlineKeyboardButton(text="📑 Multi-Subs", callback_data="sub:Multi-Subs [Esub]")
    ],
    [InlineKeyboardButton(text="✏️ Type Custom Subtitle", callback_data="sub:custom")]
])

GENRE_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="🎬 Action", callback_data="genre:Action"),
        InlineKeyboardButton(text="🚀 Sci-Fi", callback_data="genre:Sci-Fi"),
        InlineKeyboardButton(text="🎭 Drama", callback_data="genre:Drama")
    ],
    [
        InlineKeyboardButton(text="🎃 Horror", callback_data="genre:Horror"),
        InlineKeyboardButton(text="💥 Action/Sci-Fi", callback_data="genre:Action/Sci-Fi"),
        InlineKeyboardButton(text="😂 Comedy", callback_data="genre:Comedy")
    ],
    [
        InlineKeyboardButton(text="🔍 Thriller", callback_data="genre:Thriller"),
        InlineKeyboardButton(text="🌟 Adventure", callback_data="genre:Adventure"),
        InlineKeyboardButton(text="💥 Action/Thriller", callback_data="genre:Action/Thriller")
    ],
    [InlineKeyboardButton(text="✏️ Type Custom Genre", callback_data="genre:custom")]
])

OTT_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="🔴 Netflix", callback_data="ott:Netflix"),
        InlineKeyboardButton(text="🔵 Prime Video", callback_data="ott:Prime Video")
    ],
    [
        InlineKeyboardButton(text="⭐️ Disney+ Hotstar", callback_data="ott:Disney+ Hotstar"),
        InlineKeyboardButton(text="🟡 Zee5", callback_data="ott:Zee5")
    ],
    [
        InlineKeyboardButton(text="🟠 SonyLIV", callback_data="ott:SonyLIV"),
        InlineKeyboardButton(text="🟢 JioCinema", callback_data="ott:JioCinema")
    ],
    [InlineKeyboardButton(text="✏️ Type Custom OTT", callback_data="ott:custom")]
])

QUALITY_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="📱 480p", callback_data="qual:480p"),
        InlineKeyboardButton(text="📺 720p HD", callback_data="qual:720p"),
        InlineKeyboardButton(text="💿 1080p FHD", callback_data="qual:1080p")
    ],
    [
        InlineKeyboardButton(text="🔮 2K (1440p)", callback_data="qual:2K"),
        InlineKeyboardButton(text="✨ 4K (2160p)", callback_data="qual:4K"),
        InlineKeyboardButton(text="🌌 8K (4320p)", callback_data="qual:8K")
    ],
    [InlineKeyboardButton(text="✏️ Type Custom / Multiple Manually", callback_data="qual:custom")]
])

# ============================================================
# AUTO-DELETION HELPER
# ============================================================
async def delete_messages_after_delay(chat_id: int, message_ids: list[int], delay: int):
    await asyncio.sleep(delay)
    for msg_id in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

# ============================================================
# AUTOMATED UPLOAD LISTENER
# ============================================================
async def send_admin_notification(msg_ids: list):
    msg_ids.sort()
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
        
    await state.update_data(target_msg_ids=msg_ids, collected_qualities=[])
    await callback.message.answer("1️⃣ Movie Title? (e.g., `Spider-Man: No Way Home`)", parse_mode="Markdown")
    await state.set_state(QuickPostForm.title)
    await callback.answer()

@dp.message(QuickPostForm.title)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("2️⃣ Select **Language** below or tap custom to type:", reply_markup=LANGUAGE_KEYBOARD, parse_mode="Markdown")
    await state.set_state(QuickPostForm.language)

# --- LANGUAGE HANDLERS ---
@dp.callback_query(QuickPostForm.language, F.data.startswith("lang:"))
async def process_language_callback(callback: CallbackQuery, state: FSMContext):
    selected_lang = callback.data.split(":")[1]
    if selected_lang == "custom":
        await callback.message.answer("✏️ Please type the custom **Language(s)** (e.g., `Telugu, Tamil`):", parse_mode="Markdown")
        await callback.answer()
        return

    await state.update_data(language=selected_lang)
    await callback.message.answer(f"Selected Language: **{selected_lang}**", parse_mode="Markdown")
    await callback.message.answer("3️⃣ Select **Subtitle** below or tap custom to type:", reply_markup=SUBTITLE_KEYBOARD, parse_mode="Markdown")
    await state.set_state(QuickPostForm.subtitle)
    await callback.answer()

@dp.message(QuickPostForm.language)
async def process_language_text(message: Message, state: FSMContext):
    await state.update_data(language=message.text)
    await message.answer("3️⃣ Select **Subtitle** below or tap custom to type:", reply_markup=SUBTITLE_KEYBOARD, parse_mode="Markdown")
    await state.set_state(QuickPostForm.subtitle)

# --- SUBTITLE HANDLERS ---
@dp.callback_query(QuickPostForm.subtitle, F.data.startswith("sub:"))
async def process_subtitle_callback(callback: CallbackQuery, state: FSMContext):
    selected_sub = callback.data.split(":")[1]
    if selected_sub == "custom":
        await callback.message.answer("✏️ Please type the custom **Subtitle(s)** (e.g., `English, Hindi`):", parse_mode="Markdown")
        await callback.answer()
        return

    await state.update_data(subtitle=selected_sub)
    await callback.message.answer(f"Selected Subtitle: **{selected_sub}**", parse_mode="Markdown")
    await callback.message.answer("4️⃣ IMDB Rating? (e.g., `5.9`)", parse_mode="Markdown")
    await state.set_state(QuickPostForm.imdb)
    await callback.answer()

@dp.message(QuickPostForm.subtitle)
async def process_subtitle_text(message: Message, state: FSMContext):
    await state.update_data(subtitle=message.text)
    await message.answer("4️⃣ IMDB Rating? (e.g., `5.9`)", parse_mode="Markdown")
    await state.set_state(QuickPostForm.imdb)

@dp.message(QuickPostForm.imdb)
async def process_imdb(message: Message, state: FSMContext):
    await state.update_data(imdb=message.text)
    await message.answer("5️⃣ Select **Genre** below or tap custom to type:", reply_markup=GENRE_KEYBOARD, parse_mode="Markdown")
    await state.set_state(QuickPostForm.genre)

# --- GENRE HANDLERS ---
@dp.callback_query(QuickPostForm.genre, F.data.startswith("genre:"))
async def process_genre_callback(callback: CallbackQuery, state: FSMContext):
    selected_genre = callback.data.split(":")[1]
    if selected_genre == "custom":
        await callback.message.answer("✏️ Please type the custom **Genre**:", parse_mode="Markdown")
        await callback.answer()
        return
    
    await state.update_data(genre=selected_genre)
    await callback.message.answer(f"Selected Genre: **{selected_genre}**", parse_mode="Markdown")
    await callback.message.answer("6️⃣ Select **OTT Platform** below or tap custom to type:", reply_markup=OTT_KEYBOARD, parse_mode="Markdown")
    await state.set_state(QuickPostForm.ott)
    await callback.answer()

@dp.message(QuickPostForm.genre)
async def process_genre_text(message: Message, state: FSMContext):
    await state.update_data(genre=message.text)
    await message.answer("6️⃣ Select **OTT Platform** below or tap custom to type:", reply_markup=OTT_KEYBOARD, parse_mode="Markdown")
    await state.set_state(QuickPostForm.ott)

# --- OTT HANDLERS ---
@dp.callback_query(QuickPostForm.ott, F.data.startswith("ott:"))
async def process_ott_callback(callback: CallbackQuery, state: FSMContext):
    selected_ott = callback.data.split(":")[1]
    if selected_ott == "custom":
        await callback.message.answer("✏️ Please type the custom **OTT Platform**:", parse_mode="Markdown")
        await callback.answer()
        return
        
    await state.update_data(ott=selected_ott)
    await callback.message.answer(f"Selected OTT: **{selected_ott}**", parse_mode="Markdown")
    
    data = await state.get_data()
    num_files = len(data['target_msg_ids'])
    
    if num_files == 1:
        await callback.message.answer("7️⃣ Select **Video Quality** below or tap custom to type:", reply_markup=QUALITY_KEYBOARD, parse_mode="Markdown")
    else:
        await callback.message.answer(
            f"7️⃣ You uploaded an Album with **{num_files} videos**.\n"
            f"Tap the quality button for **Video #1** (or type all separated by commas):",
            reply_markup=QUALITY_KEYBOARD,
            parse_mode="Markdown"
        )
    await state.set_state(QuickPostForm.qualities_list)
    await callback.answer()

@dp.message(QuickPostForm.ott)
async def process_ott_text(message: Message, state: FSMContext):
    await state.update_data(ott=message.text)
    data = await state.get_data()
    num_files = len(data['target_msg_ids'])
    
    if num_files == 1:
        await message.answer("7️⃣ Select **Video Quality** below or tap custom to type:", reply_markup=QUALITY_KEYBOARD, parse_mode="Markdown")
    else:
        await message.answer(
            f"7️⃣ You uploaded an Album with **{num_files} videos**.\n"
            f"Tap the quality button for **Video #1** (or type all separated by commas):",
            reply_markup=QUALITY_KEYBOARD,
            parse_mode="Markdown"
        )
    await state.set_state(QuickPostForm.qualities_list)

# --- QUALITY HANDLERS ---
@dp.callback_query(QuickPostForm.qualities_list, F.data.startswith("qual:"))
async def process_quality_callback(callback: CallbackQuery, state: FSMContext):
    selected_qual = callback.data.split(":")[1]
    if selected_qual == "custom":
        await callback.message.answer("✏️ Type quality (or comma-separated qualities if album, e.g. `1080p, 720p`):", parse_mode="Markdown")
        await callback.answer()
        return

    data = await state.get_data()
    num_files = len(data['target_msg_ids'])
    collected = data.get("collected_qualities", [])
    collected.append(selected_qual)
    
    if len(collected) < num_files:
        await state.update_data(collected_qualities=collected)
        next_index = len(collected) + 1
        await callback.message.answer(
            f"✅ Video #{len(collected)}: **{selected_qual}**\n"
            f"Select quality for **Video #{next_index}**:",
            reply_markup=QUALITY_KEYBOARD,
            parse_mode="Markdown"
        )
    else:
        await state.update_data(qualities_list=collected)
        qualities_str = ", ".join(collected)
        await callback.message.answer(f"Selected Qualities: **{qualities_str}**", parse_mode="Markdown")
        await callback.message.answer("8️⃣ Almost done! Send the **Poster Photo, GIF, or Video**.", parse_mode="Markdown")
        await state.set_state(QuickPostForm.poster)
        
    await callback.answer()

@dp.message(QuickPostForm.qualities_list)
async def process_quality_text(message: Message, state: FSMContext):
    data = await state.get_data()
    num_files = len(data['target_msg_ids'])
    
    qualities = [q.strip() for q in message.text.split(",")]
    
    if len(qualities) != num_files:
        await message.answer(f"⚠️ You provided {len(qualities)} qualities, but there are {num_files} videos. Try again:")
        return
        
    await state.update_data(qualities_list=qualities)
    await message.answer("8️⃣ Almost done! Send the **Poster Photo, GIF, or Video**.", parse_mode="Markdown")
    await state.set_state(QuickPostForm.poster)

# --- POSTER HANDLER ---
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
    subtitle = data.get("subtitle", "None")
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
        f"🔈 Language:- <b>{language}</b> | Subtitle:- <b>{subtitle}</b>\n"
        f"<blockquote><b>IMDB</b> = {data['imdb']} ⭐ | <i><b>Genre</b></i> = {data['genre']}</blockquote>\n"
        f"<b>OTT</b> = {data['ott']} 🍿\n"
        f"━━━━━━━━━━━━━━━━━\n"
        
    )

    try:
        if media_type == "photo":
            await bot.send_photo(chat_id=PUBLIC_CHANNEL_ID, photo=file_id, caption=caption, reply_markup=keyboard, parse_mode="HTML")
        elif media_type == "animation":
            await bot.send_animation(chat_id=PUBLIC_CHANNEL_ID, animation=file_id, caption=caption, reply_markup=keyboard, parse_mode="HTML")
        elif media_type == "video":
            await bot.send_video(chat_id=PUBLIC_CHANNEL_ID, video=file_id, caption=caption, reply_markup=keyboard, parse_mode="HTML")
            
        await message.answer("✅ **Published to Public Channel!**", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Could not post to Public Channel: {e}")

    await state.clear()

# ============================================================
# USER DELIVERY HANDLERS
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

# ============================================================
# WEBHOOK LIFECYCLE HANDLERS
# ============================================================
async def on_startup(bot: Bot) -> None:
    await bot.set_webhook(f"{WEBHOOK_URL}", drop_pending_updates=True)
    print(f"Webhook set to {WEBHOOK_URL}")

async def health_check(request):
    return web.Response(text="Bot is alive!")

def main() -> None:
    dp.startup.register(on_startup)

    app = web.Application()
    
    app.router.add_get("/", health_check)

    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
