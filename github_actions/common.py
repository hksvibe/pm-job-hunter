"""Shared helpers: config loading, paths, simple logging."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# repo_root resolves to the parent of `github_actions/` so configs/resumes/
# jobs_seen.json sit at the repo root and are shared with the n8n setup.
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
RESUMES_DIR = REPO_ROOT / "resumes"
SEEN_PATH = REPO_ROOT / "jobs_seen.json"
ARTIFACTS_DIR = REPO_ROOT / "github_actions" / "_artifacts"


def log(*parts: object) -> None:
    print(*parts, file=sys.stderr, flush=True)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_sources() -> list[dict]:
    return load_json(CONFIG_DIR / "sources.json")["boards"]


def load_filters() -> dict:
    return load_json(CONFIG_DIR / "filters.json")


def load_routing() -> dict:
    return load_json(CONFIG_DIR / "resume_routing.json")


def load_resumes() -> dict[str, str]:
    return {p.name: load_text(p) for p in RESUMES_DIR.glob("*.txt")}


def load_seen() -> dict[str, dict]:
    """jobs_seen.json schema:
       Modern: { "<job_id>": {"date": "YYYY-MM-DD", "fp": "<fingerprint>"} }
       Legacy: { "<job_id>": "YYYY-MM-DD" }   ← migrated transparently on load
    """
    if not SEEN_PATH.exists():
        return {}
    try:
        raw = load_json(SEEN_PATH)
    except json.JSONDecodeError:
        log(f"warning: {SEEN_PATH} not valid JSON — starting fresh")
        return {}
    out: dict[str, dict] = {}
    for k, v in raw.items():
        if isinstance(v, str):           # legacy: just a date string
            out[k] = {"date": v, "fp": ""}
        elif isinstance(v, dict):
            out[k] = {"date": v.get("date", ""), "fp": v.get("fp", "")}
        else:
            out[k] = {"date": "", "fp": ""}
    return out


def save_seen(seen: dict[str, dict]) -> None:
    SEEN_PATH.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# Collapses runs of whitespace, hyphens, underscores, slashes into a single
# space so that "Senior PM - Lending" and "Senior PM- Lending" produce the
# same fingerprint. Keeps alphanumerics intact so distinct titles
# ("Senior PM - Payments" vs "Senior PM - Lending") stay distinct.
_FP_NORM_RE = re.compile(r"[\s\-_/]+")


def fingerprint(company: str, title: str) -> str:
    c = _FP_NORM_RE.sub(" ", (company or "").lower()).strip()
    t = _FP_NORM_RE.sub(" ", (title or "").lower()).strip()
    return f"{c}|{t}"


def env_required(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        log(f"FATAL: env var {name} is missing or empty")
        sys.exit(2)
    return v


def write_artifact(name: str, content: str) -> Path:
    """Write an intermediate JSON/text artifact so the three scripts can pipe state."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    p = ARTIFACTS_DIR / name
    p.write_text(content, encoding="utf-8")
    return p


def read_artifact(name: str) -> str:
    return (ARTIFACTS_DIR / name).read_text(encoding="utf-8")
