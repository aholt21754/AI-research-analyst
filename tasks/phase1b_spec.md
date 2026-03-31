# Phase 1B Specification: Lambda Deployment

## Overview
Move the working local pipeline (Phase 1A) to AWS Lambda, invoked daily via EventBridge. The handler stays thin — all logic lives in `agents/`. Add structured CloudWatch logging and a run manifest for observability.

**Prerequisite:** `pytest tests/unit/ -v` must be green before starting Phase 1B.

---

## Logging Decision: CloudWatch over S3 + Athena

**Decision: Use CloudWatch Logs with structured JSON.**

Rationale:
- Lambda stdout is automatically captured to CloudWatch — zero extra infrastructure
- 300KB/month ingestion (1 run/day × ~10KB) is well under the **5 GB/month free tier**
- CloudWatch Insights queries on structured JSON are free at this volume
- S3 + Athena costs ~$0.0002/month (more expensive than free, adds complexity)
- CloudWatch Insights supports dot-notation field queries on JSON log events

**CloudWatch Insights example queries:**
```
# Average scraper latency by source
fields @timestamp, source, latency_ms
| filter ispresent(source) and event = "source.fetch_completed"
| stats avg(latency_ms) as avg_ms by source

# Failed sources
fields @timestamp, source, error_type
| filter event = "source.fetch_failed"
| sort @timestamp desc
| limit 20

# Token usage trend
fields @timestamp, input_tokens, output_tokens, cost_usd
| filter event = "summarizer.call_completed"
| stats sum(cost_usd) as total_cost, avg(input_tokens) as avg_tokens by bin(7d)
```

---

## Run Manifest

A lightweight JSON file written after each run for cross-run comparison (prompt A/B testing, regression detection). Stored in S3 (not CloudWatch) because it's structured data for analysis, not a log stream.

**S3 key pattern:** `runs/{YYYY-MM-DD}_{run_id}.json`

**Content:**
```json
{
  "run_id": "run_20260321_abc123",
  "timestamp": "2026-03-21T07:00:00Z",
  "environment": "lambda",
  "prompt_version": "v1",
  "scraper": {
    "sources": {
      "arxiv":      {"count": 8, "latency_ms": 12000, "status": "success"},
      "hackernews": {"count": 5, "latency_ms":  3000, "status": "success"},
      "github":     {"count": 3, "latency_ms":  5000, "status": "success"},
      "rss":        {"count": 9, "latency_ms":  8000, "status": "success"}
    },
    "raw_total": 25,
    "after_dedup": 22
  },
  "summarizer": {
    "model": "claude-haiku-4-5",
    "prompt_version": "v1",
    "input_tokens": 3200,
    "output_tokens": 1600,
    "cost_usd": 0.0019,
    "latency_ms": 7800
  },
  "digest": [
    {"title": "...", "url": "...", "score": 9, "source": "arxiv", "prompt_version": "v1"}
  ]
}
```

**To compare two runs:** Download both JSON files from S3 and diff.
**To compare prompt versions:** Filter `digest[].prompt_version` across runs.

---

## Files to Implement

### `handlers/daily_digest.py`
Thin Lambda entry point. No business logic — only wires agents together. Fetches the Anthropic API key from SSM at cold start and caches it for warm invocations.

```python
import os
import json
import boto3
from agents.scraper import agent as scraper
from agents.summarizer import agent as summarizer
from delivery import email_digest
from delivery import run_manifest

_API_KEY_CACHE = None  # module-level: survives Lambda warm starts

def _get_api_key() -> str:
    global _API_KEY_CACHE
    if _API_KEY_CACHE:
        return _API_KEY_CACHE
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(
        Name="/ai-research-analyst/anthropic-api-key",
        WithDecryption=True,
    )
    _API_KEY_CACHE = response["Parameter"]["Value"]
    return _API_KEY_CACHE

def handler(event, context):
    os.environ["ANTHROPIC_API_KEY"] = _get_api_key()  # set before agent imports use it
    articles = scraper.run()
    digest = summarizer.run(articles)
    email_digest.send(digest)
    run_manifest.write(articles, digest)
    return {
        "statusCode": 200,
        "body": json.dumps({"digest_count": len(digest)})
    }
```

---

### `delivery/run_manifest.py`
Writes the post-run JSON to S3. Called from `handler` and optionally from `run_local.py` (writing to `./logs/runs/` locally).

```python
import json
import os
import uuid
from datetime import datetime, timezone

def write(articles: list[dict], digest: list[dict]) -> None:
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    manifest = _build(run_id, articles, digest)

    env = os.getenv("ENV", "local")
    if env == "local":
        _write_local(run_id, manifest)
    else:
        _write_s3(run_id, manifest)

def _build(run_id, articles, digest) -> dict:
    # Construct the manifest dict (see structure above)
    ...

def _write_local(run_id, manifest) -> None:
    os.makedirs("logs/runs", exist_ok=True)
    with open(f"logs/runs/{run_id}.json", "w") as f:
        json.dump(manifest, f, indent=2)

def _write_s3(run_id, manifest) -> None:
    import boto3
    s3 = boto3.client("s3")
    bucket = os.environ["RUNS_BUCKET"]
    key = f"runs/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}_{run_id}.json"
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(manifest, indent=2))
```

