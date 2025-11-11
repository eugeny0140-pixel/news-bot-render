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
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

# === Настройки ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_IDS = [cid.strip() for cid in os.getenv("CHANNEL_ID1", "").split(",") if cid.strip()]
if os.getenv("CHANNEL_ID2"):
    CHANNEL_IDS.extend([cid.strip() for cid in os.getenv("CHANNEL_ID2").split(",") if cid.strip()])

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

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

# === Трехэтапная фильтрация ===
KEYWORDS = [r"\b(russia|rus|российск(ая|ое|ий|их)|рф|kremlin|putin|belarus|беларусь)\b", r"\b(ukraine|ukrainian|kiev|kyiv|zelensk(y|yy)|donbas|crimea|kherson|kharkiv|lviv)\b", r"\b(russian invasion|special military operation|SVO|russo-ukrainian war|ukraine conflict)\b", r"\b(russian military|wagner group|prigozhin|separatists|LNR|DNR|annexation)\b", r"\b(ukrainian forces|ATACMS|HIMARS|f-16|patriot system|counteroffensive)\b", r"\b(sanctions (against|on) russia|eu sanctions|price cap|SWIFT ban)\b", r"\b(iaea zaporizhzhia|nuclear plant|nord stream sabotage)\b", r"\b(russia crypto|digital ruble|цифровой рубль|cbr digital assets|garantex exchange)\b", r"\b(ukraine crypto donations|war bonds crypto|kuna exchange|come back alive crypto)\b", r"\b(russian crypto ban|cbr cryptocurrency regulation|rossvyaz crypto block)\b", r"\b(energy crypto mining russia|iran russia crypto|belarus crypto scheme)\b", r"\b(ministry of defence ru|mod ru|rostec|alrosa|gazprom|rosneft)\b", r"\b(nato russia|finland nato|sweden nato|budapest memorandum)\b", r"\b(mobilization russia|filobank|shadow fleet|parallel imports russia)\b", r"\b(un vote russia|international court justice ukraine|icc putin)\b"]
BLACKLIST = [r"\bstar wars\b", r"\bworld of warcraft\b", r"\bwarhammer\b", r"\bwar of the roses\b", r"\bbitcoin price\b.*\b(analysis|forecast|technical)\b", r"\bethereum merge\b", r"\bcrypto etf approval\b", r"\bcoinbase earnings\b", r"\bpandemic\b.*\b(flu|h5n1|mpox)\b", r"\bcovid-19\b.*\b(vaccine|variant)\b\s*[^.]*?\b(not|without)\b\s*\b(russia|ukraine)\b", r"\bmilitary exercise\b.*\b(nato|pacific|china|india)\b", r"\bdrone show\b", r"\bnuclear safety\b.*\b(japan|fukushima)\b", r"\bsanction[s]?\b.*\b(venezuela|iran|north korea|myanmar|syria|belarus)\b", r"\bdrone delivery\b.*\b(amazon|google|wing)\b"]
CONTEXT_TERMS = r"\b(russia|ukraine|belarus|kremlin|putin|zelensk(y|yy)?|donbas|crimea|kyiv|kiev|moscow|russian|ukrainian|wagner|rostec|gazprom|LNR|DNR|ukrainian territory)\b"
CONTEXT_WINDOW = 200
CRITICAL_TERMS = [r"\b(?:war|attack|strike|sanction[s]?|military|conflict|drone|missile|rocket|bomb|nuclear|bio\w*)\b", r"\bcrypto(?:currency)?\b", r"\b(?:pandemic|virus|vaccine)\b"]

def is_relevant(text: str) -> bool:
    text_lower = text.lower()
    keyword_matches = [m for p in KEYWORDS for m in re.finditer(p, text_lower, re.IGNORECASE | re.UNICODE)]
    if not keyword_matches: return False
    if any(re.search(p, text_lower, re.IGNORECASE | re.UNICODE) for p in BLACKLIST): return False
    critical_compiled = re.compile("|".join(CRITICAL_TERMS), re.IGNORECASE | re.UNICODE)
    for match in keyword_matches:
        start, end = match.span()
        matched_text = match.group()
        if re.search(r"(russia|ukraine|kremlin|putin|zelensk(y|yy)?|donbas|crimea|wagner|rostec)", matched_text, re.IGNORECASE): return True
        if critical_compiled.search(matched_text):
            context_start = max(0, start - CONTEXT_WINDOW)
            context_end = min(len(text_lower), end + CONTEXT_WINDOW)
            context_snippet = text_lower[context_start:context_end]
            if re.search(CONTEXT_TERMS, context_snippet, re.IGNORECASE | re.UNICODE): return True
        else: return True
    return False

