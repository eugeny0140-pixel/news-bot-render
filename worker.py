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

# === ПРОВЕРЕННЫЕ ИСТОЧНИКИ (все работают 11.11.2025) ===
SOURCES = [
    {"name": "GOODJUDGMENT", "url": "https://goodjudgment.com/feed/"},
    {"name": "JOHNSHOPKINS", "url": "https://www.centerforhealthsecurity.org/feed.xml"},
    {"name": "METACULUS", "url": "https://www.metaculus.com/feed/"},
    {"name": "DNI", "url": "https://www.dni.gov/index.php/gt2040/feed"},
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
    {"name": "FUTURETIMELINE", "url": "https://www.futuretimeline.net/blog/feed/feed.xml"},
    {"name": "CARNEGIE", "url": "https://carnegieendowment.org/rss/all.xml"},
    {"name": "BRUEGEL", "url": "https://www.bruegel.org/feed"},
    {"name": "E3G", "url": "https://www.e3g.org/feed/"}
]

# === ОБНОВЛЕННЫЕ ФИЛЬТРЫ ===
FILTERS = {
    "SVO": [
        r"\bsvo\b", r"\bспецоперация\b", r"\bspecial military operation\b", 
        r"\bвойна\b", r"\bwar\b", r"\bconflict\b", r"\bконфликт\b", 
        r"\bнаступление\b", r"\boffensive\b", r"\bатака\b", r"\battack\b", 
        r"\bудар\b", r"\bstrike\b", r"\bобстрел\b", r"\bshelling\b", 
        r"\bдрон\b", r"\bdrone\b", r"\bmissile\b", r"\bракета\b", 
        r"\bэскалация\b", r"\bescalation\b", r"\bмобилизация\b", r"\bmobilization\b", 
        r"\bфронт\b", r"\bfrontline\b", r"\bзахват\b", r"\bcapture\b", 
        r"\bосвобождение\b", r"\bliberation\b", r"\bбой\b", r"\bbattle\b", 
        r"\bпотери\b", r"\bcasualties\b", r"\bпогиб\b", r"\bkilled\b", 
        r"\bранен\b", r"\binjured\b", r"\bпленный\b", r"\bprisoner of war\b", 
        r"\bпереговоры\b", r"\btalks\b", r"\bперемирие\b", r"\bceasefire\b", 
        r"\bсанкции\b", r"\bsanctions\b", r"\bоружие\b", r"\bweapons\b", 
        r"\bпоставки\b", r"\bsupplies\b", r"\bhimars\b", r"\batacms\b"
    ],
    "crypto": [
        r"\bbitcoin\b", r"\bbtc\b", r"\bбиткоин\b", r"\b比特币\b", 
        r"\bethereum\b", r"\beth\b", r"\bэфир\b", r"\b以太坊\b", 
        r"\bbinance coin\b", r"\bbnb\b", r"\busdt\b", r"\btether\b", 
        r"\bxrp\b", r"\bripple\b", r"\bcardano\b", r"\bada\b", 
        r"\bsolana\b", r"\bsol\b", r"\bdoge\b", r"\bdogecoin\b", 
        r"\bavalanche\b", r"\bavax\b", r"\bpolkadot\b", r"\bdot\b", 
        r"\bchainlink\b", r"\blink\b", r"\btron\b", r"\btrx\b", 
        r"\bcbdc\b", r"\bcentral bank digital currency\b", r"\bцифровой рубль\b", 
        r"\bdigital yuan\b", r"\beuro digital\b", r"\bdefi\b", r"\bдецентрализованные финансы\b", 
        r"\bnft\b", r"\bnon-fungible token\b", r"\bsec\b", r"\bцб рф\b", 
        r"\bрегуляция\b", r"\bregulation\b", r"\bзапрет\b", r"\bban\b", 
        r"\bмайнинг\b", r"\bmining\b", r"\bhalving\b", r"\bхалвинг\b", 
        r"\bволатильность\b", r"\bvolatility\b", r"\bcrash\b", r"\bкрах\b"
    ],
    "pandemic": [
        r"\bpandemic\b", r"\bпандемия\b", r"\b疫情\b", r"\bجائحة\b", 
        r"\boutbreak\b", r"\bвспышка\b", r"\bэпидемия\b", r"\bepidemic\b", 
        r"\bvirus\b", r"\bвирус\b", r"\bвирусы\b", r"\b变异株\b", 
        r"\bvaccine\b", r"\bвакцина\b", r"\b疫苗\b", r"\bلقاح\b", 
        r"\bbooster\b", r"\bбустер\b", r"\bревакцинация\b", 
        r"\bquarantine\b", r"\bкарантин\b", r"\b隔离\b", r"\bحجر صحي\b", 
        r"\blockdown\b", r"\bлокдаун\b", r"\b封锁\b", 
        r"\bmutation\b", r"\bмутация\b", r"\b变异\b", 
        r"\bstrain\b", r"\bштамм\b", r"\bomicron\b", r"\bdelta\b", 
        r"\bbiosafety\b", r"\bбиобезопасность\b", r"\b生物安全\b", 
        r"\blab leak\b", r"\bлабораторная утечка\b", r"\b实验室泄漏\b", 
        r"\bgain of function\b", r"\bусиление функции\b", 
        r"\bwho\b", r"\bвоз\b", r"\bcdc\b", r"\bроспотребнадзор\b", 
        r"\binfection rate\b", r"\bзаразность\b", r"\b死亡率\b", 
        r"\bhospitalization\b", r"\bгоспитализация\b"
    ]
}

