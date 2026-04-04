"""
OSINTFetcher - Multi-source intelligence data aggregator.

Fetches data from GDELT, RSS feeds (14 languages), and SearxNG,
normalizes it, and ingests into Graphiti knowledge graph as episodes.

Sources:
  - GDELT v2 Doc API (global events, 15M/day, free)
  - RSS feeds (IRNA, Reuters, Al Jazeera, Haaretz, Xinhua, TASS, ...)
  - SearxNG (self-hosted metasearch for web OSINT)

All sources are free and require no API keys.
"""

import json
import time
import hashlib
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..utils.logger import get_logger

logger = get_logger('mirofish.osint')

# User agent for HTTP requests
UA = 'MiroFish-OSINT/1.0 (Geopolitical Intelligence)'


@dataclass
class OSINTItem:
    """Normalized intelligence item from any source."""
    title: str
    content: str
    url: str
    source: str  # e.g. "gdelt", "rss:irna", "searxng"
    language: str  # ISO 639-1 code
    published: Optional[str] = None  # ISO datetime
    category: str = "general"  # news, military, economic, energy
    relevance_score: float = 0.0
    raw_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def dedup_key(self):
        return hashlib.md5(
            f"{self.title}:{self.url}".encode()
        ).hexdigest()


# RSS feed sources organized by language
RSS_FEEDS = {
    # Persian
    "fa": [
        ("IRNA", "https://www.irna.ir/rss"),
        ("Tasnim", "https://www.tasnimnews.com/fa/rss/feed/0/8/0"),
    ],
    # English
    "en": [
        ("Reuters World", "https://feeds.reuters.com/reuters/worldNews"),
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Al-Monitor", "https://www.al-monitor.com/rss"),
    ],
    # Arabic
    "ar": [
        ("Al Jazeera", "https://www.aljazeera.net/aljazeerarss/a7c186be-1baa-4bd4-9d80-a84db769f779/73d0e1b4-532f-45ef-b135-bfdbc8e7b8a7"),
    ],
    # Turkish
    "tr": [
        ("TRT Haber", "https://www.trthaber.com/xml_mobile.php?ession=manset"),
    ],
    # Chinese
    "zh": [
        ("Xinhua", "http://www.news.cn/rss/english.xml"),
    ],
    # Russian
    "ru": [
        ("TASS", "https://tass.com/rss/v2.xml"),
    ],
    # Hebrew - most Israeli news sites don't have public RSS
    "he": [],
    # French
    "fr": [
        ("France24", "https://www.france24.com/fr/rss"),
    ],
    # Spanish
    "es": [
        ("EFE", "https://efe.com/rss"),
    ],
    # German
    "de": [
        ("DW", "https://rss.dw.com/xml/rss-de-all"),
    ],
    # Japanese
    "ja": [
        ("NHK", "https://www3.nhk.or.jp/rss/news/cat0.xml"),
    ],
    # Portuguese
    "pt": [],
    # Italian
    "it": [],
}


