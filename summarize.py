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
    # Add more (avoid vercel-protected ones like theautomateddaily.com)
]

# Keywords for relevance (broad but focused)
KEYWORDS = [
    'AI', 'artificial intelligence', 'machine learning', 'deep learning', 'neural network',
    'LLM', 'large language model', 'generative AI', 'computer vision', 'machine vision',
    'image recognition', 'object detection', 'anomaly detection', 'predictive maintenance',
    'condition monitoring', 'failure prediction', 'smart factory', 'Industry 4.0', 'IIoT',
    'Industrial IoT', 'digital twin', 'simulation', 'edge AI', 'robot', 'robotics',
    'automation', 'autonomous', 'cobots', 'collaborative robot', 'AMR', 'AGV',
    'quality control', 'quality assurance', 'defect detection', 'visual inspection',
    'scrap reduction', 'yield improvement', 'process optimization', 'cycle time reduction',
    'downtime reduction', 'energy optimization', 'manufactur', 'factory', 'production',
    'plant', 'assembly line', 'workcell', 'industrial', 'CNC', 'PLC', 'SCADA', 'MES',
    'ERP', 'MTConnect', 'OPC UA', 'Siemens', 'Rockwell', 'ABB', 'Fanuc', 'KUKA',
    'Cognex', 'Keyence', 'NVIDIA', 'predictive analytics', 'time-series forecasting',
    'root cause analysis', 'traceability', 'lean manufacturing', 'OEE'
]

def is_relevant(text):
    text = text.lower()
    return any(kw.lower() in text for kw in KEYWORDS)

def clean_text(text):
    # Remove HTML tags and excessive whitespace
    import re
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def summarize_article(article_text):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "https://github.com/yourusername/ai-manufacturing-digest",
        "X-Title": "AI Manufacturing Digest"
    }
    payload = {
        "model": "mistralai/mistral-7b-instruct:free",
        "messages": [{
            "role": "user",
            "content": (
                "You are an expert industrial analyst. Summarize ONLY concrete applications of AI, machine learning, or automation "
                "in manufacturing from the article below. Include: (1) the specific AI technique (e.g., computer vision, predictive maintenance), "
                "(2) the manufacturing process it improves (e.g., quality control, CNC, supply chain), and (3) the outcome (e.g., fewer defects, faster inspection). "
                "If no real manufacturing use case is described, reply: \"Not a valid manufacturing AI use case.\"\n\nArticle:\n" + article_text
            )
        }],
        "max_tokens": 250
    }
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=30
        )
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content'].strip()
            if "Not a valid manufacturing AI use case." in content:
                return None
            return content
        else:
            print(f"Summarization failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Error summarizing: {e}")
        return None

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
            "Industry": {"select": {"name": "Manufacturing"}},
            "Category": {"select": {"name": "AI in Manufacturing"}},
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

def main():
    seen_urls = set()
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:  # Only latest 5 per feed
                if entry.link in seen_urls:
                    continue
                seen_urls.add(entry.link)

                title = entry.get('title', 'No Title')
                desc = entry.get('summary', '')
                content = entry.get('content', [{}])[0].get('value', '')
                text = (desc + ' ' + content).strip()

                if not is_relevant(title + ' ' + text):
                    continue

                clean = clean_text(text)
                if len(clean) < 100:
                    continue

                summary = summarize_article(clean)
                if not summary:
                    continue

                pub_date = entry.get('published', datetime.now(timezone.utc).isoformat())
                # Parse date to ISO format if needed
                if 'T' not in pub_date:
                    pub_date = datetime.now(timezone.utc).isoformat()

                add_to_notion(title, summary, entry.link, pub_date)
                time.sleep(12)  # Respect OpenRouter rate limit

        except Exception as e:
            print(f"Error processing feed {feed_url}: {e}")

if __name__ == "__main__":
    main()
