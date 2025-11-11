import os
import time
import logging
import re
import feedparser
import requests
import html
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import cloudscraper
from deep_translator import GoogleTranslator
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
required_vars = ["TELEGRAM_BOT_TOKEN", "CHANNEL_ID1", "SUPABASE_URL", "SUPABASE_KEY"]
missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    logger.error(f"❌ Отсутствуют обязательные переменные: {', '.join(missing_vars)}")
    exit(1)

# === Подключение к Supabase ===
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    # Проверка подключения с обработкой ошибок
    result = supabase.table("published_articles").select("url").limit(1).execute()
    if result.error:
        logger.warning(f"Supabase table 'published_articles' might be empty. Creating if needed.")
    logger.info("✅ Supabase подключён")
except Exception as e:
    logger.error(f"❌ Supabase ошибка: {e}")
    exit(1)

# === ВСЕ 19 ИСТОЧНИКОВ С ПРОВЕРЕННЫМИ RSS/ПАРСЕРАМИ ===
SOURCES = [
    # 1. Good Judgment (Платформа superforecasting)
    {"name": "Good Judgment", "rss": "https://goodjudgment.com/blog/feed/", "parser": "rss"},
    
    # 2. Johns Hopkins (Академический think-tank)
    {"name": "Johns Hopkins", "url": "https://www.centerforhealthsecurity.org/news/", "parser": "johns_hopkins"},
    
    # 3. Metaculus (Онлайн-платформа)
    {"name": "Metaculus", "rss": "https://metaculus.com/feed/updates/", "parser": "rss"},
    
    # 4. DNI Global Trends (Гос. think-tank)
    {"name": "DNI Global Trends", "url": "https://www.dni.gov/index.php/global-trends", "parser": "dni"},
    
    # 5. RAND Corporation (Think-tank)
    {"name": "RAND", "rss": "https://www.rand.org/rss.xml", "parser": "rss"},
    
    # 6. World Economic Forum (Think-tank/форум)
    {"name": "World Economic Forum", "rss": "https://www.weforum.org/agenda/archive/feed", "parser": "rss"},
    
    # 7. CSIS (Think-tank)
    {"name": "CSIS", "rss": "https://www.csis.org/rss.xml", "parser": "rss"},
    
    # 8. Atlantic Council (Think-tank)
    {"name": "Atlantic Council", "rss": "https://www.atlanticcouncil.org/feed/", "parser": "rss"},
    
    # 9. Chatham House (Think-tank)
    {"name": "Chatham House", "rss": "https://www.chathamhouse.org/feed", "parser": "rss"},
    
    # 10. The Economist (Журнал)
    {"name": "ECONOMIST", "rss": "https://www.economist.com/the-world-this-week/rss.xml", "parser": "rss"},
    
    # 11. Bloomberg (Онлайн/broadcaster)
    {"name": "BLOOMBERG", "rss": "https://www.bloomberg.com/feed/politics", "parser": "rss"},
    
    # 12. Reuters Institute (Академический/онлайн)
    {"name": "Reuters Institute", "rss": "https://reutersinstitute.politics.ox.ac.uk/feed", "parser": "rss"},
    
    # 13. Foreign Affairs (Журнал)
    {"name": "Foreign Affairs", "rss": "https://www.foreignaffairs.com/rss.xml", "parser": "rss"},
    
    # 14. CFR (Think-tank)
    {"name": "CFR", "rss": "https://www.cfr.org/rss.xml", "parser": "rss"},
    
    # 15. BBC Future (Broadcaster/онлайн)
    {"name": "BBC Future", "rss": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "parser": "rss"},
    
    # 16. Future Timeline (Нишевый блог)
    {"name": "Future Timeline", "rss": "http://futuretimeline.net/blog.rss", "parser": "rss"},
    
    # 17. Carnegie Endowment (Think-tank)
    {"name": "Carnegie", "url": "https://carnegieendowment.org/publications/", "parser": "carnegie"},
    
    # 18. Bruegel (Think-tank)
    {"name": "Bruegel", "search_url": "https://www.bruegel.org/search?search_term=russia", "parser": "bruegel"},
    
    # 19. E3G (Think-tank)
    {"name": "E3G", "rss": "https://www.e3g.org/feed/", "parser": "rss"},
]

# === СТРОГИЕ КЛЮЧЕВЫЕ СЛОВА ТОЛЬКО ПРО РОССИЮ ===
RUSSIA_KEYWORDS = [
    r"\brussia\b", r"\brussian\b", r"\bputin\b", r"\bmoscow\b", r"\bkremlin\b",
    r"\bukraine\b", r"\bukrainian\b", r"\bzelensky\b", r"\bkyiv\b", r"\bkiev\b",
    r"\bcrimea\b", r"\bdonbas\b", r"\bsanction[s]?\b", r"\bgazprom\b",
    r"\bnord\s?stream\b", r"\bwagner\b", r"\blavrov\b", r"\bshoigu\b",
    r"\bmedvedev\b", r"\bpeskov\b", r"\brussian army\b",
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
    r"\bпоставки\b", r"\bsupplies\b", r"\bhimars\b", r"\batacms\b",
]

