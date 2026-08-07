#!/usr/bin/env python3
"""AI Manufacturing Digest — fetch industry news, extract concrete AI use cases, file them in Notion."""
import os
import re
import sys
import json
import time
import html
import socket
import difflib
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

# ------------------- CONFIG -------------------
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "").strip()
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "").strip()

# Print what would be written instead of writing it. Use this to tune the prompt or the
# vocabulary without adding rows you then have to delete.
DRY_RUN = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes")

# Verified live 2026-08-07. Dead feeds are removed rather than left to fail silently.
FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://spectrum.ieee.org/rss/robotics",
    "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss",
    "https://www.roboticsbusinessreview.com/feed/",
    "https://www.therobotreport.com/feed/",
    "https://www.roboticstomorrow.com/rss/news/",
    "https://www.assemblymag.com/rss/articles",
    "https://www.plantengineering.com/feed/",
    "https://www.supplychaindive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed",
    "https://techcrunch.com/tag/ai/feed/",
    "https://www.zdnet.com/topic/artificial-intelligence/rss.xml",
    "https://www.forbes.com/innovation/feed2/",
    "https://blogs.nvidia.com/feed/",
    "https://www.nist.gov/news-events/news/rss.xml",
    "https://medium.com/feed/@DeloitteUKTechBlog",
    "https://medium.com/feed/deloitte-digital-connect",
]

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MAX_ARTICLES_PER_FEED = 8
LOOKBACK_DAYS = 7
MAX_ARTICLE_CHARS = 12000

# Free models get retired without notice — that is what silently killed this pipeline for
# months. Rather than hardcode one, we resolve against OpenRouter's live catalogue at startup
# and fall back to any capable free model still standing.
PREFERRED_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-31b-it:free",
    "openai/gpt-oss-20b:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
]
# Specialised models that cannot do general JSON extraction well.
MODEL_EXCLUDE = ("content-safety", "-code", "-vl", "guard", "embed", "tiny", "-xs-")

# feedparser has no timeout argument and will hang indefinitely on a stalled host;
# one such feed cost a run two minutes before returning nothing.
socket.setdefaulttimeout(30)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# ------------------- CONTROLLED VOCABULARY -------------------
# Free-form tagging grew the Notion database to 65 Category and 51 Industry options full of
# near-duplicates (predictive_maintenance vs Predictive Maintenance). The model must now pick
# from these lists, and anything off-list is snapped to the nearest match or dropped.
CATEGORIES = [
    "Predictive Maintenance", "Quality Control", "Defect Detection", "Computer Vision",
    "Robotics", "Collaborative Robotics", "Autonomous Systems", "Warehouse Automation",
    "Process Optimization", "Production Planning", "Supply Chain", "Energy Management",
    "Generative Design", "Simulation", "Digital Twin", "Machine Learning",
    "AI Assistant", "Workforce Development", "Safety", "Cybersecurity",
    "Edge Computing", "Industrial IoT", "Additive Manufacturing", "AI Infrastructure",
    "Process Automation", "Inventory Management", "Demand Forecasting", "Yield Optimization",
]
INDUSTRIES = [
    "Automotive", "Aerospace", "Defense", "Electronics", "Semiconductor Manufacturing",
    "Pharmaceuticals", "Life Sciences", "Medical Devices", "Food and Beverage",
    "Consumer Goods", "Chemicals", "Metals and Mining", "Energy", "Utilities",
    "Construction", "Logistics", "Warehousing", "Shipbuilding", "Textiles",
    "Industrial Equipment", "General Manufacturing", "Technology", "Robotics",
]

# Relevance gate: an article must show BOTH an AI signal and an industrial signal.
# The old single list matched on "ai " alone and let a lot of noise through.
AI_SIGNALS = [
    "ai", "a.i.", "artificial intelligence", "machine learning", "deep learning",
    "neural network", "computer vision", "generative", "llm", "foundation model",
    "algorithm", "autonomous", "robot", "digital twin", "predictive",
]
INDUSTRY_SIGNALS = [
    "manufactur", "factory", "factories", "industrial", "production line", "production",
    "plant", "assembly", "shop floor", "supply chain", "warehouse", "logistics",
    "quality control", "inspection", "maintenance", "cnc", "machining", "automotive",
    "aerospace", "semiconductor", "industry 4.0", "iiot", "oee", "throughput",
]


# ------------------- HELPERS -------------------
def log(msg):
    print(msg, flush=True)


def clean_html(raw):
    return html.unescape(BeautifulSoup(raw or "", "html.parser").get_text(" ", strip=True))


