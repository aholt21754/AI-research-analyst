import json
import os
import uuid
from datetime import datetime, timezone

from agents.logging_config import get_logger

logger = get_logger(__name__)


def write(articles: list[dict], digest: list[dict]) -> None:
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    manifest = _build(run_id, articles, digest)

    env = os.getenv("ENV", "local")
    if env == "local":
        _write_local(run_id, manifest)
    else:
        _write_s3(run_id, manifest)


def _build(run_id: str, articles: list[dict], digest: list[dict]) -> dict:
    return {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": os.getenv("ENV", "local"),
        "prompt_version": digest[0].get("prompt_version") if digest else None,
        "scraper": {
            "raw_total": len(articles),
        },
        "summarizer": {
            "model": "claude-haiku-4-5",
            "digest_count": len(digest),
        },
        "digest": [
            {
                "title": a.get("title"),
                "url": a.get("url"),
                "score": a.get("score"),
                "source": a.get("source"),
                "prompt_version": a.get("prompt_version"),
            }
            for a in digest
        ],
    }


def _write_local(run_id: str, manifest: dict) -> None:
    os.makedirs("logs/runs", exist_ok=True)
    path = f"logs/runs/{run_id}.json"
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info("run_manifest.written_local", extra={"path": path})


def _write_s3(run_id: str, manifest: dict) -> None:
    import boto3

    s3 = boto3.client("s3")
    bucket = os.environ["RUNS_BUCKET"]
    key = f"runs/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}_{run_id}.json"
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(manifest, indent=2))
    logger.info("run_manifest.written_s3", extra={"bucket": bucket, "key": key})
