"""Fill the directory with remote MCP servers from the official registry, each probed over MCP.

Runs on GitHub Actions (see .github/workflows/mcp_registry.yml) with SUPABASE_URL and SUPABASE_KEY from the
repository secrets. Rows are upserted by `domain` (the endpoint without its scheme), so a daily run refreshes
status, latency, tools and score instead of adding duplicates.

PROTOCOL SCORE (0-100), stored in trust_score, measures one thing: can another agent connect and use it now?
  reachable over HTTPS ............... 20
  answers `initialize` as MCP ........ 40
  answers `tools/list` with tools .... 20
  latency of `initialize` ............ 20 under 0.5 s, 10 under 1.5 s, 0 above
Servers that answer 401/403 are real and protected: they are listed with the tag `auth-required` and no score,
because nothing can be measured without credentials. It is not a security or quality rating; the LLM-judged
"trust oracle" (benchmark.py) can run on top of the servers that are open.
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv

import mcp_registry as M

load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip(' "\'')
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip(' "\'')
if SUPABASE_URL and not SUPABASE_URL.startswith("http"):
    SUPABASE_URL = f"https://{SUPABASE_URL}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("ingest_mcp")


def protocol_score(probe: dict[str, Any]) -> int | None:
    if probe.get("auth_required"):
        return None
    score = 0
    if probe.get("reachable"):
        score += 20
    if probe.get("mcp_ok"):
        score += 40
        if probe.get("tools"):
            score += 20
        latency = probe.get("latency_ms") or 10**9
        score += 20 if latency < 500 else 10 if latency < 1500 else 0
    return score


def upsert(rows: list[dict[str, Any]]) -> None:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    for i in range(0, len(rows), 100):
        chunk = rows[i:i + 100]
        res = requests.post(f"{SUPABASE_URL}/rest/v1/agents?on_conflict=domain", headers=headers, json=chunk, timeout=60)
        if res.status_code >= 300:
            log.error("Upsert failed (%s): %s", res.status_code, res.text[:300])
            res.raise_for_status()
        log.info("Upserted %d rows", len(chunk))


def main() -> None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY are required")
    entries = M.fetch_registry()
    log.info("Registry: %d active servers with an HTTPS remote", len(entries))
    probe_targets = [e for e in entries if e["remotes"][0].get("type") == "streamable-http"]

    with cf.ThreadPoolExecutor(max_workers=32) as ex:
        probes = dict(zip((id(e) for e in probe_targets),
                          ex.map(lambda e: M.probe_mcp(e["remotes"][0]["url"]), probe_targets)))

    now = datetime.now(timezone.utc).isoformat()
    rows, counts = {}, {"open": 0, "auth": 0, "failed": 0, "not_probed": 0}
    for entry in entries:
        probe = probes.get(id(entry))
        row = M.to_directory_row(entry, probe)
        row["last_scraped_at"] = now
        # PostgREST bulk upserts need the same keys in every row
        row["last_tested_at"] = None
        row["audit_log"] = None
        if probe is None:
            counts["not_probed"] += 1
            row["trust_score"] = None
        else:
            row["trust_score"] = protocol_score(probe)
            row["last_tested_at"] = now
            row["audit_log"] = {"kind": "mcp-protocol-probe", "timestamp_utc": now, "probe": probe,
                                "score_rule": "reachable 20 + initialize 40 + tools 20 + latency 20"}
            counts["auth" if probe.get("auth_required") else "open" if probe.get("mcp_ok") else "failed"] += 1
        rows[row["domain"]] = row          # one row per endpoint, even if two registry names share it
    log.info("Probe results: %s", counts)
    upsert(list(rows.values()))


if __name__ == "__main__":
    main()
