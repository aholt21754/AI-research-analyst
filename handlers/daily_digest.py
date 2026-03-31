import json
import os

import boto3

from agents.logging_config import get_logger
from agents.scraper import agent as scraper
from agents.summarizer import agent as summarizer
from delivery import email_digest, run_manifest

logger = get_logger(__name__)

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
    os.environ["ANTHROPIC_API_KEY"] = _get_api_key()

    logger.info("handler.started")

    articles = scraper.run()
    logger.info("handler.scraper_done", extra={"article_count": len(articles)})

    digest = summarizer.run(articles)
    logger.info("handler.summarizer_done", extra={"digest_count": len(digest)})

    email_digest.send(digest)
    logger.info("handler.email_sent")

    run_manifest.write(articles, digest)
    logger.info("handler.manifest_written")

    return {"statusCode": 200, "body": json.dumps({"digest_count": len(digest)})}
