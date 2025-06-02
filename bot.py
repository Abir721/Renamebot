import os
import asyncio
import logging
from time import time
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageNotModified
from mimetypes import guess_type
from PIL import Image

# ========== CONFIGURATION ========== #
API_ID = 28593211  # Replace with your API ID
API_HASH = "27ad7de4fe5cab9f8e310c5cc4b8d43d"  # Replace with your API Hash
BOT_TOKEN = "6497015478:AAEKPHpfIJ4FvoRIFJH34qqByGBlqxx6kAc"  # Replace with your Bot Token
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
THUMB_DIR = "thumbs"

os.makedirs(THUMB_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
bot = Client("file_converter_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# In-memory storage for user thumbnails and rename cache
user_thumbs = {}
rename_cache = {}

# ========== PROGRESS FUNCTION ========== #
async def progress_func(current, total, *args):
    message = args[0]
    start = args[1]
    try:
        now = time()
        speed = current / (now - start + 1)
        percent = current * 100 / total
        bar = f"[{'█' * int(percent // 5)}{'.' * (20 - int(percent // 5))}]"
        text = f"{bar} {percent:.2f}%\n" \
               f"{current / 1024 / 1024:.2f} MB of {total / 1024 / 1024:.2f} MB\n" \
               f"Speed: {speed / 1024 / 1024:.2f} MB/s"
        await message.edit(text)
    except MessageNotModified:
        pass
    except Exception:
        pass

# ========== /START COMMAND ========== #
@bot.on_message(filters.command("start"))
async def start_handler(client, message: Message):
    text = f"👋 Hello {message.from_user.mention}, I can:\n\n" \
           "📁 Convert Document <--> Video\n" \
           "✏️ Rename any file\n" \
           "🖼️ Set custom thumbnail\n\n" \
           "Just send me a file!"
    await message.reply(text)

# ========== /SETIMAGE COMMAND ========== #
@bot.on_message(filters.command("setimage") & filters.photo)
async def set_thumb(client, message: Message):
    path = os.path.join(THUMB_DIR, f"{message.from_user.id}.jpg")
    await message.download(path)
    user_thumbs[message.from_user.id] = path
    await message.reply("✅ Thumbnail saved!")

# ========== /DELTHUMB COMMAND ========== #
@bot.on_message(filters.command("delthumb"))
async def delete_thumb(client, message: Message):
    path = os.path.join(THUMB_DIR, f"{message.from_user.id}.jpg")
    if os.path.exists(path):
        os.remove(path)
        user_thumbs.pop(message.from_user.id, None)
        await message.reply("🗑️ Thumbnail deleted.")
    else:
        await message.reply("⚠️ No thumbnail set.")

# ========== FILE HANDLER ========== #
@bot.on_message(filters.document | filters.video)
async def file_handler(client, message: Message):
    media = message.document or message.video
    if media.file_size > MAX_FILE_SIZE:
        return await message.reply("❌ File too large! Max 2GB allowed.")

    file_name = media.file_name or "Unnamed"
    buttons = [
        [
            InlineKeyboardButton("🗂 Convert to Document", callback_data="to_doc"),
            InlineKeyboardButton("🎥 Convert to Video", callback_data="to_vid")
        ],
        [
            InlineKeyboardButton("✏️ Rename", callback_data="rename"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        ]
    ]
    await message.reply(
        f"📄 File: `{file_name}`\nWhat would you like to do?",
        reply_markup=InlineKeyboardMarkup(buttons),
        quote=True
    )

# ========== CALLBACK QUERY HANDLER ========== #
@bot.on_callback_query()
async def cb_handler(client, cb):
    data = cb.data
    msg = cb.message.reply_to_message

    if not msg or not (msg.document or msg.video):
        return await cb.message.edit("⚠️ Original file not found.")

    media = msg.document or msg.video
    user_id = cb.from_user.id
    file_name = media.file_name or "file"
    download_path = f"{user_id}_{file_name}"
    start = time()
    prog = await cb.message.edit("📥 Downloading...")

    try:
        await msg.download(
            file_name=download_path,
            progress=progress_func,
            progress_args=(prog, start)
        )
    except Exception as e:
        return await cb.message.edit(f"❌ Failed to download.\n`{e}`")

    if data == "to_doc":
        new_file = file_name if file_name.endswith(".mp4") else f"{os.path.splitext(file_name)[0]}.mp4"
        await send_as_document(client, cb.message, user_id, download_path, new_file)
    elif data == "to_vid":
        new_file = file_name if file_name.endswith(".mp4") else f"{os.path.splitext(file_name)[0]}.mp4"
        await send_as_video(client, cb.message, user_id, download_path, new_file)
    elif data == "rename":
        await cb.message.edit("✏️ Send me the new file name with extension (e.g., `newname.mp4`).")
        rename_cache[user_id] = download_path
        return
    else:
        os.remove(download_path)
        await cb.message.edit("❌ Cancelled.")
        return

# ========== TEXT HANDLER FOR RENAME ========== #
@bot.on_message(filters.text & filters.private)
async def rename_text(client, message: Message):
    user_id = message.from_user.id
    if user_id not in rename_cache:
        return

    old_path = rename_cache.pop(user_id)
    new_name = message.text.strip()

    if not os.path.exists(old_path):
        return await message.reply("⚠️ File missing.")

    new_path = f"{user_id}_{new_name}"
    os.rename(old_path, new_path)
    ext = os.path.splitext(new_name)[-1].lower()

    if ext in [".mp4", ".mkv", ".avi"]:
        await send_as_video(client, message, user_id, new_path, new_name)
    else:
        await send_as_document(client, message, user_id, new_path, new_name)

# ========== SEND AS VIDEO ========== #
async def send_as_video(client, message, user_id, file_path, file_name):
    thumb_path = os.path.join(THUMB_DIR, f"{user_id}.jpg")
    kwargs = {
        "caption": f"`{file_name}`",
        "file_name": file_name,
        "supports_streaming": True
    }
    if os.path.exists(thumb_path):
        kwargs["thumb"] = thumb_path

    try:
        start = time()
        prog = await message.reply("📤 Uploading as video...")
        await client.send_video(
            chat_id=message.chat.id,
            video=file_path,
            progress=progress_func,
            progress_args=(prog, start),
            **kwargs
        )
    finally:
        os.remove(file_path)

# ========== SEND AS DOCUMENT ========== #
async def send_as_document(client, message, user_id, file_path, file_name):
    thumb_path = os.path.join(THUMB_DIR, f"{user_id}.jpg")
    kwargs = {
        "caption": f"`{file_name}`",
        "file_name": file_name
    }
    if os.path.exists(thumb_path):
        kwargs["thumb"] = thumb_path

    try:
        start = time()
        prog = await message.reply("📤 Uploading as document...")
        await client.send_document(
            chat_id=message.chat.id,
            document=file_path,
            progress=progress_func,
            progress_args=(prog, start),
            **kwargs
        )
    finally:
        os.remove(file_path)

# ========== START BOT ========== #
print("🚀 Bot started.")
bot.run()
