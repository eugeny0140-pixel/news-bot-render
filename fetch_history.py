from datetime import datetime
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from supabase import create_client
import os

# === Настройки ===
# Для получения API_ID и API_HASH: https://my.telegram.org/auth
API_ID = int(os.getenv("TELEGRAM_API_ID")) # Переменная окружения
API_HASH = os.getenv("TELEGRAM_API_HASH") # Переменная окружения
PHONE = os.getenv("TELEGRAM_PHONE")       # Переменная окружения (в формате +71234567890)

SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_CHANNEL_ID")) # Например, -1002923537056

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# === Инициализация ===
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Функция для получения текста поста
def get_post_text(message):
    if message.message:
        return message.message
    # Можно добавить обработку других типов (медиа с подписью и т.п.)
    return ""

async def fetch_and_save_history():
    print("🔐 Авторизация в Telegram...")
    client = TelegramClient('anon_session', API_ID, API_HASH)

    await client.start(phone=PHONE)

    print(f"✅ Успешно вошли как {await client.get_me()}")

    print(f"📥 Получение постов из канала {SOURCE_CHANNEL_ID}...")
    channel_entity = await client.get_entity(SOURCE_CHANNEL_ID)

    # Счётчик
    count = 0
    async for message in client.iter_messages(channel_entity):
        if message.message:  # Проверяем, есть ли текст
            text = get_post_text(message)
            url = f"https://t.me/c/{str(SOURCE_CHANNEL_ID).replace('-100', '')}/{message.id}"
            pub_date = message.date

            # Проверяем, не дубль ли это (по URL)
            existing = supabase.table("ingested_content_items").select("id").eq("source_url", url).execute()
            if existing.data:
                print(f"⚠️ Пропущен дубль: {url}")
                continue

            # Сохраняем в Supabase
            try:
                supabase.table("ingested_content_items").insert({
                    "source_url": url,
                    "title": text[:500],
                    "content": text[:10000],
                    "pub_date": pub_date.isoformat(),
                    "channel_id": SOURCE_CHANNEL_ID,
                    "language": "ru",
                    "is_analyzed": False  # Пока не проанализирован
                }).execute()
                print(f"📥 Сохранён пост: {url}")
                count += 1
            except Exception as e:
                print(f"❌ Ошибка при сохранении {url}: {e}")

    print(f"✅ Загружено {count} постов из {SOURCE_CHANNEL_ID}")

# === Запуск ===
if __name__ == "__main__":
    import asyncio
    asyncio.run(fetch_and_save_history())