# === Вспомогательные функции ===
def clean_html(raw: str) -> str: return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', html.unescape(raw))).strip() if raw else ""

def translate(text: str):
    if not text.strip(): return ""
    try: return GoogleTranslator(source='auto', target='ru').translate(text)
    except Exception as e: logger.warning(f"GoogleTranslate failed: {e}. Using original text."); return text

def is_article_sent(url: str):
    try: return len(supabase.table("published_articles").select("url").eq("url", url).execute().data) > 0
    except Exception as e: logger.error(f"Supabase check error: {e}"); return False

def mark_article_sent(url: str, title: str):
    try: supabase.table("published_articles").insert({"url": url, "title": title}).execute(); logger.info(f"✅ Saved: {url}")
    except Exception as e: logger.error(f"Supabase insert error: {e}")

def send_to_telegram(prefix: str, title: str, lead: str, url: str):
    try:
        title_ru, lead_ru = translate(title), translate(lead)
        message = f"<b>{prefix}</b>: {title_ru}\n\n{lead_ru}\n\nИсточник: {url}"
        for ch in CHANNEL_IDS:
            resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": ch, "text": message, "parse_mode": "HTML", "disable_web_page_preview": False}, timeout=10)
            if resp.status_code == 200: logger.info(f"📤 Sent: {title[:60]}..."); time.sleep(0.5)
            else: logger.error(f"❌ TG error: {resp.status_code} {resp.text}")
    except Exception as e: logger.exception(f"Telegram send failed: {e}")

