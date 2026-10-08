"""Real, callable agents: remote MCP servers from the official MCP Registry, probed over the protocol itself.

Until October 2026 the directory was filled by a web crawler that found sites publishing an `llms.txt`;
none of the 75 entries it collected declared an endpoint another agent could call. This module takes the
other route: the official registry (registry.modelcontextprotocol.io) lists servers together with their
remote endpoints, and each endpoint is checked by speaking MCP to it:

  1. `initialize` (JSON-RPC over streamable HTTP, or the older SSE transport is only recorded, not probed),
  2. `notifications/initialized`, then `tools/list`,

recording latency, the protocol version and server name it reports, how many tools it exposes, and whether
it requires authentication (HTTP 401/403 is a valid, honest answer: the server exists and is protected).

Nothing here calls a tool; listing tools is read-only by the MCP specification.
"""
from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlparse

import requests

REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
PROTOCOL_VERSION = "2025-06-18"
CLIENT = {"name": "agentic-yellow-pages", "version": "2.0"}
USER_AGENT = "AgenticYellowPages/2.0 (+https://agenticyellowpage.com)"


def fetch_registry(max_pages: int = 200, page_size: int = 100) -> list[dict[str, Any]]:
    """Latest version of every active server that declares at least one remote endpoint."""
    servers: dict[str, dict[str, Any]] = {}
    cursor = None
    for _ in range(max_pages):
        params = {"limit": page_size}
        if cursor:
            params["cursor"] = cursor
        res = requests.get(REGISTRY, params=params, timeout=30, headers={"User-Agent": USER_AGENT})
        res.raise_for_status()
        data = res.json()
        for item in data.get("servers", []):
            server = item.get("server") or {}
            meta = (item.get("_meta") or {}).get("io.modelcontextprotocol.registry/official") or {}
            if meta.get("status", "active") != "active" or not meta.get("isLatest", True):
                continue
            remotes = [r for r in server.get("remotes") or [] if isinstance(r, dict) and str(r.get("url", "")).startswith("https://")]
            if remotes:
                servers[server["name"]] = {"server": server, "remotes": remotes, "updated_at": meta.get("updatedAt")}
        cursor = (data.get("metadata") or {}).get("nextCursor")
        if not cursor:
            break
    return list(servers.values())


def _read_jsonrpc(res: requests.Response, want_id: int) -> dict[str, Any] | None:
    """A JSON-RPC response from either a plain JSON body or a text/event-stream body."""
    ctype = res.headers.get("Content-Type", "")
    if "text/event-stream" in ctype:
        for line in res.text.splitlines():
            if line.startswith("data:"):
                try:
                    msg = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict) and msg.get("id") == want_id:
                    return msg
        return None
    try:
        msg = res.json()
    except ValueError:
        return None
    return msg if isinstance(msg, dict) else None


def probe_mcp(url: str, timeout: float = 15.0) -> dict[str, Any]:
    """Speak MCP to a streamable-HTTP endpoint. Returns a result dict; never raises."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": USER_AGENT,
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }
    out: dict[str, Any] = {"url": url, "reachable": False, "auth_required": False, "mcp_ok": False,
                           "latency_ms": None, "protocol_version": None, "server_info": None,
                           "tools": None, "error": None}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT}}
    try:
        t0 = time.monotonic()
        res = requests.post(url, json=init, headers=headers, timeout=timeout)
        out["latency_ms"] = round((time.monotonic() - t0) * 1000)
        out["reachable"] = True
        if res.status_code in (401, 403):
            out["auth_required"] = True
            out["error"] = f"HTTP {res.status_code}: authentication required"
            return out
        if res.status_code >= 400:
            out["error"] = f"HTTP {res.status_code}"
            return out
        msg = _read_jsonrpc(res, 1)
        if not msg or "result" not in msg:
            out["error"] = "no JSON-RPC result to initialize" if not msg else f"error: {msg.get('error')}"
            return out
        result = msg["result"] or {}
        out["mcp_ok"] = True
        out["protocol_version"] = result.get("protocolVersion")
        info = result.get("serverInfo") or {}
        out["server_info"] = {"name": info.get("name"), "version": info.get("version")}

        session = res.headers.get("Mcp-Session-Id")
        if session:
            headers["Mcp-Session-Id"] = session
        if out["protocol_version"]:
            headers["MCP-Protocol-Version"] = out["protocol_version"]
        requests.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                      headers=headers, timeout=timeout)
        res = requests.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                            headers=headers, timeout=timeout)
        if res.status_code in (401, 403):
            out["auth_required"] = True
        else:
            msg = _read_jsonrpc(res, 2)
            tools = ((msg or {}).get("result") or {}).get("tools")
            if isinstance(tools, list):
                out["tools"] = [t.get("name") for t in tools if isinstance(t, dict)][:50]
    except requests.exceptions.Timeout:
        out["error"] = "timeout"
    except requests.RequestException as exc:
        out["error"] = type(exc).__name__
    return out


def to_directory_row(entry: dict[str, Any], probe: dict[str, Any] | None) -> dict[str, Any]:
    """A row for the `agents` table. `domain` is the endpoint without the scheme (unique per endpoint)."""
    server = entry["server"]
    remote = entry["remotes"][0]
    parsed = urlparse(remote["url"])
    endpoint_key = (parsed.netloc + parsed.path).rstrip("/")
    tags = ["mcp-server", remote.get("type", "remote")]
    if probe and probe.get("auth_required"):
        tags.append("auth-required")
    elif probe and probe.get("mcp_ok"):
        tags.append("open")
    return {
        "domain": endpoint_key,
        "name": server.get("title") or server.get("name"),
        "description": server.get("description") or "",
        "tags": tags,
        "raw_card": {
            "source": "registry.modelcontextprotocol.io",
            "registry_name": server.get("name"),
            "version": server.get("version"),
            "url": remote["url"],
            "transport": remote.get("type"),
            "remotes": entry["remotes"],
            "repository": (server.get("repository") or {}).get("url"),
            "website": server.get("websiteUrl"),
            "probe": probe,
        },
        "status": "online" if probe and probe.get("reachable") else ("offline" if probe else "unknown"),
        "response_time_ms": (probe or {}).get("latency_ms") or 0,
    }
