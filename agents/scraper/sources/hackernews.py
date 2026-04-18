import time

import requests

from agents.logging_config import get_logger

logger = get_logger(__name__)

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
_RETRY_DELAYS = [1, 3, 7]


def fetch_articles(query: str = "LLM agents RAG multimodal machine learning", max_results: int = 20) -> list[dict]:
    data = _fetch_json(query, max_results)
    if data is None:
        return []
    return _parse(data)


def _fetch_json(query: str, max_results: int) -> dict | None:
    params = {
        "query": query,
        "tags": "story",
        "numericFilters": "points>10",
        "hitsPerPage": max_results,
    }

    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            logger.debug("source.fetch_started", extra={"source": "hackernews", "attempt": attempt})
            resp = requests.get(HN_SEARCH_URL, params=params, timeout=30)

            if resp.status_code == 200:
                return resp.json()

            if 400 <= resp.status_code < 500:
                logger.error(
                    "source.fetch_failed",
                    extra={"source": "hackernews", "status": resp.status_code, "retryable": False},
                )
                return None

            logger.warning(
                "source.fetch_failed",
                extra={"source": "hackernews", "status": resp.status_code, "attempt": attempt, "retryable": True},
            )

        except requests.exceptions.Timeout:
            logger.warning("source.fetch_failed", extra={"source": "hackernews", "error_type": "Timeout", "attempt": attempt, "retryable": True})

        except requests.exceptions.ConnectionError as exc:
            logger.warning("source.fetch_failed", extra={"source": "hackernews", "error_type": "ConnectionError", "error_msg": str(exc), "attempt": attempt, "retryable": True})

        except requests.exceptions.JSONDecodeError:
            logger.error("source.fetch_failed", extra={"source": "hackernews", "error_type": "JSONDecodeError", "retryable": False})
            return None

        except Exception as exc:
            logger.error("source.fetch_failed", extra={"source": "hackernews", "error_type": type(exc).__name__, "error_msg": str(exc), "retryable": False})
            return None

    logger.error("source.fetch_failed", extra={"source": "hackernews", "error_type": "MaxRetriesExceeded"})
    return None


def _parse(data: dict) -> list[dict]:
    hits = data.get("hits")
    if hits is None:
        logger.error("source.parse_error", extra={"source": "hackernews", "error": "missing 'hits' key"})
        return []

    articles = []
    failed = 0

    for i, item in enumerate(hits):
        try:
            title = item.get("title")
            published = item.get("created_at")

            if not title or not published:
                logger.warning("source.entry_skipped", extra={"source": "hackernews", "entry_index": i, "reason": "missing title or created_at"})
                failed += 1
                continue

            # Fall back to HN item URL if the story has no external URL
            url = item.get("url") or f"https://news.ycombinator.com/item?id={item.get('objectID', '')}"

            articles.append({
                "title": title,
                "url": url,
                "abstract": item.get("story_text") or "",
                "source": "hackernews",
                "published_date": published,
            })

        except Exception as exc:
            logger.warning("source.entry_skipped", extra={"source": "hackernews", "entry_index": i, "reason": str(exc)})
            failed += 1

    logger.info("source.fetch_completed", extra={"source": "hackernews", "count": len(articles), "failed": failed})
    return articles
