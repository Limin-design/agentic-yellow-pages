import os
import json
from scrapegraphai.graphs import SmartScraperGraph
from dotenv import load_dotenv

# Load your environment variables
load_dotenv()
LLM_API_KEY = os.environ.get("LLM_API_KEY") 

# Configure the Scraper to use Groq's newest Llama 3.3 model
graph_config = {
    "llm": {
        "model": "groq/llama-3.3-70b-versatile", 
        "api_key": LLM_API_KEY,
        "temperature": 0
    },
    "verbose": True,
    "headless": True # This tells it to run an invisible Chrome browser
}

def extract_agent_data(target_url):
    """Uses an LLM to read a human website and convert it to A2A JSON format."""
    print(f"🕵️‍♂️ Deep Hunting: {target_url}")
    
    prompt = """
    You are an AI directory indexer. Read this website and extract:
    1. The name of the AI agent or company.
    2. A short 1-sentence description of what it does.
    3. A list of 1 to 3 technical tags (e.g., 'mcp-server', 'trading', 'web-scraper').
    4. The official X (Twitter) handle if found (e.g., '@companyname'). Return null if not found.
    Return ONLY a valid JSON object with keys: "name", "description", "tags", "x_handle".
    """
    
    try:
        scraper = SmartScraperGraph(
            prompt=prompt,
            source=target_url,
            config=graph_config
        )
        
        result = scraper.run()
        print(f"\n✅ LLM EXTRACTION SUCCESS!")
        print(json.dumps(result, indent=2))
        return result
        
    except Exception as e:
        print(f"\n❌ Failed to scrape {target_url}: {e}")
        return None

if __name__ == "__main__":
    if not LLM_API_KEY:
        print("❌ CRITICAL: LLM_API_KEY is missing from environment!")
    else:
        # We will test it on Anthropic's homepage first to make sure it works!
        test_url = "https://www.anthropic.com"
        extract_agent_data(test_url)
