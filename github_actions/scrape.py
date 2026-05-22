"""Fetch every board in parallel, normalize to a common shape, filter, dedup,
route each surviving job to a résumé, and write the result to an artifact for
the next stage."""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
from datetime import date

import requests

from common import (
    fingerprint,
    load_filters,
    load_resumes,
    load_seen,
    load_sources,
    log,
    write_artifact,
)

HTML_TAG_RE = re.compile(r"<[^>]+>")
HTML_ENTITY_RE = re.compile(r"&[a-z]+;", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")


def strip(html: str | None) -> str:
    if not html:
        return ""
    s = HTML_TAG_RE.sub(" ", html)
    s = HTML_ENTITY_RE.sub(" ", s)
    return WHITESPACE_RE.sub(" ", s).strip()


def lower(s: object) -> str:
    return ("" if s is None else str(s)).lower()


def fetch_board(board: dict) -> dict:
    """Returns {ok, data?, error?, src}."""
    try:
        r = requests.get(
            board["fetch_url"],
            headers={"Accept": "application/json", "User-Agent": "pm-job-hunter/1.0"},
            timeout=15,
        )
        r.raise_for_status()
        return {"ok": True, "data": r.json(), "src": board}
    except Exception as e:
        return {"ok": False, "error": str(e), "src": board}


def normalize(resp: dict) -> list[dict]:
    if not resp.get("ok"):
        return []
    src = resp["src"]
    data = resp["data"]
    out: list[dict] = []
    if src["board_type"] == "greenhouse":
        for j in (data.get("jobs") or []):
            out.append({
                "id": f"gh:{src['slug']}:{j.get('id')}",
                "title": j.get("title") or "",
                "company": src["company"],
                "location": (j.get("location") or {}).get("name") or "",
                "url": j.get("absolute_url") or "",
                "jd": strip(j.get("content")),
                "region": src.get("region"),
            })
    elif src["board_type"] == "lever":
        for j in (data if isinstance(data, list) else []):
            jd_parts = [j.get("descriptionPlain") or ""]
            for lst in (j.get("lists") or []):
                jd_parts.append(f"{lst.get('text') or ''}: {strip(lst.get('content'))}")
            out.append({
                "id": f"lv:{src['slug']}:{j.get('id')}",
                "title": j.get("text") or "",
                "company": src["company"],
                "location": (j.get("categories") or {}).get("location") or j.get("workplaceType") or "",
                "url": j.get("hostedUrl") or j.get("applyUrl") or "",
                "jd": "\n".join(p for p in jd_parts if p),
                "region": src.get("region"),
            })
    elif src["board_type"] == "ashby":
        for j in (data.get("jobs") or []):
            secondary = j.get("secondaryLocations") or []
            secondary_strs = []
            for sl in secondary:
                if isinstance(sl, dict):
                    secondary_strs.append(sl.get("location") or sl.get("name") or "")
                elif isinstance(sl, str):
                    secondary_strs.append(sl)
            loc_bits = [j.get("location") or "", j.get("workplaceType") or ""] + secondary_strs
            if j.get("isRemote"):
                loc_bits.append("remote")
            location = " | ".join(b for b in loc_bits if b)
            jd = j.get("descriptionPlain") or strip(j.get("descriptionHtml"))
            out.append({
                "id": f"ab:{src['slug']}:{j.get('id')}",
                "title": j.get("title") or "",
                "company": src["company"],
                "location": location,
                "url": j.get("jobUrl") or j.get("applyUrl") or "",
                "jd": jd,
                "region": src.get("region"),
            })
    return out


def make_filter(filters: dict):
    ti = [t.lower() for t in filters["title_include"]]
    tx = [t.lower() for t in filters["title_exclude"]]
    india_locs = [l.lower() for l in filters["allowed_locations"]["india"]]
    me_locs = [l.lower() for l in filters["allowed_locations"]["middle_east"]]
    remote_locs = [l.lower() for l in filters["allowed_locations"]["remote_friendly"]]
    target_locs = india_locs + me_locs
    rx_remote_exclude = [p.lower() for p in filters["remote_exclude_patterns"]]
    location_exclude = [l.lower() for l in filters.get("location_exclude", [])]

    def passes_title(t: str) -> bool:
        lt = lower(t)
        if any(x in lt for x in tx):
            return False
        return any(x in lt for x in ti)

    def passes_location(loc: str, jd: str) -> bool:
        # Pad with spaces so tokens like " usa" or " uk " can match at word
        # boundaries without false positives on "australia" containing "us".
        lloc = f" {lower(loc)} "
        ljd  = f" {lower(jd)[:600]} "

        # 1) HARD REJECT — any explicitly excluded region in the location text.
        #    We only check `lloc`, not the JD, because a US-headquartered
        #    company often mentions "San Francisco" in their company-summary
        #    boilerplate even when hiring elsewhere.
        if any(x in lloc for x in location_exclude):
            return False

        # 2) Direct accept — location explicitly names an India or ME locale.
        if any(x in lloc for x in target_locs):
            return True

        # 3) Remote — accept only if the JD itself mentions India/ME (i.e. the
        #    role is genuinely open to candidates there) AND no remote-region-
        #    lock pattern is in the JD.
        if any(x in lloc for x in remote_locs):
            if any(p in ljd for p in rx_remote_exclude):
                return False
            if any(x in ljd for x in target_locs):
                return True
            # "remote" with no India/ME signal in JD — probably US-default remote.
            return False

        # 4) Nothing matched — reject.
        return False

    return passes_title, passes_location


def main() -> int:
    sources = load_sources()
    filters = load_filters()
    resumes = load_resumes()
    seen = load_seen()
    log(f"loaded {len(sources)} boards; {len(resumes)} resumes; {len(seen)} seen ids")

    with cf.ThreadPoolExecutor(max_workers=len(sources)) as pool:
        responses = list(pool.map(fetch_board, sources))

    board_summary = []
    for r in responses:
        raw = 0
        if r.get("ok"):
            bt = r["src"]["board_type"]
            if bt == "greenhouse":
                raw = len((r["data"] or {}).get("jobs") or [])
            elif bt == "lever":
                raw = len(r["data"]) if isinstance(r["data"], list) else 0
            elif bt == "ashby":
                raw = len(((r["data"] or {}).get("jobs")) or [])
        board_summary.append({
            "company": r["src"]["company"],
            "ok": r.get("ok"),
            "error": r.get("error"),
            "raw_count": raw,
        })
        log(f"  {r['src']['company']:14s} ok={r.get('ok')!s:5s} raw={raw}")

    all_jobs: list[dict] = []
    for r in responses:
        all_jobs.extend(normalize(r))

    passes_title, passes_location = make_filter(filters)
    after_filter = [
        j for j in all_jobs
        if passes_title(j["title"]) and passes_location(j["location"], j["jd"])
    ]

    # Two-level dedup: skip if the exact job ID was seen OR if the same
    # (company, title) fingerprint was already delivered under a different ID
    # (catches reposts under fresh ATS URLs).
    seen_ids = set(seen.keys())
    seen_fps = {v.get("fp") for v in seen.values() if v.get("fp")}
    after_dedup = []
    dedup_by_id = 0
    dedup_by_fp = 0
    for j in after_filter:
        if j["id"] in seen_ids:
            dedup_by_id += 1
            continue
        if fingerprint(j["company"], j["title"]) in seen_fps:
            dedup_by_fp += 1
            continue
        after_dedup.append(j)
    log(f"raw={len(all_jobs)}  after_filter={len(after_filter)}  "
        f"after_dedup={len(after_dedup)}  (dropped {dedup_by_id} by id, {dedup_by_fp} by fingerprint)")

    # Loud failure if filter killed everything — likely a broken source list.
    # Silent no-op if dedup killed everything — normal "no new jobs" day.
    if not after_filter and all_jobs:
        log("warning: jobs found but none passed filter — check filters.json")
    if not after_dedup:
        log("no new jobs to score; exiting cleanly")
        # Resumes must be passed through even on no-op runs — match.py loads
        # them and fails fatally if they're missing, even when there's
        # nothing to score. (Older scrape.py wrote a slimmer artifact here.)
        write_artifact(
            "scrape_output.json",
            json.dumps(
                {"jobs": [], "resumes": resumes, "board_summary": board_summary, "seen": seen}
            ),
        )
        return 0

    for j in after_dedup:
        j["_min_score"] = filters.get("min_llm_score", 7)

    # NOTE: we deliberately do NOT mark anything as "seen" here. match.py only
    # scores the top-N most relevant jobs and marks just those. Anything that
    # gets dropped by the pre-ranker stays unseen, so it gets a second chance
    # tomorrow if a higher-ranked job is delivered today.
    #
    # Résumés are attached at the top level (not per-job) so the artifact stays
    # small. match.py reads them and sends *all* variants to the LLM, which
    # picks the best fit per job.

    write_artifact(
        "scrape_output.json",
        json.dumps(
            {
                "jobs": after_dedup,
                "resumes": resumes,
                "board_summary": board_summary,
                "seen": seen,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    log(f"wrote {len(after_dedup)} jobs to artifact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
