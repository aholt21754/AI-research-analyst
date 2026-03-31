# Phase 1A Specification: Local Agent Execution

## Overview
Build the end-to-end scrape → summarize → print pipeline running locally via `scripts/run_local.py`.
All agent logic must be independently testable and establish the data contracts used by every subsequent phase.

---

## Article Dict Contract
All source files return `list[dict]` conforming to this schema. No exceptions.

```python
{
    "title": str,           # Article/repo/paper title
    "url": str,             # Canonical URL (used for deduplication)
    "abstract": str,        # Description, summary, or content excerpt
    "source": str,          # "arxiv" | "hackernews" | "github" | "rss"
    "published_date": str,  # ISO 8601, e.g. "2026-03-21T07:00:00Z"
}
```

---

## Step 0: Package Structure

Create empty `__init__.py` files — without these, Python imports fail before any code runs.

```
agents/__init__.py
agents/scraper/__init__.py
agents/scraper/sources/__init__.py
agents/summarizer/__init__.py
agents/summarizer/prompts/__init__.py
delivery/__init__.py
handlers/__init__.py
tests/__init__.py
tests/unit/__init__.py
tests/fixtures/__init__.py
```

---

## Step 1: `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "ai-research-analyst"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "anthropic>=0.30",
    "requests>=2.31",
    "feedparser>=6.0",
    "beautifulsoup4>=4.12",
    "boto3>=1.34",
    "python-dotenv>=1.0",
    "python-json-logger>=2.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-mock>=3.12", "responses>=0.25"]

[tool.setuptools.packages.find]
where = ["."]
```

Install: `pip install -e ".[dev]"`

---

## Step 2: `.env.example`

```
ANTHROPIC_API_KEY=sk-ant-...
AWS_REGION=us-east-1
FROM_EMAIL=digest@yourdomain.com
TO_EMAIL=you@example.com
ENV=local
```

---

## Steps 3–6: Source Files

### General Error Handling Rules (applies to all sources)
1. **Never raise** — catch all exceptions, log them, return `[]`
2. **Retry only transient errors** — 5xx, timeout, rate limit (up to 3 attempts, 1/3/7s backoff). Never retry 4xx.
3. **Partial success** — if some articles in a response fail to parse, return the ones that succeeded
4. **Timeout always set** — `timeout=30` prevents Lambda from hanging indefinitely
5. **Validate required fields** — skip any article missing `title`, `url`, or `published_date`

### `agents/scraper/sources/arxiv.py`

**Endpoint:** `http://export.arxiv.org/api/query?search_query={query}&max_results={n}`
**Parser:** `xml.etree.ElementTree` (stdlib — no extra dependency)
**Namespace:** Atom — `http://www.w3.org/2005/Atom`

**Signature:** `fetch_articles(query: str = "LLM agent", max_results: int = 20) -> list[dict]`

**Error handling:**

| Error | Exception | Action |
|-------|-----------|--------|
| HTTP timeout | `urllib.error.URLError` with `socket.timeout` reason | Log + retry (up to 3x) |
| HTTP 429 rate limit | `urllib.error.HTTPError` code 429 | Log + retry with backoff |
| HTTP 5xx server error | `urllib.error.HTTPError` code 5xx | Log + retry |
| HTTP 4xx client error | `urllib.error.HTTPError` code 4xx | Log + return `[]` (no retry) |
| XML root parse failure | `xml.etree.ElementTree.ParseError` | Log + return `[]` |
| Missing field on entry | `AttributeError` or None check | Log warning + skip that entry |
| All retries exhausted | — | Log error + return `[]` |

**arXiv-specific:** The `id` element contains a URL like `http://arxiv.org/abs/2501.12345v1` — use this directly as `url`. Strip whitespace from `title` and `summary` fields.

---

### `agents/scraper/sources/hackernews.py`

**Endpoint:** `https://hn.algolia.com/api/v1/search?query={query}&tags=story&numericFilters=points>10`
**Parser:** `response.json()` via `requests`

**Signature:** `fetch_articles(query: str = "LLM agent machine learning", max_results: int = 20) -> list[dict]`

**Field mapping:**

| HN field | Article field | Fallback |
|----------|---------------|---------|
| `title` | `title` | Skip article |
| `url` | `url` | Use `objectID` to build `https://news.ycombinator.com/item?id={objectID}` |
| `story_text` | `abstract` | `""` (HN links often have no text) |
| `created_at` | `published_date` | Skip article |

**Error handling:**