# === Универсальные функции для парсинга ===
def fetch_rss_feed(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8'}
        return feedparser.parse(requests.get(url, headers=headers, timeout=15).content)
    except Exception as e: logger.error(f"RSS fetch error for {url}: {e}"); return feedparser.FeedParserDict(entries=[])

def fetch_with_cloudscraper(url):
    try: return feedparser.parse(cloudscraper.create_scraper().get(url, timeout=15).content)
    except Exception as e: logger.error(f"Cloudscraper error for {url}: {e}"); return feedparser.FeedParserDict(entries=[])

def parse_html_generic(url, selectors, base_url, keywords_filter=None):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        soup = BeautifulSoup(requests.get(url, headers=headers, timeout=15).content, 'html.parser')
        entries = []
        for item in soup.select(selectors['container']):
            title_elem = item.select_one(selectors['title'])
            if not title_elem: continue
            title = title_elem.get_text().strip()
            link = title_elem['href']
            if link.startswith('/'): link = base_url + link
            elif not link.startswith('http'): link = base_url + '/' + link.lstrip('/')
            desc = item.select_one(selectors['desc']).get_text().strip() if item.select_one(selectors['desc']) else ""
            date_elem = item.select_one(selectors['date'])
            pub_date_str = date_elem.get_text().strip() if date_elem else datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
            pub_date_parsed = None
            for fmt in ["%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%Y-%m-%d", "%m/%d/%Y", "%Y"]:
                try: pub_date_parsed = datetime.strptime(pub_date_str, fmt).replace(tzinfo=timezone.utc); break
                except ValueError: continue
            if not pub_date_parsed: pub_date_parsed = datetime.now(timezone.utc)
            if keywords_filter and not any(kw in title.lower() or kw in desc.lower() for kw in keywords_filter): continue
            entries.append({'title': title, 'link': link, 'summary': desc, 'published': pub_date_str, 'published_parsed': pub_date_parsed.timetuple()})
        feed = feedparser.FeedParserDict(); feed.entries = entries; return feed
    except Exception as e: logger.error(f"HTML parsing error for {url}: {e}"); return feedparser.FeedParserDict(entries=[])

# === Функции для конкретных сайтов (с использованием универсальной) ===
def parse_dni(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        content = response.text
        if "Reference #" in content and ("edgesuite.net" in content or "Akamai" in content):
             logger.warning(f"DNI site returned error page for {url}"); return feedparser.FeedParserDict(entries=[])
        # Просто добавляем одну фиктивную запись, если страница доступна
        title, link, desc = "Global Trends 2040 Report", url, "DNI Global Trends 2040 report analysis."
        pub_date_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        feed = feedparser.FeedParserDict(); feed.entries = [{'title': title, 'link': link, 'summary': desc, 'published': pub_date_str}]; return feed
    except requests.exceptions.RequestException as e: logger.error(f"DNI network error: {e}"); return feedparser.FeedParserDict(entries=[])
    except Exception as e: logger.error(f"DNI parsing error: {e}"); return feedparser.FeedParserDict(entries=[])

def parse_future_timeline(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        entries = []
        for item in soup.select('.timeline-item, .event'):
            title_elem = item.select_one('h2 a, h3 a, .title a, .event-title a')
            if not title_elem: continue
            title = title_elem.get_text().strip()
            link = title_elem['href']
            if link.startswith('/'): link = 'http://www.futuretimeline.net' + link
            elif not link.startswith('http'): link = 'http://www.futuretimeline.net/' + link.lstrip('/')
            desc_elem = item.select_one('p, .summary, .content, .event-description')
            desc = desc_elem.get_text().strip() if desc_elem else title
            date_match = re.search(r'(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{4})', title)
            pub_date_str = date_match.group(0) if date_match else datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
            pub_date_parsed = None
            try:
                if '-' in pub_date_str and len(pub_date_str) == 10: pub_date_parsed = datetime.strptime(pub_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                elif '/' in pub_date_str: pub_date_parsed = datetime.strptime(pub_date_str, "%m/%d/%Y").replace(tzinfo=timezone.utc)
                else: pub_date_parsed = datetime.strptime(pub_date_str, "%Y").replace(tzinfo=timezone.utc, month=1, day=1)
            except ValueError: pub_date_parsed = datetime.now(timezone.utc)
            if any(keyword in title.lower() or keyword in desc.lower() for keyword in ['security', 'technology', 'geopolitical', 'war', 'conflict', 'pandemic', 'virus', 'biosecurity', 'crypto', 'russia', 'ukraine']):
                entries.append({'title': title, 'link': link, 'summary': desc, 'published': pub_date_str, 'published_parsed': pub_date_parsed.timetuple()})
        feed = feedparser.FeedParserDict(); feed.entries = entries; return feed
    except Exception as e: logger.error(f"Future Timeline parsing error: {e}"); return feedparser.FeedParserDict(entries=[])

# === Источники (все 19) ===
SOURCES = [
    {"name": "Good Judgment", "url": "https://goodjudgment.com/feed/", "method": "rss"},
    {"name": "Johns Hopkins", "url": "https://www.centerforhealthsecurity.org/news/", "method": "html", "selectors": {"container": ".resource-item, .news-item, .list-item", "title": "h3 a, h2 a, .title a", "desc": ".summary, .excerpt, p", "date": ".date, time"}, "keywords": ['health', 'security', 'pandemic', 'russia', 'ukraine']},
    {"name": "Metaculus", "url": "https://metaculus.com/feed/updates/", "method": "rss"},
    {"name": "DNI Global Trends", "url": "https://www.dni.gov/index.php/gt2040-home", "method": "dni"},
    {"name": "RAND", "url": "https://www.rand.org/rss/recent.xml", "method": "rss"},
    {"name": "World Economic Forum", "url": "https://www.weforum.org/agenda/archive/feed", "method": "rss"},
    {"name": "CSIS", "url": "https://www.csis.org/rss.xml", "method": "rss"},
    {"name": "Atlantic Council", "url": "https://www.atlanticcouncil.org/feed/", "method": "rss"},
    {"name": "Chatham House", "url": "https://www.chathamhouse.org/feed", "method": "rss"},
    {"name": "ECONOMIST", "url": "https://www.economist.com/the-world-this-week/rss.xml", "method": "rss"},
    {"name": "BLOOMBERG", "url": "https://feeds.bloomberg.com/markets/news.rss", "method": "rss"},
    {"name": "Reuters Institute", "url": "https://reutersinstitute.politics.ox.ac.uk/research", "method": "html", "selectors": {"container": ".views-row, .publication, .blog-post, .node-teaser", "title": "h2 a, h3 a, .title a", "desc": ".field-content p, .summary, .excerpt", "date": ".date, time, .submitted"}, "keywords": ['russia', 'ukraine', 'media', 'journalism', 'disinformation', 'news', 'social media', 'trust']},
    {"name": "Foreign Affairs", "url": "https://www.foreignaffairs.com/rss.xml", "method": "rss"},
    {"name": "CFR", "url": "https://www.cfr.org/publications", "method": "html", "selectors": {"container": ".teaser--publication, .views-row, .publication-item", "title": ".teaser__title a, .field-content h3 a, h3 a", "desc": ".teaser__dek, .field-content .field-name-body, .views-field-body", "date": ".teaser__date, .date-created, .submitted"}, "keywords": ['russia', 'ukraine', 'moscow', 'kremlin', 'putin', 'eastern europe', 'eurasia', 'sanction', 'economy', 'security', 'diplomacy', 'geopolitics']},
    {"name": "BBC Future", "url": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "method": "rss"},
    {"name": "Future Timeline", "url": "http://www.futuretimeline.net/", "method": "future_timeline"},
    {"name": "Carnegie", "url": "https://carnegieendowment.org/publications/", "method": "html", "selectors": {"container": ".views-row", "title": ".views-field-title a", "desc": ".views-field-field-pub-excerpt .field-content", "date": ".views-field-field-pub-date .field-content"}, "keywords": ['russia', 'ukraine', 'moscow', 'kremlin', 'putin', 'eastern europe', 'eurasia', 'sanction', 'economy', 'security', 'diplomacy']},
    {"name": "Bruegel", "url": "https://www.bruegel.org/analysis", "method": "html", "selectors": {"container": ".post-item, .blog-item, article", "title": "h3 a, h2 a, .title a", "desc": ".excerpt, .summary, .description, p", "date": ".date, time"}, "keywords": ['russia', 'ukraine', 'sanctions', 'energy security', 'europe', 'security', 'geopolitics', 'defense', 'economy']},
    {"name": "E3G", "url": "https://www.e3g.org/feed/", "method": "rss"},
]

# === Основной цикл ===
def fetch_and_process():
    logger.info("📡 Checking feeds...")
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
    for src in SOURCES:
        try:
            logger.info(f"Fetching feed from {src['name']} (method: {src['method']})")
            feed = None
            if src['method'] == 'rss': feed = fetch_rss_feed(src['url'])
            elif src['method'] == 'cloudscraper': feed = fetch_with_cloudscraper(src['url'])
            elif src['method'] == 'html': feed = parse_html_generic(src['url'], src['selectors'], src['url'].split("/")[2], src.get('keywords'))
            elif src['method'] == 'dni': feed = parse_dni(src['url'])
            elif src['method'] == 'future_timeline': feed = parse_future_timeline(src['url'])
            else: feed = feedparser.FeedParserDict(entries=[])
            
            if not hasattr(feed, 'entries') or not feed.entries: logger.warning(f"❌ Empty or invalid feed from {src['name']}"); continue

            for entry in feed.entries:
                pub_date = None
                for attr in ['published_parsed', 'updated_parsed']:
                    if hasattr(entry, attr) and getattr(entry, attr): pub_date = datetime(*getattr(entry, attr)[:6], tzinfo=timezone.utc); break
                if not pub_date and hasattr(entry, 'published'):
                    for fmt in ['%a, %d %b %Y %H:%M:%S %z', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d']:
                        try: pub_date = datetime.strptime(entry.published, fmt).replace(tzinfo=timezone.utc); break
                        except ValueError: continue
                    if not pub_date: pub_date = datetime.now(timezone.utc); logger.warning(f"Could not parse date: {entry.get('published', 'N/A')}")
                
                if pub_date and pub_date < cutoff_date: logger.debug(f"Skipping old article: {entry.get('title', 'N/A')} - {pub_date}"); continue
                
                url = entry.get("link", "").strip()
                if not url or is_article_sent(url): continue

                title, desc = entry.get("title", "").strip(), clean_html(entry.get("summary", entry.get("description", "")).strip())
                if not title or not desc or not is_relevant(title + " " + desc): continue

                lead = desc.split("\n")[0].split(". ")[0].strip() or (desc[:150] + "..." if len(desc) > 150 else desc)
                send_to_telegram(src["name"], title, lead, url)
                mark_article_sent(url, title)

        except Exception as e: logger.error(f"❌ Error on {src['name']}: {e}")

    logger.info("✅ Feed check completed.")

if __name__ == "__main__":
    logger.info("🚀 Starting Russia Monitor Bot...")
    while True:
        fetch_and_process()
        logger.info("💤 Sleeping for 10 minutes...")
        time.sleep(10 * 60)
