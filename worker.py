import os
import time
import logging
import re
import feedparser
import requests
import html
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import json
import cloudscraper
from deep_translator import GoogleTranslator
from supabase import create_client
import random

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

# === Источники с различными методами обработки ===
SOURCES = [
    # 1. Good Judgment (Платформа superforecasting)
    {"name": "Good Judgment", "type": "rss", "url": "https://goodjudgment.com/feed/"},
    
    # 2. Johns Hopkins (Академический think-tank)
    {"name": "Johns Hopkins", "type": "rss", "url": "https://www.centerforhealthsecurity.org/feed.xml"},
    
    # 3. Metaculus (Онлайн-платформа)
    {"name": "Metaculus", "type": "api", "url": "https://www.metaculus.com/api2/questions/?forecast_type= binary&status= open&page=1&limit=5"},
    
    # 4. DNI Global Trends (Гос. think-tank)
    {"name": "DNI Global Trends", "type": "html", "url": "https://www.dni.gov/index.php/gt2040-home", "parser": "dni_parser"},
    
    # 5. RAND Corporation (Think-tank)
    {"name": "RAND", "type": "rss", "url": "https://www.rand.org/rss/recent.xml"},
    
    # 6. World Economic Forum (Think-tank/форум)
    {"name": "WEF", "type": "rss", "url": "https://www.weforum.org/agenda/archive/rss"},
    
    # 7. CSIS (Think-tank)
    {"name": "CSIS", "type": "rss", "url": "https://www.csis.org/rss.xml"},
    
    # 8. Atlantic Council (Think-tank)
    {"name": "Atlantic Council", "type": "rss", "url": "https://www.atlanticcouncil.org/feed/"},
    
    # 9. Chatham House (Think-tank)
    {"name": "Chatham House", "type": "rss", "url": "https://www.chathamhouse.org/feed"},
    
    # 10. The Economist (Журнал)
    {"name": "ECONOMIST", "type": "rss", "url": "https://www.economist.com/the-world-this-week/rss.xml"},
    
    # 11. Bloomberg (Онлайн/broadcaster)
    {"name": "BLOOMBERG", "type": "rss", "url": "https://www.bloomberg.com/politics/feeds/site.xml"},
    
    # 12. Reuters Institute (Академический/онлайн)
    {"name": "Reuters Institute", "type": "rss", "url": "https://reutersinstitute.politics.ox.ac.uk/feed"},
    
    # 13. Foreign Affairs (Журнал)
    {"name": "Foreign Affairs", "type": "rss", "url": "https://www.foreignaffairs.com/rss.xml"},
    
    # 14. CFR (Think-tank)
    {"name": "CFR", "type": "rss", "url": "https://www.cfr.org/rss.xml"},
    
    # 15. BBC Future (Broadcaster/онлайн)
    {"name": "BBC Future", "type": "rss", "url": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml"},
    
    # 16. Future Timeline (Нишевый блог)
    {"name": "Future Timeline", "type": "rss", "url": "http://futuretimeline.net/blog.rss"},
    
    # 17. Carnegie Endowment (Think-tank)
    {"name": "Carnegie", "type": "html", "url": "https://carnegieendowment.org/publications/", "parser": "carnegie_parser"},
    
    # 18. Bruegel (Think-tank) - использует защиту Cloudflare
    {"name": "Bruegel", "type": "cloudflare", "url": "https://www.bruegel.org/"},
    
    # 19. E3G (Think-tank)
    {"name": "E3G", "type": "rss", "url": "https://www.e3g.org/feed/"}
]

# === Ключевые слова ===
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

# === User agents для ротации ===
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Android 11; Mobile; rv:89.0) Gecko/89.0 Firefox/89.0"
]

# === Вспомогательные функции ===
def clean_html(raw: str) -> str:
    if not raw:
        return ""
    text = re.sub(r'<[^>]+>', '', raw)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def get_headers():
    return {"User-Agent": get_random_user_agent()}

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

