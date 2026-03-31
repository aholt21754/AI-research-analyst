"""Send a test email to verify SES is configured correctly."""
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
