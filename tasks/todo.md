# Phase 1 Implementation Plan: AI Research Analyst

## Context
The project scaffold exists (all files are empty stubs). Phase 1 builds the minimum viable pipeline: scrape AI/ML sources → summarize with Claude Haiku → deliver via email → run on AWS Lambda on a daily schedule. This establishes the core data contract and architecture that later phases (memory, proactive alerts, multi-agent) will extend.

---

## Step 0 (PREREQUISITE): Create `__init__.py` Files
Without these, Python imports will fail entirely.

**Files to create (all empty):**
```
agents/__init__.py
agents/scraper/__init__.py
agents/scraper/sources/__init__.py
agents/summarizer/__init__.py
delivery/__init__.py
handlers/__init__.py
tests/__init__.py
tests/unit/__init__.py
```

---

## Phase 1A: Local Execution

### Step 1: `pyproject.toml`
Populate with all dependencies:
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
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-mock>=3.12", "responses>=0.25"]

[tool.setuptools.packages.find]
where = ["."]
```

### Step 2: `.env.example`
```
ANTHROPIC_API_KEY=sk-ant-...
AWS_REGION=us-east-1
FROM_EMAIL=digest@yourdomain.com
TO_EMAIL=you@example.com
```

### Step 3: Install
```
pip install -e ".[dev]"
```

---

### Step 4–7: Source Files (all in `agents/scraper/sources/`)

**Article dict contract (all sources must return this):**
```python
{
    "title": str,
    "url": str,
    "abstract": str,   # description/content
    "source": str,     # "arxiv" | "hackernews" | "github" | "rss"
    "published_date": str,  # ISO 8601
}
```

**`arxiv.py`** — `fetch_articles(query="LLM agent", max_results=20) -> list[dict]`
- URL: `http://export.arxiv.org/api/query?search_query=...&max_results=...`
- Parse XML with `xml.etree.ElementTree` (stdlib, no extra dep)
- Extract: title, id (→ url), summary (→ abstract), published

**`hackernews.py`** — `fetch_articles(query="LLM OR AI OR machine learning", max_results=20) -> list[dict]`
- URL: `https://hn.algolia.com/api/v1/search?query=...&tags=story&numericFilters=points>10`
- Parse JSON response, map: title→title, url→url, story_text→abstract, created_at→published_date

**`github_trending.py`** — `fetch_articles(language=None, since="daily") -> list[dict]`
- URL: `https://github.com/trending?since=daily`
- Scrape with `requests` + `BeautifulSoup`
- Filter repos with AI/ML keywords in description
- Map: repo name→title, github URL→url, description→abstract, today's date→published_date

**`rss.py`** — `fetch_articles(feed_urls: list[str]) -> list[dict]`
- Default feeds: Papers With Code, The Gradient, Import AI, Sebastian Ruder's Blog
- Parse with `feedparser`
- Map standard RSS fields to Article dict

---

### Step 8: Unit Tests (`tests/unit/test_scraper.py`)
**Gate: all tests must be green before Phase 1B begins.**

Test pattern for each source (using `responses` library or `pytest-mock`):
```python
def test_arxiv_returns_articles(mock_http):
    mock_http.add(GET, ARXIV_URL, body=ARXIV_FIXTURE_XML)
    articles = fetch_articles()
    assert len(articles) > 0
    assert all("title" in a for a in articles)
    assert all("url" in a for a in articles)
    assert all(a["source"] == "arxiv" for a in articles)
```

Fixtures: Store sample API responses in `tests/fixtures/` (arxiv_response.xml, hn_response.json, etc.)

Also test `agents/scraper/agent.py`:
- Verify deduplication (same URL appears once)
- Verify merged output contains items from all sources

---

### Step 9: `agents/scraper/agent.py`
```python
def run(sources=None) -> list[dict]:
    # Call all 4 sources, merge, deduplicate by URL
    # Return sorted by published_date desc
```

---

### Step 10: `agents/summarizer/agent.py`
**Single batch Claude Haiku call (not one per article — minimizes cost and latency).**

```python
def run(articles: list[dict]) -> list[dict]:
    # Truncate abstracts to 300 chars each
    # Build one prompt with all articles numbered
    # Call claude-haiku-4-5 with JSON output instruction
    # Parse JSON response → list of scored summaries
    # Sort by score desc
    # Return top N (default 10)
```

