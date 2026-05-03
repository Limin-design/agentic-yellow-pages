from fastapi import FastAPI, HTTPException
import requests
import os
from dotenv import load_dotenv

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

@app.get("/")
def read_root():
    return {"message": "Welcome to the Agentic Yellow Pages API. Try /agents to list agents."}

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