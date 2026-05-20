"""Probe candidate ATS slugs across Greenhouse, Lever, Ashby, Workable.

Outputs:
  - which slugs respond 2xx on each provider
  - job count for each (so we drop empty boards)

Concurrency: ~50 in flight via ThreadPoolExecutor.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
from typing import Optional

import requests

# === Candidate slugs (heavy on fintech + AI + ME) ============================
INDIA_FINTECH = [
    "razorpay", "cred", "groww", "jupiter", "jupitermoney", "niyo", "goniyo", "open", "openfinance",
    "setu", "m2p", "m2pfintech", "cashfree", "juspay", "zerodha", "smallcase", "angelone",
    "upstox", "acko", "mobikwik", "bharatpe", "khatabook", "slice", "paytm", "phonepe",
    "payu", "payuin", "pinelabs", "pine-labs", "lendingkart", "kotak", "kotaksecurities",
    "bajajfinserv", "icicibank", "hdfcbank", "indmoney", "indmoney-app", "jar", "jarapp",
    "fampay", "moneyview", "kissht", "moneytap", "kreditbee", "navi", "naviapp",
    "rupifi", "decentro", "perfios", "fingerlnk", "fundsindia", "scripbox",
]

INDIA_TECH = [
    "swiggy", "zomato", "flipkart", "meesho", "ola", "olacabs", "uber", "dream11",
    "junglee", "junglee-games", "inshorts", "glance", "inmobi", "mpl", "games24x7",
    "zepto", "blinkit", "dunzo", "postman", "browserstack", "freshworks", "zoho",
    "servify", "oyo", "magicpin", "easemytrip", "ixigo", "myntra", "nykaa",
    "udaan", "pharmeasy", "tata1mg", "1mg", "practo", "shaadi", "matrimony",
    "shiprocket", "delhivery", "rapido", "porter", "instacart", "byjus",
    "unacademy", "upgrad", "vedantu", "physicswallah", "scaler", "newton-school",
    "razorpay-x", "leap", "leapfinance",
]

ME_FINTECH = [
    "careem", "tamara", "payit", "tabby", "noon", "stcpay", "mashreq", "emiratesnbd",
    "wio", "wiobank", "lulu", "lulufinancialholdings", "rain", "lean", "leantech",
    "fawry", "mamopay", "sarwa", "wahed", "paymob", "geidea", "nymcard", "hala",
    "sukna", "foloosi", "telr", "paytabs", "swvl", "mrsool", "floward", "anghami",
    "property-finder", "propertyfinder", "bayut", "dubizzle", "talabat", "instashop",
    "fetchr", "tarjama", "edenred", "valu",
]

GLOBAL = [
    "stripe", "plaid", "wise", "revolut", "adyen", "coinbase", "anthropic", "openai",
    "shopify", "snowflake", "airbnb", "atlassian", "figma", "notion", "discord",
    "linear", "vercel", "supabase", "databricks", "scale", "scaleai", "hugginface",
    "huggingface", "cohere", "deepmind", "perplexity", "mistralai", "rivian", "duolingo",
    "loom", "miro", "asana", "monday", "intercom", "front",
]

CANDIDATES = list(set(INDIA_FINTECH + INDIA_TECH + ME_FINTECH + GLOBAL))


def probe_greenhouse(slug: str) -> Optional[int]:
    try:
        r = requests.get(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false",
            timeout=8,
            headers={"User-Agent": "probe/1.0"},
        )
        if r.status_code == 200:
            return len((r.json().get("jobs") or []))
    except Exception:
        pass
    return None


def probe_lever(slug: str) -> Optional[int]:
    try:
        r = requests.get(
            f"https://api.lever.co/v0/postings/{slug}?mode=json",
            timeout=8,
            headers={"User-Agent": "probe/1.0"},
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return len(data)
    except Exception:
        pass
    return None


def probe_ashby(slug: str) -> Optional[int]:
    try:
        r = requests.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
            timeout=8,
            headers={"User-Agent": "probe/1.0"},
        )
        if r.status_code == 200:
            data = r.json()
            return len((data.get("jobs") or []))
    except Exception:
        pass
    return None


def probe_workable(slug: str) -> Optional[int]:
    try:
        r = requests.get(
            f"https://apply.workable.com/api/v3/accounts/{slug}/jobs",
            timeout=8,
            headers={"User-Agent": "probe/1.0", "Accept": "application/json"},
            params={"state": "published"},
        )
        if r.status_code == 200:
            data = r.json()
            results = data.get("results") if isinstance(data, dict) else None
            return len(results or [])
    except Exception:
        pass
    return None


def probe_one(slug: str) -> dict:
    return {
        "slug": slug,
        "greenhouse": probe_greenhouse(slug),
        "lever":      probe_lever(slug),
        "ashby":      probe_ashby(slug),
        "workable":   probe_workable(slug),
    }


def main() -> None:
    with cf.ThreadPoolExecutor(max_workers=40) as pool:
        results = list(pool.map(probe_one, CANDIDATES))
    hits = []
    for r in results:
        for provider in ("greenhouse", "lever", "ashby", "workable"):
            if r[provider] is not None and r[provider] > 0:
                hits.append({"slug": r["slug"], "provider": provider, "count": r[provider]})
    hits.sort(key=lambda h: (-h["count"], h["provider"], h["slug"]))
    print(json.dumps({"probed": len(CANDIDATES), "hits": len(hits), "boards": hits}, indent=2))


if __name__ == "__main__":
    main()
