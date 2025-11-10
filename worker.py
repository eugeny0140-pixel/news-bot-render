import os
import re
import asyncio
import logging
from datetime import datetime, UTC
from telegram import Bot
from supabase import create_client
import aiohttp
import feedparser
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import html

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === КОНФИГУРАЦИЯ ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_IDS = [os.getenv("CHANNEL_ID1"), os.getenv("CHANNEL_ID2")]
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PORT = int(os.getenv("PORT", 10000))

# Проверка обязательных переменных
required_vars = ["TELEGRAM_TOKEN", "CHANNEL_ID1", "SUPABASE_URL", "SUPABASE_KEY"]
missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    logger.error(f"❌ Отсутствуют обязательные переменные: {', '.join(missing_vars)}")
    exit(1)

# Инициализация сервисов
BOT = Bot(token=TELEGRAM_TOKEN)
SUPABASE = create_client(SUPABASE_URL, SUPABASE_KEY)

# === РАБОЧИЕ ИСТОЧНИКИ (проверены 11.11.2025) ===
SOURCES = [
    {"name": "GOODJUDGMENT", "rss": "https://goodjudgment.com/feed/"},
    {"name": "JOHNSHOPKINS", "rss": "https://www.centerforhealthsecurity.org/feed.xml"},
    {"name": "METACULUS", "rss": "https://www.metaculus.com/feed/"},
    {"name": "DNI", "rss": "https://www.dni.gov/index.php/gt2040/feed"},
    {"name": "RAND", "rss": "https://www.rand.org/rss/news.html"},
    {"name": "WEF", "rss": "https://www.weforum.org/feed"},
    {"name": "CSIS", "rss": "https://www.csis.org/rss/all.xml"},
    {"name": "ATLANTICCOUNCIL", "rss": "https://www.atlanticcouncil.org/feed/"},
    {"name": "CHATHAMHOUSE", "rss": "https://www.chathamhouse.org/feed"},
    {"name": "ECONOMIST", "rss": "https://www.economist.com/the-world-this-week/rss.xml"},
    {"name": "BLOOMBERG", "rss": "https://feeds.bloomberg.com/politics/news.rss"},
    {"name": "REUTERS", "rss": "https://reutersinstitute.politics.ox.ac.uk/rss.xml"},
    {"name": "FOREIGNAFFAIRS", "rss": "https://www.foreignaffairs.com/rss.xml"},
    {"name": "CFR", "rss": "https://www.cfr.org/rss.xml"},
    {"name": "BBC", "rss": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "FUTURETIMELINE", "rss": "https://www.futuretimeline.net/blog/feed/feed.xml"},
    {"name": "CARNEGIE", "rss": "https://carnegieendowment.org/news/rss.xml"},
    {"name": "BRUEGEL", "rss": "https://www.bruegel.org/blog/feed"},
    {"name": "E3G", "rss": "https://www.e3g.org/feed/"}
]

# === ФИЛЬТРЫ ПО РОССИИ И УКРАИНЕ ===
FILTERS = {
    "SVO": [
        r"\brussia\b", r"\brussian\b", r"\bputin\b", r"\bmoscow\b", r"\bkremlin\b",
        r"\bukraine\b", r"\bukrainian\b", r"\bzelensky\b", r"\bkyiv\b", r"\bkiev\b",
        r"\bcrimea\b", r"\bdonbas\b", r"\bsanction[s]?\b", r"\bgazprom\b",
        r"\bnord\s?stream\b", r"\bwagner\b", r"\blavrov\b", r"\bshoigu\b",
        r"\bmedvedev\b", r"\bpeskov\b", r"\bnato\b", r"\beuropa\b", r"\busa\b",
        r"\bsoviet\b", r"\bussr\b", r"\bpost\W?soviet\b",
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
        r"\brussia\b", r"\brussian\b", r"\bputin\b", r"\bmoscow\b", r"\bkremlin\b",
        r"\bцифровой рубль\b", r"\bsanction[s]?\b", r"\bcbr\b", r"\bроссии\b",
        r"\bbitcoin\b", r"\bbtc\b", r"\bбиткоин\b", r"\b比特币\b", 
        r"\bethereum\b", r"\beth\b", r"\bэфир\b", r"\b以太坊\b", 
        r"\bbinance\b", r"\bbnb\b", r"\busdt\b", r"\btether\b", 
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
    ]
}

# === ФУНКЦИИ ОЧИСТКИ И ПЕРЕВОДА ===
def clean_html(raw: str) -> str:
    """Удаляет HTML-теги и специальные символы."""
    if not raw:
        return ""
    # Удаляем HTML теги
    text = re.sub(r'<[^>]+>', '', raw)
    # Заменяем HTML сущности
    text = html.unescape(text)
    # Удаляем лишние пробелы и переносы
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:1000]  # Ограничиваем длину

async def translate_to_russian(text: str) -> str:
    """Перевод текста на русский язык"""
    if not text or len(text) < 5:
        return text
    
    # Если уже на русском - возвращаем как есть
    if re.search(r'[а-яё]', text[:100]):
        return text
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://libretranslate.de/translate",  # ИСПРАВЛЕНО: правильный URL
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
    except Exception as e:
        logger.warning(f"❌ Ошибка LibreTranslate: {str(e)}")
    
    return text

