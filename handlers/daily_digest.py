import json
import os
import time

import boto3

from agents.logging_config import get_logger
from agents.scraper import agent as scraper
from agents.summarizer import agent as summarizer
from delivery import email_digest, run_manifest

logger = get_logger(__name__)

_API_KEY_CACHE = None  # module-level: survives Lambda warm starts
_IS_COLD_START = True  # flips to False after first invocation


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


def _emit_metric(name: str, value: float) -> None:
    """Emit a custom CloudWatch metric. Fail silently to avoid crashing the pipeline."""
    try:
        cw = boto3.client("cloudwatch")
        cw.put_metric_data(
            Namespace="AIResearchAnalyst",
            MetricData=[{"MetricName": name, "Value": value, "Unit": "Count"}],
        )
    except Exception as exc:
        logger.warning("handler.metric_emit_failed", extra={"metric": name, "error_msg": str(exc)})


def handler(event, context):
    global _IS_COLD_START

    pipeline_t0 = time.monotonic()
    os.environ["ANTHROPIC_API_KEY"] = _get_api_key()

    logger.info("handler.started", extra={"cold_start": _IS_COLD_START})
    _IS_COLD_START = False

    try:
        articles, scraper_stats = scraper.run()
        logger.info("handler.scraper_done", extra={"article_count": len(articles)})

        digest, summarizer_stats = summarizer.run(articles)
        logger.info("handler.summarizer_done", extra={"digest_count": len(digest)})

        if not digest:
            _emit_metric("EmptyDigest", 1)

        email_digest.send(digest)
        logger.info("handler.email_sent")

        run_manifest.write(articles, digest, scraper_stats, summarizer_stats)
        logger.info("handler.manifest_written")

        logger.info("pipeline.completed", extra={
            "total_latency_ms": int((time.monotonic() - pipeline_t0) * 1000),
            "scraper_article_count": len(articles),
            "digest_count": len(digest),
            "input_tokens": summarizer_stats.get("input_tokens", 0),
            "output_tokens": summarizer_stats.get("output_tokens", 0),
            "cost_usd": summarizer_stats.get("cost_usd", 0),
            "sources_ok": sum(1 for s in scraper_stats["sources"].values() if s["status"] == "success"),
            "sources_failed": sum(1 for s in scraper_stats["sources"].values() if s["status"] != "success"),
        })

        return {"statusCode": 200, "body": json.dumps({"digest_count": len(digest)})}

    except Exception as exc:
        logger.error("pipeline.failed", extra={
            "error_type": type(exc).__name__,
            "error_msg": str(exc),
            "total_latency_ms": int((time.monotonic() - pipeline_t0) * 1000),
        })
        raise