---

### `infra/template.yaml` (AWS SAM)

Full SAM template for Phase 1B. Phase 1C will add SES resources.

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31

Description: AI Research Analyst - Daily digest pipeline

Parameters:
  FromEmail:
    Type: String
    Description: Verified SES sender address
  ToEmail:
    Type: String
    Description: Recipient email address

Globals:
  Function:
    Runtime: python3.12
    Timeout: 300
    MemorySize: 512
    Environment:
      Variables:
        ENV: lambda
        FROM_EMAIL: !Ref FromEmail
        TO_EMAIL: !Ref ToEmail
        RUNS_BUCKET: !Ref RunsBucket
        # ANTHROPIC_API_KEY fetched at runtime from SSM (see handler — not injected here)

Resources:

  RunsBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub '${AWS::StackName}-runs-${AWS::AccountId}'
      LifecycleConfiguration:
        Rules:
          - Id: DeleteOldRuns
            Status: Enabled
            ExpirationInDays: 90

  DailyDigestFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: ./
      Handler: handlers/daily_digest.handler
      Policies:
        - AWSLambdaBasicExecutionRole
        - Statement:
            - Effect: Allow
              Action:
                - ses:SendEmail
                - ses:SendRawEmail
              Resource: '*'
            - Effect: Allow
              Action:
                - s3:PutObject
              Resource: !Sub '${RunsBucket.Arn}/runs/*'
            - Effect: Allow
              Action:
                - ssm:GetParameter
              Resource: !Sub 'arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/ai-research-analyst/*'
      Events:
        DailySchedule:
          Type: Schedule
          Properties:
            Schedule: cron(0 7 * * ? *)
            Description: Daily AI research digest at 7AM UTC
            Enabled: true

Outputs:
  DailyDigestFunctionArn:
    Value: !GetAtt DailyDigestFunction.Arn
  RunsBucketName:
    Value: !Ref RunsBucket
```

**SSM at runtime:** The `ANTHROPIC_API_KEY` is NOT injected as an environment variable. The handler fetches it from SSM at cold start and caches it in a module-level variable for warm invocations (see handler pattern below). This keeps the key out of the Lambda console, CloudFormation outputs, and CloudTrail logs.

---

### `infra/samconfig.toml`

```toml
version = 0.1

[default]
[default.global.parameters]
stack_name = "ai-research-analyst"

[default.build.parameters]
cached = true
parallel = true

[default.deploy.parameters]
capabilities = "CAPABILITY_IAM"
confirm_changeset = true
region = "us-east-1"
resolve_s3 = true
parameter_overrides = [
    "FromEmail=your-from@example.com",
    "ToEmail=your-to@example.com"
]
```

Update `FromEmail` and `ToEmail` before first deploy.

---

### `Makefile`

```makefile
.PHONY: test build deploy invoke logs

test:
	pytest tests/unit/ -v

build:
	sam build

deploy: build
	sam deploy

invoke:
	sam local invoke DailyDigestFunction \
		--env-vars env.local.json

logs:
	sam logs -n DailyDigestFunction \
		--stack-name ai-research-analyst \
		--tail
```

**`env.local.json`** (for `sam local invoke`, git-ignored):
```json
{
  "DailyDigestFunction": {
    "ANTHROPIC_API_KEY": "sk-ant-...",
    "FROM_EMAIL": "your-from@example.com",
    "TO_EMAIL": "your-to@example.com",
    "ENV": "local"
  }
}
```

---

## Pre-Deploy Checklist

- [ ] SSM Parameter created: `aws ssm put-parameter --name /ai-research-analyst/anthropic-api-key --value "sk-ant-..." --type SecureString`
- [ ] `FROM_EMAIL` updated in `samconfig.toml`
- [ ] `TO_EMAIL` updated in `samconfig.toml`
- [ ] `sam build` succeeds locally
- [ ] `make invoke` runs pipeline and prints output (uses `env.local.json`)
- [ ] `make deploy` — confirm changeset, approve

---

## Verification

| Gate | Command | Expected |
|------|---------|----------|
| Tests pass | `pytest tests/unit/ -v` | All green |
| SAM build | `sam build` | No errors |
| Local invoke | `make invoke` | Digest JSON returned |
| CloudWatch logs | `make logs` | Structured JSON log events visible |
| Run manifest | Check S3 bucket | `runs/YYYY-MM-DD_run_*.json` present |
| Scheduled trigger | Wait for 7AM UTC | CloudWatch shows auto-invocation log |

---

## Files Created/Modified in Phase 1B

| File | Action |
|------|--------|
| `handlers/daily_digest.py` | Implemented |
| `delivery/run_manifest.py` | Created |
| `infra/template.yaml` | Implemented |
| `infra/samconfig.toml` | Implemented |
| `Makefile` | Created |
| `env.local.json` | Created (git-ignored) |
| `.gitignore` | Add `env.local.json`, `logs/`, `.aws-sam/` |
