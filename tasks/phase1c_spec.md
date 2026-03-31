# Phase 1C Specification: Email Digest via SES

## Overview
Send the daily digest as an HTML email using AWS SES. This phase adds:
- SES email identity provisioned via CloudFormation
- HTML email template rendered from digest output
- SSM Parameter Store for the Anthropic API key (non-negotiable — plain-text secrets in env vars or code are a security risk)
- Updated SAM template with SES resources
- Full cost breakdown including all AWS services

**Prerequisite:** Phase 1B deployed and `make invoke` returning a successful response.

---

## SES Setup Process

### How SES Email Identity Works

AWS SES requires you to **verify ownership** of any email address or domain before sending. There are two approaches:

| Approach | Verification Method | CloudFormation Support | Best For |
|----------|-------------------|----------------------|----------|
| **Email address** | Click link in verification email | `AWS::SES::EmailIdentity` creates identity; human clicks link | Portfolio/personal use |
| **Domain** | Add DNS records (DKIM CNAME entries) | `AWS::SES::EmailIdentity` outputs DNS tokens | Production |

**Recommendation for Phase 1:** Verify a single email address. It's sufficient for a personal digest and requires no DNS changes.

### SES Sandbox vs. Production

All new AWS accounts start in SES **sandbox mode**:
- Can only send **to** verified addresses (not arbitrary recipients)
- Limit: 200 emails/24hr, 1 msg/sec
- **For this project:** Verify both `FROM_EMAIL` and `TO_EMAIL` → sandbox works fine

To exit sandbox: submit a manual support request in AWS Console → SES → Account dashboard → Request production access. AWS reviews in 24–48 hours. Required for sending to unverified addresses (i.e., subscribers).

---

## SSM Parameter Store for API Key

**Non-negotiable.** Storing secrets as plain-text Lambda environment variables exposes them in:
- CloudFormation template outputs
- AWS Console (Lambda → Configuration → Environment variables)
- CloudTrail logs
- Any IAM principal with `lambda:GetFunctionConfiguration`

**Setup (one-time manual step, before deploy):**
```bash
aws ssm put-parameter \
  --name "/ai-research-analyst/anthropic-api-key" \
  --value "sk-ant-YOUR_KEY_HERE" \
  --type SecureString \
  --description "Anthropic API key for AI Research Analyst"
```

- Uses `aws/ssm` default KMS key (no extra KMS cost)
- Standard tier: free storage, free API calls
- Lambda fetches at cold start, cached in memory for warm invocations

**Runtime fetch pattern (in `handlers/daily_digest.py`):**
```python
import boto3
import os

_API_KEY_CACHE = None  # module-level cache survives warm starts

def _get_api_key() -> str:
    global _API_KEY_CACHE
    if _API_KEY_CACHE:
        return _API_KEY_CACHE
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(
        Name="/ai-research-analyst/anthropic-api-key",
        WithDecryption=True
    )
    _API_KEY_CACHE = response["Parameter"]["Value"]
    return _API_KEY_CACHE
```

Set `ANTHROPIC_API_KEY = _get_api_key()` before calling any agent code.

---

## `delivery/email_digest.py`

### Responsibilities
1. Format digest list into HTML
2. Send via `boto3` SES client
3. Use `FROM_EMAIL` and `TO_EMAIL` from environment

### HTML Template Design
Simple, readable, no external CSS dependencies (many email clients strip `<style>` tags — use inline styles).

**Structure:**
```
Subject: AI Research Digest — March 21, 2026

[Header: title + article count + date]

[For each article (sorted by score desc):]
  Score badge | Title (linked)  [Source tag]
  Summary sentence.
  Why it matters: <explanation>
  ─────────────────────────────────────────

[Footer: "Powered by Claude Haiku · Unsubscribe"]
```