class OSINTFetcher:
    """Multi-source OSINT data aggregator."""

    def __init__(self, timeout: int = 15, max_workers: int = 8):
        self.timeout = timeout
        self.max_workers = max_workers

    def fetch_all(
        self,
        query: Optional[str] = None,
        languages: Optional[List[str]] = None,
        max_per_source: int = 10,
        sources: Optional[List[str]] = None,
    ) -> List[OSINTItem]:
        """
        Fetch from all available OSINT sources in parallel.

        Args:
            query: Search query for GDELT/SearxNG (optional for RSS)
            languages: Filter to specific languages (default: all)
            max_per_source: Max items per source
            sources: Specific sources to use (default: all)

        Returns:
            Deduplicated list of OSINTItem
        """
        all_items = []
        enabled = sources or ["gdelt", "rss", "searxng"]
        tasks = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # GDELT
            if "gdelt" in enabled and query:
                tasks.append(
                    executor.submit(
                        self._fetch_gdelt, query, max_per_source
                    )
                )

            # RSS feeds
            if "rss" in enabled:
                feed_langs = languages or list(RSS_FEEDS.keys())
                for lang in feed_langs:
                    feeds = RSS_FEEDS.get(lang, [])
                    for name, url in feeds:
                        tasks.append(
                            executor.submit(
                                self._fetch_rss, name, url, lang,
                                max_per_source
                            )
                        )

            # SearxNG
            if "searxng" in enabled and query:
                tasks.append(
                    executor.submit(
                        self._fetch_searxng, query, max_per_source,
                        languages
                    )
                )

            for future in as_completed(tasks):
                try:
                    items = future.result()
                    all_items.extend(items)
                except Exception as e:
                    logger.warning(f"OSINT source failed: {e}")

        # Deduplicate
        seen = set()
        unique = []
        for item in all_items:
            if item.dedup_key not in seen:
                seen.add(item.dedup_key)
                unique.append(item)

        logger.info(
            f"OSINT: fetched {len(all_items)} items, "
            f"{len(unique)} unique after dedup"
        )
        return unique

    def _fetch_gdelt(self, query: str, max_items: int) -> List[OSINTItem]:
        """Fetch from GDELT v2 Doc API."""
        items = []
        url = (
            f"https://api.gdeltproject.org/api/v2/doc/doc"
            f"?query={urllib.request.quote(query)}"
            f"&mode=artlist&maxrecords={max_items}"
            f"&format=json&timespan=7d"
        )
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            data = json.loads(resp.read())
            for art in data.get("articles", []):
                items.append(OSINTItem(
                    title=art.get("title", ""),
                    content=art.get("seendate", "") + " " + art.get("title", ""),
                    url=art.get("url", ""),
                    source="gdelt",
                    language=art.get("language", "en")[:2].lower(),
                    published=art.get("seendate"),
                    category=self._categorize(art.get("title", "")),
                    raw_metadata={
                        "domain": art.get("domain"),
                        "sourcecountry": art.get("sourcecountry"),
                        "socialimage": art.get("socialimage"),
                    },
                ))
            logger.info(f"GDELT: {len(items)} articles for '{query}'")
        except Exception as e:
            logger.warning(f"GDELT fetch failed: {e}")
        return items

    def _fetch_rss(
        self, name: str, url: str, language: str, max_items: int
    ) -> List[OSINTItem]:
        """Fetch from an RSS/Atom feed."""
        items = []
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            content = resp.read()
            root = ET.fromstring(content)

            # Handle both RSS and Atom formats
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            rss_items = root.findall('.//item')
            if not rss_items:
                rss_items = root.findall('.//atom:entry', ns)

            for item_el in rss_items[:max_items]:
                title_el = (
                    item_el.find('title') or
                    item_el.find('atom:title', ns)
                )
                link_el = (
                    item_el.find('link') or
                    item_el.find('atom:link', ns)
                )
                desc_el = (
                    item_el.find('description') or
                    item_el.find('atom:summary', ns) or
                    item_el.find('atom:content', ns)
                )
                pub_el = (
                    item_el.find('pubDate') or
                    item_el.find('atom:published', ns) or
                    item_el.find('atom:updated', ns)
                )

                title = title_el.text if title_el is not None and title_el.text else ""
                link = (
                    link_el.text if link_el is not None and link_el.text
                    else (link_el.get('href', '') if link_el is not None else '')
                )
                desc = desc_el.text if desc_el is not None and desc_el.text else ""
                pub = pub_el.text if pub_el is not None and pub_el.text else ""

                if title:
                    items.append(OSINTItem(
                        title=title.strip(),
                        content=(desc or title).strip()[:500],
                        url=link.strip(),
                        source=f"rss:{name.lower().replace(' ', '_')}",
                        language=language,
                        published=pub,
                        category=self._categorize(title),
                    ))
            logger.info(f"RSS {name} ({language}): {len(items)} items")
        except Exception as e:
            logger.warning(f"RSS {name} failed: {e}")
        return items

    def _fetch_searxng(
        self, query: str, max_items: int,
        languages: Optional[List[str]] = None
    ) -> List[OSINTItem]:
        """Fetch from SearxNG metasearch (tries Docker DNS then IP)."""
        items = []
        hosts = [
            "qadr-searxng:8080",
            "172.20.0.4:8080",
            "localhost:18080",
        ]
        for host in hosts:
            try:
                lang_param = languages[0] if languages else "en"
                url = (
                    f"http://{host}/search"
                    f"?q={urllib.request.quote(query)}"
                    f"&format=json&categories=news"
                    f"&language={lang_param}"
                )
                req = urllib.request.Request(url, headers={'User-Agent': UA})
                resp = urllib.request.urlopen(req, timeout=self.timeout)
                data = json.loads(resp.read())
                for r in data.get("results", [])[:max_items]:
                    items.append(OSINTItem(
                        title=r.get("title", ""),
                        content=r.get("content", r.get("title", ""))[:500],
                        url=r.get("url", ""),
                        source="searxng",
                        language=lang_param,
                        published=r.get("publishedDate"),
                        category=self._categorize(r.get("title", "")),
                        raw_metadata={
                            "engine": r.get("engine"),
                            "score": r.get("score"),
                        },
                    ))
                logger.info(f"SearxNG ({host}): {len(items)} results")
                break  # success, don't try other hosts
            except Exception as e:
                logger.debug(f"SearxNG {host} failed: {e}")
                continue
        return items

    def _categorize(self, text: str) -> str:
        """Simple keyword-based categorization."""
        text_lower = text.lower()
        if any(w in text_lower for w in [
            'military', 'army', 'navy', 'missile', 'drone', 'war',
            'نظامی', 'ارتش', 'موشک', 'جنگ', 'عسكري'
        ]):
            return "military"
        if any(w in text_lower for w in [
            'oil', 'energy', 'opec', 'gas', 'hormuz', 'pipeline',
            'نفت', 'انرژی', 'هرمز', 'نفط'
        ]):
            return "energy"
        if any(w in text_lower for w in [
            'economy', 'market', 'trade', 'sanction', 'bank', 'currency',
            'اقتصاد', 'بازار', 'تحریم', 'بورس', 'اقتصادي'
        ]):
            return "economic"
        if any(w in text_lower for w in [
            'diplomacy', 'negotiate', 'treaty', 'summit', 'un ',
            'دیپلماسی', 'مذاکره', 'سازمان ملل', 'دبلوماسي'
        ]):
            return "diplomatic"
        return "general"

    def ingest_to_graphiti(
        self, items: List[OSINTItem], graph_id: str
    ) -> Dict[str, Any]:
        """
        Ingest OSINT items into Graphiti as episodes.

        Args:
            items: List of normalized OSINT items
            graph_id: Graphiti graph namespace

        Returns:
            Summary of ingestion results
        """
        from .graph_client import GraphitiClient
        client = GraphitiClient()

        ingested = 0
        failed = 0
        for item in items:
            try:
                episode_text = (
                    f"[{item.source}] [{item.language}] "
                    f"[{item.category}] {item.title}\n"
                    f"{item.content}\n"
                    f"URL: {item.url}"
                )
                if item.published:
                    episode_text += f"\nPublished: {item.published}"

                client.add_episode(
                    graph_id=graph_id,
                    text=episode_text,
                    source=item.source,
                )
                ingested += 1
            except Exception as e:
                logger.warning(f"Ingest failed for '{item.title[:40]}': {e}")
                failed += 1

        result = {
            "total": len(items),
            "ingested": ingested,
            "failed": failed,
            "graph_id": graph_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            f"OSINT ingest: {ingested}/{len(items)} to graph {graph_id}"
        )
        return result

    def fetch_status(self) -> Dict[str, Any]:
        """Return status of all OSINT sources."""
        status = {
            "gdelt": self._check_source(
                "https://api.gdeltproject.org/api/v2/doc/doc"
                "?query=test&mode=artlist&maxrecords=1&format=json"
            ),
            "rss_feeds": {
                lang: len(feeds)
                for lang, feeds in RSS_FEEDS.items()
                if feeds
            },
            "total_rss_feeds": sum(
                len(f) for f in RSS_FEEDS.values()
            ),
            "languages": [
                l for l, f in RSS_FEEDS.items() if f
            ],
        }

        # Check SearxNG
        for host in ["qadr-searxng:8080", "172.20.0.4:8080"]:
            try:
                url = f"http://{host}/search?q=test&format=json"
                req = urllib.request.Request(
                    url, headers={'User-Agent': UA}
                )
                urllib.request.urlopen(req, timeout=5)
                status["searxng"] = {"status": "ok", "host": host}
                break
            except Exception:
                status["searxng"] = {"status": "unreachable"}

        return status

    def _check_source(self, url: str) -> Dict[str, Any]:
        """Check if a source URL is accessible."""
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            resp = urllib.request.urlopen(req, timeout=5)
            return {"status": "ok", "http_code": resp.status}
        except Exception as e:
            return {"status": "error", "error": str(e)[:100]}