Prompt structure:
```
System: You are a research analyst. Return ONLY valid JSON array.
User: Score and summarize these {n} articles for an AI/ML researcher.
For each return: {"index": N, "score": 1-10, "summary": "one sentence", "why_matters": "brief"}
[Article 1: title + truncated abstract]
...
```

Output dict per article:
```python
{
    "title": str, "url": str, "source": str,
    "score": int,           # 1-10
    "summary": str,         # one sentence
    "why_matters": str,     # brief explanation
}
```

---

### Step 11: `scripts/run_local.py`
```python
# Load .env, call scraper, call summarizer, print formatted digest to console
from dotenv import load_dotenv
load_dotenv()
articles = scraper.run()
digest = summarizer.run(articles)
# Pretty-print top 10 results
```

**Gate: `python scripts/run_local.py` prints a real digest.**

---

## Phase 1B: Lambda Deployment

### Step 12: `handlers/daily_digest.py` (thin handler, <50 lines)
```python
def handler(event, context):
    articles = scraper.run()
    digest = summarizer.run(articles)
    email_digest.send(digest)
    return {"statusCode": 200, "body": f"Sent digest with {len(digest)} items"}
```

### Step 13: `infra/template.yaml` (AWS SAM)
```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31

Parameters:
  FromEmail: {Type: String}
  ToEmail: {Type: String}

Globals:
  Function:
    Runtime: python3.12
    Timeout: 300
    MemorySize: 512
    Environment:
      Variables:
        FROM_EMAIL: !Ref FromEmail
        TO_EMAIL: !Ref ToEmail
        # ANTHROPIC_API_KEY from SSM Parameter Store (not hardcoded)

Resources:
  DailyDigestFunction:
    Type: AWS::Serverless::Function
    Properties:
      Handler: handlers/daily_digest.handler
      Events:
        DailySchedule:
          Type: Schedule
          Properties:
            Schedule: cron(0 7 * * ? *)   # 7AM UTC daily
      Policies:
        - SESCrudPolicy: {IdentityName: !Ref FromEmail}
        - SSMParameterReadPolicy: {ParameterName: anthropic-api-key}
        - CloudWatchLogsFullAccess
```

**Dependency strategy: SAM builds with `BuildMethod: python3.12` — no manual Lambda layer needed.**

### Step 14: `infra/samconfig.toml`
```toml
[default.deploy.parameters]
stack_name = "ai-research-analyst"
region = "us-east-1"
confirm_changeset = true
capabilities = "CAPABILITY_IAM"
parameter_overrides = "FromEmail=digest@yourdomain.com ToEmail=you@example.com"
```

### Step 15: `Makefile`
```makefile
test:
    pytest tests/unit/ -v

build:
    sam build

deploy: build
    sam deploy

invoke:
    sam local invoke DailyDigestFunction

logs:
    sam logs -n DailyDigestFunction --stack-name ai-research-analyst --tail
```

---

## Phase 1C: Email Digest via SES

### Step 16: `delivery/email_digest.py`
```python
import boto3

def send(digest: list[dict], from_email: str, to_email: str) -> None:
    ses = boto3.client("ses")
    html_body = _render_html(digest)   # simple f-string template
    ses.send_email(
        Source=from_email,
        Destination={"ToAddresses": [to_email]},
        Message={
            "Subject": {"Data": f"AI Research Digest — {today}"},
            "Body": {"Html": {"Data": html_body}},
        },
    )
```

HTML template: simple numbered list, score badge, title as link, one-sentence summary, why_matters.

**SES Prerequisites (manual steps before deploy):**
1. Verify `FROM_EMAIL` in AWS SES Console → Verified Identities
2. If account is in SES sandbox, also verify `TO_EMAIL`
3. Store `ANTHROPIC_API_KEY` in AWS SSM Parameter Store as `/ai-research-analyst/anthropic-api-key` (SecureString)

---

## Implementation Checklist

