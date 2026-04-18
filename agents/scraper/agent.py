import time

from agents.logging_config import get_logger
from agents.scraper.sources import arxiv, github_trending, hackernews, rss

logger = get_logger(__name__)

_MAX_ARTICLES = 40


def run(sources: list[str] = None) -> tuple[list[dict], dict]:
    """Fetch articles from all enabled sources.

    Returns:
        (articles, stats) where stats contains per-source results and after_dedup count.
    """
    enabled = set(sources) if sources else {"arxiv", "hackernews", "github", "rss"}
    all_articles: list[dict] = []
    source_results: dict[str, dict] = {}

    _source_map = {
        "arxiv": arxiv.fetch_articles,
        "hackernews": hackernews.fetch_articles,
        "github": github_trending.fetch_articles,
        "rss": rss.fetch_articles,
    }

    for name in ["arxiv", "hackernews", "github", "rss"]:
        if name not in enabled:
            continue
        t0 = time.monotonic()
        try:
            articles = _source_map[name]()
            latency_ms = int((time.monotonic() - t0) * 1000)
            all_articles.extend(articles)
            source_results[name] = {"status": "success", "count": len(articles), "latency_ms": latency_ms}
        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.error(
                "scraper.source_fatal_error",
                extra={"source": name, "error_type": type(exc).__name__, "error_msg": str(exc)},
            )
            source_results[name] = {"status": "unexpected_error", "count": 0, "latency_ms": latency_ms}

    before = len(all_articles)
    deduped = _deduplicate(all_articles)
    after = len(deduped)

    logger.info(
        "scraper.dedup_completed",
        extra={"before": before, "after": after, "removed": before - after, "source_results": source_results},
    )

    sorted_articles = sorted(deduped, key=lambda a: a.get("published_date", ""), reverse=True)

    stats = {
        "sources": source_results,
        "raw_total": before,
        "after_dedup": after,
    }
    return sorted_articles[:_MAX_ARTICLES], stats


def _deduplicate(articles: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for article in articles:
        url = article.get("url", "")
        if url and url not in seen:
            seen.add(url)
            result.append(article)
    return result