def has_signal(text, signals):
    return any(re.search(r"\b" + re.escape(s), text) for s in signals)


def is_relevant(text):
    t = text.lower()
    return has_signal(t, AI_SIGNALS) and has_signal(t, INDUSTRY_SIGNALS)


def stem_words(text):
    """Crude singular/plural fold so 'semiconductors' matches 'Semiconductor'."""
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in text.split()}


def snap_tags(raw_tags, vocabulary, limit=3):
    """Map model output onto the controlled vocabulary; drop anything with no close match.

    Handles the three ways a model drifts off-list: casing/underscores
    ("predictive_maintenance"), extra words ("automotive manufacturing"), and
    abbreviation ("pharma")."""
    canonical = {v.lower(): v for v in vocabulary}
    out = []
    for tag in raw_tags or []:
        key = re.sub(r"[_\-]+", " ", str(tag)).strip().lower()
        if not key:
            continue

        match = canonical.get(key)

        if not match:  # near-miss spelling
            close = difflib.get_close_matches(key, canonical.keys(), n=1, cutoff=0.82)
            match = canonical[close[0]] if close else None

        if not match:  # one is a word-subset of the other, e.g. "automotive manufacturing"
            key_words = stem_words(key)
            best = (0.0, 0)
            for cand_key, cand in canonical.items():
                cand_words = stem_words(cand_key)
                if cand_words <= key_words or key_words <= cand_words:
                    score = len(cand_words & key_words) / len(cand_words | key_words)
                    # Tie-break toward the shorter (more general) canonical name, so a bare
                    # "manufacturing" lands on "General Manufacturing", not a specific sector.
                    rank = (score, -len(cand))
                    if rank > best:
                        best, match = rank, cand

        if not match:  # abbreviation, e.g. "pharma" -> "Pharmaceuticals"
            if len(key) >= 5:
                prefixed = [c for k, c in canonical.items() if k.startswith(key)]
                if len(prefixed) == 1:
                    match = prefixed[0]

        if match and match not in out:
            out.append(match)
    return out[:limit]


# ------------------- MODEL RESOLUTION -------------------
def resolve_model():
    """Pick a free model that actually exists right now."""
    try:
        resp = requests.get(f"{OPENROUTER_BASE}/models", timeout=30)
        resp.raise_for_status()
        available = {m["id"] for m in resp.json().get("data", [])}
    except Exception as e:
        log(f"❌ Could not reach OpenRouter model catalogue: {e}")
        return None

    for model in PREFERRED_MODELS:
        if model in available:
            log(f"🤖 Model: {model}")
            return model

    fallback = sorted(
        m for m in available
        if m.endswith(":free") and not any(x in m.lower() for x in MODEL_EXCLUDE)
    )
    if fallback:
        log(f"⚠️ No preferred model available — falling back to {fallback[0]}")
        log("   Consider updating PREFERRED_MODELS in app.py.")
        return fallback[0]

    log("❌ No usable free model found on OpenRouter.")
    return None


# ------------------- ARTICLE FETCHING -------------------
def fetch_article_text(url):
    """Pull the real article body. RSS excerpts are usually 1-2 sentences, which is why
    the summaries were thin — the model was analysing a teaser, not the article."""
    try:
        resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=25)
        resp.raise_for_status()
    except Exception as e:
        log(f"   ↳ body fetch failed ({str(e)[:60]}), using RSS excerpt")
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                     "form", "noscript", "figure", "iframe"]):
        tag.decompose()

    # The densest block of <p> tags is reliably the article body.
    best, best_len = "", 0
    for node in soup.find_all(["article", "main", "div", "section"]):
        paragraphs = node.find_all("p", recursive=True)
        if len(paragraphs) < 3:
            continue
        text = " ".join(p.get_text(" ", strip=True) for p in paragraphs)
        if len(text) > best_len:
            best, best_len = text, len(text)

    return re.sub(r"\s+", " ", best).strip()[:MAX_ARTICLE_CHARS]


