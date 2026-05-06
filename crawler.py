import requests
import os
import json
import time
import re
import concurrent.futures
from urllib.parse import urlparse
from dotenv import load_dotenv
import tweepy

# 🧠 Import our new LLM Brain
from deep_hunter import extract_agent_data

# Load environment variables
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip(' "\'')
if SUPABASE_URL and not SUPABASE_URL.startswith("http"):
    SUPABASE_URL = f"https://{SUPABASE_URL}"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip(' "\'')
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "").strip(' "\'')

# X (Twitter) API Keys
X_API_KEY = os.environ.get("X_API_KEY", "").strip(' "\'')
X_API_SECRET = os.environ.get("X_API_SECRET", "").strip(' "\'')
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "").strip(' "\'')
X_ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET", "").strip(' "\'')

def get_known_domains():
    if not SUPABASE_URL or not SUPABASE_KEY: return set()
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    try:
        res = requests.get(f"{SUPABASE_URL}/rest/v1/agents?select=domain", headers=headers)
        if res.status_code == 200: return {item['domain'] for item in res.json()}
    except Exception: pass
    return set()

def announce_on_x(name, domain, tags):
    if not all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET]):
        return "⚠️ X API keys missing, skipping tweet."
    try:
        client = tweepy.Client(
            consumer_key=X_API_KEY, consumer_secret=X_API_SECRET,
            access_token=X_ACCESS_TOKEN, access_token_secret=X_ACCESS_SECRET
        )
        tag_str = ", ".join(tags[:3]) if tags else "autonomous node"
        tweet_text = f"🚨 New Agent Discovered! 🚨\n\n🤖 {name}\n⚙️ Skills: {tag_str}\n\nWe just indexed this endpoint on the A2A Registry. View details here:\n🌐 www.agenticyellowpage.com\n\n#AI #Agents #MCP"
        client.create_tweet(text=tweet_text)
        return "🐦 Successfully tweeted announcement!"
    except Exception as e:
        return f"❌ Failed to tweet: {e}"

def discover_new_targets(known_domains):
    if not SERPER_API_KEY: return []
    print("🚀 Launching WIDE HUNT (Target: 10 Credits/run)...")
    search_url = "https://google.serper.dev/search"
    queries = [
        'site:github.io "agent-card.json" OR "ai-plugin.json"',
        '"llms.txt" "AI agent" OR "LLM"',
        '"mcpServers" "version"',
        'site:x.com "my new MCP server" OR "my agent endpoint"'
    ]
    found_domains = set()
    headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}
    
    for q in queries:
        print(f"\n-> Asking Google: {q}")
        for page in range(1, 3):
            try:
                payload = json.dumps({"q": q, "page": page})
                response = requests.post(search_url, headers=headers, data=payload)
                results = response.json()
                if 'organic' in results:
                    for result in results['organic']:
                        link = result.get('link', '')
                        domain = urlparse(link).netloc
                        if domain.startswith("www."): domain = domain[4:]
                        if domain and domain not in known_domains and "x.com" not in domain:
                            found_domains.add(domain)
                        
                        snippet = result.get('snippet', '')
                        if snippet:
                            hidden_urls = re.findall(r'(https?://[a-zA-Z0-9./-]+)', snippet)
                            for u in hidden_urls:
                                hidden_domain = urlparse(u).netloc
                                if hidden_domain.startswith("www."): hidden_domain = hidden_domain[4:]
                                if hidden_domain and "x.com" not in hidden_domain and "twitter.com" not in hidden_domain:
                                    if hidden_domain not in known_domains:
                                        found_domains.add(hidden_domain)
            except Exception: pass
            time.sleep(1) 
    return list(found_domains)

def save_and_announce(domain, name, description, tags, raw_card):
    """Helper function to save to Supabase and Tweet."""
    db_payload = {"domain": domain, "name": name, "description": description, "tags": tags, "raw_card": raw_card}
    if SUPABASE_URL and SUPABASE_KEY:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}
        try:
            res = requests.post(f"{SUPABASE_URL}/rest/v1/agents", headers=headers, json=db_payload)
            res.raise_for_status()
            tweet_status = announce_on_x(name, domain, tags)
            return f"🎉 SUCCESS! Added {domain} to DB. {tweet_status}"
        except Exception as e:
            return f"❌ Failed to save {domain}: {e}"
    return f"⚠️ Database not configured for {domain}"

def process_single_domain_fast(domain):
    """PHASE 1: Fast scan for standard protocol doors."""
    base_url = f"https://{domain}"
    doors = [f"{base_url}/.well-known/agent-card.json", f"{base_url}/llms.txt", f"{base_url}/.well-known/ai-plugin.json"]
    
    for door in doors:
        try:
            res = requests.get(door, timeout=5, allow_redirects=True)
            content_type = res.headers.get('Content-Type', '').lower()
            if res.status_code == 200 and "text/html" not in content_type:
                data = res.json() if door.endswith(".json") else {"name": f"Agent Node at {domain}", "description": "Supports llms.txt protocol.", "tags": ["llms-txt"]}
                if "name" not in data or not data["name"]: data["name"] = f"Agent Node at {domain}"
                return True, data # Success
        except requests.RequestException: continue
    return False, domain # Failed, pass to Deep Hunter

def main():
    print("🚀 Starting TURBO Hunter with LLM Deep Scan...")
    known_domains = get_known_domains()
    print(f"🧠 We already know about {len(known_domains)} agents.")
    
    new_targets = discover_new_targets(known_domains)
    print(f"✅ TARGETS ACQUIRED! Found {len(new_targets)} NEW domains.")
    
    if not new_targets:
        print("No new targets to process this run.")
        return

    failed_domains = []

    print("\n⚡ PHASE 1: Launching concurrent fast protocol scan...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_single_domain_fast, dom): dom for dom in new_targets}
        for future in concurrent.futures.as_completed(futures):
            success, result = future.result()
            if success:
                # Result is the scraped data dict
                name = result.get("name", "Unknown Node")
                desc = result.get("description", "No description.")
                tags = result.get("tags", [])
                print(save_and_announce(futures[future], name, desc, tags, result))
            else:
                # Result is the domain string that failed
                failed_domains.append(result)

    if failed_domains:
        print(f"\n🕵️‍♂️ PHASE 2: Unleashing LLM Deep Hunter on {len(failed_domains)} difficult targets...")
        for domain in failed_domains:
            print(f"  -> Deep Scanning: {domain}")
            target_url = f"https://{domain}"
            llm_result = extract_agent_data(target_url)
            
            if llm_result:
                # ScrapegraphAI usually puts the result inside a 'content' key
                content = llm_result.get('content', llm_result) 
                name = content.get('name', f"Scraped Node ({domain})")
                desc = content.get('description', 'Extracted via Deep Hunter.')
                tags = content.get('tags', ['ai-agent'])
                
                print(save_and_announce(domain, name, desc, tags, llm_result))
            else:
                print(f"  ❌ {domain} yielded no data. Discarding.")
            
            # Pause for 8 seconds between LLM hits to respect Groq's free-tier token limits
            time.sleep(8)

    print("\n🏁 Turbo Automation run complete.")

if __name__ == "__main__":
    main()
