# Devin Issue Remediation Bot

An event-driven automation that uses the [Devin API](https://docs.devin.ai/api-reference/overview)
to autonomously remediate GitHub issues — in this demo, four real issues
(2 security/dependency vulnerabilities, 1 code-quality fix, 1 type-check fix)
in a fork of [apache/superset](https://github.com/apache/superset).

Target fork: `https://github.com/lorellajia/superset`

## What this solves

Large codebases accumulate a steady stream of low-to-medium complexity
issues — dependency CVEs, lint failures, unused imports, stale type-ignore
comments — that are individually cheap to fix but collectively eat up a lot
of engineering time. This system turns "an issue needs fixing" into an
automated, observable, closed-loop workflow: **event in → Devin session →
pull request out**, with no human writing the fix.

## Architecture

```
GitHub issue labeled "devin-fix"  (the event)
            │
            ▼
   POST /webhook  (FastAPI, this repo)
            │  reads issue title/body via GitHub REST API
            ▼
   POST https://api.devin.ai/v1/sessions   (Devin starts working)
            │
            ▼
   background poller (every 20s)
   GET https://api.devin.ai/v1/sessions/{id}
            │
            ▼
   SQLite tracker  ──►  dashboard (http://localhost:8000)
                          + JSON API (/api/tasks, /api/stats)
                          + CLI report (report.py)
            │
            ▼
   Devin opens a Pull Request against the fork
```

Two ways to trigger the event, matching the "event-driven" requirement:

1. **Manual/simulated trigger** (`trigger.py`) — the primary path used in
   the demo. Running it *is* the event: it reads an issue URL, fetches the
   issue content from GitHub, and starts a Devin session. This avoids
   needing a public tunnel (ngrok) for a take-home demo, while exercising
   the exact same code path a real webhook would.
2. **Real GitHub webhook** (`POST /webhook`) — production-shaped path.
   Configure a webhook on the repo for "Issues" events; when an issue is
   labeled `devin-fix`, the FastAPI endpoint fires automatically and starts
   the Devin session the same way `trigger.py` does. See "Real webhook setup"
   below for the exact steps (ngrok tunnel + GitHub webhook + HMAC secret).

## Project structure

```
main.py           FastAPI app: /webhook, dashboard, JSON API, background poller
trigger.py        Manual/simulated event entry point (the demo driver)
worker.py         Polls Devin for in-progress sessions, updates status/PR links
devin_client.py   Thin wrapper around the Devin v1 API
github_client.py  Fetches issue title/body from the public GitHub API
db.py             SQLite persistence + stats aggregation
report.py         CLI summary report
templates/dashboard.html   Observability dashboard
issues.txt        The 4 target issue URLs
```

## Quick start (for reviewers)

Everything below runs entirely inside Docker — no local Python environment
needed.

### 1. Configure your API key

```bash
cp .env.example .env   # if .env doesn't already exist
```

Edit `.env` and set:

```
DEVIN_API_KEY=your_devin_api_key_here
```

This is the only required variable. (`GITHUB_TOKEN` and
`GITHUB_WEBHOOK_SECRET` are optional — see "Optional: real GitHub webhook"
below; you do not need them to run the demo.)

### 2. Start the app

```bash
docker compose up --build -d
```

This builds the image and starts the FastAPI app (webhook receiver +
dashboard + background poller) at **http://localhost:8000**. Confirm it's up:

```bash
curl http://localhost:8000/api/stats
```

### 3. Trigger the remediation run

The demo trigger runs *inside* the same container, so nothing extra needs to
be installed:

```bash
docker compose exec app python trigger.py --all
```

This reads all 4 issue URLs from `issues.txt`, fetches each issue from
GitHub, and starts a Devin session per issue. Expected output:

```
=== Event received: remediate https://github.com/lorellajia/superset/issues/1 ===
Fetching issue #1 from lorellajia/superset...
  Title: Security: Upgrade Flask from 2.3.3 to 3.1.3 (PYSEC-2026-2151)
Task #1 created in local tracker (status=queued)
Calling Devin API to start remediation session...
Devin session started: devin-xxxxxxxx
  Watch it live at: https://app.devin.ai/sessions/xxxxxxxx
Task #1 status -> in_progress
```

To trigger a single issue instead of all four:

```bash
docker compose exec app python trigger.py https://github.com/lorellajia/superset/issues/1
```

### 4. Watch it work

Open **http://localhost:8000** in a browser. The dashboard auto-refreshes
every 15s and will move each task from `queued` → `in_progress` →
`completed` (with a link to the resulting PR) as Devin finishes, driven by
the background poller already running inside the container — no extra step
needed. A completed run typically takes 5-15 minutes per issue.

### Running without Docker (alternative)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
# in a second terminal:
python trigger.py --all
```

## Optional: real GitHub webhook (production-shaped trigger)

Everything in "Quick start" above uses `trigger.py` as a stand-in for the
event — that's sufficient to review the whole system end-to-end and is the
recommended way to run this. This section is only for anyone who wants to
see the *other* trigger path actually fire: GitHub calling `POST /webhook`
automatically the instant an issue is labeled `devin-fix`, with no script
run by hand.

This requires a repo you control (to add a webhook to) and a public URL
(since `docker compose` only binds to `localhost:8000`), so it's not part
of the reviewable demo — it's here to show the code path is real, not just
described.

1. **Set a shared secret** — add to `.env`:
   ```
   GITHUB_WEBHOOK_SECRET=<random hex string>
   ```
   `main.py` uses this to verify the `X-Hub-Signature-256` header on every
   delivery (HMAC-SHA256) and rejects anything that doesn't match with a 401.
   Without this set, signature verification is skipped — fine for local
   testing, not for a real internet-facing endpoint (anyone who finds the URL
   could otherwise trigger arbitrary paid Devin sessions).

2. **Expose your local server**, e.g. with [ngrok](https://ngrok.com/):
   ```bash
   ngrok http 8000
   ```
   Copy the `https://<random>.ngrok-free.dev` URL it prints.

3. **Add the webhook on GitHub**: repo → Settings → Webhooks → Add webhook
   - Payload URL: `https://<your-ngrok-domain>/webhook`
   - Content type: `application/json`
   - Secret: the same value as `GITHUB_WEBHOOK_SECRET`
   - Events: select just "Issues"

4. **Test it**: add the `devin-fix` label to any issue on that repo. GitHub's
   webhook "Recent Deliveries" tab shows the request/response, and a new row
   should show up on the dashboard within a few seconds.

Note: a free ngrok tunnel's URL changes every time you restart it, so you'll
need to update the webhook's Payload URL after a restart (or use a paid
ngrok static domain).

## Observability

Three ways to check whether the system is working, from quickest to most detailed:

**1. Dashboard** — http://localhost:8000
Live view (auto-refreshes every 15s) showing total/completed/failed/in-progress
counts, success rate, average remediation time, and a per-issue table with
links to the Devin session and resulting PR.

**2. JSON API** — for scripting/integration
```bash
curl http://localhost:8000/api/stats
curl http://localhost:8000/api/tasks
```

**3. CLI report** — for a quick terminal check
```bash
docker compose exec app python report.py
```
```
=== Devin Automated Remediation — Run Report ===
Total tasks:        4
Completed:          4
Failed:             0
In progress:        0
Queued:             0
Success rate:       100.0%
Avg. fix time:      9.2 min
------------------------------------------------------------
✅ Issue #1    completed    PR: https://github.com/lorellajia/superset/pull/5
✅ Issue #2    completed    PR: https://github.com/lorellajia/superset/pull/6
✅ Issue #3    completed    PR: https://github.com/lorellajia/superset/pull/7
✅ Issue #4    completed    PR: https://github.com/lorellajia/superset/pull/8
```

Status updates happen automatically via the background poller (every 20s
inside `main.py`), or manually with:

```bash
docker compose exec app python worker.py --once
```

## Remediated issues (fork: lorellajia/superset)

| # | Type | Issue | PR |
|---|------|-------|----|
| 1 | Security (major version bump) | [Upgrade Flask 2.3.3 → 3.1.3](https://github.com/lorellajia/superset/issues/1) | _link once merged_ |
| 2 | Security (patch bump) | [Upgrade setuptools 80.9.0 → 83.0.0](https://github.com/lorellajia/superset/issues/2) | _link once merged_ |
| 3 | Code quality | [Remove unused import in daos/version.py](https://github.com/lorellajia/superset/issues/3) | _link once merged_ |
| 4 | Type checking | [Remove unused type:ignore in utils/json.py](https://github.com/lorellajia/superset/issues/4) | _link once merged_ |
