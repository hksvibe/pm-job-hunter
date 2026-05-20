"""Format the scored jobs into Telegram digests (chunked under 4096 chars)
and ship them. Only persists the new jobs_seen.json after at least one chunk
delivers successfully — so a Telegram outage doesn't poison the dedup state."""
from __future__ import annotations

import json
from datetime import date

import requests

from common import (
    env_required,
    load_filters,
    log,
    read_artifact,
    save_seen,
    SEEN_PATH,
)

TG_API = "https://api.telegram.org"
MAX_MSG = 3500  # Telegram limit is 4096; leave headroom for header / footer / part-tag


def _resume_label(filename: str) -> str:
    """april_2026.txt → 'April 2026'; digital_payments.txt → 'Digital Payments'."""
    if not filename:
        return ""
    return filename.rsplit(".", 1)[0].replace("_", " ").title()


def build_messages(scored: list[dict], threshold: int) -> list[str]:
    matches = sorted([j for j in scored if (j.get("score") or 0) >= threshold], key=lambda j: -j["score"])
    if not matches:
        return []

    date_str = date.today().strftime("%d %b %Y")
    blocks: list[str] = []
    for i, j in enumerate(matches[:30], start=1):
        verdict = (j.get("verdict") or "")[:180]
        resume_label = _resume_label(j.get("chosen_resume"))
        block_lines = [f"{i}. {j['title']} — {j['company']} ({j['location']}) ★ {j['score']}/10"]
        if verdict:
            block_lines.append(f"   {verdict}")
        if resume_label:
            block_lines.append(f"   📄 Apply with: {resume_label}")
        block_lines.append(f"   → {j['url']}")
        blocks.append("\n".join(block_lines))

    footer = "\nSent by your job bot 🤖"

    # pack into chunks
    chunks: list[str] = []
    body = ""
    for block in blocks:
        candidate = (body + "\n\n" + block) if body else block
        header_overhead = 80  # rough header size
        if len(candidate) + header_overhead + len(footer) > MAX_MSG and body:
            chunks.append(body)
            body = block
        else:
            body = candidate
    if body:
        chunks.append(body)

    return [
        f"🎯 PM Jobs — {date_str}{(' (part %d/%d)' % (i + 1, len(chunks))) if len(chunks) > 1 else ''}\n"
        f"{len(matches)} match{'es' if len(matches) != 1 else ''} (score ≥ {threshold})\n\n"
        f"{c}"
        + (footer if i == len(chunks) - 1 else "")
        for i, c in enumerate(chunks)
    ]


def send(message: str, token: str, chat_id: str) -> bool:
    url = f"{TG_API}/bot{token}/sendMessage"
    r = requests.post(
        url,
        json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
        timeout=30,
    )
    try:
        data = r.json()
    except ValueError:
        log(f"telegram: non-JSON response: {r.text[:300]}")
        return False
    if not data.get("ok"):
        log(f"telegram error {data.get('error_code')}: {data.get('description')}")
        return False
    return True


def main() -> int:
    token = env_required("TELEGRAM_BOT_TOKEN")
    chat_id = env_required("TELEGRAM_CHAT_ID")

    match = json.loads(read_artifact("match_output.json"))
    scored = match.get("scored") or []
    seen = match.get("seen") or {}
    filters = load_filters()
    threshold = filters.get("min_llm_score", 7)

    messages = build_messages(scored, threshold)
    if not messages:
        log(f"no jobs ≥ {threshold}/10 today; nothing to send")
        # Still commit seen so next run skips today's batch even though we silently no-op'd
        if seen:
            save_seen(seen)
            log(f"persisted {len(seen)} seen ids to {SEEN_PATH.name}")
        return 0

    log(f"sending {len(messages)} message(s) to Telegram")
    all_ok = True
    for i, msg in enumerate(messages, start=1):
        ok = send(msg, token, chat_id)
        log(f"  chunk {i}/{len(messages)}: {'ok' if ok else 'failed'}")
        all_ok = all_ok and ok

    if all_ok and seen:
        save_seen(seen)
        log(f"persisted {len(seen)} seen ids to {SEEN_PATH.name}")
    elif not all_ok:
        log("warning: not persisting seen ids because at least one chunk failed")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
