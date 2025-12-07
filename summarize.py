import os
import feedparser
import requests
from datetime import datetime, timezone
import time
import re

# Load secrets from environment
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# RSS feeds
FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/",
]

# Keywords for relevance
KEYWORDS = [
    'AI', 'artificial intelligence', 'machine learning', 'deep learning', 'neural network',
    'LLM', 'large language model', 'generative AI', 'computer vision', 'machine vision',
    'image recognition', 'object detection', 'anomaly detection', 'predictive maintenance',
    'condition monitoring', 'failure prediction', 'smart factory', 'Industry 4.0', 'IIoT',
    'industrial', 'automation', 'robot', 'robotics', 'quality control', 'defect', 'inspection'
]

def is_relevant(text):
    text = text.lower()
    return any(kw.lower() in text for kw in KEYWORDS)

def clean_text(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# ------------------------------------------------------
# OPENROUTER SUMMARIZER WITH RETRIES (FIXED)
# ------------------------------------------------------
def summarize_article(article_text):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "https://github.com/barbararomeira/ai-manufacturing-digest",
        "X-Title": "AI Manufacturing Digest"
    }

    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": [{
            "role": "user",
            "content": (
                "You are an expert industrial analyst. Summarize ONLY concrete applications of AI, "
                "machine learning, or automation in manufacturing from the article below. Include: "
                "1) AI technique used, 2) manufacturing process, 3) outcome. "
                "If there is no manufacturing use case, reply: \"Not a valid manufacturing AI use case.\"\n\n"
                "Article:\n" + article_text
            )
        }],
        "max_tokens": 250
    }

    for attempt in range(3):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                content = response.json()['choices'][0]['message']['content'].strip()
                if "Not a valid manufacturing AI use case" in content:
                    return None
                return content

            elif response.status_code in (429, 500, 503):
                wait = 5 * (attempt + 1)
                print(f"⚠️ OpenRouter rate limit/server error ({response.status_code}). Retrying in {wait}s…")
                time.sleep(wait)
                continue

            else:
                print(f"❌ Summarization failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            print(f"Error summarizing: {e}")
            time.sleep(5)

    return None


# ------------------------------------------------------
# NOTION WRITER
# ------------------------------------------------------
def add_to_notion(title, summary, url, pub_date):
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Title": {"title": [{"text": {"content": title[:199]}}]},
            "Source": {"url": url},
            "Date": {"date": {"start": pub_date[:10]}},
            "Industry": {"multi_select": [{"name": "Manufacturing"}]},
            "Category": {"multi_select": [{"name": "AI in Manufacturing"}]},
            "Summary": {"rich_text": [{"text": {"content": summary[:2000]}}]}
        }
    }
    try:
        response = requests.post(
            "https://api.notion.com/v1/pages",
            json=payload,
            headers=headers
        )
        if response.status_code == 200:
            print(f"✅ Added: {title}")
        else:
            print(f"❌ Notion error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Error posting to Notion: {e}")



# ------------------------------------------------------
# MAIN LOOP
# ------------------------------------------------------
def main():
    seen_urls = set()

    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:5]:  # limit per feed
                if entry.link in seen_urls:
                    continue
                seen_urls.add(entry.link)

                title = entry.get('title', 'No Title')
                desc = entry.get('summary', '')
                content = entry.get('content', [{}])[0].get('value', '')
                text = clean_text(desc + " " + content)

                if not is_relevant(title + " " + text):
                    continue
                if len(text) < 100:
                    continue

                print(f"🔎 Processing: {title[:60]} | Length {len(text)} chars")

                summary = summarize_article(text)
                if not summary:
                    print(f"⏭️ Skipping (not relevant or failed): {title}")
                    continue

                pub_date = entry.get('published', "")
                if not pub_date or 'T' not in pub_date:
                    pub_date = datetime.now(timezone.utc).isoformat()

                print(f"📤 Sending to Notion → {title}")
                add_to_notion(title, summary, entry.link, pub_date)

                time.sleep(3)  # Lower delay because we use a paid model

        except Exception as e:
            print(f"Error processing feed {feed_url}: {e}")


if __name__ == "__main__":
    main()

