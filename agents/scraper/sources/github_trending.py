import time
from datetime import date

import requests
from bs4 import BeautifulSoup

from agents.logging_config import get_logger

logger = get_logger(__name__)

GITHUB_TRENDING_URL = "https://github.com/trending"
_RETRY_DELAYS = [1, 3, 7]
_AI_KEYWORDS = {
    "llm", "ai", "ml", "machine learning", "neural", "transformer",
    "diffusion", "embedding", "inference", "finetune", "fine-tune",
    "agent", "gpt", "bert", "claude", "openai", "anthropic",
    "hugging", "deep learning", "generative", "language model",
}


def fetch_articles(since: str = "daily") -> list[dict]:
    html = _fetch_html(since)
    if html is None:
        return []
    return _parse(html)


def _fetch_html(since: str) -> str | None:
    params = {"since": since}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ai-research-analyst/1.0)"}

    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            logger.debug("source.fetch_started", extra={"source": "github", "attempt": attempt})
            resp = requests.get(GITHUB_TRENDING_URL, params=params, headers=headers, timeout=30)

            if resp.status_code == 200:
                return resp.text

            if 400 <= resp.status_code < 500:
                logger.error("source.fetch_failed", extra={"source": "github", "status": resp.status_code, "retryable": False})
                return None

            logger.warning("source.fetch_failed", extra={"source": "github", "status": resp.status_code, "attempt": attempt, "retryable": True})

        except requests.exceptions.Timeout:
            logger.warning("source.fetch_failed", extra={"source": "github", "error_type": "Timeout", "attempt": attempt, "retryable": True})

        except requests.exceptions.ConnectionError as exc:
            logger.warning("source.fetch_failed", extra={"source": "github", "error_type": "ConnectionError", "error_msg": str(exc), "attempt": attempt, "retryable": True})

        except Exception as exc:
            logger.error("source.fetch_failed", extra={"source": "github", "error_type": type(exc).__name__, "error_msg": str(exc), "retryable": False})
            return None

    logger.error("source.fetch_failed", extra={"source": "github", "error_type": "MaxRetriesExceeded"})
    return None


def _parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    repo_cards = soup.select("article.Box-row")

    if not repo_cards:
        logger.warning("source.entry_skipped", extra={"source": "github", "reason": "No repo cards found — GitHub HTML structure may have changed"})
        return []

    articles = []
    failed = 0
    today = date.today().isoformat()

    for i, card in enumerate(repo_cards):
        try:
            link_el = card.select_one("h2 a")
            if link_el is None:
                logger.warning("source.entry_skipped", extra={"source": "github", "entry_index": i, "reason": "no h2 a element"})
                failed += 1
                continue

            href = link_el.get("href", "").strip()
            if not href:
                failed += 1
                continue

            full_url = f"https://github.com{href}"
            # Repo name from href: /owner/repo
            title = href.lstrip("/").replace("/", " / ")

            desc_el = card.select_one("p")
            description = desc_el.get_text(strip=True) if desc_el else ""

            # Filter: only include repos with AI/ML keywords in description or title
            combined = (title + " " + description).lower()
            if not any(kw in combined for kw in _AI_KEYWORDS):
                continue

            articles.append({
                "title": title,
                "url": full_url,
                "abstract": description,
                "source": "github",
                "published_date": today,
            })

        except Exception as exc:
            logger.warning("source.entry_skipped", extra={"source": "github", "entry_index": i, "reason": str(exc)})
            failed += 1

    logger.info("source.fetch_completed", extra={"source": "github", "count": len(articles), "failed": failed})
    return articles
