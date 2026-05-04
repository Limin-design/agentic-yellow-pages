import requests
import json
import os
from urllib.parse import urlparse
from dotenv import load_dotenv
import time

load_dotenv()
# Safely load and clean the URL
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip(' "\'')
if SUPABASE_URL and not SUPABASE_URL.startswith("http"):
    SUPABASE_URL = f"https://{SUPABASE_URL}"

SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip(' "\'')
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "").strip(' "\'')

def get_known_domains():
    """Fetches all domains currently in our DB to prevent duplicate crawling."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return set()
        
    api_url = f"{SUPABASE_URL}/rest/v1/agents?select=domain"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        res = requests.get(api_url, headers=headers, timeout=10)
        if res.status_code == 200:
            # Returns a set of domains like {'google.com', 'openai.com'}
            return {item['domain'] for item in res.json()}
    except Exception as e:
        print(f"⚠️ Could not load memory: {e}")
    return set()

def discover_new_targets(known_domains):
    if not SERPER_API_KEY:
        print("❌ Missing SERPER_API_KEY!")
        return []

    print("🚀 Launching WIDE HUNT (Target: 10 Credits/run)...")
    search_url = "https://google.serper.dev/search"
    
    # WIDER NET: Broader search terms without strict filetypes, 
    # relying on our Python script to actually test the endpoints.
    queries = [
        'site:github.io "agent-card.json" OR "ai-plugin.json"',
        '"llms.txt" "AI agent" OR "LLM"',
        '"mcpServers" "version"',
        '"A2A protocol" "agent"',
        '"openapi.json" "x-agent-api"'
    ]
    
    all_domains = set()
    
    for q in queries:
        print(f"\n-> Asking Google: {q}")
        
        for page in range(1, 3):
            # REMOVED "num": 100. Google's anti-bot blocks niche queries if you ask for 100 at once.
            # Standard 10 results per page is much safer and bypasses the filter.
            payload = json.dumps({
                "q": q, 
                "page": page
            }) 
            headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}
            
            try:
                response = requests.post(search_url, headers=headers, data=payload)
                results = response.json()
                
                if 'organic' not in results:
                    print(f"     Page {page}: No organic results found (End of Google's index).")
                    break 
                    
                found_count = len(results.get('organic', []))
                print(f"     Page {page}: Found {found_count} links.")
                
                for item in results.get('organic', []):
                    parsed = urlparse(item['link'])
                    root_domain = f"{parsed.scheme}://{parsed.netloc}"
                    clean_domain = root_domain.replace("https://", "").replace("http://", "")
                    
                    # MEMORY CHECK: Only add it if we don't already have it in Supabase!
                    if clean_domain not in known_domains:
                        all_domains.add(root_domain)
                
                if found_count < 100:
                    break
                    
            except Exception as e:
                print(f"     ❌ Search error on page {page}: {e}")
                break

    unique_domains = list(all_domains)
    print(f"\n✅ SMART HUNT COMPLETE! Found {len(unique_domains)} completely NEW domains to check.\n")
    return unique_domains

def fetch_agent_data(base_url):
    print(f"Knocking on doors at: {base_url}")
    
    doors = [
        f"{base_url}/.well-known/agent-card.json",
        f"{base_url}/llms.txt",
        f"{base_url}/.well-known/ai-plugin.json"
    ]
    
    found_data = None
    
    for door in doors:
        try:
            res = requests.get(door, timeout=5) 
            if res.status_code == 200:
                if "agent-card" in door:
                    data = res.json()
                    found_data = data.get("agent_card", data) if isinstance(data, dict) else {}
                    print(f"  🚪 Found A2A Protocol!")
                    break
                elif "llms.txt" in door:
                    print(f"  📚 Found an llms.txt index!")
                    found_data = {
                        "name": f"Agent Node at {base_url.replace('https://', '')}",
                        "description": "An AI-friendly site supporting llms.txt protocol.",
                        "skills": ["llms-txt"]
                    }
                    break
                elif "ai-plugin" in door:
                    data = res.json()
                    print(f"  🔌 Found an AI Plugin!")
                    found_data = {
                        "name": data.get("name_for_human", f"Plugin at {base_url.replace('https://', '')}"),
                        "description": data.get("description_for_human", ""),
                        "skills": ["ai-plugin", "openai-standard"],
                        "raw_card": data
                    }
                    break
        except Exception:
            pass 

    if not found_data:
        print("  ⏭️  No agent files found.")
        return
        
    # Save to Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        clean_domain = base_url.replace("https://", "").replace("http://", "").rstrip('/')
        
        db_payload = {
            "domain": clean_domain,
            "name": found_data.get("name", "Unknown Node"),
            "description": found_data.get("description", ""),
            "tags": [str(s) for s in found_data.get("skills", [])] if isinstance(found_data.get("skills"), list) else [],
            "raw_card": found_data
        }
        
        api_url = f"{SUPABASE_URL}/rest/v1/agents"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        }
        
        try:
            db_res = requests.post(api_url, headers=headers, json=db_payload)
            if db_res.status_code in [200, 201, 204]:
                print(f"  ✨ SUCCESSFULLY ADDED TO DB!")
            else:
                print(f"  ❌ Supabase rejected it. Status: {db_res.status_code}")
        except Exception as e:
            print(f"  ❌ Database connection error.")

if __name__ == "__main__":
    print("🚀 Starting SMART Hunter...\n")
    
    # 1. Ask the Database what we already know
    print("🧠 Checking memory...")
    known = get_known_domains()
    print(f"🧠 We already know about {len(known)} agents.")
    
    # 2. Discover new targets, passing our memory so we skip duplicates
    targets = discover_new_targets(known)
    
    # 3. Fetch data for only the NEW domains
    for domain in targets:
        fetch_agent_data(domain)
        time.sleep(0.5) 
        
    print("\n🏁 Smart Automation run complete.")
