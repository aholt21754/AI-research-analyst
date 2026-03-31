import time

import requests

from agents.logging_config import get_logger

logger = get_logger(__name__)

ARXIV_BASE_URL = "http://export.arxiv.org/api/query"
_RETRY_DELAYS = [1, 3, 7]

try:
    import xml.etree.ElementTree as ET
    from xml.etree.ElementTree import ParseError
except ImportError:
    pass

ATOM_NS = "http://www.w3.org/2005/Atom"


def fetch_articles(query: str = "LLM agent", max_results: int = 20) -> list[dict]:
    xml_text = _fetch_xml(query, max_results)
    if xml_text is None:
        return []
    return _parse(xml_text)


def _fetch_xml(query: str, max_results: int) -> str | None:
    params = {"search_query": f"all:{query}", "max_results": max_results}

    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            logger.debug("source.fetch_started", extra={"source": "arxiv", "attempt": attempt})
            resp = requests.get(ARXIV_BASE_URL, params=params, timeout=30)

            if resp.status_code == 200:
                return resp.text

            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                logger.error(
                    "source.fetch_failed",
                    extra={"source": "arxiv", "error_type": "HTTPError", "status": resp.status_code, "retryable": False},
                )
                return None  # no retry on 4xx (except 429 Too Many Requests)

            logger.warning(
                "source.fetch_failed",
                extra={"source": "arxiv", "error_type": "HTTPError", "status": resp.status_code, "attempt": attempt, "retryable": True},
            )

        except requests.exceptions.Timeout:
            logger.warning(
                "source.fetch_failed",
                extra={"source": "arxiv", "error_type": "Timeout", "attempt": attempt, "retryable": True},
            )

        except requests.exceptions.ConnectionError as exc:
            logger.warning(
                "source.fetch_failed",
                extra={"source": "arxiv", "error_type": "ConnectionError", "error_msg": str(exc), "attempt": attempt, "retryable": True},
            )

        except Exception as exc:
            logger.error(
                "source.fetch_failed",
                extra={"source": "arxiv", "error_type": type(exc).__name__, "error_msg": str(exc), "retryable": False},
            )
            return None

    logger.error("source.fetch_failed", extra={"source": "arxiv", "error_type": "MaxRetriesExceeded"})
    return None


def _parse(xml_text: str) -> list[dict]:
    import xml.etree.ElementTree as ET
    from xml.etree.ElementTree import ParseError

    try:
        root = ET.fromstring(xml_text)
    except ParseError as exc:
        logger.error("source.parse_error", extra={"source": "arxiv", "error": str(exc), "retryable": False})
        return []
    except Exception as exc:
        logger.error("source.parse_error", extra={"source": "arxiv", "error_type": type(exc).__name__, "error_msg": str(exc)})
        return []

    ns = {"atom": ATOM_NS}
    entries = root.findall("atom:entry", ns)
    articles = []
    failed = 0

    for i, entry in enumerate(entries):
        try:
            title_el = entry.find("atom:title", ns)
            id_el = entry.find("atom:id", ns)
            summary_el = entry.find("atom:summary", ns)
            published_el = entry.find("atom:published", ns)

            title = title_el.text.strip() if title_el is not None else None
            arxiv_id = id_el.text.strip() if id_el is not None else None
            abstract = summary_el.text.strip() if summary_el is not None else None
            published = published_el.text.strip() if published_el is not None else None

            if not all([title, arxiv_id, abstract, published]):
                missing = [k for k, v in {"title": title, "arxiv_id": arxiv_id, "abstract": abstract, "published": published}.items() if not v]
                logger.warning("source.entry_skipped", extra={"source": "arxiv", "entry_index": i, "reason": f"missing: {missing}"})
                failed += 1
                continue

            # Normalise to canonical HTTPS URL
            if not arxiv_id.startswith("http"):
                arxiv_id = f"https://arxiv.org/abs/{arxiv_id}"
            else:
                arxiv_id = arxiv_id.replace("http://", "https://")

            articles.append({
                "title": title,
                "url": arxiv_id,
                "abstract": abstract,
                "source": "arxiv",
                "published_date": published,
            })

        except (AttributeError, TypeError) as exc:
            logger.warning("source.entry_skipped", extra={"source": "arxiv", "entry_index": i, "reason": str(exc)})
            failed += 1

    logger.info(
        "source.fetch_completed",
        extra={"source": "arxiv", "count": len(articles), "failed": failed},
    )
    return articles
