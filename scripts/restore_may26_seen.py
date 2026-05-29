"""Restore the 12 jobs delivered on 2026-05-26 into jobs_seen.json.

The May 26 GH-Actions run scored 12 jobs, sent them to Telegram, and was
supposed to commit jobs_seen.json back to the repo — but somewhere in the
subsequent merges the bot commit got lost. The on-disk file went from 76
entries (right after the run) back to 64 entries.

This script finds matching listings in the current scrape artifact and
adds them to jobs_seen.json with today's date so they won't ship again.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO = Path("/Users/harshmacminim4/PM Job Scrapper")
sys.path.insert(0, str(REPO / "github_actions"))
from common import fingerprint  # noqa: E402

# The 12 jobs delivered on 2026-05-26 (company + title)
MAY_26_DELIVERY = {
    ("HighRadius", "Senior Product Manager"),
    ("HighRadius", "Product Manager"),
    ("MindTickle", "Group Product Manager"),
    ("MindTickle", "Senior Product Manager"),
    ("MindTickle", "Technical Product Owner - II"),
    ("Sarvam AI", "Product Manager (Models)"),
    ("Sarvam AI", "Product Manager"),
    ("Sarvam AI", "Product Manager On-Device & Edge AI"),
    ("Sarvam AI", "Product Manager, Growth"),
    ("Sarvam AI", "Product Manager, Monetization & Retention"),
}

target_fps = {fingerprint(c, t) for c, t in MAY_26_DELIVERY}

scrape = json.loads((REPO / "github_actions" / "_artifacts" / "scrape_output.json").read_text())
seen = json.loads((REPO / "jobs_seen.json").read_text())
today = date.today().isoformat()

added = []
for j in scrape["jobs"]:
    fp = fingerprint(j["company"], j["title"])
    if fp in target_fps and j["id"] not in seen:
        seen[j["id"]] = {"date": today, "fp": fp}
        added.append((j["company"], j["title"], j["id"]))

(REPO / "jobs_seen.json").write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n")

print(f"Added {len(added)} restored entries:")
for c, t, i in added:
    print(f"  {c:18s} {t[:50]:50s}  id={i}")
print(f"\nTotal seen entries: {len(seen)}")