### Implementation
```python
import boto3
import os
from datetime import datetime, timezone

def send(digest: list[dict]) -> None:
    from_email = os.environ["FROM_EMAIL"]
    to_email = os.environ["TO_EMAIL"]
    today = datetime.now(timezone.utc).strftime("%B %-d, %Y")

    ses = boto3.client("ses", region_name=os.getenv("AWS_REGION", "us-east-1"))
    ses.send_email(
        Source=from_email,
        Destination={"ToAddresses": [to_email]},
        Message={
            "Subject": {"Data": f"AI Research Digest — {today}", "Charset": "UTF-8"},
            "Body": {"Html": {"Data": _render_html(digest, today), "Charset": "UTF-8"}},
        },
    )

def _render_html(digest: list[dict], today: str) -> str:
    rows = "\n".join(_render_article(i + 1, a) for i, a in enumerate(digest))
    return f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 700px; margin: auto; color: #333;">
      <h1 style="border-bottom: 2px solid #0066cc; padding-bottom: 8px;">
        AI Research Digest
      </h1>
      <p style="color: #666;">{today} &middot; {len(digest)} articles</p>
      {rows}
      <hr/>
      <p style="font-size: 12px; color: #999;">
        Powered by Claude Haiku &middot;
        <a href="https://github.com/YOUR_USERNAME/ai-research-analyst">View on GitHub</a>
      </p>
    </body>
    </html>
    """

def _render_article(rank: int, article: dict) -> str:
    score = article.get("score", 0)
    score_color = "#22c55e" if score >= 8 else "#eab308" if score >= 5 else "#ef4444"
    return f"""
    <div style="margin-bottom: 24px; padding: 16px; border-left: 4px solid {score_color};">
      <div style="margin-bottom: 4px;">
        <span style="background:{score_color}; color:white; padding:2px 8px;
                     border-radius:4px; font-size:13px; font-weight:bold;">
          {score}/10
        </span>
        &nbsp;
        <a href="{article['url']}" style="font-size:16px; font-weight:bold; color:#0066cc;">
          {article['title']}
        </a>
        &nbsp;
        <span style="font-size:12px; color:#888; background:#f0f0f0;
                     padding:2px 6px; border-radius:3px;">
          {article['source']}
        </span>
      </div>
      <p style="margin: 4px 0;">{article.get('summary', '')}</p>
      <p style="margin: 4px 0; color: #555; font-size: 14px;">
        <em>Why it matters:</em> {article.get('why_matters', '')}
      </p>
    </div>
    """
```

---

## Updated `infra/template.yaml`

Add SES identity and configuration set to the Phase 1B template. Full file shown below.

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31

Description: AI Research Analyst - Daily digest pipeline

Parameters:
  FromEmail:
    Type: String
    Description: Email address to send digest from (will be SES-verified)
  ToEmail:
    Type: String
    Description: Email address to receive digest

Globals:
  Function:
    Runtime: python3.12
    Timeout: 300
    MemorySize: 512

