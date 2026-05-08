import os
import json
import time
import re
from scrapegraphai.graphs import SmartScraperGraph
from dotenv import load_dotenv

load_dotenv()

LLM_API_KEY = os.environ.get("LLM_API_KEY")

# ── Status constants so callers can branch cleanly ──────────────────────────
STATUS_SUCCESS   = "success"
STATUS_NOT_AGENT = "not_agent"   # Site was scraped but isn't an AI agent/API
STATUS_FAILED    = "failed"      # Network error, crash, or LLM gave garbage

REQUIRED_KEYS = {"name", "description", "tags", "x_handle"}

def build_graph_config(verbose: bool = False) -> dict:
    return {
        "llm": {
            "model": "groq/llama-3.3-70b-versatile",
            "api_key": LLM_API_KEY,
            "temperature": 0,
        },
        "verbose": verbose,
        "headless": True,
    }

# ── Prompt is now explicit about the schema so the LLM has less room to drift ─
EXTRACTION_PROMPT = """
You are an AI agent directory indexer. Analyze this website carefully.

STEP 1 — CLASSIFY: Decide if this page represents a specific AI agent, AI API, 
or AI tool that developers can integrate with.

Reject (return null_result) if it is:
- A generic blog, news site, or forum
- A package manager or registry (npm, pip, hex, crates.io)
- General documentation or GitHub Pages unrelated to a specific AI product
- A landing page with no technical product information

STEP 2 — EXTRACT (only if valid):
Return a JSON object with exactly these keys:
{
  "is_agent": true,
  "name": "string — the agent or product name",
  "description": "string — one sentence, what it does technically",
  "tags": ["array", "of", "1-3", "lowercase-hyphenated tags"],
  "x_handle": "string like @handle or null if not found"
}

If rejected in STEP 1, return exactly:
{ "is_agent": false }

Return ONLY the JSON object. No explanation, no markdown, no backticks.
"""

def _parse_llm_result(raw) -> dict | None:
    """Handles cases where the LLM returns a string instead of a parsed dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None
    return None

def _validate_agent_result(data: dict) -> bool:
    """Checks all required keys exist and have non-empty values."""
    if not data.get("is_agent"):
        return False
    missing = REQUIRED_KEYS - data.keys()
    if missing:
        return False
    if not isinstance(data.get("tags"), list) or not (1 <= len(data["tags"]) <= 3):
        return False
    return True

def extract_agent_data(
    target_url: str,
    retries: int = 2,
    verbose: bool = False
) -> dict:
    """
    Scrapes a URL and extracts AI agent metadata.

    Returns:
        {
            "status":  "success" | "not_agent" | "failed",
            "url":     target_url,
            "data":    { name, description, tags, x_handle } or None,
            "reason":  explanation string on non-success
        }
    """
    print(f"🕵️  Deep Hunting: {target_url}")
    config = build_graph_config(verbose=verbose)
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            scraper = SmartScraperGraph(
                prompt=EXTRACTION_PROMPT,
                source=target_url,
                config=config,
            )
            raw_result = scraper.run()

            # Normalise to dict
            parsed = _parse_llm_result(raw_result)
            if parsed is None:
                raise ValueError(f"LLM returned unparseable output: {raw_result!r}")

            # LLM correctly identified this isn't an agent
            if not parsed.get("is_agent"):
                print(f"⏭️  Not an agent — skipping: {target_url}")
                return {
                    "status": STATUS_NOT_AGENT,
                    "url": target_url,
                    "data": None,
                    "reason": "LLM classified site as non-agent",
                }

            # Validate structure before accepting
            if not _validate_agent_result(parsed):
                raise ValueError(f"LLM result missing required keys: {parsed}")

            # Strip internal key before returning
            parsed.pop("is_agent", None)

            print(f"✅ Extracted: {parsed['name']}")
            return {
                "status": STATUS_SUCCESS,
                "url": target_url,
                "data": parsed,
                "reason": None,
            }

        except Exception as e:
            last_error = str(e)
            print(f"⚠️  Attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)  # Exponential backoff: 2s, 4s

    print(f"❌ All attempts failed for: {target_url}")
    return {
        "status": STATUS_FAILED,
        "url": target_url,
        "data": None,
        "reason": last_error,
    }


if __name__ == "__main__":
    if not LLM_API_KEY:
        print("❌ CRITICAL: LLM_API_KEY is missing from environment!")
    else:
        result = extract_agent_data("https://www.anthropic.com", verbose=True)
        print(json.dumps(result, indent=2))
