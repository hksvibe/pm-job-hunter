"""Pre-rank scraped jobs, score the top-N via Groq Llama-3.3, mark scored
jobs as seen.

Why pre-rank: Groq's free tier on llama-3.3-70b-versatile is ~6000 input
tokens/minute (≈4 calls/min once you account for the ~1500-token prompt).
Scoring 94 jobs end-to-end would take ~25 min and bump into 429s repeatedly.
Cheap keyword pre-ranking lets us spend the LLM budget on the most relevant
30 instead of round-robining all 94.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date

import requests

from common import env_required, fingerprint, load_filters, log, read_artifact, write_artifact

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
PRIMARY_MODEL = "llama-3.3-70b-versatile"  # higher quality, ~6K input TPM, ~100K TPD
# Fallback used when the primary model hits its daily quota wall. Was
# llama-3.1-8b-instant, which Groq deprecated 2026-06-15 (decommission
# 2026-08-16). Migrated to Groq's recommended replacement, gpt-oss-20b,
# which is a separate quota bucket and honours response_format=json_object.
FALLBACK_MODEL = "openai/gpt-oss-20b"


# === PRE-RANKER ==============================================================
INDIA_LOC_TOKENS = (
    "bengaluru", "bangalore", "blr", "hyderabad", "hyd", "gurgaon", "gurugram",
    "noida", "delhi", "ncr", "new delhi", "mumbai", "navi mumbai", "pune",
    "chennai", "india",
)
ME_LOC_TOKENS = (
    "dubai", "uae", "united arab emirates", "abu dhabi", "sharjah",
    "riyadh", "ksa", "saudi arabia", "jeddah", "dammam", "doha", "qatar",
    "manama", "bahrain", "kuwait", "muscat", "oman", "amman", "jordan",
    "cairo", "egypt", "mena", "middle east",
)
SENIORITY_TOKENS = (
    "senior", "principal", "staff", "lead", "director", "head", "vp",
    "vice president", "group product",
)
DOWNRANK_TOKENS = (
    "intern", "internship", "graduate", "associate product manager", "apm ",
    "junior",
)


def pre_rank(job: dict, kw: list[str]) -> int:
    title = (job.get("title") or "").lower()
    jd_head = (job.get("jd") or "")[:1200].lower()
    loc = (job.get("location") or "").lower()

    score = 0
    if "product manager" in title or "product lead" in title or "product owner" in title:
        score += 30
    if any(t in title for t in SENIORITY_TOKENS):
        score += 15
    if any(t in title for t in DOWNRANK_TOKENS):
        score -= 40

    # Domain keyword overlap with the candidate's likely fit (fintech / AI).
    score += sum(3 for k in kw if k in title)
    score += sum(1 for k in kw if k in jd_head)

    # Geography preference
    if any(t in loc for t in INDIA_LOC_TOKENS):
        score += 25
    if any(t in loc for t in ME_LOC_TOKENS):
        score += 25
    if "remote" in loc and "india" in jd_head:
        score += 12
    elif "remote" in loc:
        score += 5

    return score


# === LLM SCORING =============================================================
RESUME_CHAR_CAP = 3500   # tighter cap so each call ~2350 tokens; 30 jobs/day stays
JD_CHAR_CAP = 800        # under Groq's 100K-TPD free-tier cap on llama-3.3-70b


_ACRONYMS = {"Ai": "AI", "Pm": "PM", "Bfsi": "BFSI", "Ml": "ML", "Gtm": "GTM"}


def _label(filename: str) -> str:
    """ai_first.txt → 'AI First'; digital_payments.txt → 'Digital Payments'."""
    base = filename.rsplit(".", 1)[0]
    titled = base.replace("_", " ").replace("-", " ").title()
    for wrong, right in _ACRONYMS.items():
        titled = titled.replace(f" {wrong} ", f" {right} ")
        if titled.startswith(f"{wrong} "):
            titled = right + titled[len(wrong):]
        if titled.endswith(f" {wrong}"):
            titled = titled[:-len(wrong)] + right
        if titled == wrong:
            titled = right
    return titled


def build_prompt(job: dict, resumes: dict[str, str]) -> tuple[str, str]:
    system = (
        "You score job fit. The candidate provides MULTIPLE résumé variants. "
        "Your job is to pick whichever variant fits THIS job best, score the "
        "fit against ONLY that chosen variant, and return strict JSON. "
        "No prose, no markdown, no code fences."
    )

    # Build a labelled block per résumé so the LLM can refer to them by filename
    resume_blocks = []
    for name in sorted(resumes.keys()):
        text = (resumes[name] or "")[:RESUME_CHAR_CAP]
        resume_blocks.append(f"=== RÉSUMÉ FILE: {name}  (label: {_label(name)}) ===\n{text}")
    resumes_section = "\n\n".join(resume_blocks)

    available_filenames = sorted(resumes.keys())

    user = (
        "Return ONLY this JSON object (no prose, no markdown):\n"
        '{ "score": <1-10 integer>, '
        f'"chosen_resume": <one of {json.dumps(available_filenames)}>, '
        '"verdict": "<one short sentence explaining the choice and the score>", '
        '"must_have_gaps": ["...optional list of missing skills relative to JD..."] }\n\n'
        "Scoring rubric (apply to the résumé you choose):\n"
        "- 10 = strong match on (a) role family is Product Management, (b) seniority matches the candidate (~11 yrs / Senior / Principal / Director / VP / Head level), and (c) location is India, Middle East, or India-friendly remote.\n"
        "- Penalise heavily if the role is NOT product management (engineering, marketing, ops, design, pure data/analytics, customer success, sales).\n"
        "- Penalise if seniority is far below the candidate (e.g. APM, junior PM, intern).\n"
        "- Penalise if location is remote but the JD region-locks it outside India/GCC.\n"
        "- DOMAIN: The candidate has direct experience in fintech/payments/BFSI/banking AND AI/ML/conversational AI/GraphRAG/LLM. Reward exact domain matches there strongly. BUT do NOT penalise non-fintech/non-AI roles when the candidate's senior-product-leader background transfers cleanly — these are equally fair game:\n"
        "    • consumer products & marketplaces (e-commerce, retail, q-commerce, foodtech)\n"
        "    • mobility / logistics / supply chain / last-mile\n"
        "    • travel & hospitality\n"
        "    • B2B SaaS, developer tools, enterprise platforms\n"
        "    • edtech, healthtech\n"
        "    • media, gaming, content, social, ads\n"
        "    • proptech / real estate\n"
        "  Score these on role + seniority + location fit; treat domain as a tiebreaker rather than a hard gate.\n"
        "- Pick the résumé that best matches the role: digital_payments.txt for fintech/payments/BFSI/lending/banking jobs, ai_first.txt for AI/ML/LLM/data/conversational AI jobs OR any general consumer/SaaS/marketplace PM role where the candidate's AI-first product leadership is the strongest framing.\n\n"
        f"{resumes_section}\n\n"
        f"=== JOB ===\n"
        f"Title: {job['title']}\n"
        f"Company: {job['company']}\n"
        f"Location: {job['location']}\n"
        f"JD:\n{(job.get('jd') or '')[:JD_CHAR_CAP]}"
    )
    return system, user


TPD_BAIL_THRESHOLD_SECONDS = 60  # if Groq's retry-after exceeds this we're in
                                  # TPD/RPD-limit territory, not TPM-burst; on
                                  # the primary model we try the fallback model;
                                  # on the fallback we give up and persist what
                                  # was scored so far.


def _call_model(
    model: str,
    job: dict,
    resumes: dict[str, str],
    api_key: str,
    session: requests.Session,
) -> dict:
    """Score one job against `model`. Returns a result dict; sets _tpd_hit=True
    when the model's daily quota wall is reached."""
    system, user = build_prompt(job, resumes)
    is_reasoning = model.startswith("openai/gpt-oss")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        # gpt-oss is a reasoning model: it spends tokens on a hidden reasoning
        # pass before the answer, and those count against max_tokens. Give it
        # extra headroom and dial reasoning down so the JSON answer never gets
        # truncated. llama-3.3-70b doesn't reason, so 256 is plenty there.
        "max_tokens": 1024 if is_reasoning else 256,
        "response_format": {"type": "json_object"},
    }
    if is_reasoning:
        body["reasoning_effort"] = "low"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    MAX_ATTEMPTS = 4
    for attempt in range(MAX_ATTEMPTS):
        try:
            r = session.post(GROQ_URL, headers=headers, json=body, timeout=60)
            if r.status_code == 429:
                wait = float(r.headers.get("retry-after", "5"))
                if wait > TPD_BAIL_THRESHOLD_SECONDS:
                    log(f"  429 on {model} with retry-after {wait:.0f}s ⇒ TPD/RPD wall")
                    return {"score": 0, "verdict": f"skipped: {model} TPD/RPD wall", "chosen_resume": "", "_tpd_hit": True}
                wait = max(wait, 2 ** (attempt + 1))
                if attempt < MAX_ATTEMPTS - 1:
                    log(f"  429 on {model} — sleeping {wait:.1f}s (attempt {attempt + 1}/{MAX_ATTEMPTS})")
                    time.sleep(wait)
                    continue
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            parsed = parse_score(text, resumes)
            parsed["model_used"] = model
            return parsed
        except requests.HTTPError as e:
            if attempt < MAX_ATTEMPTS - 1:
                backoff = 2 ** (attempt + 1)
                log(f"  {model} HTTP error, retrying in {backoff}s: {e}")
                time.sleep(backoff)
                continue
            log(f"  {model} scoring failed {job['id']}: {e}")
            return {"score": 0, "verdict": f"score error: {e}", "chosen_resume": "", "model_used": model}
        except Exception as e:
            log(f"  {model} scoring failed {job['id']}: {e}")
            return {"score": 0, "verdict": f"score error: {e}", "chosen_resume": "", "model_used": model}
    return {"score": 0, "verdict": "score error: retries exhausted", "chosen_resume": "", "model_used": model}


