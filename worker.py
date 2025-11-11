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

# === Источники (все 19) ===
SOURCES = [
    # 1. Good Judgment (Платформа superforecasting)
    {"name": "Good Judgment", "rss": "https://goodjudgment.com/feed/", "method": "rss"}, # Исправленный URL
    
    # 2. Johns Hopkins (Академический think-tank)
    {"name": "Johns Hopkins", "url": "https://www.centerforhealthsecurity.org/news/", "method": "html_parser"},
    
    # 3. Metaculus (Онлайн-платформа)
    {"name": "Metaculus", "rss": "https://metaculus.com/feed/updates/", "method": "rss"},
    
    # 4. DNI Global Trends (Гос. think-tank) - Исправлено на HTML-парсер с обработкой ошибки
    {"name": "DNI Global Trends", "url": "https://www.dni.gov/index.php/gt2040-home", "method": "html_parser"},
    
    # 5. RAND Corporation (Think-tank)
    {"name": "RAND", "rss": "https://www.rand.org/rss/recent.xml", "method": "rss"},
    
    # 6. World Economic Forum (Think-tank/форум) - Исправленный URL RSS
    {"name": "World Economic Forum", "rss": "https://www.weforum.org/feed", "method": "rss"},
    
    # 7. CSIS (Think-tank)
    {"name": "CSIS", "rss": "https://www.csis.org/rss.xml", "method": "rss"},
    
    # 8. Atlantic Council (Think-tank)
    {"name": "Atlantic Council", "rss": "https://www.atlanticcouncil.org/feed/", "method": "rss"},
    
    # 9. Chatham House (Think-tank)
    {"name": "Chatham House", "rss": "https://www.chathamhouse.org/feed", "method": "rss"},
    
    # 10. The Economist (Журнал)
    {"name": "ECONOMIST", "rss": "https://www.economist.com/the-world-this-week/rss.xml", "method": "rss"},
    
    # 11. Bloomberg (Онлайн/broadcaster)
    {"name": "BLOOMBERG", "rss": "https://feeds.bloomberg.com/markets/news.rss", "method": "rss"}, # Исправленный URL
    
    # 12. Reuters Institute (Академический/онлайн)
    {"name": "Reuters Institute", "rss": "https://reutersinstitute.politics.ox.ac.uk/feed", "method": "rss"},
    
    # 13. Foreign Affairs (Журнал)
    {"name": "Foreign Affairs", "rss": "https://www.foreignaffairs.com/rss.xml", "method": "rss"},
    
    # 14. CFR (Think-tank) - Теперь HTML-парсер
    {"name": "CFR", "url": "https://www.cfr.org/publications", "method": "html_parser"},
    
    # 15. BBC Future (Broadcaster/онлайн)
    {"name": "BBC Future", "rss": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "method": "rss"},
    
    # 16. Future Timeline (Нишевый блог) - Теперь HTML-парсер
    {"name": "Future Timeline", "url": "http://www.futuretimeline.net/", "method": "html_parser"},
    
    # 17. Carnegie Endowment (Think-tank) - Теперь HTML-парсер
    {"name": "Carnegie", "url": "https://carnegieendowment.org/publications/", "method": "html_parser"},
    
    # 18. Bruegel (Think-tank)
    {"name": "Bruegel", "url": "https://www.bruegel.org/analysis", "method": "html_parser"},
    
    # 19. E3G (Think-tank)
    {"name": "E3G", "rss": "https://www.e3g.org/feed/", "method": "rss"},
]