| Error | Exception | Action |
|-------|-----------|--------|
| HTTP timeout | `requests.exceptions.Timeout` | Log + retry |
| Connection error | `requests.exceptions.ConnectionError` | Log + retry |
| HTTP non-200 | Check `response.status_code` | Log + retry if 5xx, return `[]` if 4xx |
| JSON decode failure | `json.JSONDecodeError` | Log + return `[]` |
| Missing `hits` key | `KeyError` | Log + return `[]` |
| Missing field per item | `KeyError` on item | Log warning + skip that item |

---

### `agents/scraper/sources/github_trending.py`

**Endpoint:** `https://github.com/trending?since=daily`
**Parser:** `requests` + `BeautifulSoup(html, "html.parser")`

**Signature:** `fetch_articles(since: str = "daily") -> list[dict]`

**Scraping approach:**
- Select `article.Box-row` elements (GitHub trending repo cards)
- Extract repo name from `h2 > a` (href attribute)
- Extract description from `p` within the article
- Build full GitHub URL: `https://github.com{href}`
- `published_date`: use today's ISO date (GitHub trending has no timestamps)
- **Filter:** only include repos where description contains AI/ML keywords: `["llm", "ai", "ml", "machine learning", "neural", "transformer", "diffusion", "embedding", "inference", "finetune", "fine-tune", "agent", "gpt", "bert", "claude", "openai", "anthropic", "hugging"]`

**Error handling:**

| Error | Exception | Action |
|-------|-----------|--------|
| HTTP timeout | `requests.exceptions.Timeout` | Log + retry |
| Connection error | `requests.exceptions.ConnectionError` | Log + retry |
| HTTP non-200 | Check `response.status_code` | Log + return `[]` |
| No articles found | Empty `article` list | Log warning + return `[]` (GitHub may have changed HTML) |
| Missing href/description | `AttributeError` or None | Log warning + skip that repo |

**Important:** GitHub's HTML structure can change. If zero articles are found, log a `github.structure_changed` warning so it's easy to diagnose.

---

### `agents/scraper/sources/rss.py`

**Parser:** `feedparser` library
**Default feeds:**
```python
DEFAULT_FEEDS = [
    "https://paperswithcode.com/rss",          # Papers With Code
    "https://thegradient.pub/rss/",            # The Gradient
    "https://lastweekin.ai/feed",              # Last Week in AI
    "http://feeds.feedburner.com/blogspot/gJZg", # Google Research Blog
]
```

**Signature:** `fetch_articles(feed_urls: list[str] = DEFAULT_FEEDS) -> list[dict]`

**Field mapping (feedparser):**

| feedparser field | Article field | Fallback |
|-----------------|---------------|---------|
| `entry.title` | `title` | Skip entry |
| `entry.link` | `url` | Skip entry |
| `entry.summary` or `entry.content[0].value` | `abstract` | `""` |
| `entry.published` | `published_date` | Today's ISO date |

**Error handling:**

| Error | Scenario | Action |
|-------|----------|--------|
| `feedparser.parse()` raises | Unexpected exception | Log + skip that feed, continue to next |
| `feed.bozo == True` | Malformed XML/feed | Log warning + still attempt to extract entries |
| `feed.status != 200` | HTTP error | Log + skip that feed |
| Missing required field | None/missing on entry | Log warning + skip that entry |
| Empty entries list | Valid feed but no content | Log info (not an error) + return `[]` for that feed |

**Note:** `feedparser` is very tolerant of malformed feeds (`bozo` flag). Always attempt to process entries even when `bozo == True` — many real feeds trigger this.

---

## Step 7: `agents/scraper/agent.py`

**Signature:** `run(sources: list[str] = None) -> list[dict]`

**Logic:**
1. Call all 4 sources in sequence (not parallel — Lambda has no threading benefit here)
2. Merge all results into one list
3. Deduplicate by `url` — keep first occurrence (sorted by source priority: arxiv > hackernews > github > rss)
4. Sort by `published_date` descending
5. Return up to 40 articles (generous — summarizer will filter down to 10)

**Resilience:** If a source raises an uncaught exception (belt-and-suspenders), catch it, log `scraper.source_fatal_error`, continue. The pipeline must never die because one source is down.

---

## Step 8: Unit Tests (`tests/unit/test_scraper.py`)

**Testing approach:** Use `responses` library to mock HTTP calls. Store fixture files in `tests/fixtures/`.

