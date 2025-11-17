import os
import time
import logging
import re
import feedparser
import requests
import html
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from supabase import create_client
from deep_translator import GoogleTranslator, YandexTranslator

# === Логирование ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# === Настройки ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Новые ID каналов
CHANNEL_IDS = ["-1002923537056", "-1002914190770"]

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# === Проверка настроек ===
for var in ["TELEGRAM_BOT_TOKEN", "SUPABASE_URL", "SUPABASE_KEY"]:
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

# === Фильтры для России, СВО, криптовалют, мирового рынка и глобальных тенденций ===
SIMPLE_KEYWORDS = [
    # Россия и связанные темы
    r"russia|россий(ская|ской|скому|ских|скими|скую|ские|скими|скому|скими|ству|ства|ством|ств|ском|скими|ск|скому|ский|ских|ское|скими)\b",
    r"moscow|москв(а|у|ы|ой|е|ами|ах)\b",
    r"kremlin|кремл(ь|я|ю|ем|е|и)\b",
    r"putin|путин(а|у|ым|е|ы|ских)\b",
    r"russian|русск(ий|ого|ой|их|ие|им|ими|ому|ыми)\b",
    
    # Специальная военная операция
    r"svo|спецопераци(я|и|ей|ю|ей|ях|ями|ям)\b",
    r"special military operation\b",
    r"war|войн(а|ы|е|у|ой|ам|ами|ах)\b",
    r"conflict|конфликт(а|у|ом|е|ы|ов|ами|ах)\b",
    r"ukraine|украин(а|ы|е|у|ой|ам|ами|ах)\b",
    r"donbas|донбас(с|а|у|ом|се|сы|сов|сами|сах)\b",
    r"crimea|крым(а|у|ом|е|ы|ов|ами|ах)\b",
    r"military|воен(ные|ной|ных|ному|ными|ная|ное|ный|ным)\b",
    r"army|арми(я|и|ю|ей|е|й|ями|ях)\b",
    r"sanctions?|санкци(и|й|ям|ями|ях|ей|я|ю)\b",
    r"nato|\sн\s*а\s*т\s*о\b",
    
    # Криптовалюты
    r"crypto|крипто(валют|валюта|валюты|валюту|валютой|валютам|валютами|валютах|сеть)\b",
    r"bitcoin|биткоин(а|у|ом|е|ы|ов|ами|ах)\b",
    r"btc|eth|ethereum\b",
    r"ruble|рубль|рубля|рублей|рублем|рублям|рублями|рублях|цифровой рубль\b",
    r"blockchain|блокчейн(а|у|ом|е|ы|ов|ами|ах)\b",
    r"mining|майнинг(а|у|ом|е|и|ов|ами|ах)\b",
    
    # Мировой рынок
    r"market|рынок(а|у|ом|е|и|ов|ами|ах)\b",
    r"economy|экономик(а|и|е|у|ой|ам|ами|ах)\b",
    r"finance|финанс(ы|ов|ам|ами|ах|овая|овый|овое|овыми)\b",
    r"trade|торговл(я|и|ей|ю|е|ям|ями|ях)\b",
    r"stock|фондов(ый|ого|ому|ых|ому)\b",
    r"oil|gas|нефт(ь|и|ью|ью|ю|ями|ях)\b",
    r"energy|энергетик(а|и|е|у|ой|ам|ами|ах)\b",
    
    # Мировые тенденции
    r"geopolitic|геополитик(а|и|е|у|ой|ам|ами|ах)\b",
    r"global|глобальн(ый|ого|ому|ых|ых|ым|ыми|ом)\b",
    r"trends?|тенденци(и|й|ям|ями|ях|ей|я|ю)\b",
    r"climate|климат(а|у|ом|е|ы|ов|ами|ах)\b",
    r"ai|искусственный интеллект|машинное обучение\b",
    r"security|безопасност(ь|и|ью|ю|ях|ям|ями)\b",
    r"technology|технологи(и|й|ям|ями|ях|ей|я|ю)\b",
    r"innovation|инноваци(и|й|ям|ями|ях|ей|я|ю)\b"
]