# === ФУНКЦИИ ПЕРЕВОДА С ИСПРАВЛЕННЫМ URL ===
async def translate_to_russian(text: str) -> str:
    """Перевод текста на русский язык с правильным URL"""
    if not text or len(text) < 5:
        return text
    
    # Если уже на русском - возвращаем как есть
    if re.search(r'[а-яё]', text[:100]):
        return text
    
    # ИСПРАВЛЕНО: Правильный URL для LibreTranslate
    translate_url = "https://libretranslate.de/translate"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                translate_url,
                json={
                    "q": text[:500],
                    "source": "auto",
                    "target": "ru"
                },
                timeout=15
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("translatedText", text)
                else:
                    logger.warning(f"⚠️ LibreTranslate вернул статус {response.status}")
    except Exception as e:
        logger.warning(f"❌ Ошибка LibreTranslate: {str(e)}")
    
    # Резервный вариант - Google Translate
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "sl": "auto",
            "tl": "ru",
            "q": text[:500],
            "client": "gtx"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params=params,
                timeout=10
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    translated = ""
                    for item in data[0]:
                        if item[0]:
                            translated += item[0]
                    return translated if translated else text
    except Exception as e:
        logger.warning(f"❌ Ошибка Google Translate: {str(e)}")
    
    return text

# === ПРОВЕРКА ДОСТУПНОСТИ ИСТОЧНИКОВ ===
async def check_sources_availability():
    """Проверка доступности всех RSS-лент"""
    logger.info("🔍 Проверка доступности источников...")
    unavailable = []
    
    async with aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0'}) as session:
        for source in SOURCES:
            try:
                async with session.get(source["url"], timeout=8) as response:
                    if response.status != 200:
                        unavailable.append(f"{source['name']} ({response.status})")
            except Exception as e:
                unavailable.append(f"{source['name']} (ошибка: {str(e)})")
    
    if unavailable:
        logger.warning(f"⚠️ Недоступные источники: {', '.join(unavailable)}")
    else:
        logger.info("✅ Все источники доступны")

# === ОСНОВНЫЕ ФУНКЦИИ ===
async def get_articles():
    """Получение статей из всех источников"""
    await check_sources_availability()
    articles = []
    
    for source in SOURCES:
        try:
            async with aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0'}) as session:
                async with session.get(source["url"], timeout=10) as response:
                    if response.status != 200:
                        logger.warning(f"⚠️ {source['name']} недоступен (статус {response.status})")
                        continue
                    
                    content = await response.text()
                    feed = feedparser.parse(content)
                    
                    if not feed.entries:
                        logger.warning(f"⚠️ {source['name']}: пустая RSS-лента")
                        continue
                    
                    logger.info(f"✅ {source['name']}: получено {min(3, len(feed.entries))} статей")
                    
                    for entry in feed.entries[:3]:
                        lead = ""
                        if hasattr(entry, 'summary'):
                            lead = entry.summary[:300] + "..." if entry.summary else ""
                        
                        # Переводим только если текст на другом языке
                        translated_title = await translate_to_russian(entry.title)
                        translated_lead = await translate_to_russian(lead) if lead else ""
                        
                        articles.append({
                            "title": translated_title,
                            "url": entry.link,
                            "source": source["name"],
                            "lead": translated_lead,
                            "original_lang": "ru" if re.search(r'[а-яё]', entry.title[:100]) else "other"
                        })
        except Exception as e:
            logger.error(f"❌ Ошибка обработки {source['name']}: {str(e)}")
    
    logger.info(f"📊 Всего получено: {len(articles)} статей")
    return articles

def detect_category(text: str) -> str:
    """Определение категории по обновленным фильтрам"""
    text_lower = text.lower()
    
    for category, patterns in FILTERS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE | re.UNICODE):
                return category
    return None

# === ОТПРАВКА В TELEGRAM ===
async def send_to_telegram(article: dict, category: str):
    """Отправка сообщения в Telegram каналы"""
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
            logger.info(f"✅ Отправлено в {channel}: {article['title'][:30]}...")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в {channel}: {str(e)}")

# === ОСНОВНОЙ ЦИКЛ ===
async def main():
    """Основной цикл работы бота"""
    try:
        logger.info("🚀 Запуск бота с обновленными фильтрами")
        
        articles = await get_articles()
        sent_count = 0
        
        for article in articles:
            # Проверка дубликатов
            exists = SUPABASE.table("news_articles").select("id").eq("url", article["url"]).execute()
            if exists.data:
                logger.info(f"♻️ Дубликат: {article['url']}")
                continue
            
            # Определение категории
            full_text = f"{article['title']} {article.get('lead', '')}"
            category = detect_category(full_text)
            
            if not category:
                logger.debug(f"❌ Не соответствует фильтрам: {article['title'][:50]}...")
                continue
            
            # Отправка и сохранение
            await send_to_telegram(article, category)
            sent_count += 1
            
            SUPABASE.table("news_articles").insert({
                "title": article["title"],
                "source_name": article["source"],
                "url": article["url"],
                "category": category,
                "published_at": datetime.utcnow().isoformat()
            }).execute()
            
            await asyncio.sleep(1.5)
        
        logger.info(f"🎉 Обработка завершена! Отправлено: {sent_count} статей из {len(articles)}")
        
    except Exception as e:
        logger.exception(f"🔥 Фатальная ошибка: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
