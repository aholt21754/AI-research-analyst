"""Unit tests for scraper sources and scraper agent.

All HTTP calls are mocked — no real network traffic.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import responses as responses_lib
from responses import GET

# ── Fixtures ──────────────────────────────────────────────────────────────────

FIXTURES = Path(__file__).parent.parent / "fixtures"

ARXIV_URL = "http://export.arxiv.org/api/query"
HN_URL = "https://hn.algolia.com/api/v1/search"
GITHUB_URL = "https://github.com/trending"


def _load(filename: str) -> str:
    return (FIXTURES / filename).read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# arXiv
# ══════════════════════════════════════════════════════════════════════════════

class TestArxivSource:
    @responses_lib.activate
    def test_happy_path_returns_articles(self):
        responses_lib.add(GET, ARXIV_URL, body=_load("arxiv_response.xml"), status=200)
        from agents.scraper.sources.arxiv import fetch_articles
        articles = fetch_articles()
        assert len(articles) == 3

    @responses_lib.activate
    def test_article_has_all_required_fields(self):
        responses_lib.add(GET, ARXIV_URL, body=_load("arxiv_response.xml"), status=200)
        from agents.scraper.sources.arxiv import fetch_articles
        articles = fetch_articles()
        required = {"title", "url", "abstract", "source", "published_date"}
        for a in articles:
            assert required.issubset(a.keys()), f"Missing fields in: {a}"

    @responses_lib.activate
    def test_source_field_is_arxiv(self):
        responses_lib.add(GET, ARXIV_URL, body=_load("arxiv_response.xml"), status=200)
        from agents.scraper.sources.arxiv import fetch_articles
        articles = fetch_articles()
        assert all(a["source"] == "arxiv" for a in articles)

    @responses_lib.activate
    def test_url_is_https_arxiv(self):
        responses_lib.add(GET, ARXIV_URL, body=_load("arxiv_response.xml"), status=200)
        from agents.scraper.sources.arxiv import fetch_articles
        articles = fetch_articles()
        assert all(a["url"].startswith("https://arxiv.org/abs/") for a in articles)

    @responses_lib.activate
    def test_whitespace_stripped_from_title(self):
        responses_lib.add(GET, ARXIV_URL, body=_load("arxiv_response.xml"), status=200)
        from agents.scraper.sources.arxiv import fetch_articles
        articles = fetch_articles()
        assert articles[0]["title"] == "Efficient LLM Agents via Novel Attention Patterns"

    @responses_lib.activate
    def test_http_timeout_returns_empty_list(self):
        import urllib.error
        responses_lib.add(GET, ARXIV_URL, body=urllib.error.URLError("timed out"))
        from agents.scraper.sources import arxiv
        # Patch sleep to speed up retries
        with patch("agents.scraper.sources.arxiv.time.sleep"):
            articles = arxiv.fetch_articles()
        assert articles == []

    @responses_lib.activate
    def test_http_500_returns_empty_after_retries(self):
        for _ in range(4):
            responses_lib.add(GET, ARXIV_URL, status=500)
        from agents.scraper.sources import arxiv
        with patch("agents.scraper.sources.arxiv.time.sleep"):
            articles = arxiv.fetch_articles()
        assert articles == []

    @responses_lib.activate
    def test_http_404_returns_empty_no_retry(self):
        responses_lib.add(GET, ARXIV_URL, status=404)
        from agents.scraper.sources import arxiv
        with patch("agents.scraper.sources.arxiv.time.sleep"):
            articles = arxiv.fetch_articles()
        assert articles == []
        # Only one request should have been made (no retry on 4xx)
        assert len(responses_lib.calls) == 1

    @responses_lib.activate
    def test_malformed_xml_returns_empty_list(self):
        responses_lib.add(GET, ARXIV_URL, body="THIS IS NOT XML", status=200)
        from agents.scraper.sources.arxiv import fetch_articles
        articles = fetch_articles()
        assert articles == []

    @responses_lib.activate
    def test_partial_parse_returns_valid_entries(self):
        # One entry missing the title element
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/abs/2501.99991v1</id>
    <summary>Valid abstract.</summary>
    <published>2026-03-21T00:00:00Z</published>
  </entry>
  <entry>
    <id>https://arxiv.org/abs/2501.99992v1</id>
    <title>Valid Title</title>
    <summary>Valid abstract.</summary>
    <published>2026-03-21T00:00:00Z</published>
  </entry>
</feed>"""
        responses_lib.add(GET, ARXIV_URL, body=xml, status=200)
        from agents.scraper.sources.arxiv import fetch_articles
        articles = fetch_articles()
        assert len(articles) == 1
        assert articles[0]["title"] == "Valid Title"

    @responses_lib.activate
    def test_empty_result_returns_empty_list(self):
        xml = '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        responses_lib.add(GET, ARXIV_URL, body=xml, status=200)
        from agents.scraper.sources.arxiv import fetch_articles
        assert fetch_articles() == []