# === ПРОВЕРКА ДОСТУПНОСТИ ИСТОЧНИКОВ ===
async def check_sources():
    """Проверка доступности всех RSS-лент"""
    logger.info("🔍 Проверка доступности источников...")
    available = []
    
    async with aiohttp.ClientSession(headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }) as session:
        tasks = []
        for source in SOURCES:
            tasks.append(session.get(source["rss"], timeout=10))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            source_name = SOURCES[i]["name"]
            if isinstance(result, Exception):
                logger.warning(f"⚠️ {source_name}: недоступен ({str(result)})")
            elif result.status == 200:
                available.append(source_name)
                logger.info(f"✅ {source_name}: доступен")
            else:
                logger.warning(f"⚠️ {source_name}: статус {result.status}")
    
    logger.info(f"📊 Рабочих источников: {len(available)} из {len(SOURCES)}")
    return available

# === ОСНОВНЫЕ ФУНКЦИИ ===
async def get_articles(available_sources):
    """Получение статей из доступных источников"""
    articles = []
    
    for source in SOURCES:
        if source["name"] not in available_sources:
            continue
            
        try:
            async with aiohttp.ClientSession(headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }) as session:
                async with session.get(source["rss"], timeout=15) as response:
                    if response.status != 200:
                        continue
                    
                    content = await response.text()
                    feed = feedparser.parse(content)
                    
                    logger.info(f"📰 {source['name']}: получено {len(feed.entries)} записей")
                    
                    for entry in feed.entries[:2]:  # Берем только 2 самые свежие
                        title = clean_html(entry.get("title", ""))
                        url = entry.get("link", "").strip()
                        lead = ""
                        
                        # Получаем лид из разных возможных полей
                        for field in ["summary", "description", "content"]:
                            if hasattr(entry, field):
                                content_value = entry.get(field, "")
                                if isinstance(content_value, list):
                                    content_value = content_value[0].get("value", "") if content_value else ""
                                if content_value:
                                    lead = clean_html(content_value)
                                    break
                        
                        # Ограничиваем лид 300 символами
                        lead = lead[:300] + "..." if len(lead) > 300 else lead
                        
                        # Пропускаем пустые статьи
                        if not title or not url or not lead:
                            continue
                        
                        # Переводим заголовок и лид
                        translated_title = await translate_to_russian(title)
                        translated_lead = await translate_to_russian(lead)
                        
                        articles.append({
                            "title": translated_title,
                            "url": url,
                            "source": source["name"],
                            "lead": translated_lead
                        })
        except Exception as e:
            logger.error(f"❌ Ошибка обработки {source['name']}: {str(e)}")
    
    logger.info(f"✨ Получено статей для обработки: {len(articles)}")
    return articles

def detect_category(text: str) -> str:
    """Определение категории ТОЛЬКО при упоминании России/Украины"""
    text_lower = text.lower()
    
    # Проверяем только две категории
    for category, patterns in FILTERS.items():
        if any(re.search(pattern, text_lower, re.IGNORECASE | re.UNICODE) for pattern in patterns):
            return category
    return None

async def send_to_telegram(article: dict, category: str):
    """Отправка сообщения в Telegram каналы"""
    # Форматируем сообщение с экранированием специальных символов
    message = (
        f"<b>{article['source']}</b>: {html.escape(article['title'])}\n\n"
        f"{html.escape(article['lead'])}\n\n"
        f"Источник: {article['url']}"
    )
    
    for channel_id in CHANNEL_IDS:
        if not channel_id:
            continue
            
        try:
            await BOT.send_message(
                chat_id=channel_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"✅ Отправлено в {channel_id}: {article['title'][:30]}...")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в {channel_id}: {str(e)}")

# === HTTP-сервер для Render (health check) ===
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ["/", "/health"]:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

def run_http_server():
    server = HTTPServer(("", PORT), HealthCheckHandler)
    logger.info(f"🌐 Health check server запущен на порту {PORT}")
    server.serve_forever()

# === ОСНОВНОЙ ЦИКЛ ===
async def main():
    """Основной цикл работы бота"""
    try:
        logger.info("🚀 Запуск бота с фильтрами по России/Украине")
        
        # Запускаем HTTP-сервер в отдельном потоке для health check
        http_thread = threading.Thread(target=run_http_server, daemon=True)
        http_thread.start()
        
        # Проверка доступности источников
        available_sources = await check_sources()
        if not available_sources:
            logger.error("❌ Нет доступных источников! Завершение работы.")
            return
        
        # Получение статей
        articles = await get_articles(available_sources)
        sent_count = 0
        
        for article in articles:
            # Проверка дубликатов
            exists = SUPABASE.table("news_articles").select("id").eq("url", article["url"]).execute()
            if exists.
                logger.info(f"♻️ Дубликат: {article['url']}")
                continue
            
            # Определение категории (только SVO и crypto)
            full_text = f"{article['title']} {article.get('lead', '')}"
            category = detect_category(full_text)
            
            if not category:
                logger.debug(f"❌ Не соответствует фильтрам: {article['title'][:50]}...")
                continue
            
            # Отправка и сохранение
            await send_to_telegram(article, category)
            sent_count += 1
            
            # Сохраняем в базу с правильной категорией
            SUPABASE.table("news_articles").insert({
                "title": article["title"],
                "source_name": article["source"],
                "url": article["url"],
                "category": category,
                "published_at": datetime.now(UTC).isoformat()  # ИСПРАВЛЕНО: устаревший метод
            }).execute()
            
            await asyncio.sleep(1.5)
        
        logger.info(f"🎉 Обработка завершена! Отправлено: {sent_count} статей из {len(articles)}")
        
    except Exception as e:
        logger.exception(f"🔥 Фатальная ошибка: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
