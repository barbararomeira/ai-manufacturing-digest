import os
import sys
import feedparser
import requests
from datetime import datetime, timezone
import time
import re
import json

# =======================
# Load environment variables
# =======================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

for var, name in [(OPENROUTER_KEY, "OPENROUTER_KEY"), (NOTION_TOKEN, "NOTION_TOKEN"), (NOTION_DATABASE_ID, "NOTION_DATABASE_ID")]:
    if not var:
        print(f"❌ {name} not found! Exiting.")
        sys.exit(1)
    else:
        print(f"✅ {name} loaded correctly.")

# =======================
# Config
# =======================
FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/",
]

KEYWORDS = [
    'AI', 'artificial intelligence', 'machine learning', 'deep learning', 'neural network',
    'LLM', 'large language model', 'generative AI', 'computer vision', 'object detection',
    'anomaly detection', 'predictive maintenance', 'condition monitoring', 'failure prediction',
    'smart factory', 'Industry 4.0', 'IIoT', 'digital twin', 'simulation', 'edge AI',
    'robot', 'robotics', 'automation', 'autonomous', 'cobots', 'collaborative robot',
    'AMR', 'AGV', 'quality control', 'defect detection', 'visual inspection',
    'process optimization', 'downtime reduction', 'energy optimization', 'factory', 'plant',
    'manufacturing process', 'industrial AI', 'industrial automation', 'smart manufacturing',
    'production efficiency', 'maintenance AI', 'supply chain optimization', 'predictive analytics'
]

MAX_CHUNK_SIZE = 3000   # Approx characters per chunk for Mistral
MAX_CHUNKS_PER_ARTICLE = 5
MAX_RETRIES = 3
INITIAL_WAIT = 5
MAX_WAIT = 20
ARTICLE_LIMIT_PER_FEED = 3

# =======================
# Helper functions
# =======================
def is_relevant(text):
    text = text.lower()
    return any(kw.lower() in text for kw in KEYWORDS)

def clean_text(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def chunk_text(text, size=MAX_CHUNK_SIZE):
    return [text[i:i+size] for i in range(0, len(text), size)]

# =======================
# Summarization with Mistral
# =======================
def summarize_chunk(chunk, url, pub_date):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "https://github.com/yourusername/ai-manufacturing-digest",
        "X-Title": "AI Use Case Extractor"
    }

    prompt = (
        "You are an expert industrial analyst. Extract AI use cases in manufacturing.\n"
        "Return only **one most relevant use case** per chunk in JSON:\n"
        "- title\n- problem\n- ai_solution\n- category: Manufacturing | Logistic | Supply Chain\n"
        "- industry\n- source: article URL\n- date: publication date in ISO format\n"
        "If no valid use case exists, return an empty array.\n\n"
        f"Article chunk:\n{chunk}"
    )

    payload = {
        "model": "mistralai/mistral-7b-instruct:latest",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500
    }

    retries = 0
    wait_time = INITIAL_WAIT
    while retries < MAX_RETRIES:
        try:
            response = requests.post("https://openrouter.ai/api/v1/chat/completions",
                                     headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                content = response.json()['choices'][0]['message']['content'].strip()
                try:
                    data = json.loads(content)
                    if isinstance(data, list) and data:
                        for uc in data:
                            uc["source"] = url
                            uc["date"] = pub_date
                        return data
                    return []
                except json.JSONDecodeError:
                    print("❌ Failed to parse JSON from chunk")
                    return []
            elif response.status_code == 429:
                print(f"⚠️ Rate limit hit. Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                wait_time = min(wait_time*2, MAX_WAIT)
                retries += 1
            else:
                print(f"❌ API error: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            print(f"❌ Exception: {e}")
            return []
    return []

# =======================
# Notion insertion
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
            "Date": {"date": {"start": use_case.get("date", datetime.now(timezone.utc).isoformat())[:10]}}
        }
    }

    try:
        response = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload)
        if response.status_code == 200:
            print(f"✅ Added to Notion: {use_case.get('title')}")
        else:
            print(f"❌ Notion error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error posting to Notion: {e}")

# =======================
# Main
# =======================
def main():
    seen_urls = set()
    for feed_url in FEEDS:
        print(f"📡 Fetching feed: {feed_url}")
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:ARTICLE_LIMIT_PER_FEED]:
                url = entry.link
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                title = entry.get('title', 'No Title')
                desc = entry.get('summary', '')
                content = entry.get('content', [{}])[0].get('value', '')
                text = clean_text(desc + ' ' + content)

                if not is_relevant(title + ' ' + text) or len(text) < 100:
                    print(f"⏭️ Skipping: {title}")
                    continue

                pub_date = entry.get('published', datetime.now(timezone.utc).isoformat())
                if 'T' not in pub_date:
                    pub_date = datetime.now(timezone.utc).isoformat()

                print(f"🔎 Processing article: {title} ({len(text)} chars)")
                chunks = chunk_text(text)
                all_use_cases = []

                for idx, chunk in enumerate(chunks[:MAX_CHUNKS_PER_ARTICLE]):
                    print(f"  ➤ Model chunk {idx+1}/{len(chunks[:MAX_CHUNKS_PER_ARTICLE])} ...")
                    uc = summarize_chunk(chunk, url, pub_date)
                    if uc:
                        all_use_cases.extend(uc)
                        break  # take **first valid use case only**

                if all_use_cases:
                    add_to_notion(all_use_cases[0])
                else:
                    print(f"⏭️ No valid use case found: {title}")

        except Exception as e:
            print(f"❌ Error processing feed {feed_url}: {e}")

if __name__ == "__main__":
    main()