# ══════════════════════════════════════════════════════════════════════════════
# Hacker News
# ══════════════════════════════════════════════════════════════════════════════

class TestHackerNewsSource:
    @responses_lib.activate
    def test_happy_path_returns_articles(self):
        responses_lib.add(GET, HN_URL, body=_load("hn_response.json"), status=200, content_type="application/json")
        from agents.scraper.sources.hackernews import fetch_articles
        articles = fetch_articles()
        assert len(articles) == 3

    @responses_lib.activate
    def test_article_has_all_required_fields(self):
        responses_lib.add(GET, HN_URL, body=_load("hn_response.json"), status=200, content_type="application/json")
        from agents.scraper.sources.hackernews import fetch_articles
        articles = fetch_articles()
        required = {"title", "url", "abstract", "source", "published_date"}
        for a in articles:
            assert required.issubset(a.keys())

    @responses_lib.activate
    def test_source_field_is_hackernews(self):
        responses_lib.add(GET, HN_URL, body=_load("hn_response.json"), status=200, content_type="application/json")
        from agents.scraper.sources.hackernews import fetch_articles
        articles = fetch_articles()
        assert all(a["source"] == "hackernews" for a in articles)

    @responses_lib.activate
    def test_missing_url_falls_back_to_hn_link(self):
        responses_lib.add(GET, HN_URL, body=_load("hn_response.json"), status=200, content_type="application/json")
        from agents.scraper.sources.hackernews import fetch_articles
        articles = fetch_articles()
        # Third item in fixture has null url — should fall back to HN item URL
        hn_item = next(a for a in articles if "40000003" in a["url"])
        assert hn_item["url"] == "https://news.ycombinator.com/item?id=40000003"

    @responses_lib.activate
    def test_http_timeout_returns_empty_list(self):
        import requests as req
        responses_lib.add(GET, HN_URL, body=req.exceptions.Timeout())
        from agents.scraper.sources import hackernews
        with patch("agents.scraper.sources.hackernews.time.sleep"):
            articles = hackernews.fetch_articles()
        assert articles == []

    @responses_lib.activate
    def test_http_500_returns_empty_list(self):
        for _ in range(4):
            responses_lib.add(GET, HN_URL, status=500)
        from agents.scraper.sources import hackernews
        with patch("agents.scraper.sources.hackernews.time.sleep"):
            articles = hackernews.fetch_articles()
        assert articles == []

    @responses_lib.activate
    def test_invalid_json_returns_empty_list(self):
        responses_lib.add(GET, HN_URL, body="not json", status=200, content_type="application/json")
        from agents.scraper.sources.hackernews import fetch_articles
        articles = fetch_articles()
        assert articles == []

    @responses_lib.activate
    def test_missing_hits_key_returns_empty_list(self):
        responses_lib.add(GET, HN_URL, body='{"results": []}', status=200, content_type="application/json")
        from agents.scraper.sources.hackernews import fetch_articles
        articles = fetch_articles()
        assert articles == []

    @responses_lib.activate
    def test_missing_item_field_skips_item(self):
        body = '{"hits": [{"url": "https://example.com", "created_at": "2026-03-21T00:00:00Z", "objectID": "1"}]}'
        responses_lib.add(GET, HN_URL, body=body, status=200, content_type="application/json")
        from agents.scraper.sources.hackernews import fetch_articles
        # Item has no title — should be skipped
        articles = fetch_articles()
        assert articles == []


