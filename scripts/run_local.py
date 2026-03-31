"""
Run the full pipeline locally: scrape → summarize → print digest.

Usage:
    python scripts/run_local.py
"""

import os
import sys

# Ensure project root is on the path when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from agents.scraper import agent as scraper
from agents.summarizer import agent as summarizer


def main() -> None:
    print("Fetching articles...")
    articles = scraper.run()
    print(f"  Scraped {len(articles)} articles after deduplication.\n")

    if not articles:
        print("No articles found. Check source availability.")
        return

    print("Summarising with Claude Haiku...")
    digest = summarizer.run(articles)
    print(f"  Digest contains {len(digest)} scored articles.\n")

    print("=" * 60)
    print(f"  AI Research Digest  ({len(digest)} articles)")
    print("=" * 60)

    for i, item in enumerate(digest, 1):
        score = item.get("score", "?")
        bar = "█" * score + "░" * (10 - score) if isinstance(score, int) else ""
        print(f"\n{i}. [{score}/10] {bar}")
        print(f"   {item['title']}")
        print(f"   {item.get('summary', '')}")
        print(f"   Why it matters: {item.get('why_matters', '')}")
        print(f"   Source: {item.get('source', '')}  |  {item['url']}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
