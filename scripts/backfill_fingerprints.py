"""One-off backfill: add a fingerprint to every legacy entry in jobs_seen.json.

Run once after schema-migrating common.load_seen() to the new {id: {date, fp}}
shape. Fetches all configured boards once to look up each seen job's
(company, title), computes the fingerprint, and writes the seen file back.

Idempotent: skips entries that already have a non-empty `fp`.
"""
from __future__ import annotations

import concurrent.futures as cf
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "github_actions"))

from common import fingerprint, load_seen, log, save_seen  # noqa: E402
from scrape import fetch_board, normalize  # noqa: E402

import json  # noqa: E402


def main() -> int:
    sources = json.loads((REPO_ROOT / "config/sources.json").read_text())["boards"]
    seen = load_seen()
    log(f"loaded {len(seen)} seen entries; checking which need fp backfill")

    needs_backfill = [k for k, v in seen.items() if not v.get("fp")]
    if not needs_backfill:
        log("nothing to backfill")
        return 0

    log(f"{len(needs_backfill)} entries need fingerprints; fetching {len(sources)} boards…")

    with cf.ThreadPoolExecutor(max_workers=len(sources)) as pool:
        responses = list(pool.map(fetch_board, sources))

    id_to_meta: dict[str, tuple[str, str]] = {}
    for r in responses:
        if r.get("ok"):
            for j in normalize(r):
                id_to_meta[j["id"]] = (j["company"], j["title"])
    log(f"indexed {len(id_to_meta)} live jobs across {sum(1 for r in responses if r.get('ok'))} boards")

    backfilled = 0
    not_found = 0
    for sid in needs_backfill:
        if sid in id_to_meta:
            company, title = id_to_meta[sid]
            seen[sid]["fp"] = fingerprint(company, title)
            backfilled += 1
        else:
            not_found += 1

    save_seen(seen)
    log(f"done. backfilled={backfilled}, not_found_on_boards_anymore={not_found}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
