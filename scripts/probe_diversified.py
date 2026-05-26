"""Probe a diversified set of ~250 India + ME company slugs across 5 ATS
providers (Greenhouse, Lever, Ashby, Workable, SmartRecruiters)."""
from __future__ import annotations

import concurrent.futures as cf
import json
from typing import Optional

import requests

# === Candidates organised by domain ==========================================

INDIA_ECOMMERCE_MARKETPLACE = [
    "flipkart", "myntra", "nykaa", "tatacliq", "tata-cliq", "firstcry", "lenskart",
    "ajio", "limeroad", "voonik", "shopclues", "snapdeal", "udaan", "udaanb2b",
    "meesho", "reliancedigital", "tatadigital",
]

INDIA_FOODTECH_QCOMMERCE = [
    "swiggy", "zomato", "zepto", "blinkit", "dunzo", "bigbasket", "grofers",
    "instamart", "swiggy-instamart", "licious", "fresh-to-home", "freshtohome",
]

INDIA_MOBILITY_LOGISTICS = [
    "ola", "olacabs", "ola-electric", "olaelectric", "uber", "uber-india",
    "rapido", "porter", "blusmart", "blu-smart", "yulu",
    "delhivery", "shiprocket", "ecom-express", "ecomexpress", "xpressbees",
    "shadowfax", "rivigo",
]

INDIA_TRAVEL = [
    "makemytrip", "mmt", "goibibo", "ixigo", "easemytrip", "easetrip", "yatra",
    "redbus", "abhibus", "agoda", "booking", "tripadvisor",
]

INDIA_EDTECH = [
    "byjus", "unacademy", "vedantu", "physicswallah", "physics-wallah", "upgrad",
    "scaler", "newton-school", "newton", "talentsprint", "interviewbit",
    "doubtnut", "topper", "leverage-edu", "leverageedu", "leap",
]

INDIA_HEALTHTECH = [
    "practo", "pharmeasy", "tata1mg", "1mg", "netmeds", "mfine", "tata-1mg",
    "curefit", "cult", "cult-fit", "healthifyme", "phable",
]

INDIA_GAMING_MEDIA = [
    "dream11", "mpl", "games24x7", "junglee-games", "junglee", "winzo",
    "rummy-culture", "rummyculture", "hotstar", "jiocinema", "zee5",
    "sonyliv", "viacom18", "voot", "alt-balaji", "altbalaji",
    "sharechat", "mxplayer", "mx-player", "inshorts", "dailyhunt",
]

INDIA_SAAS_B2B = [
    "freshworks", "zoho", "browserstack", "darwinbox", "chargebee",
    "haptik", "yellow", "yellow-ai", "exotel", "exotel-techcom",
    "atlan", "rocketlane", "interview-kickstart", "razorpayx",
    "highradius", "icertis", "mindtickle",
]

INDIA_PROPTECH_RETAIL = [
    "nobroker", "no-broker", "housing", "magicbricks", "99acres",
    "urban-company", "urbancompany", "urbanclap", "purplle",
    "magicpin", "shopkirana",
]

INDIA_AI_DATA = [
    "fractal", "fractal-analytics", "tigeranalytics", "tiger-analytics",
    "mu-sigma", "musigma", "krutrim", "ola-krutrim", "sarvam", "sarvam-ai",
    "yellow-ai", "haptik", "rephrase-ai", "rephrase",
]

ME_ECOMMERCE_RETAIL = [
    "noon", "amazon-ae", "carrefour-mena", "carrefour", "alfuttaim", "al-futtaim",
    "lulu-group", "lulugroup", "namshi", "ounass", "level-shoes",
    "majidalfuttaim", "majid-al-futtaim",
]

ME_FOOD_QCOMMERCE = [
    "talabat", "deliveroo-mena", "deliveroo", "carriage", "jahez", "hungerstation",
    "mrsool", "instashop", "el-grocer", "elgrocer", "kitopi", "iwgb-foods",
]

