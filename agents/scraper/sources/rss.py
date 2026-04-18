from datetime import date, timezone
from email.utils import parsedate_to_datetime

import feedparser

from agents.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_FEEDS = [
    "https://huggingface.co/blog/feed.xml",
    "https://thegradient.pub/rss/",
    "https://lastweekin.ai/feed",
    "https://blog.research.google/feeds/posts/default",
    "https://towardsdatascience.com/feed",
    "https://aws.amazon.com/blogs/machine-learning/feed/",
]


def fetch_articles(feed_urls: list[str] = None) -> list[dict]:
    urls = feed_urls if feed_urls is not None else DEFAULT_FEEDS
    all_articles: list[dict] = []

    for url in urls:
        articles = _fetch_feed(url)
        all_articles.extend(articles)

    return all_articles


def _fetch_feed(url: str) -> list[dict]:
    try:
        logger.debug("source.fetch_started", extra={"source": "rss", "url": url})
        feed = feedparser.parse(url)
    except Exception as exc:
        logger.error("source.fetch_failed", extra={"source": "rss", "url": url, "error_type": type(exc).__name__, "error_msg": str(exc)})
        return []

    # feedparser returns status 0 for local files / errors without HTTP
    status = getattr(feed, "status", 200)
    if status and status >= 400:
        logger.warning("source.fetch_failed", extra={"source": "rss", "url": url, "status": status})
        return []

    if feed.get("bozo"):
        logger.warning("source.fetch_bozo", extra={"source": "rss", "url": url, "bozo_exception": str(feed.get("bozo_exception", ""))})
        # Still attempt to process entries — many valid feeds trigger bozo

    entries = feed.get("entries", [])
    if not entries:
        logger.info("source.fetch_completed", extra={"source": "rss", "url": url, "count": 0})
        return []

    articles = []
    failed = 0
    today = date.today().isoformat()

    for i, entry in enumerate(entries):
        try:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()

            if not title or not link:
                logger.warning("source.entry_skipped", extra={"source": "rss", "url": url, "entry_index": i, "reason": "missing title or link"})
                failed += 1
                continue

            # Abstract: prefer summary, fall back to first content block
            abstract = entry.get("summary", "")
            if not abstract and entry.get("content"):
                abstract = entry["content"][0].get("value", "")

            # Published date: try structured time first, then string, then today
            published = _parse_date(entry) or today

            articles.append({
                "title": title,
                "url": link,
                "abstract": abstract,
                "source": "rss",
                "published_date": published,
            })

        except Exception as exc:
            logger.warning("source.entry_skipped", extra={"source": "rss", "url": url, "entry_index": i, "reason": str(exc)})
            failed += 1

    logger.info("source.fetch_completed", extra={"source": "rss", "url": url, "count": len(articles), "failed": failed})
    return articles


def _parse_date(entry: dict) -> str | None:
    # feedparser provides published_parsed as a time.struct_time in UTC
    if entry.get("published_parsed"):
        try:
            from datetime import datetime
            dt = datetime(*entry["published_parsed"][:6], tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            pass

    # Fall back to raw string parsing
    if entry.get("published"):
        try:
            dt = parsedate_to_datetime(entry["published"])
            return dt.isoformat()
        except Exception:
            pass

    return None
