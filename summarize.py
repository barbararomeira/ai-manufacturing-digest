import os
import sys
import feedparser
import requests
from datetime import datetime, timezone
import time
import re

# =======================
# Load secrets
# =======================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# =======================
# Validate keys
# =======================
if not OPENROUTER_KEY:
    print("❌ OPENROUTER_KEY missing"); sys.exit(1)
else:
    print("✅ OPENROUTER_KEY loaded correctly.")

if not NOTION_TOKEN:
    print("❌ NOTION_TOKEN missing"); sys.exit(1)
else:
    print("✅ NOTION_TOKEN loaded correctly.")

if not NOTION_DATABASE_ID:
    print("❌ NOTION_DATABASE_ID missing"); sys.exit(1)
else:
    print("✅ NOTION_DATABASE_ID loaded correctly.")

# =======================
# RSS feeds
# =======================
FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/"
]

# =======================
# Keywords for filtering
# =======================
KEYWORDS = [
    # --- AI / Machine Learning / Data ---
    'ai', 'artificial intelligence', 'machine learning', 'ml', 'deep learning',
    'neural network', 'neural nets', 'nlp', 'natural language processing',
    'computer vision', 'cv', 'image recognition', 'image analysis',
    'object detection', 'segmentation', 'transformer model', 'llm',
    'large language model', 'generative ai', 'genai', 'predictive analytics',
    'predictive maintenance', 'anomaly detection', 'failure prediction',
    'quality prediction', 'pattern recognition', 'reinforcement learning',
    'supervised learning', 'unsupervised learning',

    # --- Industry 4.0 / Smart Factory / IIoT ---
    'industry 4.0', 'industrial iot', 'iiot', 'smart factory',
    'digital twin', 'virtual commissioning', 'process simulation',
    'digital thread', 'connected factory', 'smart manufacturing',
    'industrial automation', 'industrial ai', 'factory ai', 'edge ai',

    # --- Sensors / Data / Edge / Infrastructure ---
    'sensor', 'vibration analysis', 'condition monitoring',
    'edge computing', 'edge inference', 'embedded ai',
    'data pipeline', 'data acquisition', 'factory data',

    # --- Robotics / Automation ---
    'robot', 'robotics', 'cobot', 'collaborative robot', 'arm robot',
    'autonomous robot', 'mobile robot', 'amr', 'agv',
    'robot automation', 'robotic vision', 'robotic inspection',
    'robotic welding', 'robotic assembly',

    # --- Quality Inspection / Defects ---
    'visual inspection', 'quality control', 'qc automation',
    'inspection system', 'defect detection', 'surface inspection',
    'inline inspection', 'metrology', 'measurement automation',

    # --- Production / Operations Optimization ---
    'process optimization', 'downtime reduction', 'cycle time reduction',
    'yield improvement', 'energy optimization', 'scheduling optimization',
    'production planning', 'plant optimization', 'continuous improvement',
    'lean digital', 'throughput improvement',

    # --- Logistics / Supply Chain / Warehousing ---
    'supply chain', 'warehouse automation', 'warehouse robotics',
    'order picking', 'inventory optimization', 'inventory prediction',
    'demand forecasting', 'logistics automation',
    'route optimization', 'fleet management',

    # --- Additive Manufacturing / CNC / Machine Tools ---
    '3d printing', 'additive manufacturing', 'metal printing',
    'cnc', 'machining optimization', 'tool wear prediction',
    'manufacturing execution system', 'mes',

    # --- Vision / Imaging / Sensors ---
    'thermal imaging', 'infrared camera', 'high-speed imaging',
    'lidar', 'radar', 'vision system', 'image processing',

    # --- Safety / Human-AI Interaction ---
    'worker safety', 'ergonomics', 'ai assistant', 'digital assistant',
    'autonomous inspection', 'predictive safety',

    # --- Manufacturing Sectors (to broaden matching) ---
    'automotive', 'electronics manufacturing', 'semiconductor',
    'food manufacturing', 'pharma manufacturing', 'packaging machinery',
    'aerospace manufacturing', 'chemical plant', 'steel plant',
    'textile production', 'oil & gas plant', 'energy plant',

    # --- General industrial technology terms ---
    'automation', 'smart sensor', 'plc', 'scada', 'industrial cloud',
    'robot arm', 'industrial robot', 'manufacturing technology',
    'industrial innovation', 'factory modernization', 'industrial upgrade'
]