def score_one(job: dict, resumes: dict[str, str], api_key: str, session: requests.Session) -> dict:
    """Try the primary 70B model; on a TPD wall, fall back to the gpt-oss-20b
    model (which has its own quota bucket). Only when *both* hit TPD do we
    surface the _tpd_hit flag to the main loop."""
    result = _call_model(PRIMARY_MODEL, job, resumes, api_key, session)
    if not result.get("_tpd_hit"):
        return result

    log(f"  ↪ falling back to {FALLBACK_MODEL}")
    result = _call_model(FALLBACK_MODEL, job, resumes, api_key, session)
    # If both walls are up, surface the bail signal — match.main() stops iterating.
    return result


def parse_score(s: str, resumes: dict[str, str]) -> dict:
    available = set(resumes.keys())
    fallback_resume = next(iter(sorted(available)), "")

    if not s:
        return {"score": 0, "verdict": "empty response", "chosen_resume": fallback_resume}

    cleaned = s.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]

    try:
        obj = json.loads(cleaned)
        chosen = str(obj.get("chosen_resume") or "")
        if chosen not in available:
            # LLM hallucinated a filename or returned a label — try to match it
            chosen_l = chosen.lower().replace(" ", "_").replace("-", "_")
            chosen = next((r for r in available if chosen_l in r.lower() or r.lower().rstrip(".txt") in chosen_l), fallback_resume)
        return {
            "score": int(obj.get("score", 0) or 0),
            "verdict": str(obj.get("verdict") or ""),
            "chosen_resume": chosen,
        }
    except Exception:
        m_score = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', s)
        m_verd = re.search(r'"verdict"\s*:\s*"([^"]*)"', s)
        m_resume = re.search(r'"chosen_resume"\s*:\s*"([^"]*)"', s)
        if m_score:
            chosen = m_resume.group(1) if m_resume else fallback_resume
            if chosen not in available:
                chosen = fallback_resume
            return {
                "score": int(float(m_score.group(1))),
                "verdict": m_verd.group(1) if m_verd else "",
                "chosen_resume": chosen,
            }
        return {"score": 0, "verdict": f"parse failed; raw[0..120]={s[:120]!r}", "chosen_resume": fallback_resume}


