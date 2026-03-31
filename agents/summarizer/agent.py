import json
import os

import anthropic

from agents.logging_config import get_logger
from agents.summarizer.prompts.registry import get_prompt

logger = get_logger(__name__)

_MODEL = "claude-haiku-4-5"
_MAX_INPUT_ARTICLES = 30
_ABSTRACT_TRUNCATE = 300


def run(articles: list[dict], prompt_version: str = None, top_n: int = 10) -> list[dict]:
    if not articles:
        return []

    version, system_prompt, user_template = get_prompt(prompt_version)
    batch = articles[:_MAX_INPUT_ARTICLES]

    articles_text = "\n\n".join(
        f"[Article {i + 1}]\nTitle: {a['title']}\nAbstract: {a['abstract'][:_ABSTRACT_TRUNCATE]}\nURL: {a['url']}"
        for i, a in enumerate(batch)
    )
    user_message = user_template.format(num_articles=len(batch), articles_text=articles_text)

    logger.info("summarizer.call_started", extra={"num_articles": len(batch), "model": _MODEL, "prompt_version": version})

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text
    logger.info(
        "summarizer.call_completed",
        extra={
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "prompt_version": version,
        },
    )

    scored = _parse_response(raw, batch, version)
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    return scored[:top_n]


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

    result = []
    for item in items:
        idx = item.get("index", 0) - 1  # convert 1-based to 0-based
        if not (0 <= idx < len(articles)):
            continue
        original = articles[idx]
        result.append({
            "title": original["title"],
            "url": original["url"],
            "source": original["source"],
            "score": int(item.get("score", 0)),
            "summary": item.get("summary", ""),
            "why_matters": item.get("why_matters", ""),
            "prompt_version": version,
        })

    return result
