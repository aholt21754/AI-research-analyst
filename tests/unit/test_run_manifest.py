"""Unit tests for delivery.run_manifest."""

import json
import os
from unittest.mock import MagicMock, mock_open, patch


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _sample_articles() -> list[dict]:
    return [
        {"title": "Article 1", "url": "https://example.com/1", "source": "arxiv", "abstract": "...", "published_date": "2026-04-01T00:00:00Z"},
        {"title": "Article 2", "url": "https://example.com/2", "source": "hackernews", "abstract": "...", "published_date": "2026-04-01T00:00:00Z"},
    ]


def _sample_digest() -> list[dict]:
    return [
        {"title": "Article 1", "url": "https://example.com/1", "source": "arxiv", "score": 9, "summary": "Summary.", "why_matters": "Matters.", "prompt_version": "v1"},
    ]


def _sample_scraper_stats() -> dict:
    return {
        "sources": {
            "arxiv": {"status": "success", "count": 8, "latency_ms": 320},
            "hackernews": {"status": "success", "count": 5, "latency_ms": 210},
        },
        "raw_total": 13,
        "after_dedup": 12,
    }


def _sample_summarizer_stats() -> dict:
    return {
        "input_tokens": 1200,
        "output_tokens": 600,
        "cost_usd": 0.003360,
        "latency_ms": 1800,
    }


# ══════════════════════════════════════════════════════════════════════════════
# _build
# ══════════════════════════════════════════════════════════════════════════════

class TestBuild:
    def test_includes_all_required_top_level_keys(self):
        from delivery.run_manifest import _build
        manifest = _build("run_123", _sample_articles(), _sample_digest(), _sample_scraper_stats(), _sample_summarizer_stats())

        required = {"run_id", "timestamp", "environment", "prompt_version", "scraper", "summarizer", "digest"}
        assert required.issubset(manifest.keys())

    def test_run_id_is_preserved(self):
        from delivery.run_manifest import _build
        manifest = _build("run_abc", _sample_articles(), _sample_digest(), _sample_scraper_stats(), _sample_summarizer_stats())
        assert manifest["run_id"] == "run_abc"

    def test_scraper_includes_after_dedup_and_sources(self):
        from delivery.run_manifest import _build
        manifest = _build("run_123", _sample_articles(), _sample_digest(), _sample_scraper_stats(), _sample_summarizer_stats())

        assert manifest["scraper"]["raw_total"] == 13
        assert manifest["scraper"]["after_dedup"] == 12
        assert "arxiv" in manifest["scraper"]["sources"]
        assert manifest["scraper"]["sources"]["arxiv"]["latency_ms"] == 320

    def test_summarizer_includes_tokens_and_cost(self):
        from delivery.run_manifest import _build
        manifest = _build("run_123", _sample_articles(), _sample_digest(), _sample_scraper_stats(), _sample_summarizer_stats())

        assert manifest["summarizer"]["input_tokens"] == 1200
        assert manifest["summarizer"]["output_tokens"] == 600
        assert manifest["summarizer"]["cost_usd"] == 0.003360
        assert manifest["summarizer"]["latency_ms"] == 1800

    def test_prompt_version_from_first_digest_item(self):
        from delivery.run_manifest import _build
        manifest = _build("run_123", _sample_articles(), _sample_digest(), _sample_scraper_stats(), _sample_summarizer_stats())
        assert manifest["prompt_version"] == "v1"

    def test_empty_digest_prompt_version_is_none(self):
        from delivery.run_manifest import _build
        manifest = _build("run_123", _sample_articles(), [], _sample_scraper_stats(), _sample_summarizer_stats())
        assert manifest["prompt_version"] is None
        assert manifest["digest"] == []

    def test_empty_digest_does_not_crash(self):
        from delivery.run_manifest import _build
        # Should not raise
        _build("run_123", [], [], _sample_scraper_stats(), _sample_summarizer_stats())

    def test_digest_items_contain_required_fields(self):
        from delivery.run_manifest import _build
        manifest = _build("run_123", _sample_articles(), _sample_digest(), _sample_scraper_stats(), _sample_summarizer_stats())
        item = manifest["digest"][0]
        assert item["title"] == "Article 1"
        assert item["url"] == "https://example.com/1"
        assert item["score"] == 9


# ══════════════════════════════════════════════════════════════════════════════
# write — local
# ══════════════════════════════════════════════════════════════════════════════

class TestWriteLocal:
    @patch("delivery.run_manifest.os.getenv", return_value="local")
    @patch("delivery.run_manifest.os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    @patch("delivery.run_manifest.uuid.uuid4")
    def test_write_local_creates_file_in_logs_runs(self, mock_uuid, mock_file, mock_makedirs, mock_getenv):
        mock_uuid.return_value.hex = "aabbcc112233"
        from delivery.run_manifest import write

        write(_sample_articles(), _sample_digest(), _sample_scraper_stats(), _sample_summarizer_stats())

        mock_makedirs.assert_called_once_with("logs/runs", exist_ok=True)
        mock_file.assert_called_once()
        path_arg = mock_file.call_args[0][0]
        assert path_arg.startswith("logs/runs/run_")
        assert path_arg.endswith(".json")


# ══════════════════════════════════════════════════════════════════════════════
# write — S3
# ══════════════════════════════════════════════════════════════════════════════

class TestWriteS3:
    @patch.dict(os.environ, {"ENV": "lambda", "RUNS_BUCKET": "test-bucket"})
    @patch("boto3.client")
    def test_write_s3_calls_put_object(self, mock_boto_client):
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        from delivery import run_manifest
        import importlib
        importlib.reload(run_manifest)

        run_manifest.write(_sample_articles(), _sample_digest(), _sample_scraper_stats(), _sample_summarizer_stats())

        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"].startswith("runs/")
        assert call_kwargs["Key"].endswith(".json")

        # Verify body is valid JSON
        body = json.loads(call_kwargs["Body"])
        assert "run_id" in body
