# summarize.py
# ----------------
# Production-ready scraper + summarizer that:
# - Fetches RSS feeds
# - For each article (1 article = 1 use case) extracts the MOST RELEVANT AI-in-manufacturing use case
# - Uses OpenRouter-hosted models (Gemma 9B free primary, Qwen 7B free fallback)
# - Handles long articles by chunking
# - Parses structured label-like model output (Title / Problem / AI Solution / Category / Industry)
# - Posts a single row to Notion per article
#
# Make sure you have these environment variables set:
# - OPENROUTER_KEY
# - NOTION_TOKEN
# - NOTION_DATABASE_ID
#
# Notes:
# - If OpenRouter free quota is exhausted you'll see 429. Wait for reset or add credits.
# - Option A behavior: if multiple use cases exist, the model is instructed to pick the most relevant one.
# - The model is also asked to optionally add a short "Note:" line if there are other use cases present.

import os
import sys
import feedparser
import requests
from datetime import datetime, timezone
import time
import re
from typing import Optional, Dict, List

# -----------------------
# Config / Environment
# -----------------------
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

if not OPENROUTER_KEY:
    print("❌ OPENROUTER_KEY missing. Set it in your environment or GitHub Secrets.")
    sys.exit(1)
else:
    print("✅ OPENROUTER_KEY loaded correctly.")

if not NOTION_TOKEN:
    print("❌ NOTION_TOKEN missing. Set it in your environment or GitHub Secrets.")
    sys.exit(1)
else:
    print("✅ NOTION_TOKEN loaded correctly.")

if not NOTION_DATABASE_ID:
    print("❌ NOTION_DATABASE_ID missing. Set it in your environment or GitHub Secrets.")
    sys.exit(1)
else:
    print("✅ NOTION_DATABASE_ID loaded correctly.")

# -----------------------
# Feeds - add or remove as needed
# -----------------------
FEEDS = [
    "https://industry4o.com/feed",
    "https://www.manufacturingdive.com/feeds/news/",
    "https://venturebeat.com/category/ai/feed/",
]

# -----------------------
# Expanded keyword list (used for relevance and simple scoring)
# -----------------------
KEYWORDS = [
    # AI / ML
    'ai', 'artificial intelligence', 'machine learning', 'ml', 'deep learning', 'neural network',
    'llm', 'large language model', 'generative ai', 'genai', 'computer vision', 'object detection',
    'anomaly detection', 'predictive maintenance', 'predictive analytics', 'reinforcement learning',
    # Industry 4.0 / IIoT / digital twin
    'industry 4.0', 'iiot', 'industrial iot', 'digital twin', 'smart factory', 'edge ai', 'industrial automation',
    # Robotics / automation
    'robot', 'robotics', 'cobot', 'amr', 'agv', 'robotic', 'robotics vision',
    # Quality / inspection / production
    'quality control', 'visual inspection', 'defect detection', 'inspection', 'process optimization',
    'downtime', 'yield', 'throughput', 'oee', 'CNC', '3d printing', 'additive manufacturing',
    # Supply chain / logistics
    'supply chain', 'logistics', 'warehouse', 'inventory', 'demand forecasting',
    # Sectors
    'automotive', 'food', 'semiconductor', 'electronics', 'pharma', 'aerospace'
]
# normalize keywords for scoring
KEYWORDS_LOWER = [k.lower() for k in KEYWORDS]

# -----------------------
# OpenRouter Models (primary + fallback)
# Use the free variants (as of 2025 naming conventions)
# -----------------------
MODEL_PRIMARY = "google/gemma-9b:free"     # primary model for long context
MODEL_FALLBACK = "qwen/qwen-7b-instruct:free"  # fallback for structured extraction

OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"

