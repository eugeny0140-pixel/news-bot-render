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
    {"name": "Good Judgment", "rss": "https://goodjudgment.com/blog/feed/", "method": "rss"},
    
    # 2. Johns Hopkins (Академический think-tank)
    {"name": "Johns Hopkins", "url": "https://www.centerforhealthsecurity.org/news/", "method": "html_parser"},
    
    # 3. Metaculus (Онлайн-платформа)
    {"name": "Metaculus", "rss": "https://metaculus.com/feed/updates/", "method": "rss"},
    
    # 4. DNI Global Trends (Гос. think-tank)
    {"name": "DNI Global Trends", "url": "https://www.dni.gov/index.php/gt2040-home", "method": "html_parser"},
    
    # 5. RAND Corporation (Think-tank)
    {"name": "RAND", "rss": "https://www.rand.org/rss/recent.xml", "method": "rss"},
    
    # 6. World Economic Forum (Think-tank/форум)
    {"name": "World Economic Forum", "rss": "https://www.weforum.org/agenda/archive/feed", "method": "rss"},
    
    # 7. CSIS (Think-tank)
    {"name": "CSIS", "rss": "https://www.csis.org/rss.xml", "method": "rss"},
    
    # 8. Atlantic Council (Think-tank)
    {"name": "Atlantic Council", "rss": "https://www.atlanticcouncil.org/feed/", "method": "rss"},
    
    # 9. Chatham House (Think-tank)
    {"name": "Chatham House", "rss": "https://www.chathamhouse.org/feed", "method": "rss"},
    
    # 10. The Economist (Журнал)
    {"name": "ECONOMIST", "rss": "https://www.economist.com/the-world-this-week/rss.xml", "method": "rss"},
    
    # 11. Bloomberg (Онлайн/broadcaster)
    {"name": "BLOOMBERG", "rss": "https://www.bloomberg.com/politics/feeds/site.xml", "method": "rss"},
    
    # 12. Reuters Institute (Академический/онлайн)
    {"name": "Reuters Institute", "rss": "https://reutersinstitute.politics.ox.ac.uk/feed", "method": "rss"},
    
    # 13. Foreign Affairs (Журнал)
    {"name": "Foreign Affairs", "rss": "https://www.foreignaffairs.com/rss.xml", "method": "rss"},
    
    # 14. CFR (Think-tank)
    {"name": "CFR", "rss": "https://www.cfr.org/rss.xml", "method": "rss"},
    
    # 15. BBC Future (Broadcaster/онлайн)
    {"name": "BBC Future", "rss": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "method": "rss"},
    
    # 16. Future Timeline (Нишевый блог)
    {"name": "Future Timeline", "rss": "http://futuretimeline.net/blog.rss", "method": "rss_with_fallback"},
    
    # 17. Carnegie Endowment (Think-tank)
    {"name": "Carnegie", "url": "https://carnegieendowment.org/publications/", "method": "html_parser"},
    
    # 18. Bruegel (Think-tank)
    {"name": "Bruegel", "rss": "https://www.bruegel.org/", "method": "cloudscraper"},
    
    # 19. E3G (Think-tank)
    {"name": "E3G", "rss": "https://www.e3g.org/feed/", "method": "rss"},
]

# === Ключевые слова (точные регулярные выражения) ===
KEYWORDS = [
    r"\brussia\b", r"\brussian\b", r"\bputin\b", r"\bmoscow\b", r"\bkremlin\b",
    r"\bukraine\b", r"\bukrainian\b", r"\bzelensky\b", r"\bkyiv\b", r"\bkiev\b",
    r"\bcrimea\b", r"\bdonbas\b", r"\bsanction[s]?\b", r"\bgazprom\b",
    r"\bnord\s?stream\b", r"\bwagner\b", r"\blavrov\b", r"\bshoigu\b",
    r"\bmedvedev\b", r"\bpeskov\b", r"\bnato\b", r"\beuropa\b", r"\busa\b",
    r"\bsoviet\b", r"\bussr\b", r"\bpost\W?soviet\b",
    # === СВО и Война ===
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
    r"\bhour ago\b", r"\bчас назад\b", r"\bminutos atrás\b", r"\b小时前\b",
    # === Криптовалюта ===
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
    r"\bволатильность\b", r"\bvolatility\b", r"\bcrash\b", r"\bкрах\b",
    r"\b刚刚\b", r"\bدقائق مضت\b",
    # === Пандемия ===
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
    r"\bhospitalization\b", r"\bгоспитализация\b",
    r"\bقبل ساعات\b", r"\b刚刚报告\b"
]

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

