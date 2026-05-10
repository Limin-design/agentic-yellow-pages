import requests
import os
import json
import time
import re
import logging
import concurrent.futures
from urllib.parse import urlparse
from dotenv import load_dotenv
import tweepy

from deep_hunter import extract_agent_data, STATUS_SUCCESS, STATUS_NOT_AGENT, STATUS_FAILED
from utils import clean_x_handle

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
SUPABASE_URL    = os.environ.get("SUPABASE_URL", "").strip(' "\'')
SUPABASE_KEY    = os.environ.get("SUPABASE_KEY", "").strip(' "\'')
SERPER_API_KEY  = os.environ.get("SERPER_API_KEY", "").strip(' "\'')
X_API_KEY       = os.environ.get("X_API_KEY", "").strip(' "\'')
X_API_SECRET    = os.environ.get("X_API_SECRET", "").strip(' "\'')
X_ACCESS_TOKEN  = os.environ.get("X_ACCESS_TOKEN", "").strip(' "\'')
X_ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET", "").strip(' "\'')

if SUPABASE_URL and not SUPABASE_URL.startswith("http"):
    SUPABASE_URL = f"https://{SUPABASE_URL}"

# Domains that commonly appear in search snippets but are never agents
DOMAIN_BLOCKLIST = {
    "github.com", "google.com", "youtube.com", "twitter.com", "x.com",
    "linkedin.com", "reddit.com", "stackoverflow.com", "medium.com",
    "npmjs.com", "pypi.org", "docs.python.org", "wikipedia.org",
}

TWEET_MAX_LENGTH = 280

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Supabase helpers ──────────────────────────────────────────────────────────
def _supabase_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def _supabase_fetch_all(endpoint: str) -> list:
    """
    Generic paginated fetch from any Supabase table endpoint.
    Returns a flat list of all rows across all pages.
    """
    rows = []
    page_size = 1000
    offset = 0

    while True:
        headers = {**_supabase_headers(), "Range": f"{offset}-{offset + page_size - 1}"}
        try:
            res = requests.get(
                f"{SUPABASE_URL}/{endpoint}",
                headers=headers,
                timeout=10,
            )
            if res.status_code not in (200, 206):
                log.warning(f"Supabase fetch error on {endpoint}: {res.status_code} {res.text}")
                break
            batch = res.json()
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < page_size:
                break  # Last page
            offset += page_size
        except Exception as e:
            log.warning(f"Supabase pagination error on {endpoint} at offset {offset}: {e}")
            break

    return rows


def get_known_domains() -> set:
    """Returns all domains already indexed in the agents table."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return set()
    rows = _supabase_fetch_all("rest/v1/agents?select=domain")
    known = {row["domain"] for row in rows}
    log.info(f"Loaded {len(known)} known domains from Supabase.")
    return known


def get_blocklist() -> set:
    """Returns all domains permanently rejected by the LLM."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return set()
    rows = _supabase_fetch_all("rest/v1/blocklist?select=domain")
    blocked = {row["domain"] for row in rows}
    log.info(f"Loaded {len(blocked)} blocked domains from Supabase.")
    return blocked


def save_agent(domain: str, name: str, description: str, tags: list, raw_card: dict) -> bool:
    """Saves a single agent to Supabase. Returns True on success."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        log.warning(f"DB not configured — skipping save for {domain}")
        return False

    payload = {
        "domain": domain,
        "name": name,
        "description": description,
        "tags": tags,
        "raw_card": raw_card,
    }
    try:
        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/agents",
            headers=_supabase_headers(),
            json=payload,
            timeout=10,
        )
        res.raise_for_status()
        log.info(f"✅ Saved to DB: {domain}")
        return True
    except requests.HTTPError as e:
        log.error(f"DB save failed for {domain}: {e} — {res.text}")
        return False
    except Exception as e:
        log.error(f"DB save failed for {domain}: {e}")
        return False


def save_to_blocklist(domain: str) -> None:
    """Permanently blocks a domain from future crawls."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    try:
        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/blocklist",
            headers=_supabase_headers(),
            json={"domain": domain, "reason": "llm_rejected"},
            timeout=10,
        )
        res.raise_for_status()
        log.info(f"🚫 Blocklisted: {domain}")
    except Exception as e:
        log.error(f"Failed to blocklist {domain}: {e}")