# -----------------------
# Utilities: text cleaning / chunking / scoring
# -----------------------
def clean_text(html_or_text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    text = re.sub(r'<[^>]+>', '', html_or_text or '')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# =======================
# Function to check if an article is relevant based on keywords
# =======================
def is_relevant(text: str) -> bool:
    """
    Returns True if any keyword appears in the text.
    Case-insensitive match.
    """
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS_LOWER)

def chunk_text_by_chars(text: str, chunk_size: int = 4000) -> List[str]:
    """
    Split by roughly chunk_size characters, trying to split on sentence boundaries.
    chunk_size default 4000 chars (safe for long-context models).
    """
    text = text.strip()
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        # attempt to move end to next sentence boundary within 200 chars
        if end < len(text):
            m = re.search(r'[.?!]\s', text[end:end+200])
            if m:
                end = end + m.start() + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks

def score_use_case_candidate(candidate: Dict[str, str], article_text: str) -> int:
    """
    Score candidate based on keyword matches in title/problem/ai_solution and in article.
    Higher score => more relevant.
    """
    score = 0
    combined = " ".join([candidate.get("title",""), candidate.get("problem",""), candidate.get("ai_solution","")]).lower()
    article_lower = article_text.lower()
    # keyword matches in candidate fields
    for kw in KEYWORDS_LOWER:
        if kw in combined:
            score += 3
        if kw in article_lower:
            score += 1
    # give weight to having both title and ai_solution present
    if candidate.get("title"):
        score += 2
    if candidate.get("ai_solution"):
        score += 3
    return score

# -----------------------
# Model prompt & parsing utilities
# -----------------------
def build_prompt_for_chunk(chunk_text: str) -> str:
    """
    The prompt instructs the model to return EXACTLY in a label-based format:
    Title:, Problem:, AI Solution:, Category:, Industry:
    - The model must choose the single MOST RELEVANT use case for the article/chunk
    - If multiple use cases exist, the model should pick the most important and may add one short 'Note:' line
    """
    prompt = f"""
You are an expert industrial analyst. Read the article excerpt below and *select the single most relevant AI-in-manufacturing use case*.
Return your answer ONLY in this exact label format (no JSON, no extra commentary except an optional single 'Note:' line at the end):

Title: <short title>
Problem: <what problem is solved>
AI Solution: <concise description of the AI / ML technique used>
Category: Manufacturing | Logistics | Supply Chain
Industry: <industry name or "General">
Note: <optional short note, e.g. "Article contains other minor use cases">

Article excerpt:
{chunk_text}
"""
    return prompt.strip()

