# PM Job Hunter — Zero-Cost AI-Scored Daily Job Feed

> An end-to-end agentic workflow that scrapes Product Manager openings across India and the Middle East every morning, scores each one against my résumé using a 70B-parameter LLM, and delivers the shortlist to my phone — for ₹0/month.

**Status:** Production. Running daily since May 2026.
**Pipeline cost:** ₹0/month (every component on a free tier with ≥10× headroom).
**Engineering time:** ~6 hours from blank directory to first scheduled run.

---

## 1. The problem

Searching for a senior Product Manager role in fintech / AI-first products means watching ~20 different career pages, each updating at irregular hours. ATS-driven boards (Greenhouse, Lever) post jobs at midnight in three timezones; LinkedIn's algorithm is noisy; Naukri buries fresh listings under sponsored slots. A typical day spent "checking job boards" yields 3–5 actually-relevant openings, after 45–60 minutes of manual scanning.

I wanted to compress that to **a single Telegram digest, every morning at 8 AM IST**, containing only roles that meaningfully match my background.

## 2. The solution at a glance

```
┌──────────┐   ┌──────────────────┐   ┌────────────┐   ┌──────────────┐   ┌─────────────┐   ┌──────────┐
│  Daily   │ → │ Fetch 42 ATS     │ → │ Pre-rank   │ → │ LLM-score    │ → │ Threshold   │ → │ Push     │
│  8 AM    │   │ boards (GH+Lever │   │ by keyword │   │ top 30 vs.   │   │ ≥ 7 +       │   │ digest   │
│  cron    │   │ + Ashby) in      │   │ heuristic; │   │ resume using │   │ chunked     │   │ to phone │
│          │   │ parallel; filter │   │ cap at N   │   │ Llama-3.3-70B│   │ messages    │   │          │
│          │   │ + dedup          │   │            │   │              │   │             │   │          │
└──────────┘   └──────────────────┘   └────────────┘   └──────────────┘   └─────────────┘   └──────────┘
```

- **Sources:** 42 ATS endpoints across **Greenhouse, Lever, and Ashby** — Indian fintechs (PhonePe, Paytm, CRED, Slice, Groww, Meesho, FamPay, InMobi, Glance, Postman, Navi, Leap, …), Middle East fintechs (Careem, Tamara, PayIt, Hala, Rain, Lean Technologies), and global PM-heavy companies (Stripe, Adyen, Anthropic, OpenAI, Snowflake, Databricks, Figma, Notion, Cohere, Plaid, Scale AI, …). Extensible via [`config/sources.json`](../config/sources.json) — adding a new board takes one curl probe and one JSON entry.
- **Pre-rank:** ~5,500 raw jobs → ~95 PM-titled jobs in target geographies. A cheap keyword heuristic (title quality + seniority + fintech/AI domain overlap + India/ME geo bonus) ranks them; only the top 30 are sent to the LLM. Knobs (`max_jobs_to_score`, `llm_pace_seconds`, keyword list) live in [`config/filters.json`](../config/filters.json).
- **Scoring:** Each surviving job is paired with the most relevant résumé variant (AI-first or Digital Payments) and sent to **Groq's Llama-3.3-70B-Versatile** with a structured prompt. The model returns JSON `{score: 1–10, verdict, must_have_gaps}`. Calls are paced at 16s to stay under Groq's free-tier ~6,000-token-per-minute input cap, with exponential backoff on the rare 429.
- **Delivery:** Jobs with `score ≥ 7` are formatted into a digest and pushed via the Telegram Bot API. Long digests are auto-chunked under the 4,096-character message limit.
- **Dedup:** Each scored job's stable ID is recorded after successful delivery; tomorrow's run skips anything already sent. Jobs dropped by the pre-ranker stay unseen so they're re-considered the next day.

## 3. Architecture & tech stack

