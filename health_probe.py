import requests
import os
import time
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip(' "\'')
if SUPABASE_URL and not SUPABASE_URL.startswith("http"):
    SUPABASE_URL = f"https://{SUPABASE_URL}"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip(' "\'')

def check_agent_health(url: str) -> dict:
    """
    Returns a dict with:
      - status: "alive" | "degraded" | "offline"
      - code:   HTTP status code (int) or None
      - reason: human-readable explanation
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 A2A-Health-Probe/2.0"
    }
    try:
        # Using HEAD instead of GET makes this incredibly fast
        response = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
        code = response.status_code
        category = code // 100  # 2, 3, 4, or 5

        if category in (2, 3):
            return {"status": "alive", "code": code, "reason": "OK"}
        elif category == 4:
            return {"status": "alive", "code": code, "reason": f"Client error {code}, but server is reachable"}
        elif category == 5:
            return {"status": "degraded", "code": code, "reason": f"Server error {code}"}
        else:
            return {"status": "offline", "code": code, "reason": f"Unexpected status {code}"}

    except requests.exceptions.ConnectionError:
        return {"status": "offline", "code": None, "reason": "Connection refused or DNS failure"}
    except requests.exceptions.Timeout:
        return {"status": "offline", "code": None, "reason": f"Timed out after 10s"}
    except requests.exceptions.RequestException as e:
        return {"status": "offline", "code": None, "reason": str(e)}

def run_health_probe():
    print("🩺 Starting Advanced Live Health Probe...")
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
    counts = {"online": 0, "degraded": 0, "offline": 0}

    for agent in agents:
        agent_id = agent.get('id')
        domain = agent['domain']
        old_status = agent.get('status', 'online')

        # Run the robust HEAD check
        health_data = check_agent_health(f"https://{domain}")
        
        # Map 'alive' -> 'online' so it matches our database schema perfectly
        new_status = 'online' if health_data['status'] == 'alive' else health_data['status']
        
        counts[new_status] = counts.get(new_status, 0) + 1

        # Only execute a database write if the status has actually changed
        if new_status != old_status and agent_id:
            print(f"  -> {domain} status changed: {old_status} -> {new_status} ({health_data['reason']}). Updating DB...")
            update_url = f"{SUPABASE_URL}/rest/v1/agents?id=eq.{agent_id}"
            try:
                update_res = requests.patch(update_url, headers=headers, json={"status": new_status})
                update_res.raise_for_status()
            except Exception as e:
                print(f"  ❌ Failed to update {domain}: {e}")
        else:
            print(f"  -> {domain}: {new_status} | Code: {health_data['code']} ({health_data['reason']})")
        
        time.sleep(0.5)

    print("\n✅ Health Probe Complete!")
    print(f"📊 Stats: {counts.get('online', 0)} Online | {counts.get('degraded', 0)} Degraded | {counts.get('offline', 0)} Offline")

if __name__ == "__main__":
    run_health_probe()