def clean_html(raw: str) -> str:
    """Удаляет HTML-теги и декодирует HTML-сущности."""
    if not raw:
        return ""
    # Удаляем теги
    text = re.sub(r'<[^>]+>', '', raw)
    # Декодируем сущности
    text = html.unescape(text)
    # Заменяем множественные пробелы
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def translate(text: str) -> str:
    if not text.strip():
        return ""
    try:
        translator = GoogleTranslator(source='auto', target='ru')
        return translator.translate(text)
    except Exception as e:
        logger.warning(f"GoogleTranslate failed: {e}. Using original text.")
        return text

def is_about_russia(title: str, desc: str) -> bool:
    """Строгая проверка на наличие упоминаний о России в статье"""
    text = (title + " " + desc).lower()
    
    # Проверяем наличие ключевых слов про Россию
    has_russia_keywords = any(re.search(pattern, text) for pattern in RUSSIA_KEYWORDS)
    
    if not has_russia_keywords:
        return False
    
    # Проверяем отрицательный контекст (Россия упоминается только для сравнения)
    negative_context = [
        r"\bnot russia\b", r"\bnot russian\b", r"\brather than russia\b",
        r"\bcompared to russia\b", r"\bunlike russia\b", r"\bvs russia\b",
        r"\bcompared with russia\b", r"\bin contrast to russia\b",
        r"\bno russia\b", r"\bno russian\b", r"\bwithout russia\b"
    ]
    
    if any(re.search(pattern, text) for pattern in negative_context):
        logger.debug(f"❌ Отфильтровано (негативный контекст): {title}")
        return False
    
    # Дополнительная проверка: ключевые слова должны быть в начале текста
    first_300_chars = text[:300].lower()
    has_keywords_in_beginning = any(re.search(pattern, first_300_chars) for pattern in RUSSIA_KEYWORDS)
    
    return has_keywords_in_beginning

def is_article_sent(url: str) -> bool:
    try:
        resp = supabase.table("published_articles").select("url").eq("url", url).execute()
        if resp.error:
            logger.error(f"Supabase error checking URL {url}: {resp.error}")
            return False
        return len(resp.data) > 0
    except Exception as e:
        logger.error(f"Supabase check error for {url}: {e}")
        return False

