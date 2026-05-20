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

from common import env_required, load_filters, log, read_artifact, write_artifact

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"


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


def _label(filename: str) -> str:
    """april_2026.txt → 'April 2026'; digital_payments.txt → 'Digital Payments'."""
    return filename.rsplit(".", 1)[0].replace("_", " ").title()


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
        "- 10 = strong match on role (Product Management), seniority, domain, AND location (India / Middle East / India-friendly remote).\n"
        "- Penalise heavily if the role is non-PM (engineering, marketing, ops, design, data) or if seniority is far below the candidate.\n"
        "- Penalise if location is remote but region-locked outside India/GCC.\n"
        "- Reward domain overlap (fintech, payments, BFSI, AI/ML, conversational AI, KYC/KYB).\n"
        "- Pick the résumé whose domain emphasis fits the job — e.g. payments JD → digital_payments.txt; AI/LLM JD → april_2026.txt.\n\n"
        f"{resumes_section}\n\n"
        f"=== JOB ===\n"
        f"Title: {job['title']}\n"
        f"Company: {job['company']}\n"
        f"Location: {job['location']}\n"
        f"JD:\n{(job.get('jd') or '')[:JD_CHAR_CAP]}"
    )
    return system, user


def score_one(job: dict, resumes: dict[str, str], api_key: str, session: requests.Session) -> dict:
    system, user = build_prompt(job, resumes)
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    MAX_ATTEMPTS = 4
    for attempt in range(MAX_ATTEMPTS):
        try:
            r = session.post(GROQ_URL, headers=headers, json=body, timeout=60)
            if r.status_code == 429:
                wait = float(r.headers.get("retry-after", "5"))
                wait = max(wait, 2 ** (attempt + 1))
                if attempt < MAX_ATTEMPTS - 1:
                    log(f"  429 — sleeping {wait:.1f}s (attempt {attempt + 1}/{MAX_ATTEMPTS})")
                    time.sleep(wait)
                    continue
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            return parse_score(text, resumes)
        except requests.HTTPError as e:
            if attempt < MAX_ATTEMPTS - 1:
                backoff = 2 ** (attempt + 1)
                log(f"  HTTP error, retrying in {backoff}s: {e}")
                time.sleep(backoff)
                continue
            log(f"  scoring failed {job['id']}: {e}")
            return {"score": 0, "verdict": f"score error: {e}", "chosen_resume": ""}
        except Exception as e:
            log(f"  scoring failed {job['id']}: {e}")
            return {"score": 0, "verdict": f"score error: {e}", "chosen_resume": ""}
    return {"score": 0, "verdict": "score error: retries exhausted", "chosen_resume": ""}


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

    if not resumes:
        log("FATAL: no résumés in scrape artifact — match.py cannot score without them")
        return 2

    if not jobs:
        log("no jobs to score; passing through empty list")
        write_artifact(
            "match_output.json",
            json.dumps({"scored": [], "seen": seen, "board_summary": scrape.get("board_summary", [])}),
        )
        return 0

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
    log(f"scoring {len(to_score)} jobs against Groq ({MODEL}); pacing {pace}s between calls")
    for i, j in enumerate(to_score, start=1):
        result = score_one(j, resumes, api_key, session)
        j_out = {k: v for k, v in j.items() if k not in {"_pre_score"}}
        j_out["score"] = result["score"]
        j_out["verdict"] = result["verdict"]
        j_out["chosen_resume"] = result["chosen_resume"]
        scored.append(j_out)
        # Mark as seen ONLY now that we've made a real scoring attempt
        # (a 0/10 from a 429 still counts — we don't want to retry it tomorrow
        # if Groq was the problem; the user can manually re-run if needed).
        seen[j["id"]] = today_iso
        resume_short = _label(result["chosen_resume"]) if result["chosen_resume"] else "—"
        log(f"  [{i:2d}/{len(to_score)}] {j['company']:14s} {j['title'][:42]:42s} → {result['score']}/10  [{resume_short}]")
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
                "candidates_scored": len(to_score),
                "candidates_dropped": len(dropped),
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