**Fixture files needed:**
- `tests/fixtures/arxiv_response.xml` — sample arXiv Atom XML with 3 entries
- `tests/fixtures/hn_response.json` — sample HN Algolia JSON with 3 entries
- `tests/fixtures/github_trending.html` — sample GitHub trending page HTML with 3 repos
- `tests/fixtures/rss_response.xml` — sample RSS feed with 3 entries

### Full Test Case List

**`TestArxivSource`**
- `test_happy_path_returns_articles` — valid XML → 3 Article dicts returned
- `test_article_has_all_required_fields` — each dict has title, url, abstract, source, published_date
- `test_source_field_is_arxiv` — `source == "arxiv"` on all results
- `test_url_is_https_arxiv` — URL is valid `https://arxiv.org/abs/...` format
- `test_http_timeout_returns_empty_list` — mock timeout → `[]` returned, no exception raised
- `test_http_500_retries_and_returns_empty` — mock 500 → retries 3x → returns `[]`
- `test_http_404_returns_empty_no_retry` — mock 404 → returns `[]` immediately (no retry)
- `test_malformed_xml_returns_empty_list` — invalid XML → `[]` returned
- `test_partial_parse_returns_valid_entries` — XML with 2 valid + 1 missing-title entry → 2 articles returned
- `test_empty_result_returns_empty_list` — valid XML with zero entries → `[]`
- `test_whitespace_stripped_from_title` — title with leading/trailing whitespace → stripped

**`TestHackerNewsSource`**
- `test_happy_path_returns_articles` — valid JSON → Article dicts returned
- `test_article_has_all_required_fields` — all fields present
- `test_source_field_is_hackernews` — `source == "hackernews"` on all results
- `test_missing_url_falls_back_to_hn_link` — item with no `url` → uses HN item URL
- `test_http_timeout_returns_empty_list` — mock timeout → `[]`
- `test_http_500_returns_empty_list` — mock 500 → `[]`
- `test_invalid_json_returns_empty_list` — non-JSON response → `[]`
- `test_missing_hits_key_returns_empty_list` — JSON without `hits` key → `[]`
- `test_missing_item_field_skips_item` — item missing `title` → item skipped, others returned

**`TestGithubTrendingSource`**
- `test_happy_path_returns_ai_repos` — valid HTML with AI repos → articles returned
- `test_article_has_all_required_fields` — all fields present
- `test_source_field_is_github` — `source == "github"` on all results
- `test_non_ai_repos_filtered_out` — HTML with non-AI repos → `[]`
- `test_http_timeout_returns_empty_list` — mock timeout → `[]`
- `test_http_500_returns_empty_list` — mock 500 → `[]`
- `test_empty_trending_page_returns_empty_list` — HTML with no article elements → `[]`
- `test_url_is_full_github_url` — URL is `https://github.com/...`

**`TestRssSource`**
- `test_happy_path_returns_articles` — valid RSS → Article dicts returned
- `test_article_has_all_required_fields` — all fields present
- `test_source_field_is_rss` — `source == "rss"` on all results
- `test_malformed_feed_still_extracts_entries` — bozo feed → attempts extraction
- `test_empty_feed_returns_empty_list` — valid feed with zero entries → `[]`
- `test_multiple_feeds_combined` — 2 feeds with 3 entries each → 6 articles
- `test_failed_feed_skips_continues_to_next` — first feed errors → second feed still processed
- `test_missing_published_date_uses_today` — entry without published → today's date used

**`TestScraperAgent`**
- `test_merges_results_from_all_sources` — all 4 sources return articles → all in output
- `test_deduplication_removes_same_url` — same URL from 2 sources → appears once
- `test_sorted_by_date_descending` — articles with mixed dates → most recent first
- `test_one_source_fails_others_succeed` — mock one source to raise → other 3 still in output
- `test_all_sources_fail_returns_empty_list` — all sources raise → `[]`, no exception
- `test_returns_at_most_40_articles` — sources return 50 total → max 40 returned

---

## Step 9: Prompt Versioning

### File structure
```
agents/summarizer/prompts/
├── __init__.py
├── registry.py    # Version loader + cache
└── v1.json        # Baseline prompt
```

### `agents/summarizer/prompts/registry.py`
```python
import json
from pathlib import Path

PROMPT_DIR = Path(__file__).parent
LATEST_VERSION = "v1"  # Update this string when promoting new versions

class PromptRegistry:
    _cache: dict = {}

    @classmethod
    def load(cls, version: str = "latest") -> dict:
        if version == "latest":
            version = LATEST_VERSION
        if version in cls._cache:
            return cls._cache[version]
        path = PROMPT_DIR / f"{version}.json"
        if not path.exists():
            raise FileNotFoundError(f"Prompt version '{version}' not found at {path}")
        with open(path) as f:
            prompt = json.load(f)
        cls._cache[version] = prompt
        return prompt

def get_prompt(version: str = None) -> tuple[str, str, str]:
    """Returns (version_str, system_prompt, user_template)"""
    version = version or "latest"
    data = PromptRegistry.load(version)
    actual_version = data["version"]
    return actual_version, data["system"], data["user_template"]
```