| Layer | Tool | Why it was chosen | Cost |
|---|---|---|---|
| **Orchestrator** | n8n 2.20 (self-hosted via Docker) | Visual workflow editor with full Node.js access in Code nodes; runs locally; persistent volume keeps state across restarts | ₹0 (open-source) |
| **Job sources** | Greenhouse + Lever + Ashby public ATS APIs (42 boards) | Official JSON endpoints, no scraping, no rate-limiting, no auth required. Discovery script (`probe_ats.py`) probes ~180 candidate slugs in parallel to find new boards. | ₹0 |
| **LLM scoring** | **Groq Llama-3.3-70B-Versatile** | Fast (~500 ms/call), generous free tier (~30 req/min, 14,400 req/day), OpenAI-compatible API | ₹0 (free tier) |
| **Delivery** | **Telegram Bot API** via `@BotFather` | Free, instant, reliable, official API, no flakiness; push notification on phone | ₹0 |
| **Container runtime** | Docker Desktop (macOS) | Standard, low-overhead local hosting | ₹0 |
| **PDF → text** | `pdfplumber` (Python) | Reliable on multi-column résumé layouts | ₹0 (open-source) |
| **HTTP transport** | Node.js built-in `https` module | Required because n8n's task-runner sandbox in v2.x strips global `fetch()` | ₹0 |
| **Dedup storage** | n8n workflow static data (`$getWorkflowStaticData('global')`) | Built-in persistent KV store scoped per workflow, no external DB needed | ₹0 |

### Cost proof (daily)

| Resource | Free-tier limit | Actual daily usage | Headroom |
|---|---|---|---|
| GitHub Actions (public repo) | unlimited | ~9 min/day | ∞ |
| n8n self-hosted (local) | unlimited | 1 scheduled run | ∞ |
| Groq API calls (Llama-3.3-70B) | 14,400 req/day, 6,000 tokens/min | up to 30 scored calls/day | 480× on req/day |
| Telegram messages | unlimited (personal use) | 0–3 messages | ∞ |
| ATS JSON endpoints | unlimited | 42 parallel requests, daily | ∞ |
| **Total** | — | — | **₹0/month indefinitely** |

## 4. Configuration model

Everything tunable is split out of code into version-controlled JSON. No restart needed for config changes — the workflow re-reads `/data` on every run.

### `config/sources.json` — ATS boards to fetch

```json
{
  "boards": [
    { "company": "Tamara",  "region": "Middle East", "board_type": "greenhouse",
      "slug": "tamara",  "fetch_url": "https://boards-api.greenhouse.io/v1/boards/tamara/jobs?content=true" },
    { "company": "Paytm",   "region": "India",       "board_type": "lever",
      "slug": "paytm",   "fetch_url": "https://api.lever.co/v0/postings/paytm?mode=json" }
    // ...
  ]
}
```

Adding a new board takes one curl probe and one JSON entry.

### `config/filters.json` — what counts as a "PM job in my geography"

```json
{
  "title_include": ["product manager", "senior product manager", "ai product manager", "director of product", ...],
  "title_exclude": ["intern", "associate product manager", "marketing manager", "program manager", ...],
  "allowed_locations": {
    "india":       ["bengaluru", "hyderabad", "gurgaon", "mumbai", "noida", ...],
    "middle_east": ["dubai", "abu dhabi", "riyadh", "jeddah", "doha", "manama", "kuwait", ...],
    "remote_friendly": ["remote", "anywhere", "fully remote", ...]
  },
  "remote_exclude_patterns": ["us only", "eu only", "canada only", ...],
  "min_llm_score": 7
}
```

### `config/resume_routing.json` — which résumé scores which type of job

```json
{
  "default_resume": "april_2026.txt",
  "rules": [
    {
      "name": "Payments / fintech → DigitalPayments resume",
      "use_resume": "digital_payments.txt",
      "match_any": ["payment", "upi", "lending", "bnpl", "kyc", "banking", ...]
    },
    {
      "name": "AI/LLM/GenAI → April 2026 (AI-first) resume",
      "use_resume": "april_2026.txt",
      "match_any": ["ai ", "llm", "genai", "rag", "conversational", "agent", ...]
    }
  ]
}
```

First-match-wins routing means an "AI Product Manager — Payments" job at a fintech automatically gets scored against the more relevant Digital Payments résumé instead of the generic one. Higher signal score.

### Résumé corpus

Two résumé variants kept in `resumes/`, parsed once from PDF via a one-line script:

```bash
python3 scripts/parse_resume.py /path/to/new.pdf resumes/april_2026.txt
```

## 5. The LLM scoring prompt

The prompt is built per-job at runtime, with the routed résumé text concatenated in. Llama-3.3 is told **exactly** what to return:

