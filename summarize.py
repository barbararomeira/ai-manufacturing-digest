#!/usr/bin/env python3
import os
import re
import time
import json
import requests
import feedparser
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────
# ENVIRONMENT VARIABLES
# ─────────────────────────────────────────────────────────────
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

MODEL = "deepseek/deepseek-r1-distill-qwen-32b"  # stable + fast


# ─────────────────────────────────────────────────────────────
# HTML CLEANING
# ─────────────────────────────────────────────────────────────
def clean_html(html):
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")

    # Remove scripts, styles, ads, forms
    for tag in soup(["script", "style", "noscript", "form", "footer", "header", "iframe"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text


# ─────────────────────────────────────────────────────────────
# TEXT CHUNKING
# ─────────────────────────────────────────────────────────────
def chunk_text(text, max_len=7000):
    words = text.split()
    chunks = []
    current = []

    for w in words:
        current.append(w)
        if len(" ".join(current)) > max_len:
            chunks.append(" ".join(current))
            current = []
    if current:
        chunks.append(" ".join(current))
    return chunks


# ─────────────────────────────────────────────────────────────
# OPENROUTER LLM CALL
# ─────────────────────────────────────────────────────────────
def llm(prompt):
    url = "https://api.openrouter.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "https://github.com",
        "X-Title": "AI Manufacturing Digest",
        "Content-Type": "application/json",
    }
    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }

    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=data, timeout=40)
            r.raise_for_status()
            out = r.json()["choices"][0]["message"]["content"]
            return out
        except Exception as e:
            print(f"⚠️ LLM error on {url} (attempt {attempt+1}): {e}")
            time.sleep(3)
    return None


# ─────────────────────────────────────────────────────────────
# EXTRACT USE CASES
# ─────────────────────────────────────────────────────────────
def extract_use_case(text):
    prompt = f"""
Given the article below, extract ONLY ONE item:

1. A **concise manufacturing-relevant AI use case** (NOT business news, not market analysis)
2. Return it in EXACTLY this JSON:
{{
  "use_case": "string or empty"
}}

Article:
{text}
"""
    reply = llm(prompt)
    if not reply:
        return None

    try:
        data = json.loads(reply)
        return data.get("use_case")
    except:
        return None


# ─────────────────────────────────────────────────────────────
# NOTION DUPLICATE CHECK
# ─────────────────────────────────────────────────────────────
def notion_has_article(url, title):
    """Prevent duplicates by checking if URL or Title already exists."""
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    query = {
        "filter": {
            "or": [
                {"property": "Source", "url": {"equals": url}},
                {"property": "Title", "title": {"equals": title[:100]}}
            ]
        }
    }

    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
            headers=headers,
            json=query,
            timeout=30
        )
        r.raise_for_status()
        return len(r.json().get("results", [])) > 0
    except Exception as e:
        print(f"⚠️ Notion query failed (continuing): {e}")
        return False


# ─────────────────────────────────────────────────────────────
# POST TO NOTION
# ─────────────────────────────────────────────────────────────
def post_to_notion(title, url, use_case):
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    data = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Title": {"title": [{"text": {"content": title}}]},
            "Source": {"url": url},
            "Use Case": {"rich_text": [{"text": {"content": use_case}}]},
        }
    }

    try:
        r = requests.post("https://api.notion.com/v1/pages", headers=headers, json=data)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Notion error: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# MAIN: PROCESS FEEDS
# ─────────────────────────────────────────────────────────────
FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/",
]


def process_feed(feed_url):
    print(f"\n📡 Feed: {feed_url}")
    feed = feedparser.parse(feed_url)

    for entry in feed.entries:
        title = entry.title.strip()
        link = entry.link

        print(f"🧠 Processing: {title}")

        # 1. Notion duplicate check
        if notion_has_article(link, title):
            print(f"⏭️ Already in Notion: {title}")
            continue

        # 2. Extract & clean text
        raw = entry.get("content", [{}])[0].get("value") or entry.get("summary", "")
        text = clean_html(raw)
        if not text:
            print("⏭️ No text found.")
            continue

        # 3. Chunking for long articles
        chunks = chunk_text(text)
        merged_use_case = None

        for c in chunks:
            uc = extract_use_case(c)
            if uc:
                merged_use_case = uc
                break

        if not merged_use_case:
            print(f"⏭️ No use case: {title}")
            continue

        # 4. Post to Notion
        if post_to_notion(title, link, merged_use_case):
            print(f"✅ Added: {title}")
        else:
            print(f"❌ Failed to add: {title}")


# ─────────────────────────────────────────────────────────────
# EXECUTION
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 Starting Simple AI Manufacturing Digest (DeepSeek/Qwen)")
    for feed in FEEDS:
        process_feed(feed)
    print("✅ Done!")
