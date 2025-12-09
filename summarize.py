#!/usr/bin/env python3
import os
import json
import time
import feedparser
import requests
from bs4 import BeautifulSoup
import html
from datetime import datetime, timedelta

# ------------------- CONFIG -------------------
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "").strip()
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "").strip()

FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/"
]

MODEL = "tngtech/deepseek-r1t2-chimera:free"
MAX_ARTICLES_PER_FEED = 6

# Two endpoints to avoid GitHub Actions DNS issues
OPENROUTER_ENDPOINTS = [
    "https://api.openrouter.ai/v1/chat/completions",
    "https://openrouter.ai/api/v1/chat/completions"
]

if not all([OPENROUTER_KEY, NOTION_TOKEN, NOTION_DATABASE_ID]):
    raise SystemExit("❌ Missing environment variables")

RELEVANCE_KEYWORDS = [
    "manufactur", "factory", "industrial", "production", "ai ", "artificial intelligence",
    "machine learning", "robotics", "automation", "predictive maintenance", "digital twin",
    "smart factory", "computer vision", "quality control", "iiot", "industry 4.0",
    "automotive", "aerospace", "cnc", "defect detection", "supply chain"
]

# ------------------- WEEKLY FILTER SETUP -------------------
ONE_WEEK_AGO = datetime.utcnow() - timedelta(days=7)


# ------------------- DUPLICATE CHECK -------------------
def notion_has_article(source_url, title):
    """
    Check if Notion already contains an article with this exact Source URL
    OR Title. Prevents duplicates.
    """
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    payload = {
        "filter": {
            "or": [
                {"property": "Source", "url": {"equals": source_url}},
                {"property": "Title", "title": {"equals": title[:100]}}
            ]
        },
        "page_size": 1
    }

    try:
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
            headers=headers,
            json=payload,
            timeout=20
        )
        resp.raise_for_status()
        return len(resp.json().get("results", [])) > 0
    except Exception as e:
        print(f"⚠️ Notion duplicate-check error (ignoring): {e}")
        return False


def is_relevant(text):
    return any(kw in text.lower() for kw in RELEVANCE_KEYWORDS)


def clean_html(raw):
    return html.unescape(BeautifulSoup(raw, "html.parser").get_text(" ", strip=True))


# ------------------- LLM CALL WITH FALLBACK ENDPOINTS -------------------
def call_llm(prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/your-repo",
        "X-Title": "AI Manufacturing Digest"
    }

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800,
        "temperature": 0.3
    }

    for endpoint in OPENROUTER_ENDPOINTS:
        for attempt in range(2):
            try:
                print(f"🌐 Trying LLM endpoint: {endpoint} (attempt {attempt+1})")
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                print(f"⚠️ LLM error on {endpoint} (attempt {attempt+1}): {e}")
                time.sleep(1)

    print("❌ All OpenRouter endpoints failed.")
    return None


# ------------------- USE CASE EXTRACTION -------------------
def extract_use_case(article_text, title, url):
    prompt = f"""
You are an AI application expert for manufacturing. Extract ONE AI use case in manufacturing from this article. Return JSON with:
- "problem": challenge address in the news
- "ai_solution": how AI solves it
- "category": ["tag1", "tag2"]
- "industry": ["sector1", "sector2"]

If not relevant, return {{"skip": true}}.

Title: {title}
Text: {article_text[:4000]}
"""

    output = call_llm(prompt)
    if not output:
        return None

    try:
        if "```json" in output:
            output = output.split("```json")[1].split("```")[0]

        data = json.loads(output.strip())

        if data.get("skip"):
            return None

        return {
            "problem": str(data.get("problem", ""))[:1000],
            "ai_solution": str(data.get("ai_solution", ""))[:1000],
            "category": [str(t)[:50] for t in (data.get("category") or [])],
            "industry": [str(i)[:50] for i in (data.get("industry") or [])] or ["General"]
        }
    except Exception as e:
        print(f"❌ JSON error: {e}")
        return None


# ------------------- NOTION POSTING -------------------
def post_to_notion(title, problem, ai_solution, category, industry, source, date_str):
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Title": {"title": [{"text": {"content": title[:100]}}]},
            "Problem": {"rich_text": [{"text": {"content": problem}}]},
            "AI Solution": {"rich_text": [{"text": {"content": ai_solution}}]},
            "Category": {"multi_select": [{"name": c} for c in category[:5]]},
            "Industry": {"multi_select": [{"name": i} for i in industry[:5]]},
            "Source": {"url": source},
            "Date": {"date": {"start": date_str}}
        }
    }

    try:
        requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload).raise_for_status()
        print(f"✅ Added: {title}")
        return True
    except Exception as e:
        print(f"❌ Notion error: {e}")
        return False


# ------------------- MAIN -------------------
def main():
    print("🚀 Starting AI Manufacturing Digest")
    seen = set()

    for feed_url in FEEDS:
        print(f"\n📡 Feed: {feed_url}")

        try:
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:

                title = entry.title.strip()
                if not title or title in seen:
                    continue
                seen.add(title)

                # WEEKLY FILTER — skip articles older than 7 days
                pub = entry.get("published_parsed")
                if pub:
                    pub_dt = datetime(*pub[:6])
                else:
                    pub_dt = datetime.utcnow()

                if pub_dt < ONE_WEEK_AGO:
                    print(f"⏭️ Too old (>{7} days): {title}")
                    continue

                date_str = pub_dt.strftime("%Y-%m-%d")

                # Check for duplicates in Notion
                if notion_has_article(entry.link, title):
                    print(f"⏭️ Already exists in Notion: {title}")
                    continue

                # Extract text
                text = clean_html(
                    entry.get("summary", "") +
                    " " +
                    entry.get("content", [{}])[0].get("value", "")
                )

                if not is_relevant(title + " " + text):
                    print(f"⏭️ Skipped (not relevant): {title}")
                    continue

                print(f"🧠 Processing: {title}")

                use_case = extract_use_case(text, title, entry.link)

                if use_case:
                    post_to_notion(
                        title,
                        use_case["problem"],
                        use_case["ai_solution"],
                        use_case["category"],
                        use_case["industry"],
                        entry.link,
                        date_str
                    )
                else:
                    print(f"⏭️ No use case: {title}")

                time.sleep(1.2)

        except Exception as e:
            print(f"💥 Feed error: {e}")

    print("\n✅ Done!")


if __name__ == "__main__":
    main()