```
SYSTEM: You score job fit and return ONLY a JSON object. No prose, no markdown,
        no code fences.

USER:   Scoring rubric (return JSON: {"score": <1-10>, "verdict": "<one sentence>",
        "must_have_gaps": ["..."]}):
        - 10 = strong match on role (Product Management), seniority, domain, AND
          location (India / Middle East / India-friendly remote).
        - Penalise heavily if the role is non-PM (engineering, marketing, ops,
          design, data) or seniority is far below the candidate.
        - Penalise if location is remote but region-locked outside India/GCC.
        - Reward domain overlap (fintech, payments, BFSI, AI/ML, conversational
          AI, KYC/KYB).

        RESUME:
        {resume_text}

        JOB:
        Title: {title}
        Company: {company}
        Location: {location}
        JD: {jd_text[:3000]}
```

Two reliability tricks built into the call:
- `response_format: {type: "json_object"}` — Groq's OpenAI-compatible API forces strict JSON output, eliminating prose hallucinations.
- `temperature: 0.2` — deterministic-ish scores; running the same job twice yields the same number.

A tolerant parser handles edge cases anyway: strips markdown fences, regex-extracts `"score"` if JSON.parse fails, and exposes the raw response in the verdict field on full failure (so debugging happens through the Telegram digest itself).

## 6. The pipeline, node by node

The n8n workflow is **7 nodes** wired linearly:

```
[Cron trigger]
    │
    ▼
[Fetch + normalize + filter + dedup + route]   ← all in one Code node
    │ • Reads config + résumés from /data volume
    │ • Fetches 42 ATS boards in parallel (Promise.all + Node https module)
    │ • Normalizes Greenhouse / Lever / Ashby shapes into a common job schema
    │ • Title and location filters
    │ • Dedups against persistent workflow state
    │ • Routes each job to the most relevant résumé
    │
    ▼
[Pre-rank + cap to top N]
    │ • Cheap keyword scoring: title quality, seniority, domain overlap, geo
    │ • Sorts descending; keeps top 30 (configurable in filters.json)
    │ • Drops the rest — they'll be re-considered tomorrow
    │
    ▼
[Build LLM prompts]   ← one prompt per surviving job
    │
    ▼
[Score (Groq Llama 3.3)]   ← serial HTTP POSTs; 16s pacing under TPM cap
    │
    ▼
[Score → filter → format]
    │ • Parses each response, drops scores < threshold
    │ • Chunks digest into ≤3,500-char messages (Telegram's 4,096-char limit)
    │ • Emits one item per chunk
    │
    ▼
[IF: anything to send?]   ← skips Telegram send on zero-match days
    │
    ▼
[Send Telegram]   ← one HTTP POST per chunk
```

Why one Code node for fetch+normalize+filter+dedup+route instead of separate HTTP Request nodes? **A subtle n8n bug**: its HTTP Request node auto-splits top-level JSON arrays into individual items, which broke index-based pairing across nodes (Lever returns `[{job}, {job}, ...]` while Greenhouse returns `{jobs: [...]}`). Consolidating into a single Code node that does its own HTTP via `require('https')` sidesteps the problem completely and is also faster.

## 7. Reliability features

These weren't in the original plan but emerged from production debugging:

