import os
import re
import asyncio
import logging
from datetime import datetime
from telegram import Bot
from supabase import create_client
import aiohttp
import feedparser

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === КОНФИГУРАЦИЯ ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNELS = [os.getenv("CHANNEL_ID1"), os.getenv("CHANNEL_ID2")]
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not all([TELEGRAM_TOKEN, CHANNELS[0], CHANNELS[1], SUPABASE_URL, SUPABASE_KEY]):
    raise ValueError("❌ Не все переменные окружения заполнены")

BOT = Bot(token=TELEGRAM_TOKEN)
SUPABASE = create_client(SUPABASE_URL, SUPABASE_KEY)

SOURCES = [
    {"name": "GOODJUDGMENT", "url": "https://www.goodjudgment.com/feed"},
    {"name": "JOHNSHOPKINS", "url": "https://www.centerforhealthsecurity.org/feed.xml"},
    {"name": "METACULUS", "url": "https://www.metaculus.com/feed/"},
    {"name": "DNI", "url": "https://www.dni.gov/index.php/gt2040-feed"},
    {"name": "RANDCORP", "url": "https://www.rand.org/rss/news.html"},
    {"name": "WEF", "url": "https://www.weforum.org/feed"},
    {"name": "CSIS", "url": "https://www.csis.org/rss/all.xml"},
    {"name": "ATLANTICCOUNCIL", "url": "https://www.atlanticcouncil.org/feed/"},
    {"name": "CHATHAMHOUSE", "url": "https://www.chathamhouse.org/feed"},
    {"name": "ECONOMIST", "url": "https://www.economist.com/the-world-this-week/rss.xml"},
    {"name": "BLOOMBERG", "url": "https://feeds.bloomberg.com/politics/news.rss"},
    {"name": "REUTERS", "url": "https://reutersinstitute.politics.ox.ac.uk/rss.xml"},
    {"name": "FOREIGNAFFAIRS", "url": "https://www.foreignaffairs.com/rss.xml"},
    {"name": "CFR", "url": "https://www.cfr.org/rss.xml"},
    {"name": "BBCFUTURE", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "FUTURETIMELINE", "url": "https://www.futuretimeline.net/blog/feed/"},
    {"name": "CARNEGIE", "url": "https://carnegieendowment.org/rss/all.xml"},
    {"name": "BRUEGEL", "url": "https://www.bruegel.org/blog/feed"},
    {"name": "E3G", "url": "https://www.e3g.org/feed/"}
]

# === ФИЛЬТРЫ ПО РОССИИ И УКРАИНЕ ===
FILTERS = {
    "SVO": [
        # Военная операция
        r"военная\s+операци[ия]\s+на\s+украине", r"спецопераци[ия]\s+на\s+украине", 
        r"российская\s+армия\s+в\s+украине", r"вс\s+рф\s+на\s+донбассе", r"днр\s+лнр\s+присоединение",
        
        # Украинские территории
        r"(донбасс|донецк|луганск|херсон|запорожье|мариуполь)\s+(освобождени[ея]|контроль\s+российских\s+войск)",
        
        # Военные действия
        r"(удар|атака|наступление)\s+(российских|вс\s+рф)\s+(войск|сил)\s+(на|в)\s+(киев|харьков|одесса)",
        r"сбит[оыи]\s+(российск|украинск)\s+(самолет|дрон|ракет)",
        
        # Санкции
        r"санкции\s+(против|в\s+отношении)\s+(росси[ия]|рф|российских\s+компаний)",
        r"(запрет|ограничение)\s+на\s+(нефть|газ)\s+из\s+росси[и]",
        r"северный\s+поток\s+(приостановлен|разрушен)"
    ],
    "crypto": [
        # Цифровой рубль
        r"цифровой\s+рубль", r"digital\s+ruble", r"цифровая\s+валют[аы]\s+российского\s+банка",
        
        # Санкции и крипта
        r"(санкции\s+против\s+рф|российские\s+хакеры)\s+(биткоин|bitcoin|криптовалют[аы])",
        r"россия\s+(использует|отмывает)\s+криптовалют[уы]",
        
        # Регулирование в РФ
        r"(цб\s+рф|правительство\s+рф)\s+(разрешает|запрещает|регулирует)\s+криптовалют[ыу]",
        r"майнинг\s+в\s+россии\s+(легализован|запрещен)",
        
        # Криптобиржи и РФ
        r"(binance|bybit)\s+(блокирует|ограничивает)\s+российских\s+пользователей"
    ]
}