# === MAIN ====================================================================
def main() -> int:
    api_key = env_required("GROQ_API_KEY")
    scrape = json.loads(read_artifact("scrape_output.json"))
    jobs = scrape.get("jobs") or []
    resumes = scrape.get("resumes") or {}
    seen = scrape.get("seen") or {}
    filters = load_filters()

    # Check no-jobs first — a fresh "nothing new today" run is a normal,
    # successful outcome. Only complain about missing résumés when we'd
    # actually need them to score something.
    if not jobs:
        log("no jobs to score; passing through empty list")
        write_artifact(
            "match_output.json",
            json.dumps({"scored": [], "seen": seen, "board_summary": scrape.get("board_summary", [])}),
        )
        return 0

    if not resumes:
        log("FATAL: jobs to score but no résumés in scrape artifact — check the resume-inject step")
        return 2

    # === Pre-rank ===
    keywords = [k.lower() for k in filters.get("_pre_rank_keywords", [])]
    for j in jobs:
        j["_pre_score"] = pre_rank(j, keywords)
    jobs.sort(key=lambda j: -j["_pre_score"])

    cap = int(filters.get("max_jobs_to_score", 30))
    to_score = jobs[:cap]
    dropped = jobs[cap:]
    log(f"{len(jobs)} candidates → top {len(to_score)} pre-ranked for LLM "
        f"(pre_score range {to_score[-1]['_pre_score']}–{to_score[0]['_pre_score']}); "
        f"{len(dropped)} dropped (will retry tomorrow)")
    log(f"scoring against {len(resumes)} résumé variant(s): {sorted(resumes.keys())}")

    # === LLM scoring with pacing ===
    pace = float(filters.get("llm_pace_seconds", 16))
    session = requests.Session()
    today_iso = date.today().isoformat()
    scored: list[dict] = []
    log(f"scoring {len(to_score)} jobs; primary={PRIMARY_MODEL}, fallback={FALLBACK_MODEL}; pacing {pace}s between calls")
    bailed_early = False
    for i, j in enumerate(to_score, start=1):
        result = score_one(j, resumes, api_key, session)
        if result.get("_tpd_hit"):
            # Groq daily quota wall. Don't mark this job as seen (so it gets
            # re-scored tomorrow), don't include it in the digest, and stop
            # iterating — every subsequent call would also 429.
            log(f"  ⛔ bailing at job {i}/{len(to_score)} with {len(scored)} jobs already scored; "
                f"{len(to_score) - i + 1} will roll over to tomorrow")
            bailed_early = True
            break
        j_out = {k: v for k, v in j.items() if k not in {"_pre_score"}}
        j_out["score"] = result["score"]
        j_out["verdict"] = result["verdict"]
        j_out["chosen_resume"] = result["chosen_resume"]
        j_out["model_used"] = result.get("model_used", PRIMARY_MODEL)
        scored.append(j_out)
        # Mark as seen ONLY after a successful scoring attempt. Jobs that got
        # the _tpd_hit sentinel above stay unseen so tomorrow's run picks them
        # up automatically. We record the fingerprint too so a future repost
        # under a fresh ATS URL (different ID, same company+title) is caught
        # by scrape.py's two-level dedup.
        seen[j["id"]] = {
            "date": today_iso,
            "fp": fingerprint(j["company"], j["title"]),
        }
        resume_short = _label(result["chosen_resume"]) if result["chosen_resume"] else "—"
        model_tag = "20B" if result.get("model_used") == FALLBACK_MODEL else "70B"
        log(f"  [{i:2d}/{len(to_score)}] {j['company']:14s} {j['title'][:42]:42s} → {result['score']}/10  [{resume_short}, {model_tag}]")
        if i < len(to_score):
            time.sleep(pace)

    write_artifact(
        "match_output.json",
        json.dumps(
            {
                "scored": scored,
                "seen": seen,
                "board_summary": scrape.get("board_summary", []),
                "candidates_considered": len(jobs),
                "candidates_scored": len(scored),
                "candidates_pre_ranked": len(to_score),
                "candidates_dropped_by_pre_rank": len(dropped),
                "bailed_early_on_tpd": bailed_early,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
