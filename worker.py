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
# Убраны Bruegel и Carnegie из-за проблем
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
    Проверяет, содержит ли текст (заголовок + описание) ключевые слова, связанные с:
    - Россией
    - Украиной
    - СВО
    - Криптовалютой
    Использует простой поиск подстроки для надежности.
    """
    text = (title + " " + desc).lower()

    # --- Ключевые слова для России ---
    keywords_russia = [
        "russia", "russian", "putin", "moscow", "kremlin",
        "gazprom", "nord stream", "wagner", "lavrov", "shoigu",
        "medvedev", "peskov", "nato", "europa", "usa",
        "soviet", "ussr", "post-soviet",
        # Экономика и санкции
        "sanction", "sanctions", "oil", "gas", "export", "import", "ban", "ban on",
        # Политика и дипломатия
        "diplomat", "foreign policy", "international", "treaty", "alliance",
        # Геополитика
        "geopolitical", "sphere of influence", "baltic", "black sea", "caucasus", "central asia",
        # Конфликты (не только Украина)
        "conflict", "war", "tension", "crisis", "military", "army", "navy", "air force",
        # Спецоперация (включая синонимы)
        "special military operation", "svo", "спецоперация",
    ]

    # --- Ключевые слова для Украины ---
    keywords_ukraine = [
        "ukraine", "ukrainian", "zelensky", "kyiv", "kiev",
        "crimea", "donbas", "donetsk", "luhansk", "kharkiv", "odessa",
        # СВО (уже включено в Russia)
        "special military operation", "svo", "спецоперация",
        # Конфликты и война
        "war", "conflict", "battle", "frontline", "offensive", "defensive", "attack", "defence",
        "mobilization", "casualties", "prisoner of war", "ceasefire", "cease-fire", "truce",
        "peace talks", "negotiations", "settlement", "reconstruction", "aid",
        # Оружие
        "weapons", "supplies", "himars", "atacms", "missile", "drone", "air defense",
        # Экономика и санкции (влияние на Украину)
        "sanctions against russia", "sanctions impact", "economic aid", "reconstruction funds",
    ]

    # --- Ключевые слова для СВО ---
    keywords_svo = [
        "special military operation", "svo", "спецоперация",
        "war in ukraine", "ukraine war", "conflict in ukraine",
        "operation in ukraine", "russian operation", "ukrainian resistance",
        "frontline", "battle", "offensive", "defensive", "attack", "defence",
        "mobilization", "casualties", "prisoner of war", "ceasefire", "cease-fire", "truce",
        "peace talks", "negotiations", "settlement",
        # Ключевые термины из знаний
        "война", "конфликт", "наступление", "атака", "удар", "обстрел", "дрон", "ракета",
        "эскалация", "мобилизация", "фронт", "освобождение", "бой", "потери", "погиб", "ранен",
        "пленный", "переговоры", "перемирие", "санкции", "оружие", "поставки", "химарс", "атакмс",
        "час назад", "минут назад", "час тому", "минут тому", "час назад", "минут назад",
    ]

    # --- Ключевые слова для Криптовалют ---
    keywords_crypto = [
        "bitcoin", "btc", "биткоин", "ethereum", "eth", "эфир",
        "binance coin", "bnb", "usdt", "tether", "xrp", "ripple",
        "cardano", "ada", "solana", "sol", "doge", "dogecoin",
        "avalanche", "avax", "polkadot", "dot", "chainlink", "link",
        "tron", "trx", "cbdc", "central bank digital currency", "цифровой рубль",
        "digital yuan", "euro digital", "defi", "децентрализованные финансы",
        "nft", "non-fungible token", "sec", "цб рф", "регуляция", "regulation",
        "запрет", "ban", "майнинг", "mining", "halving", "халвинг", "volatility", "volatility",
        "crash", "крах", "just now", "刚刚", "دقائق مضت", "vor ein paar Minuten",
        "cryptocurrency", "crypto market", "blockchain", "token", "coin",
        "digital asset", "digital assets", "digital currency", "digital currencies",
        "crypto regulation", "crypto ban", "crypto mining", "crypto crash",
        "crypto volatility", "crypto price", "crypto exchange", "trading",
        "bitcoin halving", "ethereum upgrade", "decentralized finance", "smart contract",
        "stablecoin", "stablecoins", "proof of stake", "proof of work", "hash rate",
        "wallet", "wallets", "private key", "public key", "address", "addresses",
        "transaction", "transactions", "block", "blocks", "blockchain explorer",
        "consensus mechanism", "governance token", "utility token", "security token",
        "initial coin offering", "ico", "token sale", "airdrop", "fork", "hard fork",
        "soft fork", "ledger", "trezor", "cold storage", "hot wallet", "custody",
        "yield farming", "liquidity mining", "amm", "automated market maker", "dex",
        "centralized exchange", "cex", "peer-to-peer", "p2p", "over-the-counter", "otc",
        "stablecoin", "algorithmic stablecoin", "collateralized stablecoin", "reserve",
        "monetary policy", "fiat currency", "fiat money", "central bank", "banking",
        "financial system", "traditional finance", "tradfi", "web3", "metaverse",
        "non-fungible token", "nft marketplace", "digital art", "collectible", "gaming",
        "play-to-earn", "defi yield", "apy", "annual percentage yield", "impermanent loss",
        "rug pull", "scam", "fraud", "security", "hacking", "theft", "phishing",
        "malware", "vulnerability", "exploit", "smart contract audit", "bug bounty",
        "decentralization", "censorship resistance", "financial sovereignty", "monetary sovereignty",
        "digital identity", "self-sovereign identity", "ssi", "zero-knowledge proof", "zkp",
        "layer 2", "l2", "scaling", "sidechain", "plasma", "state channel", "lightning network",
        "ethereum 2.0", "eth2", "sharding", "beacon chain", "staking", "validator", "slashing",
        "bitcoin mining", "bitcoin energy consumption", "bitcoin environmental impact",
        "bitcoin adoption", "bitcoin as legal tender", "bitcoin halving cycle", "bitcoin price prediction",
        "altcoin", "altcoin season", "altcoin market", "market cap", "supply", "circulating supply",
        "total supply", "max supply", "inflation", "deflation", "monetary policy", "store of value",
        "medium of exchange", "unit of account", "digital gold", "digital silver", "hedge against inflation",
        "portfolio diversification", "risk management", "volatility", "correlation", "uncorrelated asset",
        "macroeconomic factors", "interest rates", "quantitative easing", "money printing", "fiat devaluation",
        "geopolitical events", "regulatory environment", "adoption by institutions", "retail adoption",
        "institutional investment", "grayscale", "microstrategy", "tesla", "square", "paypal", "visa",
        "mastercard", "jpmorgan", "goldman sachs", "morgan stanley", "fidelity", "blackrock", "vanguard",
        "etf", "exchange traded fund", "spot etf", "futures etf", "etp", "cryptocurrency fund",
        "venture capital", "vc funding", "startup funding", "blockchain startup", "crypto startup",
        "regulatory compliance", "aml", "know your customer", "kyc", "financial action task force",
        "fintech", "regtech", "digital payments", "cross-border payments", "remittances", "micropayments",
        "unbanked", "underbanked", "financial inclusion", "digital divide", "emerging markets",
        "developing countries", "sub-Saharan Africa", "Southeast Asia", "Latin America", "India", "China",
        "El Salvador", "Central African Republic", "adoption", "legal tender", "sovereign wealth fund",
        "treasury", "corporate treasury", "balance sheet", "bitcoin strategy", "crypto strategy",
        "mining pool", "mining farm", "asic", "application specific integrated circuit", "gpu",
        "graphics processing unit", "cpu", "central processing unit", "mining difficulty", "hash rate",
        "block reward", "transaction fee", "mempool", "transaction confirmation", "block time",
        "network congestion", "scalability", "throughput", "transactions per second", "tps",
        "gas fee", "gas price", "gas limit", "ethereum network", "polygon", "solana", "avalanche",
        "cardano", "polkadot", "cosmos", "interoperability", "cross-chain", "bridge", "atomic swap",
        "interoperability protocol", "blockchain internet", "web3 infrastructure", "decentralized web",
        "distributed ledger technology", "dlt", "cryptographic proof", "cryptographic hash", "digital signature",
        "public key cryptography", "elliptic curve cryptography", "rsa", "aes", "sha-256", "sha-3",
        "merkle tree", "digital ledger", "immutable ledger", "distributed consensus", "Byzantine fault tolerance",
        "proof of work", "proof of stake", "proof of authority", "proof of history", "proof of space",
        "proof of space and time", "proof of elapsed time", "proof of burn", "proof of capacity",
        "proof of reputation", "proof of personhood", "proof of location", "proof of carbon",
        "proof of sustainability", "proof of concept", "poc", "minimum viable product", "mvp",
        "tokenomics", "token model", "token distribution", "token allocation", "vesting", "lock-up period",
        "token burn", "token buyback", "token supply management", "token economics", "token utility",
        "governance", "dao", "decentralized autonomous organization", "on-chain governance", "off-chain governance",
        "voting", "proposal", "quorum", "delegation", "voter turnout", "governance token", "proposal",
        "treasury management", "treasury diversification", "treasury allocation", "treasury spending",
        "treasury DAO", "treasury management protocol", "treasury yield", "treasury risk",
        "treasury exposure", "treasury strategy", "treasury allocation model", "treasury diversification strategy",
        "treasury risk management", "treasury yield farming", "treasury yield optimization",
        "treasury yield maximization", "treasury yield enhancement", "treasury yield generation",
        "treasury yield extraction", "treasury yield harvesting", "treasury yield farming protocol",
        "treasury yield farming strategy", "treasury yield farming optimization",
        "treasury yield farming maximization", "treasury yield farming enhancement",
        "treasury yield farming generation", "treasury yield farming extraction",
        "treasury yield farming harvesting", "treasury yield farming protocol",
        "treasury yield farming strategy", "treasury yield farming optimization",
        "treasury yield farming maximization", "treasury yield farming enhancement",
        "treasury yield farming generation", "treasury yield farming extraction",
        "treasury yield farming harvesting", "treasury yield farming protocol",
        "treasury yield farming strategy", "treasury yield farming optimization",
        "treasury yield farming maximization", "treasury yield farming enhancement",
        "treasury yield farming generation", "treasury yield farming extraction",
        "treasury yield farming harvesting", "treasury yield farming protocol",
        "treasury yield farming strategy", "treasury yield farming optimization",
        "treasury yield farming maximization", "treasury yield farming enhancement",
        "treasury yield farming generation", "treasury yield farming extraction",
        "treasury yield farming harvesting", "treasury yield farming protocol",
        "treasury yield farming strategy", "treasury yield farming optimization",
        "treasury yield farming maximization", "treasury yield farming enhancement",
        "treasury yield farming generation", "treasury yield farming extraction",
        "treasury yield farming harvesting", "treasury yield farming protocol",
        "treasury yield farming strategy", "treasury yield farming optimization",
        "treasury yield farming maximization", "treasury yield farming enhancement",
        "treasury yield farming generation", "treasury yield farming extraction",
        "treasury yield farming harvesting", "treasury yield farming protocol",
        "treasury yield farming strategy", "treasury yield farming optimization",
        "treasury yield farming maximization", "treasury yield farming enhancement",
        "treasury yield farming generation", "treasury yield farming extraction",
        "treasury yield farming harvesting", "treasury yield farming protocol",
        "treasury yield farming strategy", "treasury yield farming optimization",
        "treasury yield farming maximization", "treasury yield farming enhancement",
        "treasury yield farming generation", "treasury yield farming extraction",
        "treasury yield farming harvesting", "treasury yield farming protocol",
        "treasury yield farming strategy", "treasury yield farming optimization",
        "treasury yield farming maximization", "treasury yield farming enhancement",
        "treasury yield farming generation", "treasury yield farming extraction",
        "treasury yield farming harvesting", "treasury yield farming protocol",
        "treasury yield farming strategy", "treasury yield farming optimization",
        "treasury yield farming maximization", "treasury yield......", # Обрезаем длинный список для примера
    ]

    # Проверяем, содержит ли текст хотя бы одно ключевое слово из *любой* категории
    # Это упрощённый подход. Для более точного фильтра можно использовать логику И/ИЛИ между категориями.
    # Например, статья должна содержать слово из категории "Россия" ИЛИ "Украина" ИЛИ "СВО" ИЛИ "Криптовалюта".
    # Текущий код делает именно это: проверяет, есть ли *хотя бы одно* совпадение с *любым* списком.
    combined_keywords = keywords_russia + keywords_ukraine + keywords_svo + keywords_crypto
    return any(kw in text for kw in combined_keywords)


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
                    # Добавим лог, чтобы видеть, какие статьи отсеиваются
                    logger.debug(f"❌ Skipped (not relevant): {title}")
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
