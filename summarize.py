import os
import sys
import feedparser
import requests
from datetime import datetime, timezone
import time
import re
import json

# =======================
# Load environment variables (GitHub Secrets)
# =======================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")  # OpenRouter API key for Mistral
NOTION_TOKEN = os.getenv("NOTION_TOKEN")      # Notion integration token
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")  # Notion database ID

# =======================
# Quick validation of secrets
# =======================
if not OPENROUTER_KEY:
    print("❌ OPENROUTER_KEY not found! Exiting.")
    sys.exit(1)
else:
    print("✅ OPENROUTER_KEY loaded correctly.")

if not NOTION_TOKEN:
    print("❌ NOTION_TOKEN not found! Exiting.")
    sys.exit(1)
else:
    print("✅ NOTION_TOKEN loaded correctly.")

if not NOTION_DATABASE_ID:
    print("❌ NOTION_DATABASE_ID not found! Exiting.")
    sys.exit(1)
else:
    print("✅ NOTION_DATABASE_ID loaded correctly.")

# =======================
# RSS feeds to process
# =======================
FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/",
]

# =======================
# Keywords for relevance
# =======================
KEYWORDS = [
    'AI', 'artificial intelligence', 'machine learning', 'deep learning', 'neural network',
    'LLM', 'large language model', 'generative AI', 'computer vision', 'object detection',
    'anomaly detection', 'predictive maintenance', 'condition monitoring', 'failure prediction',
    'smart factory', 'Industry 4.0', 'IIoT', 'digital twin', 'simulation', 'edge AI',
    'robot', 'robotics', 'automation', 'autonomous', 'cobots', 'collaborative robot',
    'AMR', 'AGV', 'quality control', 'defect detection', 'visual inspection',
    'process optimization', 'downtime reduction', 'energy optimization', 'factory', 'plant',
    'manufacturing innovation', 'production improvement', 'industrial AI', 'AI application'
]

# =======================
# Utility: check if article contains relevant keywords
# =======================
def is_relevant(text):
    text = text.lower()
    return any(kw.lower() in text for kw in KEYWORDS)

# =======================
# Utility: clean text by removing HTML and extra spaces
# =======================
def clean_text(text):
    text = re.sub(r'<[^>]+>', '', text)  # Remove HTML tags
    text = re.sub(r'\s+', ' ', text)     # Collapse whitespace
    return text.strip()

# =======================
# Split long text into chunks (~3000 chars) for the model
# =======================
def chunk_text(text, max_chars=3000):
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        # Try to break at last sentence if possible
        if end < len(text):
            period_pos = text.rfind('.', start, end)
            if period_pos != -1:
                end = period_pos + 1
        chunks.append(text[start:end].strip())
        start = end
    return chunks

# =======================
# Summarize a single chunk using Mistral 7B
# =======================
def summarize_chunk(chunk, article_url):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "https://github.com/yourusername/ai-manufacturing-digest",
        "X-Title": "AI Use Case Extractor"
    }

    prompt = (
        "You are an expert industrial analyst. From the article below, extract the most relevant AI use case in manufacturing.\n"
        "If multiple use cases exist, pick the most relevant one and note in a 'comment' field that other use cases may exist.\n"
        "Return exactly one JSON object with the fields:\n"
        "- title: short descriptive title\n"
        "- problem: problem the AI solves\n"
        "- ai_solution: AI technique(s) used\n"
        "- category: Manufacturing | Logistic | Supply Chain\n"
        "- industry: Automotive | Food | etc.\n"
        "- source: article URL\n"
        "- date: publication date in ISO format\n"
        "- comment: optional comment\n\n"
        f"Article URL: {article_url}\n"
        f"Article Content:\n{chunk}"
    )

    payload = {
        "model": "mistralai/mistral-7b-instruct:free",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=60
        )
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content'].strip()
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    return data
                print("❌ Model returned invalid JSON format (expected dict)")
                return None
            except json.JSONDecodeError:
                print("❌ Failed to parse JSON from model output")
                return None
        else:
            print(f"❌ Model call failed {response.status_code}: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Exception during model call: {e}")
        return None

# =======================
# Add a single use case to Notion
# =======================
def add_to_notion(use_case):
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Title": {"title": [{"text": {"content": use_case.get("title","")[:199]}}]},
            "Problem": {"rich_text": [{"text": {"content": use_case.get("problem","")[:2000]}}]},
            "AI Solution": {"rich_text": [{"text": {"content": use_case.get("ai_solution","")[:2000]}}]},
            "Category": {"multi_select": [{"name": use_case.get("category","Unknown")}]},
            "Industry": {"multi_select": [{"name": use_case.get("industry","Unknown")}]},
            "Source": {"url": use_case.get("source","")},
            "Date": {"date": {"start": use_case.get("date", datetime.now(timezone.utc).isoformat())[:10]}},
            "Comment": {"rich_text": [{"text": {"content": use_case.get("comment","")[:2000]}}]}
        }
    }

    try:
        response = requests.post(
            "https://api.notion.com/v1/pages",
            json=payload,
            headers=headers
        )
        if response.status_code == 200:
            print(f"✅ Added to Notion: {use_case.get('title')}")
        else:
            print(f"❌ Notion error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ Exception posting to Notion: {e}")

# =======================
# Process a single article
# =======================
def process_article(entry):
    title = entry.get('title', 'No Title')
    desc = entry.get('summary', '')
    content = entry.get('content', [{}])[0].get('value', '')
    text = clean_text(desc + ' ' + content)

    if not is_relevant(title + " " + text):
        print(f"⏭️ Not relevant: {title}")
        return

    if len(text) < 100:
        print(f"⏭️ Too short: {title}")
        return

    print(f"🔎 Processing article: {title} ({len(text)} chars)")

    # Split article into chunks
    chunks = chunk_text(text)
    all_use_cases = []
    for i, chunk in enumerate(chunks):
        print(f"  ➤ Model chunk {i+1}/{len(chunks)} ...")
        uc = summarize_chunk(chunk, entry.link)
        if uc:
            all_use_cases.append(uc)
        else:
            print(f"  ❌ Chunk {i+1} failed or returned invalid data")

    if not all_use_cases:
        print(f"⏭️ No valid use case found: {title}")
        return

    # Option A: pick most relevant use case from chunks
    main_use_case = all_use_cases[0]
    if len(all_use_cases) > 1:
        main_use_case['comment'] = f"Article contains {len(all_use_cases)} use case chunks; showing primary."

    # Fill Notion fields
    main_use_case["source"] = entry.link
    main_use_case["date"] = entry.get('published', datetime.now(timezone.utc).isoformat())

    # Send to Notion
    add_to_notion(main_use_case)

# =======================
# Main function: iterate feeds
# =======================
def main():
    seen_urls = set()
    for feed_url in FEEDS:
        print(f"\n📡 Fetching feed: {feed_url}")
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:  # limit to latest 5 per feed
                if entry.link in seen_urls:
                    continue
                seen_urls.add(entry.link)
                process_article(entry)
        except Exception as e:
            print(f"❌ Error processing feed {feed_url}: {e}")

    print("\n✅ Done.")

# =======================
# Entry point
# =======================
if __name__ == "__main__":
    main()