# ══════════════════════════════════════════════════════════════════════════════
# GitHub Trending
# ══════════════════════════════════════════════════════════════════════════════

class TestGithubTrendingSource:
    @responses_lib.activate
    def test_happy_path_returns_ai_repos(self):
        responses_lib.add(GET, GITHUB_URL, body=_load("github_trending.html"), status=200, content_type="text/html")
        from agents.scraper.sources.github_trending import fetch_articles
        articles = fetch_articles()
        # Fixture has 4 repos; linux kernel should be filtered out → 3 AI repos
        assert len(articles) == 3

    @responses_lib.activate
    def test_article_has_all_required_fields(self):
        responses_lib.add(GET, GITHUB_URL, body=_load("github_trending.html"), status=200, content_type="text/html")
        from agents.scraper.sources.github_trending import fetch_articles
        articles = fetch_articles()
        required = {"title", "url", "abstract", "source", "published_date"}
        for a in articles:
            assert required.issubset(a.keys())

    @responses_lib.activate
    def test_source_field_is_github(self):
        responses_lib.add(GET, GITHUB_URL, body=_load("github_trending.html"), status=200, content_type="text/html")
        from agents.scraper.sources.github_trending import fetch_articles
        articles = fetch_articles()
        assert all(a["source"] == "github" for a in articles)

    @responses_lib.activate
    def test_url_is_full_github_url(self):
        responses_lib.add(GET, GITHUB_URL, body=_load("github_trending.html"), status=200, content_type="text/html")
        from agents.scraper.sources.github_trending import fetch_articles
        articles = fetch_articles()
        assert all(a["url"].startswith("https://github.com/") for a in articles)

    @responses_lib.activate
    def test_non_ai_repos_filtered_out(self):
        responses_lib.add(GET, GITHUB_URL, body=_load("github_trending.html"), status=200, content_type="text/html")
        from agents.scraper.sources.github_trending import fetch_articles
        articles = fetch_articles()
        titles = [a["title"] for a in articles]
        assert not any("torvalds" in t for t in titles)

    @responses_lib.activate
    def test_http_timeout_returns_empty_list(self):
        import requests as req
        responses_lib.add(GET, GITHUB_URL, body=req.exceptions.Timeout())
        from agents.scraper.sources import github_trending
        with patch("agents.scraper.sources.github_trending.time.sleep"):
            articles = github_trending.fetch_articles()
        assert articles == []

    @responses_lib.activate
    def test_http_500_returns_empty_list(self):
        for _ in range(4):
            responses_lib.add(GET, GITHUB_URL, status=500)
        from agents.scraper.sources import github_trending
        with patch("agents.scraper.sources.github_trending.time.sleep"):
            articles = github_trending.fetch_articles()
        assert articles == []

    @responses_lib.activate
    def test_empty_trending_page_returns_empty_list(self):
        responses_lib.add(GET, GITHUB_URL, body="<html><body><p>No repos</p></body></html>", status=200, content_type="text/html")
        from agents.scraper.sources.github_trending import fetch_articles
        articles = fetch_articles()
        assert articles == []


# ══════════════════════════════════════════════════════════════════════════════
# RSS
# feedparser uses urllib internally (not requests), so we mock feedparser.parse
# directly rather than using the responses library.
# ══════════════════════════════════════════════════════════════════════════════

import feedparser as _feedparser

RSS_FEED_URL = "https://paperswithcode.com/rss"