# ------------------- LLM CALL -------------------
def call_llm(prompt, model):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/barbararomeira/ai-manufacturing-digest",
        "X-Title": "AI Manufacturing Digest",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1500,
        "temperature": 0.2,
    }

    for attempt in range(3):
        try:
            resp = requests.post(f"{OPENROUTER_BASE}/chat/completions",
                                 headers=headers, json=payload, timeout=90)
            if resp.status_code == 429:
                wait = 15 * (attempt + 1)
                log(f"   ↳ rate limited, waiting {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log(f"   ↳ LLM error (attempt {attempt + 1}/3): {str(e)[:120]}")
            time.sleep(2 * (attempt + 1))

    return None


def parse_json(output):
    """Free models wrap JSON in prose, fences, or <think> blocks."""
    if not output:
        return None
    output = re.sub(r"<think>.*?</think>", "", output, flags=re.DOTALL)
    fenced = re.search(r"```(?:json)?\s*(.*?)```", output, re.DOTALL)
    if fenced:
        output = fenced.group(1)
    start, end = output.find("{"), output.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(output[start:end + 1])
    except json.JSONDecodeError:
        return None


# ------------------- USE CASE EXTRACTION -------------------
def extract_use_case(article_text, title, model):
    prompt = f"""You are a manufacturing AI analyst. Analyse the article below and decide whether it describes a CONCRETE application of AI in an industrial or manufacturing setting.

Return ONLY a JSON object.

Skip the article — return {{"skip": true, "reason": "..."}} — if ANY of these are true:
- It is a funding round, acquisition, earnings report, or executive appointment with no described application
- It is a product launch or partnership announcement with no described problem being solved
- It is opinion, survey, prediction, market-sizing, or policy commentary
- The AI is consumer-facing or non-industrial (chatbots, marketing, search)
- You cannot identify a specific operational problem it addresses

Otherwise return:
{{
  "problem": "The specific operational problem, in 2-3 sentences. Name the company/plant and include concrete details from the article — the defect rate, downtime hours, cycle time, headcount, cost, or scale involved. Do NOT write generic statements like 'manufacturers face quality challenges'.",
  "ai_solution": "What was actually built and how it works, in 2-3 sentences. Name the technique (e.g. vision-based anomaly detection, time-series forecasting on vibration sensors) and the measured result if the article gives one. Do NOT write 'they used AI to improve efficiency'.",
  "category": ["pick 1-3 from the CATEGORY list"],
  "industry": ["pick 1-2 from the INDUSTRY list"]
}}

CATEGORY list (use these exact strings): {", ".join(CATEGORIES)}

INDUSTRY list (use these exact strings): {", ".join(INDUSTRIES)}

Rules:
- Every claim must come from the article. Never invent numbers or company names.
- If the article gives no numbers, describe the mechanism precisely instead of padding with adjectives.
- Prefer skipping over producing a vague entry.

TITLE: {title}

ARTICLE:
{article_text[:MAX_ARTICLE_CHARS]}"""

    data = parse_json(call_llm(prompt, model))
    if not data:
        return None
    if data.get("skip"):
        log(f"   ↳ skipped: {str(data.get('reason', 'not a use case'))[:90]}")
        return None

    problem = str(data.get("problem", "")).strip()
    solution = str(data.get("ai_solution", "")).strip()

    # A one-line answer means the model had nothing real to say.
    if len(problem) < 80 or len(solution) < 80:
        log("   ↳ skipped: extraction too thin to be useful")
        return None

    return {
        "problem": problem[:1900],
        "ai_solution": solution[:1900],
        "category": snap_tags(data.get("category"), CATEGORIES),
        "industry": snap_tags(data.get("industry"), INDUSTRIES) or ["General Manufacturing"],
    }


# ------------------- NOTION -------------------
def notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def notion_has(title, url):
    """Check by title AND source URL — the same story is often re-titled across feeds."""
    query = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {
        "filter": {"or": [
            {"property": "Title", "title": {"equals": title[:100]}},
            {"property": "Source", "url": {"equals": url}},
        ]},
        "page_size": 1,
    }
    try:
        resp = requests.post(query, headers=notion_headers(), json=payload, timeout=30)
        resp.raise_for_status()
        return bool(resp.json().get("results"))
    except Exception as e:
        log(f"⚠️ Notion duplicate check failed: {str(e)[:120]}")
        return False


def post_to_notion(title, use_case, source, date_str):
    if DRY_RUN:
        log(f"   📝 [dry run] would add: {title[:80]}")
        log(f"      Problem : {use_case['problem']}")
        log(f"      Solution: {use_case['ai_solution']}")
        log(f"      Tags    : {use_case['category']} / {use_case['industry']}")
        return True

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Title": {"title": [{"text": {"content": title[:100]}}]},
            "Problem": {"rich_text": [{"text": {"content": use_case["problem"]}}]},
            "AI Solution": {"rich_text": [{"text": {"content": use_case["ai_solution"]}}]},
            "Category": {"multi_select": [{"name": c} for c in use_case["category"]]},
            "Industry": {"multi_select": [{"name": i} for i in use_case["industry"]]},
            "Source": {"url": source},
            "Date": {"date": {"start": date_str}},
        },
    }
    try:
        resp = requests.post("https://api.notion.com/v1/pages",
                             headers=notion_headers(), json=payload, timeout=30)
        resp.raise_for_status()
        log(f"   ✅ Added: {title[:80]}")
        return True
    except Exception as e:
        detail = getattr(e, "response", None)
        log(f"   ❌ Notion write failed: {str(e)[:120]}")
        if detail is not None:
            log(f"      {detail.text[:300]}")
        return False


