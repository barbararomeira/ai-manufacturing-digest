import os
import sys
import feedparser
import requests
from datetime import datetime, timezone
import time
import re
import json


# Load OpenRouter key
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
# Load secrets from environment
# =======================
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")  # OpenRouter API key for Mistral model
NOTION_TOKEN = os.getenv("NOTION_TOKEN")      # Notion integration token
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")  # Notion database ID to store results

# =======================
# RSS feeds to process
# =======================
FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/",
    # Add more feeds if needed
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
    'process optimization', 'downtime reduction', 'energy optimization', 'factory', 'plant'
]

# =======================
# Function to check if an article is relevant based on keywords
# =======================
def is_relevant(text):
    text = text.lower()
    return any(kw.lower() in text for kw in KEYWORDS)

# =======================
# Function to clean article text (remove HTML and extra whitespace)
# =======================
def clean_text(text):
    text = re.sub(r'<[^>]+>', '', text)  # Remove HTML tags
    text = re.sub(r'\s+', ' ', text)     # Remove extra whitespace
    return text.strip()

# =======================
# Function to summarize an article and extract AI use cases in JSON format
# =======================
def summarize_article(article_text):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "https://github.com/yourusername/ai-manufacturing-digest",
        "X-Title": "AI Use Case Extractor"
    }

    # Prompt for Mistral model
    prompt = (
        "You are an expert industrial analyst. From the article below, extract all AI use cases in manufacturing.\n"
        "For each use case, return in JSON format with the following fields:\n"
        "- title: short descriptive title\n"
        "- problem: problem the AI solves\n"
        "- ai_solution: AI technique(s) used\n"
        "- category: Manufacturing | Logistic | Supply Chain\n"
        "- industry: Automotive | Food | etc.\n"
        "- source: article URL\n"
        "- date: publication date in ISO format\n\n"
        "If no valid AI manufacturing use case exists, return an empty array.\n\n"
        f"Article:\n{article_text}"
    )

    payload = {
        "model": "mistralai/mistral-7b-instruct:free",  # Free Mistral model
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500  # Limit response size
    }

    try:
        # Send request to OpenRouter API
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=60
        )

        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content'].strip()
            try:
                # Parse JSON from model output
                data = json.loads(content)
                if isinstance(data, list) and data:
                    return data
                return []
            except json.JSONDecodeError:
                print("❌ Failed to parse JSON from summarization output")
                return []
        else:
            print(f"Summarization failed: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        print(f"Error summarizing: {e}")
        return []

# =======================
# Function to add a single AI use case to Notion database
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
        print(f"Error posting to Notion: {e}")

# =======================
# Main function to process feeds and send use cases to Notion
# =======================
def main():
    seen_urls = set()  # Avoid duplicates
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:  # Limit to latest 5 articles per feed
                if entry.link in seen_urls:
                    continue
                seen_urls.add(entry.link)

                title = entry.get('title', 'No Title')
                desc = entry.get('summary', '')
                content = entry.get('content', [{}])[0].get('value', '')
                text = clean_text(desc + ' ' + content)

                # Skip irrelevant or too short articles
                if not is_relevant(title + ' ' + text):
                    print(f"⏭️ Skipping (not relevant): {title}")
                    continue
                if len(text) < 100:
                    print(f"⏭️ Skipping (too short): {title}")
                    continue

                # Process article with Mistral
                print(f"🔎 Processing: {title} | Length {len(text)} chars")
                use_cases = summarize_article(text)
                if not use_cases:
                    print(f"⏭️ No valid use cases found: {title}")
                    continue

                # Get publication date or fallback to now
                pub_date = entry.get('published', datetime.now(timezone.utc).isoformat())
                if 'T' not in pub_date:
                    pub_date = datetime.now(timezone.utc).isoformat()

                # Send all extracted use cases to Notion
                for uc in use_cases:
                    uc["source"] = entry.link
                    uc["date"] = pub_date
                    print(f"📤 Sending to Notion → {uc.get('title')}")
                    add_to_notion(uc)
                    time.sleep(12)  # Respect rate limits

        except Exception as e:
            print(f"Error processing feed {feed_url}: {e}")

if __name__ == "__main__":
    main()

