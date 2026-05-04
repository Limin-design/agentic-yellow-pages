from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List, Dict, Any

# 1. Load environment variables
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# 2. Initialize the API
app = FastAPI(
    title="Agentic Yellow Pages API",
    description="A2A Discovery Directory for machine-to-machine orchestration.",
    version="1.0.0"
)

# --- Enable CORS for Frontend Access ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows any frontend to fetch data
    allow_credentials=True,
    allow_methods=["*"], # Allows GET, POST, etc.
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Welcome to the Agentic Yellow Pages API. Try /agents to list agents."}

# --- Data Validation Model ---
class AgentSubmission(BaseModel):
    domain: str
    name: str
    description: str = "No description provided."
    tags: List[str] = []
    raw_card: Dict[str, Any] = {}

# --- The Registration Desk (POST) ---
@app.post("/agents")
def register_agent(agent: AgentSubmission):
    """
    Allow developers or other agents to submit their own agent card to the directory.
    Includes strict verification to prevent HTML/Spam submissions.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Database configuration missing.")

    clean_domain = agent.domain.replace("https://", "").replace("http://", "").rstrip('/')
    
    # --- VERIFICATION STEP: Prevent Spam and Soft-404s ---
    base_url = f"https://{clean_domain}"
    doors_to_check = [
        f"{base_url}/.well-known/agent-card.json",
        f"{base_url}/llms.txt",
        f"{base_url}/.well-known/ai-plugin.json"
    ]
    
    is_verified = False
    for door in doors_to_check:
        try:
            # 5-second timeout, follow redirects
            res = requests.get(door, timeout=5, allow_redirects=True)
            content_type = res.headers.get('Content-Type', '').lower()
            
            # 1: Must be a 200 OK
            # 2: MUST NOT be an HTML page (Stops Google/Reddit from tricking us)
            if res.status_code == 200 and "text/html" not in content_type:
                
                # If we are checking a JSON door, verify the contents parse as valid JSON
                if door.endswith(".json"):
                    try:
                        res.json()
                        is_verified = True
                        break
                    except ValueError:
                        continue # It's a fake/broken JSON file, keep checking
                else:
                    # It's an llms.txt and it passed the HTML check. We are good!
                    is_verified = True
                    break
        except requests.RequestException:
            continue
            
    if not is_verified:
        raise HTTPException(
            status_code=400, 
            detail=f"Verification Failed: Could not detect valid A2A data at {clean_domain}. Make sure the file exists and is not returning an HTML page."
        )
    # --- END VERIFICATION ---
    
    db_payload = {
        "domain": clean_domain,
        "name": agent.name,
        "description": agent.description,
        "tags": agent.tags,
        "raw_card": agent.raw_card
    }

    api_url = f"{SUPABASE_URL}/rest/v1/agents"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates" # Updates the agent if they already exist
    }

    try:
        response = requests.post(api_url, headers=headers, json=db_payload)
        response.raise_for_status()
        return {"status": "success", "message": f"Successfully registered {agent.name} at {clean_domain}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save to database: {str(e)}")

# --- Profile Look-up (GET specific agent) ---
@app.get("/agents/{domain:path}")
def get_single_agent(domain: str):
    """
    Retrieve the exact details of a single agent using their domain.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Database configuration missing.")

    clean_domain = domain.replace("https://", "").replace("http://", "").rstrip('/')
    
    # Query Supabase for this exact domain
    api_url = f"{SUPABASE_URL}/rest/v1/agents?domain=eq.{clean_domain}&select=*"
    
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if not data:
            raise HTTPException(status_code=404, detail="Agent not found in the directory.")
            
        return {"status": "success", "agent": data[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Search / List Agents (GET all) ---
@app.get("/agents")
def list_agents(tag: str = None, limit: int = 50):
    """
    Search for agents in the directory.
    Orchestrators can provide a 'tag' to find specific specialists.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Database configuration missing.")

    # Setup the Supabase API request headers
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    # Base URL to get all agents
    api_url = f"{SUPABASE_URL}/rest/v1/agents?select=*"

    # If the orchestrator provided a tag (e.g. ?tag=customer_support), filter the query!
    if tag:
        # We tell Supabase to look inside our 'tags' array column
        api_url += f"&tags=cs.%7B{tag}%7D"

    # Add the limit so we don't overwhelm the API
    api_url += f"&limit={limit}"

    try:
        # Fetch the data from our Supabase database
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        # Return a cleanly formatted JSON response to the inquiring Agent
        return {
            "status": "success",
            "count": len(data),
            "agents": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
