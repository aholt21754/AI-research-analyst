"""Integration tests for handlers.daily_digest.

All agents and AWS services are mocked — no real network, no real AWS calls.
Tests verify the handler wiring: correct call order, return contract, and
that partial failures (empty scraper/summarizer results) don't crash the pipeline.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

_SAMPLE_ARTICLES = [
    {"title": "Article 1", "url": "https://example.com/1", "source": "arxiv", "abstract": "...", "published_date": "2026-04-01T00:00:00Z"},
]

_SAMPLE_DIGEST = [
    {"title": "Article 1", "url": "https://example.com/1", "source": "arxiv", "score": 9, "summary": "Summary.", "why_matters": "Matters.", "prompt_version": "v1"},
]

_SCRAPER_STATS = {"sources": {"arxiv": {"status": "success", "count": 1, "latency_ms": 100}}, "raw_total": 1, "after_dedup": 1}
_SUMMARIZER_STATS = {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.0002, "latency_ms": 500}


def _patch_all(scraper_result=None, summarizer_result=None):
    """Return a context manager stack that mocks all external dependencies."""
    if scraper_result is None:
        scraper_result = (_SAMPLE_ARTICLES, _SCRAPER_STATS)
    if summarizer_result is None:
        summarizer_result = (_SAMPLE_DIGEST, _SUMMARIZER_STATS)

    patches = [
        patch("handlers.daily_digest._get_api_key", return_value="test-key"),
        patch("handlers.daily_digest.scraper.run", return_value=scraper_result),
        patch("handlers.daily_digest.summarizer.run", return_value=summarizer_result),
        patch("handlers.daily_digest.email_digest.send"),
        patch("handlers.daily_digest.run_manifest.write"),
        patch("handlers.daily_digest._emit_metric"),
    ]
    return patches


# ══════════════════════════════════════════════════════════════════════════════
# Happy path
# ══════════════════════════════════════════════════════════════════════════════

class TestHandlerHappyPath:
    def test_returns_200_with_digest_count(self):
        patches = _patch_all()
        active = [p.start() for p in patches]
        try:
            from handlers.daily_digest import handler
            result = handler({}, None)
        finally:
            for p in patches:
                p.stop()

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["digest_count"] == 1

    def test_all_pipeline_stages_called_in_order(self):
        call_order = []

        with patch("handlers.daily_digest._get_api_key", return_value="key"), \
             patch("handlers.daily_digest.scraper.run", side_effect=lambda: (call_order.append("scraper"), (_SAMPLE_ARTICLES, _SCRAPER_STATS))[1]), \
             patch("handlers.daily_digest.summarizer.run", side_effect=lambda a: (call_order.append("summarizer"), (_SAMPLE_DIGEST, _SUMMARIZER_STATS))[1]), \
             patch("handlers.daily_digest.email_digest.send", side_effect=lambda d: call_order.append("email")), \
             patch("handlers.daily_digest.run_manifest.write", side_effect=lambda *a: call_order.append("manifest")), \
             patch("handlers.daily_digest._emit_metric"):

            from handlers.daily_digest import handler
            handler({}, None)

        assert call_order == ["scraper", "summarizer", "email", "manifest"]


# ══════════════════════════════════════════════════════════════════════════════
# Partial failure resilience
# ══════════════════════════════════════════════════════════════════════════════

class TestHandlerPartialFailures:
    def test_empty_scraper_result_still_calls_summarizer(self):
        empty_scraper = ([], {"sources": {}, "raw_total": 0, "after_dedup": 0})
        patches = _patch_all(scraper_result=empty_scraper)
        mock_summarizer = None
        for p in patches:
            if hasattr(p, "attribute") and p.attribute == "run":
                pass

        with patch("handlers.daily_digest._get_api_key", return_value="key"), \
             patch("handlers.daily_digest.scraper.run", return_value=empty_scraper), \
             patch("handlers.daily_digest.summarizer.run", return_value=([], _SUMMARIZER_STATS)) as mock_sum, \
             patch("handlers.daily_digest.email_digest.send"), \
             patch("handlers.daily_digest.run_manifest.write"), \
             patch("handlers.daily_digest._emit_metric"):

            from handlers.daily_digest import handler
            handler({}, None)
            mock_sum.assert_called_once_with([])

    def test_empty_digest_still_sends_email(self):
        empty_digest = ([], _SUMMARIZER_STATS)

        with patch("handlers.daily_digest._get_api_key", return_value="key"), \
             patch("handlers.daily_digest.scraper.run", return_value=(_SAMPLE_ARTICLES, _SCRAPER_STATS)), \
             patch("handlers.daily_digest.summarizer.run", return_value=empty_digest), \
             patch("handlers.daily_digest.email_digest.send") as mock_send, \
             patch("handlers.daily_digest.run_manifest.write"), \
             patch("handlers.daily_digest._emit_metric"):

            from handlers.daily_digest import handler
            handler({}, None)
            mock_send.assert_called_once_with([])

    def test_empty_digest_emits_metric(self):
        empty_digest = ([], _SUMMARIZER_STATS)

        with patch("handlers.daily_digest._get_api_key", return_value="key"), \
             patch("handlers.daily_digest.scraper.run", return_value=(_SAMPLE_ARTICLES, _SCRAPER_STATS)), \
             patch("handlers.daily_digest.summarizer.run", return_value=empty_digest), \
             patch("handlers.daily_digest.email_digest.send"), \
             patch("handlers.daily_digest.run_manifest.write"), \
             patch("handlers.daily_digest._emit_metric") as mock_metric:

            from handlers.daily_digest import handler
            handler({}, None)
            mock_metric.assert_called_once_with("EmptyDigest", 1)

    def test_non_empty_digest_does_not_emit_metric(self):
        with patch("handlers.daily_digest._get_api_key", return_value="key"), \
             patch("handlers.daily_digest.scraper.run", return_value=(_SAMPLE_ARTICLES, _SCRAPER_STATS)), \
             patch("handlers.daily_digest.summarizer.run", return_value=(_SAMPLE_DIGEST, _SUMMARIZER_STATS)), \
             patch("handlers.daily_digest.email_digest.send"), \
             patch("handlers.daily_digest.run_manifest.write"), \
             patch("handlers.daily_digest._emit_metric") as mock_metric:

            from handlers.daily_digest import handler
            handler({}, None)
            mock_metric.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Error handling (A2)
# ══════════════════════════════════════════════════════════════════════════════

class TestHandlerErrorHandling:
    def test_unhandled_exception_is_re_raised(self):
        with patch("handlers.daily_digest._get_api_key", return_value="key"), \
             patch("handlers.daily_digest.scraper.run", side_effect=RuntimeError("boom")), \
             patch("handlers.daily_digest._emit_metric"):

            from handlers.daily_digest import handler
            with pytest.raises(RuntimeError, match="boom"):
                handler({}, None)

    def test_manifest_receives_stats(self):
        with patch("handlers.daily_digest._get_api_key", return_value="key"), \
             patch("handlers.daily_digest.scraper.run", return_value=(_SAMPLE_ARTICLES, _SCRAPER_STATS)), \
             patch("handlers.daily_digest.summarizer.run", return_value=(_SAMPLE_DIGEST, _SUMMARIZER_STATS)), \
             patch("handlers.daily_digest.email_digest.send"), \
             patch("handlers.daily_digest.run_manifest.write") as mock_write, \
             patch("handlers.daily_digest._emit_metric"):

            from handlers.daily_digest import handler
            handler({}, None)

            mock_write.assert_called_once()
            args = mock_write.call_args[0]
            # write(articles, digest, scraper_stats, summarizer_stats)
            assert args[2] == _SCRAPER_STATS
            assert args[3] == _SUMMARIZER_STATS
