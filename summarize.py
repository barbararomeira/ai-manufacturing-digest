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

for key, val in [("OPENROUTER_KEY", OPENROUTER_KEY), 
                 ("NOTION_TOKEN", NOTION_TOKEN), 
                 ("NOTION_DATABASE_ID", NOTION_DATABASE_ID)]:
    if not val:
        print(f"❌ {key} not found! Please check your environment variables.")
        sys.exit(1)
    else:
        print(f"✅ {key} loaded correctly.")

# =======================
# RSS Feeds
# =======================
FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/",
]

# =======================
# Expanded Keywords for filtering relevant articles
# =======================
KEYWORDS = [
    "AI", "artificial intelligence", "machine learning", "deep learning", "neural network",
    "LLM", "large language model", "generative AI", "computer vision", "object detection",
    "anomaly detection", "predictive maintenance", "condition monitoring", "failure prediction",
    "smart factory", "Industry 4.0", "IIoT", "digital twin", "simulation", "edge AI",
    "robot", "robotics", "automation", "autonomous", "cobots", "collaborative robot",
    "AMR", "AGV", "quality control", "defect detection", "visual inspection",
    "process optimization", "downtime reduction", "energy optimization", "factory", "plant",
    "supply chain", "manufacturing innovation", "industrial AI", "predictive analytics",
    "digital manufacturing", "production efficiency", "smart manufacturing"
]

# =======================
# Helpers
# =======================
def is_relevant(text):
    text = text.lower()
    return any(kw.lower() in text for kw in KEYWORDS)

def clean_text(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def chunk_text(text, max_len=4000, overlap=200):
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_len, len(text))
        chunks.append(text[start:end])
        start = end - overlap
    return chunks

# =======================
# Summarize Article via OpenRouter
# =======================
def summarize_article(text, url, pub_date):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    chunks = chunk_text(text)
    all_use_cases = []

    for idx, chunk in enumerate(chunks):
        prompt = (
            "You are an expert industrial analyst. From the article below, extract the most relevant AI use case in manufacturing.\n"
            "Return only **one primary use case** in JSON format with the following fields:\n"
            "- title: short descriptive title\n"
            "- problem: problem the AI solves\n"
            "- ai_solution: AI technique(s) used\n"
            "- category: Manufacturing | Logistic | Supply Chain\n"
            "- industry: Automotive | Food | etc.\n"
            "- source: article URL\n"
            "- date: publication date in ISO format\n"
            "If no valid AI use case exists, return an empty array.\n\n"
            f"Article:\n{chunk}"
        )
        payload = {
            "model": "mistralai/mistral-7b-instruct:latest",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500
        }

        retries = 0
        wait_time = 5
        while retries < 5:
            try:
                response = requests.post("https://openrouter.ai/api/v1/chat/completions", 
                                         headers=headers, json=payload, timeout=60)
                if response.status_code == 200:
                    content = response.json()['choices'][0]['message']['content'].strip()
                    try:
                        data = json.loads(content)
                        if isinstance(data, list) and data:
                            for uc in data:
                                uc["source"] = url
                                uc["date"] = pub_date
                            all_use_cases.extend(data)
                        break
                    except json.JSONDecodeError:
                        print(f"❌ Failed to parse JSON from chunk {idx+1}")
                        break
                elif response.status_code == 429:
                    print(f"⚠️ Rate limit hit. Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    wait_time *= 2
                    retries += 1
                else:
                    print(f"❌ API error: {response.status_code} - {response.text}")
                    break
            except Exception as e:
                print(f"❌ Exception on chunk {idx+1}: {e}")
                break

    # Return **only the most relevant one**
    if all_use_cases:
        return [all_use_cases[0]]
    return []

# =======================
# Add Use Case to Notion
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
        response = requests.post("https://api.notion.com/v1/pages", json=payload, headers=headers)
        if response.status_code == 200:
            print(f"✅ Added to Notion: {use_case.get('title')}")
        else:
            print(f"❌ Notion error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Exception posting to Notion: {e}")

# =======================
# Main Function
# =======================
def main():
    print("✅ Environment variables loaded")
    seen_urls = set()
    for feed_url in FEEDS:
        print(f"📡 Fetching feed: {feed_url}")
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:3]:  # Limit 3 for faster testing
                url = entry.get('link')
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                title = entry.get('title', 'No Title')
                desc = entry.get('summary', '')
                content = entry.get('content', [{}])[0].get('value', '')
                text = clean_text(desc + ' ' + content)

                if not text:
                    print(f"⏭️ Skipping empty article: {title}")
                    continue
                if not is_relevant(title + ' ' + text):
                    print(f"⏭️ Not relevant: {title}")
                    continue

                print(f"🔎 Processing article: {title} ({len(text)} chars)")
                pub_date = entry.get('published', datetime.now(timezone.utc).isoformat())
                if 'T' not in pub_date:
                    pub_date = datetime.now(timezone.utc).isoformat()

                use_cases = summarize_article(text, url, pub_date)
                if not use_cases:
                    print(f"⏭️ No valid use case found: {title}")
                    continue

                for uc in use_cases:
                    add_to_notion(uc)
                    time.sleep(10)  # Respect rate limits

        except Exception as e:
            print(f"❌ Error processing feed {feed_url}: {e}")

if __name__ == "__main__":
    main()

