import logging
import os
import time

from atlassian import Jira
from markdownify import markdownify
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("askable.sources.jira")

ATLASSIAN_URL = "https://optimizely-ext.atlassian.net"
DEFAULT_PROJECT = "DHK"
DEFAULT_DAYS = 90
RATE_LIMIT_DELAY = 0.5


def get_client() -> Jira:
    return Jira(
        url=ATLASSIAN_URL,
        username=os.getenv("ATLASSIAN_EMAIL"),
        password=os.getenv("ATLASSIAN_API_TOKEN"),
    )


def ticket_to_text(issue: dict) -> str:
    """Combine a Jira ticket's summary, description, and comments into plain text.

    Jira descriptions can be HTML (rendered) or ADF (raw). We request rendered
    HTML via the renderedFields expand and convert with markdownify.
    """
    # TODO: Implement this function.
    #
    # Steps:
    # 1. Start with the summary as a heading:
    #    parts = [f"# {issue['fields']['summary']}"]
    #
    # 2. Get the rendered description (HTML):
    #    rendered = issue.get("renderedFields", {}).get("description", "")
    #    If rendered is truthy, convert with markdownify(rendered) and append.
    #    Otherwise, try the raw description: issue["fields"].get("description", "")
    #    and append as-is (it might be plain text or None).
    #
    # 3. Get comments from rendered fields:
    #    rendered_comments = issue.get("renderedFields", {}).get("comment", {})
    #    comment_list = rendered_comments.get("comments", [])
    #    For each comment:
    #      author = comment.get("author", {}).get("displayName", "Unknown")
    #      body = markdownify(comment.get("body", ""))
    #      Append: f"\n---\n**{author}:**\n{body}"
    #    Limit to the last 10 comments to keep text manageable.
    #
    # 4. Join all parts with "\n\n" and return

    raise NotImplementedError("TODO: implement ticket_to_text")


def fetch_tickets(project: str = DEFAULT_PROJECT, days: int = DEFAULT_DAYS, limit: int = 100) -> list[dict]:
    """Fetch recent Jira tickets from a project, convert to plain text.

    Returns a list of dicts ready for ingest_single_document():
      {text, source, source_title, doc_type, date, author, owner}
    """
    # TODO: Implement this function.
    #
    # Steps:
    # 1. Create a Jira client with get_client()
    #
    # 2. Build JQL query:
    #    jql = f"project = {project} AND updated >= -{days}d ORDER BY updated DESC"
    #
    # 3. Fetch tickets:
    #    response = client.jql(
    #        jql, limit=limit,
    #        fields="summary,description,comment,status,assignee,reporter,updated,created",
    #        expand="renderedFields"
    #    )
    #    issues = response.get("issues", [])
    #
    # 4. For each issue:
    #    a. Convert to text with ticket_to_text(issue)
    #    b. Skip if text is too short (< 30 chars)
    #    c. Extract:
    #       - key: issue["key"] (e.g., "DHK-123")
    #       - summary: issue["fields"]["summary"]
    #       - source URL: f"{ATLASSIAN_URL}/browse/{key}"
    #       - date: issue["fields"]["updated"][:10]
    #       - author: issue["fields"].get("reporter", {}).get("displayName", "unknown")
    #    d. Append to results with doc_type="jira_ticket", owner=project
    #    e. Sleep RATE_LIMIT_DELAY between tickets
    #    f. Log: log.info("Fetched: %s — %s (%d chars)", key, summary[:60], len(text))
    #
    # 5. Log summary: log.info("Fetched %d tickets from project %s", len(results), project)
    # 6. Return results list

    raise NotImplementedError("TODO: implement fetch_tickets")
