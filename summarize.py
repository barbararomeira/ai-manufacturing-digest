#!/usr/bin/env python3
import os
import time
import json
import feedparser
import requests
from bs4 import BeautifulSoup
import html

# ------------------- CONFIG -------------------
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/"
]
MODEL_ID = "mistral/mistral-7b-instruct"  # OpenRouter-compatible model
CHUNK_SIZE = 4000  # characters per chunk
MAX_RETRIES = 5
RETRY_BACKOFF = 5  # seconds

HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_KEY}",
    "Content-Type": "application/json"
}

# ------------------- HELPERS -------------------
def clean_article(text):
    """Remove HTML tags and decode entities"""
    soup = BeautifulSoup(text, "html.parser")
    clean_text = soup.get_text(separator=" ")
    clean_text = html.unescape(clean_text)
    return clean_text.strip()

def chunk_text(text, size=CHUNK_SIZE):
    """Split text into chunks"""
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end
    return chunks

def call_model(prompt):
    """Call OpenRouter model with retry and rate limit handling"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            data = {
                "model": MODEL_ID,
                "input": prompt,
                "max_output_tokens": 500
            }
            response = requests.post(
                "https://api.openrouter.ai/v1/completions",
                headers=HEADERS,
                data=json.dumps(data),
                timeout=60
            )
            if response.status_code == 429:
                backoff = RETRY_BACKOFF * (2 ** (attempt - 1))
                print(f"⚠️ Rate limit hit. Waiting {backoff}s before retry...")
                time.sleep(backoff)
                continue
            response.raise_for_status()
            result = response.json()
            output_text = result.get("completion", "").strip()
            return output_text
        except Exception as e:
            print(f"❌ Model call error on attempt {attempt}: {e}")
            time.sleep(RETRY_BACKOFF)
    return None

def parse_json_safe(text):
    """Try to parse JSON, return None if fails"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None

def summarize_article(title, text):
    """Split article into chunks, send to model, combine results"""
    text = clean_article(text)
    chunks = chunk_text(text)
    summaries = []
    for i, chunk in enumerate(chunks):
        print(f"  ➤ Model chunk {i+1}/{len(chunks)} ...")
        prompt = f"""
You are an AI assistant. Summarize the following article chunk.
Return ONLY a JSON object in this format:

{{
  "title": "<article title>",
  "summary": "<short summary of use case or key point>",
  "keywords": ["keyword1", "keyword2"]
}}

Article chunk:
{chunk}
"""
        output = call_model(prompt)
        if not output:
            print(f"  ❌ Chunk {i+1} failed or returned invalid data")
            continue
        data = parse_json_safe(output)
        if data:
            summaries.append(data)
        else:
            print(f"  ❌ Failed to parse JSON from chunk")
    if summaries:
        # Merge summaries into one
        merged = {
            "title": title,
            "summary": " ".join([s["summary"] for s in summaries if "summary" in s]),
            "keywords": list({kw for s in summaries if "keywords" in s for kw in s["keywords"]})
        }
        return merged
    return None

def is_relevant(text):
    """Simple relevance filter based on keywords"""
    keywords = ["manufacturing", "AI", "automation", "industrial", "robotics", "machine learning"]
    text_lower = text.lower()
    return any(k.lower() in text_lower for k in keywords)

# ------------------- MAIN -------------------
def main():
    if not (OPENROUTER_KEY and NOTION_TOKEN and NOTION_DATABASE_ID):
        print("❌ Missing environment variables!")
        return

    print("✅ Environment variables loaded")
    for feed_url in FEEDS:
        try:
            print(f"📡 Fetching feed: {feed_url}")
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                title = entry.get("title", "No title")
                text = entry.get("content", [{"value": entry.get("summary", "")}])[0]["value"]
                if not is_relevant(title + " " + text):
                    print(f"⏭️ Skipping: {title}")
                    continue
                print(f"🔎 Processing article: {title} ({len(text)} chars)")
                summary_data = summarize_article(title, text)
                if summary_data:
                    print(f"✅ Summary found: {summary_data}")
                else:
                    print(f"⏭️ No valid use case found: {title}")
        except Exception as e:
            print(f"❌ Error processing feed {feed_url}: {e}")

if __name__ == "__main__":
    main()
