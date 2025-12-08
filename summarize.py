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

if not OPENROUTER_KEY or not NOTION_TOKEN or not NOTION_DATABASE_ID:
    print("❌ Missing environment variables")
    sys.exit(1)
else:
    print("✅ Environment variables loaded")

# =======================
# RSS feeds
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
    'manufacturing', 'production', 'industrial', 'supply chain', 'logistics', 'MES', 'ERP',
    'digital manufacturing', 'smart manufacturing', 'predictive analytics', 'AI deployment',
    'automation system', 'industrial AI', 'AI solution'
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

def chunk_text(text, chunk_size=4000, overlap=2000):
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = start + chunk_size - overlap
    return chunks

# =======================
# Summarize article with Mistral 7B
# =======================
def call_model(prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "mistralai/mistral-7b-instruct:free",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800
    }

    for attempt in range(5):
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=60
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
            elif resp.status_code == 429:
                wait = (2 ** attempt) * 5
                print(f"⚠️ Rate limit hit. Waiting {wait}s before retry...")
                time.sleep(wait)
                continue
            else:
                print(f"❌ Model call failed {resp.status_code}: {resp.text}")
                return None
        except Exception as e:
            print(f"❌ Model call error: {e}")
            time.sleep(5)
    return None

def parse_json_safe(content):
    try:
        return json.loads(content)
    except:
        try:
            # extract array if extra text
            clean = re.search(r"\[.*\]", content, flags=re.DOTALL)
            if clean:
                return json.loads(clean.group())
        except:
            # log for debugging
            with open("debug_model_output.txt", "a") as f:
                f.write(content + "\n\n")
    return []

def summarize_article(article_text, url, pub_date):
    chunks = chunk_text(article_text)
    all_use_cases = []

    for idx, chunk in enumerate(chunks):
        prompt = f"""
You are an expert industrial analyst. Extract AI use cases in manufacturing from the article chunk below.
Return **only JSON array**. Each use case must have:
- title
- problem
- ai_solution
- category: Manufacturing | Logistic | Supply Chain
- industry
- source (article URL)
- date (ISO format)
If no valid use case exists, return [].

Article chunk {idx+1} of {len(chunks)}:
{chunk}
"""
        output = call_model(prompt)
        if not output:
            print(f"❌ Chunk {idx+1} failed or returned invalid data")
            continue
        data = parse_json_safe(output)
        if isinstance(data, list):
            for uc in data:
                uc["source"] = url
                uc["date"] = pub_date
            all_use_cases.extend(data)
        else:
            print(f"❌ Chunk {idx+1} returned non-list JSON")

    # fallback last resort
    if not all_use_cases:
        fallback_chunk = " ".join(article_text.split()[:2000])
        fallback_prompt = f"""
Extract AI use cases in manufacturing from this text. Return only JSON array.
{text}
"""
        output = call_model(fallback_prompt)
        data = parse_json_safe(output)
        if isinstance(data, list):
            for uc in data:
                uc["source"] = url
                uc["date"] = pub_date
            all_use_cases.extend(data)

    if all_use_cases:
        primary_uc = all_use_cases[0]
        if len(all_use_cases) > 1:
            primary_uc["comment"] = f"Article contains {len(all_use_cases)} use cases. Check source for others."
        else:
            primary_uc["comment"] = ""
        return [primary_uc]
    return []

# =======================
# Post to Notion
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
            "Comment": {"rich_text": [{"text": {"content": use_case.get("comment","")}}]}
        }
    }
    try:
        resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers=headers,
            json=payload
        )
        if resp.status_code == 200:
            print(f"✅ Added: {use_case.get('title')}")
        else:
            print(f"❌ Notion error {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"❌ Notion post exception: {e}")

# =======================
# Main loop
# =======================
def main():
    seen_urls = set()
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            print(f"📡 Fetching feed: {feed_url}")
            for entry in feed.entries[:5]:
                if entry.link in seen_urls:
                    continue
                seen_urls.add(entry.link)

                title = entry.get('title', 'No Title')
                desc = entry.get('summary', '')
                content = entry.get('content', [{}])[0].get('value', '')
                text = clean_text(desc + " " + content)

                if not is_relevant(title + " " + text):
                    print(f"⏭️ Not relevant: {title}")
                    continue
                if len(text) < 100:
                    print(f"⏭️ Too short: {title}")
                    continue

                print(f"🔎 Processing article: {title} ({len(text)} chars)")
                pub_date = entry.get('published', datetime.now(timezone.utc).isoformat())
                if 'T' not in pub_date:
                    pub_date = datetime.now(timezone.utc).isoformat()

                use_cases = summarize_article(text, entry.link, pub_date)
                if not use_cases:
                    print(f"⏭️ No valid use case found: {title}")
                    continue

                for uc in use_cases:
                    print(f"📤 Sending to Notion → {uc.get('title')}")
                    add_to_notion(uc)
                    time.sleep(12)  # rate limit

        except Exception as e:
            print(f"❌ Error processing feed {feed_url}: {e}")

if __name__ == "__main__":
    main()