# ------------------- MAIN -------------------
def main():
    log("🚀 AI Manufacturing Digest" + (" — DRY RUN (nothing will be written)" if DRY_RUN else ""))

    missing = [n for n, v in [("OPENROUTER_KEY", OPENROUTER_KEY),
                              ("NOTION_TOKEN", NOTION_TOKEN),
                              ("NOTION_DATABASE_ID", NOTION_DATABASE_ID)] if not v]
    if missing:
        log(f"❌ Missing environment variables: {', '.join(missing)}")
        return 1

    model = resolve_model()
    if not model:
        return 1

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    stats = {"seen": 0, "candidates": 0, "added": 0, "duplicate": 0,
             "irrelevant": 0, "old": 0, "no_use_case": 0, "llm_failed": 0,
             "notion_failed": 0, "dead_feeds": 0}

    for feed_url in FEEDS:
        log(f"\n📡 {feed_url}")
        try:
            feed = feedparser.parse(feed_url, agent=BROWSER_UA)
        except Exception as e:
            log(f"   💥 Feed error: {str(e)[:120]}")
            stats["dead_feeds"] += 1
            continue

        if not feed.entries:
            log(f"   💀 No entries (status {feed.get('status')}) — feed may be dead")
            stats["dead_feeds"] += 1
            continue

        for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            stats["seen"] += 1

            published = entry.get("published_parsed") or entry.get("updated_parsed")
            published_dt = (datetime(*published[:6], tzinfo=timezone.utc)
                            if published else datetime.now(timezone.utc))
            if published_dt < cutoff:
                stats["old"] += 1
                continue

            content = entry.get("content") or []
            excerpt = clean_html(
                (entry.get("summary") or "") + " " +
                (content[0].get("value", "") if content else "")
            )

            if not is_relevant(f"{title} {excerpt}"):
                stats["irrelevant"] += 1
                continue

            # In a dry run we want to see extractions for everything, including rows already
            # filed, so the dedup check is bypassed.
            if not DRY_RUN and notion_has(title, link):
                stats["duplicate"] += 1
                log(f"   ⏭️ Already in Notion: {title[:70]}")
                continue

            stats["candidates"] += 1
            log(f"   🧠 {title[:80]}")

            body = fetch_article_text(link)
            text = body if len(body) > len(excerpt) else excerpt
            if len(text) < 200:
                log("   ↳ skipped: not enough text to analyse")
                stats["no_use_case"] += 1
                continue

            use_case = extract_use_case(text, title, model)
            if use_case is None:
                stats["no_use_case"] += 1
            elif post_to_notion(title, use_case, link,
                                published_dt.strftime("%Y-%m-%d")):
                stats["added"] += 1
            else:
                stats["notion_failed"] += 1

            time.sleep(2)

    log("\n" + "=" * 52)
    log(f"  Articles seen        {stats['seen']}")
    log(f"  Too old              {stats['old']}")
    log(f"  Not relevant         {stats['irrelevant']}")
    log(f"  Already in Notion    {stats['duplicate']}")
    log(f"  Analysed             {stats['candidates']}")
    log(f"  No usable use case   {stats['no_use_case']}")
    log(f"  Notion write failed  {stats['notion_failed']}")
    log(f"  Dead feeds           {stats['dead_feeds']}")
    log(f"  ✅ ADDED             {stats['added']}")
    log("=" * 52)

    # Fail loudly. The previous version swallowed every error and exited 0, so GitHub
    # reported success every Monday while writing nothing to Notion for months.
    if stats["notion_failed"] and not stats["added"]:
        log("\n❌ Every Notion write failed — check NOTION_TOKEN and database permissions.")
        return 1
    if stats["candidates"] and not stats["added"]:
        log("\n❌ Analysed articles but added nothing — the model or prompt is failing.")
        return 1
    if stats["dead_feeds"] > len(FEEDS) // 2:
        log("\n❌ More than half the feeds returned nothing.")
        return 1

    log("\n✅ Done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