def call_openrouter_model(model_name: str, prompt: str, max_tokens: int = 400) -> Optional[str]:
    """
    Call OpenRouter chat completion endpoint with the chosen model.
    Returns the assistant content string on success, or None on error.
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/ai-manufacturing-digest",
        "X-Title": "AI Use Case Extractor"
    }
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens
    }
    try:
        r = requests.post(OPENROUTER_API, json=payload, headers=headers, timeout=60)
    except Exception as e:
        print(f"❌ OpenRouter request error: {e}")
        return None

    if r.status_code == 200:
        try:
            content = r.json()['choices'][0]['message']['content']
            return content
        except Exception as e:
            print(f"❌ Unexpected OpenRouter response format: {e} - {r.text[:200]}")
            return None
    else:
        # print concise error for debugging
        print(f"❌ Model call failed {r.status_code}: {r.text}")
        return None

def parse_labelled_output(text: str) -> Optional[Dict[str,str]]:
    """
    Parse back the label-based output into a dict:
    expects lines like "Title: ...", "Problem: ...", etc.
    Auto-repair heuristics:
    - Strip surrounding fences (```), markdown, or assistant preamble
    - Search for label patterns anywhere in text
    """
    if not text or not text.strip():
        return None
    # remove markdown fences and leading/trailing whitespace
    text = re.sub(r'```[\s\S]*?```', '', text)  # remove fenced code
    text = re.sub(r'\*\*|\[|\]', '', text)      # remove bold/markdown brackets
    # normalize newlines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    fields = {"title":"", "problem":"", "ai_solution":"", "category":"", "industry":"", "note":""}

    # try label-based parse (first-pass)
    for ln in lines:
        m = re.match(r'^\s*Title\s*:\s*(.+)', ln, flags=re.I)
        if m:
            fields["title"] = m.group(1).strip()
            continue
        m = re.match(r'^\s*Problem\s*:\s*(.+)', ln, flags=re.I)
        if m:
            fields["problem"] = m.group(1).strip()
            continue
        m = re.match(r'^\s*(AI Solution|AI solution|AI solution)\s*:\s*(.+)', ln, flags=re.I)
        if m:
            fields["ai_solution"] = m.group(2).strip()
            continue
        m = re.match(r'^\s*Category\s*:\s*(.+)', ln, flags=re.I)
        if m:
            fields["category"] = m.group(1).strip()
            continue
        m = re.match(r'^\s*Industry\s*:\s*(.+)', ln, flags=re.I)
        if m:
            fields["industry"] = m.group(1).strip()
            continue
        m = re.match(r'^\s*Note\s*:\s*(.+)', ln, flags=re.I)
        if m:
            fields["note"] = m.group(1).strip()
            continue

    # second-pass: if title empty, try to infer from first non-label line
    if not fields["title"]:
        # use first line up to 100 chars as title candidate
        for ln in lines:
            if ':' not in ln and len(ln) > 10:
                fields["title"] = ln[:120].strip()
                break

    # final guards: if ai_solution empty but problem present, set ai_solution to "unspecified"
    if not fields["ai_solution"] and fields["problem"]:
        # try to extract an AI phrase from problem via keyword search
        for kw in KEYWORDS_LOWER:
            if kw in fields["problem"].lower():
                fields["ai_solution"] = kw
                break
        if not fields["ai_solution"]:
            fields["ai_solution"] = "unspecified"

    # sanity: require at least title and ai_solution
    if not fields["title"] or not fields["ai_solution"]:
        return None

    return fields

# -----------------------
# Orchestration: per-article pipeline
# -----------------------
def extract_single_use_case_for_article(article_text: str, article_title: str, article_url: str, pub_date_iso: str) -> Optional[Dict]:
    """
    Main pipeline for ONE article -> ONE use case.
    Steps:
    - chunk article
    - call primary model for each chunk
    - parse candidates
    - if no valid candidates from primary, try fallback model
    - score candidates and pick single winner (Option A)
    - attach source+date and return final dict
    """
    chunks = chunk_text_by_chars(article_text, chunk_size=4000)
    candidates = []

    # call primary model (Gemma) for each chunk
    for i, chunk in enumerate(chunks):
        prompt = build_prompt_for_chunk(chunk)
        print(f"  ➤ Model (primary) chunk {i+1}/{len(chunks)} ...")
        out = call_openrouter_model(MODEL_PRIMARY, prompt, max_tokens=600)
        if out:
            parsed = parse_labelled_output(out)
            if parsed:
                # indicate which chunk provided it
                parsed["_source_chunk_idx"] = i
                candidates.append(parsed)
                # short sleep to be polite
        time.sleep(1)

    # if primary produced nothing, try fallback on full text (single shot)
    if not candidates:
        print("  ➤ No candidate from primary model; trying fallback model on full article...")
        prompt_full = build_prompt_for_chunk(article_text)
        out_fb = call_openrouter_model(MODEL_FALLBACK, prompt_full, max_tokens=800)
        if out_fb:
            parsed_fb = parse_labelled_output(out_fb)
            if parsed_fb:
                parsed_fb["_source_chunk_idx"] = -1
                candidates.append(parsed_fb)
        time.sleep(1)

    # still nothing -> return None
    if not candidates:
        return None

    # Score all candidates and pick best (Option A: strict one)
    scored = []
    for c in candidates:
        score = score_use_case_candidate(c, article_text)
        scored.append( (score, c) )
    scored.sort(key=lambda x: x[0], reverse=True)

    winner = scored[0][1]
    # Add a comment if there were other candidates (we will mention them in 'note')
    if len(scored) > 1:
        other_notes = []
        for s,c in scored[1:]:
            t = c.get("title") or c.get("problem")[:120]
            other_notes.append(t)
        # append a short note field indicating other candidate titles (max 200 chars)
        existing_note = winner.get("note","")
        other_str = "; ".join(other_notes)
        note_text = (existing_note + ("; " if existing_note and other_str else "") + other_str).strip()
        winner["note"] = note_text[:200]

    # attach metadata
    winner["source"] = article_url
    winner["date"] = pub_date_iso
    return winner

# -----------------------
# Notion uploader
# -----------------------
def add_to_notion(use_case: Dict):
    """
    Map the fields to your Notion DB:
    Title [text], Problem [text], AI Solution [text], Category [multi-select],
    Industry [multi-select], Source [link], Date [date].
    """
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    # safe defaults
    title = use_case.get("title","Untitled Use Case")
    problem = use_case.get("problem","")
    ai_solution = use_case.get("ai_solution","")
    category = use_case.get("category","General")
    industry = use_case.get("industry","General")
    source = use_case.get("source","")
    date = use_case.get("date", datetime.now(timezone.utc).isoformat())[:10]

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Title": {"title": [{"text": {"content": title}}]},
            "Problem": {"rich_text": [{"text": {"content": problem}}]},
            "AI Solution": {"rich_text": [{"text": {"content": ai_solution}}]},
            "Category": {"multi_select": [{"name": category}]},
            "Industry": {"multi_select": [{"name": industry}]},
            "Source": {"url": source},
            "Date": {"date": {"start": date}}
        }
    }

    try:
        r = requests.post("https://api.notion.com/v1/pages", json=payload, headers=headers, timeout=30)
        if r.status_code == 200:
            print(f"✅ Added to Notion: {title}")
        else:
            print(f"❌ Notion error {r.status_code}: {r.text}")
    except Exception as e:
        print(f"❌ Error posting to Notion: {e}")

# -----------------------
# Main: iterate feeds & articles
# -----------------------
def main():
    seen = set()
    for feed_url in FEEDS:
        print(f"\n📡 Fetching feed: {feed_url}")
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"❌ Failed to parse feed {feed_url}: {e}")
            continue

        for entry in feed.entries[:5]:
            url = entry.get("link")
            if not url or url in seen:
                continue
            seen.add(url)

            title = entry.get("title","(no title)")
            summary = entry.get("summary","")
            content = entry.get("content",[{}])[0].get("value","")
            text = clean_text(summary + "\n\n" + content)

            # Basic filters
            if len(text) < 200:
                print(f"⏭️ Too short: {title}")
                continue
            if not is_relevant(title + " " + text):
                print(f"⏭️ Not relevant: {title}")
                continue

            print(f"\n🔎 Processing article: {title} ({len(text)} chars)")

            # Get canonical date
            pub_date = entry.get("published", datetime.now(timezone.utc).isoformat())
            if "T" not in pub_date:
                pub_date = datetime.now(timezone.utc).isoformat()

            # Extract single use case
            use_case = extract_single_use_case_for_article(text, title, url, pub_date)
            if not use_case:
                print(f"⏭️ No valid use case found: {title}")
                continue

            # Optional: attach a comment if note present (we put in Problem as appended note if desired)
            if use_case.get("note"):
                use_case["problem"] = (use_case.get("problem","") + "  (Note: " + use_case.get("note") + ")")[:2000]

            # Send to Notion
            add_to_notion(use_case)

            # be polite and avoid hitting rate limits
            time.sleep(8)

    print("\n✅ Done.")

if __name__ == "__main__":
    main()
