# PM Job Hunter — India + Middle East

Daily, free, automated Product Manager job feed delivered to your own Telegram.

- Scrapes PM openings from official ATS boards (Greenhouse, Lever) across India and the Middle East
- Filters to PM roles in Bengaluru, Hyderabad, NCR, Mumbai, Pune + Dubai, Abu Dhabi, Riyadh, Jeddah, Doha, Manama, Kuwait + India-friendly remote
- Routes each job to the most relevant resume (Digital Payments resume for fintech roles, AI-first resume for AI/LLM roles)
- Scores each job 1–10 against your resume via Gemini 1.5 Flash (free tier)
- Sends the shortlist (score ≥ 7) to your Telegram chat at 8:00 AM IST every day
- Dedupes across runs so you don't see the same job twice
- Cost: **₹0/month**

This is **Orchestration A** (n8n visual workflow). A Python/GitHub Actions version (Orchestration B) can be built on top of the same configs later.

---

## Project layout

```
PM Job Scrapper/
├── README.md                 ← you are here
├── n8n/
│   ├── workflow.json         ← import this into n8n
│   ├── docker-compose.yml    ← runs n8n locally with the right mounts
│   └── .env.example          ← copy → .env, fill in API keys
├── resumes/
│   ├── april_2026.txt        ← AI-first resume (default)
│   └── digital_payments.txt  ← fintech/payments tailored
├── config/
│   ├── sources.json          ← ATS boards to fetch from
│   ├── filters.json          ← title/location/keyword rules
│   └── resume_routing.json   ← which resume to score against per job
└── scripts/
    └── parse_resume.py       ← re-run when a resume PDF changes
```

---

## One-time setup (~30 min)

### 1. Install Docker Desktop (10 min)

Required to run n8n locally.

1. Download from https://www.docker.com/products/docker-desktop/ (pick Apple Silicon or Intel based on your Mac).
2. Open the `.dmg`, drag Docker to Applications, launch it.
3. Wait for the whale icon in the menu bar to stop animating.
4. Verify:
   ```bash
   docker --version
   docker compose version
   ```

### 2. Get a Groq API key (free, 2 min)

1. Go to https://console.groq.com/keys
2. Sign in with Google or GitHub → **Create API Key** → copy the key (starts with `gsk_...`)
3. Free tier: ~30 req/min, ~14,400 req/day on `llama-3.3-70b-versatile` — well within our 8-board run.

(Originally the plan suggested Gemini 1.5 Flash, but Google's free tier on that model is unreliable. Groq's free tier is rock-solid and the OpenAI-compatible API drops in cleanly.)

### 3. Create a Telegram bot (2 min)

We use Telegram instead of WhatsApp/CallMeBot — it's more reliable, instant, and free.

