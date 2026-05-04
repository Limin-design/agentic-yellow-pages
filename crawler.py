import requests
import os
import json
import time
import concurrent.futures
from urllib.parse import urlparse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip(' "\'')
if SUPABASE_URL and not SUPABASE_URL.startswith("http"):
    SUPABASE_URL = f"https://{SUPABASE_URL}"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip(' "\'')
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "").strip(' "\'')

def get_known_domains():
    """Fetch domains we already have in the DB so we don't scrape them again."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return set()
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    try:
        res = requests.get(f"{SUPABASE_URL}/rest/v1/agents?select=domain", headers=headers)
        if res.status_code == 200:
            return {item['domain'] for item in res.json()}
    except Exception:
        pass
    return set()

def discover_new_targets(known_domains):
    """Use Google Serper API to cast a wide net and find potential A2A endpoints."""
    if not SERPER_API_KEY:
        print("❌ Missing SERPER_API_KEY! Skipping discovery.")
        return []

    print("🚀 Launching WIDE HUNT (Target: 10 Credits/run)...")
    search_url = "https://google.serper.dev/search"
    
    # WIDER NET: Broader search terms without strict filetypes
    queries = [
        'site:github.io "agent-card.json" OR "ai-plugin.json"',
        '"llms.txt" "AI agent" OR "LLM"',
        '"mcpServers" "version"',
        '"A2A protocol" "agent"',
        '"openapi.json" "x-agent-api"'
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
                        # Strip www. to keep it clean
                        if domain.startswith("www."):
                            domain = domain[4:]
                        
                        if domain and domain not in known_domains:
                            found_domains.add(domain)
            except Exception as e:
                print(f"Error fetching Serper API: {e}")
            time.sleep(1) # Rate limiting to avoid being blocked
            
    return list(found_domains)

def fetch_agent_data(domain):
    """Knock on standard protocol doors to see if the site is an agent."""
    base_url = f"https://{domain}"
    doors = [
        f"{base_url}/.well-known/agent-card.json",
        f"{base_url}/llms.txt",
        f"{base_url}/.well-known/ai-plugin.json"
    ]
    
    for door in doors:
        try:
            res = requests.get(door, timeout=5, allow_redirects=True)
            content_type = res.headers.get('Content-Type', '').lower()
            
            # Must be 200 OK and MUST NOT be an HTML page (to avoid soft-404s)
            if res.status_code == 200 and "text/html" not in content_type:
                data = {}
                if door.endswith(".json"):
                    try:
                        data = res.json()
                    except ValueError:
                        continue
                else:
                    # For llms.txt, create a basic schema fallback
                    data = {
                        "name": f"Agent Node at {domain}",
                        "description": "An AI-friendly site supporting the llms.txt protocol.",
                        "tags": ["llms-txt"]
                    }
                
                # Ensure name exists
                if "name" not in data or not data["name"]:
                    data["name"] = f"Agent Node at {domain}"
                    
                return data
        except requests.RequestException:
            continue
    return None

def process_single_domain(domain):
    """Worker function to process one domain asynchronously."""
    print(f"  -> Scanning: {domain}")
    data = fetch_agent_data(domain)
    if not data:
        return f"  💨 Skipped {domain} (No A2A files found)"
        
    name = data.get("name", f"Agent Node at {domain}")
    description = data.get("description", "No description provided.")
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = []

    # --- M2M Payment Protocol Scanner ---
    raw_str = str(data).lower()
    payment_tags = []
    if "atxp" in raw_str: payment_tags.append("pay:ATXP")
    if "x402" in raw_str or "l402" in raw_str: payment_tags.append("pay:L402")
    if "ap2" in raw_str: payment_tags.append("pay:AP2")
    if "stripe" in raw_str or "stripe-mcp" in raw_str: payment_tags.append("pay:Stripe")
        
    tags.extend(payment_tags)
    tags = list(set(tags))
    # --- END M2M Scanner ---
    
    db_payload = {
        "domain": domain,
        "name": name,
        "description": description,
        "tags": tags,
        "raw_card": data
    }
    
    # Save to Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        }
        api_url = f"{SUPABASE_URL}/rest/v1/agents"
        try:
            res = requests.post(api_url, headers=headers, json=db_payload)
            res.raise_for_status()
            return f"  🎉 SUCCESS! Added {domain} to DB."
        except Exception as e:
            return f"  ❌ Failed to save {domain}: {e}"
            
    return f"  ⚠️ Database not configured for {domain}"

def main():
    print("🚀 Starting TURBO Hunter...")
    known_domains = get_known_domains()
    print(f"🧠 We already know about {len(known_domains)} agents.")
    
    new_targets = discover_new_targets(known_domains)
    print(f"✅ TARGETS ACQUIRED! Found {len(new_targets)} NEW domains.")
    
    # --- Multi-Threaded Processing ---
    if new_targets:
        print("⚡ Launching 10 concurrent crawler threads...")
        # Max workers = 10 means it processes 10 websites at the exact same time
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            # Map the list of domains to our worker function
            results = executor.map(process_single_domain, new_targets)
            
            # Print results as they finish
            for result in results:
                print(result)
    else:
        print("No new targets to process this run.")

    print("🏁 Turbo Automation run complete.")

if __name__ == "__main__":
    main()
