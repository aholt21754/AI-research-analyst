from agents.logging_config import get_logger
from agents.scraper.sources import arxiv, github_trending, hackernews, rss

logger = get_logger(__name__)

_MAX_ARTICLES = 40


def run(sources: list[str] = None) -> list[dict]:
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
        try:
            articles = _source_map[name]()
            all_articles.extend(articles)
            source_results[name] = {"status": "success", "count": len(articles)}
        except Exception as exc:
            logger.error(
                "scraper.source_fatal_error",
                extra={"source": name, "error_type": type(exc).__name__, "error_msg": str(exc)},
            )
            source_results[name] = {"status": "unexpected_error", "count": 0}

    before = len(all_articles)
    deduped = _deduplicate(all_articles)
    after = len(deduped)

    logger.info(
        "scraper.dedup_completed",
        extra={"before": before, "after": after, "removed": before - after, "source_results": source_results},
    )

    sorted_articles = sorted(deduped, key=lambda a: a.get("published_date", ""), reverse=True)
    return sorted_articles[:_MAX_ARTICLES]


def _deduplicate(articles: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for article in articles:
        url = article.get("url", "")
        if url and url not in seen:
            seen.add(url)
            result.append(article)
    return result