- **Tolerant LLM parser:** strips ```` ```json ```` code fences, falls back to regex on `JSON.parse` failure, and embeds the raw response in the digest verdict line so misformatted answers are visible without checking logs.
- **Two-tier zero-handling:** if zero jobs pass *filter*, the Code node throws with full diagnostics (which boards succeeded, what counts, etc.) so a broken source is loudly visible. If zero jobs pass *after dedup* (normal day where nothing new was posted), the workflow silently no-ops — no spam, no false alarms.
- **Message chunking:** the Telegram API caps individual messages at 4,096 characters. A 30-job digest easily exceeds that. The formatter packs job blocks into chunks of ≤3,500 chars, emits one message per chunk, and labels them "part 1/N" so they read in order.
- **Per-job verdict cap:** each verdict line is capped at 180 chars so a single chatty LLM response can't break message budgeting for the rest of the digest.
- **Resilient HTTP transport:** Node.js built-in `https` module wrapped in a `Promise.all`, with timeouts, redirect-following, and per-board error capture. One failing board doesn't take down the run.
- **Pre-ranker as rate-limit defense:** the keyword pre-ranker isn't just optimization — it's the only thing that makes the pipeline viable on Groq's free tier. Without it, scoring ~95 PM jobs/day at ~1,500 input tokens/call would saturate the 6,000-tokens-per-minute cap. With it, the LLM only sees the top 30, and the 16-second pacing comfortably stays under all per-minute limits with zero 429s in production.
- **Dedup respects scoring success:** marking a job as "seen" only happens after the LLM has actually scored it. Jobs the pre-ranker drops stay unseen so they get re-evaluated tomorrow if today's higher-ranked jobs are delivered. This means the pre-ranker reduces *cost* without reducing *coverage* — every PM job in target geography eventually gets its turn at the LLM.

## 8. Engineering decisions worth highlighting

A few non-obvious calls that shaped the final design:

| Decision | Why |
|---|---|
| **Two résumé variants, routed by keyword** | Llama-3.3 scores 7 vs 9 depending on whether the résumé it's matched against highlights fintech or AI. First-match keyword routing gives ~30% lift on score quality compared to a single generic résumé. |
| **Greenhouse/Lever first, scraping later** | Official ATS JSON APIs are free, structured, unlimited, and never block. Scraping LinkedIn/Naukri can come later, gated on the core loop being solid. |
| **Threshold = 7 (not 5 or 8)** | At 5, digest had too many ops/marketing roles slipping through. At 8, even strong matches got rejected for tiny résumé gaps. 7 surfaces 1–4 jobs/day on average — the sweet spot for daily attention. |
| **In-process Code node (no microservices)** | The whole pipeline fits in one Docker container running n8n. No FastAPI, no queue, no DB. Lower complexity, lower latency, fewer failure modes. |
| **Configs and résumés mounted read-only from host** | Workflow JSON contains no secrets and no résumé content. Configs can be edited in your favorite editor without touching n8n's UI. |
| **Groq over Gemini** | Gemini's free tier was unreliable (model retirement + project-level `limit:0` errors). Groq's free tier is generous, fast, and uses the OpenAI-compatible API that most LLM clients already speak. |
| **Cheap pre-ranker over more LLM calls** | Could have just paid for higher Groq throughput or sharded calls across multiple API keys. Instead a 30-line keyword pre-ranker filters ~95 → ~30 most-likely-relevant jobs, keeping the pipeline ₹0/month and the daily digest's LLM time bounded. Picks are visible in `match_output.json` artifact for tuning. |
| **Discovery via probe script, not curation** | Rather than hand-curate companies, `probe_ats.py` parallel-probes ~180 candidate slugs across 4 ATS providers and prints which respond. Adding a new geography (Latin America? Europe?) is a config change, not a code change. |

## 9. Repository layout

The repo carries **both orchestrations** side-by-side, sharing configs and résumé state. Pick the one that fits your deployment model.

```
PM Job Scrapper/
├── README.md                       ← setup walkthrough (for re-deploying)
├── docs/
│   └── PORTFOLIO.md                ← this document
│
├── n8n/                            ← Orchestration A: laptop-hosted (Docker)
│   ├── workflow.json               ← the 7-node n8n pipeline
│   ├── docker-compose.yml          ← container config with env mounts
│   └── .env.example                ← local secrets template
│
├── github_actions/                 ← Orchestration B: cloud-hosted (Actions)
│   ├── README.md
│   ├── requirements.txt            ← single dep: requests
│   ├── common.py                   ← config/artifact helpers
│   ├── scrape.py                   ← stage 1: fetch + filter + dedup
│   ├── match.py                    ← stage 2: pre-rank + LLM score
│   └── notify.py                   ← stage 3: format + chunk + send Telegram
│
├── .github/workflows/
│   └── daily.yml                   ← cron at 02:30 UTC = 8 AM IST
│
├── config/                         ← shared by both orchestrations
│   ├── sources.json                ← 42 ATS boards (GH + Lever + Ashby)
│   ├── filters.json                ← titles / locations / threshold / pacing
│   └── resume_routing.json         ← résumé→job-type mapping
│
├── resumes/                        ← gitignored; injected via repo secrets in CI
│   ├── april_2026.txt              ← AI-first résumé (default)
│   └── digital_payments.txt        ← fintech-tailored résumé
│
├── scripts/
│   ├── parse_resume.py             ← one-shot PDF → text converter
│   └── probe_ats.py                ← discovery: probe many slugs to find live ATS boards
│
├── jobs_seen.json                  ← dedup state — committed back by the cron each run
└── .gitignore
```

## 10. Sample output

A real digest from a recent run, sanitized:

```
🎯 PM Jobs — 19 May 2026
3 matches (score ≥ 7)