def is_relevant(title: str, desc: str) -> bool:
    text = (title + " " + desc).lower()
    return any(re.search(pattern, text) for pattern in KEYWORDS)

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

# === Специализированные функции для парсинга ===
def fetch_rss_feed(url):
    """Стандартное получение RSS-ленты"""
    feed = feedparser.parse(url)
    return feed

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
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        # Поиск статей на странице
        for article in soup.select('.news-item'):
            title_elem = article.select_one('h3 a')
            if not title_elem:
                continue
                
            title = title_elem.get_text().strip()
            link = "https://www.centerforhealthsecurity.org" + title_elem['href']
            desc_elem = article.select_one('.summary')
            desc = desc_elem.get_text().strip() if desc_elem else ""
            date_elem = article.select_one('.date')
            pub_date = date_elem.get_text().strip() if date_elem else ""
            
            entries.append({
                'title': title,
                'link': link,
                'summary': desc,
                'published': pub_date
            })
        
        feed = feedparser.FeedParserDict()
        feed.entries = entries
        return feed
    except Exception as e:
        logger.error(f"Johns Hopkins parsing error: {e}")
        return feedparser.FeedParserDict(entries=[])

def parse_dni_global_trends():
    """Парсинг сайта DNI Global Trends"""
    url = "https://www.dni.gov/index.php/gt2040-home"
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        # Поиск отчетов и новостей
        for item in soup.select('.main-content a'):
            if 'gt2040' in item['href'].lower() or 'global' in item.text.lower():
                title = item.get_text().strip()
                link = url + item['href'] if item['href'].startswith('/') else item['href']
                desc = f"Global Trends report from DNI: {title}"
                
                entries.append({
                    'title': title,
                    'link': link,
                    'summary': desc,
                    'published': time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
                })
        
        feed = feedparser.FeedParserDict()
        feed.entries = entries
        return feed
    except Exception as e:
        logger.error(f"DNI Global Trends parsing error: {e}")
        return feedparser.FeedParserDict(entries=[])

def parse_carnegie():
    """Парсинг сайта Carnegie Endowment"""
    url = "https://carnegieendowment.org/publications/"
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        entries = []
        # Поиск публикаций
        for article in soup.select('.publications-list .item'):
            title_elem = article.select_one('.title a')
            if not title_elem:
                continue
                
            title = title_elem.get_text().strip()
            link = "https://carnegieendowment.org" + title_elem['href']
            desc_elem = article.select_one('.summary')
            desc = desc_elem.get_text().strip() if desc_elem else ""
            date_elem = article.select_one('.date')
            date = date_elem.get_text().strip() if date_elem else ""
            
            entries.append({
                'title': title,
                'link': link,
                'summary': desc,
                'published': date
            })
        
        feed = feedparser.FeedParserDict()
        feed.entries = entries
        return feed
    except Exception as e:
        logger.error(f"Carnegie parsing error: {e}")
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
                else:
                    feed = feedparser.FeedParserDict(entries=[])
            else:
                feed = fetch_rss_feed(src.get('rss', ''))
            
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
                        pub_date = datetime.strptime(entry.published, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    except:
                        pass
                
                # Пропуск старых статей (старше 7 дней)
                if pub_date is not None and pub_date < cutoff_date:
                    continue
                
                url = entry.get("link", "").strip()
                if not url or is_article_sent(url):
                    continue

                title = entry.get("title", "").strip()
                desc = (entry.get("summary") or entry.get("description") or "").strip()
                desc = clean_html(desc)
                if not title or not desc:
                    continue

                if not is_relevant(title, desc):
                    continue

                lead = desc.split("\n")[0].split(". ")[0].strip()
                if not lead:
                    continue

                send_to_telegram(src["name"], title, lead, url)
                mark_article_sent(url, title)
                time.sleep(0.5)

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
