"""
main.py
FastAPI service that ties the whole system together:

  - POST /webhook          real GitHub webhook receiver (issue "labeled" event)
  - GET  /                 observability dashboard (HTML)
  - GET  /api/tasks        raw task list (JSON)
  - GET  /api/stats        summary metrics (JSON)

A background task polls Devin every 20s for any in-progress session and
updates the local tracker, so the dashboard always reflects current state
without the user needing to refresh Devin manually.
"""

import asyncio
import hashlib
import hmac
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

import db
import devin_client
import github_client
import worker

TRIGGER_LABEL = os.getenv("TRIGGER_LABEL", "devin-fix")
POLL_INTERVAL_SECONDS = 20
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")


def verify_signature(secret: str, payload_body: bytes, signature_header: str | None) -> bool:
    """Validate the X-Hub-Signature-256 header GitHub sends with every webhook delivery."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))


templates = Jinja2Templates(directory="templates")


async def background_poller():
    while True:
        try:
            worker.poll_once()
        except Exception as e:
            print(f"[poller] error: {e}")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    task = asyncio.create_task(background_poller())
    yield
    task.cancel()


app = FastAPI(title="Devin Issue Remediation Bot", lifespan=lifespan)


@app.post("/webhook")
async def github_webhook(request: Request):
    """
    Real event-driven trigger. Configure this URL as a GitHub webhook
    (Settings -> Webhooks) listening to "Issues" events. When an issue is
    labeled with TRIGGER_LABEL, a Devin remediation session is started
    automatically.
    """
    body = await request.body()

    if GITHUB_WEBHOOK_SECRET:
        if not verify_signature(GITHUB_WEBHOOK_SECRET, body, request.headers.get("X-Hub-Signature-256")):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()

    action = payload.get("action")
    issue = payload.get("issue")

    if not issue:
        return JSONResponse({"status": "ignored", "reason": "not a relevant issue event"})

    if action == "labeled":
        # The label was added to an issue that already existed.
        has_trigger_label = payload.get("label", {}).get("name") == TRIGGER_LABEL
    elif action == "opened":
        # GitHub reports "opened", not "labeled", when the issue is created
        # with the label already attached -- check the issue's label list too.
        has_trigger_label = any(l.get("name") == TRIGGER_LABEL for l in issue.get("labels", []))
    else:
        has_trigger_label = False

    if not has_trigger_label:
        return JSONResponse({"status": "ignored", "reason": f"label is not '{TRIGGER_LABEL}'"})

    repo_full_name = payload["repository"]["full_name"]
    issue_number = issue["number"]
    issue_title = issue["title"]
    issue_body = issue.get("body", "") or ""
    issue_url = issue["html_url"]

    task_id = db.create_task(issue_url, issue_number, issue_title)

    session = devin_client.create_session(
        repo_full_name=repo_full_name,
        issue_number=issue_number,
        issue_title=issue_title,
        issue_body=issue_body,
    )
    db.set_devin_session(task_id, session["session_id"], session.get("url", ""))

    return JSONResponse(
        {
            "status": "started",
            "task_id": task_id,
            "devin_session_id": session["session_id"],
            "devin_session_url": session.get("url"),
        }
    )


@app.get("/api/tasks")
async def api_tasks():
    return db.get_all_tasks()


@app.get("/api/stats")
async def api_stats():
    return db.get_stats()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    stats = db.get_stats()
    tasks = db.get_all_tasks()
    return templates.TemplateResponse(
        request, "dashboard.html", {"stats": stats, "tasks": tasks}
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