| # | Action | Gate | Done |
|---|--------|------|------|
| 0 | Create all `__init__.py` files | Python imports work | [x] |
| 1 | `pyproject.toml` dependencies | — | [x] |
| 2 | `pip install -e ".[dev]"` | `import anthropic` works | [x] |
| 3 | `.env.example` template | — | [x] |
| 4 | `agents/scraper/sources/arxiv.py` | — | [x] |
| 5 | `agents/scraper/sources/hackernews.py` | — | [x] |
| 6 | `agents/scraper/sources/github_trending.py` | — | [x] |
| 7 | `agents/scraper/sources/rss.py` | — | [x] |
| 8 | `tests/unit/test_scraper.py` (sources) | `pytest tests/unit/` green | [x] |
| 9 | `agents/scraper/agent.py` + agent tests | `pytest tests/unit/` still green | [x] |
| 10 | `agents/summarizer/agent.py` | — | [x] |
| 11 | `scripts/run_local.py` | Digest prints to console | [x] |
| 12 | `delivery/email_digest.py` | — | [x] |
| 13 | `handlers/daily_digest.py` | — | [x] |
| 14 | `infra/template.yaml` + `infra/samconfig.toml` | `sam build` succeeds | [x] |
| 15 | `Makefile` | `make test` + `make invoke` pass | [x] |
| 16 | SES identity verification + SSM secret (manual) | AWS console | [ ] |
| 17 | `make deploy` | Email arrives in inbox | [ ] |

---

## Cost Estimate
- 30 articles × 300-char truncation ≈ 2,700 input tokens + 1,800 output tokens per run
- Claude Haiku pricing: ~$0.002/day → ~$0.06/month
- Lambda + SES: negligible (free tier / $0.10/1k emails)
- **Total: well under $1/month**

---

## Review — Phase 1A (2026-03-22)

**Result:** 41/41 unit tests passing. `pytest tests/unit/ -q` exits 0 with no warnings.

**Files created:**
- `agents/logging_config.py` — structured JSON logging (pythonjsonlogger)
- `agents/scraper/sources/arxiv.py`, `hackernews.py`, `github_trending.py`, `rss.py`
- `agents/scraper/agent.py` — orchestrator with dedup + partial-failure resilience
- `agents/summarizer/prompts/registry.py` + `v1.json` — versioned prompt system
- `agents/summarizer/agent.py` — single-batch Claude Haiku call
- `tests/unit/test_scraper.py` — 41 tests across 5 test classes
- `scripts/run_local.py` — end-to-end local runner

**Issues encountered and fixed:**
1. `setuptools.backends.legacy` not available — switched to `setuptools.build_meta`
2. `responses` library only mocks `requests`, not `urllib` — arxiv.py switched to `requests`
3. `feedparser` uses its own HTTP layer — RSS tests mock `feedparser.parse` directly
4. Python 3.14 reserves `message` in `LogRecord` — renamed all `extra={"message": ...}` → `extra={"error_msg": ...}`

**Next:** Phase 1B — Lambda handler, SAM template, run manifest, Makefile

---

## Review — Phase 1B + 1C (2026-03-22)

**Result:** All Phase 1B/1C files implemented. 41/41 unit tests still passing.

**Files created:**
- `handlers/daily_digest.py` — thin Lambda handler; SSM runtime fetch with `_API_KEY_CACHE`
- `delivery/run_manifest.py` — writes post-run JSON to S3 (lambda) or `logs/runs/` (local)
- `delivery/email_digest.py` — SES HTML email with inline styles, score badges, ranked articles
- `infra/template.yaml` — SAM template: Lambda + EventBridge + S3 + SES identity + config set
- `infra/samconfig.toml` — deployment config (update FromEmail/ToEmail before first deploy)
- `Makefile` — `make test/build/deploy/invoke/logs` targets
- `scripts/test_email.py` — standalone SES smoke test
- `env.local.json` — local invoke env vars (git-ignored)
- `.gitignore` — excludes secrets, logs, .aws-sam/, .env

**Pending manual steps before `make deploy`:**
1. Create SSM SecureString: `aws ssm put-parameter --name /ai-research-analyst/anthropic-api-key --value "sk-ant-..." --type SecureString`
2. Update `FromEmail` and `ToEmail` in `infra/samconfig.toml`
3. After deploy: click verification link in `FROM_EMAIL` inbox (SES sandbox)
4. Verify `TO_EMAIL` in AWS Console → SES → Verified identities (sandbox only)