def is_relevant_simple(text: str) -> bool:
    """Проверка на релевантность для России, СВО, криптовалют, мирового рынка и глобальных тенденций"""
    if not text or len(text) < 10:
        return False
    
    text_lower = text.lower()
    
    # Основная проверка по ключевым словам
    for pattern in SIMPLE_KEYWORDS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            # Дополнительные проверки для исключения ложных срабатываний
            if re.search(r"star wars|world of warcraft|warhammer|war of the roses|drone show|drone delivery\b(amazon|google|wing)\b", text_lower, re.IGNORECASE):
                continue
            return True
    
    return False

def safe_translate(text: str) -> str:
    """Надежный перевод с резервным переводчиком"""
    if not text.strip() or len(text) < 5:
        return text
    
    try:
        # Пробуем Google Translate
        translator = GoogleTranslator(source='auto', target='ru')
        return translator.translate(text)
    except Exception as e:
        logger.warning(f"GoogleTranslate failed: {e}. Trying Yandex.")
        try:
            # Резервный вариант: Yandex Translate (бесплатный)
            translator = YandexTranslator(source='auto', target='ru')
            return translator.translate(text)
        except Exception as e2:
            logger.warning(f"YandexTranslate also failed: {e2}. Using original text.")
            return text

# === Вспомогательные функции ===
def clean_html(raw: str) -> str:
    if not raw:
        return ""
    text = re.sub(r'<[^>]+>', '', raw)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

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
        # Переводим заголовок и описание на русский
        title_ru = safe_translate(title)
        lead_ru = safe_translate(lead)
        
        message = f"<b>{prefix}</b>: {title_ru}\n\n{lead_ru}\n\nИсточник: {url}"
        for ch in CHANNEL_IDS:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": ch,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False
                },
                timeout=10
            )
            if resp.status_code == 200:
                logger.info(f"📤 Sent: {title[:60]}...")
            else:
                logger.error(f"❌ TG error: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.exception(f"Telegram send failed: {e}")

def fetch_rss_feed(url):
    """Получение RSS-ленты"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        return feed
    except Exception as e:
        logger.error(f"RSS fetch error for {url}: {e}")
        return feedparser.FeedParserDict(entries=[])

def parse_html_feed(url, selectors):
    """Универсальный парсер HTML"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        for item in soup.select(selectors['container']):
            title_elem = item.select_one(selectors['title'])
            if not title_elem:
                continue
                
            title = title_elem.get_text().strip()
            link = title_elem['href'] if 'href' in title_elem.attrs else ""
            if link.startswith('/'):
                link = '/'.join(url.split('/')[:3]) + link
            
            desc_elem = item.select_one(selectors['desc'])
            desc = desc_elem.get_text().strip() if desc_elem else ""
            
            date_elem = item.select_one(selectors['date'])
            pub_date_str = date_elem.get_text().strip() if date_elem else datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
            
            entries.append({
                'title': title,
                'link': link,
                'summary': desc,
                'published': pub_date_str
            })
        
        feed = feedparser.FeedParserDict()
        feed.entries = entries
        return feed
    except Exception as e:
        logger.error(f"HTML parsing error for {url}: {e}")
        return feedparser.FeedParserDict(entries=[])

# === Источники (самые надежные) ===
SOURCES = [
    # 1. World Economic Forum (Основной источник)
    {"name": "WEF", "url": "https://www.weforum.org/agenda/archive/feed", "method": "rss"},
    
    # 2. Good Judgment
    {"name": "Good Judgment", "url": "https://goodjudgment.com/feed/", "method": "rss"},
    
    # 3. RAND Corporation
    {"name": "RAND", "url": "https://www.rand.org/rss/recent.xml", "method": "rss"},
    
    # 4. CSIS
    {"name": "CSIS", "url": "https://www.csis.org/rss.xml", "method": "rss"},
    
    # 5. Atlantic Council
    {"name": "Atlantic Council", "url": "https://www.atlanticcouncil.org/feed/", "method": "rss"},
    
    # 6. Chatham House
    {"name": "Chatham House", "url": "https://www.chathamhouse.org/feed", "method": "rss"},
    
    # 7. The Economist
    {"name": "Economist", "url": "https://www.economist.com/the-world-this-week/rss.xml", "method": "rss"},
    
    # 8. Bloomberg
    {"name": "Bloomberg", "url": "https://feeds.bloomberg.com/politics/news.rss", "method": "rss"},
    
    # 9. Foreign Affairs
    {"name": "Foreign Affairs", "url": "https://www.foreignaffairs.com/rss.xml", "method": "rss"},
    
    # 10. CFR
    {"name": "CFR", "url": "https://www.cfr.org/rss.xml", "method": "rss"},
    
    # 11. Carnegie Endowment (упрощенный парсер)
    {"name": "Carnegie", "url": "https://carnegieendowment.org/publications/", 
     "method": "html", 
     "selectors": {
         "container": ".views-row",
         "title": ".views-field-title a",
         "desc": ".views-field-field-pub-excerpt .field-content",
         "date": ".views-field-field-pub-date .field-content"
     }},
    
    # 12. Bruegel (упрощенный парсер)
    {"name": "Bruegel", "url": "https://www.bruegel.org/analysis", 
     "method": "html", 
     "selectors": {
         "container": ".post-item",
         "title": "h3 a",
         "desc": ".excerpt",
         "date": ".date"
     }}
]

def fetch_and_process():
    logger.info("📡 Checking feeds...")
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=3)  # Берем новости за последние 3 дня
    
    for src in SOURCES:
        try:
            logger.info(f"Fetching feed from {src['name']} (method: {src['method']})")
            feed = None
            
            # Получение данных
            if src['method'] == 'rss':
                feed = fetch_rss_feed(src['url'])
            elif src['method'] == 'html' and 'selectors' in src:
                feed = parse_html_feed(src['url'], src['selectors'])
            else:
                feed = fetch_rss_feed(src['url'])
            
            if not hasattr(feed, 'entries') or not feed.entries:
                logger.warning(f"❌ Empty or invalid feed from {src['name']}")
                continue

            for entry in feed.entries:
                # Проверка даты публикации
                pub_date = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    pub_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'published') and entry.published:
                    try:
                        pub_date = datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %z').astimezone(timezone.utc)
                    except ValueError:
                        try:
                            pub_date = datetime.strptime(entry.published, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                        except ValueError:
                            pub_date = datetime.now(timezone.utc)
                
                # Пропуск старых статей
                if pub_date and pub_date < cutoff_date:
                    continue
                
                url = entry.get("link", "").strip()
                if not url or is_article_sent(url):
                    continue

                title = entry.get("title", "").strip()
                desc = (entry.get("summary") or entry.get("description", "")).strip()
                desc = clean_html(desc)
                if not title or not desc:
                    continue

                # Дополнительная проверка на релевантность
                full_text = title + " " + desc
                if not is_relevant_simple(full_text):
                    continue

                lead = desc.split("\n")[0].split(". ")[0].strip()
                if not lead:
                    lead = desc[:120] + "..." if len(desc) > 120 else desc
                
                send_to_telegram(src["name"], title, lead, url)
                mark_article_sent(url, title)
                time.sleep(1)  # Задержка для избежания блокировки Telegram

        except Exception as e:
            logger.error(f"❌ Error on {src['name']}: {e}")

    logger.info("✅ Feed check completed.")

# === Запуск ===
if __name__ == "__main__":
    logger.info("🚀 Starting Russia Monitor Bot with translation...")
    logger.info("🔍 Using simple keyword filters for Russia/Ukraine and global topics")
    logger.info(f"✅ Sending translations to channels: {', '.join(CHANNEL_IDS)}")
    logger.info(f"⏳ Checking last 3 days of news from {len(SOURCES)} sources")
    
    while True:
        fetch_and_process()
        logger.info("💤 Sleeping for 10 minutes...")
        time.sleep(50* 60)