### `agents/summarizer/prompts/v1.json`
```json
{
  "version": "v1",
  "created_at": "2026-03-21",
  "description": "Phase 1 baseline: technical depth scoring for AI/ML articles",
  "model": "claude-haiku-4-5",
  "system": "You are an expert AI research analyst. Score and summarize technical AI/ML articles for a senior engineer focused on LLMs, agents, fine-tuning, and inference optimization.\n\nReturn ONLY a valid JSON array. No preamble, no explanation, no markdown — just the array. Each element must have exactly these fields:\n- index: integer (article index from input, 1-based)\n- score: integer 1-10 (see scoring rubric)\n- summary: string, one sentence, max 15 words\n- why_matters: string, max 30 words explaining practical engineering value\n\nSCORING RUBRIC:\n\n9-10 HIGHLY RELEVANT: Novel design pattern, architecture, or optimization directly applicable to production LLM systems. Must include NEW method with quantified results (benchmarks, timings, or quality metrics). Examples: new attention mechanism, inference optimization breakthrough, novel agent loop, fine-tuning method beating SOTA.\n  Ask yourself: Would you reference this in a design doc? → 9-10\n\n7-8 RELEVANT: Strong technical depth on existing methods with new insights, detailed comparison, or excellent non-obvious tutorial. Actionable for engineering decisions. Examples: LoRA variant comparison with benchmarks, detailed agent framework comparison, inference serving deep-dive.\n  Ask yourself: Would this inform your architecture choices? → 7-8\n\n5-6 MODERATELY RELEVANT: Solid fundamentals but limited novelty. Literature surveys, well-known technique explainers, or tangentially applicable ML content.\n  Ask yourself: Is this a textbook section? → 5-6\n\n3-4 TANGENTIALLY RELEVANT: AI/ML-related but lacks technical depth. Product announcements, high-level trend pieces, or industry news with some technical mention.\n  Ask yourself: Would you reference this in a code review? → No → 3-4\n\n1-2 NOT RELEVANT: Marketing, hype, opinion without technical basis, or off-topic.\n  Ask yourself: Is this trying to sell something or make an unproven claim? → 1-2\n\nEDGE CASES:\n- LLM safety/alignment: score ≤ 6 unless introducing novel technique with quantified results\n- Model capability announcements: score 5-6 for technical details, 3-4 for press release style\n- Agent frameworks (AutoGPT, LangChain etc.): score 7-8 for architectural comparison, 5-6 for tutorials\n- Fine-tuning (LoRA, QLoRA): score 8-9 for novel method with benchmarks, 7 for explaining existing well\n- Deployment/ops: score 7-8 if covering inference optimization specifics, 5-6 if high-level",
  "user_template": "Score and summarize these {num_articles} articles for a senior AI/ML engineer:\n\n{articles_text}\n\nReturn the JSON array now."
}
```

---

## Step 10: `agents/summarizer/agent.py`

**Signature:** `run(articles: list[dict], prompt_version: str = None, top_n: int = 10) -> list[dict]`

**Logic:**
1. Load prompt from registry (`get_prompt(prompt_version)`)
2. Truncate each article's abstract to 300 chars
3. Build numbered article text block
4. Make ONE `client.messages.create` call to `claude-haiku-4-5`
5. Parse JSON response — handle parse errors with a retry (ask Claude to fix it)
6. Merge scores back with original article data (to carry forward `url`, `source`, `title`)
7. Sort by `score` descending, return top `top_n`

**Output dict per article:**
```python
{
    "title": str,
    "url": str,
    "source": str,
    "score": int,           # 1-10
    "summary": str,         # one sentence, max 15 words
    "why_matters": str,     # max 30 words
    "prompt_version": str,  # e.g. "v1"
}
```

**Token budget (30 articles):**
- Input: ~30 × 80 tokens + system prompt ~600 tokens ≈ 3,000 tokens
- Output: ~30 × 60 tokens ≈ 1,800 tokens
- Cost per run at Haiku pricing: ~$0.002

---

## Step 11: Observability