1. On Telegram (mobile or desktop), search for **@BotFather** → open chat → tap **Start**.
2. Send `/newbot`.
3. BotFather asks for a **name** — anything, e.g. `PM Job Hunter`.
4. BotFather asks for a **username** — must end in `bot`, e.g. `pm_job_hunter_bot`. Pick something unique.
5. BotFather replies with your token, looks like `123456789:ABCdef-ghIJKlmNOPqrSTU_vwxyzABCDEFG`. Copy it — that's your `TELEGRAM_BOT_TOKEN`.
6. Tap the link BotFather gave you (or search for your bot's username), open the chat with your bot, tap **Start**, and send any message (e.g. `hi`).
7. In a browser, open (replace `<TOKEN>` with your token):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   You'll see JSON. Find the part that looks like `"chat":{"id":123456789,…}`. The number is your `TELEGRAM_CHAT_ID`.

### 4. Fill in `.env`

```bash
cd "/Users/harshmacminim4/PM Job Scrapper/n8n"
cp .env.example .env
open -e .env     # or use your editor
```

Fill in `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and save.

### 5. Start n8n

```bash
cd "/Users/harshmacminim4/PM Job Scrapper/n8n"
docker compose up -d
```

First boot pulls the n8n image (~200 MB) and takes ~1 min.

Open http://localhost:5678 in a browser. Create the owner account (local-only — credentials never leave your laptop).

### 6. Import the workflow

1. In the n8n UI, top right → **Workflows** → **Import from File**.
2. Pick `n8n/workflow.json`.
3. After import, click each red-bordered node (if any) and verify environment variable references show resolved values — they should, because Docker Compose injected them.

### 7. Test the workflow once

1. Open the imported workflow → click **Execute workflow** in the toolbar.
2. Watch nodes turn green left-to-right.
3. If everything works, you'll get a Telegram message from your bot within seconds.
4. If `Anything to send?` goes down the false branch, no jobs cleared the score threshold today — that's fine, run it again tomorrow.

### 8. Activate the schedule

Top-right toggle on the workflow → **Active**. The Schedule trigger will now fire daily at 02:30 UTC = **8:00 AM IST**.

You can keep your Mac plugged in and let it run overnight, or change the cron to a time when the laptop is usually awake. The cron string lives in the `Daily 8 AM IST` node — `30 2 * * *` means "02:30 UTC every day."

---

## Maintenance

### Stop / start n8n

```bash
cd "/Users/harshmacminim4/PM Job Scrapper/n8n"
docker compose down       # stop
docker compose up -d      # start
docker compose logs -f n8n  # tail logs
```

### Update a resume

1. Drop the new PDF into `resumes/` (or anywhere) and re-parse:
   ```bash
   cd "/Users/harshmacminim4/PM Job Scrapper"
   python3 scripts/parse_resume.py /path/to/new.pdf resumes/april_2026.txt
   ```
2. No restart needed — the workflow re-reads the file on every run.

### Add a new ATS board

1. Find a fintech you like → open their careers page → look at the page source / network tab for the ATS.
   - If you see `boards-api.greenhouse.io/v1/boards/<slug>/jobs` → board_type = `greenhouse`
   - If you see `api.lever.co/v0/postings/<slug>` → board_type = `lever`
2. Probe it:
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" "https://boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=false"
   ```
   `200` = good.
3. Append an entry to `config/sources.json` under `boards`. No restart needed.

The `candidates_to_verify_periodically` list in `sources.json` has 15 ME + India fintechs to chase down whenever you have 10 min — most just need their ATS slug confirmed.

### Tune what gets through

- **Too noisy:** raise `min_llm_score` in `config/filters.json` (e.g. 8 instead of 7).
- **Too sparse:** add cities to `allowed_locations`, broaden `title_include`, or drop entries from `title_exclude`.
- **Wrong resume scored against a job:** add a routing rule to `config/resume_routing.json` — first match wins.

### Reset dedup memory

If you ever want to re-see jobs you've already been notified about (e.g. you swapped resumes and want a fresh round of scoring), reset the workflow's static data:

1. n8n UI → open workflow → **⋯ menu** → **Settings** → scroll to **Static data** → **Clear**.

---

## How the workflow is wired

```
Daily 8 AM IST (cron)
  ↓
Load config         ← reads /data/config/*.json and /data/resumes/*.txt
  ↓                   emits one item per source
Fetch board          ← HTTP GET per source (runs in parallel inside n8n)
  ↓
Normalize + filter + dedup + route
                     ← per board_type, extract job list, filter by title/location,
                       drop jobs already in workflow static data, pick a resume
  ↓
Build Gemini prompts ← per job, construct the resume-matching prompt
  ↓
Score (Gemini Flash) ← HTTP POST per job, free tier
  ↓
Score → filter → format
                     ← parse JSON response, keep score ≥ 7, sort desc, format msg
  ↓
Anything to send?    ← IF, skips notification when shortlist is empty
  ↓ (true)
Send Telegram
```

---

## Daily cost proof

| Item | Free-tier limit | Daily usage | Headroom |
|---|---|---|---|
| n8n self-hosted | unlimited | 1 run | ∞ |
| Gemini 1.5 Flash | 1,500 req/day | ~20–50 req | 30× |
| Telegram Bot API | unlimited (~30 msg/sec to one chat) | 1 msg | ∞ |
| Greenhouse / Lever JSON | unlimited | ~8 calls | ∞ |

Verdict: ₹0/month, sustainable indefinitely.

---

## Known caveats

- **LinkedIn / Naukri scraping is not wired up yet.** Greenhouse + Lever boards are the highest-signal-per-byte starting set. Once those feel solid, we can add LinkedIn guest-view scraping as a separate Code node.
- **The Middle East list is small on day 1** — only Careem, Tamara, and PayIt are confirmed Greenhouse boards. As you (or I, in a follow-up session) verify Tabby / Noon / Wio / STC Pay / Mashreq / Emirates NBD, add them to `sources.json`.
- **CallMeBot / WhatsApp note:** original plan was CallMeBot → WhatsApp, but their bot is flaky (often never replies with the activation API key). Swapped to Telegram, which is instant and rock-solid. If you ever want WhatsApp back, the only change is the final HTTP Request node and the env vars — everything upstream is unchanged.

---

## What's next (Orchestration B)

Once the n8n version has been running cleanly for a few days, the same configs (`sources.json`, `filters.json`, `resume_routing.json`, `resumes/*.txt`) drop straight into a GitHub Actions cron repo with three small Python scripts: `scrape.py`, `match.py`, `notify.py`. That version runs in the cloud — no Mac needed — and doubles as a resume-portfolio piece. Ping when ready.
