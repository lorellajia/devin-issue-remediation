"""
worker.py
Polls the Devin API for every task currently "in_progress" and updates
the local tracker once Devin finishes (success -> PR link, or failure).

Run this once:
    python worker.py --once

Or run it continuously in the background (used inside Docker):
    python worker.py
"""

import sys
import time

from dotenv import load_dotenv

load_dotenv()

import db
import devin_client

POLL_INTERVAL_SECONDS = 20


def poll_once() -> int:
    """
    Check all trackable tasks once. Returns number of tasks updated.

    "Trackable" includes tasks marked "failed", not just "in_progress": a session
    we gave up on can be manually restarted/resumed from the Devin UI and become
    active again, so we keep re-checking it rather than freezing the local status
    forever. "completed" tasks are the only true dead end.
    """
    tasks = db.get_all_tasks()
    trackable = [t for t in tasks if t["status"] in ("in_progress", "failed") and t["devin_session_id"]]

    if not trackable:
        return 0

    updated = 0
    for task in trackable:
        session_id = task["devin_session_id"]
        try:
            session_data = devin_client.get_session_status(session_id)
        except Exception as e:
            print(f"  [task {task['id']}] error polling session {session_id}: {e}")
            continue

        status_enum = session_data.get("status_enum")
        pr_url = devin_client.extract_pr_url(session_data)

        if status_enum == "finished":
            if pr_url:
                db.update_status(task["id"], "completed", pr_url=pr_url)
                print(f"  [task {task['id']}] COMPLETED -> PR: {pr_url}")
            else:
                # Finished but no PR was opened -- treat as failed for our purposes,
                # since "success" for this system means "a PR was produced".
                db.update_status(task["id"], "failed", error_message="Session finished without opening a PR")
                print(f"  [task {task['id']}] FAILED -> finished with no PR")
            updated += 1
        elif status_enum == "expired":
            db.update_status(task["id"], "failed", error_message=f"Devin session ended with status: {status_enum}")
            print(f"  [task {task['id']}] FAILED -> {status_enum}")
            updated += 1
        elif status_enum == "blocked":
            # "blocked" means Devin is waiting on a reply in the session (e.g. asking for
            # repo access or a clarifying question) -- it is NOT terminal. The session can
            # resume and still finish successfully, so we keep polling. If a PR has already
            # been opened despite being blocked, treat it as done right away.
            if pr_url:
                db.update_status(task["id"], "completed", pr_url=pr_url)
                print(f"  [task {task['id']}] COMPLETED -> PR: {pr_url} (was blocked, but PR already exists)")
                updated += 1
            elif task["status"] == "failed":
                db.update_status(task["id"], "in_progress", error_message=None)
                print(f"  [task {task['id']}] RESUMED -> session is blocked (waiting on input) again, was failed")
                updated += 1
            else:
                print(f"  [task {task['id']}] blocked -- waiting on user input in the Devin session, still in_progress")
        else:
            # Actively running/working. If this task had previously been marked
            # "failed", the underlying session was restarted from the Devin UI --
            # bring the local status back in line with reality.
            if task["status"] == "failed":
                db.update_status(task["id"], "in_progress", error_message=None)
                print(f"  [task {task['id']}] RESUMED -> session is active again ({status_enum}), was failed")
                updated += 1
            else:
                print(f"  [task {task['id']}] still {status_enum or 'working'}...")

    return updated


def main():
    db.init_db()
    run_once = "--once" in sys.argv

    if run_once:
        print("Polling all in-progress tasks once...")
        poll_once()
        return

    print(f"Worker started. Polling every {POLL_INTERVAL_SECONDS}s. Ctrl+C to stop.")
    while True:
        poll_once()
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