### Logging Setup (`agents/logging_config.py`)
```python
import logging
import os
from pythonjsonlogger import jsonlogger

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # Already configured
    level = logging.DEBUG if os.getenv("ENV", "local") == "local" else logging.INFO
    logger.setLevel(level)
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
```

**Each source file imports:** `from agents.logging_config import get_logger; logger = get_logger(__name__)`

### Events to log at each stage

| Stage | Event name | Key fields |
|-------|-----------|------------|
| Source fetch start | `source.fetch_started` | source, query |
| Source fetch success | `source.fetch_completed` | source, count, latency_ms |
| Source fetch failure | `source.fetch_failed` | source, error_type, attempt, retryable |
| Parse failure (root) | `source.parse_error` | source, error, retryable=False |
| Parse skip (entry) | `source.entry_skipped` | source, reason, entry_index |
| Deduplication done | `scraper.dedup_completed` | before, after, removed |
| Summarizer call start | `summarizer.call_started` | num_articles, model, prompt_version |
| Summarizer call success | `summarizer.call_completed` | input_tokens, output_tokens, cost_usd, latency_ms |
| JSON parse error | `summarizer.parse_error` | error, raw_length, attempt |
| Pipeline done | `pipeline.completed` | total_articles, digest_count, total_latency_ms |

### Run Manifest (`logs/runs/YYYY-MM-DD_runid.json`)
Written at end of each run to `./logs/runs/` locally (S3 in Phase 1B).
```json
{
  "run_id": "run_20260321_abc123",
  "timestamp": "2026-03-21T07:00:00Z",
  "environment": "local",
  "prompt_version": "v1",
  "scraper": {
    "sources": {
      "arxiv": {"count": 8, "latency_ms": 12000, "status": "success"},
      "hackernews": {"count": 5, "latency_ms": 3000, "status": "success"},
      "github": {"count": 3, "latency_ms": 5000, "status": "success"},
      "rss": {"count": 9, "latency_ms": 8000, "status": "success"}
    },
    "raw_total": 25,
    "after_dedup": 22
  },
  "summarizer": {
    "input_tokens": 3200,
    "output_tokens": 1600,
    "cost_usd": 0.0019,
    "latency_ms": 7800
  },
  "digest": [
    {"title": "...", "url": "...", "score": 9, "prompt_version": "v1"}
  ]
}
```

`./logs/runs/` is git-ignored. To compare two runs: `diff logs/runs/run_A.json logs/runs/run_B.json`.
To compare prompt versions: filter `digest[].prompt_version` and compare score distributions.

---

## Step 12: `scripts/run_local.py`

```python
from dotenv import load_dotenv
load_dotenv()

from agents.scraper import agent as scraper
from agents.summarizer import agent as summarizer

articles = scraper.run()
digest = summarizer.run(articles)

# Pretty-print
print(f"\n=== AI Research Digest ({len(digest)} articles) ===\n")
for i, item in enumerate(digest, 1):
    print(f"{i}. [{item['score']}/10] {item['title']}")
    print(f"   {item['summary']}")
    print(f"   Why it matters: {item['why_matters']}")
    print(f"   {item['url']}\n")
```

**Gate:** `python scripts/run_local.py` prints a real digest with scores and summaries.

---

## Verification Checklist

- [ ] `pytest tests/unit/ -v` → all tests green
- [ ] `python scripts/run_local.py` → digest prints with 10 articles, scores 1-10, summaries
- [ ] Run manifest written to `logs/runs/`
- [ ] At least one 9-10 score article in digest (proves rubric is working)
- [ ] No unhandled exceptions when a source is unreachable (test by blocking a URL in `/etc/hosts`)

---

## Files Created/Modified in Phase 1A

| File | Status |
|------|--------|
| `pyproject.toml` | Modified |
| `.env.example` | Modified |
| `agents/__init__.py` and sub-packages | Created |
| `agents/logging_config.py` | Created |
| `agents/scraper/sources/arxiv.py` | Implemented |
| `agents/scraper/sources/hackernews.py` | Implemented |
| `agents/scraper/sources/github_trending.py` | Implemented |
| `agents/scraper/sources/rss.py` | Implemented |
| `agents/scraper/agent.py` | Implemented |
| `agents/summarizer/prompts/registry.py` | Created |
| `agents/summarizer/prompts/v1.json` | Created |
| `agents/summarizer/agent.py` | Implemented |
| `scripts/run_local.py` | Implemented |
| `tests/unit/test_scraper.py` | Created |
| `tests/fixtures/*.xml / *.json / *.html` | Created |
| `logs/runs/` | Created (git-ignored) |
