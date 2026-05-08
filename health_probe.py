"""
A2A Health Probe — V2.0
Fixes over V1:
  - Bug: fallback heartbeat marked parked domains / Cloudflare splashes as ONLINE
  - Bug: unbounded redirects (allow_redirects=True, no max) — ad chains faked ONLINE
  - Bug: Supabase no pagination → silent 1000-row truncation
  - Bug: malformed User-Agent string (token appended without separator)
  - Design: three-tier status (a2a_verified / alive / offline) instead of binary
  - Design: flap detection — requires consecutive_failures threshold before going OFFLINE
  - Design: concurrent probing via ThreadPoolExecutor (was fully serial + sleep)
  - Design: response_time_ms captured and stored in DB
  - Design: last_checked_at timestamp stored on every probe
  - Design: retry (with backoff) on transient network errors before recording failure
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# BOOTSTRAP
# ---------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger("health_probe")

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "").strip(" \"'")
if SUPABASE_URL and not SUPABASE_URL.startswith("http"):
    SUPABASE_URL = f"https://{SUPABASE_URL}"
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "").strip(" \"'")

DB_HEADERS: dict[str, str] = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

# Probe settings
PROBE_TIMEOUT_S      = 6
FALLBACK_TIMEOUT_S   = 7
MAX_REDIRECTS        = 3          # cap redirect chains; prevents ad-network spoofing
RETRY_ATTEMPTS       = 2          # retries on transient errors before recording failure
RETRY_BACKOFF_S      = 1.0
OFFLINE_THRESHOLD    = 2          # consecutive failures needed to flip to 'offline'
MAX_WORKERS          = 12         # concurrent probe threads
SUPABASE_PAGE_SIZE   = 500

# A clean, honest UA that identifies the probe without faking a browser
PROBE_UA = "A2A-HealthProbe/2.0 (+https://agenticyellowpage.com/probe)"

# Status tier values stored in DB
Status = Literal["a2a_verified", "alive", "offline"]

# Parked-domain / Cloudflare-challenge signatures to reject even on 200
_PARKED_SIGNATURES = [
    "this domain is for sale",
    "buy this domain",
    "godaddy",
    "parking page",
    "checking your browser",
    "just a moment",         # Cloudflare challenge
    "enable javascript",
    "domain is parked",
    "coming soon",
]

# A2A discovery file candidates in priority order
_A2A_DOORS = [
    (".well-known/agent-card.json", "json"),
    ("llms.txt",                    "text"),
    (".well-known/ai-plugin.json",  "json"),
]


# ---------------------------------------------------------------------------
# CORE PROBE LOGIC
# ---------------------------------------------------------------------------
@dataclass
class ProbeResult:
    status:          Status
    response_time_ms: int
    detail:          str          # human-readable reason


def _get(url: str, timeout: float) -> requests.Response:
    """GET with bounded redirects, honest UA, and no cookie jar leakage."""
    return requests.get(
        url,
        headers={"User-Agent": PROBE_UA},
        timeout=timeout,
        allow_redirects=True,
        max_redirects=MAX_REDIRECTS,
    )


def _is_parked_page(response: requests.Response) -> bool:
    """Returns True if the response body looks like a parked/splash page."""
    try:
        body = response.text[:2000].lower()
        return any(sig in body for sig in _PARKED_SIGNATURES)
    except Exception:
        return False


def _try_a2a_doors(base_url: str) -> ProbeResult | None:
    """
    Attempt each A2A discovery endpoint.
    Returns a ProbeResult on first verified hit, or None if all miss.
    """
    for path, kind in _A2A_DOORS:
        url = f"{base_url}/{path}"
        for attempt in range(RETRY_ATTEMPTS):
            try:
                t0 = time.monotonic()
                res = _get(url, PROBE_TIMEOUT_S)
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                content_type = res.headers.get("Content-Type", "").lower()

                if res.status_code != 200:
                    break   # don't retry non-200; try next door

                # Reject HTML responses on A2A endpoints (caught redirect to homepage)
                if "text/html" in content_type:
                    break

                if kind == "json":
                    try:
                        res.json()
                        return ProbeResult("a2a_verified", elapsed_ms, f"Valid JSON at {path}")
                    except ValueError:
                        break   # malformed JSON; try next door
                else:
                    # llms.txt — valid if non-empty and not HTML
                    if res.text.strip():
                        return ProbeResult("a2a_verified", elapsed_ms, f"Content at {path}")
                    break

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt < RETRY_ATTEMPTS - 1:
                    time.sleep(RETRY_BACKOFF_S)
                continue
            except requests.exceptions.TooManyRedirects:
                break   # redirect chain → definitely not a clean A2A endpoint
            except Exception:
                break

    return None


def _try_fallback_heartbeat(base_url: str) -> ProbeResult | None:
    """
    Conservative fallback: server is 'alive' only if it returns a genuine 
    non-parked 2xx/3xx/4xx response. 5xx and parked pages = offline.
    """
    for attempt in range(RETRY_ATTEMPTS):
        try:
            t0 = time.monotonic()
            res = _get(base_url, FALLBACK_TIMEOUT_S)
            elapsed_ms = int((time.monotonic() - t0) * 1000)

            # 5xx = server is broken
            if res.status_code >= 500:
                return None

            # Reject parked domains even if they return 200
            if _is_parked_page(res):
                return None

            # Anything else: server is genuinely up
            return ProbeResult("alive", elapsed_ms, f"Heartbeat {res.status_code}")

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF_S)
            continue
        except requests.exceptions.TooManyRedirects:
            return None
        except Exception:
            return None

    return None


def check_health(domain: str) -> ProbeResult:
    """
    Three-tier probe:
      a2a_verified — has a valid agent-card.json, llms.txt, or ai-plugin.json
      alive        — server responds but no A2A discovery files found
      offline      — DNS failure, timeout, 5xx, or parked domain
    """
    base_url = f"https://{domain}"

    # Tier 1: A2A discovery files
    result = _try_a2a_doors(base_url)
    if result:
        return result

    # Tier 2: conservative heartbeat
    result = _try_fallback_heartbeat(base_url)
    if result:
        return result

    return ProbeResult("offline", 0, "No response or parked domain")


# ---------------------------------------------------------------------------
# SUPABASE HELPERS
# ---------------------------------------------------------------------------
def fetch_all_agents() -> list[dict]:
    """Paginated fetch to avoid the silent 1000-row truncation."""
    agents: list[dict] = []
    offset = 0

    while True:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/agents",
            headers={**DB_HEADERS, "Range": f"{offset}-{offset + SUPABASE_PAGE_SIZE - 1}"},
            params={"select": "id,domain,status,consecutive_failures"},
        )
        if res.status_code not in (200, 206):
            log.error("Supabase fetch error: %s %s", res.status_code, res.text)
            break

        batch = res.json()
        agents.extend(batch)
        if len(batch) < SUPABASE_PAGE_SIZE:
            break
        offset += SUPABASE_PAGE_SIZE

    return agents


def push_status(agent_id: str, new_status: Status, result: ProbeResult, consecutive_failures: int) -> None:
    payload = {
        "status":               new_status,
        "response_time_ms":     result.response_time_ms,
        "last_checked_at":      datetime.now(timezone.utc).isoformat(),
        "consecutive_failures": consecutive_failures,
    }
    try:
        res = requests.patch(
            f"{SUPABASE_URL}/rest/v1/agents",
            headers=DB_HEADERS,
            params={"id": f"eq.{agent_id}"},
            json=payload,
        )
        if res.status_code not in (200, 204):
            log.warning("DB PATCH returned %s for agent %s", res.status_code, agent_id)
    except Exception as exc:
        log.error("Failed to update agent %s: %s", agent_id, exc)


# ---------------------------------------------------------------------------
# PROBE WORKER (called concurrently)
# ---------------------------------------------------------------------------
def probe_agent(agent: dict) -> dict:
    """Runs the full probe for one agent and returns a result dict."""
    domain   = agent.get("domain", "")
    agent_id = agent.get("id")
    old_status         = agent.get("status", "online")
    consecutive_fails  = agent.get("consecutive_failures") or 0

    result = check_health(domain)

    # --- Flap detection ---
    # Don't flip to 'offline' on first failure; require OFFLINE_THRESHOLD consecutive ones.
    if result.status == "offline":
        consecutive_fails += 1
        if consecutive_fails < OFFLINE_THRESHOLD:
            # Not enough consecutive failures yet; keep current status in DB
            log.info(
                "  ~ %-40s  transient failure (%d/%d), holding status",
                domain, consecutive_fails, OFFLINE_THRESHOLD,
            )
            push_status(agent_id, old_status, result, consecutive_fails)
            return {"domain": domain, "final_status": old_status, "held": True}
        new_status = "offline"
    else:
        consecutive_fails = 0   # reset on any non-offline result
        new_status = result.status

    status_emoji = {"a2a_verified": "✅", "alive": "🟡", "offline": "❌"}.get(new_status, "❓")
    changed = new_status != old_status

    log.info(
        "  %s %-40s  %s → %s  (%dms)%s",
        status_emoji, domain, old_status, new_status, result.response_time_ms,
        "  [CHANGED]" if changed else "",
    )

    push_status(agent_id, new_status, result, consecutive_fails)
    return {"domain": domain, "final_status": new_status, "changed": changed}


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def run_health_probe() -> None:
    log.info("🩺  Starting A2A Health Probe V2.0")

    if not SUPABASE_URL or not SUPABASE_KEY:
        log.error("Missing SUPABASE_URL or SUPABASE_KEY.")
        return

    agents = fetch_all_agents()
    log.info("📡  Loaded %d agents. Probing with %d workers...", len(agents), MAX_WORKERS)

    counts: dict[str, int] = {"a2a_verified": 0, "alive": 0, "offline": 0, "held": 0}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(probe_agent, a): a for a in agents}
        for future in as_completed(futures):
            try:
                res = future.result()
                if res.get("held"):
                    counts["held"] += 1
                else:
                    counts[res["final_status"]] = counts.get(res["final_status"], 0) + 1
            except Exception as exc:
                log.error("Worker error: %s", exc)

    log.info(
        "\n✅  Probe complete.\n"
        "    A2A Verified : %d\n"
        "    Alive (no A2A): %d\n"
        "    Offline      : %d\n"
        "    Held (flap)  : %d",
        counts["a2a_verified"], counts["alive"], counts["offline"], counts["held"],
    )


if __name__ == "__main__":
    run_health_probe()
