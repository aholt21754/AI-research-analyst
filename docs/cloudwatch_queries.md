# CloudWatch Logs Insights Queries

Saved queries for monitoring the AI Research Analyst pipeline. All queries run
against structured JSON log events emitted by `handlers/daily_digest.py`,
`agents/scraper/agent.py`, and `agents/summarizer/agent.py`.

---

## Setup

1. Open the [AWS CloudWatch Console](https://console.aws.amazon.com/cloudwatch/)
2. In the left sidebar, select **Logs → Logs Insights**
3. In the **Log groups** dropdown, select:
   ```
   /aws/lambda/ai-research-analyst-DailyDigestFunction
   ```
4. Paste the query, set your time range, and click **Run query**
5. To save a query: click **Actions → Save query**, give it a name under a folder like `ai-research-analyst`

---

## Queries

### Daily Cost Trend

Track Claude API spend per run over the last 30 invocations.

```sql
fields @timestamp, cost_usd, digest_count, input_tokens, output_tokens
| filter message = "pipeline.completed"
| sort @timestamp desc
| limit 30
```

**Key fields:** `cost_usd` (USD per run), `digest_count` (articles in digest), `input_tokens` / `output_tokens`

---

### Source Reliability — Failures by Source

Which scraper source fails most often?

```sql
fields source, error_type, attempt
| filter message = "source.fetch_failed"
| stats count() as failures by source
| sort failures desc
```

**Key fields:** `source` (arxiv / hackernews / github / rss), `error_type`, `attempt`

---

### Pipeline Latency Over Time

Average and peak end-to-end latency by day.

```sql
fields total_latency_ms, scraper_article_count, digest_count
| filter message = "pipeline.completed"
| stats avg(total_latency_ms) as avg_ms, max(total_latency_ms) as max_ms by bin(1d)
```

**Key fields:** `total_latency_ms` (full pipeline wall time in ms)

---

### Prompt Quality Drift — Score Distribution

How does Claude score articles over time? A drift toward `low_below_5` suggests
the prompt needs updating or the source content has changed.

```sql
fields @timestamp, high_8_plus, mid_5_7, low_below_5, total
| filter message = "summarizer.score_distribution"
| sort @timestamp desc
| limit 14
```

**Key fields:** `high_8_plus` (scores ≥ 8), `mid_5_7` (scores 5–7), `low_below_5` (scores < 5)

---

### Failed Runs

All pipeline failures with error context.

```sql
fields @timestamp, error_type, error_msg, total_latency_ms
| filter message = "pipeline.failed"
| sort @timestamp desc
```

**Key fields:** `error_type` (Python exception class), `error_msg`

---

### Cold Start Frequency

How often does the Lambda container start cold vs. warm? High cold-start rates
can explain latency spikes.

```sql
fields @timestamp, cold_start
| filter message = "handler.started"
| stats count() as total_invocations, sum(cold_start) as cold_starts by bin(7d)
```

**Key fields:** `cold_start` (boolean, `true` on first invocation of a new container)

---

### Per-Source Article Counts

How many articles does each source contribute after deduplication?

```sql
fields source_results
| filter message = "scraper.dedup_completed"
| sort @timestamp desc
| limit 14
```

Then drill into individual `source_results.{source}.count` fields in the CloudWatch Logs Insights result table.

---

## Recommended Dashboard

Create a CloudWatch Dashboard named `ai-research-analyst` with these widgets:

| Widget Type | Metric / Query | What to Watch |
|-------------|---------------|---------------|
| Line chart | `pipeline.completed → cost_usd` over time | Spending creep |
| Number | `pipeline.completed → digest_count` (latest) | Today's digest count |
| Bar chart | `source.fetch_failed` by `source` | Flaky scrapers |
| Table | `summarizer.score_distribution` (last 14 days) | Prompt quality |
| Alarm status | `LambdaErrorAlarm`, `EmptyDigestAlarm` | Red/green pipeline health |

**To create:** CloudWatch Console → Dashboards → Create dashboard → Add widget → Logs Insights (paste query above) or Metrics (for alarm status).

---

## S3 Run Manifests — Cross-Run Analysis

Every run writes a JSON manifest to S3:
```
s3://{stack-name}-runs-{account-id}/runs/{date}_{run_id}.json
```

Each manifest includes the full schema:
```json
{
  "run_id": "run_20260418_070000_abc123",
  "timestamp": "2026-04-18T07:00:00Z",
  "environment": "lambda",
  "prompt_version": "v1",
  "scraper": {
    "raw_total": 28,
    "after_dedup": 24,
    "sources": {
      "arxiv": {"status": "success", "count": 8, "latency_ms": 320},
      "hackernews": {"status": "success", "count": 12, "latency_ms": 210},
      "github": {"status": "success", "count": 4, "latency_ms": 890},
      "rss": {"status": "success", "count": 8, "latency_ms": 450}
    }
  },
  "summarizer": {
    "model": "claude-haiku-4-5",
    "digest_count": 10,
    "input_tokens": 3200,
    "output_tokens": 1800,
    "cost_usd": 0.00976,
    "latency_ms": 2100
  },
  "digest": [...]
}
```

**Use cases:**
- **Prompt A/B testing:** Filter manifests by `prompt_version`, compare average `summarizer.digest_count` and score distributions across versions.
- **Monthly cost rollup:** Sum `summarizer.cost_usd` across all manifests for the month.
- **Source health over time:** Track per-source `latency_ms` trends to catch degrading sources before they fail.

**Local analysis (Python):**
```python
import json, glob

manifests = [json.load(open(f)) for f in glob.glob("logs/runs/*.json")]
total_cost = sum(m["summarizer"]["cost_usd"] for m in manifests)
print(f"Total cost: ${total_cost:.4f}")
```