def _parsed_feed(xml_text: str, status: int = 200) -> object:
    """Parse XML from a string (no network) and inject a status code."""
    feed = _feedparser.parse(xml_text)
    feed["status"] = status
    return feed


def _error_feed(exc: Exception) -> object:
    """Simulate a feedparser result that raises on parse."""
    raise exc


class TestRssSource:
    def test_happy_path_returns_articles(self):
        mock_result = _parsed_feed(_load("rss_response.xml"))
        with patch("agents.scraper.sources.rss.feedparser.parse", return_value=mock_result):
            from agents.scraper.sources.rss import fetch_articles
            articles = fetch_articles(feed_urls=[RSS_FEED_URL])
        assert len(articles) == 3

    def test_article_has_all_required_fields(self):
        mock_result = _parsed_feed(_load("rss_response.xml"))
        with patch("agents.scraper.sources.rss.feedparser.parse", return_value=mock_result):
            from agents.scraper.sources.rss import fetch_articles
            articles = fetch_articles(feed_urls=[RSS_FEED_URL])
        required = {"title", "url", "abstract", "source", "published_date"}
        for a in articles:
            assert required.issubset(a.keys())

    def test_source_field_is_rss(self):
        mock_result = _parsed_feed(_load("rss_response.xml"))
        with patch("agents.scraper.sources.rss.feedparser.parse", return_value=mock_result):
            from agents.scraper.sources.rss import fetch_articles
            articles = fetch_articles(feed_urls=[RSS_FEED_URL])
        assert all(a["source"] == "rss" for a in articles)

    def test_empty_feed_returns_empty_list(self):
        empty_xml = '<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>'
        mock_result = _parsed_feed(empty_xml)
        with patch("agents.scraper.sources.rss.feedparser.parse", return_value=mock_result):
            from agents.scraper.sources.rss import fetch_articles
            articles = fetch_articles(feed_urls=[RSS_FEED_URL])
        assert articles == []

    def test_multiple_feeds_combined(self):
        feed2_url = "https://thegradient.pub/rss/"
        mock_result = _parsed_feed(_load("rss_response.xml"))
        with patch("agents.scraper.sources.rss.feedparser.parse", return_value=mock_result):
            from agents.scraper.sources.rss import fetch_articles
            articles = fetch_articles(feed_urls=[RSS_FEED_URL, feed2_url])
        assert len(articles) == 6  # 3 per feed × 2 feeds

    def test_failed_feed_skips_continues_to_next(self):
        feed2_url = "https://thegradient.pub/rss/"
        good_result = _parsed_feed(_load("rss_response.xml"))

        def _side_effect(url):
            if url == RSS_FEED_URL:
                raise ConnectionError("network down")
            return good_result

        with patch("agents.scraper.sources.rss.feedparser.parse", side_effect=_side_effect):
            from agents.scraper.sources.rss import fetch_articles
            articles = fetch_articles(feed_urls=[RSS_FEED_URL, feed2_url])
        assert len(articles) == 3

    def test_missing_published_date_uses_today(self):
        from datetime import date
        no_date_xml = """<?xml version="1.0"?><rss version="2.0"><channel>
          <item>
            <title>No Date Article</title>
            <link>https://example.com/no-date</link>
            <description>Content here.</description>
          </item>
        </channel></rss>"""
        mock_result = _parsed_feed(no_date_xml)
        with patch("agents.scraper.sources.rss.feedparser.parse", return_value=mock_result):
            from agents.scraper.sources.rss import fetch_articles
            articles = fetch_articles(feed_urls=[RSS_FEED_URL])
        assert len(articles) == 1
        assert articles[0]["published_date"] == date.today().isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# Scraper Agent
# ══════════════════════════════════════════════════════════════════════════════

def _make_article(title: str, url: str, source: str = "arxiv", date: str = "2026-03-21T00:00:00Z") -> dict:
    return {"title": title, "url": url, "abstract": "Test abstract.", "source": source, "published_date": date}


