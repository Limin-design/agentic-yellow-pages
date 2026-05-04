import requests
import os
import time
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip(' "\'')
if SUPABASE_URL and not SUPABASE_URL.startswith("http"):
    SUPABASE_URL = f"https://{SUPABASE_URL}"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip(' "\'')

def check_health(domain):
    """Pings the agent's domain to see if it is still serving valid A2A files."""
    base_url = f"https://{domain}"
    doors_to_check = [
        f"{base_url}/.well-known/agent-card.json",
        f"{base_url}/llms.txt",
        f"{base_url}/.well-known/ai-plugin.json"
    ]
    
    for door in doors_to_check:
        try:
            res = requests.get(door, timeout=5, allow_redirects=True)
            content_type = res.headers.get('Content-Type', '').lower()
            
            # Ensure it's a successful response and NOT an HTML fallback page
            if res.status_code == 200 and "text/html" not in content_type:
                if door.endswith(".json"):
                    try:
                        res.json()
                        return 'online'
                    except ValueError:
                        continue
                else:
                    return 'online'
        except requests.RequestException:
            continue
            
    return 'offline'

def run_health_probe():
    print("🩺 Starting Live Health Probe...")
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ Missing database credentials.")
        return

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    # 1. Fetch all agents
    try:
        api_url = f"{SUPABASE_URL}/rest/v1/agents?select=id,domain,status"
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        agents = response.json()
        print(f"📡 Found {len(agents)} agents in the directory to probe.")
    except Exception as e:
        print(f"❌ Failed to fetch agents: {e}")
        return

    # 2. Probe and Update
    online_count = 0
    offline_count = 0

    for agent in agents:
        # Supabase uses 'id' (UUID) by default for rows, or whatever your primary key is
        agent_id = agent.get('id')
        domain = agent['domain']
        old_status = agent.get('status', 'online')

        new_status = check_health(domain)
        
        if new_status == 'online':
            online_count += 1
        else:
            offline_count += 1

        # Only execute a database write if the status has actually changed
        if new_status != old_status and agent_id:
            print(f"  -> {domain} status changed: {old_status} -> {new_status}. Updating DB...")
            update_url = f"{SUPABASE_URL}/rest/v1/agents?id=eq.{agent_id}"
            try:
                # Use PATCH to update just the status column
                update_res = requests.patch(update_url, headers=headers, json={"status": new_status})
                update_res.raise_for_status()
            except Exception as e:
                print(f"  ❌ Failed to update {domain}: {e}")
        else:
            print(f"  -> {domain}: {new_status} (No change)")
        
        time.sleep(0.5) # Gentle pacing to avoid rate limits

    print("\n✅ Health Probe Complete!")
    print(f"📊 Stats: {online_count} Online | {offline_count} Offline")

if __name__ == "__main__":
    run_health_probe()
