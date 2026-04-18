"""Unit tests for the summarizer agent.

All Anthropic API calls are mocked — no real network traffic or API costs.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

# Summarizer reads ANTHROPIC_API_KEY from the environment; set a dummy value for all tests.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_articles(n: int = 3) -> list[dict]:
    return [
        {
            "title": f"Article {i + 1}",
            "url": f"https://example.com/{i + 1}",
            "abstract": f"Abstract for article {i + 1}",
            "source": "arxiv",
            "published_date": "2026-04-01T00:00:00Z",
        }
        for i in range(n)
    ]


def _make_response_text(articles: list[dict], score: int = 8) -> str:
    """Build a valid JSON response string as Claude would return."""
    items = [
        {
            "index": i + 1,
            "score": score,
            "summary": f"Summary of article {i + 1}.",
            "why_matters": f"Why article {i + 1} matters.",
        }
        for i in range(len(articles))
    ]
    return json.dumps(items)


def _mock_anthropic(response_text: str, input_tokens: int = 100, output_tokens: int = 50):
    """Return a configured mock for anthropic.Anthropic."""
    mock_usage = MagicMock()
    mock_usage.input_tokens = input_tokens
    mock_usage.output_tokens = output_tokens

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    mock_message.usage = mock_usage

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    return mock_client


# ══════════════════════════════════════════════════════════════════════════════
# Happy path
# ══════════════════════════════════════════════════════════════════════════════

class TestSummarizerHappyPath:
    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_returns_sorted_results_with_required_fields(self, mock_anthropic_cls):
        articles = _make_articles(3)
        response_text = json.dumps([
            {"index": 1, "score": 6, "summary": "Summary 1.", "why_matters": "Matters 1."},
            {"index": 2, "score": 9, "summary": "Summary 2.", "why_matters": "Matters 2."},
            {"index": 3, "score": 7, "summary": "Summary 3.", "why_matters": "Matters 3."},
        ])
        mock_anthropic_cls.return_value = _mock_anthropic(response_text)

        from agents.summarizer.agent import run
        digest, stats = run(articles)

        required = {"title", "url", "source", "score", "summary", "why_matters", "prompt_version"}
        assert len(digest) == 3
        for item in digest:
            assert required.issubset(item.keys())
        # sorted by score descending
        assert digest[0]["score"] == 9
        assert digest[1]["score"] == 7
        assert digest[2]["score"] == 6

    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_top_n_limits_results(self, mock_anthropic_cls):
        articles = _make_articles(5)
        mock_anthropic_cls.return_value = _mock_anthropic(_make_response_text(articles))

        from agents.summarizer.agent import run
        digest, stats = run(articles, top_n=2)

        assert len(digest) <= 2

    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_stats_contains_expected_keys(self, mock_anthropic_cls):
        articles = _make_articles(2)
        mock_anthropic_cls.return_value = _mock_anthropic(_make_response_text(articles), input_tokens=200, output_tokens=80)

        from agents.summarizer.agent import run
        _, stats = run(articles)

        assert "input_tokens" in stats
        assert "output_tokens" in stats
        assert "cost_usd" in stats
        assert "latency_ms" in stats
        assert stats["input_tokens"] == 200
        assert stats["output_tokens"] == 80
        assert stats["cost_usd"] > 0

    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_prompt_version_attached_to_each_result(self, mock_anthropic_cls):
        articles = _make_articles(2)
        mock_anthropic_cls.return_value = _mock_anthropic(_make_response_text(articles))

        from agents.summarizer.agent import run
        digest, _ = run(articles)

        assert all(item.get("prompt_version") for item in digest)


# ══════════════════════════════════════════════════════════════════════════════
# Edge cases — empty / no API call
# ══════════════════════════════════════════════════════════════════════════════

class TestSummarizerEdgeCases:
    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_empty_articles_returns_empty_without_api_call(self, mock_anthropic_cls):
        from agents.summarizer.agent import run
        digest, stats = run([])

        mock_anthropic_cls.return_value.messages.create.assert_not_called()
        assert digest == []
        assert stats["input_tokens"] == 0

    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_index_out_of_bounds_skipped(self, mock_anthropic_cls):
        articles = _make_articles(2)
        response_text = json.dumps([
            {"index": 999, "score": 8, "summary": "Out of range.", "why_matters": "Should be skipped."},
            {"index": 1, "score": 7, "summary": "Valid item.", "why_matters": "Valid why matters."},
        ])
        mock_anthropic_cls.return_value = _mock_anthropic(response_text)

        from agents.summarizer.agent import run
        digest, _ = run(articles)

        assert len(digest) == 1
        assert digest[0]["summary"] == "Valid item."


# ══════════════════════════════════════════════════════════════════════════════
# JSON parsing
# ══════════════════════════════════════════════════════════════════════════════

class TestSummarizerJsonParsing:
    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_markdown_fence_stripped_and_parsed(self, mock_anthropic_cls):
        articles = _make_articles(1)
        inner = json.dumps([{"index": 1, "score": 8, "summary": "A summary.", "why_matters": "Why it matters."}])
        fenced = f"```json\n{inner}\n```"
        mock_anthropic_cls.return_value = _mock_anthropic(fenced)

        from agents.summarizer.agent import run
        digest, _ = run(articles)

        assert len(digest) == 1

    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_invalid_json_returns_empty_list(self, mock_anthropic_cls):
        articles = _make_articles(2)
        mock_anthropic_cls.return_value = _mock_anthropic("NOT JSON AT ALL")

        from agents.summarizer.agent import run
        digest, stats = run(articles)

        assert digest == []
        assert stats["input_tokens"] > 0  # API was still called

    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_non_list_json_returns_empty(self, mock_anthropic_cls):
        articles = _make_articles(2)
        mock_anthropic_cls.return_value = _mock_anthropic('{"results": []}')

        from agents.summarizer.agent import run
        digest, _ = run(articles)

        assert digest == []


# ══════════════════════════════════════════════════════════════════════════════
# Output validation (D1)
# ══════════════════════════════════════════════════════════════════════════════

class TestSummarizerOutputValidation:
    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_score_clamped_to_1_10_range(self, mock_anthropic_cls):
        articles = _make_articles(1)
        response_text = json.dumps([{"index": 1, "score": 15, "summary": "A summary.", "why_matters": "Why it matters."}])
        mock_anthropic_cls.return_value = _mock_anthropic(response_text)

        from agents.summarizer.agent import run
        digest, _ = run(articles)

        assert len(digest) == 1
        assert digest[0]["score"] == 10  # clamped from 15

    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_score_below_1_clamped(self, mock_anthropic_cls):
        articles = _make_articles(1)
        response_text = json.dumps([{"index": 1, "score": -3, "summary": "A summary.", "why_matters": "Why it matters."}])
        mock_anthropic_cls.return_value = _mock_anthropic(response_text)

        from agents.summarizer.agent import run
        digest, _ = run(articles)

        assert len(digest) == 1
        assert digest[0]["score"] == 1  # clamped from -3

    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_missing_summary_skips_item(self, mock_anthropic_cls):
        articles = _make_articles(2)
        response_text = json.dumps([
            {"index": 1, "score": 8, "summary": "", "why_matters": "Why it matters."},
            {"index": 2, "score": 7, "summary": "Valid summary.", "why_matters": "Valid why matters."},
        ])
        mock_anthropic_cls.return_value = _mock_anthropic(response_text)

        from agents.summarizer.agent import run
        digest, _ = run(articles)

        assert len(digest) == 1
        assert digest[0]["summary"] == "Valid summary."

    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_missing_why_matters_skips_item(self, mock_anthropic_cls):
        articles = _make_articles(2)
        response_text = json.dumps([
            {"index": 1, "score": 8, "summary": "Valid summary.", "why_matters": ""},
            {"index": 2, "score": 7, "summary": "Another summary.", "why_matters": "Valid."},
        ])
        mock_anthropic_cls.return_value = _mock_anthropic(response_text)

        from agents.summarizer.agent import run
        digest, _ = run(articles)

        assert len(digest) == 1
        assert digest[0]["why_matters"] == "Valid."


# ══════════════════════════════════════════════════════════════════════════════
# Retry logic (A1)
# ══════════════════════════════════════════════════════════════════════════════

class TestSummarizerRetry:
    @patch("time.sleep")
    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_rate_limit_retries_then_returns_empty(self, mock_anthropic_cls, mock_sleep):
        import anthropic as anthropic_lib

        articles = _make_articles(2)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic_lib.RateLimitError(
            message="rate limit", response=MagicMock(status_code=429), body={}
        )
        mock_anthropic_cls.return_value = mock_client

        from agents.summarizer.agent import run
        digest, stats = run(articles)

        assert digest == []
        assert stats["input_tokens"] == 0
        # 3 delays after first attempt + 1 initial = 4 total calls attempted
        assert mock_client.messages.create.call_count == 4

    @patch("time.sleep")
    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_connection_error_retries_then_returns_empty(self, mock_anthropic_cls, mock_sleep):
        import anthropic as anthropic_lib

        articles = _make_articles(2)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic_lib.APIConnectionError(request=MagicMock())
        mock_anthropic_cls.return_value = mock_client

        from agents.summarizer.agent import run
        digest, stats = run(articles)

        assert digest == []
        assert mock_client.messages.create.call_count == 4

    @patch("time.sleep")
    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_non_retryable_api_error_returns_empty_immediately(self, mock_anthropic_cls, mock_sleep):
        import anthropic as anthropic_lib

        articles = _make_articles(2)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic_lib.BadRequestError(
            message="bad request", response=MagicMock(status_code=400), body={}
        )
        mock_anthropic_cls.return_value = mock_client

        from agents.summarizer.agent import run
        digest, _ = run(articles)

        assert digest == []
        assert mock_client.messages.create.call_count == 1  # no retry on non-retryable

    @patch("time.sleep")
    @patch("agents.summarizer.agent.anthropic.Anthropic")
    def test_succeeds_on_second_attempt(self, mock_anthropic_cls, mock_sleep):
        import anthropic as anthropic_lib

        articles = _make_articles(1)
        response_text = json.dumps([{"index": 1, "score": 8, "summary": "Recovered.", "why_matters": "After retry."}])

        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=response_text)]
        mock_message.usage = mock_usage

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            anthropic_lib.RateLimitError(message="rate limit", response=MagicMock(status_code=429), body={}),
            mock_message,
        ]
        mock_anthropic_cls.return_value = mock_client

        from agents.summarizer.agent import run
        digest, _ = run(articles)

        assert len(digest) == 1
        assert digest[0]["summary"] == "Recovered."
        assert mock_client.messages.create.call_count == 2