1. Senior Product Manager - Banking Product — Tamara (Riyadh) ★ 9/10
   Strong fintech + product leadership overlap; banking domain matches resume.
   → https://job-boards.eu.greenhouse.io/tamara/jobs/4852757101

2. Senior Product Manager — PhonePe (Bengaluru) ★ 8/10
   PhonePe payments product role fits 11+ yrs fintech PM background.
   → https://job-boards.greenhouse.io/phonepe/jobs/7662554003

3. Senior Product Manager - Lending Platform — Paytm (Noida) ★ 7/10
   Lending PM role matches fintech experience; remote India location fits.
   → https://jobs.lever.co/paytm/75992181-c0d0-44e7-805a-6dddfd0fe23b

Sent by your job bot 🤖
```

## 11. What I learned

A few things I didn't expect going in:

- **LLM-as-a-filter beats keyword filtering** at the long-tail. A keyword filter catches "Product Manager" titles, but it can't tell apart a marketing-PM-with-product-in-the-title from a real product role. The LLM verdict line surfaces *why* a 4/10 score is a 4, which makes filter tuning much easier than reading raw JDs.
- **But cheap keyword pre-ranking beats LLM at scale.** Once the source list grew from 8 to 42 boards, the LLM was the bottleneck (free-tier TPM caps). A 30-line keyword scorer that runs in microseconds picks the top 30 candidates, and the LLM only refines the close calls. Same digest quality, 3× the source coverage, ₹0 still.
- **n8n is great as a prototyping layer, less so as a production target.** The visual canvas accelerates the first 80% of the build. The last 20% (sandbox quirks, env-var gating, env-specific globals like `fetch`, message-chunking edge cases) ended up being trial-and-error.
- **Free tiers degrade silently.** Gemini 1.5 Flash silently got retired from `v1beta`. Gemini 2.0 Flash arrived but with `limit:0` for new projects. The swap to Groq took 20 minutes once I realized "free" doesn't mean "stable."
- **Dedup state belongs at the end, not the middle.** My first dedup-too-early bug marked jobs as "seen" before they were delivered — meaning every test run poisoned the seen list. Moving the dedup mark to *after* successful LLM scoring (or *after* successful Telegram delivery for the cloud version) eliminated the recurring "why is my workflow throwing today?" issue. The pre-ranker's "drop ≠ seen" rule is the same idea: only mark seen what you actually processed.
- **Discovery is leverage.** Hand-curating "20 fintechs I care about" takes an hour. Writing a 50-line probe script that hits ~180 slugs across 4 ATS providers and reports which are live takes the same hour, but now adding 50 more companies to evaluate is a one-line list edit. The probe script is committed as a tool, not as throwaway code.

## 12. What's next

- ✅ ~~Orchestration B — port to GitHub Actions + Python.~~ (Done — live in [`github_actions/`](../github_actions) running daily.)
- ✅ ~~Expand Middle East coverage.~~ (Hala, Rain, Lean Technologies added on Ashby; Careem/Tamara/PayIt already on Greenhouse. Still to discover: Tabby, Noon, STC Pay, Wio Bank — all on non-standard ATS systems.)
- **More ATS providers** — SmartRecruiters, Workday, SuccessFactors normalizers would unlock another wave of large enterprise hirers (Razorpay, Swiggy, Zomato, Flipkart, the GCC banks).
- **LinkedIn fallback** — guest-view scraping for boards not on a standard ATS. Lower priority since ATS coverage already captures most of what's worth seeing.
- **Weekly recap mode** — Sunday email with the week's top-scoring jobs even if they were already in daily digests, as a re-surface for ones I didn't action.
- **Calibration loop** — after a few weeks of digests, look at which jobs I actually applied to vs. which I skipped despite high scores. Feed that back as few-shot examples in the scoring prompt to drive the rubric toward what I actually find interesting.

---

**Stack TL;DR:** Docker → n8n → Node.js → Groq Llama-3.3-70B → Telegram, glued with JSON configs. Costs nothing, runs daily, surfaces 1–4 relevant Product Manager openings every morning across India and the Middle East.
