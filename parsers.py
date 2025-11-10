import aiohttp
import asyncio
from bs4 import BeautifulSoup
import feedparser
import random
import time
import logging

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/535.11 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
]

SOURCES = [
    {"name": "Atlantic Council", "url": "https://www.atlanticcouncil.org", "type": "rss", "rss_url": "https://www.atlanticcouncil.org/feed/"},
    {"name": "DNI Global Trends", "url": "https://www.dni.gov/index.php/gt2040-home", "type": "html", "selector": ".article"},
    {"name": "RAND Corporation", "url": "https://www.rand.org", "type": "rss", "rss_url": "https://www.rand.org/rss/news.html"},
    {"name": "Chatham House", "url": "https://www.chathamhouse.org", "type": "rss", "rss_url": "https://www.chathamhouse.org/feed"},
    {"name": "CSIS", "url": "https://www.csis.org", "type": "rss", "rss_url": "https://www.csis.org/rss/all.xml"},
    {"name": "WEF", "url": "https://www.weforum.org", "type": "rss", "rss_url": "https://www.weforum.org/feed"},
    {"name": "The Economist", "url": "https://www.economist.com", "type": "rss", "rss_url": "https://www.economist.com/the-world-this-week/rss.xml"},
    {"name": "Foreign Affairs", "url": "https://www.foreignaffairs.com", "type": "rss", "rss_url": "https://www.foreignaffairs.com/rss.xml"},
    {"name": "Bloomberg", "url": "https://www.bloomberg.com", "type": "rss", "rss_url": "https://www.bloomberg.com/feed/politics"},
    {"name": "Reuters Institute", "url": "https://reutersinstitute.politics.ox.ac.uk", "type": "html", "selector": ".card--article"},
    {"name": "BBC Future", "url": "https://www.bbc.com/future", "type": "rss", "rss_url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"},
    {"name": "CFR", "url": "https://www.cfr.org", "type": "rss", "rss_url": "https://www.cfr.org/rss.xml"},
    {"name": "Carnegie Endowment", "url": "https://carnegieendowment.org", "type": "rss", "rss_url": "https://carnegieendowment.org/rss/all.xml"},
    {"name": "Bruegel", "url": "https://www.bruegel.org", "type": "rss", "rss_url": "https://www.bruegel.org/blog/feed"},
    {"name": "E3G", "url": "https://www.e3g.org", "type": "rss", "rss_url": "https://www.e3g.org/feed/"},
    {"name": "Good Judgment", "url": "https://goodjudgment.com", "type": "html", "selector": ".post-preview"},
    {"name": "Johns Hopkins", "url": "https://www.centerforhealthsecurity.org", "type": "rss", "rss_url": "https://www.centerforhealthsecurity.org/feed.xml"},
    {"name": "Metaculus", "url": "https://www.metaculus.com", "type": "rss", "rss_url": "https://www.metaculus.com/feed/"},
    {"name": "Future Timeline", "url": "https://www.futuretimeline.net", "type": "html", "selector": ".timeline-item"}
]

async def fetch_url(url: str) -> str:
    """Асинхронный запрос с ротацией User-Agent"""
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=15) as response:
                return await response.text()
        except Exception as e:
            logger.error(f"Ошибка при загрузке {url}: {str(e)}")
            return ""

async def parse_rss(source: dict) -> list:
    """Парсинг RSS-ленты"""
    try:
        feed = feedparser.parse(await fetch_url(source['rss_url']))
        articles = []
        for entry in feed.entries[:5]:  # Берем последние 5 статей
            articles.append({
                "title": entry.title,
                "url": entry.link,
                "source": source['name'],
                "lead": entry.get('summary', '')[:200] + "..." if entry.get('summary') else "",
                "published": entry.get('published', '')
            })
        return articles
    except Exception as e:
        logger.error(f"Ошибка парсинга RSS {source['name']}: {str(e)}")
        return []

async def parse_html(source: dict) -> list:
    """Парсинг HTML-страницы"""
    html = await fetch_url(source['url'])
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    articles = []
    
    for item in soup.select(source['selector'])[:5]:
        title = item.select_one('h2, h3, .title') or item.select_one('a')
        if not title:
            continue
            
        link = item.select_one('a')
        url = link['href'] if link else source['url']
        if not url.startswith('http'):
            url = source['url'] + url
            
        lead = item.select_one('p, .excerpt')
        
        articles.append({
            "title": title.get_text(strip=True),
            "url": url,
            "source": source['name'],
            "lead": lead.get_text(strip=True)[:200] + "..." if lead else "",
            "published": datetime.now().isoformat()
        })
    
    return articles

async def check_all_sources():
    """Проверяет доступность всех источников"""
    async with aiohttp.ClientSession() as session:
        tasks = []
        for source in SOURCES:
            tasks.append(session.get(source['url'], timeout=10))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.warning(f"⚠️ Источник недоступен: {SOURCES[i]['name']} ({str(res)})")

async def get_all_articles() -> list:
    """Собирает статьи со всех источников"""
    await check_all_sources()
    
    tasks = []
    for source in SOURCES:
        if source['type'] == 'rss':
            tasks.append(parse_rss(source))
        else:
            tasks.append(parse_html(source))
    
    results = await asyncio.gather(*tasks)
    return [article for sublist in results for article in sublist]
