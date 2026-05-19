# Orchestration B — GitHub Actions + Python

Cloud-hosted, laptop-independent daily PM job digest. Same configs and résumés as the n8n setup (Orchestration A) but the pipeline runs on GitHub-hosted runners instead of your Mac.

## How it works

The workflow at [`.github/workflows/daily.yml`](../.github/workflows/daily.yml) fires:
- **On a cron**: every day at 02:30 UTC (= 8:00 AM IST).
- **On `workflow_dispatch`**: manual trigger from the GitHub UI, useful for testing.

Each run:
1. Checks out the repo (which carries the configs, résumés, and dedup state).
2. Sets up Python 3.12 with pip cache.
3. Runs the three scripts in order:
   - `scrape.py` — fetches all boards in parallel, normalizes, filters, dedups, routes résumés.
   - `match.py` — scores each remaining job against its routed résumé via Groq Llama-3.3.
   - `notify.py` — formats into chunked Telegram messages, sends, persists dedup state on success.
4. Commits the updated `jobs_seen.json` back to the repo, so tomorrow's run knows what was already delivered.

Average run time: ~30 seconds. Daily Actions-minute usage: ~150 min/month — well under the 2,000-min free-tier cap (and unlimited on public repos).

## Repo secrets (set once)

The workflow needs five secrets under **Settings → Secrets and variables → Actions**:

| Secret | Where to get it |
|---|---|
| `GROQ_API_KEY` | https://console.groq.com/keys → Create API Key |
| `TELEGRAM_BOT_TOKEN` | @BotFather on Telegram → `/newbot` |
| `TELEGRAM_CHAT_ID` | Send any message to your bot → fetch `https://api.telegram.org/bot<TOKEN>/getUpdates` → use `chat.id` |
| `RESUME_APRIL_2026` | Base64-encoded contents of `resumes/april_2026.txt` (kept out of the public repo). Set with: `gh secret set RESUME_APRIL_2026 --body "$(base64 < resumes/april_2026.txt)"` |
| `RESUME_DIGITAL_PAYMENTS` | Base64-encoded contents of `resumes/digital_payments.txt`. Set with: `gh secret set RESUME_DIGITAL_PAYMENTS --body "$(base64 < resumes/digital_payments.txt)"` |

The first three match the names used in `.env` for Orchestration A. The two résumé secrets are unique to Orchestration B — they exist so the public repo never contains your contact info (résumés are gitignored). The workflow decodes them into `resumes/*.txt` at the start of every run.

To rotate a résumé later: re-run `python3 scripts/parse_resume.py /path/new.pdf resumes/april_2026.txt` and then `gh secret set RESUME_APRIL_2026 --body "$(base64 < resumes/april_2026.txt)"`.

## File layout

```
github_actions/
├── README.md            ← you are here
├── requirements.txt     ← single dep: requests
├── common.py            ← config / artifact helpers, shared by all 3 scripts
├── scrape.py            ← stage 1
├── match.py             ← stage 2
├── notify.py            ← stage 3
└── _artifacts/          ← gitignored intermediate JSON between stages
```

Shared with Orchestration A (live at repo root):
```
config/sources.json
config/filters.json
config/resume_routing.json
resumes/*.txt
jobs_seen.json           ← committed; the cloud's dedup memory
```

## Local testing

You can run the three stages by hand without touching GitHub:

```bash
cd "/Users/harshmacminim4/PM Job Scrapper"
pip install -r github_actions/requirements.txt
export GROQ_API_KEY=gsk_...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...

cd github_actions
python scrape.py    # → _artifacts/scrape_output.json
python match.py     # → _artifacts/match_output.json
python notify.py    # → sends Telegram, updates ../jobs_seen.json
```

Re-running scrape/match locally is safe — `notify.py` is the only step that persists dedup state. If you stop before `notify.py`, no jobs are marked seen.

## Why the three scripts pipe via JSON artifacts

Splitting the pipeline into discrete stages, each reading from `_artifacts/`, has two payoffs:

1. **Debuggable in isolation.** You can re-run `match.py` against the same scraped output to iterate on prompts without re-hitting the ATS boards. You can re-run `notify.py` against a frozen scored set to test formatting without re-spending LLM tokens.
2. **GitHub Actions step boundaries are observable.** Each script becomes a step with its own logs, exit code, and timing. Failures land on the right step in the GitHub UI rather than buried in a 200-line single-step output.

The artifacts directory is gitignored — only `jobs_seen.json` (the dedup state) is committed back.

## Differences vs. Orchestration A (n8n)

| | n8n (A) | GitHub Actions (B) |
|---|---|---|
| Host | Your laptop (Docker Desktop) | GitHub-hosted runner |
| Compute cost | Local CPU | 150 min/mo of free Actions minutes (out of unlimited for public repo) |
| Trigger reliability | Mac must be awake | Always on |
| Dedup storage | n8n's workflow static data (per-workflow KV in SQLite) | `jobs_seen.json` committed to the repo |
| Editing the pipeline | Click around the n8n canvas | Edit Python + push |
| Editing configs | Same files (`config/*.json`, `resumes/*.txt`) | Same files |
| Debuggability | n8n Executions panel | GitHub Actions logs per step |
| Portfolio fit | Demonstrates visual workflow tools | Demonstrates Python + CI + secrets management |

Both orchestrations can run side by side — same Groq key, same Telegram bot — but it's cleaner to disable one once the other is solid. The n8n side ships with a single toggle (Inactive/Active in the workflow header); the Actions side ships via this `daily.yml` schedule.
