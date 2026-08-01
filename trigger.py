"""
trigger.py
This is the "event" entry point for the automation.

In a full production setup this same logic would run inside the FastAPI
webhook handler (see main.py: POST /webhook), fired automatically the
moment someone labels a GitHub issue "devin-fix". For this demo, running
this script IS the event -- it simulates "issue got labeled / flagged for
remediation" without needing a public webhook + ngrok tunnel.

Usage:
    python trigger.py https://github.com/lorellajia/superset/issues/1
    python trigger.py --all     # process all 4 issues in issues.txt
"""

import sys
import time

from dotenv import load_dotenv

load_dotenv()

import db
import devin_client
import github_client

ISSUES_FILE = "issues.txt"


def remediate_issue(issue_url: str):
    print(f"\n=== Event received: remediate {issue_url} ===")

    owner, repo, issue_number = github_client.parse_issue_url(issue_url)
    repo_full_name = f"{owner}/{repo}"

    print(f"Fetching issue #{issue_number} from {repo_full_name}...")
    issue = github_client.fetch_issue(owner, repo, issue_number)
    print(f"  Title: {issue['title']}")

    task_id = db.create_task(issue_url, issue_number, issue["title"])
    print(f"Task #{task_id} created in local tracker (status=queued)")

    print("Calling Devin API to start remediation session...")
    session = devin_client.create_session(
        repo_full_name=repo_full_name,
        issue_number=issue_number,
        issue_title=issue["title"],
        issue_body=issue["body"],
    )

    session_id = session["session_id"]
    session_url = session.get("url", "")
    db.set_devin_session(task_id, session_id, session_url)

    print(f"Devin session started: {session_id}")
    print(f"  Watch it live at: {session_url}")
    print(f"Task #{task_id} status -> in_progress")

    return task_id


def main():
    db.init_db()

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--all":
        try:
            with open(ISSUES_FILE) as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        except FileNotFoundError:
            print(f"No {ISSUES_FILE} found. Create one with one issue URL per line.")
            sys.exit(1)

        task_ids = []
        for url in urls:
            task_id = remediate_issue(url)
            task_ids.append(task_id)
            time.sleep(1)  # be polite to the APIs

        print(f"\nAll {len(task_ids)} tasks submitted to Devin.")
        print("Run `python worker.py` to poll for completion, or check the dashboard.")
    else:
        remediate_issue(sys.argv[1])


if __name__ == "__main__":
    main()
