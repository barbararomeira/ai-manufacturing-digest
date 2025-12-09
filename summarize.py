#!/usr/bin/env python3
import os
import time
import json
import feedparser
import requests
from bs4 import BeautifulSoup
import html
import socket  # For IPv4 fallback

# ------------------- IPv4 Fallback (fixes DNS issues in some CI envs) -------------------
original_getaddrinfo = socket.getaddrinfo
def ipv4_only_getaddrinfo(*args, **kwargs):
    responses = original_getaddrinfo(*args, **kwargs)
    return [res for res in responses if res[0] == socket.AF_INET]
socket.getaddrinfo = ipv4_only_getaddrinfo

# ------------------- CONFIG -------------------
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "").strip()
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "").strip()
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "").strip()

FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/"
]

MODEL_ID = "mistral/mistral-7b-instruct"
MAX_RETRIES = 5
RETRY_BACKOFF = 5  # seconds

HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://github.com/your-username/your-repo",  # Optional but recommended by OpenRouter
    "X-Title": "AI Manufacturing Digest",  # Optional
}

# ------------------- HELPERS -------------------
def clean_article(text):
    soup = BeautifulSoup(text, "html.parser")
    clean_text = soup.get_text(separator=" ")
    clean_text = html.unescape(clean_text)
    return clean_text.strip()

def chunk_text(text, size=4000):
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end
    return chunks

def call_model(prompt):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            data = {
                "model": MODEL_ID,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500
            }
            response = requests.post(
                "https://api.openrouter.ai/v1/chat/completions",
                headers=HEADERS,
                json=data,  # Cleaner than data=json.dumps()
                timeout=60
            )
            if response.status_code == 429:
                backoff = RETRY_BACKOFF * (2 ** (attempt - 1))
                print(f"⚠️ Rate limit hit. Waiting {backoff}s before retry...")
                time.sleep(backoff)
                continue
            response.raise_for_status()
            result = response.json()
            output_text = result["choices"][0]["message"]["content"].strip()
            return output_text
        except Exception as e:
            print(f"❌ Model call error on attempt {attempt}: {e}")
            time.sleep(RETRY_BACKOFF)
    return None

def parse_json_safe(text):
    try:
        # Sometimes model returns markdown code blocks
        if text.startswith("```json"):
            text = text.split("```json", 1)[1].split("```", 1)[0]
        elif text.startswith("```"):
            text = text.split("```", 1)[1].split("```", 1)[0]
        return json.loads(text.strip())
    except (json.JSONDecodeError, IndexError):
        return None

def summarize_article(title, text):
    text = clean_article(text)
    chunks = chunk_text(text)
    summaries = []
    for i, chunk in enumerate(chunks):
        print(f"  ➤ Model chunk {i+1}/{len(chunks)} ...")
        prompt = f"""You are an AI assistant. Summarize the following article chunk.
Return ONLY a JSON object in this format:
{{
  "title": "{title}",
  "summary": "<short summary of use case or key point>",
  "keywords": ["keyword1", "keyword2"]
}}

Article chunk:
{chunk}"""
        output = call_model(prompt)
        if not output:
            print(f"  ❌ Chunk {i+1} failed or returned invalid data")
            continue
        data = parse_json_safe(output)
        if data and "summary" in data and "keywords" in data:
            summaries.append(data)
        else:
            print(f"  ❌ Failed to parse JSON from chunk: {output[:200]}...")
    if summaries:
        merged = {
            "title": title,
            "summary": " ".join([s["summary"] for s in summaries]),
            "keywords": list({kw for s in summaries for kw in s["keywords"]})
        }
        return merged
    return None

def is_relevant(text):
    keywords = ["manufacturing", "AI", "automation", "industrial", "robotics", "machine learning"]
    text_lower = text.lower()
    return any(k.lower() in text_lower for k in keywords)

# ------------------- MAIN -------------------
def main():
    if not (OPENROUTER_KEY and NOTION_TOKEN and NOTION_DATABASE_ID):
        print("❌ Missing one or more environment variables!")
        return

    print("✅ Environment variables loaded")
    for feed_url in FEEDS:
        feed_url = feed_url.strip()
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
                    print(f"✅ Summary found: {summary_data['title']}")
                else:
                    print(f"⏭️ No valid use case found: {title}")
        except Exception as e:
            print(f"❌ Error processing feed {feed_url}: {e}")

if __name__ == "__main__":
    main()