# === Трехэтапная фильтрация для России/Украины, СВО и крипторынка ===
# ЭТАП 1: ПОЗИТИВНАЯ ФИЛЬТРАЦИЯ
KEYWORDS = [
    # Геополитика и военные действия
    r"\b(russia|rus|российск(ая|ое|ий|их)|рф|kremlin|putin|belarus|беларусь)\b",
    r"\b(ukraine|ukrainian|kiev|kyiv|zelensk(y|yy)|donbas|crimea|kherson|kharkiv|lviv)\b",
    r"\b(russian invasion|special military operation|SVO|russo-ukrainian war|ukraine conflict)\b",
    r"\b(russian military|wagner group|prigozhin|separatists|LNR|DNR|annexation)\b",
    r"\b(ukrainian forces|ATACMS|HIMARS|f-16|patriot system|counteroffensive)\b",
    r"\b(sanctions (against|on) russia|eu sanctions|price cap|SWIFT ban)\b",
    r"\b(iaea zaporizhzhia|nuclear plant|nord stream sabotage)\b",
    
    # Крипторынок в контексте РФ/Украины
    r"\b(russia crypto|digital ruble|цифровой рубль|cbr digital assets|garantex exchange)\b",
    r"\b(ukraine crypto donations|war bonds crypto|kuna exchange|come back alive crypto)\b",
    r"\b(russian crypto ban|cbr cryptocurrency regulation|rossvyaz crypto block)\b",
    r"\b(energy crypto mining russia|iran russia crypto|belarus crypto scheme)\b",
    
    # Ключевые события и институты
    r"\b(ministry of defence ru|mod ru|rostec|alrosa|gazprom|rosneft)\b",
    r"\b(nato russia|finland nato|sweden nato|budapest memorandum)\b",
    r"\b(mobilization russia|filobank|shadow fleet|parallel imports russia)\b",
    r"\b(un vote russia|international court justice ukraine|icc putin)\b"
]

# ЭТАП 2: НЕГАТИВНАЯ ФИЛЬТРАЦИЯ (ЧЁРНЫЙ СПИСОК)
BLACKLIST = [
    # Исключение ложных срабатываний для "war"
    r"\bstar wars\b", r"\bworld of warcraft\b", r"\bwarhammer\b", r"\bwar of the roses\b",
    
    # Исключение общих крипто-новостей без связи с РФ/Укр
    r"\bbitcoin price\b.*\b(analysis|forecast|technical)\b", 
    r"\bethereum merge\b", r"\bcrypto etf approval\b", r"\bcoinbase earnings\b",
    
    # Исключение пандемий без геопривязки
    r"\bpandemic\b.*\b(flu|h5n1|mpox)\b", r"\bcovid-19\b.*\b(vaccine|variant)\b\s*[^.]*?\b(not|without)\b\s*\b(russia|ukraine)\b",
    
    # Исключение военных учений без связи с регионом
    r"\bmilitary exercise\b.*\b(nato|pacific|china|india)\b", 
    r"\bdrone show\b", r"\bnuclear safety\b.*\b(japan|fukushima)\b",
    
    # Санкции против других стран
    r"\bsanction[s]?\b.*\b(venezuela|iran|north korea|myanmar|syria|belarus)\b",
    
    # Коммерческие дроны
    r"\bdrone delivery\b.*\b(amazon|google|wing)\b"
]

# ЭТАП 3: КОНТЕКСТНАЯ ВАЛИДАЦИЯ
CONTEXT_TERMS = r"\b(russia|ukraine|belarus|kremlin|putin|zelensk(y|yy)?|donbas|crimea|kyiv|kiev|moscow|russian|ukrainian|wagner|rostec|gazprom|LNR|DNR|ukrainian territory)\b"
CONTEXT_WINDOW = 200  # символов в каждую сторону от ключевого слова
CRITICAL_TERMS = [
    r"\b(?:war|attack|strike|sanction[s]?|military|conflict|drone|missile|rocket|bomb|nuclear|bio\w*)\b",
    r"\bcrypto(?:currency)?\b",
    r"\b(?:pandemic|virus|vaccine)\b"
]

def is_relevant(text: str) -> bool:
    """Трёхэтапная фильтрация новостей"""
    text_lower = text.lower()
    
    # === ЭТАП 1: ПОЗИТИВНАЯ ФИЛЬТРАЦИЯ ===
    keyword_matches = []
    for pattern in KEYWORDS:
        matches = list(re.finditer(pattern, text_lower, re.IGNORECASE | re.UNICODE))
        if matches:
            keyword_matches.extend(matches)
    
    if not keyword_matches:
        return False
    
    # === ЭТАП 2: НЕГАТИВНАЯ ФИЛЬТРАЦИЯ ===
    for pattern in BLACKLIST:
        if re.search(pattern, text_lower, re.IGNORECASE | re.UNICODE):
            return False
    
    # === ЭТАП 3: КОНТЕКСТНАЯ ВАЛИДАЦИЯ ===
    critical_compiled = re.compile("|".join(CRITICAL_TERMS), re.IGNORECASE | re.UNICODE)
    
    for match in keyword_matches:
        start, end = match.span()
        matched_text = match.group()
        
        # Пропускаем явно геопривязанные термины (не требуют контекста)
        if re.search(r"(russia|ukraine|kremlin|putin|zelensk(y|yy)?|donbas|crimea|wagner|rostec)", matched_text, re.IGNORECASE):
            return True
        
        # Проверяем критичность термина
        if critical_compiled.search(matched_text):
            # Формируем контекстное окно
            context_start = max(0, start - CONTEXT_WINDOW)
            context_end = min(len(text_lower), end + CONTEXT_WINDOW)
            context_snippet = text_lower[context_start:context_end]
            
            # Валидация контекста
            if re.search(CONTEXT_TERMS, context_snippet, re.IGNORECASE | re.UNICODE):
                return True
        else:
            # Некритичные термины (например, "digital ruble") всегда проходят
            return True
    
    return False

