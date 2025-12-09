#!/usr/bin/env python3
import os
import time
import json
import requests
import feedparser
from bs4 import BeautifulSoup

# -----------------------------------------
# CONFIG
# -----------------------------------------
MODEL = "google/gemini-2.0-flash-thinking-exp:free"
OPENROUTER_URL = "https://api.openrouter.ai/v1/chat/completions"
TIMEOUT = 30
MAX_RETRIES = 5
CHUNK_SIZE = 3500


# -----------------------------------------
# Read env variables
# -----------------------------------------
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

print("🔧 Environment check:")
print("  OPENROUTER_KEY:", "OK" if OPENROUTER_KEY else "MISSING!")
print("  NOTION_TOKEN:", "OK" if NOTION_TOKEN else "MISSING!")
print("  NOTION_DATABASE_ID:", "OK" if NOTION_DATABASE_ID else "MISSING!")
print()


# -----------------------------------------
# Clean HTML safely
# -----------------------------------------
def clean_html(raw_html):
    soup = BeautifulSoup(raw_html, "html.parser")
    cleaned = soup.get_text(separator=" ", strip=True)
    return cleaned


# -----------------------------------------
# OpenRouter API call with retries
# -----------------------------------------
def call_model(prompt):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.2
                },
                timeout=TIMEOUT
            )

            # If DNS / network fails, this is where it happens
            if response.status_code != 200:
                print(f"  ❌ API Error {response.status_code}: {response.text}")
                continue

            return response.json()["choices"][0]["message"]["content"]

        except requests.exceptions.RequestException as e:
            print(f"  ⚠️ Network error (attempt {attempt}/{MAX_RETRIES}): {e}")

        # exponential backoff
        time.sleep(2 ** attempt)

    print("  ❌ Model gave no result after retries")
    return None


# -----------------------------------------
# Build prompt for the model
# -----------------------------------------
def build_prompt(text):
    return f"""
You will receive an article chunk. Extract ONLY if present:

{{
  "title": "...",
  "summary": "...",
  "use_case": "..."
}}

Rules:
- MUST return valid JSON only.
- No explanations.
- If no use case exists, return: {{"use_case": null}}
- Never output HTML.

Article chunk:
{text}
"""


# -----------------------------------------
# Process a single article
# -----------------------------------------
def summarize_article(title, html_content):
    print(f"🔎 Processing: {title}")

    text = clean_html(html_content)

    if len(text) < 200:
        print("  ⏭️ Too short, skipping.")
        return None

    # Split into chunks
    chunks = [
        text[i:i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)
    ]

    full_summary = ""
    final_use_case = None

    for idx, chunk in enumerate(chunks, start=1):
        print(f"  ➤ Chunk {idx}/{len(chunks)}...")

        prompt = build_prompt(chunk)
        output = call_model(prompt)

        if not output:
            print("  ❌ Model returned nothing for chunk.")
            continue

        # Parse JSON safely
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            print("  ❌ Invalid JSON returned by model.")
            continue

        # Accumulate findings
        if "summary" in data:
            full_summary += data["summary"] + " "

        if not final_use_case and "use_case" in data and data["use_case"]:
            final_use_case = data["use_case"]

    if not full_summary.strip():
        print("  ⏭️ No usable summary extracted.")
        return None

    return {
        "title": title,
        "summary": full_summary.strip(),
        "use_case": final_use_case
    }


# -----------------------------------------
# Feeds to process
# -----------------------------------------
FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/"
]


# -----------------------------------------
# MAIN LOOP
# -----------------------------------------
for feed_url in FEEDS:
    print(f"\n📡 Fetching feed: {feed_url}")
    feed = feedparser.parse(feed_url)

    for entry in feed.entries:
        title = entry.title
        raw = entry.get("content", [{"value": entry.get("summary", "")}])[0]["value"]

        result = summarize_article(title, raw)

        if not result:
            print(f"⏭️ No summary saved for: {title}")
            continue

        print(f"✅ Summary extracted: {result['title'][:40]}...")
        print()


print("\n🎉 DONE — script finished cleanly.\n")

