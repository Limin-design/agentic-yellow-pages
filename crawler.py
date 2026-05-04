import requests
import json
import os
from dotenv import load_dotenv

# 1. Load environment variables
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

def discover_new_targets():
    """Uses a search engine to find websites likely to have agent cards."""
    if not SERPER_API_KEY:
        print("⚠️ No SERPER_API_KEY found. Falling back to a manual check.")
        return ["https://a2aregistry.org"]

    print("🔎 Scouting the web for new AI Agents via Serper...")
    search_url = "https://google.serper.dev/search"
    
    # We search for the specific A2A protocol file footprint
    payload = json.dumps({
      "q": '"/.well-known/agent-card.json"'
    })
    headers = {
      'X-API-KEY': SERPER_API_KEY,
      'Content-Type': 'application/json'
    }

    try:
        response = requests.post(search_url, headers=headers, data=payload)
        results = response.json()
        
        # Extract the base domains from search results
        found_links = [item['link'] for item in results.get('organic', [])]
        # Clean the links to get just the base domain (everything before /.well-known)
        domains = list(set([link.split('/.well-known')[0] for link in found_links]))
        
        print(f"✅ Found {len(domains)} potential new targets!")
        return domains
    except Exception as e:
        print(f"❌ Search failed: {e}")
        return []

def fetch_agent_card(base_url):
    """The core logic to download an agent card and save it to Supabase."""
    target_url = f"{base_url.rstrip('/')}/.well-known/agent-card.json"
    print(f"Checking: {target_url}...")
    
    try:
        response = requests.get(target_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            # Handle cases where the JSON is wrapped in an 'agent_card' object
            agent_card = data.get("agent_card", data) if isinstance(data, dict) else {}
            
            name = agent_card.get("name", "Unknown Agent")
            description = agent_card.get("description", "No description provided.")
            skills = agent_card.get("skills", [])
            
            # Save to Supabase
            if SUPABASE_URL and SUPABASE_KEY:
                clean_domain = base_url.replace("https://", "").replace("http://", "").rstrip('/')
                
                db_payload = {
                    "domain": clean_domain,
                    "name": name,
                    "description": description,
                    "tags": [str(s) for s in skills] if isinstance(skills, list) else [], 
                    "raw_card": agent_card
                }
                
                api_url = f"{SUPABASE_URL}/rest/v1/agents"
                headers = {
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates" # UPSERT mode
                }
                
                db_res = requests.post(api_url, headers=headers, json=db_payload)
                if db_res.status_code in [200, 201, 204]:
                    print(f"✨ Successfully saved {name} ({clean_domain})")
                else:
                    print(f"❌ DB Error for {name}: {db_res.text}")
            return agent_card
    except Exception as e:
        print(f"❌ Skipping {base_url}: {e}")
    return None

# --- EXECUTION ---
if __name__ == "__main__":
    print("🚀 Starting Automated Discovery & Crawl...\n")
    
    # 1. Discover targets automatically!
    target_domains = discover_new_targets()
    
    # 2. Process each target
    for domain in target_domains:
        fetch_agent_card(domain)

    print("\n🏁 Automation run complete.")