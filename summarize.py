#!/usr/bin/env python3
import os
import json
import time
import feedparser
import requests
import socket
from bs4 import BeautifulSoup
import html
from datetime import datetime

# ------------------- DNS RESOLUTION VIA DoH -------------------
def resolve_domain_doh(domain):
    try:
        resp = requests.get(f"https://dns.google/resolve?name={domain}&type=A", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        for answer in data.get("Answer", []):
            if answer["type"] == 1:  # A record
                return answer["data"]
    except Exception as e:
        print(f"⚠️ DoH resolution failed: {e}")
    return None

# Resolve once at startup
OPENROUTER_IP = resolve_domain_doh("api.openrouter.ai")
if not OPENROUTER_IP:
    raise SystemExit("❌ Could not resolve api.openrouter.ai using DNS-over-HTTPS")

print(f"✅ Using IP {OPENROUTER_IP} for api.openrouter.ai")

# Patch socket.getaddrinfo to return our IP
original_getaddrinfo = socket.getaddrinfo
def patched_getaddrinfo(*args, **kwargs):
    if args[0] == "api.openrouter.ai":
        return original_getaddrinfo(OPENROUTER_IP, *args[1:], **kwargs)
    return original_getaddrinfo(*args, **kwargs)

socket.getaddrinfo = patched_getaddrinfo

# ------------------- CONFIG -------------------
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "").strip()
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "").strip()

FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.iot-worlds.com/feed/",
    "https://www.smartindustry.com/rss/articles/"
]

MODEL = "mistral/mistral-7b-instruct"
MAX_ARTICLES_PER_FEED = 8

if not all([OPENROUTER_KEY, NOTION_TOKEN, NOTION_DATABASE_ID]):
    raise SystemExit("❌ Missing required environment variables")

RELEVANCE_KEYWORDS = [
    "manufactur", "factory", "industrial", "production", "plant", "assembly", "shop floor",
    "ai ", "artificial intelligence", "machine learning", "ml ", "deep learning", "neural network",
    "computer vision", "predictive maintenance", "digital twin", "iiot", "industry 4.0",
    "smart factory", "automation", "robotics", "cobots", "agv", "autonomous mobile robot",
    "process mining", "anomaly detection", "yield optimization", "cnc", "machining", "3d printing",
    "additive manufacturing", "quality control", "defect detection", "visual inspection",
    "supply chain", "logistics", "warehouse automation", "automotive", "aerospace", "semiconductor",
    "electronics", "pharmaceutical", "food and beverage", "chemical", "metal", "steel",
    "plastic", "textile", "packaging"
]

def is_relevant(text):
    return any(kw in text.lower() for kw in RELEVANCE_KEYWORDS)

def clean_html(raw_text):
    soup = BeautifulSoup(raw_text, "html.parser")
    return html.unescape(soup.get_text(" ", strip=True))

def call_llm(prompt, max_tokens=800):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/your-repo",
        "X-Title": "AI Manufacturing Digest"
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.4
    }
    try:
        response = requests.post(
            "https://api.openrouter.ai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=50
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"⚠️ LLM error: {e}")
        return None

def extract_use_case(article_text, title, url):
    prompt = f"""
You are an expert in AI for manufacturing. Extract ONE concrete use case from this article.

Return a JSON with:
- "problem": the manufacturing challenge
- "ai_solution": how AI solves it
- "category": list of 2-4 technical tags (e.g., ["predictive maintenance", "computer vision"])
- "industry": list of applicable industries (e.g., ["automotive", "aerospace"])

If NOT a valid AI+manufacturing use case, return: {{"skip": true}}

Title: {title}
Text:
{article_text[:5000]}
"""
    output = call_llm(prompt)
    if not output:
        return None
    try:
        if output.startswith("```json"):
            output = output.split("```json", 1)[1].split("```", 1)[0]
        elif output.startswith("```"):
            output = output.split("```", 1)[1].split("```", 1)[0]
        data = json.loads(output.strip())
        if data.get("skip"):
            return None
        category = data.get("category", [])
        industry = data.get("industry", [])
        if isinstance(category, str):
            category = [category]
        if isinstance(industry, str):
            industry = [industry]
        return {
            "problem": str(data.get("problem", ""))[:1000],
            "ai_solution": str(data.get("ai_solution", ""))[:1000],
            "category": [str(t).strip()[:50] for t in category if t],
            "industry": [str(i).strip()[:50] for i in industry if i] or ["General"]
        }
    except Exception as e:
        print(f"❌ JSON parse failed: {e}")
        return None

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
            "Problem": {"rich_text": [{"text": {"content": problem or "N/A"}}]},
            "AI Solution": {"rich_text": [{"text": {"content": ai_solution or "N/A"}}]},
            "Category": {"multi_select": [{"name": tag} for tag in category[:5]]},
            "Industry": {"multi_select": [{"name": ind} for ind in industry[:5]]},
            "Source": {"url": source},
            "Date": {"date": {"start": date_str}}
        }
    }
    try:
        resp = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload)
        resp.raise_for_status()
        print(f"✅ Added to Notion: {title}")
        return True
    except Exception as e:
        print(f"❌ Notion API error: {e}")
        return False

def main():
    print("🚀 Starting AI Manufacturing Use Case Extractor (DoH DNS Fix)")
    processed_titles = set()

    for feed_url in FEEDS:
        print(f"\n📡 Fetching feed: {feed_url}")
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
                title = entry.get("title", "").strip()
                if not title or title in processed_titles:
                    continue
                processed_titles.add(title)

                raw_content = entry.get("summary", "") + " " + entry.get("content", [{}])[0].get("value", "")
                clean_content = clean_html(raw_content)
                pub_time = entry.get("published_parsed")
                date_str = time.strftime("%Y-%m-%d", pub_time) if pub_time else datetime.utcnow().strftime("%Y-%m-%d")

                if not is_relevant(title + " " + clean_content):
                    print(f"⏭️ Skipped (not relevant): {title}")
                    continue

                print(f"🧠 Analyzing: {title}")
                use_case = extract_use_case(clean_content, title, entry.link)
                if not use_case:
                    print(f"⏭️ No valid use case: {title}")
                    continue

                post_to_notion(
                    title=title,
                    problem=use_case["problem"],
                    ai_solution=use_case["ai_solution"],
                    category=use_case["category"],
                    industry=use_case["industry"],
                    source=entry.link,
                    date_str=date_str
                )
                time.sleep(2.5)

        except Exception as e:
            print(f"💥 Error processing {feed_url}: {e}")

    print("\n✅ Workflow completed!")

if __name__ == "__main__":
    main()
