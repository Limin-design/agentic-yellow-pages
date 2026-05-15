import os  
import re  
import json  
import time  
import requests  
from bs4 import BeautifulSoup  
from urllib.parse import urlparse  
from dotenv import load_dotenv  
  
load_dotenv()  
  
# -----------------------------  
# Config from env (strict defaults)  
# -----------------------------  
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")  
OPENAI_MAX_INPUT_CHARS = int(os.getenv("OPENAI_MAX_INPUT_CHARS", "4000"))  
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))  
REQUEST_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT_MS", "20000")) / 1000.0  
  
# Fail-fast required secrets  
REQUIRED = ["SERPER_API_KEY"]  
missing = [k for k in REQUIRED if not os.getenv(k)]  
if missing:  
    raise RuntimeError(f"Missing required env vars: {missing}")  
  
HEADERS = {  
    "User-Agent": "Mozilla/5.0 (compatible; AgenticYellowPagesBot/1.0)",  
}  
  
def rate_sleep(last_calls, rpm):  
    """Simple rate limiter: max rpm requests/minute."""  
    now = time.time()  
    window_start = now - 60  
    last_calls[:] = [t for t in last_calls if t > window_start]  
    if len(last_calls) >= rpm:  
        sleep_for = 60 - (now - last_calls[0]) + 0.1  
        if sleep_for > 0:  
            time.sleep(sleep_for)  
    last_calls.append(time.time())  
  
def search_serper(query, num_results=10):  
    url = "https://google.serper.dev/search"  
    payload = {"q": query, "num": num_results}  
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}  
    resp = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)  
    resp.raise_for_status()  
    data = resp.json()  
    organic = data.get("organic", [])  
    return [item.get("link") for item in organic if item.get("link")]  
  
def clean_text(html):  
    soup = BeautifulSoup(html, "html.parser")  
    for tag in soup(["script", "style", "noscript"]):  
        tag.decompose()  
    text = soup.get_text(separator=" ", strip=True)  
    text = re.sub(r"\s+", " ", text).strip()  
    return text  
  
def scrape_url(url):  
    try:  
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)  
        r.raise_for_status()  
        content_type = r.headers.get("Content-Type", "")  
        if "text/html" not in content_type:  
            return None  
        text = clean_text(r.text)  
        if not text:  
            return None  
        text = text[:OPENAI_MAX_INPUT_CHARS]  # strict input cap  
        return {  
            "url": url,  
            "domain": urlparse(url).netloc,  
            "title": extract_title(r.text),  
            "text": text,  
        }  
    except Exception:  
        return None  
  
def extract_title(html):  
    soup = BeautifulSoup(html, "html.parser")  
    if soup.title and soup.title.string:  
        return soup.title.string.strip()  
    return ""  
  
def run_scraper(query, max_pages=10, out_file="scraped.jsonl"):  
    urls = search_serper(query, num_results=max_pages * 2)  
    seen = set()  
    results = []  
    calls = []  
  
    for u in urls:  
        if not u or u in seen:  
            continue  
        seen.add(u)  
  
        if len(results) >= max_pages:  
            break  
  
        rate_sleep(calls, RATE_LIMIT_PER_MINUTE)  
        doc = scrape_url(u)  
        if doc:  
            results.append(doc)  
            print(f"[OK] {doc['url']}")  
  
    with open(out_file, "w", encoding="utf-8") as f:  
        for row in results:  
            f.write(json.dumps(row, ensure_ascii=False) + "\n")  
  
    print(f"\nSaved {len(results)} docs -> {out_file}")  
    return results  
  
if __name__ == "__main__":  
    # Example:  
    # python scraper.py  
    QUERY = os.getenv("SCRAPER_QUERY", "best local plumbers in Lisbon")  
    MAX_PAGES = int(os.getenv("SCRAPER_MAX_PAGES", "10"))  
    run_scraper(QUERY, max_pages=MAX_PAGES, out_file="scraped.jsonl")  