def mark_article_sent(url: str, title: str):
    try:
        resp = supabase.table("published_articles").insert({"url": url, "title": title}).execute()
        if resp.error:
            logger.error(f"Supabase error inserting {url}: {resp.error}")
        else:
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
                logger.error(f"❌ TG error: {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        logger.exception(f"Telegram send failed: {e}")

# === Специализированные парсеры для проблемных источников ===
def parse_johns_hopkins():
    """Парсер для Johns Hopkins Center for Health Security"""
    url = "https://www.centerforhealthsecurity.org/news/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        # Обновленные селекторы для текущей верстки
        for article in soup.select('.item.news'):
            title_elem = article.select_one('h3.title a')
            if not title_elem:
                continue
                
            title = title_elem.get_text().strip()
            link = "https://www.centerforhealthsecurity.org" + title_elem['href']
            desc_elem = article.select_one('.description')
            desc = desc_elem.get_text().strip() if desc_elem else ""
            date_elem = article.select_one('.date')
            pub_date = date_elem.get_text().strip() if date_elem else ""
            
            entries.append({
                'title': title,
                'link': link,
                'summary': desc,
                'published': pub_date
            })
        
        feed = feedparser.FeedParserDict(entries=entries)
        return feed
    except Exception as e:
        logger.error(f"Johns Hopkins parsing error: {e}")
        return feedparser.FeedParserDict(entries=[])

def parse_dni():
    """Парсер для DNI Global Trends"""
    url = "https://www.dni.gov/index.php/global-trends"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        # Ищем статьи, связанные с Россией
        for article in soup.select('.item'):
            title_elem = article.select_one('h3 a')
            if not title_elem:
                continue
                
            title = title_elem.get_text().strip()
            link = "https://www.dni.gov" + title_elem['href'] if not title_elem['href'].startswith('http') else title_elem['href']
            desc_elem = article.select_one('.description')
            desc = desc_elem.get_text().strip() if desc_elem else ""
            
            # Фильтруем только статьи про Россию
            if "russia" in title.lower() or "russia" in desc.lower() or "putin" in title.lower():
                entries.append({
                    'title': title,
                    'link': link,
                    'summary': desc,
                    'published': time.strftime("%Y-%m-%d")
                })
        
        feed = feedparser.FeedParserDict(entries=entries)
        return feed
    except Exception as e:
        logger.error(f"DNI parsing error: {e}")
        return feedparser.FeedParserDict(entries=[])

def parse_carnegie():
    """Парсер для Carnegie Endowment"""
    url = "https://carnegieendowment.org/publications/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        for article in soup.select('.publications-list .item'):
            title_elem = article.select_one('.title a')
            if not title_elem:
                continue
                
            title = title_elem.get_text().strip()
            link = "https://carnegieendowment.org" + title_elem['href'] if not title_elem['href'].startswith('http') else title_elem['href']
            desc_elem = article.select_one('.summary')
            desc = desc_elem.get_text().strip() if desc_elem else ""
            date_elem = article.select_one('.date')
            date = date_elem.get_text().strip() if date_elem else ""
            
            # Фильтруем только статьи про Россию
            if "russia" in title.lower() or "russia" in desc.lower() or "putin" in title.lower() or "ukraine" in title.lower():
                entries.append({
                    'title': title,
                    'link': link,
                    'summary': desc,
                    'published': date
                })
        
        feed = feedparser.FeedParserDict(entries=entries)
        return feed
    except Exception as e:
        logger.error(f"Carnegie parsing error: {e}")
        return feedparser.FeedParserDict(entries=[])

def parse_bruegel():
    """Парсер для Bruegel (обход Cloudflare)"""
    url = "https://www.bruegel.org/search?search_term=russia"
    scraper = cloudscraper.create_scraper()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = scraper.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        for result in soup.select('.search-result'):
            title_elem = result.select_one('.search-result__title a')
            if not title_elem:
                continue
                
            title = title_elem.get_text().strip()
            link = title_elem['href']
            if not link.startswith('http'):
                link = "https://www.bruegel.org" + link
                
            desc_elem = result.select_one('.search-result__summary')
            desc = desc_elem.get_text().strip() if desc_elem else ""
            
            entries.append({
                'title': title,
                'link': link,
                'summary': desc,
                'published': time.strftime("%Y-%m-%d")
            })
        
        feed = feedparser.FeedParserDict(entries=entries)
        return feed
    except Exception as e:
        logger.error(f"Bruegel parsing error: {e}")
        return feedparser.FeedParserDict(entries=[])

def fetch_feed(source):
    """Общий метод получения фида с учетом типа парсера"""
    try:
        if source['parser'] == 'rss':
            url = source['rss']
            feed = feedparser.parse(url)
            if hasattr(feed, 'bozo') and feed.bozo:
                logger.warning(f"RSS feed warning for {source['name']}: {feed.bozo_exception}")
            return feed
        elif source['parser'] == 'johns_hopkins':
            return parse_johns_hopkins()
        elif source['parser'] == 'dni':
            return parse_dni()
        elif source['parser'] == 'carnegie':
            return parse_carnegie()
        elif source['parser'] == 'bruegel':
            return parse_bruegel()
        else:
            logger.warning(f"Unknown parser type {source['parser']} for {source['name']}")
            return feedparser.FeedParserDict(entries=[])
    except Exception as e:
        logger.error(f"Error fetching {source['name']}: {e}")
        return feedparser.FeedParserDict(entries=[])

def fetch_and_process():
    logger.info("📡 Checking feeds from all 19 sources...")
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
    processed_count = 0
    sent_count = 0
    
    for src in SOURCES:
        try:
            logger.info(f"🔍 Processing {src['name']} with {src['parser']} parser")
            feed = fetch_feed(src)
            
            if not hasattr(feed, 'entries') or not feed.entries:
                logger.warning(f"❌ No entries found for {src['name']}")
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
                        pub_date = datetime.strptime(entry.published[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    except:
                        pass
                
                # Пропускаем старые статьи
                if pub_date is not None and pub_date < cutoff_date:
                    continue
                
                url = entry.get("link", "").strip()
                if not url:
                    continue
                    
                # Пропускаем уже отправленные статьи
                if is_article_sent(url):
                    continue

                title = entry.get("title", "").strip()
                desc = (entry.get("summary") or entry.get("description") or "").strip()
                desc = clean_html(desc)
                if not title or not desc:
                    continue

                # СТРОГАЯ ФИЛЬТРАЦИЯ ТОЛЬКО ПРО РОССИЮ
                if not is_about_russia(title, desc):
                    logger.debug(f"🚫 Skipped (not about Russia): {title}")
                    continue

                # Извлекаем лид из описания
                lead = desc.split("\n")[0].split(". ")[0].strip()
                if not lead:
                    continue

                send_to_telegram(src["name"], title, lead, url)
                mark_article_sent(url, title)
                sent_count += 1
                time.sleep(0.5)
                processed_count += 1

        except Exception as e:
            logger.error(f"❌ Error processing {src['name']}: {e}")

    logger.info(f"✅ Feed check completed for all sources. Processed: {processed_count} articles, Sent: {sent_count} articles.")

# === Запуск ===
if __name__ == "__main__":
    logger.info("🚀 Starting Russia Monitor Bot with all 19 sources...")
    while True:
        try:
            fetch_and_process()
        except Exception as e:
            logger.exception(f"🔥 CRITICAL ERROR in main loop: {e}")
        logger.info("💤 Sleeping for 10 minutes...")
        time.sleep(10 * 60)
