import os
import time
import logging
import re
import feedparser
import requests
import html  # Добавлен для декодирования HTML-сущностей
from deep_translator import GoogleTranslator, MyMemoryTranslator
from supabase import create_client

# === Логирование ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# === Настройки ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_IDS = [cid.strip() for cid in os.getenv("CHANNEL_ID1", "").split(",") if cid.strip()]
if os.getenv("CHANNEL_ID2"):
    CHANNEL_IDS.extend([cid.strip() for cid in os.getenv("CHANNEL_ID2").split(",") if cid.strip()])

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# === Проверка настроек ===
for var in ["TELEGRAM_BOT_TOKEN", "CHANNEL_ID1", "SUPABASE_URL", "SUPABASE_KEY"]:
    if not os.getenv(var):
        logger.error(f"❌ Обязательная переменная {var} не задана!")
        exit(1)

# === Подключение к Supabase ===
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    supabase.table("published_articles").select("url").limit(1).execute()
    logger.info("✅ Supabase подключён")
except Exception as e:
    logger.error(f"❌ Supabase ошибка: {e}")
    exit(1)

# === Источники (с короткими префиксами) ===
# Убраны Bruegel и Carnegie из-за ошибок
SOURCES = [
    {"name": "E3G", "rss": "https://www.e3g.org/feed/"},
    {"name": "Foreign Affairs", "rss": "https://www.foreignaffairs.com/rss.xml"},
    {"name": "Reuters Institute", "rss": "https://reutersinstitute.politics.ox.ac.uk/feed"},
    # {"name": "Bruegel", "rss": "https://www.bruegel.org/rss"}, # Закомментирован из-за защиты
    {"name": "Chatham House", "rss": "https://www.chathamhouse.org/feed"},
    {"name": "CSIS", "rss": "https://www.csis.org/rss.xml"},
    {"name": "Atlantic Council", "rss": "https://www.atlanticcouncil.org/feed/"},
    {"name": "RAND", "rss": "https://www.rand.org/rss/recent.xml"},
    {"name": "CFR", "rss": "https://www.cfr.org/rss.xml"},
    # {"name": "Carnegie", "rss": "https://carnegieendowment.org/rss"}, # Закомментирован из-за 404
    {"name": "ECONOMIST", "rss": "https://www.economist.com/rss/the_world_this_week_rss.xml"},
    {"name": "BLOOMBERG", "rss": "https://www.bloomberg.com/politics/feeds/site.xml"},
    # Добавленные источники
    {"name": "BBC Future", "rss": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml"},
    {"name": "Future Timeline", "rss": "http://futuretimeline.net/blog.rss"},
]

# === Вспомогательные функции ===
def clean_html(raw: str) -> str:
    """Удаляет HTML-теги и декодирует HTML-сущности."""
    if not raw:
        return ""
    # Сначала удаляем теги
    text = re.sub(r'<[^>]+>', '', raw)
    # Затем декодируем сущности типа &nbsp; -> пробел
    text = html.unescape(text)
    # Заменяем множественные пробелы и переносы на один пробел
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def translate(text: str) -> str:
    if not text.strip():
        return ""
    try:
        return GoogleTranslator(source='auto', target='ru').translate(text)
    except Exception as e:
        logger.warning(f"GoogleTranslate failed: {e}. Trying MyMemory.")
        try:
            return MyMemoryTranslator(source='auto', target='ru').translate(text)
        except:
            return text

def is_relevant(title: str, desc: str) -> bool:
    """
    Проверяет, содержит ли текст (заголовок + описание) хотя бы одно ключевое слово.
    Использует простой поиск подстроки для надежности.
    """
    text = (title + " " + desc).lower()
    # Простые ключевые слова для поиска (подстроки)
    keywords = [
        "russia", "russian", "putin", "moscow", "kremlin",
        "ukraine", "ukrainian", "zelensky", "kyiv", "kiev",
        "crimea", "donbas", "sanction", "gazprom",
        "nord stream", "wagner", "lavrov", "shoigu",
        "medvedev", "peskov", "nato", "europa", "usa",
        "soviet", "ussr", "post-soviet",
        # СВО
        "svo", "спецоперация", "special military operation",
        "война", "war", "conflict", "конфликт",
        "наступление", "offensive", "атака", "attack",
        "удар", "strike", "обстрел", "shelling",
        "дрон", "drone", "missile", "ракета",
        "эскалация", "escalation", "мобилизация", "mobilization",
        "фронт", "frontline", "захват", "capture",
        "освобождение", "liberation", "бой", "battle",
        "потери", "casualties", "погиб", "killed",
        "ранен", "injured", "пленный", "prisoner of war",
        "переговоры", "talks", "перемирие", "ceasefire",
        "санкции", "sanctions", "оружие", "weapons",
        "поставки", "supplies", "himars", "atacms",
        # Криптовалюта
        "bitcoin", "btc", "биткоин", "ethereum", "eth",
        "binance coin", "bnb", "usdt", "tether",
        "xrp", "ripple", "cardano", "ada",
        "solana", "sol", "doge", "dogecoin",
        "avalanche", "avax", "polkadot", "dot",
        "chainlink", "link", "tron", "trx",
        "cbdc", "central bank digital currency", "цифровой рубль",
        "digital yuan", "euro digital", "defi", "децентрализованные финансы",
        "nft", "non-fungible token", "sec", "цб рф",
        "регуляция", "regulation", "запрет", "ban",
        "майнинг", "mining", "halving", "халвинг",
        "волатильность", "volatility", "crash", "крах",
    ]
    return any(kw in text for kw in keywords)

def is_generic(desc: str) -> bool:
    return any(phrase in desc.lower() for phrase in ["appeared first", "read more", "©", "all rights"])

def is_article_sent(url: str) -> bool:
    try:
        resp = supabase.table("published_articles").select("url").eq("url", url).execute()
        return len(resp.data) > 0
    except Exception as e:
        logger.error(f"Supabase check error: {e}")
        return False

def mark_article_sent(url: str, title: str):
    try:
        supabase.table("published_articles").insert({"url": url, "title": title}).execute()
        logger.info(f"✅ Saved: {url}")
    except Exception as e:
        logger.error(f"Supabase insert error: {e}")

def send_to_telegram(prefix: str, title: str, lead: str, url: str):
    try:
        title_ru = translate(title)
        lead_ru = translate(lead)
        message = f"<b>{prefix}</b>: {title_ru}\n\n{lead_ru}\n\nИсточник: {url}"

        for ch in CHANNEL_IDS:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": ch,
                    "text": message,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
            if resp.status_code == 200:
                logger.info(f"📤 Sent: {title[:60]}...")
            else:
                logger.error(f"❌ TG error: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.exception(f"Telegram send failed: {e}")

def fetch_and_process():
    logger.info("📡 Checking feeds...")
    for src in SOURCES:
        try:
            logger.info(f"Fetching feed from {src['name']} ({src['rss']})")
            feed = feedparser.parse(src["rss"])
            if not feed.entries:
                logger.warning(f"Feed from {src['name']} is empty or invalid.")
                continue

            for entry in feed.entries:
                url = entry.get("link", "").strip()
                if not url or is_article_sent(url):
                    continue

                title = entry.get("title", "").strip()
                desc = (entry.get("summary") or entry.get("description") or "").strip()
                desc = clean_html(desc)
                if not title or not desc or is_generic(desc):
                    continue

                if not is_relevant(title, desc):
                    continue

                lead = desc.split("\n")[0].split(". ")[0].strip()
                if not lead:
                    continue

                send_to_telegram(src["name"], title, lead, url)
                mark_article_sent(url, title)
                time.sleep(0.5)  # Пауза между отправками

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error fetching feed from {src['name']}: {e}")
        except Exception as e:
            logger.error(f"Error processing feed from {src['name']}: {e}")

    logger.info("✅ Feed check completed.")

# === Запуск ===
if __name__ == "__main__":
    logger.info("🚀 Starting Russia Monitor Bot (Background Worker)...")
    while True:
        fetch_and_process()
        logger.info("💤 Sleeping for 10 minutes...")  # Изменено на 10 минут
        time.sleep(10 * 60)  # Спим 10 минут перед следующей проверкой
