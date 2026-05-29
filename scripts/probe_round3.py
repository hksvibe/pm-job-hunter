"""Round 3: probe ~150 more candidates across 5 ATS providers.
Focus: India IT product cos + India AI/SaaS startups + ME non-fintech.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
from typing import Optional

import requests

EXISTING = {
    "careem", "tamara", "payit", "hala", "rain", "leantech",
    "groww", "slice", "phonepe", "postman", "inmobi", "glance",
    "cred", "paytm", "meesho", "porter", "fampay",
    "navi", "leap", "scaler",
    "stripe", "adyen", "databricks", "anthropic", "airbnb", "scaleai",
    "intercom", "figma", "asana", "duolingo", "vercel", "discord",
    "deepmind", "instacart", "openai", "snowflake", "notion", "cohere",
    "plaid", "perplexity", "supabase", "linear",
    "epifi", "thndr", "freshworks", "ixigo", "naukri", "unacademy",
    "cars24", "lendingkart", "upstox", "almosafer", "namshi",
    "noonacademy", "linkedin", "uber", "drivetrain", "highradius",
    "sarvam", "atlan", "mindtickle", "newton", "abhibus",
    "interviewbit", "nobroker", "aldar", "carriage", "agoda",
    "tripadvisor", "deliveroo",
}

INDIA_AI_SAAS = [
    "krutrim", "yellow", "yellow-ai", "yellow.ai", "haptik", "exotel",
    "rocketlane", "chargebee", "icertis", "highradius",
    "rephrase", "rephrase-ai", "observe-ai", "observeai",
    "kuku-fm", "kuku", "skit", "skit-ai", "skit.ai",
    "matter-ai", "matter", "decimal", "browserstack",
    "lambdatest", "smallcase",
]

INDIA_CONSUMER = [
    "lenskart", "myntra", "nykaa", "ajio", "firstcry",
    "tata-1mg", "tata1mg", "pharmeasy", "practo",
    "magicpin", "urbancompany", "urban-company", "uc",
    "purplle", "snitch", "swiggy", "zomato", "blinkit",
    "zepto", "bigbasket", "rapido", "ola-cabs", "olacabs",
    "ola", "rebel-foods", "rebelfoods",
]

INDIA_B2B_SAAS = [
    "razorpay", "pinelabs", "pine-labs", "bharatpe", "khatabook",
    "innovaccer", "darwinbox", "leadsquared", "leadsquared-marketxpand",
    "mfilterit", "amagi", "swiggy-instamart", "amber-student", "amberstudent",
    "fynd", "shopx", "udaan-b2b", "moglix", "ofbusiness",
    "razorpay-x", "khatabook", "captainfresh", "captain-fresh",
]

INDIA_PRODUCT_TECH = [
    "salesforce", "salesforceindia", "oracle", "adobe", "microsoft",
    "google", "amazon", "amazon-jobs", "microsoftindia",
    "servicenow", "atlassian", "workday", "snowflake",
    "splunk", "twilio", "okta", "datadog", "newrelic", "new-relic",
    "elasticsearch", "elastic", "mongodb", "redis",
    "confluent", "datadog", "github", "cloudera",
]

ME_TECH_NON_FINTECH = [
    "swvl", "anghami", "starzplay", "shahid", "mbc",
    "salla", "zid", "tabby", "tamara", "noon",
    "property-finder", "propertyfinder", "bayut", "dubizzle",
    "houza", "huspy", "stake", "lulu-group", "lulugroup",
    "carrefour-mena", "carrefour", "alfuttaim", "al-futtaim",
    "majidalfuttaim", "majid-al-futtaim",
    "talabat", "deliveroo-mena", "instashop",
    "hungerstation", "jahez", "mrsool",
    "almosafer", "wego", "tajawal", "rehlat",
    "g42", "core42", "presight", "inception",
    "stcgroup", "stc", "etisalat", "du-uae", "mobily",
    "halan", "elgrocer",
]

ME_RETAIL = [
    "noon-academy", "saudi-airlines", "saudia",
    "emirates", "etihad", "qatar-airways", "qatarairways",
    "saudi-aramco", "aramco",
]

CANDIDATES = sorted(set(
    INDIA_AI_SAAS + INDIA_CONSUMER + INDIA_B2B_SAAS + INDIA_PRODUCT_TECH
    + ME_TECH_NON_FINTECH + ME_RETAIL
) - EXISTING)
UA = {"User-Agent": "probe/1.0"}


def probe_greenhouse(s):
    try:
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs?content=false", timeout=8, headers=UA)
        if r.status_code == 200:
            return len((r.json().get("jobs") or []))
    except: pass


def probe_lever(s):
    try:
        r = requests.get(f"https://api.lever.co/v0/postings/{s}?mode=json", timeout=8, headers=UA)
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, list): return len(d)
    except: pass


def probe_ashby(s):
    try:
        r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{s}", timeout=8, headers=UA)
        if r.status_code == 200:
            return len((r.json().get("jobs") or []))
    except: pass


def probe_workable(s):
    try:
        r = requests.get(f"https://apply.workable.com/api/v3/accounts/{s}/jobs", timeout=8,
                         headers={**UA, "Accept": "application/json"}, params={"state": "published"})
        if r.status_code == 200:
            d = r.json()
            res = d.get("results") if isinstance(d, dict) else None
            return len(res or [])
    except: pass


def probe_sr(s):
    try:
        r = requests.get(f"https://api.smartrecruiters.com/v1/companies/{s}/postings", timeout=8, headers=UA)
        if r.status_code == 200:
            d = r.json()
            return d.get("totalFound") or len(d.get("content") or [])
    except: pass


def probe_one(s):
    return dict(
        slug=s,
        greenhouse=probe_greenhouse(s),
        lever=probe_lever(s),
        ashby=probe_ashby(s),
        workable=probe_workable(s),
        smartrecruiters=probe_sr(s),
    )


def main():
    with cf.ThreadPoolExecutor(max_workers=40) as pool:
        results = list(pool.map(probe_one, CANDIDATES))
    hits = []
    for r in results:
        for p in ("greenhouse","lever","ashby","workable","smartrecruiters"):
            v = r[p]
            if v is not None and v > 0:
                hits.append({"slug": r["slug"], "provider": p, "count": v})
    hits.sort(key=lambda h: (-h["count"], h["provider"], h["slug"]))
    print(json.dumps({"probed": len(CANDIDATES), "hits": len(hits), "boards": hits}, indent=2))


if __name__ == "__main__":
    main()
