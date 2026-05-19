"""Score each scraped job against its routed résumé via Groq Llama-3.3.

Same prompt and same tolerant JSON parser as the n8n workflow's
Score → filter → format node, so behavior is identical across orchestrations.
"""
from __future__ import annotations

import json
import re
import time

import requests

from common import env_required, log, read_artifact, write_artifact

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"


def build_prompt(job: dict) -> tuple[str, str]:
    system = "You score job fit and return ONLY a JSON object. No prose, no markdown, no code fences."
    user = (
        'Scoring rubric (return JSON: {"score": <1-10 integer>, "verdict": "<one short sentence>", "must_have_gaps": ["..."]}):\n'
        "- 10 = strong match on role (Product Management), seniority, domain, AND location (India / Middle East / India-friendly remote).\n"
        "- Penalise heavily if the role is non-PM (engineering, marketing, ops, design, data) or seniority is far below the candidate.\n"
        "- Penalise if location is remote but region-locked outside India/GCC.\n"
        "- Reward domain overlap (fintech, payments, BFSI, AI/ML, conversational AI, KYC/KYB).\n\n"
        f"RESUME:\n{job['resume_text']}\n\n"
        f"JOB:\nTitle: {job['title']}\nCompany: {job['company']}\nLocation: {job['location']}\nJD:\n{(job.get('jd') or '')[:3000]}"
    )
    return system, user


def score_one(job: dict, api_key: str, session: requests.Session) -> tuple[int, str]:
    system, user = build_prompt(job)
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

    # one short retry on 429 / 5xx
    for attempt in range(2):
        try:
            r = session.post(GROQ_URL, headers=headers, json=body, timeout=30)
            if r.status_code == 429 and attempt == 0:
                wait = float(r.headers.get("retry-after", "2"))
                log(f"  rate-limited, sleeping {wait}s")
                time.sleep(min(wait, 5))
                continue
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            return parse_score(text)
        except Exception as e:
            if attempt == 0:
                time.sleep(1)
                continue
            log(f"  error scoring {job['id']}: {e}")
            return 0, f"score error: {e}"
    return 0, "score error: retries exhausted"


def parse_score(s: str) -> tuple[int, str]:
    if not s:
        return 0, "empty response"
    cleaned = s.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        obj = json.loads(cleaned)
        return int(obj.get("score", 0) or 0), str(obj.get("verdict") or "")
    except Exception:
        m_score = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', s)
        m_verd = re.search(r'"verdict"\s*:\s*"([^"]*)"', s)
        if m_score:
            return int(float(m_score.group(1))), m_verd.group(1) if m_verd else ""
        return 0, f"parse failed; raw[0..120]={s[:120]!r}"


def main() -> int:
    api_key = env_required("GROQ_API_KEY")
    scrape = json.loads(read_artifact("scrape_output.json"))
    jobs = scrape.get("jobs") or []

    if not jobs:
        log("no jobs to score; passing through empty list")
        write_artifact(
            "match_output.json",
            json.dumps({"scored": [], "seen": scrape.get("seen", {}), "board_summary": scrape.get("board_summary", [])}),
        )
        return 0

    log(f"scoring {len(jobs)} jobs against Groq ({MODEL})")
    session = requests.Session()
    scored: list[dict] = []
    for j in jobs:
        score, verdict = score_one(j, api_key, session)
        j2 = {k: v for k, v in j.items() if k != "resume_text"}  # drop bulky text from artifact
        j2["score"] = score
        j2["verdict"] = verdict
        scored.append(j2)
        log(f"  {j['company']:14s} {j['title'][:50]:50s} -> {score}/10")

    write_artifact(
        "match_output.json",
        json.dumps(
            {"scored": scored, "seen": scrape.get("seen", {}), "board_summary": scrape.get("board_summary", [])},
            ensure_ascii=False,
            indent=2,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