# === Специальные парсеры для источников без RSS ===
def parse_dni_global_trends(html_content):
    """Парсит DNI Global Trends"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        articles = []
        
        # Ищем статьи по разным селекторам
        article_elements = soup.select('.article, .post, .publication, [class*="article"], [class*="post"], [class*="publication"]')
        
        for article in article_elements:
            title_elem = article.select_one('h1, h2, h3, h4, .title, .headline')
            link_elem = article.select_one('a')
            desc_elem = article.select_one('p, .description, .summary, .excerpt')
            
            if title_elem and link_elem and desc_elem:
                title = title_elem.get_text().strip()
                link = link_elem['href']
                if not link.startswith('http'):
                    link = f"https://www.dni.gov{link}"
                desc = desc_elem.get_text().strip()
                
                # Пытаемся найти дату
                date_elem = article.select_one('.date, time, [class*="date"]')
                pub_date = None
                if date_elem:
                    try:
                        pub_date = datetime.strptime(date_elem.get_text().strip(), '%B %d, %Y').replace(tzinfo=timezone.utc)
                    except:
                        pass
                
                articles.append({
                    'title': title,
                    'link': link,
                    'description': desc,
                    'published': pub_date
                })
        
        return articles
    except Exception as e:
        logger.error(f"DNI parsing error: {e}")
        return []

def parse_carnegie_endowment(html_content):
    """Парсит Carnegie Endowment"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        articles = []
        
        # Статьи в Carnegie имеют определенную структуру
        item_elements = soup.select('.publication-item, .media-item, .featured-item')
        
        for item in item_elements:
            title_elem = item.select_one('.title a, h3 a, .headline a')
            desc_elem = item.select_one('.abstract, .description, .summary')
            date_elem = item.select_one('.date, time')
            
            if title_elem:
                title = title_elem.get_text().strip()
                link = title_elem['href']
                if not link.startswith('http'):
                    link = f"https://carnegieendowment.org{link}"
                
                desc = desc_elem.get_text().strip() if desc_elem else "No description"
                
                # Парсинг даты
                pub_date = None
                if date_elem:
                    try:
                        date_text = date_elem.get_text().strip()
                        pub_date = datetime.strptime(date_text, '%B %d, %Y').replace(tzinfo=timezone.utc)
                    except:
                        pass
                
                articles.append({
                    'title': title,
                    'link': link,
                    'description': desc,
                    'published': pub_date
                })
        
        return articles
    except Exception as e:
        logger.error(f"Carnegie parsing error: {e}")
        return []

def parse_bruegel_cloudflare():
    """Обходит защиту Cloudflare на Bruegel.org"""
    try:
        # Используем cloudscraper для обхода Cloudflare
        scraper = cloudscraper.create_scraper()
        response = scraper.get("https://www.bruegel.org/articles/feed/", headers=get_headers(), timeout=15)
        response.raise_for_status()
        
        # Парсим RSS-ленту
        feed = feedparser.parse(response.content)
        return feed.entries
    except Exception as e:
        logger.error(f"Bruegel (Cloudflare) error: {e}")
        return []

def fetch_and_process():
    logger.info("📡 Checking feeds from all 19 sources...")
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
    
    for src in SOURCES:
        try:
            logger.info(f"🔍 Processing {src['name']} ({src['type']})")
            
            articles = []
            entries = []
            
            # Обработка в зависимости от типа источника
            if src['type'] == 'rss':
                # Стандартный RSS
                feed = feedparser.parse(src['url'], agent=get_random_user_agent())
                entries = feed.entries
                
            elif src['type'] == 'api':
                # API-запросы
                if src['name'] == 'Metaculus':
                    response = requests.get(src['url'], headers=get_headers(), timeout=15)
                    response.raise_for_status()
                    data = response.json()
                    
                    for item in data.get('results', []):
                        articles.append({
                            'title': item.get('title', ''),
                            'link': f"https://www.metaculus.com{item.get('page_url', '')}",
                            'description': item.get('description', ''),
                            'published': datetime.fromisoformat(item.get('created_at', '')[:-1]).replace(tzinfo=timezone.utc) if item.get('created_at') else None
                        })
            
            elif src['type'] == 'html':
                # Парсинг HTML
                response = requests.get(src['url'], headers=get_headers(), timeout=15)
                response.raise_for_status()
                
                if src['parser'] == 'dni_parser':
                    articles = parse_dni_global_trends(response.text)
                elif src['parser'] == 'carnegie_parser':
                    articles = parse_carnegie_endowment(response.text)
            
            elif src['type'] == 'cloudflare':
                # Обход Cloudflare
                if src['name'] == 'Bruegel':
                    entries = parse_bruegel_cloudflare()
            
            # Если есть записи из RSS или API
            for entry in entries:
                url = entry.get("link", "").strip()
                if not url:
                    continue
                
                # Проверяем дату
                pub_date = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    pub_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                
                # Проверяем, была ли статья уже отправлена и не слишком ли она старая
                if (pub_date is not None and pub_date < cutoff_date) or is_article_sent(url):
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
                
                send_to_telegram(src['name'], title, lead, url)
                mark_article_sent(url, title)
                time.sleep(0.5)
            
            # Если есть статьи из HTML-парсинга
            for article in articles:
                url = article.get("link", "").strip()
                if not url:
                    continue
                
                pub_date = article.get("published")
                if (pub_date is not None and pub_date < cutoff_date) or is_article_sent(url):
                    continue
                
                title = article.get("title", "").strip()
                desc = article.get("description", "").strip()
                desc = clean_html(desc)
                
                if not title or not desc:
                    continue
                
                if not is_relevant(title, desc):
                    continue
                
                lead = desc.split("\n")[0].split(". ")[0].strip()
                if not lead:
                    continue
                
                send_to_telegram(src['name'], title, lead, url)
                mark_article_sent(url, title)
                time.sleep(0.5)
        
        except Exception as e:
            logger.error(f"❌ Error processing {src['name']}: {str(e)}")
        
        # Добавляем задержку между источниками, чтобы не перегружать серверы
        time.sleep(1)
    
    logger.info("✅ All feeds processed completed.")

# === Запуск ===
if __name__ == "__main__":
    logger.info("🚀 Starting Russia Monitor Bot with all 19 sources...")
    while True:
        fetch_and_process()
        logger.info("💤 Sleeping for 10 minutes...")
        time.sleep(10 * 60)
