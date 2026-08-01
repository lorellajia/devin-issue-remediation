"""
devin_client.py
Thin wrapper around the Devin v1 API (https://docs.devin.ai/api-reference/overview).

Two calls are used:
  POST /v1/sessions              -> start a new Devin session (a "task")
  GET  /v1/sessions/{session_id} -> poll for status + resulting PR
"""

import os
import requests

DEVIN_API_BASE = "https://api.devin.ai/v1"
DEVIN_API_KEY = os.getenv("DEVIN_API_KEY")

if not DEVIN_API_KEY:
    raise RuntimeError(
        "DEVIN_API_KEY is not set. Add it to your .env file "
        "(DEVIN_API_KEY=your_key_here) before running the app."
    )

HEADERS = {
    "Authorization": f"Bearer {DEVIN_API_KEY}",
    "Content-Type": "application/json",
}

# Devin's status_enum values that mean "the session is done, one way or another"
TERMINAL_STATUSES = {"finished", "expired", "blocked"}


def build_prompt(repo_full_name: str, issue_number: int, issue_title: str, issue_body: str) -> str:
    """
    Construct the instruction we hand to Devin. Being explicit about the repo,
    the issue, and what "done" looks like gives Devin (and us) a clear
    success criterion to check against later.
    """
    return f"""You are working in the GitHub repository {repo_full_name}.

Please resolve GitHub issue #{issue_number}: "{issue_title}"

Issue description:
{issue_body}

Instructions:
1. Clone/checkout the repository and locate the relevant code.
2. Make the minimal, correct change needed to resolve the issue.
3. Run any relevant checks (flake8/mypy/tests) to confirm the fix is valid and
   nothing else is broken.
4. Open a pull request against the default branch with a clear title and
   description referencing "Fixes #{issue_number}".

Only make changes directly related to this issue. Do not refactor unrelated code.
"""


def create_session(repo_full_name: str, issue_number: int, issue_title: str, issue_body: str) -> dict:
    """
    Kick off a new Devin session to fix a specific issue.
    Returns the raw API response, e.g. {"session_id": ..., "url": ..., "is_new_session": ...}
    """
    prompt = build_prompt(repo_full_name, issue_number, issue_title, issue_body)

    resp = requests.post(
        f"{DEVIN_API_BASE}/sessions",
        headers=HEADERS,
        json={
            "prompt": prompt,
            "idempotent": True,
            "title": f"Fix issue #{issue_number}: {issue_title}",
            "tags": ["auto-remediation", f"issue-{issue_number}"],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_session_status(session_id: str) -> dict:
    """
    Poll a session for its current status and (if finished) the resulting PR.
    Returns the raw API response including status_enum and pull_request.
    """
    resp = requests.get(
        f"{DEVIN_API_BASE}/sessions/{session_id}",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def extract_pr_url(session_data: dict) -> str | None:
    pr = session_data.get("pull_request")
    if pr and isinstance(pr, dict):
        return pr.get("url")
    return None