# === ОСНОВНЫЕ ФУНКЦИИ ===
async def translate_to_russian(text: str) -> str:
    """Перевод текста на русский язык"""
    if not text or len(text) < 5:
        return text
    
    # Если уже на русском - возвращаем как есть
    if re.search(r'[а-яё]', text[:100]):
        return text
    
    # Попытка перевода через LibreTranslate
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://libretranslate.de/translate",
                json={"q": text[:500], "source": "auto", "target": "ru"},
                timeout=15
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("translatedText", text)
    except Exception as e:
        logger.warning(f"LibreTranslate ошибка: {str(e)}")
    
    return text

async def get_articles():
    """Получение и перевод статей из всех источников"""
    articles = []
    
    for source in SOURCES:
        try:
            async with aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0'}) as session:
                async with session.get(source["url"], timeout=10) as response:
                    if response.status != 200:
                        continue
                    
                    feed = feedparser.parse(await response.text())
                    for entry in feed.entries[:3]:
                        lead = entry.summary[:300] + "..." if hasattr(entry, 'summary') else ""
                        
                        # Переводим заголовок и лид
                        translated_title = await translate_to_russian(entry.title)
                        translated_lead = await translate_to_russian(lead)
                        
                        articles.append({
                            "title": translated_title,
                            "url": entry.link,
                            "source": source["name"],
                            "lead": translated_lead
                        })
        except Exception as e:
            logger.error(f"Ошибка обработки {source['name']}: {str(e)}")
    
    logger.info(f"✅ Получено {len(articles)} статей")
    return articles

def detect_category(text: str) -> str:
    """Определение категории по точным паттернам"""
    text_lower = text.lower()
    
    for category, patterns in FILTERS.items():
        if any(re.search(p, text_lower, re.IGNORECASE | re.UNICODE) for p in patterns):
            return category
    return None

async def send_to_telegram(article: dict, category: str):
    """Отправка сообщения БЕЗ ХЕШТЕГА"""
    message = (
        f"<b>{article['source']}</b>: {article['title']}\n\n"
        f"{article['lead']}\n\n"
        f"Источник: {article['url']}"
    )
    
    for channel in CHANNELS:
        try:
            await BOT.send_message(
                chat_id=channel,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"📤 Отправлено в {channel}: {article['title'][:25]}...")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в {channel}: {str(e)}")

async def main():
    """Основной цикл работы бота"""
    try:
        logger.info("🚀 Запуск бота с фильтрами по России/Украине")
        articles = await get_articles()
        
        for article in articles:
            # Проверка дубликатов в базе - ИСПРАВЛЕНО
            exists = SUPABASE.table("news_articles").select("id").eq("url", article["url"]).execute()
            if exists.data:  # ИСПРАВЛЕНО: добавлено .data
                logger.info(f"♻️ Дубликат: {article['url']}")
                continue
            
            # Определение категории
            category = detect_category(f"{article['title']} {article['lead']}")
            if not category:
                continue
            
            # Отправка сообщения
            await send_to_telegram(article, category)
            
            # Сохранение в базу
            SUPABASE.table("news_articles").insert({
                "title": article["title"],
                "source_name": article["source"],
                "url": article["url"],
                "category": category,
                "published_at": datetime.utcnow().isoformat()
            }).execute()
            
            await asyncio.sleep(1.5)  # Задержка между отправками
        
        logger.info(f"✅ Обработка завершена. Отправлено: {len(articles)} статей")
        
    except Exception as e:
        logger.exception(f"🔥 Фатальная ошибка: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