Resources:

  # ─── S3: Run manifests ─────────────────────────────────────────────────────
  RunsBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub '${AWS::StackName}-runs-${AWS::AccountId}'
      LifecycleConfiguration:
        Rules:
          - Id: DeleteOldRuns
            Status: Enabled
            ExpirationInDays: 90

  # ─── SES: Email identity (sender) ──────────────────────────────────────────
  SESFromIdentity:
    Type: AWS::SES::EmailIdentity
    Properties:
      EmailIdentity: !Ref FromEmail
      DkimAttributes:
        SigningEnabled: true
      FeedbackAttributes:
        EmailForwardingEnabled: false

  # ─── SES: Configuration set (tracking + bounce handling) ───────────────────
  SESConfigurationSet:
    Type: AWS::SES::ConfigurationSet
    Properties:
      Name: !Sub '${AWS::StackName}-config'
      ReputationOptions:
        ReputationMetricsEnabled: true
      SendingOptions:
        SendingEnabled: true

  # ─── Lambda ────────────────────────────────────────────────────────────────
  DailyDigestFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: ./
      Handler: handlers/daily_digest.handler
      Environment:
        Variables:
          ENV: lambda
          FROM_EMAIL: !Ref FromEmail
          TO_EMAIL: !Ref ToEmail
          RUNS_BUCKET: !Ref RunsBucket
          # ANTHROPIC_API_KEY fetched at runtime from SSM (see handler)
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
              Resource: !Sub >-
                arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/ai-research-analyst/*
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
  SESIdentity:
    Value: !Ref SESFromIdentity
    Description: SES email identity — check AWS Console to confirm verification status
```

---

## SES Setup Sequence (Step-by-Step)

### Step 1: Deploy the stack
```bash
make deploy
```
This creates `AWS::SES::EmailIdentity` for `FROM_EMAIL`.

### Step 2: Verify `FROM_EMAIL`
- AWS SES automatically sends a verification email to `FROM_EMAIL`
- Check the inbox and **click the verification link**
- Confirm verified: AWS Console → SES → Verified identities → Status = "Verified"

### Step 3: Verify `TO_EMAIL` (sandbox only)
If the AWS account is in SES sandbox, all recipients must also be verified.
- AWS Console → SES → Verified identities → Create identity → Email address → enter `TO_EMAIL`
- Click verification link in `TO_EMAIL`'s inbox

### Step 4: (Optional) Exit sandbox for arbitrary recipients
- AWS Console → SES → Account dashboard → Request production access
- Fill out the form: intended use case (daily personal digest), bounce handling (CloudWatch), expected volume (~30/month)
- AWS reviews in 24–48 hours
- **Not required** if `FROM_EMAIL` and `TO_EMAIL` are both verified

### Step 5: Test email send
```bash
python scripts/test_email.py
```

### Step 6: Trigger Lambda manually
```bash
aws lambda invoke \
  --function-name $(aws cloudformation describe-stack-resource \
    --stack-name ai-research-analyst \
    --logical-resource-id DailyDigestFunction \
    --query 'StackResourceDetail.PhysicalResourceId' \
    --output text) \
  --payload '{}' \
  response.json && cat response.json
```

Check inbox — email should arrive within 60 seconds.

---

### `scripts/test_email.py`
Sends a single test email with a mock digest to verify SES is configured correctly.

```python
from dotenv import load_dotenv
load_dotenv()

from delivery.email_digest import send

MOCK_DIGEST = [
    {
        "title": "Test Article: SES Email Verification",
        "url": "https://example.com",
        "source": "arxiv",
        "score": 9,
        "summary": "This is a test to verify SES email delivery is working correctly.",
        "why_matters": "Confirms the email pipeline is operational end-to-end.",
        "prompt_version": "v1",
    }
]

send(MOCK_DIGEST)
print("Test email sent. Check your inbox.")
```

---

## Cost Estimate (All AWS Services, Monthly)

| Service | Usage | Cost |
|---------|-------|------|
| **Lambda** | 1 invocation/day × 30 = 30/month, 300s × 512MB | $0 (free tier: 1M invocations, 400K GB-seconds) |
| **CloudWatch Logs** | ~300KB ingested/month | $0 (free tier: 5GB/month) |
| **CloudWatch Insights** | ~10 queries/month on 300KB | $0 (free tier: 5GB scanned/month) |
| **S3 (run manifests)** | ~300KB/month, 30 objects | $0 (free tier: 5GB storage, 2,000 PUT/month) |
| **EventBridge** | 30 scheduled events/month | $0 (free: 14M events/month) |
| **SSM Parameter Store** | 1 SecureString parameter, ~30 GetParameter calls/month | $0 (standard tier free; aws/ssm KMS key free) |
| **SES (email sending)** | 30 emails/month | $0 (free tier: 3,000 messages/month for 12 months; then $0.003/month) |
| **Claude Haiku (claude-haiku-4-5)** | ~2,700 input + 1,800 output tokens/day | ~$0.002/day → **~$0.06/month** |
| **TOTAL** | | **~$0.06/month** |

After 12-month SES free tier expires: add $0.003/month → **~$0.07/month** total.

---

## Verification

| Gate | How to verify |
|------|--------------|
| SES identity verified | AWS Console → SES → Verified identities → Status = Verified |
| SSM parameter exists | `aws ssm get-parameter --name /ai-research-analyst/anthropic-api-key --with-decryption` |
| Test email received | `python scripts/test_email.py` → check inbox |
| Lambda sends email | `make invoke` or manual AWS Console test → check inbox |
| Scheduled run | Wait for 7AM UTC → CloudWatch Logs shows invocation, email arrives |

---

## Files Created/Modified in Phase 1C

| File | Action |
|------|--------|
| `delivery/email_digest.py` | Implemented |
| `scripts/test_email.py` | Implemented |
| `infra/template.yaml` | Updated (add SES resources) |

---

## SES Gotchas

1. **`AWS::SES::EmailIdentity` does not wait for verification.** The CloudFormation stack will complete even if you haven't clicked the verify link. You must verify manually before the Lambda can send.
2. **Sandbox recipients must be verified.** If you get `MessageRejected: Email address is not verified`, the `TO_EMAIL` needs verification too.
3. **DKIM signing takes up to 72 hours** after domain verification to propagate. Email sending works before that; DKIM just improves deliverability.
4. **`ses:SendEmail` resource `*`** is necessary for email sending in sandbox mode since the verified identity ARN format varies. Scope to the identity ARN in production if required by your org's security policy.
