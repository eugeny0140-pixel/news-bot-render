import os
import asyncio
import re
from datetime import datetime, timedelta
import logging
from parsers import get_all_articles
from filters import FILTERS, CATEGORIES
from supabase import create_client
from telegram import Bot

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_IDS = [os.getenv("CHANNEL_ID1"), os.getenv("CHANNEL_ID2")]
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=TELEGRAM_TOKEN)

def check_filters(text: str, category: str) -> bool:
    """Проверяет текст на соответствие фильтрам категории"""
    for pattern in FILTERS[category]:
        if re.search(pattern, text, re.IGNORECASE | re.UNICODE):
            return True
    return False

def format_message(article: dict, category: str) -> str:
    """Форматирует сообщение для Telegram"""
    source_tag = article['source'].replace(" ", "").upper()
    title = article['title'].strip()
    lead = article['lead'].strip() if article.get('lead') else ""
    
    return (
        f"(<b>{source_tag}</b>): {title}\n\n"
        f"({lead})\n\n"
        f"Источник: {article['url']}\n\n"
        f"#{category}"
    )

async def send_to_channels(message: str):
    """Отправляет сообщение в оба канала"""
    for channel_id in CHANNEL_IDS:
        try:
            await bot.send_message(
                chat_id=channel_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"✅ Отправлено в {channel_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в {channel_id}: {str(e)}")

async def process_articles():
    """Основной цикл обработки"""
    logger.info("🔍 Начинаю сбор новостей...")
    articles = await get_all_articles()
    
    for article in articles:
        # Проверка дубликатов
        existing = supabase.table("news_articles").select("*").eq("url", article['url']).execute()
        if existing.data:
            continue
            
        # Определение категории
        matched_category = None
        full_text = f"{article['title']} {article.get('lead', '')}"
        
        for category in CATEGORIES:
            if check_filters(full_text, category):
                matched_category = category
                break
        
        if not matched_category:
            continue
            
        # Формирование и отправка сообщения
        message = format_message(article, matched_category)
        await send_to_channels(message)
        
        # Сохранение в базу
        supabase.table("news_articles").insert({
            "title": article['title'],
            "source_name": article['source'],
            "lead": article.get('lead', ''),
            "url": article['url'],
            "category": matched_category,
            "published_at": datetime.utcnow().isoformat(),
            "is_sent": True
        }).execute()
        
        await asyncio.sleep(1)  # Задержка между отправками
    
    logger.info(f"✅ Обработано {len(articles)} статей")

if __name__ == "__main__":
    asyncio.run(process_articles())
