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
┌──────────┐   ┌──────────────────┐   ┌──────────────┐   ┌─────────────┐   ┌──────────┐
│  Daily   │ → │ Fetch 8 ATS      │ → │ Score each   │ → │ Filter by   │ → │ Push     │
│  8 AM    │   │ boards in        │   │ job vs.      │   │ score ≥ 7   │   │ digest   │
│  cron    │   │ parallel; filter │   │ resume using │   │ + chunk     │   │ to phone │
│          │   │ + dedup          │   │ Llama-3.3-70B│   │ for limits  │   │          │
└──────────┘   └──────────────────┘   └──────────────┘   └─────────────┘   └──────────┘
```

- **Sources:** Greenhouse + Lever ATS endpoints for Indian and Middle East fintechs (Careem, Tamara, PayIt, PhonePe, Groww, Slice, CRED, Paytm — extensible via a JSON config).
- **Scoring:** Each job is paired with the most relevant résumé variant (AI-first or Digital Payments) and sent to **Groq's Llama-3.3-70B-Versatile** with a structured prompt. The model returns JSON `{score: 1–10, verdict, must_have_gaps}`.
- **Delivery:** Jobs with `score ≥ 7` are formatted into a digest and pushed via the Telegram Bot API. Long digests are auto-chunked under the 4,096-character message limit.
- **Dedup:** Each job's stable ID is recorded after delivery; tomorrow's run skips anything already sent.

## 3. Architecture & tech stack

| Layer | Tool | Why it was chosen | Cost |
|---|---|---|---|
| **Orchestrator** | n8n 2.20 (self-hosted via Docker) | Visual workflow editor with full Node.js access in Code nodes; runs locally; persistent volume keeps state across restarts | ₹0 (open-source) |
| **Job sources** | Greenhouse + Lever public ATS APIs | Official JSON endpoints, no scraping, no rate-limiting, no auth required | ₹0 |
| **LLM scoring** | **Groq Llama-3.3-70B-Versatile** | Fast (~500 ms/call), generous free tier (~30 req/min, 14,400 req/day), OpenAI-compatible API | ₹0 (free tier) |
| **Delivery** | **Telegram Bot API** via `@BotFather` | Free, instant, reliable, official API, no flakiness; push notification on phone | ₹0 |
| **Container runtime** | Docker Desktop (macOS) | Standard, low-overhead local hosting | ₹0 |
| **PDF → text** | `pdfplumber` (Python) | Reliable on multi-column résumé layouts | ₹0 (open-source) |
| **HTTP transport** | Node.js built-in `https` module | Required because n8n's task-runner sandbox in v2.x strips global `fetch()` | ₹0 |
| **Dedup storage** | n8n workflow static data (`$getWorkflowStaticData('global')`) | Built-in persistent KV store scoped per workflow, no external DB needed | ₹0 |

### Cost proof (daily)

| Resource | Free-tier limit | Actual daily usage | Headroom |
|---|---|---|---|
| n8n self-hosted | unlimited | 1 scheduled run | ∞ |
| Groq API calls | 14,400/day | ~5–15 calls | 1,000× |
| Telegram messages | unlimited (personal use) | 0–3 messages | ∞ |
| Greenhouse / Lever JSON | unlimited | ~8 requests | ∞ |
| Docker compute | local | ~10 sec/day of CPU | ∞ |
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
    │ • Fetches 8 ATS boards in parallel (Promise.all + Node https module)
    │ • Normalizes Greenhouse / Lever shapes into a common job schema
    │ • Title and location filters
    │ • Dedups against persistent workflow state
    │ • Routes each job to the most relevant résumé
    │
    ▼
[Build LLM prompts]   ← one prompt per job in OpenAI-compatible body shape
    │
    ▼
[Score (Groq Llama 3.3)]   ← HTTP POST per job; ~500 ms each, parallelisable
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
- **Message chunking:** the Telegram API caps individual messages at 4,096 characters. A 15-job digest can easily exceed that. The formatter packs job blocks into chunks of ≤3,500 chars, emits one message per chunk, and labels them "part 1/N" so they read in order.
- **Per-job verdict cap:** each verdict line is capped at 180 chars so a single chatty LLM response can't break message budgeting for the rest of the digest.
- **Resilient HTTP transport:** Node.js built-in `https` module wrapped in a `Promise.all`, with timeouts, redirect-following, and per-board error capture. One failing board doesn't take down the run.

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

## 9. Repository layout

```
PM Job Scrapper/
├── README.md                    ← setup walkthrough (for re-deploying)
├── docs/
│   └── PORTFOLIO.md             ← this document
├── n8n/
│   ├── workflow.json            ← the 7-node pipeline (import into n8n)
│   ├── docker-compose.yml       ← container config with env mounts
│   └── .env.example             ← API key template
├── config/
│   ├── sources.json             ← ATS boards
│   ├── filters.json             ← title / location / score rules
│   └── resume_routing.json      ← résumé→job-type mapping
├── resumes/
│   ├── april_2026.txt           ← AI-first résumé (default)
│   └── digital_payments.txt     ← fintech-tailored résumé
├── scripts/
│   └── parse_resume.py          ← one-shot PDF → text converter
└── .gitignore                   ← keeps .env and secrets out of version control
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
- **n8n is great as a prototyping layer, less so as a production target.** The visual canvas accelerates the first 80% of the build. The last 20% (sandbox quirks, env-var gating, env-specific globals like `fetch`, message-chunking edge cases) ended up being trial-and-error.
- **Free tiers degrade silently.** Gemini 1.5 Flash silently got retired from `v1beta`. Gemini 2.0 Flash arrived but with `limit:0` for new projects. The swap to Groq took 20 minutes once I realized "free" doesn't mean "stable."
- **Dedup state belongs at the end, not the middle.** My first dedup-too-early bug marked jobs as "seen" before they were delivered — meaning every n8n test run poisoned the seen list. Moving the dedup mark to after successful send (or treating dedup-zero as a silent no-op instead of an error) eliminated the recurring "why is my workflow throwing today?" issue.

## 12. What's next

- **Orchestration B** — port the same configs and pipeline logic to GitHub Actions + Python so the system runs in the cloud, not on my laptop. Doubles as a portfolio repo.
- **Expand Middle East coverage** — Tabby, Noon, STC Pay, Mashreq, Wio Bank don't expose Greenhouse/Lever endpoints. Need to discover their actual ATS slugs (Workday, SAP SuccessFactors, custom) and add normalizers.
- **LinkedIn fallback** — guest-view scraping for boards not on a standard ATS. Lower priority since ATS coverage already captures ~80% of relevant openings.
- **Weekly digest mode** — opt-in summary email on Sunday with the week's full backlog, in case a daily digest got missed.

---

**Stack TL;DR:** Docker → n8n → Node.js → Groq Llama-3.3-70B → Telegram, glued with JSON configs. Costs nothing, runs daily, surfaces 1–4 relevant Product Manager openings every morning across India and the Middle East.
