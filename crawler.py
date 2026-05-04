import requests
import json
import os
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

def discover_new_targets():
    if not SERPER_API_KEY:
        print("❌ Missing SERPER_API_KEY!")
        return []

    print("🔎 Launching Smart Hunt V3...")
    search_url = "https://google.serper.dev/search"
    
    # Kept the best footprints!
    queries = [
        '"/.well-known/agent-card.json"',
        'filetype:json "mcpServers"',
        'filetype:txt "llms.txt"'
    ]
    
    all_domains = set()
    
    for q in queries:
        print(f"  -> Asking Google: {q}")
        # Removed the 'num' parameter to ensure we stay safely inside the Free Tier limits
        payload = json.dumps({"q": q}) 
        headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}
        
        try:
            response = requests.post(search_url, headers=headers, data=payload)
            results = response.json()
            
            # 🚨 DIAGNOSTIC CHECK: If Serper is mad at us, this will tell us exactly why!
            if 'organic' not in results:
                print(f"     ⚠️ Serper API Error/Warning: {results}")
                continue
                
            found_count = len(results.get('organic', []))
            print(f"     ✅ Found {found_count} raw links for this query.")
            
            for item in results.get('organic', []):
                parsed = urlparse(item['link'])
                root_domain = f"{parsed.scheme}://{parsed.netloc}"
                all_domains.add(root_domain)
                    
        except Exception as e:
            print(f"     ❌ Search error: {e}")

    unique_domains = list(all_domains)
    print(f"\n✅ Total UNIQUE domains to investigate today: {len(unique_domains)}\n")
    return unique_domains

def fetch_agent_data(base_url):
    print(f"Knocking on doors at: {base_url}")
    
    door_1 = f"{base_url}/.well-known/agent-card.json"
    door_2 = f"{base_url}/llms.txt"
    
    found_data = None
    
    try:
        # Door 1 (A2A Protocol)
        res1 = requests.get(door_1, timeout=10)
        if res1.status_code == 200:
            found_data = res1.json()
            found_data = found_data.get("agent_card", found_data) if isinstance(found_data, dict) else {}
            print("  🚪 Found A2A agent-card.json!")
            
        # Door 2 (LLMs index)
        else:
            res2 = requests.get(door_2, timeout=10)
            if res2.status_code == 200:
                print("  📚 Found an llms.txt index!")
                found_data = {
                    "name": f"Agent Node at {base_url.replace('https://', '')}",
                    "description": "An AI-friendly site supporting llms.txt protocol.",
                    "skills": ["llms-txt"]
                }
            else:
                print("  ⏭️  No agent files found.")

    except Exception as e:
        print(f"  ⚠️ Crawl error (site blocked us): {e}")
        return # Stop here if we can't crawl the site
        
    # Save to Supabase (Separated so we can see Database errors!)
    if found_data and SUPABASE_URL and SUPABASE_KEY:
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
                print(f"  ❌ Supabase rejected it. Status: {db_res.status_code}, Error: {db_res.text}")
        except Exception as e:
            print(f"  ❌ Database connection error: {e}")

if __name__ == "__main__":
    print("🚀 Starting Smart Hunter V3...\n")
    targets = discover_new_targets()
    for domain in targets:
        fetch_agent_data(domain)
    print("\n🏁 Automation run complete.")