class TestScraperAgent:
    def test_merges_results_from_all_sources(self):
        with patch("agents.scraper.agent.arxiv.fetch_articles", return_value=[_make_article("A", "https://a.com", "arxiv")]), \
             patch("agents.scraper.agent.hackernews.fetch_articles", return_value=[_make_article("B", "https://b.com", "hackernews")]), \
             patch("agents.scraper.agent.github_trending.fetch_articles", return_value=[_make_article("C", "https://c.com", "github")]), \
             patch("agents.scraper.agent.rss.fetch_articles", return_value=[_make_article("D", "https://d.com", "rss")]):
            from agents.scraper import agent
            result = agent.run()
        assert len(result) == 4
        sources = {a["source"] for a in result}
        assert sources == {"arxiv", "hackernews", "github", "rss"}

    def test_deduplication_removes_same_url(self):
        shared_url = "https://shared.com/article"
        with patch("agents.scraper.agent.arxiv.fetch_articles", return_value=[_make_article("A", shared_url, "arxiv")]), \
             patch("agents.scraper.agent.hackernews.fetch_articles", return_value=[_make_article("A-HN", shared_url, "hackernews")]), \
             patch("agents.scraper.agent.github_trending.fetch_articles", return_value=[]), \
             patch("agents.scraper.agent.rss.fetch_articles", return_value=[]):
            from agents.scraper import agent
            result = agent.run()
        urls = [a["url"] for a in result]
        assert urls.count(shared_url) == 1

    def test_sorted_by_date_descending(self):
        with patch("agents.scraper.agent.arxiv.fetch_articles", return_value=[
                _make_article("Old", "https://old.com", date="2026-01-01T00:00:00Z"),
                _make_article("New", "https://new.com", date="2026-03-21T00:00:00Z"),
             ]), \
             patch("agents.scraper.agent.hackernews.fetch_articles", return_value=[]), \
             patch("agents.scraper.agent.github_trending.fetch_articles", return_value=[]), \
             patch("agents.scraper.agent.rss.fetch_articles", return_value=[]):
            from agents.scraper import agent
            result = agent.run()
        assert result[0]["title"] == "New"
        assert result[1]["title"] == "Old"

    def test_one_source_fails_others_succeed(self):
        with patch("agents.scraper.agent.arxiv.fetch_articles", side_effect=RuntimeError("network down")), \
             patch("agents.scraper.agent.hackernews.fetch_articles", return_value=[_make_article("B", "https://b.com", "hackernews")]), \
             patch("agents.scraper.agent.github_trending.fetch_articles", return_value=[]), \
             patch("agents.scraper.agent.rss.fetch_articles", return_value=[]):
            from agents.scraper import agent
            result = agent.run()
        assert len(result) == 1
        assert result[0]["source"] == "hackernews"

    def test_all_sources_fail_returns_empty_list(self):
        with patch("agents.scraper.agent.arxiv.fetch_articles", side_effect=RuntimeError()), \
             patch("agents.scraper.agent.hackernews.fetch_articles", side_effect=RuntimeError()), \
             patch("agents.scraper.agent.github_trending.fetch_articles", side_effect=RuntimeError()), \
             patch("agents.scraper.agent.rss.fetch_articles", side_effect=RuntimeError()):
            from agents.scraper import agent
            result = agent.run()
        assert result == []

    def test_returns_at_most_40_articles(self):
        many = [_make_article(f"Article {i}", f"https://example.com/{i}") for i in range(50)]
        with patch("agents.scraper.agent.arxiv.fetch_articles", return_value=many), \
             patch("agents.scraper.agent.hackernews.fetch_articles", return_value=[]), \
             patch("agents.scraper.agent.github_trending.fetch_articles", return_value=[]), \
             patch("agents.scraper.agent.rss.fetch_articles", return_value=[]):
            from agents.scraper import agent
            result = agent.run()
        assert len(result) <= 40
