import os
from datetime import datetime, timezone

import boto3

from agents.logging_config import get_logger

logger = get_logger(__name__)


def send(digest: list[dict]) -> None:
    from_email = os.environ["FROM_EMAIL"]
    to_email = os.environ["TO_EMAIL"]
    today = datetime.now(timezone.utc).strftime("%B %-d, %Y")

    ses = boto3.client("ses", region_name=os.getenv("AWS_REGION", "us-east-1"))
    ses.send_email(
        Source=from_email,
        Destination={"ToAddresses": [to_email]},
        Message={
            "Subject": {"Data": f"AI Research Digest \u2014 {today}", "Charset": "UTF-8"},
            "Body": {"Html": {"Data": _render_html(digest, today), "Charset": "UTF-8"}},
        },
    )
    logger.info("email_digest.sent", extra={"to": to_email, "article_count": len(digest)})


def _render_html(digest: list[dict], today: str) -> str:
    rows = "\n".join(_render_article(i + 1, a) for i, a in enumerate(digest))
    return f"""<!DOCTYPE html>
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
    <a href="https://github.com/aholt21754/ai-research-analyst">View on GitHub</a>
  </p>
</body>
</html>"""


def _render_article(rank: int, article: dict) -> str:
    score = article.get("score", 0)
    score_color = "#22c55e" if score >= 8 else "#eab308" if score >= 5 else "#ef4444"
    title = article.get("title", "")
    url = article.get("url", "#")
    source = article.get("source", "")
    summary = article.get("summary", "")
    why_matters = article.get("why_matters", "")
    return f"""<div style="margin-bottom: 24px; padding: 16px; border-left: 4px solid {score_color};">
  <div style="margin-bottom: 4px;">
    <span style="background:{score_color}; color:white; padding:2px 8px;
                 border-radius:4px; font-size:13px; font-weight:bold;">
      {score}/10
    </span>
    &nbsp;
    <a href="{url}" style="font-size:16px; font-weight:bold; color:#0066cc;">
      {title}
    </a>
    &nbsp;
    <span style="font-size:12px; color:#888; background:#f0f0f0;
                 padding:2px 6px; border-radius:3px;">
      {source}
    </span>
  </div>
  <p style="margin: 4px 0;">{summary}</p>
  <p style="margin: 4px 0; color: #555; font-size: 14px;">
    <em>Why it matters:</em> {why_matters}
  </p>
</div>"""