# ── X (Twitter) ───────────────────────────────────────────────────────────────
def announce_on_x(name: str, domain: str, tags: list, x_handle: str | None = None) -> bool:
    """Posts a discovery tweet. Returns True on success."""
    if not all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET]):
        log.warning("X API keys missing — skipping tweet.")
        return False
    try:
        client = tweepy.Client(
            consumer_key=X_API_KEY,
            consumer_secret=X_API_SECRET,
            access_token=X_ACCESS_TOKEN,
            access_token_secret=X_ACCESS_SECRET,
        )

        clean_handle = clean_x_handle(x_handle)
        name_line    = f"🤖 {name} ({clean_handle})" if clean_handle else f"🤖 {name}"
        tag_str      = ", ".join(tags[:3]) if tags else "autonomous node"

        tweet = (
            f"🚨 New Agent Discovered! 🚨\n\n"
            f"{name_line}\n"
            f"⚙️ Skills: {tag_str}\n\n"
            f"We just indexed this endpoint on the A2A Registry:\n"
            f"🌐 www.agenticyellowpage.com\n\n"
            f"#AI #Agents #MCP"
        )

        # Truncate name_line if tweet is too long, preserving the rest of the template
        if len(tweet) > TWEET_MAX_LENGTH:
            overflow  = len(tweet) - TWEET_MAX_LENGTH + 3  # +3 for "..."
            name_line = name_line[:-overflow] + "..."
            tweet = (
                f"🚨 New Agent Discovered! 🚨\n\n"
                f"{name_line}\n"
                f"⚙️ Skills: {tag_str}\n\n"
                f"We just indexed this endpoint on the A2A Registry:\n"
                f"🌐 www.agenticyellowpage.com\n\n"
                f"#AI #Agents #MCP"
            )

        client.create_tweet(text=tweet[:TWEET_MAX_LENGTH])
        log.info(f"🐦 Tweeted about {name}")
        return True

    except Exception as e:
        log.error(f"Tweet failed for {domain}: {e}")
        return False


# ── Discovery ─────────────────────────────────────────────────────────────────
def _is_valid_domain(domain: str, excluded: set) -> bool:
    """
    Returns True only if the domain is not in the combined excluded set
    (known agents + blocklist + static blocklist) and looks well-formed.
    """
    if not domain or "." not in domain:
        return False
    if domain in excluded:
        return False
    if any(domain == b or domain.endswith(f".{b}") for b in DOMAIN_BLOCKLIST):
        return False
    return True


def discover_new_targets(excluded_domains: set) -> list:
    """
    Searches for new agent domains via Serper.
    excluded_domains should be known_domains | blocklist merged together.
    """
    if not SERPER_API_KEY:
        log.warning("SERPER_API_KEY missing — skipping discovery.")
        return []

    log.info("🚀 Launching wide hunt...")
    queries = [
        'site:github.io "agent-card.json" OR "ai-plugin.json"',
        '"llms.txt" "AI agent" OR "LLM"',
        '"mcpServers" "version"',
        'site:x.com "my new MCP server" OR "my agent endpoint"',
    ]
    found   = set()
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}

    for query in queries:
        log.info(f"  Querying: {query}")
        for page in range(1, 3):
            try:
                res = requests.post(
                    "https://google.serper.dev/search",
                    headers=headers,
                    json={"q": query, "page": page},
                    timeout=10,
                )
                res.raise_for_status()
                for result in res.json().get("organic", []):
                    # Primary result URL
                    link   = result.get("link", "")
                    domain = urlparse(link).netloc.removeprefix("www.")
                    if _is_valid_domain(domain, excluded_domains):
                        found.add(domain)

                    # Snippet URLs — only well-formed https:// links
                    for url in re.findall(r'https://[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', result.get("snippet", "")):
                        d = urlparse(url).netloc.removeprefix("www.")
                        if _is_valid_domain(d, excluded_domains):
                            found.add(d)

            except Exception as e:
                log.warning(f"Serper error (page {page}): {e}")

            time.sleep(1)

    log.info(f"Discovery complete — {len(found)} new domains found.")
    return list(found)


