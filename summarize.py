import os
import sys
import feedparser
import requests
from datetime import datetime, timezone
import time
import re
import json
from math import ceil

# =======================
# Load environment variables
# =======================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# Quick validation
if not OPENROUTER_KEY:
    print("❌ OPENROUTER_KEY not found! Please check your GitHub Secrets and workflow.")
    sys.exit(1)
else:
    print("✅ OPENROUTER_KEY loaded correctly.")

if not NOTION_TOKEN:
    print("❌ NOTION_TOKEN not found! Please check your GitHub Secrets and workflow.")
    sys.exit(1)
else:
    print("✅ NOTION_TOKEN loaded correctly.")

if not NOTION_DATABASE_ID:
    print("❌ NOTION_DATABASE_ID not found! Please check your GitHub Secrets and workflow.")
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
# Keywords for filtering relevant articles
# =======================
KEYWORDS = [
    'AI', 'artificial intelligence', 'machine learning', 'deep learning', 'neural network',
    'LLM', 'large language model', 'generative AI', 'computer vision', 'object detection',
    'anomaly detection', 'predictive maintenance', 'condition monitoring', 'failure prediction',
    'smart factory', 'Industry 4.0', 'IIoT', 'digital twin', 'simulation', 'edge AI',
    'robot', 'robotics', 'automation', 'autonomous', 'cobots', 'collaborative robot',
    'AMR', 'AGV', 'quality control', 'defect detection', 'visual inspection',
    'process optimization', 'downtime reduction', 'energy optimization', 'factory', 'plant',
    'manufacturing innovation', 'production efficiency', 'industrial AI', 'AI deployment', 'industrial automation'
]

# =======================
# Helper functions
# =======================
def is_relevant(text):
    text = text.lower()
    return any(kw.lower() in text for kw in KEYWORDS)

def clean_text(text):
    text = re.sub(r'<[^>]+>', '', text)  # Remove HTML tags
    text = re.sub(r'\s+', ' ', text)     # Remove extra whitespace
    return text.strip()

def chunk_text(text, max_chars=2000):
    """Split text into manageable chunks"""
    text = text.strip()
    return [text[i:i+max_chars] for i in range(0, len(text), max_chars)]

def parse_model_output(content):
    """Clean and parse JSON from model output"""
    content = re.sub(r"```json(.*?)```", r"\1", content, flags=re.DOTALL)
    content = re.sub(r"```(.*?)```", r"\1", content, flags=re.DOTALL)
    content = content.strip()
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data
        return None
    except json.JSONDecodeError:
        match = re.search(r"(\[.*\])", content, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except:
                return None
        return None

# =======================
# Summarize a single chunk
# =======================
def summarize_chunk(chunk_text, article_url, pub_date):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "https://github.com/yourusername/ai-manufacturing-digest",
        "X-Title": "AI Use Case Extractor"
    }

    prompt = (
        "You are an expert industrial analyst. From the article below, extract the most relevant AI use case "
        "in manufacturing or industrial applications. Return exactly ONE use case as a JSON object with fields:\n"
        "- title: short descriptive title\n"
        "- problem: problem the AI solves\n"
        "- ai_solution: AI technique(s) used\n"
        "- category: Manufacturing | Logistic | Supply Chain\n"
        "- industry: Automotive | Food | etc.\n"
        "- source: article URL\n"
        "- date: publication date in ISO format\n\n"
        f"Article:\n{chunk_text}\n"
        f"URL: {article_url}\nDate: {pub_date}\n\n"
        "Return only JSON. If no use case exists, return {}."
    )

    payload = {
        "model": "mistralai/mistral-7b-instruct:free",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1800
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=90
        )
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content'].strip()
            data = parse_model_output(content)
            if data:
                return data
            else:
                print("❌ Failed to parse JSON from model output")
                return None
        else:
            print(f"❌ Model call failed {response.status_code}: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Exception during model call: {e}")
        return None

# =======================
# Add use case to Notion
# =======================
def add_to_notion(use_case):
    if not use_case:
        return
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
            "Date": {"date": {"start": use_case.get("date", datetime.now(timezone.utc).isoformat())[:10]}}
        }
    }
    try:
        response = requests.post(
            "https://api.notion.com/v1/pages",
            headers=headers,
            json=payload
        )
        if response.status_code == 200:
            print(f"✅ Added to Notion: {use_case.get('title')}")
        else:
            print(f"❌ Notion error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ Exception posting to Notion: {e}")

# =======================
# Process a full article (chunk if necessary)
# =======================
def summarize_article(article_text, article_url, pub_date):
    chunks = chunk_text(article_text, max_chars=2000)
    best_use_case = None

    for idx, chunk in enumerate(chunks):
        print(f"  ➤ Model chunk {idx+1}/{len(chunks)} ...")
        result = summarize_chunk(chunk, article_url, pub_date)
        if result:
            # Option A: Take first non-empty valid use case
            best_use_case = result
            break
        else:
            print(f"  ❌ Chunk {idx+1} failed or returned invalid data")

    return best_use_case

# =======================
# Main workflow
# =======================
def main():
    seen_urls = set()
    for feed_url in FEEDS:
        try:
            print(f"\n📡 Fetching feed: {feed_url}")
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:5]:
                if entry.link in seen_urls:
                    continue
                seen_urls.add(entry.link)

                title = entry.get("title","No Title")
                desc = entry.get("summary","")
                content = entry.get("content", [{}])[0].get("value", "")
                text = clean_text(desc + " " + content)

                if len(text) < 100:
                    print(f"⏭️ Too short: {title}")
                    continue
                if not is_relevant(title + " " + text):
                    print(f"⏭️ Not relevant: {title}")
                    continue

                pub_date = entry.get('published', datetime.now(timezone.utc).isoformat())
                if 'T' not in pub_date:
                    pub_date = datetime.now(timezone.utc).isoformat()

                print(f"\n🔎 Processing article: {title} ({len(text)} chars)")
                use_case = summarize_article(text, entry.link, pub_date)

                if use_case:
                    print(f"📤 Sending to Notion → {use_case.get('title')}")
                    add_to_notion(use_case)
                    time.sleep(12)  # Notion & API rate limit
                else:
                    print(f"⏭️ No valid use case found: {title}")

        except Exception as e:
            print(f"❌ Error processing feed {feed_url}: {e}")

    print("\n✅ Done.")

if __name__ == "__main__":
    main()
