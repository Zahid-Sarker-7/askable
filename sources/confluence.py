import logging
import os
import time

from atlassian import Confluence
from markdownify import markdownify
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("askable.sources.confluence")

ATLASSIAN_URL = "https://optimizely-ext.atlassian.net"
DEFAULT_SPACE = "DEX"
RATE_LIMIT_DELAY = 0.5


def get_client() -> Confluence:
    return Confluence(
        url=ATLASSIAN_URL,
        username=os.getenv("ATLASSIAN_EMAIL"),
        password=os.getenv("ATLASSIAN_API_TOKEN"),
    )


def html_to_text(html: str) -> str:
    """Convert Confluence storage format HTML to clean plain text."""
    # TODO: Implement this function.
    #
    # Use markdownify to convert HTML to markdown (preserves structure better
    # than BeautifulSoup's get_text). Then strip excessive whitespace.
    #
    # Steps:
    # 1. Call markdownify(html, strip=["img", "script", "style"])
    #    - strip removes tags that produce garbage text
    # 2. Clean up: collapse 3+ consecutive newlines into 2
    # 3. Strip leading/trailing whitespace
    # 4. Return the cleaned text
    #
    # Test with: print(html_to_text("<h1>Title</h1><p>Hello <b>world</b></p>"))
    # Expected: "# Title\n\nHello **world**"

    raise NotImplementedError("TODO: implement html_to_text")


def fetch_pages(space: str = DEFAULT_SPACE, limit: int = 50) -> list[dict]:
    """Fetch all pages from a Confluence space, convert to plain text.

    Returns a list of dicts ready for ingest_single_document():
      {text, source, source_title, doc_type, date, author, owner}
    """
    # TODO: Implement this function.
    #
    # Steps:
    # 1. Create a Confluence client with get_client()
    #
    # 2. Fetch pages with pagination:
    #    pages = client.get_all_pages_from_space(
    #        space, start=0, limit=limit,
    #        expand="body.storage,version,history"
    #    )
    #    This returns a list of page dicts. Each page has:
    #      page["title"]                              → page title
    #      page["body"]["storage"]["value"]            → HTML content
    #      page["version"]["when"]                     → last modified ISO datetime
    #      page["history"]["createdBy"]["displayName"] → author name
    #      page["_links"]["webui"]                     → relative URL (prepend ATLASSIAN_URL + "/wiki")
    #
    # 3. For each page:
    #    a. Convert HTML to text with html_to_text()
    #    b. Skip if text is too short (< 50 chars — empty or stub pages)
    #    c. Build the source URL: f"{ATLASSIAN_URL}/wiki{page['_links']['webui']}"
    #    d. Extract date: page["version"]["when"][:10] (just the date part)
    #    e. Extract author: page["history"]["createdBy"]["displayName"]
    #    f. Append to results list with structure matching ingest_single_document()
    #    g. Sleep RATE_LIMIT_DELAY seconds between pages (avoid 429s)
    #    h. Log each page: log.info("Fetched: %s (%d chars)", title, len(text))
    #
    # 4. Log summary: log.info("Fetched %d pages from space %s", len(results), space)
    # 5. Return results list

    raise NotImplementedError("TODO: implement fetch_pages")
