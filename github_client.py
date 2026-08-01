"""
github_client.py
Minimal helper for reading issue data from the public GitHub REST API.
No auth token is required for public repos (rate-limited to 60 req/hr,
which is plenty for this demo).
"""

import os
import re
import requests

ISSUE_URL_RE = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)"
)

# Optional: set GITHUB_TOKEN in .env to raise the rate limit from 60/hr
# (unauthenticated) to 5000/hr. Not required for a handful of demo calls.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


def _headers():
    if GITHUB_TOKEN:
        return {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    return {}


def parse_issue_url(issue_url: str) -> tuple[str, str, int]:
    """
    Parse a GitHub issue URL like:
      https://github.com/lorellajia/superset/issues/1
    into (owner, repo, issue_number).
    """
    match = ISSUE_URL_RE.search(issue_url)
    if not match:
        raise ValueError(f"Could not parse GitHub issue URL: {issue_url}")
    return match.group("owner"), match.group("repo"), int(match.group("number"))


def fetch_issue(owner: str, repo: str, issue_number: int) -> dict:
    """
    Fetch issue title/body from the GitHub REST API.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
    resp = requests.get(url, headers=_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return {
        "title": data.get("title", ""),
        "body": data.get("body", "") or "",
        "number": issue_number,
        "html_url": data.get("html_url", ""),
    }