# === Вспомогательные функции ===
def clean_html(raw: str) -> str:
    if not raw:
        return ""
    text = re.sub(r'<[^>]+>', '', raw)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def translate(text: str) -> str:
    if not text.strip():
        return ""
    try:
        return GoogleTranslator(source='auto', target='ru').translate(text)
    except Exception as e:
        logger.warning(f"GoogleTranslate failed: {e}. Using original text.")
        return text

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

# === Специализированные функции для парсинга ===
def fetch_rss_feed(url):
    """Стандартное получение RSS-ленты"""
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

def fetch_rss_with_fallback(url):
    """Получение RSS с резервным вариантом при ошибке"""
    try:
        return fetch_rss_feed(url)
    except Exception as e:
        logger.warning(f"RSS fallback error for {url}: {e}")
        return feedparser.FeedParserDict(entries=[])

def fetch_with_cloudscraper(url):
    """Обход защиты Cloudflare с помощью cloudscraper"""
    try:
        scraper = cloudscraper.create_scraper()
        response = scraper.get(url, timeout=15)
        response.raise_for_status()
        return feedparser.parse(response.content)
    except Exception as e:
        logger.error(f"Cloudscraper error for {url}: {e}")
        return feedparser.FeedParserDict(entries=[])

def parse_johns_hopkins():
    """Парсинг сайта Johns Hopkins Center for Health Security"""
    url = "https://www.centerforhealthsecurity.org/news/"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        # Поиск статей на странице
        for article in soup.select('.resource-item, .news-item, .list-item'):
            title_elem = article.select_one('h3 a, h2 a, .title a')
            if not title_elem:
                continue
                
            title = title_elem.get_text().strip()
            link = title_elem['href']
            # Ensure absolute URL
            if link.startswith('/'):
                link = 'https://www.centerforhealthsecurity.org' + link
            
            desc_elem = article.select_one('.summary, .excerpt, p')
            desc = desc_elem.get_text().strip() if desc_elem else ""
            
            date_elem = article.select_one('.date, time')
            pub_date_str = date_elem.get_text().strip() if date_elem else time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
            # Попробуем распарсить дату, если возможно
            pub_date_parsed = None
            try:
                # Пример формата даты на сайте: "May 15, 2024"
                pub_date_parsed = datetime.strptime(pub_date_str, "%B %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                try:
                    # Пробуем другой формат, если не подошёл
                    pub_date_parsed = datetime.strptime(pub_date_str, "%b %d, %Y").replace(tzinfo=timezone.utc)
                except ValueError:
                    # Если не получилось, используем текущее время
                    pub_date_parsed = datetime.now(timezone.utc)
            
            entries.append({
                'title': title,
                'link': link,
                'summary': desc,
                'published': pub_date_str,
                'published_parsed': pub_date_parsed.timetuple() if pub_date_parsed else None
            })
        
        feed = feedparser.FeedParserDict()
        feed.entries = entries
        return feed
    except Exception as e:
        logger.error(f"Johns Hopkins parsing error: {e}")
        return feedparser.FeedParserDict(entries=[])

def parse_dni_global_trends():
    """Парсинг сайта DNI Global Trends (обработка ошибки)"""
    url = "https://www.dni.gov/index.php/gt2040-home"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        content = response.text
        # Проверяем на наличие ошибки
        if "Reference #" in content and ("edgesuite.net" in content or "Akamai" in content):
             logger.warning(f"DNI site returned error page for {url}")
             return feedparser.FeedParserDict(entries=[])
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        # Поиск отчетов и новостей - уточнить селекторы на реальном сайте
        # На текущем сайте структура не позволяет легко извлечь статьи
        # Для примера добавим одну фиктивную запись, если страница доступна
        # В реальности нужно анализировать структуру страницы
        title = "Global Trends 2040 Report"
        link = url
        desc = "DNI Global Trends 2040 report analysis."
        pub_date_str = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
        
        entries.append({
            'title': title,
            'link': link,
            'summary': desc,
            'published': pub_date_str
        })
        
        feed = feedparser.FeedParserDict()
        feed.entries = entries
        return feed
    except requests.exceptions.RequestException as e:
        logger.error(f"DNI Global Trends network error: {e}")
        return feedparser.FeedParserDict(entries=[])
    except Exception as e:
        logger.error(f"DNI Global Trends parsing error: {e}")
        return feedparser.FeedParserDict(entries=[])

def parse_carnegie():
    """Парсинг сайта Carnegie Endowment"""
    url = "https://carnegieendowment.org/publications/"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        # Поиск публикаций - уточнён селектор
        for article in soup.select('.views-row'):
            title_elem = article.select_one('.views-field-title a')
            if not title_elem:
                continue
                
            title = title_elem.get_text().strip()
            link = title_elem['href']
            # Ensure absolute URL
            if link.startswith('/'):
                link = 'https://carnegieendowment.org' + link
            
            desc_elem = article.select_one('.views-field-field-pub-excerpt .field-content')
            desc = desc_elem.get_text().strip() if desc_elem else ""
            
            date_elem = article.select_one('.views-field-field-pub-date .field-content')
            pub_date_str = date_elem.get_text().strip() if date_elem else time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
            # Попробуем распарсить дату, если возможно
            pub_date_parsed = None
            try:
                pub_date_parsed = datetime.strptime(pub_date_str, "%B %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                try:
                    pub_date_parsed = datetime.strptime(pub_date_str, "%b %d, %Y").replace(tzinfo=timezone.utc)
                except ValueError:
                    pub_date_parsed = datetime.now(timezone.utc)
            
            # Filter for relevant topics
            if any(keyword in title.lower() or keyword in desc.lower() 
                   for keyword in ['russia', 'ukraine', 'moscow', 'kremlin', 'putin', 'eastern europe', 'eurasia', 'sanction', 'economy', 'security']):
                entries.append({
                    'title': title,
                    'link': link,
                    'summary': desc,
                    'published': pub_date_str,
                    'published_parsed': pub_date_parsed.timetuple() if pub_date_parsed else None
                })
        
        feed = feedparser.FeedParserDict()
        feed.entries = entries
        return feed
    except Exception as e:
        logger.error(f"Carnegie parsing error: {e}")
        return feedparser.FeedParserDict(entries=[])

def parse_cfr():
    """Парсинг сайта CFR"""
    url = "https://www.cfr.org/publications"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        # Поиск публикаций - уточнён селектор
        for article in soup.select('.teaser--publication'): # или '.views-row', '.publication-item'
            title_elem = article.select_one('.teaser__title a')
            if not title_elem:
                continue
                
            title = title_elem.get_text().strip()
            link = title_elem['href']
            # Ensure absolute URL
            if link.startswith('/'):
                link = 'https://www.cfr.org' + link
            
            desc_elem = article.select_one('.teaser__dek')
            desc = desc_elem.get_text().strip() if desc_elem else ""
            
            date_elem = article.select_one('.teaser__date')
            pub_date_str = date_elem.get_text().strip() if date_elem else time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
            # Попробуем распарсить дату, если возможно
            pub_date_parsed = None
            try:
                pub_date_parsed = datetime.strptime(pub_date_str, "%B %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                try:
                    pub_date_parsed = datetime.strptime(pub_date_str, "%b %d, %Y").replace(tzinfo=timezone.utc)
                except ValueError:
                    pub_date_parsed = datetime.now(timezone.utc)
            
            # Filter for relevant topics
            if any(keyword in title.lower() or keyword in desc.lower() 
                   for keyword in ['russia', 'ukraine', 'moscow', 'kremlin', 'putin', 'eastern europe', 'eurasia', 'sanction', 'economy', 'security', 'diplomacy']):
                entries.append({
                    'title': title,
                    'link': link,
                    'summary': desc,
                    'published': pub_date_str,
                    'published_parsed': pub_date_parsed.timetuple() if pub_date_parsed else None
                })
        
        feed = feedparser.FeedParserDict()
        feed.entries = entries
        return feed
    except Exception as e:
        logger.error(f"CFR parsing error: {e}")
        return feedparser.FeedParserDict(entries=[])

def parse_future_timeline():
    """Парсинг сайта Future Timeline"""
    url = "http://www.futuretimeline.net/"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        # Поиск событий на главной странице или в блоге
        # Структура сайта: .timeline-item, .blog-post, .event
        for item in soup.select('.timeline-item, .blog-post, .event'): # Уточнить селектор
            title_elem = item.select_one('h2 a, h3 a, .title a')
            if not title_elem:
                continue
                
            title = title_elem.get_text().strip()
            link = title_elem['href']
            # Ensure absolute URL
            if link.startswith('/'):
                link = 'http://www.futuretimeline.net' + link
            elif link.startswith('..'):
                 link = 'http://www.futuretimeline.net/' + link.lstrip('../')
            
            desc_elem = item.select_one('p, .summary, .content')
            desc = desc_elem.get_text().strip() if desc_elem else ""
            
            # Дата может быть в заголовке или отдельно
            date_match = re.search(r'(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{4})', title) # Пример поиска даты
            pub_date_str = date_match.group(0) if date_match else time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
            # Попробуем распарсить дату, если возможно
            pub_date_parsed = None
            try:
                if '-' in pub_date_str:
                    pub_date_parsed = datetime.strptime(pub_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                elif '/' in pub_date_str:
                    pub_date_parsed = datetime.strptime(pub_date_str, "%m/%d/%Y").replace(tzinfo=timezone.utc)
                else:
                    pub_date_parsed = datetime.strptime(pub_date_str, "%Y").replace(tzinfo=timezone.utc, month=1, day=1)
            except ValueError:
                pub_date_parsed = datetime.now(timezone.utc)
            
            # Filter for relevant topics (например, связанные с безопасностью, технологиями)
            if any(keyword in title.lower() or keyword in desc.lower() 
                   for keyword in ['security', 'technology', 'geopolitical', 'war', 'conflict', 'pandemic', 'virus', 'biosecurity', 'crypto', 'russia', 'ukraine']):
                entries.append({
                    'title': title,
                    'link': link,
                    'summary': desc,
                    'published': pub_date_str,
                    'published_parsed': pub_date_parsed.timetuple() if pub_date_parsed else None
                })
        
        feed = feedparser.FeedParserDict()
        feed.entries = entries
        return feed
    except Exception as e:
        logger.error(f"Future Timeline parsing error: {e}")
        return feedparser.FeedParserDict(entries=[])

def parse_bruegel():
    """Парсинг сайта Bruegel"""
    url = "https://www.bruegel.org/analysis"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        # Поиск статей
        for article in soup.select('.post-item, .blog-item, article'): # Уточнить селектор
            title_elem = article.select_one('h3 a, h2 a, .title a')
            if not title_elem:
                continue
                
            title = title_elem.get_text().strip()
            link = title_elem['href']
            # Ensure absolute URL
            if not link.startswith('http'):
                link = 'https://www.bruegel.org' + link
            
            desc_elem = article.select_one('.excerpt, .summary, .description, p')
            desc = desc_elem.get_text().strip() if desc_elem else ""
            
            date_elem = article.select_one('.date, time')
            pub_date_str = date_elem.get_text().strip() if date_elem else time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
            # Попробуем распарсить дату, если возможно
            pub_date_parsed = None
            try:
                pub_date_parsed = datetime.strptime(pub_date_str, "%B %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                try:
                    pub_date_parsed = datetime.strptime(pub_date_str, "%b %d, %Y").replace(tzinfo=timezone.utc)
                except ValueError:
                    pub_date_parsed = datetime.now(timezone.utc)
            
            # Filter for relevant topics
            if any(keyword in title.lower() or keyword in desc.lower() 
                   for keyword in ['russia', 'ukraine', 'sanctions', 'energy security', 'europe', 'security', 'geopolitics', 'defense', 'economy']):
                entries.append({
                    'title': title,
                    'link': link,
                    'summary': desc,
                    'published': pub_date_str,
                    'published_parsed': pub_date_parsed.timetuple() if pub_date_parsed else None
                })
        
        feed = feedparser.FeedParserDict()
        feed.entries = entries
        return feed
    except Exception as e:
        logger.error(f"Bruegel parsing error: {e}")
        return feedparser.FeedParserDict(entries=[])

def fetch_and_process():
    logger.info("📡 Checking feeds...")
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
    
    for src in SOURCES:
        try:
            logger.info(f"Fetching feed from {src['name']} (method: {src.get('method', 'unknown')})")
            feed = None
            
            # Определение метода получения данных
            if src.get('method') == 'rss':
                feed = fetch_rss_feed(src['rss'])
            elif src.get('method') == 'rss_with_fallback':
                feed = fetch_rss_with_fallback(src['rss'])
            elif src.get('method') == 'cloudscraper':
                feed = fetch_with_cloudscraper(src['rss'])
            elif src.get('method') == 'html_parser':
                if src['name'] == "Johns Hopkins":
                    feed = parse_johns_hopkins()
                elif src['name'] == "DNI Global Trends":
                    feed = parse_dni_global_trends()
                elif src['name'] == "Carnegie":
                    feed = parse_carnegie()
                elif src['name'] == "CFR":
                    feed = parse_cfr()
                elif src['name'] == "Future Timeline":
                    feed = parse_future_timeline()
                elif src['name'] == "Bruegel":
                    feed = parse_bruegel()
                else:
                    feed = feedparser.FeedParserDict(entries=[])
            else:
                if 'rss' in src:
                    feed = fetch_rss_feed(src['rss'])
                elif 'url' in src:
                    # Default to html parser if no method specified but url exists
                    if src['name'] in ["Johns Hopkins", "DNI Global Trends", "Carnegie", "CFR", "Future Timeline", "Bruegel"]:
                        if src['name'] == "Johns Hopkins":
                            feed = parse_johns_hopkins()
                        elif src['name'] == "DNI Global Trends":
                            feed = parse_dni_global_trends()
                        elif src['name'] == "Carnegie":
                            feed = parse_carnegie()
                        elif src['name'] == "CFR":
                            feed = parse_cfr()
                        elif src['name'] == "Future Timeline":
                            feed = parse_future_timeline()
                        elif src['name'] == "Bruegel":
                            feed = parse_bruegel()
                    else:
                        feed = fetch_rss_feed(src['url'])  # Try as RSS
                else:
                    logger.warning(f"No valid URL or RSS for source: {src['name']}")
                    continue
            
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
                        # Пробуем распарсить форматы, которые могут быть в RSS или HTML-парсере
                        pub_date = datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %z').astimezone(timezone.utc)
                    except ValueError:
                        try:
                            pub_date = datetime.strptime(entry.published, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                        except ValueError:
                            try:
                                pub_date = datetime.strptime(entry.published, '%Y-%m-%dT%H:%M:%S%z').astimezone(timezone.utc)
                            except ValueError:
                                try:
                                    pub_date = datetime.strptime(entry.published, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                                except ValueError:
                                    logger.warning(f"Could not parse date: {entry.get('published', 'N/A')}")
                                    pub_date = datetime.now(timezone.utc) # Если не получилось, используем текущее время
                
                # Пропуск старых статей (старше 7 дней) - ОСНОВНАЯ ПРОВЕРКА НА СВЕЖЕСТЬ
                if pub_date is not None and pub_date < cutoff_date:
                    logger.debug(f"Skipping old article: {entry.get('title', 'N/A')} - {pub_date}")
                    continue
                
                url = entry.get("link", "").strip()
                if not url or is_article_sent(url):
                    continue

                title = entry.get("title", "").strip()
                desc = (entry.get("summary") or entry.get("description") or "").strip()
                desc = clean_html(desc)
                if not title or not desc:
                    continue

                if not is_relevant(title + " " + desc):
                    continue

                lead = desc.split("\n")[0].split(". ")[0].strip()
                if not lead:
                    lead = desc[:150] + "..." if len(desc) > 150 else desc
                
                send_to_telegram(src["name"], title, lead, url)
                mark_article_sent(url, title)
                time.sleep(0.5) # Задержка между отправками

        except Exception as e:
            logger.error(f"❌ Error on {src['name']}: {e}")

    logger.info("✅ Feed check completed.")

# === Запуск ===
if __name__ == "__main__":
    logger.info("🚀 Starting Russia Monitor Bot (Background Worker) with all 19 sources...")
    while True:
        fetch_and_process()
        logger.info("💤 Sleeping for 10 minutes...")
        time.sleep(10 * 60)
