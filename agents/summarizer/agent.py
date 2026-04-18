import json
import os
import re
import time

import anthropic

from agents.logging_config import get_logger
from agents.summarizer.prompts.registry import get_prompt

logger = get_logger(__name__)

_MODEL = "claude-haiku-4-5"
_MAX_INPUT_ARTICLES = 30
_ABSTRACT_TRUNCATE = 300
_RETRY_DELAYS = [1, 3, 7]

# claude-haiku-4-5 pricing per token
_INPUT_TOKEN_COST = 0.0000008   # $0.80 / 1M tokens
_OUTPUT_TOKEN_COST = 0.000004   # $4.00 / 1M tokens


def run(articles: list[dict], prompt_version: str = None, top_n: int = 10) -> tuple[list[dict], dict]:
    """Score and summarize articles using Claude.

    Returns:
        (digest, stats) where stats contains input_tokens, output_tokens,
        cost_usd, and latency_ms. On failure returns ([], empty_stats).
    """
    _empty_stats = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "latency_ms": 0}

    if not articles:
        return [], _empty_stats

    version, system_prompt, user_template = get_prompt(prompt_version)
    batch = articles[:_MAX_INPUT_ARTICLES]

    articles_text = "\n\n".join(
        f"[Article {i + 1}]\nTitle: {_sanitize_text(a['title'], 200)}\nAbstract: {_sanitize_text(a['abstract'], _ABSTRACT_TRUNCATE)}\nURL: {a['url']}"
        for i, a in enumerate(batch)
    )
    user_message = user_template.format(num_articles=len(batch), articles_text=articles_text)

    logger.info("summarizer.call_started", extra={"num_articles": len(batch), "model": _MODEL, "prompt_version": version})

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = None
    t0 = time.monotonic()

    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            response = client.messages.create(
                model=_MODEL,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            break
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as exc:
            retryable = True
            if attempt < len(_RETRY_DELAYS):
                logger.warning(
                    "summarizer.call_retrying",
                    extra={"attempt": attempt + 1, "error_type": type(exc).__name__, "error_msg": str(exc), "retryable": retryable},
                )
            else:
                logger.error(
                    "summarizer.call_failed",
                    extra={"attempt": attempt + 1, "error_type": type(exc).__name__, "error_msg": str(exc), "retryable": retryable},
                )
                return [], _empty_stats
        except anthropic.APIError as exc:
            logger.error(
                "summarizer.call_failed",
                extra={"attempt": attempt + 1, "error_type": type(exc).__name__, "error_msg": str(exc), "retryable": False},
            )
            return [], _empty_stats

    if response is None:
        return [], _empty_stats

    latency_ms = int((time.monotonic() - t0) * 1000)
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost_usd = round((input_tokens * _INPUT_TOKEN_COST) + (output_tokens * _OUTPUT_TOKEN_COST), 6)

    logger.info(
        "summarizer.call_completed",
        extra={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "prompt_version": version,
        },
    )

    raw = response.content[0].text
    scored = _parse_response(raw, batch, version)
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)

    high = sum(1 for a in scored if a["score"] >= 8)
    mid  = sum(1 for a in scored if 5 <= a["score"] < 8)
    low  = sum(1 for a in scored if a["score"] < 5)
    logger.info("summarizer.score_distribution", extra={"high_8_plus": high, "mid_5_7": mid, "low_below_5": low, "total": len(scored)})

    stats = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "latency_ms": latency_ms,
    }
    return scored[:top_n], stats


def _parse_response(raw: str, articles: list[dict], version: str) -> list[dict]:
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        # Strip accidental markdown fences and retry once
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            items = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error("summarizer.parse_error", extra={"error": str(exc), "raw_length": len(raw)})
            return []

    if not isinstance(items, list):
        logger.error("summarizer.parse_error", extra={"error": "response is not a JSON array", "raw_length": len(raw)})
        return []

    result = []
    for item in items:
        idx = item.get("index", 0) - 1  # convert 1-based to 0-based
        if not (0 <= idx < len(articles)):
            continue
        original = articles[idx]

        score_raw = item.get("score", 0)
        try:
            score = max(1, min(10, int(score_raw)))
        except (TypeError, ValueError):
            logger.warning("summarizer.item_skipped", extra={"reason": "invalid_score", "score_raw": str(score_raw)})
            continue

        summary = item.get("summary", "").strip()
        why_matters = item.get("why_matters", "").strip()

        if not summary or not why_matters:
            logger.warning("summarizer.item_skipped", extra={"reason": "missing_fields", "has_summary": bool(summary), "has_why_matters": bool(why_matters)})
            continue

        result.append({
            "title": original["title"],
            "url": original["url"],
            "source": original["source"],
            "score": score,
            "summary": summary,
            "why_matters": why_matters,
            "prompt_version": version,
        })

    return result


def _sanitize_text(text: str, max_len: int) -> str:
    """Strip control characters and truncate to max_len."""
    text = text.strip()
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text[:max_len]