ME_MOBILITY_LOGISTICS = [
    "careem", "uber", "fetchr", "aramex", "shipa", "shipa-delivery", "swvl",
    "shahin", "yallahub", "yallow-fetchr",
]

ME_TRAVEL_HOSPITALITY = [
    "almosafer", "wego", "tajawal", "kanoo-travel", "musafir", "rehlat",
    "emirates", "emirates-group", "etihad", "saudia", "qatar-airways", "qatarairways",
    "marriott-mea", "jumeirah", "rotana", "damac-hotels",
]

ME_PROPTECH_REAL_ESTATE = [
    "propertyfinder", "property-finder", "bayut", "dubizzle", "houza",
    "huspy", "stake", "emaar", "damac", "aldar", "aldar-properties",
]

ME_AI_TECH = [
    "g42", "core42", "inception", "presight", "presight-ai", "cequence",
    "sparkclouds", "yallaspree",
]

ME_TELECOM_MEDIA = [
    "stc", "stc-group", "stcgroup", "du-uae", "etisalat", "etisalat-group",
    "mobily", "anghami", "starzplay", "shahid", "mbc",
]

CANDIDATES = sorted(set(
    INDIA_ECOMMERCE_MARKETPLACE + INDIA_FOODTECH_QCOMMERCE + INDIA_MOBILITY_LOGISTICS
    + INDIA_TRAVEL + INDIA_EDTECH + INDIA_HEALTHTECH + INDIA_GAMING_MEDIA
    + INDIA_SAAS_B2B + INDIA_PROPTECH_RETAIL + INDIA_AI_DATA
    + ME_ECOMMERCE_RETAIL + ME_FOOD_QCOMMERCE + ME_MOBILITY_LOGISTICS
    + ME_TRAVEL_HOSPITALITY + ME_PROPTECH_REAL_ESTATE + ME_AI_TECH
    + ME_TELECOM_MEDIA
))

UA = {"User-Agent": "probe/1.0"}


def probe_greenhouse(slug: str) -> Optional[int]:
    try:
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false", timeout=8, headers=UA)
        if r.status_code == 200:
            return len((r.json().get("jobs") or []))
    except Exception:
        pass
    return None


def probe_lever(slug: str) -> Optional[int]:
    try:
        r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=8, headers=UA)
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, list):
                return len(d)
    except Exception:
        pass
    return None


def probe_ashby(slug: str) -> Optional[int]:
    try:
        r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=8, headers=UA)
        if r.status_code == 200:
            return len((r.json().get("jobs") or []))
    except Exception:
        pass
    return None


def probe_workable(slug: str) -> Optional[int]:
    try:
        r = requests.get(f"https://apply.workable.com/api/v3/accounts/{slug}/jobs", timeout=8,
                         headers={**UA, "Accept": "application/json"}, params={"state": "published"})
        if r.status_code == 200:
            d = r.json()
            res = d.get("results") if isinstance(d, dict) else None
            return len(res or [])
    except Exception:
        pass
    return None


def probe_smartrecruiters(slug: str) -> Optional[int]:
    try:
        r = requests.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", timeout=8, headers=UA)
        if r.status_code == 200:
            d = r.json()
            return d.get("totalFound") or len(d.get("content") or [])
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
        "smartrecruiters": probe_smartrecruiters(slug),
    }


def main() -> None:
    with cf.ThreadPoolExecutor(max_workers=40) as pool:
        results = list(pool.map(probe_one, CANDIDATES))
    hits = []
    for r in results:
        for provider in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters"):
            if r[provider] is not None and r[provider] > 0:
                hits.append({"slug": r["slug"], "provider": provider, "count": r[provider]})
    hits.sort(key=lambda h: (-h["count"], h["provider"], h["slug"]))
    print(json.dumps({"probed": len(CANDIDATES), "hits": len(hits), "boards": hits}, indent=2))


if __name__ == "__main__":
    main()
