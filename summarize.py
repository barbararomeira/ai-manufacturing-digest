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

# Quick validation
if not OPENROUTER_KEY or not NOTION_TOKEN or not NOTION_DATABASE_ID:
    print("❌ Missing environment variables. Please check GitHub Secrets.")
    sys.exit(1)

print("✅ OPENROUTER_KEY loaded correctly.")
print("✅ NOTION_TOKEN loaded correctly.")
print("✅ NOTION_DATABASE_ID loaded correctly.")

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
    # Expanded keywords
    'manufacturing technology', 'industrial automation', 'supply chain AI', 
    'predictive analytics', 'industrial IoT', 'smart manufacturing', 
    'digital transformation', 'production efficiency', 'maintenance AI', 'logistics AI'
]

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

def chunk_text(text, max_chars=4000):
    text = text.strip()
    return [text[i:i+max_chars] for i in range(0, len(text), max_chars)]

# =======================
# Summarize article via Mistral
# =======================
def summarize_article(article_text):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "https://github.com/yourusername/ai-manufacturing-digest",
        "X-Title": "AI Use Case Extractor"
    }

    chunks = chunk_text(article_text)
    all_use_cases = []

    for idx, chunk in enumerate(chunks, start=1):
        print(f"  ➤ Model chunk {idx}/{len(chunks)} ...")
        prompt = (
            "You are an expert industrial analyst. From the article below, extract the most relevant AI use case in manufacturing.\n"
            "If there are multiple, pick the most important one and mention in a 'comment' field that other use cases exist.\n"
            "Return JSON with fields: title, problem, ai_solution, category, industry, source, date, comment.\n"
            "If no valid AI manufacturing use case exists, return an empty array.\n\n"
            f"Article:\n{chunk}"
        )
        payload = {
            "model": "mistralai/mistral-7b-instruct:latest",
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
                    if isinstance(data, list) and data:
                        all_use_cases.extend(data)
                except json.JSONDecodeError:
                    print("❌ Failed to parse JSON from model output")
            else:
                print(f"❌ Model call failed {response.status_code}: {response.text}")
        except Exception as e:
            print(f"❌ Error summarizing chunk: {e}")

        time.sleep(5)  # avoid rate limits

    # Return only the first use case but keep comment if more exist
    if all_use_cases:
        main_use_case = all_use_cases[0]
        if len(all_use_cases) > 1:
            main_use_case['comment'] = f"Additional {len(all_use_cases)-1} use cases exist; check source for details."
        return [main_use_case]

    return []

# =======================
# Add to Notion
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
        response = requests.post(
            "https://api.notion.com/v1/pages",
            json=payload,
            headers=headers
        )
        if response.status_code == 200:
            print(f"✅ Added: {use_case.get('title')}")
        else:
            print(f"❌ Notion error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error posting to Notion: {e}")


# =======================
# Main function
# =======================
def main():
    seen_urls = set()
    for feed_url in FEEDS:
        print(f"📡 Fetching feed: {feed_url}")
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:  # limit for testing
                if entry.link in seen_urls:
                    continue
                seen_urls.add(entry.link)

                title = entry.get('title', 'No Title')
                desc = entry.get('summary', '')
                content = entry.get('content', [{}])[0].get('value', '')
                text = clean_text(desc + ' ' + content)

                if not is_relevant(title + ' ' + text):
                    print(f"⏭️ Not relevant: {title}")
                    continue
                if len(text) < 100:
                    print(f"⏭️ Too short: {title}")
                    continue

                print(f"🔎 Processing article: {title} ({len(text)} chars)")
                use_cases = summarize_article(text)
                if not use_cases:
                    print(f"⏭️ No valid use case found: {title}")
                    continue

                pub_date = entry.get('published', datetime.now(timezone.utc).isoformat())
                if 'T' not in pub_date:
                    pub_date = datetime.now(timezone.utc).isoformat()

                for uc in use_cases:
                    uc["source"] = entry.link
                    uc["date"] = pub_date
                    print(f"📤 Sending to Notion → {uc.get('title')}")
                    add_to_notion(uc)
                    time.sleep(12)  # respect rate limits
        except Exception as e:
            print(f"❌ Error processing feed {feed_url}: {e}")

if __name__ == "__main__":
    main()
