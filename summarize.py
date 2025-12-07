import os
import feedparser
import re
import json
import time
from datetime import datetime, timezone
import requests
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

# ==============================
# Notion Config
# ==============================
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# ==============================
# RSS Feeds
# ==============================
FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/",
]

# ==============================
# Relevance Keywords
# ==============================
KEYWORDS = [
    'AI', 'artificial intelligence', 'machine learning', 'deep learning', 'neural network',
    'LLM', 'computer vision', 'object detection', 'anomaly detection', 'predictive maintenance',
    'quality control', 'inspection', 'robot', 'robotics', 'automation', 'assembly line',
    'production', 'supply chain', 'process optimization', 'downtime reduction', 'factory', 'plant'
]

# ==============================
# Local Model Setup (CPU-friendly)
# ==============================
MODEL_NAME = "tiiuae/falcon-7b-instruct"
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    device_map="auto",
    load_in_4bit=True,
    torch_dtype=torch.float16
)

# ==============================
# Helper Functions
# ==============================
def is_relevant(text):
    text = text.lower()
    return any(kw.lower() in text for kw in KEYWORDS)

def clean_text(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def chunk_text(text, max_tokens=500):
    words = text.split()
    chunks = []
    current = []
    tokens = 0
    for w in words:
        current.append(w)
        tokens += 1
        if tokens >= max_tokens:
            chunks.append(' '.join(current))
            current = []
            tokens = 0
    if current:
        chunks.append(' '.join(current))
    return chunks

def summarize_chunk(chunk_text, article_url, pub_date):
    prompt = (
        "You are an expert industrial analyst. Extract all AI use cases in manufacturing.\n"
        "Return JSON array of use cases with fields: title, problem, ai_solution, category (Manufacturing/Logistic/Supply Chain), "
        "industry (Automotive/Food/etc.), source, date.\n"
        f"Article:\n{chunk_text}\n"
    )
    inputs = tokenizer(prompt, return_tensors="pt").to("cuda" if torch.cuda.is_available() else "cpu")
    outputs = model.generate(**inputs, max_new_tokens=500)
    text_output = tokenizer.decode(outputs[0], skip_special_tokens=True)

    try:
        data = json.loads(text_output)
        if isinstance(data, list):
            for uc in data:
                uc.setdefault("source", article_url)
                uc.setdefault("date", pub_date)
            return data
    except json.JSONDecodeError:
        print("❌ Failed to parse JSON from model output.")
    return []

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
    response = requests.post(
        "https://api.notion.com/v1/pages", json=payload, headers=headers
    )
    if response.status_code == 200:
        print(f"✅ Added: {use_case.get('title')}")
    else:
        print(f"❌ Notion error: {response.status_code} - {response.text}")

# ==============================
# Main
# ==============================
def main():
    seen_urls = set()
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                if entry.link in seen_urls:
                    continue
                seen_urls.add(entry.link)

                title = entry.get('title', 'No Title')
                desc = entry.get('summary', '')
                content = entry.get('content', [{}])[0].get('value', '')
                text = clean_text(desc + ' ' + content)

                if not is_relevant(text + title):
                    print(f"⏭️ Skipping (not relevant): {title}")
                    continue
                if len(text) < 100:
                    print(f"⏭️ Skipping (too short): {title}")
                    continue

                pub_date = entry.get('published', datetime.now(timezone.utc).isoformat())
                if 'T' not in pub_date:
                    pub_date = datetime.now(timezone.utc).isoformat()

                print(f"🔎 Processing: {title} | Length {len(text)}")

                chunks = chunk_text(text, max_tokens=500)
                all_use_cases = []
                for chunk in chunks:
                    use_cases = summarize_chunk(chunk, entry.link, pub_date)
                    all_use_cases.extend(use_cases)
                    time.sleep(1)

                if not all_use_cases:
                    print(f"⏭️ No valid use cases found: {title}")
                    continue

                for uc in all_use_cases:
                    add_to_notion(uc)
                    time.sleep(1)

        except Exception as e:
            print(f"Error processing feed {feed_url}: {e}")

if __name__ == "__main__":
    main()




'''
import os
import feedparser
import requests
from datetime import datetime, timezone
import time
import re
import json

# Load secrets from environment
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# RSS feeds
FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/",
    # Add more feeds as needed
]

# Keywords for relevance
KEYWORDS = [
    'AI', 'artificial intelligence', 'machine learning', 'deep learning', 'neural network',
    'LLM', 'large language model', 'generative AI', 'computer vision', 'object detection',
    'anomaly detection', 'predictive maintenance', 'condition monitoring', 'failure prediction',
    'smart factory', 'Industry 4.0', 'IIoT', 'digital twin', 'simulation', 'edge AI',
    'robot', 'robotics', 'automation', 'autonomous', 'cobots', 'collaborative robot',
    'AMR', 'AGV', 'quality control', 'defect detection', 'visual inspection',
    'process optimization', 'downtime reduction', 'energy optimization', 'factory', 'plant'
]

def is_relevant(text):
    text = text.lower()
    return any(kw.lower() in text for kw in KEYWORDS)

def clean_text(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def summarize_article(article_text):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "https://github.com/yourusername/ai-manufacturing-digest",
        "X-Title": "AI Use Case Extractor"
    }
    prompt = (
        "You are an expert industrial analyst. From the article below, extract all AI use cases in manufacturing.\n"
        "For each use case, return in the following structured format (JSON):\n\n"
        "[\n"
        "  {\n"
        "    \"title\": \"Short descriptive title\",\n"
        "    \"problem\": \"Problem the AI solves\",\n"
        "    \"ai_solution\": \"AI technique(s) used\",\n"
        "    \"category\": \"Manufacturing | Logistic | Supply Chain\",\n"
        "    \"industry\": \"Automotive | Food | etc.\",\n"
        "    \"source\": \"<article URL>\",\n"
        "    \"date\": \"<publication date ISO format>\"\n"
        "  }\n"
        "]\n\n"
        "If there is no valid AI manufacturing use case, return an empty array.\n\n"
        f"Article:\n{article_text}"
    )

    payload = {
        "model": "mistralai/mistral-7b-instruct:free",
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

def main():
    seen_urls = set()
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                if entry.link in seen_urls:
                    continue
                seen_urls.add(entry.link)

                title = entry.get('title', 'No Title')
                desc = entry.get('summary', '')
                content = entry.get('content', [{}])[0].get('value', '')
                text = clean_text(desc + ' ' + content)

                if not is_relevant(title + ' ' + text):
                    print(f"⏭️ Skipping (not relevant): {title}")
                    continue

                if len(text) < 100:
                    print(f"⏭️ Skipping (too short): {title}")
                    continue

                print(f"🔎 Processing: {title} | Length {len(text)} chars")
                use_cases = summarize_article(text)
                if not use_cases:
                    print(f"⏭️ No valid use cases found: {title}")
                    continue

                pub_date = entry.get('published', datetime.now(timezone.utc).isoformat())
                if 'T' not in pub_date:
                    pub_date = datetime.now(timezone.utc).isoformat()

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
'''
