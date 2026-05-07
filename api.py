from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
import requests
import os
import tweepy
import json
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List, Dict, Any

# 1. Load environment variables
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# X (Twitter) API Keys
X_API_KEY = os.environ.get("X_API_KEY")
X_API_SECRET = os.environ.get("X_API_SECRET")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN")
X_ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET")

# 2. Initialize the API
app = FastAPI(
    title="Agentic Yellow Pages API",
    description="A2A Discovery Directory for machine-to-machine orchestration.",
    version="1.0.0"
)

# --- Enable CORS for Frontend Access ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"],
)

def announce_on_x(name, domain, tags):
    """Automatically tweet when a human registers a new agent."""
    if not all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET]):
        print("X API keys missing, skipping tweet.")
        return False
        
    try:
        client = tweepy.Client(
            consumer_key=X_API_KEY,
            consumer_secret=X_API_SECRET,
            access_token=X_ACCESS_TOKEN,
            access_token_secret=X_ACCESS_SECRET
        )
        
        tag_str = ", ".join(tags[:3]) if tags else "autonomous node"
        tweet_text = f"🚨 New Agent Registered! 🚨\n\n🤖 {name}\n⚙️ Skills: {tag_str}\n\nWe just verified and indexed this endpoint on the A2A Registry.\n\nExplore it here:\n🌐 www.agenticyellowpage.com\n\n#AI #Agents #MCP"
        
        client.create_tweet(text=tweet_text)
        print("Successfully tweeted announcement!")
        return True
    except Exception as e:
        print(f"Failed to tweet: {e}")
        return False

@app.get("/")
def read_root():
    return {"message": "Welcome to the Agentic Yellow Pages API. Try /agents to list agents."}

@app.get("/llms.txt", response_class=PlainTextResponse)
def get_llms_txt():
    return """# Agentic Yellow Pages API
> The central discovery layer for A2A (Agent-to-Agent) orchestration.

This API allows AI agents, orchestrators, and MCP clients to search for specialized AI nodes, tools, and endpoints across the internet.

## Core Capabilities for AI Agents:
- Search the directory: Make a GET request to `/agents`. 
- Filter by skill: Make a GET request to `/agents?tag={skill}`
- Look up a specific node: Make a GET request to `/agents/{domain}`.
- Register yourself: Make a POST request to `/agents` with your domain.
"""

@app.get("/.well-known/mcp.json")
def get_mcp_manifest():
    return {
        "mcpServers": {
            "agentic-yellow-pages": {
                "url": "https://agentic-yellow-pages.onrender.com",
                "description": "The Discovery Layer for Autonomous Agents. Query the A2A protocol database.",
                "tools": [
                    {
                        "name": "search_agents",
                        "description": "List or search for autonomous AI agents by skill or tag.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "tag": { "type": "string" },
                                "limit": { "type": "integer", "default": 50 }
                            }
                        }
                    }
                ]
            }
        }
    }

@app.get("/agents.md", response_class=PlainTextResponse)
def list_agents_markdown(tag: str = None, limit: int = 50):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Database missing.")

    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    api_url = f"{SUPABASE_URL}/rest/v1/agents?select=*"
    if tag: api_url += f"&tags=cs.%7B{tag}%7D"
    api_url += f"&limit={limit}"

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        md_lines = [f"# Agentic Yellow Pages - {tag.capitalize() if tag else 'All'} Agents\n"]
        md_lines.append("> The Discovery Layer for Autonomous Agents.\n")
        
        for agent in data:
            domain = agent.get('domain', 'Unknown')
            name = agent.get('name', 'Unnamed Agent')
            desc = agent.get('description', 'No description.')
            tags_list = ", ".join(agent.get('tags', []))
            md_lines.append(f"## {name} (`{domain}`)")
            md_lines.append(f"**Description:** {desc}")
            md_lines.append(f"**Skills/Tags:** {tags_list}")
            md_lines.append(f"**API Endpoint:** `https://{domain}`\n")
            
        return "\n".join(md_lines)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class AgentSubmission(BaseModel):
    domain: str
    name: str
    description: str = "No description provided."
    tags: List[str] = []
    raw_card: Dict[str, Any] = {}

@app.post("/agents")
def register_agent(agent: AgentSubmission):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Database configuration missing.")

    clean_domain = agent.domain.replace("https://", "").replace("http://", "").rstrip('/')
    base_url = f"https://{clean_domain}"
    doors_to_check = [f"{base_url}/.well-known/agent-card.json", f"{base_url}/llms.txt", f"{base_url}/.well-known/ai-plugin.json"]
    
    is_verified = False
    for door in doors_to_check:
        try:
            res = requests.get(door, timeout=5, allow_redirects=True)
            content_type = res.headers.get('Content-Type', '').lower()
            if res.status_code == 200 and "text/html" not in content_type:
                if door.endswith(".json"):
                    try:
                        res.json()
                        is_verified = True
                        break
                    except ValueError: continue
                else:
                    is_verified = True
                    break
        except requests.RequestException: continue
            
    if not is_verified:
        raise HTTPException(status_code=400, detail=f"Verification Failed: Could not detect valid A2A data at {clean_domain}.")
    
    # NEW: We deliberately reset the trust_score and audit_log so the Oracle will re-test the claimed agent.
    db_payload = {
        "domain": clean_domain,
        "name": agent.name,
        "description": agent.description,
        "tags": agent.tags,
        "raw_card": agent.raw_card,
        "trust_score": None,
        "audit_log": None
    }

    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}

    try:
        # STEP 1: Check if the agent was already scraped by our bots
        check_url = f"{SUPABASE_URL}/rest/v1/agents?domain=eq.{clean_domain}&select=id"
        check_res = requests.get(check_url, headers=headers)
        check_res.raise_for_status()
        existing_agent = check_res.json()
        
        # STEP 2: Update (Claim) if it exists, or Insert (Create) if it doesn't
        if existing_agent and len(existing_agent) > 0:
            patch_url = f"{SUPABASE_URL}/rest/v1/agents?domain=eq.{clean_domain}"
            response = requests.patch(patch_url, headers=headers, json=db_payload)
            response.raise_for_status()
            message = f"Successfully claimed and updated {agent.name} at {clean_domain}"
        else:
            post_url = f"{SUPABASE_URL}/rest/v1/agents"
            response = requests.post(post_url, headers=headers, json=db_payload)
            response.raise_for_status()
            message = f"Successfully registered {agent.name} at {clean_domain}"
        
        # --- NEW: Trigger the auto-tweet when a human registers successfully! ---
        announce_on_x(agent.name, clean_domain, agent.tags)
        
        return {"status": "success", "message": message}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save to database: {str(e)}")

@app.get("/agents")
def list_agents(tag: str = None, limit: int = 50):
    if not SUPABASE_URL or not SUPABASE_KEY: raise HTTPException(status_code=500, detail="Database missing.")
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    api_url = f"{SUPABASE_URL}/rest/v1/agents?select=*"
    if tag: api_url += f"&tags=cs.%7B{tag}%7D"
    api_url += f"&limit={limit}"
    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        return {"status": "success", "count": len(response.json()), "agents": response.json()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