# =======================
# Utility: relevance
# =======================
def is_relevant(text):
    text = text.lower()
    return any(kw.lower() in text for kw in KEYWORDS)

# =======================
# Utility: clean html/text
# =======================
def clean_text(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# =======================
# Summarization (1 article → 1 structured use case)
# =======================
def summarize_article(article_text, article_title):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "https://github.com/ai-manufacturing-digest",
        "X-Title": "AI-Manufacturing-UseCase"
    }

    prompt = f"""
You are an expert industrial analyst. Summarize the **single most relevant AI manufacturing use case** found in the article below.

Return your answer ONLY in this exact format (NO JSON, NO explanations):

Title: <short title>
Problem: <what problem is solved>
AI Solution: <the AI/ML technique used>
Category: Manufacturing | Logistics | Supply Chain
Industry: <industry name or "General">
-----
Article:
{article_text}
"""

    payload = {
        "model": "mistralai/mistral-7b-instruct:free",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 350
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=60
        )

        if response.status_code != 200:
            print(f"❌ Summarization failed: {response.status_code} - {response.text}")
            return None

        content = response.json()['choices'][0]['message']['content']

        # Parse structured text (super reliable)
        lines = content.split("\n")
        use_case = {"title": "", "problem": "", "ai_solution": "", "category": "", "industry": ""}

        for line in lines:
            if line.lower().startswith("title:"):
                use_case["title"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("problem:"):
                use_case["problem"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("ai solution:"):
                use_case["ai_solution"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("category:"):
                use_case["category"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("industry:"):
                use_case["industry"] = line.split(":", 1)[1].strip()

        # Validate
        if not use_case["title"] or not use_case["ai_solution"]:
            print("⏭️ Model returned incomplete data, skipping.")
            return None

        return use_case

    except Exception as e:
        print(f"❌ Error summarizing: {e}")
        return None

# =======================
# Push to Notion
# =======================
def add_to_notion(use_case, source_url, pub_date):
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Title": {"title": [{"text": {"content": use_case["title"]}}]},
            "Problem": {"rich_text": [{"text": {"content": use_case["problem"]}}]},
            "AI Solution": {"rich_text": [{"text": {"content": use_case["ai_solution"]}}]},
            "Category": {"multi_select": [{"name": use_case["category"]}]},
            "Industry": {"multi_select": [{"name": use_case["industry"]}]},
            "Source": {"url": source_url},
            "Date": {"date": {"start": pub_date[:10]}}
        }
    }

    try:
        r = requests.post("https://api.notion.com/v1/pages", json=payload, headers=headers)

        if r.status_code == 200:
            print(f"✅ Added to Notion: {use_case['title']}")
        else:
            print(f"❌ Notion error: {r.status_code} - {r.text}")

    except Exception as e:
        print(f"❌ Error posting to Notion: {e}")

# =======================
# Main Runner
# =======================
def main():
    seen = set()

    for feed_url in FEEDS:
        print(f"\n📡 Fetching feed: {feed_url}")
        try:
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:5]:
                url = entry.link
                if url in seen:
                    continue
                seen.add(url)

                title = entry.get("title", "")
                summary = entry.get("summary", "")
                content = entry.get("content", [{}])[0].get("value", "")

                text = clean_text(summary + " " + content)

                if not is_relevant(title + " " + text):
                    print(f"⏭️ Not relevant: {title}")
                    continue

                if len(text) < 200:
                    print(f"⏭️ Too short: {title}")
                    continue

                print(f"\n🔎 Processing article: {title} ({len(text)} chars)")

                use_case = summarize_article(text, title)

                if not use_case:
                    print(f"⏭️ No valid use case found: {title}")
                    continue

                pub_date = entry.get("published", datetime.now(timezone.utc).isoformat())
                if "T" not in pub_date:
                    pub_date = datetime.now(timezone.utc).isoformat()

                add_to_notion(use_case, url, pub_date)

                time.sleep(10)  # Rate limit safety

        except Exception as e:
            print(f"❌ Feed error: {e}")

if __name__ == "__main__":
    main()


