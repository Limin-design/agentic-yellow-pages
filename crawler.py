import requests
import json
import os
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

# MEMORY FILE: So we don't waste credits checking the same sites every day
MEMORY_FILE = "checked_domains.txt"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return set(line.strip() for line in f)
    return set()

def save_to_memory(domain):
    with open(MEMORY_FILE, "a") as f:
        f.write(f"{domain}\n")

def discover_new_targets():
    if not SERPER_API_KEY:
        return ["https://a2aregistry.org"]

    print("🔎 Launching Smart Hunt for Agent Protocols...")
    search_url = "https://google.serper.dev/search"
    
    # THE GOLDEN FOOTPRINTS (Google Dorks for the Agentic Web)
    queries = [
        # A2A Protocol Cards
        '"/.well-known/agent-card.json"',
        # Model Context Protocol (MCP) servers
        'filetype:json "mcpServers" "command"',
        # Agent documentation manifests
        'filetype:txt "llms.txt" "agent"',
        # GitHub agent onboarding files
        'filetype:md "AGENTS.md"'
    ]
    
    all_domains = set()
    memory = load_memory()
    
    for q in queries:
        payload = json.dumps({"q": q, "num": 50}) # 50 results per query
        headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}
        
        try:
            response = requests.post(search_url, headers=headers, data=payload)
            results = response.json()
            for item in results.get('organic', []):
                parsed = urlparse(item['link'])
                root_domain = f"{parsed.scheme}://{parsed.netloc}"
                
                # Check memory before adding
                if root_domain not in memory:
                    all_domains.add(root_domain)
                    
        except Exception as e:
            print(f"❌ Search error: {e}")

    print(f"✅ Found {len(all_domains)} NEW domains to investigate today!")
    return list(all_domains)

def fetch_agent_data(base_url):
    """Checks the base domain for standard AI Agent files"""
    print(f"\nKnocking on doors at: {base_url}")
    
    # We check the 2 most common "Front Doors"
    door_1 = f"{base_url}/.well-known/agent-card.json"
    door_2 = f"{base_url}/llms.txt"
    
    found_data = None
    
    try:
        # Knock on Door 1 (A2A Protocol)
        res1 = requests.get(door_1, timeout=5)
        if res1.status_code == 200:
            found_data = res1.json()
            # Clean up the format
            found_data = found_data.get("agent_card", found_data) if isinstance(found_data, dict) else {}
            print("  🚪 Found A2A agent-card.json!")
            
        # If Door 1 fails, Knock on Door 2 (llms.txt standard)
        elif requests.get(door_2, timeout=5).status_code == 200:
            print("  📚 Found an llms.txt index! Marking as an Agent-Friendly Site.")
            found_data = {
                "name": f"Agent Node at {base_url.replace('https://', '')}",
                "description": "An AI-friendly site supporting llms.txt protocol.",
                "skills": ["llms-txt", "agent-readable"]
            }
        else:
            print("  ⏭️  No agent files found.")

        # If we found something, save it!
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
            
            requests.post(api_url, headers=headers, json=db_payload)
            print(f"  ✨ SUCCESSFULLY ADDED TO DB!")
            
    except Exception as e:
        print(f"  ❌ Failed to connect.")
        
    # Always save to memory so we don't check this domain again tomorrow
    save_to_memory(base_url)

if __name__ == "__main__":
    print("🚀 Starting Smart Hunter V2...\n")
    targets = discover_new_targets()
    for domain in targets:
        fetch_agent_data(domain)
    print("\n🏁 Automation run complete.")