# ── Phase 1: Fast Protocol Scan ───────────────────────────────────────────────
PROTOCOL_DOORS = [
    "/.well-known/agent-card.json",
    "/llms.txt",
    "/.well-known/ai-plugin.json",
]


def process_single_domain_fast(domain: str) -> dict:
    """
    Tries standard protocol endpoints for a domain.

    Returns:
        {
            "domain":  str,
            "success": bool,
            "data":    dict | None,
            "error":   str | None
        }
    """
    base = f"https://{domain}"
    for path in PROTOCOL_DOORS:
        url = base + path
        try:
            res   = requests.get(url, timeout=5, allow_redirects=True)
            ctype = res.headers.get("Content-Type", "").lower()

            if res.status_code == 200 and "text/html" not in ctype:
                if path.endswith(".json"):
                    data = res.json()
                else:
                    data = {
                        "name":        f"Agent Node at {domain}",
                        "description": "Supports llms.txt protocol.",
                        "tags":        ["llms-txt"],
                    }

                if not data.get("name"):
                    data["name"] = f"Agent Node at {domain}"

                return {"domain": domain, "success": True, "data": data, "error": None}

        except requests.RequestException:
            continue

    return {"domain": domain, "success": False, "data": None, "error": "No protocol door responded"}


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("🚀 Starting Turbo Hunter with LLM Deep Scan + Blocklist...")

    # Load both exclusion sets and merge them before passing to discovery —
    # this is the key step that prevents wasting SERP credits on known noise.
    known_domains = get_known_domains()
    blocklist     = get_blocklist()
    excluded      = known_domains | blocklist

    new_targets = discover_new_targets(excluded)

    if not new_targets:
        log.info("No new targets this run.")
        return

    log.info(f"✅ {len(new_targets)} new domains to process.")
    failed_domains = []

    # ── Phase 1: Concurrent fast protocol scan ────────────────────────────────
    log.info(f"⚡ Phase 1: Fast scanning {len(new_targets)} domains...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_single_domain_fast, d): d for d in new_targets}

        for future in concurrent.futures.as_completed(futures):
            domain = futures[future]
            try:
                result = future.result()
            except Exception as e:
                # Thread crashed unexpectedly — send to Phase 2 for LLM attempt
                log.warning(f"Thread crashed for {domain}: {e}")
                failed_domains.append(domain)
                continue

            if result["success"]:
                data     = result["data"]
                x_handle = data.get("x_handle") or data.get("twitter") or data.get("x")
                saved    = save_agent(
                    domain,
                    data.get("name", "Unknown"),
                    data.get("description", ""),
                    data.get("tags", []),
                    data,
                )
                if saved:
                    announce_on_x(data["name"], domain, data.get("tags", []), x_handle)
            else:
                failed_domains.append(domain)

    # ── Phase 2: LLM deep scan on Phase 1 failures ───────────────────────────
    if failed_domains:
        log.info(f"🕵️  Phase 2: LLM deep scanning {len(failed_domains)} domains...")

        for domain in failed_domains:
            target_url = f"https://{domain}"
            llm_result = extract_agent_data(target_url)  # {status, url, data, reason}

            if llm_result["status"] == STATUS_SUCCESS:
                data     = llm_result["data"]
                x_handle = clean_x_handle(data.get("x_handle"))
                saved    = save_agent(
                    domain,
                    data["name"],
                    data["description"],
                    data["tags"],
                    data,
                )
                if saved:
                    announce_on_x(data["name"], domain, data["tags"], x_handle)

            elif llm_result["status"] == STATUS_NOT_AGENT:
                # LLM was confident this isn't an agent — persist immediately
                # so future runs skip it before spending a SERP credit.
                log.info(f"  ⏭️  Not an agent, blocklisting: {domain}")
                save_to_blocklist(domain)

            else:  # STATUS_FAILED — transient error, do not blocklist, may succeed next run
                log.warning(f"  ❌ Deep scan failed: {domain} — {llm_result['reason']}")

            time.sleep(8)  # Respect Groq free-tier rate limits

    log.info("🏁 Run complete.")


if __name__ == "__main__":
    main()
